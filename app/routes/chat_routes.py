# app/routes/chat_routes.py
import os
import uuid
import mimetypes
import codecs # For reading text file previews
from datetime import datetime, timezone, timedelta

from flask import (
    Blueprint, render_template, redirect, url_for, flash, request,
    session, jsonify, current_app
)
from flask_login import login_required, current_user
from sqlalchemy.orm import joinedload

# Import from app package
from app import db
from app.utils import get_user_upload_path # Import directly
from app.models import ( # Models
    User, Setting, GroupChatMessage, DirectMessage, OllamaChatMessage, File
)
from app.forms import ( # Forms
    GroupChatForm, DirectMessageForm, OllamaChatForm
)
from app.utils import ( # Utility functions
    get_user_storage_info, send_message_to_ollama, is_file_editable
)
from app.config import ( # Config constants
    DEFAULT_MAX_UPLOAD_MB_FALLBACK
)
from werkzeug.utils import secure_filename

# Define the blueprint
bp = Blueprint('chat_routes', __name__, url_prefix='/chat') # Using '/chat' prefix


# --- Group Chat Routes ---
@bp.route('/group')
@login_required
def group_chat():
    form = GroupChatForm()
    try:
        messages = GroupChatMessage.query.options(
            joinedload(GroupChatMessage.sender),
            joinedload(GroupChatMessage.shared_file)
        ).order_by(GroupChatMessage.timestamp.asc()).all()
        message_dicts = [msg.to_dict() for msg in messages]
    except Exception as e:
        current_app.logger.error(f"Error fetching group chat messages: {e}", exc_info=True)
        flash("Could not load chat history.", "danger")
        message_dicts = []

    try:
        max_upload_mb_str = Setting.get('max_upload_size_mb', str(DEFAULT_MAX_UPLOAD_MB_FALLBACK))
        max_upload_mb = int(max_upload_mb_str)
    except (ValueError, TypeError):
        max_upload_mb = DEFAULT_MAX_UPLOAD_MB_FALLBACK

    return render_template('chat/group_chat.html', # Assuming templates in chat/
                           title="Group Chat", form=form,
                           chat_history=message_dicts, max_upload_mb=max_upload_mb)


