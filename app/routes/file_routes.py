# app/routes/file_routes.py
import os
import uuid
import shutil
import zipfile
import mimetypes
import codecs
import json
import tempfile
import py7zr

from flask import (
    Blueprint, render_template, redirect, url_for, flash, request,
    session, jsonify, current_app, abort, send_from_directory, make_response, send_file
)
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename
from werkzeug.security import check_password_hash, generate_password_hash # For public file passwords

# Import from app package
from app import db, csrf
from app.utils import get_user_upload_path # Import directly
from app.models import File, Folder, User, Setting, GroupChatMessage, DirectMessage # Models
from app.forms import UploadFileForm, CreateFolderForm, EditFileForm # Forms
from app.utils import ( # Utility functions
    get_user_storage_info, is_file_editable, allowed_file,
    check_name_conflict, copy_file_record, copy_folder_recursive, delete_folder_recursive,
    get_archive_uncompressed_size, add_folder_to_zip, register_extracted_items
)
from app.config import ( # Config constants
    DEFAULT_MAX_UPLOAD_MB_FALLBACK,
    VIDEO_THUMBNAIL_FOLDER # For thumbnail generation during upload
)
import subprocess # For video thumbnail generation

# Define the blueprint
bp = Blueprint('file_routes', __name__, url_prefix='/files')


@bp.route('/', defaults={'folder_id': None}, methods=['GET'])
@bp.route('/folder/<int:folder_id>', methods=['GET'])
@login_required
def list_files(folder_id):
    upload_form = UploadFileForm()
    create_folder_form = CreateFolderForm()
    current_folder = None
    parent_folder = None

    if folder_id:
        current_folder = Folder.query.filter_by(id=folder_id, user_id=current_user.id).first_or_404()
        parent_folder = current_folder.parent
        subfolders = current_folder.children.filter(Folder.user_id == current_user.id).order_by(Folder.name).all()
        files = current_folder.files_in_folder.filter(File.user_id == current_user.id).order_by(File.original_filename).all()
    else:
        subfolders = Folder.query.filter_by(user_id=current_user.id, parent_folder_id=None).order_by(Folder.name).all()
        files = File.query.filter_by(user_id=current_user.id, parent_folder_id=None).order_by(File.original_filename).all()

    for file_record in files:
        file_record.is_editable = is_file_editable(file_record.original_filename, file_record.mime_type)

    storage_info = get_user_storage_info(current_user)
    usage_mb = round(storage_info['usage_bytes'] / (1024 * 1024), 2)
    limit_display = f"{storage_info['limit_mb']} MB" if storage_info['limit_mb'] is not None else "Unlimited"
    limit_type_indicator = f"({storage_info['limit_type'].capitalize()})" if storage_info['limit_type'] != 'user' else ""


    breadcrumbs = []
    temp_folder = current_folder
    while temp_folder:
        breadcrumbs.append({'id': temp_folder.id, 'name': temp_folder.name})
        temp_folder = temp_folder.parent
    breadcrumbs.reverse()

    clipboard_session_data = session.get('clipboard', None)
    clipboard_json = json.dumps(clipboard_session_data) if clipboard_session_data else 'null'

    try:
        global_max_upload_mb_str = Setting.get('max_upload_size_mb', str(DEFAULT_MAX_UPLOAD_MB_FALLBACK))
        global_max_upload_mb = int(global_max_upload_mb_str)
    except (ValueError, TypeError):
        global_max_upload_mb = DEFAULT_MAX_UPLOAD_MB_FALLBACK
    effective_display_max_upload_mb = global_max_upload_mb
    if current_user.max_file_size is not None and current_user.max_file_size > 0:
        effective_display_max_upload_mb = current_user.max_file_size
    server_max_content_bytes = current_app.config.get('MAX_CONTENT_LENGTH')
    if server_max_content_bytes:
        server_max_content_mb = server_max_content_bytes // (1024 * 1024)
        if server_max_content_mb < effective_display_max_upload_mb:
            effective_display_max_upload_mb = server_max_content_mb

    # Pass current_folder_id for upload target
    current_folder_id_for_upload = folder_id if folder_id else ''


    return render_template('files/files.html', # Assuming templates in files/ subdirectory
                           title='My Files' + (f' - {current_folder.name}' if current_folder else ''),
                           files=files, subfolders=subfolders, current_folder=current_folder,
                           parent_folder=parent_folder, breadcrumbs=breadcrumbs,
                           usage_mb=usage_mb, limit_display=limit_display,
                           limit_type_indicator=limit_type_indicator,
                           max_upload_mb=effective_display_max_upload_mb,
                           upload_form=upload_form, create_folder_form=create_folder_form,
                           clipboard_json=clipboard_json,
                           current_folder_id_for_upload=current_folder_id_for_upload)


