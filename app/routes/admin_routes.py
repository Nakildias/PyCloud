# app/routes/admin_routes.py
from functools import wraps # Ensure functools.wraps is imported

from flask import (
    Blueprint, render_template, redirect, url_for, flash, request,
    jsonify, current_app, abort, g # Added g for admin_settings template context
)
from flask_login import login_required, current_user
from sqlalchemy.exc import IntegrityError

# Import from app package
from app import db
from app import load_mail_settings_into_app_config
from app.models import User, Setting, GroupChatMessage
from app.forms import AdminSettingsForm, EditUserForm
from app.utils import get_user_storage_info
from app.config import DEFAULT_SETTINGS, DEFAULT_MAX_UPLOAD_MB_FALLBACK, DEFAULT_MAX_PHOTO_MB, DEFAULT_MAX_VIDEO_MB


# Define the blueprint
bp = Blueprint('admin', __name__, url_prefix='/admin')



# Decorator for admin-only routes
def admin_required(f):
    @wraps(f)
    @login_required
    def decorated_function(*args, **kwargs):
        if not current_user.is_admin:
            flash("You do not have permission to access this page.", "danger")
            return redirect(url_for('main_routes.index'))
        return f(*args, **kwargs)
    return decorated_function


@bp.route('/settings', methods=['GET', 'POST'])
@admin_required
def admin_settings():
    form = AdminSettingsForm()
    default_mail_config = {
        'MAIL_SERVER': DEFAULT_SETTINGS.get('MAIL_SERVER', 'smtp.example.com'),
        'MAIL_PORT': int(DEFAULT_SETTINGS.get('MAIL_PORT', 587)),
        'MAIL_USE_TLS': DEFAULT_SETTINGS.get('MAIL_USE_TLS', 'true').lower() == 'true',
        'MAIL_USE_SSL': DEFAULT_SETTINGS.get('MAIL_USE_SSL', 'false').lower() == 'true',
        'MAIL_USERNAME': DEFAULT_SETTINGS.get('MAIL_USERNAME', ''),
        'MAIL_PASSWORD': DEFAULT_SETTINGS.get('MAIL_PASSWORD', ''),
        'MAIL_DEFAULT_SENDER_NAME': DEFAULT_SETTINGS.get('MAIL_DEFAULT_SENDER_NAME', 'PyCloud'),
        'MAIL_DEFAULT_SENDER_EMAIL': DEFAULT_SETTINGS.get('MAIL_DEFAULT_SENDER_EMAIL', 'noreply@example.com'),
        'allow_registration': DEFAULT_SETTINGS.get('allow_registration', 'true'),
        'default_storage_limit_mb': DEFAULT_SETTINGS.get('default_storage_limit_mb', '1024'),
        'ollama_api_url': DEFAULT_SETTINGS.get('ollama_api_url', ''),
        'ollama_model': DEFAULT_SETTINGS.get('ollama_model', 'llama3.2:3b'),
    }

    if form.validate_on_submit():
        try:
            Setting.set('allow_registration', str(form.allow_registration.data).lower())
            Setting.set('default_storage_limit_mb', str(form.default_storage_limit_mb.data))
            Setting.set('max_upload_size_mb', str(form.max_upload_size_mb.data))
            Setting.set('ollama_api_url', form.ollama_api_url.data or '')
            Setting.set('ollama_model', form.ollama_model.data or '')

            Setting.set('MAIL_SERVER', form.mail_server.data or '')
            Setting.set('MAIL_PORT', str(form.mail_port.data) if form.mail_port.data is not None else str(default_mail_config['MAIL_PORT']))
            Setting.set('MAIL_USE_TLS', str(form.mail_use_tls.data).lower())
            Setting.set('MAIL_USE_SSL', str(form.mail_use_ssl.data).lower())
            Setting.set('MAIL_USERNAME', form.mail_username.data or '')
            if form.mail_password.data:
                Setting.set('MAIL_PASSWORD', form.mail_password.data)
            Setting.set('MAIL_DEFAULT_SENDER_NAME', form.mail_default_sender_name.data or '')
            Setting.set('MAIL_DEFAULT_SENDER_EMAIL', form.mail_default_sender_email.data or '')

            db.session.commit()
            flash('Settings updated successfully!', 'success')
            current_app.logger.info(f"Admin settings saved by {current_user.username}.")

            # REMOVE the incorrect local import:
            # from app import configure_mail_from_db  # <--- DELETE THIS LINE

            # USE the correctly imported function:
            load_mail_settings_into_app_config(current_app._get_current_object()) # <--- USE THIS LINE
            current_app.logger.info("Mail configuration reloaded into app.config after admin save.")

            return redirect(url_for('admin.admin_settings'))
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error updating admin settings: {e}", exc_info=True)
            flash(f'Failed to update settings: {str(e)}', 'danger')
    elif request.method == 'GET':
        try:
            form.allow_registration.data = (Setting.get('allow_registration', default_mail_config['allow_registration']) == 'true')
            form.default_storage_limit_mb.data = int(Setting.get('default_storage_limit_mb', default_mail_config['default_storage_limit_mb']))
            form.max_upload_size_mb.data = int(Setting.get('max_upload_size_mb', str(DEFAULT_MAX_UPLOAD_MB_FALLBACK)))
            form.ollama_api_url.data = Setting.get('ollama_api_url', default_mail_config['ollama_api_url'])
            form.ollama_model.data = Setting.get('ollama_model', default_mail_config['ollama_model'])
            form.mail_server.data = Setting.get('MAIL_SERVER', default_mail_config['MAIL_SERVER'])
            form.mail_port.data = int(Setting.get('MAIL_PORT', str(default_mail_config['MAIL_PORT'])))
            form.mail_use_tls.data = (Setting.get('MAIL_USE_TLS', 'true' if default_mail_config['MAIL_USE_TLS'] else 'false').lower() == 'true')
            form.mail_use_ssl.data = (Setting.get('MAIL_USE_SSL', 'true' if default_mail_config['MAIL_USE_SSL'] else 'false').lower() == 'true')
            form.mail_username.data = Setting.get('MAIL_USERNAME', default_mail_config['MAIL_USERNAME'])
            form.mail_default_sender_name.data = Setting.get('MAIL_DEFAULT_SENDER_NAME', default_mail_config['MAIL_DEFAULT_SENDER_NAME'])
            form.mail_default_sender_email.data = Setting.get('MAIL_DEFAULT_SENDER_EMAIL', default_mail_config['MAIL_DEFAULT_SENDER_EMAIL'])

            g.max_photo_upload_mb = Setting.get('max_photo_upload_mb', str(DEFAULT_MAX_PHOTO_MB))
            g.max_video_upload_mb = Setting.get('max_video_upload_mb', str(DEFAULT_MAX_VIDEO_MB))

        except ValueError as ve:
            current_app.logger.error(f"ValueError populating admin settings form: {ve}. Check if DB settings are valid.", exc_info=True)
            flash("Error loading some settings. Values might be corrupted or of unexpected type in DB.", "warning")
            g.max_photo_upload_mb = str(DEFAULT_MAX_PHOTO_MB)
            g.max_video_upload_mb = str(DEFAULT_MAX_VIDEO_MB)
        except Exception as e_get:
            current_app.logger.error(f"Unexpected error populating admin_settings form: {e_get}", exc_info=True)
            flash("An unexpected error occurred while loading settings.", "danger")
            g.max_photo_upload_mb = str(DEFAULT_MAX_PHOTO_MB)
            g.max_video_upload_mb = str(DEFAULT_MAX_VIDEO_MB)

    return render_template('admin/admin_settings.html', title='Admin Settings', form=form,
                           max_photo_upload_mb=getattr(g, 'max_photo_upload_mb', str(DEFAULT_MAX_PHOTO_MB)),
                           max_video_upload_mb=getattr(g, 'max_video_upload_mb', str(DEFAULT_MAX_VIDEO_MB)))