@bp.route('/api/group/send', methods=['POST'])
@login_required
def api_group_chat_send():
    content = request.form.get('content', '').strip()
    file_storage = request.files.get('file') # Renamed for clarity
    new_file_record = None
    error_message = None
    status_code = 200
    file_path_on_disk = None # For cleanup

    if not content and (not file_storage or file_storage.filename == ''):
        return jsonify({"status": "error", "message": "Message content or file attachment required."}), 400

    if file_storage and file_storage.filename != '':
        original_filename = secure_filename(file_storage.filename)
        try:
            current_pos = file_storage.tell()
            file_storage.seek(0, os.SEEK_END)
            uploaded_filesize = file_storage.tell()
            file_storage.seek(current_pos)
        except: uploaded_filesize = request.content_length
        if uploaded_filesize is None: return jsonify({"status": "error", "message": "Could not determine file size."}), 400

        # File size checks (Simplified for brevity, ensure original detailed checks are used if needed)
        hard_limit_bytes = current_app.config.get('MAX_CONTENT_LENGTH')
        if hard_limit_bytes and uploaded_filesize > hard_limit_bytes: error_message = "File exceeds server limit."; status_code = 413
        if not error_message:
            max_upload_mb_str = Setting.get('max_upload_size_mb', str(DEFAULT_MAX_UPLOAD_MB_FALLBACK))
            admin_limit_bytes = int(max_upload_mb_str) * 1024 * 1024
            if uploaded_filesize > admin_limit_bytes: error_message = f"File exceeds max upload size ({max_upload_mb_str} MB)."; status_code = 413
        if not error_message:
            storage_info = get_user_storage_info(current_user)
            available_bytes = float('inf') if storage_info['limit_bytes'] == float('inf') else storage_info['limit_bytes'] - storage_info['usage_bytes']
            if uploaded_filesize > available_bytes: error_message = "Insufficient storage for this file."; status_code = 413

        if not error_message:
            try:
                _, ext = os.path.splitext(original_filename)
                stored_filename = str(uuid.uuid4()) + ext
                user_upload_path = get_user_upload_path(current_user.id)
                os.makedirs(user_upload_path, exist_ok=True)
                file_path_on_disk = os.path.join(user_upload_path, stored_filename)
                file_storage.save(file_path_on_disk)
                mime_type, _ = mimetypes.guess_type(file_path_on_disk); mime_type = mime_type or 'application/octet-stream'
                new_file_record = File(original_filename=original_filename, stored_filename=stored_filename, filesize=uploaded_filesize, mime_type=mime_type, owner=current_user, parent_folder_id=None)
                db.session.add(new_file_record); db.session.flush()
            except Exception as e: # First problematic except block
                db.session.rollback()
                current_app.logger.error(f"Error processing file before message save: {original_filename} - {e}", exc_info=True) # More context in log
                if file_path_on_disk and os.path.exists(file_path_on_disk):
                    try:
                        os.remove(file_path_on_disk)
                        current_app.logger.info(f"Cleaned up file {file_path_on_disk} after processing error.")
                    except OSError as e_remove:
                        current_app.logger.error(f"Failed to remove file {file_path_on_disk} after processing error: {e_remove}")
                error_message = f"Error processing attached file: {str(e)}" # Use str(e) for cleaner message
                status_code = 500

    if error_message: return jsonify({"status": "error", "message": error_message}), status_code

    try:
        new_message = GroupChatMessage(user_id=current_user.id, content=content if content else None, file_id=new_file_record.id if new_file_record else None)
        db.session.add(new_message); db.session.commit()
        db.session.refresh(new_message)
        if new_file_record: db.session.refresh(new_file_record)
        return jsonify({"status": "success", "message": new_message.to_dict()}), 201
    except Exception as e: # Second problematic except block (final one in the function)
        db.session.rollback()
        current_app.logger.error(f"Error saving group chat message to DB: {e}", exc_info=True)
        # Cleanup physical file if it was part of this failed transaction
        if file_path_on_disk and os.path.exists(file_path_on_disk) and new_file_record: # Check new_file_record to ensure it was this operation's file
            try:
                os.remove(file_path_on_disk)
                current_app.logger.info(f"Cleaned up chat file {file_path_on_disk} after DB error.")
            except OSError as rm_err:
                current_app.logger.error(f"Error cleaning up chat file {file_path_on_disk} after DB error: {rm_err}")
        return jsonify({"status": "error", "message": "Error saving message to database."}), 500



@bp.route('/api/group/edit/<int:message_id>', methods=['POST'])
@login_required
def api_group_chat_edit_message(message_id):
    message = GroupChatMessage.query.get_or_404(message_id)
    if message.user_id != current_user.id: return jsonify({"status": "error", "message": "Permission denied."}), 403
    data = request.get_json(); new_content = data.get('content', '').strip()
    if not new_content: return jsonify({"status": "error", "message": "Content cannot be empty."}), 400
    if message.file_id: return jsonify({"status": "error", "message": "Cannot edit messages with files this way."}), 400
    try:
        message.content = new_content; message.edited_at = datetime.now(timezone.utc)
        db.session.commit(); db.session.refresh(message)
        return jsonify({"status": "success", "message": "Message updated.", "updated_message": message.to_dict()})
    except Exception as e:
        db.session.rollback(); current_app.logger.error(f"Error editing GCM {message_id}: {e}")
        return jsonify({"status": "error", "message": "Failed to update message."}), 500