@bp.route('/upload', methods=['POST'])
@login_required
def upload_file_route(): # Renamed to avoid conflict with helper if any
    if 'file' not in request.files:
        if request.accept_mimetypes.accept_json: return jsonify({"status": "error", "message": "No file part."}), 400
        flash('No file part in the request.', 'danger'); return redirect(request.referrer or url_for('.list_files'))

    file_storage = request.files['file']
    if not file_storage or file_storage.filename == '':
        if request.accept_mimetypes.accept_json: return jsonify({"status": "error", "message": "No file selected."}), 400
        flash('No file selected for uploading.', 'warning'); return redirect(request.referrer or url_for('.list_files'))

    # Determine effective limits (copied from original logic)
    user_max_file_size_mb = current_user.max_file_size
    system_default_max_file_size_mb_str = Setting.get('max_upload_size_mb', str(DEFAULT_MAX_UPLOAD_MB_FALLBACK))
    try: system_default_max_file_size_mb = int(system_default_max_file_size_mb_str)
    except: system_default_max_file_size_mb = DEFAULT_MAX_UPLOAD_MB_FALLBACK
    effective_max_file_size_mb = user_max_file_size_mb if user_max_file_size_mb is not None and user_max_file_size_mb > 0 else system_default_max_file_size_mb
    effective_max_file_size_bytes = effective_max_file_size_mb * 1024 * 1024
    global_max_content_bytes = current_app.config.get('MAX_CONTENT_LENGTH')

    filename = secure_filename(file_storage.filename)
    file_storage.seek(0, os.SEEK_END)
    file_size_bytes = file_storage.tell()
    file_storage.seek(0)

    error_msg, status_code = None, 200
    if global_max_content_bytes is not None and file_size_bytes > global_max_content_bytes:
        error_msg = f"File too large. Max request size: {global_max_content_bytes / (1024*1024):.2f} MB."; status_code = 413
    elif file_size_bytes > effective_max_file_size_bytes:
        error_msg = f"File exceeds your max upload size of {effective_max_file_size_mb} MB."; status_code = 413
    else:
        storage_info = get_user_storage_info(current_user)
        available_bytes = storage_info['limit_bytes'] - storage_info['usage_bytes']
        if file_size_bytes > available_bytes:
            error_msg = "Uploading this file would exceed your storage limit."; status_code = 413

    if error_msg:
        if request.accept_mimetypes.accept_json: return jsonify({"status": "error", "message": error_msg}), status_code
        flash(error_msg, "danger"); return redirect(request.referrer or url_for('.list_files'))

    user_upload_folder = get_user_upload_path(current_user.id)
    if not os.path.exists(user_upload_folder): os.makedirs(user_upload_folder, exist_ok=True)

    target_parent_folder_id_str = request.form.get('parent_folder_id') # From hidden input in files.html
    target_parent_folder_id = int(target_parent_folder_id_str) if target_parent_folder_id_str and target_parent_folder_id_str != 'None' else None

    if target_parent_folder_id and not Folder.query.filter_by(id=target_parent_folder_id, user_id=current_user.id).first():
        if request.accept_mimetypes.accept_json: return jsonify({"status": "error", "message": "Target folder not found."}), 400
        flash("Target folder not found.", "danger"); return redirect(request.referrer or url_for('.list_files'))

    original_filename_for_db = filename
    _, ext = os.path.splitext(filename)
    stored_filename_on_disk = str(uuid.uuid4()) + ext
    file_path_on_disk = os.path.join(user_upload_folder, stored_filename_on_disk)

    counter = 1
    temp_original_filename = original_filename_for_db
    while File.query.filter_by(user_id=current_user.id, parent_folder_id=target_parent_folder_id, original_filename=temp_original_filename).first():
        base, extension = os.path.splitext(original_filename_for_db)
        temp_original_filename = f"{base}_{counter}{extension}"; counter += 1
    final_original_filename_for_db = temp_original_filename

    try:
        file_storage.save(file_path_on_disk)
        mime_type, _ = mimetypes.guess_type(file_path_on_disk)
        mime_type = mime_type or 'application/octet-stream'
        new_file = File(
            original_filename=final_original_filename_for_db, stored_filename=stored_filename_on_disk,
            filesize=file_size_bytes, mime_type=mime_type, user_id=current_user.id, parent_folder_id=target_parent_folder_id
        )
        db.session.add(new_file)
        db.session.commit()

        # Video thumbnail generation (ensure VIDEO_THUMBNAIL_FOLDER is in app.config)
        if new_file.mime_type and new_file.mime_type.startswith('video/'):
            thumbnail_filename = f"{new_file.id}.jpg"
            thumb_folder_config = current_app.config.get('VIDEO_THUMBNAIL_FOLDER', VIDEO_THUMBNAIL_FOLDER)
            thumbnail_path = os.path.join(thumb_folder_config, thumbnail_filename)
            os.makedirs(thumb_folder_config, exist_ok=True)
            try:
                ffmpeg_command = ["ffmpeg", "-i", file_path_on_disk, "-ss", "00:00:01", "-vframes", "1", "-q:v", "2", "-vf", "scale='min(320,iw):-1'", thumbnail_path]
                subprocess.run(ffmpeg_command, check=True, capture_output=True, text=True, timeout=60)
            except Exception as e_thumb: current_app.logger.error(f"Thumbnail generation failed for video {new_file.id}: {e_thumb}")

        if request.accept_mimetypes.accept_json:
            return jsonify({"status": "success", "message": f"File '{final_original_filename_for_db}' uploaded!", "file": {"id": new_file.id, "original_filename": new_file.original_filename}}), 201
        flash(f"File '{final_original_filename_for_db}' uploaded successfully!", "success")
        redirect_url = url_for('.list_files', folder_id=target_parent_folder_id) if target_parent_folder_id else url_for('.list_files')
        return redirect(request.referrer or redirect_url)

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error saving uploaded file {final_original_filename_for_db}: {e}", exc_info=True)
        if os.path.exists(file_path_on_disk):
            try:
                os.remove(file_path_on_disk)
                current_app.logger.info(f"Cleaned up partially uploaded file: {file_path_on_disk}")
            except OSError as e_remove: # Catch specific OSError for the remove operation
                current_app.logger.error(f"Failed to remove partially uploaded file {file_path_on_disk} after error: {e_remove}")
        error_msg_commit = f"Error uploading '{final_original_filename_for_db}': {str(e)}" # Use str(e) for a cleaner message
        if request.accept_mimetypes.accept_json:
            return jsonify({"status": "error", "message": error_msg_commit}), 500
        else: # Added else for clarity
            flash(error_msg_commit, "danger")
            # Ensure target_parent_folder_id is defined in this scope for the redirect
            # It should be from earlier in the function.
            return redirect(request.referrer or url_for('.list_files', folder_id=target_parent_folder_id if 'target_parent_folder_id' in locals() else None))



