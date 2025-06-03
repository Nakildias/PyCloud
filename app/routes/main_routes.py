# app/routes/main_routes.py
import os
import json
from datetime import datetime, timezone
from flask import (
    Blueprint, render_template, redirect, url_for, flash, request,
    session, jsonify, current_app, g, send_from_directory, abort
)
from flask_login import login_required, current_user
from sqlalchemy import or_ # For find_people search

# Import from app package
from app import db # db is correctly initialized in app/__init__ and can be imported like this
from app.utils import get_user_upload_path # Import directly from where it's defined
from app.models import User, Setting, Post, Comment, Notification, DirectMessage, File # Models
from app.forms import EditProfileForm, CreatePostForm, CommentForm, DirectMessageForm # Forms
from app.utils import (
    get_user_storage_info, create_notification,
    get_post_media_path, is_file_editable # Utility functions
)
from app.config import (
    DEFAULT_SETTINGS, AVAILABLE_THEMES,
    VIEWABLE_IMAGE_MIMES, VIEWABLE_VIDEO_MIMES, VIDEO_THUMBNAIL_FOLDER,
    DEFAULT_MAX_UPLOAD_MB_FALLBACK, DEFAULT_MAX_PHOTO_MB, DEFAULT_MAX_VIDEO_MB
)
from werkzeug.utils import secure_filename # For profile picture
from PIL import Image, ImageSequence # For profile picture
from flask_wtf.csrf import generate_csrf # For social macros if needed there
from sqlalchemy.orm import aliased # For sorting posts by shares

# Define the blueprint
bp = Blueprint('main_routes', __name__) # No url_prefix, these are top-level routes


@bp.route('/')
def index():
    if current_user.is_authenticated:
        # Redirect to file listing, assuming it will be in 'file_routes.list_files'
        return redirect(url_for('file_routes.list_files'))
    return redirect(url_for('auth.login'))


@bp.route('/settings', methods=['GET'])
@login_required
def user_settings_page():
    available_cm_themes = get_available_codemirror_themes()
    current_cm_theme = current_user.preferred_codemirror_theme if current_user.preferred_codemirror_theme else 'default' # Assuming 'default' or a specific like 'material.css'
    # Ensure the current_cm_theme is valid, if not, fallback
    if current_cm_theme not in available_cm_themes and 'default.css' in available_cm_themes : # or your actual default
         current_cm_theme = 'default.css'
    elif current_cm_theme not in available_cm_themes and available_cm_themes:
         current_cm_theme = next(iter(available_cm_themes)) # Fallback to the first available


    return render_template(
        'user_settings.html',
        title="User Settings",
        available_themes=AVAILABLE_THEMES, # Your existing app themes
        current_theme_name=current_user.preferred_theme,
        available_codemirror_themes=available_cm_themes,
        current_codemirror_theme_name=current_cm_theme
    )


@bp.route('/change-theme', methods=['POST'])
@login_required
def change_theme():
    new_theme_file = request.form.get('theme')
    if not new_theme_file or new_theme_file not in AVAILABLE_THEMES:
        flash("Invalid theme selected.", "error")
        return redirect(url_for('main_routes.user_settings_page'))

    try:
        current_user.preferred_theme = new_theme_file
        db.session.commit()
        flash(f"Theme changed to {AVAILABLE_THEMES[new_theme_file]}.", "success")
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Database error saving theme for user {current_user.id}: {e}")
        flash("Database error saving theme preference.", "error")
    return redirect(url_for('main_routes.user_settings_page'))


def get_available_codemirror_themes():
    themes = {}
    try:
        theme_dir = os.path.join(current_app.static_folder, 'codemirror', 'theme')
        if os.path.isdir(theme_dir):
            for filename in os.listdir(theme_dir):
                if filename.endswith(".css"):
                    display_name = os.path.splitext(filename)[0].replace('-', ' ').replace('_', ' ').title()
                    themes[filename] = display_name
    except Exception as e:
        current_app.logger.error(f"Error scanning CodeMirror themes: {e}")
    return dict(sorted(themes.items())) # Sort for consistent display