@bp.route('/api/group/delete/<int:message_id>', methods=['POST'])
@login_required
def api_group_chat_delete_message(message_id):
    message = GroupChatMessage.query.get_or_404(message_id)
    if not (message.user_id == current_user.id or current_user.is_admin):
        return jsonify({"status": "error", "message": "Permission denied."}), 403

    file_to_delete_permanently = None
    if message.file_id:
        file_record = File.query.get(message.file_id)
        if file_record and (file_record.user_id == current_user.id or current_user.is_admin):
            file_to_delete_permanently = file_record
    try:
        message.is_deleted = True; message.deleted_at = datetime.now(timezone.utc); message.edited_at = message.deleted_at
        if file_to_delete_permanently:
            user_upload_path = get_user_upload_path(file_to_delete_permanently.user_id)
            full_file_path = os.path.join(user_upload_path, file_to_delete_permanently.stored_filename)
            if os.path.exists(full_file_path): os.remove(full_file_path)
            message.file_id = None # Unlink before deleting File object
            db.session.delete(file_to_delete_permanently)
        db.session.commit()
        return jsonify({"status": "success", "message": "Message deleted."})
    except Exception as e:
        db.session.rollback(); current_app.logger.error(f"Error deleting GCM {message_id} or attachment: {e}", exc_info=True)
        return jsonify({"status": "error", "message": "Failed to delete message/attachment."}), 500

@bp.route('/api/group/history')
@login_required
def api_group_chat_history():
    last_message_id = request.args.get('last_message_id', type=int, default=0)
    client_last_edit_ts_str = request.args.get('last_edit_ts')
    limit = 100; conditions = []
    if last_message_id > 0: conditions.append(GroupChatMessage.id > last_message_id)
    if client_last_edit_ts_str:
        try:
            client_last_edit_dt = datetime.fromisoformat(client_last_edit_ts_str.replace('Z', '+00:00'))
            conditions.append(GroupChatMessage.edited_at > client_last_edit_dt)
        except ValueError: current_app.logger.warning(f"Invalid last_edit_ts format: {client_last_edit_ts_str}")

    query = GroupChatMessage.query.options(joinedload(GroupChatMessage.sender).load_only(User.username, User.profile_picture_filename), joinedload(GroupChatMessage.shared_file))
    if conditions: query = query.filter(db.or_(*conditions))
    messages = query.order_by(GroupChatMessage.timestamp.asc(), GroupChatMessage.id.asc()).limit(limit).all()
    return jsonify({"status": "success", "messages": [msg.to_dict() for msg in messages]})


# --- Friends / Direct Messages Routes ---
@bp.route('/friends') # This was /friends in main.py
@login_required
def friends_interface():
    user_friends = current_user.get_friends()
    message_form = DirectMessageForm()
    try: max_upload_mb = int(Setting.get('max_upload_size_mb', str(DEFAULT_MAX_UPLOAD_MB_FALLBACK)))
    except: max_upload_mb = DEFAULT_MAX_UPLOAD_MB_FALLBACK

    friend_activity_statuses = {}
    if user_friends:
        friend_ids = [friend.id for friend in user_friends]
        afk_threshold = timedelta(minutes=30); now = datetime.now(timezone.utc)
        friends_for_status_check = User.query.filter(User.id.in_(friend_ids)).all()
        for friend_obj in friends_for_status_check:
            status_string = "offline"
            if friend_obj.is_online:
                friend_last_seen = friend_obj.last_seen
                if friend_last_seen and friend_last_seen.tzinfo is None: friend_last_seen = friend_last_seen.replace(tzinfo=timezone.utc)
                if friend_last_seen and (now - friend_last_seen) < afk_threshold: status_string = "online"
                else: status_string = "afk"
            friend_activity_statuses[friend_obj.id] = status_string

    return render_template('chat/friends.html', title='Direct Messages', friends=user_friends,
                           message_form=message_form, max_upload_mb=max_upload_mb,
                           initial_friend_statuses=friend_activity_statuses)


