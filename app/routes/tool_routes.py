# app/routes/tool_routes.py
import os
import uuid
import shutil
import json
import threading
import time
import select
import mimetypes
from datetime import datetime
import socket

from flask import (
    Blueprint, render_template, redirect, url_for, flash, request,
    session, jsonify, current_app, send_from_directory, abort
)
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename
from PIL import Image, ImageSequence # For Image Upscaler

# Import from app package
from app import db, socketio # db and socketio from app/__init__
from app.models import File, User, Setting, MonitoredServer
from app.forms import YtdlpForm, ImageUpscalerForm, AddServerForm # Forms
from app.utils import get_user_upload_path, get_user_storage_info, allowed_file_upscaler # Utilities
from app.config import ( # Config constants
    YTDLP_TEMP_DOWNLOAD_FOLDER, UPSCALED_IMAGE_FOLDER, ALLOWED_EXTENSIONS_UPSCALER,
    DEFAULT_MAX_UPLOAD_MB_FALLBACK # For YTDLP storage check
)

# Tool-specific imports
import yt_dlp
from yt_dlp import YoutubeDL
import paramiko


# Define the blueprint
bp = Blueprint('tool_routes', __name__, url_prefix='/tools') # Using '/tools' prefix


# --- YouTube Downloader (YTDLP) ---
def get_user_ytdlp_temp_path(user_id): # Helper specific to YTDLP
    # YTDLP_TEMP_DOWNLOAD_FOLDER is from config.py
    path = os.path.join(YTDLP_TEMP_DOWNLOAD_FOLDER, str(user_id))
    os.makedirs(path, exist_ok=True)
    return path