@bp.route('/change-codemirror-theme', methods=['POST'])
@login_required
def change_codemirror_theme():
    new_cm_theme_file = request.form.get('codemirror_theme')
    available_cm_themes = get_available_codemirror_themes()

    if not new_cm_theme_file or new_cm_theme_file not in available_cm_themes:
        flash("Invalid CodeMirror theme selected.", "error")
        return redirect(url_for('main_routes.user_settings_page'))

    try:
        current_user.preferred_codemirror_theme = new_cm_theme_file
        db.session.commit()
        flash(f"Code Editor theme changed to {available_cm_themes.get(new_cm_theme_file, new_cm_theme_file)}.", "success")
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Database error saving CodeMirror theme for user {current_user.id}: {e}")
        flash("Database error saving CodeMirror theme preference.", "error")
    return redirect(url_for('main_routes.user_settings_page'))

@bp.route('/profile/edit', methods=['GET', 'POST'])
@login_required
def edit_profile():
    form = EditProfileForm(original_username=current_user.username, original_email=current_user.email)
    if form.validate_on_submit():
        current_user.email = form.email.data
        current_user.bio = form.bio.data
        current_user.github_url = form.github_url.data
        current_user.spotify_url = form.spotify_url.data
        current_user.youtube_url = form.youtube_url.data
        current_user.twitter_url = form.twitter_url.data
        current_user.steam_url = form.steam_url.data
        current_user.twitch_url = form.twitch_url.data
        current_user.discord_server_url = form.discord_server_url.data
        current_user.reddit_url = form.reddit_url.data

        picture_filename_to_save = current_user.profile_picture_filename # Keep old if new fails
        picture_path_on_disk = None

        if form.profile_picture.data:
            picture_file = form.profile_picture.data
            try:
                img = Image.open(picture_file)
                is_animated = getattr(img, 'is_animated', False)
                file_format = img.format

                filename_base = secure_filename(str(current_user.id))
                # STATIC_PROFILE_PICS_FOLDER is from config.py, imported via app.config
                static_pics_path = current_app.config.get('STATIC_PROFILE_PICS_FOLDER', os.path.join(current_app.root_path, 'app', 'static', 'uploads', 'profile_pics'))
                os.makedirs(static_pics_path, exist_ok=True)

                max_size = (256, 256)

                if is_animated and file_format == 'GIF':
                    new_pfp_filename = f"{filename_base}.gif"
                    picture_path_on_disk = os.path.join(static_pics_path, new_pfp_filename)
                    frames = []
                    duration = img.info.get('duration', 100)
                    loop = img.info.get('loop', 0)
                    for frame in ImageSequence.Iterator(img):
                        frame_copy = frame.copy()
                        if frame_copy.mode == 'P': frame_copy = frame_copy.convert('RGBA')
                        if frame_copy.mode == 'RGBA': frame_copy = frame_copy.convert('RGB') # Or handle transparency
                        frame_copy.thumbnail(max_size, Image.Resampling.LANCZOS)
                        frames.append(frame_copy)
                    if frames:
                        frames[0].save(picture_path_on_disk, format='GIF', save_all=True, append_images=frames[1:], duration=duration, loop=loop, optimize=False)
                        picture_filename_to_save = new_pfp_filename
                    else: raise ValueError("Could not process GIF frames.")
                else:
                    new_pfp_filename = f"{filename_base}.jpg"
                    picture_path_on_disk = os.path.join(static_pics_path, new_pfp_filename)
                    img.thumbnail(max_size, Image.Resampling.LANCZOS)
                    if img.mode in ("RGBA", "P"): img = img.convert("RGB")
                    img.save(picture_path_on_disk, format='JPEG', quality=85, optimize=True)
                    picture_filename_to_save = new_pfp_filename

                current_user.profile_picture_filename = picture_filename_to_save
                current_app.logger.info(f"Profile picture updated for {current_user.username} to {picture_filename_to_save}")

            except Exception as e:
                current_app.logger.error(f"Error processing profile picture for {current_user.id}: {e}", exc_info=True)
                flash(f'Could not process profile picture: {e}. Please try a different image.', 'danger')
                if picture_path_on_disk and os.path.exists(picture_path_on_disk): # Cleanup partially saved file
                    try: os.remove(picture_path_on_disk)
                    except OSError: pass
        try:
            db.session.commit()
            flash('Your profile has been updated!', 'success')
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error committing profile update for {current_user.id}: {e}", exc_info=True)
            flash('An error occurred saving your profile.', 'danger')
        return redirect(url_for('main_routes.user_profile', username=current_user.username))

    elif request.method == 'GET':
        form.username.data = current_user.username # Username is readonly
        form.email.data = current_user.email
        form.bio.data = current_user.bio
        form.github_url.data = current_user.github_url
        form.spotify_url.data = current_user.spotify_url
        form.youtube_url.data = current_user.youtube_url
        form.twitter_url.data = current_user.twitter_url
        form.steam_url.data = current_user.steam_url
        form.twitch_url.data = current_user.twitch_url
        form.discord_server_url.data = current_user.discord_server_url
        form.reddit_url.data = current_user.reddit_url

    profile_picture_url = None
    if current_user.profile_picture_filename:
        profile_picture_url = url_for('static', filename=f'uploads/profile_pics/{current_user.profile_picture_filename}')
    return render_template('edit_profile.html', title='Edit Profile', form=form, profile_picture_url=profile_picture_url)