@bp.route('/download/<int:file_id>')
@login_required
def download_file(file_id):
    file_record = File.query.get_or_404(file_id)
    can_access = False
    if file_record.owner == current_user: can_access = True
    else: # Check if shared in group or direct chat involving current user
        if GroupChatMessage.query.filter_by(file_id=file_record.id).first(): can_access = True
        if not can_access:
            dm_association = DirectMessage.query.filter(DirectMessage.file_id == file_record.id, ((DirectMessage.sender_id == current_user.id) | (DirectMessage.receiver_id == current_user.id))).first()
            if dm_association and (file_record.user_id == dm_association.sender_id or file_record.user_id == dm_association.receiver_id):
                can_access = True
    if not can_access: abort(403)

    user_upload_path = get_user_upload_path(file_record.user_id)
    full_file_path = os.path.join(user_upload_path, file_record.stored_filename)
    if not os.path.exists(full_file_path): abort(404)

    try:
        # Zip problematic image types (webp, avif)
        _, file_extension = os.path.splitext(file_record.original_filename)
        if file_extension.lower() in ['.webp', '.avif']:
            with tempfile.TemporaryDirectory() as temp_dir:
                zip_file_path = os.path.join(temp_dir, f"{os.path.splitext(file_record.original_filename)[0]}.zip")
                with zipfile.ZipFile(zip_file_path, 'w', zipfile.ZIP_DEFLATED) as zf:
                    zf.write(full_file_path, arcname=file_record.original_filename)
                response = send_file(zip_file_path, mimetype='application/zip', as_attachment=True, download_name=f"{os.path.splitext(file_record.original_filename)[0]}.zip", conditional=True)
        else:
            mime_type = file_record.mime_type or mimetypes.guess_type(full_file_path)[0] or 'application/octet-stream'
            response = send_file(full_file_path, mimetype=mime_type, as_attachment=True, download_name=file_record.original_filename.replace('"', '\\"'), conditional=True)

        response.headers['X-Content-Type-Options'] = 'nosniff'
        return response
    except Exception as e:
        current_app.logger.error(f"Error downloading file {file_id}: {e}", exc_info=True)
        abort(500)


@bp.route('/view/<int:file_id>')
@login_required
def view_file(file_id): # For inline viewing
    file_record = File.query.get_or_404(file_id)
    can_access = False # Same access logic as download_file
    if file_record.owner == current_user: can_access = True
    else:
        if GroupChatMessage.query.filter_by(file_id=file_record.id).first(): can_access = True
        if not can_access:
            dm_association = DirectMessage.query.filter(DirectMessage.file_id == file_record.id, ((DirectMessage.sender_id == current_user.id) | (DirectMessage.receiver_id == current_user.id))).first()
            if dm_association and (file_record.user_id == dm_association.sender_id or file_record.user_id == dm_association.receiver_id):
                can_access = True
    if not can_access: abort(403)

    user_upload_path = get_user_upload_path(file_record.user_id)
    full_file_path = os.path.join(user_upload_path, file_record.stored_filename)
    if not os.path.exists(full_file_path): abort(404)

    mime_type = file_record.mime_type or 'application/octet-stream'
    try:
        return send_from_directory(user_upload_path, file_record.stored_filename, mimetype=mime_type, as_attachment=False, conditional=True)
    except Exception as e:
        current_app.logger.error(f"Error serving file {file_id} for viewing: {e}", exc_info=True)
        abort(500)


@bp.route('/delete/<int:file_id>', methods=['POST'])
@login_required
def delete_file_route(file_id): # Renamed
    file_record = File.query.get_or_404(file_id)
    if file_record.owner != current_user:
        return jsonify({"status": "error", "message": "Permission denied."}), 403

    original_filename = file_record.original_filename
    user_upload_path = get_user_upload_path(current_user.id)
    full_file_path = os.path.join(user_upload_path, file_record.stored_filename)
    try:
        if os.path.exists(full_file_path): os.remove(full_file_path)
        db.session.delete(file_record)
        db.session.commit()
        return jsonify({"status": "success", "message": f"File '{original_filename}' deleted."})
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error deleting file {file_id}: {e}", exc_info=True)
        return jsonify({"status": "error", "message": f"Error deleting '{original_filename}'."}), 500