@bp.route('/users')
@admin_required # Apply the decorator
def admin_list_users():
    try:
        users = User.query.order_by(User.username).all()
        users_with_storage = [{'user': u, 'storage': get_user_storage_info(u)} for u in users]
    except Exception as e:
        current_app.logger.error(f"Error fetching users for admin list: {e}", exc_info=True)
        flash("Error retrieving user list.", "danger"); users_with_storage = []
    return render_template('admin/admin_users.html', title='Manage Users', users_with_storage=users_with_storage)


@bp.route('/user/edit/<int:user_id>', methods=['GET', 'POST'])
@admin_required # Apply the decorator
def admin_edit_user(user_id):
    user_to_edit = User.query.get_or_404(user_id)
    form = EditUserForm(obj=user_to_edit, original_username=user_to_edit.username, original_email=user_to_edit.email)

    if form.validate_on_submit():
        original_username_log = user_to_edit.username
        user_to_edit.username = form.username.data
        user_to_edit.email = form.email.data
        if user_to_edit.id != current_user.id:
            user_to_edit.is_admin = form.is_admin.data
        else:
            user_to_edit.is_admin = True # Admin cannot un-admin self

        user_to_edit.storage_limit_mb = form.storage_limit_mb.data if form.storage_limit_mb.data is not None and form.storage_limit_mb.data > 0 else None
        user_to_edit.max_file_size = form.max_file_size.data if form.max_file_size.data is not None and form.max_file_size.data > 0 else None

        if form.password.data:
            if form.password.data == form.confirm_password.data: # Should be caught by EqualTo
                user_to_edit.set_password(form.password.data)
                flash('Password updated successfully.', 'info')
            else:
                # This path should ideally not be hit if EqualTo validator works.
                form.password.errors.append("Passwords must match.")
                return render_template('admin/admin_edit_user.html', title=f'Edit User: {user_to_edit.username}', form=form, user_to_edit=user_to_edit)
        try:
            db.session.commit()
            flash(f'User "{user_to_edit.username}" updated successfully.', 'success')
            current_app.logger.info(f"Admin {current_user.username} updated user {original_username_log} (now {user_to_edit.username}, ID: {user_id}).")
            return redirect(url_for('admin.admin_list_users'))
        except IntegrityError as e:
            db.session.rollback()
            current_app.logger.warning(f"Update failed for user {user_id} (username: {user_to_edit.username}) due to integrity error: {e}")
            if 'user.username' in str(e).lower(): form.username.errors.append("This username is already taken.")
            elif 'user.email' in str(e).lower(): form.email.errors.append("This email is already registered.")
            else: flash('Database error: Could not update user. Check logs.', 'danger')
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error updating user {user_id} by admin {current_user.username}: {e}", exc_info=True)
            flash('An unexpected error occurred while updating the user.', 'danger')

    elif request.method == 'GET':
        # Form is pre-populated by obj=user_to_edit, but can re-assign if needed
        form.username.data = user_to_edit.username
        form.email.data = user_to_edit.email
        form.is_admin.data = user_to_edit.is_admin
        form.storage_limit_mb.data = user_to_edit.storage_limit_mb
        form.max_file_size.data = user_to_edit.max_file_size

    return render_template('admin/admin_edit_user.html', title=f'Edit User: {user_to_edit.username}', form=form, user_to_edit=user_to_edit)