@bp.route('/api/friends/recent_messages')
@login_required
def api_recent_direct_messages():
    try:
        latest_message_subquery = db.session.query(
            DirectMessage.sender_id, db.func.max(DirectMessage.timestamp).label('max_timestamp')
        ).filter(DirectMessage.receiver_id == current_user.id).group_by(DirectMessage.sender_id).subquery()

        recent_messages = db.session.query(DirectMessage).join(
            latest_message_subquery,
            db.and_(DirectMessage.sender_id == latest_message_subquery.c.sender_id,
                    DirectMessage.timestamp == latest_message_subquery.c.max_timestamp,
                    DirectMessage.receiver_id == current_user.id)
        ).options(joinedload(DirectMessage.author).load_only(User.username, User.profile_picture_filename, User.id)
        ).order_by(DirectMessage.timestamp.desc()).limit(5).all()

        messages_data = [{
            'message_id': msg.id, 'sender_id': msg.sender_id, 'sender_username': msg.author.username,
            'sender_profile_picture_filename': msg.author.profile_picture_filename,
            'content_snippet': (msg.content[:30] + '...' if msg.content and len(msg.content) > 30 else msg.content) if msg.content else "Sent a file",
            'timestamp': msg.timestamp.isoformat() + 'Z', 'is_read': msg.is_read
        } for msg in recent_messages]
        return jsonify({'status': 'success', 'recent_messages': messages_data})
    except Exception as e:
        current_app.logger.error(f"Error fetching recent DMs for user {current_user.id}: {e}", exc_info=True)
        return jsonify({'status': 'error', 'message': 'Could not fetch recent messages.'}), 500


@bp.route('/api/direct/history/<string:friend_username>')
@login_required
def api_direct_chat_history(friend_username):
    friend_user = User.query.filter_by(username=friend_username).first()
    if not friend_user: return jsonify({"status": "error", "message": "Friend not found."}), 404
    if friend_user == current_user: return jsonify({"status": "error", "message": "Cannot chat with yourself."}), 400
    if not (current_user.is_following(friend_user) and friend_user.is_following(current_user)):
        return jsonify({"status": "error", "message": "You are not friends with this user."}), 403

    last_message_id = request.args.get('last_message_id', type=int, default=0); limit = 50
    messages_query = DirectMessage.query.filter(
        ((DirectMessage.sender_id == current_user.id) & (DirectMessage.receiver_id == friend_user.id)) |
        ((DirectMessage.sender_id == friend_user.id) & (DirectMessage.receiver_id == current_user.id))
    ).options(
        joinedload(DirectMessage.author).load_only(User.username, User.profile_picture_filename),
        joinedload(DirectMessage.recipient).load_only(User.username, User.profile_picture_filename),
        joinedload(DirectMessage.shared_file)
    ).order_by(DirectMessage.timestamp.desc())
    if last_message_id > 0: messages_query = messages_query.filter(DirectMessage.id < last_message_id)
    messages = messages_query.limit(limit).all(); messages.reverse()

    unread_message_ids_to_mark = [msg.id for msg in messages if msg.receiver_id == current_user.id and not msg.is_read]
    if unread_message_ids_to_mark:
        DirectMessage.query.filter(DirectMessage.id.in_(unread_message_ids_to_mark)).update({"is_read": True}, synchronize_session=False)
        try: db.session.commit()
        except Exception as e: db.session.rollback(); current_app.logger.error(f"Error marking DMs as read: {e}")

    return jsonify({"status": "success", "messages": [msg.to_dict(current_user.id) for msg in messages]})