@bp.route('/edit/<int:file_id>', methods=['GET', 'POST'])
@login_required
def edit_file_route(file_id): # Renamed in original, keeping consistent
    file_record = File.query.get_or_404(file_id)
    if file_record.owner != current_user:
        abort(403)
    if not is_file_editable(file_record.original_filename, file_record.mime_type):
        flash(f"File '{file_record.original_filename}' is not editable.", 'warning')
        return redirect(url_for('.list_files', folder_id=file_record.parent_folder_id))

    form = EditFileForm()
    user_upload_path = get_user_upload_path(current_user.id)
    file_path = os.path.join(user_upload_path, file_record.stored_filename)

    if not os.path.exists(file_path):
        flash("Error: File not found in storage.", "danger")
        return redirect(url_for('.list_files', folder_id=file_record.parent_folder_id))

    # Get user's preferred CodeMirror theme
    user_cm_theme = current_user.preferred_codemirror_theme if hasattr(current_user, 'preferred_codemirror_theme') and current_user.preferred_codemirror_theme else 'material-darker.css'

    if form.validate_on_submit():
        new_content = form.content.data
        original_size = file_record.filesize
        try:
            with codecs.open(file_path, 'w', encoding='utf-8', errors='replace') as f:
                f.write(new_content)
            new_size = os.path.getsize(file_path)
            size_difference = new_size - original_size

            if size_difference > 0:  # Check storage if file grew
                storage_info = get_user_storage_info(current_user)
                # Ensure limit_bytes and usage_bytes are available and are numbers
                current_usage_bytes = storage_info.get('usage_bytes', 0)
                storage_limit_bytes = storage_info.get('limit_bytes')


                if storage_limit_bytes is not None: # Only check if there's a limit
                    available_bytes = storage_limit_bytes - current_usage_bytes
                    if size_difference > available_bytes:
                        # Attempt to revert content (simplified)
                        with codecs.open(file_path, 'r', encoding='utf-8', errors='replace') as f_orig:
                            original_content_temp = f_orig.read() # Read original content before overwriting
                        with codecs.open(file_path, 'w', encoding='utf-8', errors='replace') as f_revert:
                             f_revert.write(original_content_temp) # Revert
                        os.truncate(file_path, original_size) # Ensure filesize is also reverted

                        flash('Save failed: Editing this file would exceed your storage limit.', 'danger')
                        form.content.data = original_content_temp  # Show reverted content in form
                        return render_template('files/edit.html', # Rerender with error and old content
                                               form=form,
                                               file_id=file_id,
                                               original_filename=file_record.original_filename,
                                               stored_filename=file_record.stored_filename, # Pass stored_filename
                                               parent_folder_id=file_record.parent_folder_id,
                                               user_codemirror_theme=user_cm_theme) # Pass theme

            file_record.filesize = new_size
            db.session.commit()
            flash(f"File '{file_record.original_filename}' saved.", 'success')
            return redirect(url_for('.list_files', folder_id=file_record.parent_folder_id))
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error saving edited file {file_id}: {e}", exc_info=True)
            flash("Error saving file.", 'danger')
            # If save fails, try to repopulate form with attempted content or original content
            form.content.data = new_content # Keep attempted changes in form on error
    elif request.method == 'GET':
        try:
            with codecs.open(file_path, 'r', encoding='utf-8', errors='replace') as f:
                form.content.data = f.read()
        except Exception as e:
            current_app.logger.error(f"Error reading file {file_id} for edit: {e}", exc_info=True)
            flash("Error reading file content.", "danger")
            form.content.data = "[Error reading file]"

    return render_template('files/edit.html',
                           form=form,
                           file_id=file_id,
                           original_filename=file_record.original_filename,
                           stored_filename=file_record.stored_filename, # Pass stored_filename
                           parent_folder_id=file_record.parent_folder_id,
                           user_codemirror_theme=user_cm_theme) # Pass theme


# --- Public Sharing (these routes are at root level, not /files/*) ---
# We'll define a separate blueprint or handle them in main_routes.py later for root access.
# For now, let's keep them conceptually with file actions.
# To make this work, this blueprint would need to be registered without a prefix,
# or these routes moved to a blueprint registered at root.
# Let's assume they are moved to main_routes or a dedicated 'sharing_routes' blueprint.
# For this exercise, I will put them here and note they need careful registration.