@bp.route('/disable_user/<int:user_id>', methods=['POST'])
@admin_required # Apply the decorator
def disable_user(user_id):
    user = User.query.get_or_404(user_id)
    if user.id == current_user.id:
        flash('You cannot disable yourself.', 'danger')
    else:
        user.is_disabled = True
        db.session.commit()
        flash(f'User {user.username} has been disabled.', 'success')
    return redirect(url_for('admin.admin_list_users'))


@bp.route('/enable_user/<int:user_id>', methods=['POST'])
@admin_required # Apply the decorator
def enable_user(user_id):
    user = User.query.get_or_404(user_id)
    user.is_disabled = False
    db.session.commit()
    flash(f'User {user.username} has been enabled.', 'success')
    return redirect(url_for('admin.admin_list_users'))


@bp.route('/delete_user/<int:user_id>', methods=['POST'])
@admin_required # Apply the decorator
def delete_user(user_id):
    user_to_delete = User.query.get_or_404(user_id)
    if user_to_delete.id == current_user.id:
        flash("You cannot delete yourself.", "danger")
    elif not user_to_delete.is_disabled: # Ensure user is disabled first as per original logic
        flash(f'User {user_to_delete.username} must be disabled before they can be deleted.', 'warning')
    else:
        try:
            # Add logic here to delete user's files from disk if desired, before DB delete
            db.session.delete(user_to_delete) # DB cascades should handle related data
            db.session.commit()
            flash(f'User {user_to_delete.username} has been deleted.', 'success')
        except Exception as e:
            db.session.rollback()
            flash(f'Error deleting user {user_to_delete.username}: {str(e)}', 'danger')
            current_app.logger.error(f"Error deleting user {user_id}: {e}", exc_info=True)
    return redirect(url_for('admin.admin_list_users'))


@bp.route('/group_chat/delete/<int:message_id>', methods=['POST'])
@admin_required # Apply the decorator
def admin_delete_group_chat_message(message_id):
    message = GroupChatMessage.query.get_or_404(message_id)
    is_ajax = request.accept_mimetypes.accept_json and not request.accept_mimetypes.accept_html
    try:
        # Note: This does not delete the associated file from storage by default
        # Add file deletion logic if admin deletion should also remove the file
        db.session.delete(message)
        db.session.commit()
        current_app.logger.info(f"Admin {current_user.username} deleted group chat message ID {message_id}")
        if is_ajax:
            return jsonify({"status": "success", "message": "Message deleted."})
        flash("Message deleted successfully.", "success")
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Admin {current_user.username} failed to delete GCM ID {message_id}: {e}", exc_info=True)
        if is_ajax:
            return jsonify({"status": "error", "message": "Failed to delete message."}), 500
        flash("Failed to delete message.", "danger")
    # Redirect to the group chat page, assuming it's in 'chat_routes' blueprint
    return redirect(url_for('chat_routes.group_chat'))