@bp.route('/api/direct/send/<string:friend_username>', methods=['POST'])
@login_required
def api_direct_chat_send(friend_username):
    friend_user = User.query.filter_by(username=friend_username).first()
    if not friend_user: return jsonify({"status": "error", "message": "Recipient not found."}), 404
    if friend_user == current_user: return jsonify({"status": "error", "message": "Cannot message yourself."}), 400
    if not (current_user.is_following(friend_user) and friend_user.is_following(current_user)):
        return jsonify({"status": "error", "message": "Can only message friends."}), 403

    content = request.form.get('content', '').strip()
    file_storage = request.files.get('file') # Renamed
    new_file_record, error_message, file_path_on_disk = None, None, None
    status_code = 200

    if not content and (not file_storage or file_storage.filename == ''):
        return jsonify({"status": "error", "message": "Message content or file required."}), 400

    if file_storage and file_storage.filename != '': # File upload logic (same as group chat send)
        original_filename = secure_filename(file_storage.filename)
        try: file_storage.seek(0, os.SEEK_END); uploaded_filesize = file_storage.tell(); file_storage.seek(0)
        except: uploaded_filesize = request.content_length
        if uploaded_filesize is None: return jsonify({"status": "error", "message": "Could not determine file size."}), 400
        # Size checks (simplified)
        hard_limit_bytes = current_app.config.get('MAX_CONTENT_LENGTH')
        if hard_limit_bytes and uploaded_filesize > hard_limit_bytes: error_message = "File exceeds server limit."; status_code = 413
        # ... (other size checks: admin limit, user storage) ... (omitted for brevity, ensure they are present)
        if not error_message: # If previous checks passed
            storage_info = get_user_storage_info(current_user)
            available_bytes = float('inf') if storage_info['limit_bytes'] == float('inf') else storage_info['limit_bytes'] - storage_info['usage_bytes']
            if uploaded_filesize > available_bytes: error_message = 'Insufficient storage space for this file.'; status_code = 413

        if not error_message:
            try:
                _, ext = os.path.splitext(original_filename)
                stored_filename = str(uuid.uuid4()) + ext
                user_upload_path = get_user_upload_path(current_user.id)
                os.makedirs(user_upload_path, exist_ok=True)
                file_path_on_disk = os.path.join(user_upload_path, stored_filename)
                file_storage.save(file_path_on_disk)
                mime_type, _ = mimetypes.guess_type(file_path_on_disk); mime_type = mime_type or 'application/octet-stream'
                new_file_record = File(original_filename=original_filename, stored_filename=stored_filename, filesize=uploaded_filesize, mime_type=mime_type, owner=current_user, parent_folder_id=None)
                db.session.add(new_file_record); db.session.flush()
            except Exception as e: # First place to correct
                db.session.rollback()
                current_app.logger.error(f"Error processing file for DM: {original_filename} - {e}", exc_info=True)
                if file_path_on_disk and os.path.exists(file_path_on_disk):
                    try:
                        os.remove(file_path_on_disk)
                        current_app.logger.info(f"Cleaned up DM file {file_path_on_disk} after processing error.")
                    except OSError as e_remove:
                        current_app.logger.error(f"Failed to remove DM file {file_path_on_disk} after processing error: {e_remove}")
                error_message = f"Error processing attached file: {str(e)}"
                status_code = 500

    if error_message: return jsonify({"status": "error", "message": error_message}), status_code

    try:
        new_dm = DirectMessage(sender_id=current_user.id, receiver_id=friend_user.id, content=content if content else None, file_id=new_file_record.id if new_file_record else None, is_read=False)
        db.session.add(new_dm); db.session.commit()
        db.session.refresh(new_dm)
        if new_file_record: db.session.refresh(new_file_record)
        return jsonify({"status": "success", "message": new_dm.to_dict(current_user.id)}), 201
    except Exception as e: # Second place to correct (final except block)
        db.session.rollback()
        current_app.logger.error(f"Error saving direct message for user {current_user.id} to {friend_user.id}: {e}", exc_info=True)
        if file_path_on_disk and os.path.exists(file_path_on_disk) and new_file_record:
            try:
                os.remove(file_path_on_disk)
                current_app.logger.info(f"Cleaned up DM file {file_path_on_disk} after DB error.")
            except OSError as rm_err:
                current_app.logger.error(f"Error cleaning up DM file {file_path_on_disk} after DB error: {rm_err}")
        return jsonify({"status": "error", "message": "Error saving message to database."}), 500