# These should probably be in a different blueprint if `bp` has a /files prefix
@bp.route('/s/<string:public_id>', methods=['GET', 'POST'], endpoint='serve_shared_file_unprefixed') # Temp endpoint name
@csrf.exempt # If it's a public endpoint, CSRF might not apply or needs careful handling.
def serve_shared_file(public_id):
    file_record = File.query.filter_by(public_id=public_id, is_public=True).first_or_404()
    is_protected = bool(file_record.public_password_hash)
    password_ok = not is_protected

    if is_protected and request.method == 'POST':
        submitted_password = request.form.get('password')
        if submitted_password and check_password_hash(file_record.public_password_hash, submitted_password):
            password_ok = True
        else:
            flash('Incorrect password.', 'danger')

    if password_ok:
        user_upload_path = get_user_upload_path(file_record.user_id)
        full_file_path = os.path.join(user_upload_path, file_record.stored_filename)
        if not os.path.exists(full_file_path): abort(404)
        try:
            return send_from_directory(user_upload_path, file_record.stored_filename, as_attachment=True, download_name=file_record.original_filename, conditional=True)
        except Exception as e: abort(500)
    elif is_protected:
        return render_template('share_password.html', public_id=public_id, file_name=file_record.original_filename)
    else: abort(500) # Should not happen


@bp.route('/share/<int:file_id>', methods=['POST'])
@login_required
def share_file(file_id):
    file_record = File.query.get_or_404(file_id)
    if file_record.owner != current_user: abort(403)
    data = request.get_json() or {}
    password = data.get('password')
    try:
        if not file_record.public_id: file_record.public_id = str(uuid.uuid4())
        if password: file_record.public_password_hash = generate_password_hash(password); password_protected = True
        else: file_record.public_password_hash = None; password_protected = False
        file_record.is_public = True
        db.session.commit()
        share_url = url_for('.serve_shared_file_unprefixed', public_id=file_record.public_id, _external=True) # Adjust endpoint
        return jsonify({"status": "success", "message": "File shared" + (" (password protected)." if password_protected else "."), "share_url": share_url, "password_protected": password_protected})
    except Exception as e:
        db.session.rollback(); current_app.logger.error(f"Error sharing file {file_id}: {e}")
        return jsonify({"status": "error", "message": "Failed to share file."}), 500

@bp.route('/unshare/<int:file_id>', methods=['POST'])
@login_required
def unshare_file(file_id):
    file_record = File.query.get_or_404(file_id)
    if file_record.owner != current_user: abort(403)
    try:
        file_record.is_public = False
        file_record.public_password_hash = None
        db.session.commit()
        return jsonify({"status": "success", "message": "File sharing disabled."})
    except Exception as e:
        db.session.rollback(); current_app.logger.error(f"Error unsharing file {file_id}: {e}")
        return jsonify({"status": "error", "message": "Failed to unshare file."}), 500


# --- Folder Operations ---
@bp.route('/folder/new', methods=['POST'])
@login_required
def create_folder():
    form = CreateFolderForm()
    parent_folder_id_str = request.form.get('parent_folder_id')
    parent_folder_id = int(parent_folder_id_str) if parent_folder_id_str and parent_folder_id_str != 'None' else None

    if parent_folder_id and not Folder.query.filter_by(id=parent_folder_id, user_id=current_user.id).first():
        flash('Parent folder not found.', 'danger'); return redirect(url_for('.list_files'))

    if form.validate_on_submit():
        new_name = form.name.data.strip()
        if '/' in new_name or '\\' in new_name: flash('Folder name cannot contain slashes.', 'danger')
        elif Folder.query.filter_by(user_id=current_user.id, parent_folder_id=parent_folder_id, name=new_name).first():
            flash(f'A folder named "{new_name}" already exists here.', 'danger')
        else:
            try:
                new_folder = Folder(name=new_name, user_id=current_user.id, parent_folder_id=parent_folder_id)
                db.session.add(new_folder); db.session.commit()
                flash(f'Folder "{new_name}" created.', 'success')
            except Exception as e:
                db.session.rollback(); current_app.logger.error(f"Error creating folder: {e}")
                flash('Failed to create folder.', 'danger')
    else:
        for field, errors in form.errors.items():
            for error in errors: flash(error, 'danger')
    return redirect(url_for('.list_files', folder_id=parent_folder_id) if parent_folder_id else url_for('.list_files'))


@bp.route('/folder/delete/<int:folder_id>', methods=['POST'])
@login_required
def delete_folder_route(folder_id): # Renamed
    folder_to_delete = Folder.query.get_or_404(folder_id)
    if folder_to_delete.owner != current_user:
        return jsonify({"status": "error", "message": "Permission denied."}), 403
    folder_name = folder_to_delete.name
    try:
        delete_folder_recursive(folder_to_delete, current_user.id) # Util function
        db.session.commit()
        return jsonify({"status": "success", "message": f"Folder '{folder_name}' deleted."})
    except Exception as e:
        db.session.rollback(); current_app.logger.error(f"Error deleting folder {folder_id}: {e}", exc_info=True)
        return jsonify({"status": "error", "message": f"Error deleting folder '{folder_name}'."}), 500