@bp.route('/user/<username>')
@login_required
def user_profile(username):
    user = User.query.filter_by(username=username).first_or_404()
    profile_picture_url = None
    if user.profile_picture_filename:
        profile_picture_url = url_for('static', filename=f'uploads/profile_pics/{user.profile_picture_filename}')

    member_since_date = user.created_at.strftime("%B %d, %Y")

    # Ensure user.created_at is timezone-aware before subtraction
    user_created_at_aware = user.created_at
    if user_created_at_aware.tzinfo is None:
        # If naive, assume it's UTC (consistent with model default) and make it aware
        user_created_at_aware = user_created_at_aware.replace(tzinfo=timezone.utc)

    # Now both datetime objects are offset-aware (UTC)
    time_difference = datetime.now(timezone.utc) - user_created_at_aware

    days = time_difference.days
    if days < 30: member_for = f"{days} day{'s' if days != 1 else ''}"
    elif days < 365: months = days // 30; member_for = f"{months} month{'s' if months != 1 else ''}"
    else: years = days // 365; member_for = f"{years} year{'s' if years != 1 else ''}"

    # ... rest of your function ...
    page = request.args.get('page', 1, type=int)
    sort_by = request.args.get('sort', 'recent_desc')
    comment_form = CommentForm() # Assuming CommentForm is defined/imported
    query = Post.query.filter(Post.user_id == user.id)

    # Simplified sorting for brevity, ensure you have all fields/joins needed for complex sorts
    if sort_by == 'recent_asc': query = query.order_by(Post.timestamp.asc())
    else: query = query.order_by(Post.timestamp.desc()) # Default to recent_desc

    # Eager loading options (ensure these match your Post model and macro needs)
    query = query.options(
        db.joinedload(Post.author).load_only(User.username, User.profile_picture_filename, User.id),
        db.joinedload(Post.shared_comment).options(
            db.joinedload(Comment.author).load_only(User.username, User.profile_picture_filename, User.id),
            db.selectinload(Comment.likers).load_only(User.id),
            db.selectinload(Comment.dislikers).load_only(User.id)
        ),
        db.selectinload(Post.comments).options(
            db.joinedload(Comment.author).load_only(User.username, User.profile_picture_filename, User.id),
            db.selectinload(Comment.likers).load_only(User.id),
            db.selectinload(Comment.dislikers).load_only(User.id),
            db.selectinload(Comment.replies).options( # For nested replies
                db.joinedload(Comment.author).load_only(User.username, User.profile_picture_filename, User.id),
                db.selectinload(Comment.likers).load_only(User.id),
                db.selectinload(Comment.dislikers).load_only(User.id)
            )
        ),
        db.selectinload(Post.likers).load_only(User.id),
        db.selectinload(Post.dislikers).load_only(User.id)
    )
    posts_pagination = query.paginate(page=page, per_page=10, error_out=False)


    return render_template('user_profile.html', title=f"{user.username}'s Profile",
                           user=user, profile_picture_url=profile_picture_url,
                           member_since_date=member_since_date, member_for=member_for,
                           posts=posts_pagination, current_sort=sort_by,
                           comment_form=comment_form, csrf_token=generate_csrf) # Assuming generate_csrf is imported