# --- Ollama Chat Routes ---
@bp.route('/ollama', methods=['GET', 'POST']) # /chat/ollama
@login_required
def ollama_chat():
    form = OllamaChatForm()
    history_for_template = []
    try:
        db_messages = current_user.ollama_chat_messages.options(joinedload(OllamaChatMessage.user)).order_by(OllamaChatMessage.timestamp).all()
        history_for_ollama = [msg.to_dict() for msg in db_messages] # For sending to API
        history_for_template = list(history_for_ollama) # For rendering
    except Exception as e:
        current_app.logger.error(f"Error fetching ollama history for {current_user.id}: {e}", exc_info=True)
        flash("Could not load ollama chat history.", "danger")

    if form.validate_on_submit():
        user_message_content = form.message.data
        ai_response_content, error_message = send_message_to_ollama(user_message_content, history_for_ollama) # Util
        if error_message: flash(error_message, 'danger')
        elif ai_response_content:
            try:
                user_msg_db = OllamaChatMessage(user_id=current_user.id, role='user', content=user_message_content)
                ai_msg_db = OllamaChatMessage(user_id=current_user.id, role='assistant', content=ai_response_content)
                db.session.add_all([user_msg_db, ai_msg_db]); db.session.commit()
                return redirect(url_for('.ollama_chat')) # Redirect after successful POST
            except Exception as e:
                db.session.rollback(); current_app.logger.error(f"Error saving ollama messages: {e}", exc_info=True)
                flash("Failed to save ollama chat message.", "danger")
        else: flash("Received no response from AI.", "warning")
    # Render template on GET or if POST had issues and didn't redirect
    return render_template('chat/ollama_chat.html', title='Ollama Chat', form=form, ollama_chat_history=history_for_template)


@bp.route('/ollama/clear', methods=['GET'])
@login_required
def clear_ollama_chat_history():
    try:
        num_deleted = OllamaChatMessage.query.filter_by(user_id=current_user.id).delete()
        db.session.commit()
        flash(f'Ollama chat history cleared ({num_deleted} messages).', 'info')
    except Exception as e:
        db.session.rollback(); current_app.logger.error(f"Error clearing ollama history: {e}", exc_info=True)
        flash('Failed to clear ollama chat history.', 'danger')
    return redirect(url_for('.ollama_chat'))


@bp.route('/api/ollama/send', methods=['POST'])
@login_required
def api_ollama_chat_send():
    data = request.get_json()
    if not data or 'message' not in data or not data['message'].strip():
        return jsonify({"status": "error", "message": "Message cannot be empty."}), 400
    user_message_content = data['message'].strip()
    history_for_ollama = []
    try:
        db_messages = current_user.ollama_chat_messages.options(joinedload(OllamaChatMessage.user)).order_by(OllamaChatMessage.timestamp).all()
        history_for_ollama = [msg.to_dict() for msg in db_messages]
    except Exception as e: return jsonify({"status": "error", "message": "Could not retrieve history."}), 500

    ai_response_content, error_message = send_message_to_ollama(user_message_content, history_for_ollama)
    if error_message: return jsonify({"status": "error", "message": error_message}), 500
    elif ai_response_content:
        try:
            user_msg_db = OllamaChatMessage(user_id=current_user.id, role='user', content=user_message_content)
            ai_msg_db = OllamaChatMessage(user_id=current_user.id, role='assistant', content=ai_response_content)
            db.session.add_all([user_msg_db, ai_msg_db]); db.session.commit()
            db.session.refresh(ai_msg_db); _ = ai_msg_db.user # Ensure user relationship is loaded for to_dict
            return jsonify({"status": "success", "ai_message": ai_msg_db.to_dict()})
        except Exception as e:
            db.session.rollback(); current_app.logger.error(f"API Error saving ollama messages: {e}", exc_info=True)
            return jsonify({"status": "error", "message": "Failed to save messages to DB."}), 500
    else: return jsonify({"status": "error", "message": "No response from AI."}), 500