@bp.route('/folder/rename/<int:folder_id>', methods=['POST'])
@login_required
def rename_folder(folder_id):
    folder_record = Folder.query.get_or_404(folder_id)
    if folder_record.owner != current_user: return jsonify({"status": "error", "message": "Permission denied."}), 403
    data = request.get_json(); new_name_raw = data.get('new_name', '').strip()
    if not new_name_raw or len(new_name_raw) > 100 or '/' in new_name_raw or '\\' in new_name_raw:
        return jsonify({"status": "error", "message": "Invalid folder name."}), 400
    if Folder.query.filter(Folder.user_id == current_user.id, Folder.parent_folder_id == folder_record.parent_folder_id, Folder.name == new_name_raw, Folder.id != folder_id).first():
        return jsonify({"status": "error", "message": f"A folder named '{new_name_raw}' already exists."}), 400
    if folder_record.name == new_name_raw: return jsonify({"status": "success", "message": "Name unchanged.", "new_name": new_name_raw})
    try:
        folder_record.name = new_name_raw; db.session.commit()
        return jsonify({"status": "success", "message": "Folder renamed.", "new_name": new_name_raw})
    except Exception as e:
        db.session.rollback(); current_app.logger.error(f"Error renaming folder {folder_id}: {e}")
        return jsonify({"status": "error", "message": "DB error during rename."}), 500


@bp.route('/rename/<int:file_id>', methods=['POST']) # Assumed relative to /files prefix
@login_required
def rename_file(file_id):
    file_record = File.query.get_or_404(file_id)
    if file_record.owner != current_user: return jsonify({"status": "error", "message": "Permission denied."}), 403
    data = request.get_json(); new_name_raw = data.get('new_name', '').strip()
    if not new_name_raw or len(new_name_raw) > 250 or '/' in new_name_raw or '\\' in new_name_raw:
        return jsonify({"status": "error", "message": "Invalid filename."}), 400
    # Add check for filename conflict in the same folder if desired
    if File.query.filter(File.user_id == current_user.id, File.parent_folder_id == file_record.parent_folder_id, File.original_filename == new_name_raw, File.id != file_id).first():
        return jsonify({"status": "error", "message": f"A file named '{new_name_raw}' already exists in this folder."}), 400
    if file_record.original_filename == new_name_raw: return jsonify({"status": "success", "message": "Filename unchanged.", "new_name": new_name_raw})
    try:
        file_record.original_filename = new_name_raw; db.session.commit()
        return jsonify({"status": "success", "message": "File renamed.", "new_name": new_name_raw})
    except Exception as e:
        db.session.rollback(); current_app.logger.error(f"Error renaming file {file_id}: {e}")
        return jsonify({"status": "error", "message": "DB error during rename."}), 500


# --- API Routes for Clipboard and Batch Operations (prefix with /files/api/ if desired) ---
@bp.route('/api/move', methods=['POST']) # /files/api/move
@login_required
def move_items():
    data = request.get_json()
    if not data or 'items' not in data or 'target_folder_id' not in data:
        return jsonify({"status": "error", "message": "Invalid payload."}), 400
    items_to_move = data['items']
    target_folder_id_str = data['target_folder_id']
    target_folder_id = int(target_folder_id_str) if target_folder_id_str and target_folder_id_str != 'None' else None
    user_id = current_user.id; moved_count = 0; errors = []

    if target_folder_id and not Folder.query.filter_by(id=target_folder_id, user_id=user_id).first():
        return jsonify({"status": "error", "message": "Target folder not found."}), 404
    try:
        for item_data in items_to_move:
            item_id = int(item_data['id']); item_type = item_data['type']
            item_name_for_log = item_data.get('name', f'{item_type} ID {item_id}')
            item_obj = None
            if item_type == 'file': item_obj = File.query.filter_by(id=item_id, user_id=user_id).first()
            elif item_type == 'folder': item_obj = Folder.query.filter_by(id=item_id, user_id=user_id).first()
            if not item_obj: errors.append(f"{item_name_for_log} not found."); continue
            if item_obj.parent_folder_id == target_folder_id: moved_count +=1; continue # Already in target
            if item_type == 'folder' and item_obj.id == target_folder_id: errors.append(f"Cannot move folder into itself."); continue
            # Add more robust cycle check for folders if needed
            current_name = item_obj.name if item_type == 'folder' else item_obj.original_filename
            if check_name_conflict(user_id, target_folder_id, current_name, item_type, exclude_id=item_obj.id):
                errors.append(f"Name conflict for {item_name_for_log} in target folder."); continue
            item_obj.parent_folder_id = target_folder_id; db.session.add(item_obj); moved_count += 1
        db.session.commit()
        if errors: return jsonify({"status": "partial_success", "message": f"{moved_count} moved, {len(errors)} failed.", "errors": errors}), 207
        return jsonify({"status": "success", "message": f"{moved_count} item(s) moved."})
    except Exception as e:
        db.session.rollback(); current_app.logger.error(f"Error during move: {e}", exc_info=True)
        return jsonify({"status": "error", "message": "Server error during move.", "errors": errors}), 500