@bp.route('/follow/<username>', methods=['POST'])
@login_required
def follow_user(username):
    user_to_follow = User.query.filter_by(username=username).first_or_404()
    if user_to_follow == current_user:
        flash('You cannot follow yourself!', 'warning')
    elif not current_user.is_following(user_to_follow):
        current_user.follow(user_to_follow)
        try:
            db.session.commit()
            flash(f'You are now following {username}.', 'success')
            create_notification(recipient_user=user_to_follow, sender_user=current_user, type='new_follower')
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error following user or creating notification: {e}")
            flash('Could not follow user due to an error.', 'danger')
    else:
        flash(f'You are already following {username}.', 'info')
    return redirect(request.referrer or url_for('main_routes.user_profile', username=username))


@bp.route('/unfollow/<username>', methods=['POST'])
@login_required
def unfollow_user(username):
    user_to_unfollow = User.query.filter_by(username=username).first_or_404()
    if current_user.is_following(user_to_unfollow):
        current_user.unfollow(user_to_unfollow)
        try:
            db.session.commit()
            flash(f'You have unfollowed {username}.', 'info')
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error unfollowing user: {e}")
            flash('Could not unfollow user due to an error.', 'danger')
    else:
        flash(f'You are not following {username}.', 'warning')
    return redirect(request.referrer or url_for('main_routes.user_profile', username=username))


@bp.route('/find_people', methods=['GET'])
@login_required
def find_people():
    search_query = request.args.get('search_query', '').strip()
    query_builder = User.query.filter(User.id != current_user.id)
    if search_query:
        search_term = f"%{search_query}%"
        # Add other searchable fields if User model has them (e.g., first_name, last_name)
        query_builder = query_builder.filter(User.username.ilike(search_term))

    all_users_profiles = query_builder.order_by(User.username).all()
    users_with_follow_status = [{
        'profile': user_prof,
        'is_following': current_user.is_following(user_prof) if hasattr(current_user, 'is_following') else False
    } for user_prof in all_users_profiles]

    return render_template('find_people.html', title="Find People",
                           users_data=users_with_follow_status, search_query=search_query)


@bp.route('/notifications')
@login_required
def notifications_page():
    page = request.args.get('page', 1, type=int)
    unread_notifications = current_user.notifications_received.filter_by(is_read=False).all()
    if unread_notifications:
        for notification_instance in unread_notifications: # Use a different variable name
            notification_instance.is_read = True
        try:
            db.session.commit()
        except Exception as e:
            db.session.rollback() # Rollback on error
            current_app.logger.error(f"Error marking notifications as read for {current_user.id}: {e}")

    notifications_pagination = current_user.notifications_received.order_by(
        Notification.timestamp.desc()
    ).paginate(page=page, per_page=15, error_out=False)

    processed_notifications = [n.to_dict() for n in notifications_pagination.items]

    return render_template('notifications.html', title='My Notifications',
                           processed_notifications=processed_notifications,
                           notifications_pagination_obj=notifications_pagination) # Pass pagination object for pagination controls


@bp.route('/api/notifications/unread_count')
@login_required
def api_unread_notification_count():
    try:
        count = current_user.notifications_received.filter_by(is_read=False).count()
        return jsonify({'status': 'success', 'unread_count': count})
    except Exception as e:
        current_app.logger.error(f"Error fetching unread notification count for {current_user.id}: {e}")
        return jsonify({'status': 'error', 'message': 'Could not fetch unread count.'}), 500


@bp.route('/api/notifications/dismiss/<int:notification_id>', methods=['POST'])
@login_required
def api_dismiss_notification(notification_id):
    notification_to_dismiss = Notification.query.filter_by(id=notification_id, user_id=current_user.id).first_or_404() # Renamed variable
    try:
        db.session.delete(notification_to_dismiss)
        db.session.commit()
        unread_count = current_user.notifications_received.filter_by(is_read=False).count()
        return jsonify({'status': 'success', 'message': 'Notification deleted.', 'unread_count': unread_count})
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error deleting notification {notification_id} for {current_user.id}: {e}")
        return jsonify({'status': 'error', 'message': 'Could not delete notification.'}), 500