@bp.route('/ytdlp', methods=['GET', 'POST'])
@login_required
def ytdlp_downloader():
    form = YtdlpForm()
    if form.validate_on_submit():
        video_url = form.youtube_url.data
        download_format = form.download_format.data
        video_quality = form.video_quality.data
        user_id = current_user.id
        user_temp_ytdlp_path = get_user_ytdlp_temp_path(user_id)

        # Clean temp ytdlp dir for user
        try:
            for item in os.listdir(user_temp_ytdlp_path):
                item_path = os.path.join(user_temp_ytdlp_path, item)
                if os.path.isfile(item_path) or os.path.islink(item_path): os.unlink(item_path)
                elif os.path.isdir(item_path): shutil.rmtree(item_path)
        except Exception as e_clean:
            current_app.logger.warning(f"Could not fully clean temp ytdlp dir {user_temp_ytdlp_path}: {e_clean}")

        video_title_for_filename = "yt_download"
        try:
            with YoutubeDL({'quiet': True, 'noplaylist': True, 'extract_flat': True, 'logger': current_app.logger}) as ydl_info:
                pre_info_dict = ydl_info.extract_info(video_url, download=False)
            video_title_for_filename = pre_info_dict.get('title', video_title_for_filename)
        except Exception as e_pre_info:
            current_app.logger.warning(f"Could not pre-fetch video title for {video_url}: {e_pre_info}")

        temp_dl_uuid_filename = str(uuid.uuid4())
        temp_output_template = os.path.join(user_temp_ytdlp_path, f"{temp_dl_uuid_filename}.%(ext)s")
        ydl_opts = {'outtmpl': temp_output_template, 'noplaylist': True, 'quiet': False, 'noprogress': True, 'logger': current_app.logger, 'continuedl': True, 'ignoreerrors': False}
        final_extension_hint = ".mp4"

        if download_format == 'mp3':
            ydl_opts.update({'format': 'bestaudio/best', 'postprocessors': [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3', 'preferredquality': '192'}]})
            final_extension_hint = ".mp3"
        else: # mp4
            quality_filter = f"[height<={video_quality}]" if video_quality != 'best' else ""
            ydl_opts['format'] = f"bestvideo{quality_filter}+bestaudio/best{quality_filter}/best"
            ydl_opts['postprocessors'] = [{'key': 'FFmpegVideoConvertor', 'preferedformat': 'mp4'}]

        downloaded_video_actual_path = None
        try:
            with YoutubeDL(ydl_opts) as ydl:
                result_info = ydl.extract_info(video_url, download=True)
            # Determine downloaded_video_actual_path (logic from original main.py)
            if result_info and result_info.get('filepath'): downloaded_video_actual_path = result_info['filepath']
            elif result_info and result_info.get('requested_downloads') and result_info['requested_downloads'][0].get('filepath'): downloaded_video_actual_path = result_info['requested_downloads'][0]['filepath']
            elif result_info and result_info.get('_filename'):
                 _fn = result_info['_filename']
                 downloaded_video_actual_path = os.path.join(user_temp_ytdlp_path, os.path.basename(_fn)) if not os.path.isabs(_fn) else _fn

            if not downloaded_video_actual_path or not os.path.exists(downloaded_video_actual_path):
                found_files = [f for f in os.listdir(user_temp_ytdlp_path) if f.startswith(temp_dl_uuid_filename)]
                if found_files:
                    full_paths = [os.path.join(user_temp_ytdlp_path, f) for f in found_files]
                    preferred_found_file = next((p for p in full_paths if p.endswith(final_extension_hint)), None)
                    downloaded_video_actual_path = preferred_found_file if preferred_found_file else max(full_paths, key=lambda p: os.path.getsize(p) if os.path.exists(p) else -1)

            if not downloaded_video_actual_path or not os.path.exists(downloaded_video_actual_path):
                raise Exception("Could not locate downloaded file after yt-dlp.")

            file_size_bytes = os.path.getsize(downloaded_video_actual_path)
            actual_extension = os.path.splitext(downloaded_video_actual_path)[1].lower() or final_extension_hint
            original_filename_for_db = secure_filename(video_title_for_filename + actual_extension)
            if not original_filename_for_db.endswith(actual_extension): original_filename_for_db = secure_filename(video_title_for_filename) + actual_extension

            stored_filename_on_disk = str(uuid.uuid4()) + actual_extension
            user_main_upload_path = get_user_upload_path(user_id) # Util function
            final_file_path_on_disk = os.path.join(user_main_upload_path, stored_filename_on_disk)

            storage_info = get_user_storage_info(current_user) # Util function
            available_bytes = storage_info['limit_bytes'] - storage_info['usage_bytes']
            if file_size_bytes > available_bytes:
                os.remove(downloaded_video_actual_path)
                flash(f"Downloaded file ({file_size_bytes / (1024*1024):.2f}MB) exceeds available storage.", 'danger')
                return redirect(url_for('.ytdlp_downloader'))

            shutil.move(downloaded_video_actual_path, final_file_path_on_disk)
            mime_type, _ = mimetypes.guess_type(final_file_path_on_disk)
            mime_type = mime_type or ('audio/mpeg' if download_format == 'mp3' else 'video/mp4')

            new_file_db_record = File(
                original_filename=original_filename_for_db, stored_filename=stored_filename_on_disk,
                filesize=file_size_bytes, mime_type=mime_type, user_id=user_id, parent_folder_id=None
            )
            db.session.add(new_file_db_record); db.session.commit()
            flash(f"Successfully downloaded '{new_file_db_record.original_filename}'!", 'success')
            session['last_downloaded_ytdlp_info'] = {'original_filename': new_file_db_record.original_filename, 'filesize': new_file_db_record.filesize, 'id': new_file_db_record.id}
            return redirect(url_for('.ytdlp_downloader'))

        except yt_dlp.utils.DownloadError as e:
            current_app.logger.error(f"yt-dlp DownloadError for {video_url}: {e}")
            flash(f"Download Error: {e}", 'danger')
        except Exception as e:
            current_app.logger.error(f"YTDLP unexpected error: {e}", exc_info=True)
            flash(f"Unexpected error: {e}", 'danger')
            if downloaded_video_actual_path and os.path.exists(downloaded_video_actual_path):
                 try: os.remove(downloaded_video_actual_path)
                 except OSError: pass

    downloaded_file_info_from_session = session.pop('last_downloaded_ytdlp_info', None)
    return render_template('tools/ytdlp.html', title='YouTube Downloader', form=form, # Assuming templates in tools/
                           downloaded_file_info=downloaded_file_info_from_session)


# --- Image Upscaler ---
@bp.route('/image_upscaler', methods=['GET', 'POST'])
@login_required
def image_upscaler():
    form = ImageUpscalerForm()
    original_file_saved_name, upscaled_file_saved_name, original_filename_for_download = None, None, None
    upscaled_img_dimensions = {}

    if request.method == 'POST':
        if 'image_file' not in request.files:
            flash('No image file part.', 'danger'); return redirect(request.url)
        file_storage = request.files['image_file'] # Renamed
        scale_factor = int(request.form.get('scale_factor', 2))
        if not file_storage or file_storage.filename == '':
            flash('No image selected.', 'warning'); return redirect(request.url)

        if file_storage and allowed_file_upscaler(file_storage.filename):
            original_filename_for_client = secure_filename(file_storage.filename) # Used for user feedback and DB

            # Current logic saves original to UPSCALED_IMAGE_FOLDER. This can remain or be optimized.
            # For this example, we'll focus on the upscaled output.
            # temp_original_ext = os.path.splitext(original_filename_for_client)[1].lower()
            # temp_original_saved_name = "original_" + str(uuid.uuid4()) + temp_original_ext
            # original_file_path = os.path.join(UPSCALED_IMAGE_FOLDER, temp_original_saved_name)
            # original_file_saved_name = temp_original_saved_name # For template if needed
            # file_storage.save(original_file_path)
            # input_img_pil = Image.open(original_file_path)

            # It's often better to open from stream if possible to avoid intermediate file for original
            try:
                input_img_pil = Image.open(file_storage.stream) # Try opening from stream
            except Exception as e_open_stream:
                current_app.logger.warning(f"Could not open image from stream, falling back to temp save: {e_open_stream}")
                # Fallback: save original temporarily if stream opening fails or PIL requires it
                # This part is simplified; ensure proper temp handling if you keep it.
                temp_orig_path = os.path.join(YTDLP_TEMP_DOWNLOAD_FOLDER, "temp_original_" + str(uuid.uuid4()))
                file_storage.save(temp_orig_path)
                input_img_pil = Image.open(temp_orig_path)
                # Consider removing temp_orig_path immediately after open if not needed by PIL further

            try:
                img_to_resize = input_img_pil.copy()
                if img_to_resize.mode == 'P': img_to_resize = img_to_resize.convert('RGBA')
                elif img_to_resize.mode not in ['RGBA', 'LA']: img_to_resize = img_to_resize.convert('RGB')

                new_width = img_to_resize.width * scale_factor
                new_height = img_to_resize.height * scale_factor
                upscaled_img_pil = img_to_resize.resize((new_width, new_height), Image.Resampling.LANCZOS)

                output_ext = os.path.splitext(original_filename_for_client)[1].lower()
                if output_ext not in ['.png', '.jpg', '.jpeg', '.webp']: output_ext = '.png'

                # --- START: New Direct Save Logic (adapted from ytdlp and save_permanently_upscaled_image) ---
                user_id = current_user.id

                # Prepare to save to a temporary processing file to get its size
                # You can use a subfolder in YTDLP_TEMP_DOWNLOAD_FOLDER or a new configured temp image folder
                user_temp_processing_dir = get_user_ytdlp_temp_path(user_id) # Or a new function for image temp path
                temp_processed_filename = "upscaled_temp_" + str(uuid.uuid4()) + output_ext
                temp_processed_image_path = os.path.join(user_temp_processing_dir, temp_processed_filename)

                # PIL save options
                pil_save_format = 'JPEG' if output_ext in ['.jpg', '.jpeg'] else output_ext.upper().lstrip('.')
                save_kwargs = {'quality': 90} if pil_save_format in ['JPEG', 'WEBP'] else {}
                if pil_save_format == 'WEBP' and upscaled_img_pil.mode in ['RGBA', 'LA']: save_kwargs['lossless'] = True
                if pil_save_format == 'PNG': save_kwargs['optimize'] = True

                final_pil_image_to_save = upscaled_img_pil
                if pil_save_format == 'JPEG' and final_pil_image_to_save.mode != 'RGB':
                    final_pil_image_to_save = final_pil_image_to_save.convert('RGB')

                final_pil_image_to_save.save(temp_processed_image_path, format=pil_save_format, **save_kwargs)
                file_size_bytes = os.path.getsize(temp_processed_image_path)

                # Check storage space
                storage_info = get_user_storage_info(current_user)
                available_bytes = storage_info['limit_bytes'] - storage_info['usage_bytes']

                if file_size_bytes > available_bytes:
                    os.remove(temp_processed_image_path) # Clean up temp file
                    flash(f"Upscaled image ({file_size_bytes / (1024*1024):.2f}MB) exceeds your available storage.", 'danger')
                    return redirect(url_for('.image_upscaler'))

                # Determine permanent storage location
                stored_filename_on_disk = str(uuid.uuid4()) + output_ext
                user_main_upload_path = get_user_upload_path(user_id)
                os.makedirs(user_main_upload_path, exist_ok=True)
                permanent_file_path_on_disk = os.path.join(user_main_upload_path, stored_filename_on_disk)

                shutil.move(temp_processed_image_path, permanent_file_path_on_disk)

                # Create File record in the database
                base_original_name, _ = os.path.splitext(original_filename_for_client)
                final_original_filename_for_db = secure_filename(base_original_name + output_ext)

                mime_type, _ = mimetypes.guess_type(permanent_file_path_on_disk)
                if not mime_type: # Fallback logic from save_permanently_upscaled_image
                    if output_ext == '.jpg' or output_ext == '.jpeg': mime_type = 'image/jpeg'
                    elif output_ext == '.png': mime_type = 'image/png'
                    elif output_ext == '.webp': mime_type = 'image/webp'
                    # Add other types like .gif if you support them
                    else: mime_type = 'application/octet-stream'

                new_file_db_record = File(
                    original_filename=final_original_filename_for_db,
                    stored_filename=stored_filename_on_disk,
                    filesize=file_size_bytes,
                    mime_type=mime_type,
                    user_id=user_id,
                    parent_folder_id=None # Or your folder logic
                )
                db.session.add(new_file_db_record)
                db.session.commit()

                flash(f"Successfully upscaled and saved '{new_file_db_record.original_filename}' to your files!", 'success')
                current_app.logger.info(f"User {user_id} upscaled and saved image {original_filename_for_client} as {stored_filename_on_disk}")

                # Optionally, store info about the saved file in session for display
                session['last_upscaled_file_info'] = {
                    'original_filename': new_file_db_record.original_filename,
                    'filesize': new_file_db_record.filesize,
                    'id': new_file_db_record.id,
                    'width': upscaled_img_pil.width, # Store new dimensions
                    'height': upscaled_img_pil.height
                }
                return redirect(url_for('.image_upscaler'))
                # --- END: New Direct Save Logic ---

            except Exception as e:
                flash(f'Error processing or saving image: {e}', 'danger')
                current_app.logger.error(f"Error in image upscaler: {e}", exc_info=True)
                # Clean up temp processed file if it exists and an error occurs after its creation
                if 'temp_processed_image_path' in locals() and os.path.exists(temp_processed_image_path):
                    try: os.remove(temp_processed_image_path)
                    except OSError: pass
                # Also, clean up original temp file if you created one (e.g., temp_orig_path)
                if 'temp_orig_path' in locals() and os.path.exists(temp_orig_path):
                    try: os.remove(temp_orig_path)
                    except OSError: pass
                return redirect(url_for('.image_upscaler')) # Redirect on error
        else:
            flash('Invalid file type for upscaling.', 'warning')
            return redirect(request.url)

    # Cleanup for UPSCALED_IMAGE_FOLDER (if still used for temporary originals or other temp items)
    # This cleanup might need adjustment based on what you keep in UPSCALED_IMAGE_FOLDER
    try:
        # Ensure datetime is imported: from datetime import datetime
        now_ts = datetime.now().timestamp()
        # Only clean general temp files, not specific ones related to an ongoing process if they are outside this function's scope
        for f_name in os.listdir(UPSCALED_IMAGE_FOLDER):
            # Be careful what you delete here. If this folder is now purely for transient originals, fine.
            # If 'original_file_saved_name' logic is removed/changed, this check might not be relevant
            # if f_name == original_file_saved_name: continue
            f_path = os.path.join(UPSCALED_IMAGE_FOLDER, f_name)
            if (now_ts - os.path.getmtime(f_path)) > 600: # 10 minutes
                 try: os.remove(f_path)
                 except OSError: pass
    except Exception as e_clean:
        current_app.logger.warning(f"Upscaled image folder cleanup error: {e_clean}")

    last_upscaled_info = session.pop('last_upscaled_file_info', None)
    return render_template('tools/image_upscaler.html', title='Image Upscaler', form=form,
                           last_upscaled_file_info=last_upscaled_info) # Pass new info to template


@bp.route('/temp_upscaled_images/<filename>')
@login_required
def serve_temp_upscaled_image(filename):
    safe_filename = secure_filename(filename)
    if safe_filename != filename: abort(404)
    # UPSCALED_IMAGE_FOLDER from config.py
    return send_from_directory(UPSCALED_IMAGE_FOLDER, safe_filename)

@bp.route('/save_permanently_upscaled_image', methods=['POST'])
@login_required
def save_permanently_upscaled_image():
    temp_filename = request.form.get('temp_filename')
    original_filename_for_save = request.form.get('original_filename_for_save')
    # scale_factor = request.form.get('scale_factor') # Not used in save logic but available

    if not temp_filename or not original_filename_for_save:
        flash('Missing file information for saving.', 'danger')
        return redirect(url_for('.image_upscaler'))

    # Secure the original filename for saving, but prioritize the extension from the temp_filename
    # as it reflects the actual format after upscaling (e.g. if converted to PNG)
    base_original_name, _ = os.path.splitext(original_filename_for_save)
    _, temp_ext = os.path.splitext(temp_filename)

    # Ensure the extension from temp_filename is valid and secure
    if not temp_ext or temp_ext.lower() not in ['.png', '.jpg', '.jpeg', '.webp', '.gif']: # Add other allowed extensions if necessary
        temp_ext = '.png' # Default to png if extension is missing or invalid

    final_original_filename = secure_filename(base_original_name + temp_ext)


    temp_upscaled_path = os.path.join(UPSCALED_IMAGE_FOLDER, secure_filename(temp_filename))

    if not os.path.exists(temp_upscaled_path):
        flash('Upscaled image not found. It might have expired or been removed.', 'danger')
        current_app.logger.warning(f"Attempt to save non-existent temp file: {temp_upscaled_path} for user {current_user.id}")
        return redirect(url_for('.image_upscaler'))

    try:
        file_size_bytes = os.path.getsize(temp_upscaled_path)
        user_id = current_user.id

        # Check storage space
        storage_info = get_user_storage_info(current_user) # util function
        available_bytes = storage_info['limit_bytes'] - storage_info['usage_bytes']

        if file_size_bytes > available_bytes:
            # No need to os.remove temp_upscaled_path, it will be cleaned up eventually.
            flash(f"Upscaled image ({file_size_bytes / (1024*1024):.2f}MB) exceeds your available storage.", 'danger')
            return redirect(url_for('.image_upscaler'))

        # Determine permanent storage location
        stored_filename_on_disk = str(uuid.uuid4()) + temp_ext # Use extension from temp file
        user_main_upload_path = get_user_upload_path(user_id) # util function
        os.makedirs(user_main_upload_path, exist_ok=True) # Ensure user's upload directory exists
        permanent_file_path_on_disk = os.path.join(user_main_upload_path, stored_filename_on_disk)

        # Move the file
        shutil.move(temp_upscaled_path, permanent_file_path_on_disk)

        # Create a new File record in the database
        mime_type, _ = mimetypes.guess_type(permanent_file_path_on_disk)
        if not mime_type: # Fallback if guess_type fails
            if temp_ext == '.jpg' or temp_ext == '.jpeg':
                mime_type = 'image/jpeg'
            elif temp_ext == '.png':
                mime_type = 'image/png'
            elif temp_ext == '.webp':
                mime_type = 'image/webp'
            elif temp_ext == '.gif':
                mime_type = 'image/gif'
            else:
                mime_type = 'application/octet-stream' # Generic fallback

        new_file_db_record = File(
            original_filename=final_original_filename,
            stored_filename=stored_filename_on_disk,
            filesize=file_size_bytes,
            mime_type=mime_type,
            user_id=user_id,
            parent_folder_id=None  # Or handle folder logic if you have it
        )
        db.session.add(new_file_db_record)
        db.session.commit()

        flash(f"Successfully saved '{new_file_db_record.original_filename}' to your files!", 'success')
        current_app.logger.info(f"User {user_id} permanently saved upscaled image {original_filename_for_save} as {stored_filename_on_disk}")

    except Exception as e:
        current_app.logger.error(f"Error saving upscaled image permanently for user {current_user.id}: {e}", exc_info=True)
        flash(f"An unexpected error occurred while saving the image: {e}", 'danger')
        # If the file was moved and DB failed, it's tricky. For simplicity, we don't try to move it back.
        # If it wasn't moved, it will be cleaned up by the existing cleanup logic.

    return redirect(url_for('.image_upscaler'))

# --- SSH Client ---
active_ssh_sessions = {} # Moved here, specific to this tool

class SSHClientSession:
    def __init__(self, ip, port, username, socket_id):
        self.ip, self.port, self.username, self.socket_id = ip, port, username, socket_id
        self.client, self.channel, self.output_thread, self.active = None, None, None, False
        self.lock = threading.Lock()

    def connect(self, password=None):
        try:
            self.client = paramiko.SSHClient()
            self.client.load_system_host_keys()
            self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            connect_params = {'hostname': self.ip, 'port': self.port, 'username': self.username, 'timeout': 10}
            if password: connect_params['password'] = password
            self.client.connect(**connect_params)
            self.channel = self.client.invoke_shell(); self.channel.setblocking(0); self.active = True
            socketio.emit('ssh_connected', {}, room=self.socket_id) # socketio imported from app
            self.output_thread = threading.Thread(target=self._read_output, daemon=True); self.output_thread.start()
            return True
        except Exception as e: # Simplified exception handling
            error_msg = f'SSH Connection Error: {type(e).__name__} - {e}'
            current_app.logger.error(f"SSH Error for {self.username}@{self.ip}: {error_msg}", exc_info=True)
            socketio.emit('ssh_error', {'message': error_msg}, room=self.socket_id)
            self.disconnect(); return False

    def _read_output(self):
        while self.active:
            try:
                rlist, _, _ = select.select([self.channel], [], [], 0.1)
                if rlist:
                    output = b''
                    while self.channel.recv_ready(): output += self.channel.recv(4096)
                    while self.channel.recv_stderr_ready(): output += self.channel.recv_stderr(4096)
                    if output: socketio.emit('ssh_output', {'output': output.decode('utf-8', errors='replace')}, room=self.socket_id)
                if self.channel and (self.channel.exit_status_ready() or not self.channel.active):
                    self.disconnect(); break
                time.sleep(0.01)
            except Exception as e:
                current_app.logger.error(f"SSH output read error: {e}", exc_info=True)
                if self.active: socketio.emit('ssh_error', {'message': f'Terminal read error: {e}'}, room=self.socket_id)
                self.disconnect(); break
        current_app.logger.info(f"SSH output thread for {self.username}@{self.ip} finished.")

    def execute_command(self, command):
        if not self.active or not self.channel:
            socketio.emit('ssh_error', {'message': 'Not connected.'}, room=self.socket_id); return
        try:
            with self.lock: self.channel.send(command.encode('utf-8'))
        except Exception as e:
            socketio.emit('ssh_error', {'message': f'Failed to send command: {e}'}, room=self.socket_id)
            self.disconnect()

    def disconnect(self):
        if self.active:
            self.active = False
            if self.channel:
                try:
                    self.channel.close()
                    current_app.logger.info(f"SSH channel closed for {self.username}@{self.ip}")
                except Exception as e_ch_close:
                    current_app.logger.warning(f"Error closing SSH channel for {self.username}@{self.ip}: {e_ch_close}")
            if self.client:
                try:
                    self.client.close()
                    current_app.logger.info(f"SSH client closed for {self.username}@{self.ip}")
                except Exception as e_cli_close:
                    current_app.logger.warning(f"Error closing SSH client for {self.username}@{self.ip}: {e_cli_close}")

            # Ensure socketio is available if this class is used outside of a Flask app context directly
            # However, in this setup, it's called via socketio.emit which implies app context
            if socketio: # Check if socketio object exists
                 socketio.emit('ssh_disconnected', {}, room=self.socket_id)
            else:
                current_app.logger.warning("socketio object not available in SSHClientSession.disconnect")

            self._cleanup_session_data()

@bp.route('/ssh_client')
@login_required
def ssh_client_page():
    return render_template('tools/ssh_client.html', title='SSH Client') # Assuming templates in tools/

@bp.route('/ssh_terminal_popup')
@login_required
def ssh_terminal_popup():
    return render_template('tools/ssh_terminal_popup.html') # Assuming templates in tools/

# SocketIO event handlers for SSH (need to be registered with the main socketio instance)
# These are defined here but will be attached in app/__init__.py or when socketio is initialized.
# For now, they are just functions. The @socketio.on decorators from main.py will be handled
# by importing these functions into app/__init__.py and calling them with the app's socketio instance.

def handle_ssh_connect_request(data):
    if not current_user.is_authenticated: return # Basic check, though @login_required might be better on SocketIO if possible
    socket_id = request.sid; ip = data.get('ip'); port = int(data.get('port', 22)); username = data.get('username'); password = data.get('password')
    if not ip or not username: socketio.emit('ssh_error', {'message': 'IP and username required.'}, room=socket_id); return
    if socket_id in active_ssh_sessions: active_ssh_sessions[socket_id].disconnect(); del active_ssh_sessions[socket_id]
    ssh_session = SSHClientSession(ip, port, username, socket_id); active_ssh_sessions[socket_id] = ssh_session
    threading.Thread(target=ssh_session.connect, args=(password,), daemon=True).start()

def handle_ssh_command(data):
    if not current_user.is_authenticated: return
    socket_id = request.sid; command = data.get('command')
    ssh_session = active_ssh_sessions.get(socket_id)
    if not ssh_session or not ssh_session.active: socketio.emit('ssh_error', {'message': 'No active SSH connection.'}, room=socket_id); return
    ssh_session.execute_command(command)

def handle_ssh_disconnect_request():
    if not current_user.is_authenticated: return
    socket_id = request.sid
    ssh_session = active_ssh_sessions.get(socket_id)
    if ssh_session: ssh_session.disconnect()
    else: socketio.emit('ssh_disconnected', {}, room=socket_id) # Send confirmation anyway

def handle_ssh_resize(data):
    if not current_user.is_authenticated: return
    socket_id = request.sid; cols = data.get('cols'); rows = data.get('rows')
    ssh_session = active_ssh_sessions.get(socket_id)
    if ssh_session and ssh_session.active and ssh_session.channel:
        try: ssh_session.channel.resize_pty(width=cols, height=rows)
        except Exception as e: current_app.logger.error(f"Error resizing PTY for {socket_id}: {e}")

def handle_socket_disconnect(): # General SocketIO disconnect
    socket_id = request.sid
    current_app.logger.info(f"Socket.IO client disconnected: {socket_id}")
    ssh_session = active_ssh_sessions.get(socket_id)
    if ssh_session: ssh_session.disconnect()


# --- GBA Emulator ---
@bp.route('/emulator_gba')
@login_required
def emulator_gba():
    return render_template('tools/emulator_gba.html', title="GBA Emulator") # Assuming template in tools/

@bp.route('/emulator_gba/roms/<filename>') # This serves ROMs, path might need adjustment based on where GBA ROMs are stored.
@login_required
def serve_gba_rom(filename):
    # GBA_ROM_UPLOAD_FOLDER should be in app.config
    rom_folder = current_app.config.get('GBA_ROM_UPLOAD_FOLDER')
    if not rom_folder or not os.path.isdir(rom_folder):
        current_app.logger.error("GBA ROM upload folder not configured or does not exist.")
        abort(404)
    return send_from_directory(rom_folder, filename)

# --- Server Monitor ---

def _log_daemon_comm(message, level="info"):
    """Helper to log messages related to daemon communication."""
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    log_func = getattr(current_app.logger, level, current_app.logger.info)
    log_func(f"[{timestamp}] [DAEMON_COMM] {message}")

def _request_info_from_daemon(host, port, password):
    """
    Connects to the daemon, authenticates, and requests information.
    Adapted from the user's client script.
    Returns a tuple: (data_dict, error_message_string)
    """
    _log_daemon_comm(f"Attempting to connect to {host}:{port}...")
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.connect((host, port))
            s.settimeout(10)  # Set a timeout for socket operations

            prompt = s.recv(1024).decode()
            if "Password:" not in prompt:
                err_msg = f"Did not receive password prompt from {host}:{port}. Received: {prompt}"
                _log_daemon_comm(err_msg, level="warning")
                return None, err_msg

            s.sendall(password.encode())
            auth_response_raw = s.recv(1024).decode()
            _log_daemon_comm(f"Auth response from {host}:{port}: {auth_response_raw.strip()}")

            if "Authentication failed" in auth_response_raw:
                err_msg = f"Authentication failed for {host}:{port}."
                _log_daemon_comm(err_msg, level="warning")
                return None, err_msg
            elif "Authentication successful" not in auth_response_raw:
                err_msg = f"Unexpected authentication response from {host}:{port}: {auth_response_raw.strip()}"
                _log_daemon_comm(err_msg, level="warning")
                return None, err_msg

            full_data_str = ""
            while True:
                chunk = s.recv(4096)
                if not chunk:
                    break
                full_data_str += chunk.decode('utf-8', errors='replace')
                try:
                    # Attempt to parse if we might have a complete JSON object
                    # This is a common pattern: server sends a confirmation, then JSON.
                    # The JSON might not be immediately after the auth confirmation line.
                    # We look for a structure that could be JSON.
                    if full_data_str.strip().startswith("{") and full_data_str.strip().endswith("}"):
                        # Find the start of the actual JSON data
                        # It might be after "Sending data...\n" or similar.
                        json_start_index = full_data_str.find('{')
                        if json_start_index != -1:
                            json_candidate = full_data_str[json_start_index:]
                            data = json.loads(json_candidate)
                            _log_daemon_comm(f"Successfully received and parsed data from {host}:{port}.")
                            return data, None
                except json.JSONDecodeError:
                    # Not a complete JSON object yet, or malformed. Continue accumulating if more data is expected.
                    # If the server sends data in one go, and then closes, this might fail if not caught correctly.
                    pass # Continue to accumulate more data
                except Exception as e_parse: # Catch other potential parsing errors
                    _log_daemon_comm(f"Error during data parsing from {host}:{port}: {e_parse}", level="error")
                    return None, f"Error parsing data: {e_parse}"


            # If loop finishes, try to parse accumulated data (if any)
            if full_data_str:
                try:
                    # Attempt to find JSON within the accumulated string
                    json_start_index = full_data_str.find('{')
                    if json_start_index != -1:
                        json_candidate = full_data_str[json_start_index:]
                        data = json.loads(json_candidate)
                        _log_daemon_comm(f"Successfully received and parsed data (end of stream) from {host}:{port}.")
                        return data, None
                    else:
                        err_msg = f"No JSON object found in data from {host}:{port}. Received: {full_data_str}"
                        _log_daemon_comm(err_msg, level="warning")
                        return None, err_msg
                except json.JSONDecodeError as e:
                    err_msg = f"JSONDecodeError for data from {host}:{port}: {e}. Raw: {full_data_str}"
                    _log_daemon_comm(err_msg, level="error")
                    return None, err_msg
            else:
                err_msg = f"No data received from {host}:{port} after authentication."
                _log_daemon_comm(err_msg, level="warning")
                return None, err_msg

    except socket.timeout:
        err_msg = f"Connection to {host}:{port} timed out."
        _log_daemon_comm(err_msg, level="error")
        return None, err_msg
    except ConnectionRefusedError:
        err_msg = f"Connection to {host}:{port} refused. Is the daemon running?"
        _log_daemon_comm(err_msg, level="error")
        return None, err_msg
    except Exception as e:
        err_msg = f"An unexpected error occurred with {host}:{port}: {e}"
        current_app.logger.error(err_msg, exc_info=True)
        return None, err_msg
    return None, "Unknown error or no data received."


@bp.route('/monitor', methods=['GET', 'POST'])
@login_required
def monitor_dashboard():
    form = AddServerForm()
    if form.validate_on_submit():
        # Check for existing server by name (already in place)
        existing_server_by_name = MonitoredServer.query.filter_by(
            user_id=current_user.id,
            name=form.name.data
        ).first()
        if existing_server_by_name:
            flash('A server with this name already exists.', 'warning')
            return redirect(url_for('.monitor_dashboard')) # Redirect to show modal closed or handle via JS

        # Check for existing server by host and port
        existing_server_by_host_port = MonitoredServer.query.filter_by(
            user_id=current_user.id,
            host=form.host.data,
            port=form.port.data
        ).first()
        if existing_server_by_host_port:
            flash(f"The server {form.host.data}:{form.port.data} is already in your list.", 'warning')
            return redirect(url_for('.monitor_dashboard'))

        # If no duplicates, add the new server
        new_server = MonitoredServer(
            user_id=current_user.id,
            name=form.name.data,
            host=form.host.data,
            port=form.port.data,
            password=form.password.data,
            display_order=MonitoredServer.query.filter_by(user_id=current_user.id).count()
        )
        db.session.add(new_server)
        try:
            db.session.commit()
            flash(f"Server '{new_server.name}' added successfully!", 'success')
        except Exception as e: # Catch potential unique constraint violation if somehow missed
            db.session.rollback()
            current_app.logger.error(f"Error adding server: {e}")
            flash("Error adding server. It might already exist or there was a database issue.", "danger")

        return redirect(url_for('.monitor_dashboard'))

    servers = MonitoredServer.query.filter_by(user_id=current_user.id).order_by(MonitoredServer.display_order).all()
    # Pass the form to the template for the modal
    return render_template('tools/monitor.html', title="Server Monitor", servers=servers, form=form)

@bp.route('/monitor/delete/<int:server_id>', methods=['POST'])
@login_required
def delete_monitored_server(server_id):
    server = MonitoredServer.query.get_or_404(server_id)
    if server.user_id != current_user.id:
        abort(403) # Forbidden
    db.session.delete(server)
    db.session.commit()
    flash(f"Server '{server.name}' deleted.", 'success')
    return redirect(url_for('.monitor_dashboard'))

@bp.route('/monitor/fetch_data/<int:server_id>', methods=['GET'])
@login_required
def fetch_server_data_api(server_id):
    server = MonitoredServer.query.get_or_404(server_id)
    if server.user_id != current_user.id:
        return jsonify({'error': 'Forbidden'}), 403

    data, error = _request_info_from_daemon(server.host, server.port, server.password)

    if error:
        return jsonify({'error': str(error), 'server_name': server.name, 'server_id': server.id}), 500 # Internal Server Error or specific error
    if data:
        return jsonify({'data': data, 'server_name': server.name, 'server_id': server.id}), 200

    return jsonify({'error': 'No data received or unknown issue.', 'server_name': server.name, 'server_id': server.id}), 500

@bp.route('/monitor/reorder', methods=['POST'])
@login_required
def reorder_monitored_servers():
    ordered_ids = request.json.get('order')
    if not ordered_ids:
        return jsonify({'error': 'No order provided'}), 400

    servers_to_reorder = MonitoredServer.query.filter(
        MonitoredServer.user_id == current_user.id,
        MonitoredServer.id.in_(ordered_ids)
    ).all()

    server_map = {server.id: server for server in servers_to_reorder}

    for index, server_id_str in enumerate(ordered_ids):
        server_id = int(server_id_str)
        if server_id in server_map:
            server_map[server_id].display_order = index
        else:
            current_app.logger.warning(f"Server ID {server_id} not found for user {current_user.id} during reorder.")
            # Optionally, handle this error more gracefully

    try:
        db.session.commit()
        return jsonify({'success': True, 'message': 'Server order updated.'}), 200
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error reordering servers: {e}", exc_info=True)
        return jsonify({'error': 'Failed to update server order.'}), 500