@bp.route('/api/batch_delete', methods=['POST']) # /files/api/batch_delete
@login_required
def api_batch_delete():
    data = request.get_json()
    if not data or 'items' not in data or not isinstance(data['items'], list):
        return jsonify({"status": "error", "message": "Invalid payload."}), 400
    items_to_delete = data['items']; deleted_count = 0; errors = []
    user_upload_path = get_user_upload_path(current_user.id)
    for item_data in items_to_delete:
        item_id = int(item_data['id']); item_type = item_data['type']
        item_name_for_log = item_data.get('name', f'{item_type} ID {item_id}')
        try:
            if item_type == 'file':
                file_record = File.query.get(item_id)
                if not file_record or file_record.user_id != current_user.id: errors.append({"item": item_name_for_log, "error": "File not found or permission denied."}); continue
                full_file_path = os.path.join(user_upload_path, file_record.stored_filename)
                if os.path.exists(full_file_path): os.remove(full_file_path)
                db.session.delete(file_record); db.session.commit(); deleted_count += 1
            elif item_type == 'folder':
                folder_record = Folder.query.get(item_id)
                if not folder_record or folder_record.user_id != current_user.id: errors.append({"item": item_name_for_log, "error": "Folder not found or permission denied."}); continue
                delete_folder_recursive(folder_record, current_user.id) # Util function
                db.session.commit(); deleted_count += 1
        except Exception as e:
            db.session.rollback(); errors.append({"item": item_name_for_log, "error": str(e)})
            current_app.logger.error(f"Batch delete error for {item_name_for_log}: {e}", exc_info=True)
    if errors:
        status = "partial_success" if deleted_count > 0 else "error"
        http_status = 207 if status == "partial_success" else 500
        return jsonify({"status": status, "message": f"{deleted_count} deleted, {len(errors)} errors.", "errors": errors}), http_status
    return jsonify({"status": "success", "message": f"Successfully deleted {deleted_count} item(s)."}), 200


@bp.route('/api/clipboard/set', methods=['POST']) # /files/api/clipboard/set
@login_required
def set_clipboard():
    data = request.get_json()
    if not data or 'items' not in data or 'operation' not in data or not isinstance(data['items'], list) or data['operation'] not in ['copy', 'cut']:
        return jsonify({"status": "error", "message": "Invalid clipboard data."}), 400
    # Basic validation of item structure (can be enhanced with ownership checks)
    validated_items = [{'id': item['id'], 'type': item['type']} for item in data['items'] if 'id' in item and 'type' in item and item['type'] in ['file', 'folder']]
    if len(validated_items) != len(data['items']): return jsonify({"status": "error", "message": "Invalid item structure in clipboard."}), 400
    session['clipboard'] = {'items': validated_items, 'operation': data['operation']}
    return jsonify({"status": "success", "message": "Items added to clipboard."})


@bp.route('/api/clipboard/paste', methods=['POST']) # /files/api/clipboard/paste
@login_required
def paste_from_clipboard():
    data = request.get_json(); target_folder_id_str = data.get('target_folder_id')
    target_folder_id = int(target_folder_id_str) if target_folder_id_str and target_folder_id_str != 'None' else None
    clipboard_data = session.get('clipboard')
    if not clipboard_data: return jsonify({"status": "error", "message": "Clipboard is empty."}), 400
    items_to_process = clipboard_data['items']; operation = clipboard_data['operation']; user_id = current_user.id
    processed_count = 0; errors = []

    if target_folder_id and not Folder.query.filter_by(id=target_folder_id, user_id=user_id).first():
        return jsonify({"status": "error", "message": "Target folder not found."}), 404
    try:
        for item_data in items_to_process:
            item_id = int(item_data['id']); item_type = item_data['type']
            item_to_process = File.query.filter_by(id=item_id, user_id=user_id).first() if item_type == 'file' else Folder.query.filter_by(id=item_id, user_id=user_id).first()
            if not item_to_process: errors.append(f"Item ID {item_id} not found."); continue
            if operation == 'cut' and item_to_process.parent_folder_id == target_folder_id: processed_count +=1; continue
            try:
                if operation == 'copy':
                    if item_type == 'file': copy_file_record(item_to_process, target_folder_id, user_id)
                    else: copy_folder_recursive(item_to_process, target_folder_id, user_id)
                elif operation == 'cut':
                    new_name = item_to_process.name if item_type == 'folder' else item_to_process.original_filename
                    if check_name_conflict(user_id, target_folder_id, new_name, item_type, exclude_id=item_id):
                        raise ValueError(f"Name conflict: '{new_name}' already exists in target.")
                    item_to_process.parent_folder_id = target_folder_id; db.session.add(item_to_process)
                processed_count += 1
            except ValueError as e_val: errors.append(f"Error processing {item_type} {item_id}: {e_val}")
            except Exception as e_proc: errors.append(f"Server error on {item_type} {item_id}."); current_app.logger.error(f"Paste error: {e_proc}", exc_info=True)
        if errors: db.session.rollback()
        else: db.session.commit()
        session.pop('clipboard', None) # Clear clipboard after attempt
        if errors: return jsonify({"status": "error", "message": f"Paste failed for {len(errors)} items.", "errors": errors}), 500
        return jsonify({"status": "success", "message": f"{processed_count} items {operation}ed."})
    except Exception as e_main:
        db.session.rollback(); session.pop('clipboard', None)
        current_app.logger.error(f"Major paste error: {e_main}", exc_info=True)
        return jsonify({"status": "error", "message": "Server error during paste."}), 500