@bp.route('/api/notifications/mark_all_read', methods=['POST'])
@login_required
def api_mark_all_notifications_read():
    try:
        unread_notifications_list = current_user.notifications_received.filter_by(is_read=False).all() # Renamed variable
        for notification_item in unread_notifications_list: # Renamed loop variable
            notification_item.is_read = True
        db.session.commit()
        return jsonify({'status': 'success', 'message': 'All notifications marked as read.', 'unread_count': 0})
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error marking all notifications as read for {current_user.id}: {e}")
        return jsonify({'status': 'error', 'message': 'Could not mark all as read.'}), 500


@bp.route('/photos')
@login_required
def photos():
    image_files_query = File.query.filter(
        File.user_id == current_user.id,
        File.mime_type.in_(current_app.config.get('VIEWABLE_IMAGE_MIMES', VIEWABLE_IMAGE_MIMES))
    ).order_by(File.upload_date.desc()).all() # Renamed variable

    for img_file in image_files_query: # Make sure to use the new variable name here
        img_file.view_url = url_for('file_routes.view_file', file_id=img_file.id) # Assuming 'file_routes' blueprint

    return render_template('photos.html', title='My Photos', image_files=image_files_query)


@bp.route('/videos')
@login_required
def videos():
    video_files_query = File.query.filter(
        File.user_id == current_user.id,
        File.mime_type.in_(current_app.config.get('VIEWABLE_VIDEO_MIMES', VIEWABLE_VIDEO_MIMES))
    ).order_by(File.upload_date.desc()).all() # Renamed variable

    # VIDEO_THUMBNAIL_FOLDER from config, ensure it's in app.config
    thumbnail_folder_config = current_app.config.get('VIDEO_THUMBNAIL_FOLDER', VIDEO_THUMBNAIL_FOLDER)

    for vid_file in video_files_query: # Use new variable name
        vid_file.view_url = url_for('file_routes.view_file', file_id=vid_file.id) # Assuming 'file_routes'
        thumbnail_filename = f"{vid_file.id}.jpg"
        # Construct path relative to the static folder for url_for
        relative_thumbnail_path = os.path.join('uploads', 'video_thumbnails', thumbnail_filename)
        # Check existence using absolute path
        if os.path.exists(os.path.join(thumbnail_folder_config, thumbnail_filename)):
            vid_file.poster_url = url_for('static', filename=relative_thumbnail_path)
        else:
            vid_file.poster_url = None

    return render_template('videos.html', title='My Videos', video_files=video_files_query)

@bp.route('/api/users/activity_status', methods=['POST']) # Or the correct URL path
@login_required
def api_users_activity_status(): # The function name becomes the endpoint suffix
    # Your logic for this route, which was originally in main.py:
    data = request.get_json()
    if not data or 'user_ids' not in data or not isinstance(data['user_ids'], list):
        return jsonify({"status": "error", "message": "Invalid request. 'user_ids' list is required."}), 400

    user_ids_to_check = data['user_ids']
    statuses = {}

    # Make sure User model and timedelta are imported if used here
    from app.models import User
    from datetime import timedelta, datetime, timezone

    afk_threshold = timedelta(minutes=30)
    now = datetime.now(timezone.utc)

    users_found = User.query.filter(User.id.in_(user_ids_to_check)).all()

    for user_obj in users_found:
        status_string = "offline"
        if user_obj.is_online:
            user_last_seen = user_obj.last_seen
            if user_last_seen and user_last_seen.tzinfo is None:
                user_last_seen = user_last_seen.replace(tzinfo=timezone.utc)
            if user_last_seen and (now - user_last_seen) < afk_threshold:
                status_string = "online"
            else:
                status_string = "afk"
        statuses[user_obj.id] = status_string
    return jsonify({"status": "success", "user_statuses": statuses})