# --- Archive and Extract ---
@bp.route('/folder/archive/<int:folder_id>', methods=['POST'])
@login_required
def archive_folder_route(folder_id): # Renamed
    folder = Folder.query.get_or_404(folder_id)
    if folder.owner != current_user: abort(403)
    archive_basename = secure_filename(f"{folder.name}.zip")
    user_upload_path = get_user_upload_path(current_user.id)
    archive_final_physical_path = os.path.join(user_upload_path, archive_basename) # Store flat for now

    if (File.query.filter_by(user_id=current_user.id, parent_folder_id=folder.parent_folder_id, original_filename=archive_basename).first() or
        Folder.query.filter_by(user_id=current_user.id, parent_folder_id=folder.parent_folder_id, name=archive_basename).first()):
        return jsonify({"status": "error", "message": f"Item '{archive_basename}' already exists."}), 409
    try:
        with zipfile.ZipFile(archive_final_physical_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            add_folder_to_zip(zipf, folder.id, current_user.id, folder.name, user_upload_path) # Util
        filesize = os.path.getsize(archive_final_physical_path)
        storage_info = get_user_storage_info(current_user)
        current_usage_bytes = db.session.query(db.func.sum(File.filesize)).filter(File.user_id == current_user.id).scalar() or 0
        available_bytes = storage_info['limit_bytes'] - current_usage_bytes
        if filesize > available_bytes:
            os.remove(archive_final_physical_path)
            return jsonify({"status": "error", "message": "Insufficient storage for archive."}), 413
        new_file = File(
            original_filename=archive_basename, stored_filename=archive_basename, filesize=filesize,
            mime_type='application/zip', owner=current_user, parent_folder_id=folder.parent_folder_id
        )
        db.session.add(new_file); db.session.commit()
        return jsonify({"status": "success", "message": f"Folder '{folder.name}' archived."})
    except Exception as e:
        db.session.rollback()
        if os.path.exists(archive_final_physical_path):
            try:
                os.remove(archive_final_physical_path)
                current_app.logger.info(f"Cleaned up partially created archive: {archive_final_physical_path}")
            except OSError as e_remove: # Catch specific OSError for the remove operation
                current_app.logger.error(f"Failed to remove partially created archive {archive_final_physical_path} after error: {e_remove}")
        current_app.logger.error(f"Error archiving folder {folder_id}: {e}", exc_info=True)
        return jsonify({"status": "error", "message": "Failed to archive folder."}), 500



@bp.route('/extract/<int:file_id>', methods=['POST'])
@login_required
def extract_file_route(file_id): # Renamed
    file_record = File.query.get_or_404(file_id)
    if file_record.owner != current_user: abort(403)
    user_upload_path = get_user_upload_path(current_user.id)
    archive_path = os.path.join(user_upload_path, file_record.stored_filename)
    file_ext = os.path.splitext(file_record.original_filename)[1].lower()

    if not os.path.isfile(archive_path): return jsonify({"status": "error", "message": "Archive not found."}), 404

    # Updated to include .7z
    SUPPORTED_EXTENSIONS = {'.zip', '.7z'}
    if file_ext not in SUPPORTED_EXTENSIONS:
        return jsonify({"status": "error", "message": f"Extraction not supported for {file_ext}."}), 400

    try: # Pre-extraction storage check
        required_space = get_archive_uncompressed_size(archive_path) # Util
        if required_space > 0:
            storage_info = get_user_storage_info(current_user)
            available_space = storage_info['limit_bytes'] - storage_info['usage_bytes']
            if required_space > available_space:
                return jsonify({"status": "error", "message": "Insufficient storage to extract."}), 413
    except ValueError as e_size:
        return jsonify({"status": "error", "message": f"Storage check failed: {str(e_size)}"}), 400

    temp_extract_dir = os.path.join(user_upload_path, f"temp_extract_{uuid.uuid4()}")
    try:
        os.makedirs(temp_extract_dir, exist_ok=True)

        # Add logic for .7z extraction
        if file_ext == '.zip':
            shutil.unpack_archive(archive_path, temp_extract_dir)
        elif file_ext == '.7z':
            try:
                with py7zr.SevenZipFile(archive_path, mode='r') as z:
                    z.extractall(path=temp_extract_dir)
            except py7zr.exceptions.Bad7zFile:
                current_app.logger.error(f"Bad 7z file: {archive_path}", exc_info=True)
                return jsonify({"status": "error", "message": "Invalid or corrupted .7z archive."}), 400
            except Exception as e_7z:
                current_app.logger.error(f"7z extraction failed for {archive_path}: {e_7z}", exc_info=True)
                # Re-raise to be caught by the outer try-except, or return specific error
                return jsonify({"status": "error", "message": f"Failed to extract .7z archive: {str(e_7z)}"}), 500
        else:
            # This case should ideally not be reached due to SUPPORTED_EXTENSIONS check
            current_app.logger.error(f"Extraction attempted for unhandled supported extension: {file_ext}")
            return jsonify({"status": "error", "message": "Internal error: unhandled archive type."}), 500

        register_extracted_items(temp_extract_dir, current_user.id, file_record.parent_folder_id, user_upload_path) # Util
        db.session.commit()
        return jsonify({"status": "success", "message": f"Archive '{file_record.original_filename}' extracted."})
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error during extraction process for {file_id} ({file_ext}): {e}", exc_info=True)
        return jsonify({"status": "error", "message": f"Failed to extract archive: {str(e)}"}), 500
    finally:
        if os.path.exists(temp_extract_dir): shutil.rmtree(temp_extract_dir, ignore_errors=True)

