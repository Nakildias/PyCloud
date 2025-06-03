# app/routes/social_routes.py
import os
import uuid
from datetime import datetime, timezone
from werkzeug.utils import secure_filename

from flask import (
    Blueprint, render_template, redirect, url_for, flash, request,
    jsonify, current_app, g # g might not be needed here directly unless for specific hooks
)
from flask_login import login_required, current_user
from sqlalchemy.orm import aliased, joinedload, selectinload # For eager loading and aliases
from flask_wtf.csrf import generate_csrf # For passing CSRF token to macros

# Import from app package
from app import db
from app.models import User, Post, Comment, Setting # Models
from app.models import post_likes, post_dislikes # Association tables for counts
from app.forms import CreatePostForm, CommentForm # Forms
from app.utils import get_post_media_path, create_notification # Utilities
from app.config import (
    DEFAULT_MAX_PHOTO_MB, DEFAULT_MAX_VIDEO_MB,
)


# Define the blueprint
bp = Blueprint('social_routes', __name__, url_prefix='/social') # Using '/social' prefix


@bp.route('/feed')
@login_required
def post_feed():
    page = request.args.get('page', 1, type=int)
    sort_by = request.args.get('sort', 'recent_desc')
    comment_form = CommentForm()

    followed_users_ids = [user.id for user in current_user.followed]
    followed_users_ids.append(current_user.id) # Include current user's posts
    followed_users_ids = list(set(followed_users_ids))

    query = Post.query.filter(Post.user_id.in_(followed_users_ids))

    if sort_by == 'recent_asc': query = query.order_by(Post.timestamp.asc())
    elif sort_by == 'likes_desc': query = query.outerjoin(post_likes).group_by(Post.id).order_by(db.func.count(post_likes.c.user_id).desc(), Post.timestamp.desc())
    elif sort_by == 'likes_asc': query = query.outerjoin(post_likes).group_by(Post.id).order_by(db.func.count(post_likes.c.user_id).asc(), Post.timestamp.desc())
    elif sort_by == 'comments_desc': query = query.outerjoin(Comment, Post.id == Comment.post_id).group_by(Post.id).order_by(db.func.count(Comment.id).desc(), Post.timestamp.desc())
    elif sort_by == 'comments_asc': query = query.outerjoin(Comment, Post.id == Comment.post_id).group_by(Post.id).order_by(db.func.count(Comment.id).asc(), Post.timestamp.desc())
    elif sort_by == 'shares_desc':
        SharedPostAlias = aliased(Post, name='shares_alias')
        query = query.outerjoin(SharedPostAlias, Post.shares).group_by(Post.id).order_by(db.func.count(SharedPostAlias.id).desc(), Post.timestamp.desc())
    else: query = query.order_by(Post.timestamp.desc()) # Default: recent_desc

    query = query.options(
        joinedload(Post.author).load_only(User.username, User.profile_picture_filename, User.id),
        joinedload(Post.shared_comment).options(
            joinedload(Comment.author).load_only(User.username, User.profile_picture_filename, User.id),
            selectinload(Comment.likers).load_only(User.id),
            selectinload(Comment.dislikers).load_only(User.id)
        ),
        selectinload(Post.comments).options(
            joinedload(Comment.author).load_only(User.username, User.profile_picture_filename, User.id),
            selectinload(Comment.likers).load_only(User.id),
            selectinload(Comment.dislikers).load_only(User.id),
            selectinload(Comment.replies).options(
                joinedload(Comment.author).load_only(User.username, User.profile_picture_filename, User.id),
                selectinload(Comment.likers).load_only(User.id),
                selectinload(Comment.dislikers).load_only(User.id)
            )
        ),
        selectinload(Post.likers).load_only(User.id),
        selectinload(Post.dislikers).load_only(User.id)
    )
    posts_pagination = query.paginate(page=page, per_page=10, error_out=False)

    return render_template('social/post_feed.html', # Assuming templates in social/
                           title='My Feed', posts=posts_pagination,
                           current_sort=sort_by, comment_form=comment_form,
                           csrf_token=generate_csrf)


@bp.route('/post/new', methods=['GET', 'POST'])
@login_required
def create_post():
    form = CreatePostForm()
    try: max_photo_mb = int(Setting.get('max_photo_upload_mb', str(DEFAULT_MAX_PHOTO_MB)))
    except: max_photo_mb = DEFAULT_MAX_PHOTO_MB
    try: max_video_mb = int(Setting.get('max_video_upload_mb', str(DEFAULT_MAX_VIDEO_MB)))
    except: max_video_mb = DEFAULT_MAX_VIDEO_MB

    if form.validate_on_submit():
        photo_fn, video_fn = None, None
        upload_path = get_post_media_path() # Util function
        picture_path_on_disk, video_path_on_disk = None, None # For potential cleanup

        if form.photo.data:
            try:
                picture_file = form.photo.data
                picture_file.seek(0, os.SEEK_END); file_size = picture_file.tell(); picture_file.seek(0)
                if file_size > max_photo_mb * 1024 * 1024:
                    flash(f'Photo exceeds {max_photo_mb} MB limit.', 'danger')
                    return render_template('social/create_post.html', title='New Post', form=form, max_photo_upload_mb=max_photo_mb, max_video_upload_mb=max_video_mb)
                ext = os.path.splitext(secure_filename(picture_file.filename))[1].lower()
                photo_fn = str(uuid.uuid4()) + ext
                picture_path_on_disk = os.path.join(upload_path, photo_fn)
                picture_file.save(picture_path_on_disk)
            except Exception as e: current_app.logger.error(f"Photo upload error: {e}"); flash("Error uploading photo.", "danger"); photo_fn = None

        if form.video.data and not photo_fn: # Only allow video if no photo
            try:
                video_file = form.video.data
                video_file.seek(0, os.SEEK_END); file_size = video_file.tell(); video_file.seek(0)
                if file_size > max_video_mb * 1024 * 1024:
                    flash(f'Video exceeds {max_video_mb} MB limit.', 'danger')
                    return render_template('social/create_post.html', title='New Post', form=form, max_photo_upload_mb=max_photo_mb, max_video_upload_mb=max_video_mb)
                ext = os.path.splitext(secure_filename(video_file.filename))[1].lower()
                video_fn = str(uuid.uuid4()) + ext
                video_path_on_disk = os.path.join(upload_path, video_fn)
                video_file.save(video_path_on_disk)
            except Exception as e: current_app.logger.error(f"Video upload error: {e}"); flash("Error uploading video.", "danger"); video_fn = None
        elif form.video.data and photo_fn:
            flash("Upload a photo OR a video, not both.", "warning")
            # Do not proceed if both are attempted
            return render_template('social/create_post.html', title='New Post', form=form, max_photo_upload_mb=max_photo_mb, max_video_upload_mb=max_video_mb)


        if not form.text_content.data and not photo_fn and not video_fn:
            flash('A post must have text, a photo, or a video.', 'warning')
        else:
            try:
                new_post = Post(user_id=current_user.id,
                                text_content=form.text_content.data if form.text_content.data else None,
                                photo_filename=photo_fn, video_filename=video_fn)
                db.session.add(new_post); db.session.commit()
                flash('Post created!', 'success')
                # Notify followers
                if current_user.followers:
                    for follower in current_user.followers:
                        if follower.id != current_user.id:
                            create_notification(recipient_user=follower, sender_user=current_user, type='new_post_from_followed_user', post=new_post)
                return redirect(url_for('main_routes.user_profile', username=current_user.username)) # Redirect to user's profile
            except Exception as e:
                db.session.rollback(); current_app.logger.error(f"Error saving post: {e}", exc_info=True)
                flash("Error saving post.", "danger")
                if picture_path_on_disk and os.path.exists(picture_path_on_disk): os.remove(picture_path_on_disk)
                if video_path_on_disk and os.path.exists(video_path_on_disk): os.remove(video_path_on_disk)

    return render_template('social/create_post.html', title='New Post', form=form, max_photo_upload_mb=max_photo_mb, max_video_upload_mb=max_video_mb)


@bp.route('/post/<int:post_id>')
@login_required
def view_single_post(post_id):
    post = Post.query.options( # Eager loading options from feed
        joinedload(Post.author).load_only(User.username, User.profile_picture_filename, User.id),
        joinedload(Post.shared_comment).options(
            joinedload(Comment.author).load_only(User.username, User.profile_picture_filename, User.id),
            selectinload(Comment.likers).load_only(User.id), selectinload(Comment.dislikers).load_only(User.id)
        ),
        selectinload(Post.comments).options(
            joinedload(Comment.author).load_only(User.username, User.profile_picture_filename, User.id),
            selectinload(Comment.likers).load_only(User.id), selectinload(Comment.dislikers).load_only(User.id),
            selectinload(Comment.replies).options(
                joinedload(Comment.author).load_only(User.username, User.profile_picture_filename, User.id),
                selectinload(Comment.likers).load_only(User.id), selectinload(Comment.dislikers).load_only(User.id)
            )
        ),
        selectinload(Post.likers).load_only(User.id), selectinload(Post.dislikers).load_only(User.id)
    ).get_or_404(post_id)
    comment_form = CommentForm()
    return render_template('view_single_post.html', title=f"Post by {post.author.username}",
                           post=post, comment_form=comment_form, csrf_token=generate_csrf)


@bp.route('/post/<int:post_id>/delete', methods=['POST'])
@login_required
def delete_post(post_id):
    post_to_delete = Post.query.get_or_404(post_id)
    if not (post_to_delete.author == current_user or current_user.is_admin):
        flash('Permission denied.', 'danger'); return redirect(request.referrer or url_for('.post_feed'))
    try:
        upload_path = get_post_media_path()
        if post_to_delete.photo_filename:
            photo_path = os.path.join(upload_path, post_to_delete.photo_filename)
            if os.path.exists(photo_path): os.remove(photo_path)
        if post_to_delete.video_filename:
            video_path = os.path.join(upload_path, post_to_delete.video_filename)
            if os.path.exists(video_path): os.remove(video_path)
        db.session.delete(post_to_delete); db.session.commit()
        flash('Post deleted.', 'success')
    except Exception as e:
        db.session.rollback(); current_app.logger.error(f"Error deleting post {post_id}: {e}")
        flash('Error deleting post.', 'danger')
    return redirect(url_for('.post_feed'))


@bp.route('/post/<int:post_id>/like', methods=['POST'])
@login_required
def like_post(post_id):
    post = Post.query.get_or_404(post_id)
    action = 'liked'
    if current_user in post.dislikers: post.dislikers.remove(current_user)
    if current_user in post.likers: post.likers.remove(current_user); action = 'unliked'
    else:
        post.likers.append(current_user)
        if post.author != current_user:
            create_notification(recipient_user=post.author, sender_user=current_user, type='like_post', post=post)
    try:
        db.session.commit()
        like_count = db.session.query(post_likes.c.user_id).filter(post_likes.c.post_id == post.id).count()
        dislike_count = db.session.query(post_dislikes.c.user_id).filter(post_dislikes.c.post_id == post.id).count()
        return jsonify({'status': 'success', 'action': action, 'likes': like_count, 'dislikes': dislike_count})
    except Exception as e:
        db.session.rollback(); current_app.logger.error(f"Error liking post {post_id}: {e}")
        return jsonify({'status': 'error', 'message': 'DB error during like.'}), 500


@bp.route('/post/<int:post_id>/dislike', methods=['POST'])
@login_required
def dislike_post(post_id):
    post = Post.query.get_or_404(post_id)
    action = 'disliked'
    if current_user in post.likers: post.likers.remove(current_user)
    if current_user in post.dislikers: post.dislikers.remove(current_user); action = 'undisliked'
    else:
        post.dislikers.append(current_user)
        if post.author != current_user: # Notify only if someone else disliked the post
             create_notification(recipient_user=post.author, sender_user=current_user, type='dislike_post', post=post)
    try:
        db.session.commit()
        like_count = db.session.query(post_likes.c.user_id).filter(post_likes.c.post_id == post.id).count()
        dislike_count = db.session.query(post_dislikes.c.user_id).filter(post_dislikes.c.post_id == post.id).count()
        return jsonify({'status': 'success', 'action': action, 'likes': like_count, 'dislikes': dislike_count})
    except Exception as e:
        db.session.rollback(); current_app.logger.error(f"Error disliking post {post_id}: {e}")
        return jsonify({'status': 'error', 'message': 'DB error during dislike.'}), 500

@bp.route('/post/<int:post_id>/share', methods=['POST'])
@login_required
def share_post(post_id):
    original_post = Post.query.get_or_404(post_id)
    if original_post.author == current_user:
        return jsonify({'status': 'error', 'message': 'Cannot share your own post this way.'}), 400
    existing_share = Post.query.filter_by(user_id=current_user.id, original_post_id=original_post.id).first()
    if existing_share:
        return jsonify({'status': 'info', 'message': 'Already shared this post.'}), 200
    shared_post = Post(user_id=current_user.id, original_post_id=original_post.id)
    db.session.add(shared_post)
    if original_post.author != current_user:
        create_notification(recipient_user=original_post.author, sender_user=current_user, type='share_post', post=original_post)
    db.session.commit()
    # original_post.shares is a relationship, .count() should work if it's dynamic or after commit
    return jsonify({'status': 'success', 'message': 'Post shared!', 'share_count': original_post.shares.count()}), 201

@bp.route('/post/<int:post_id>/comment/add', methods=['POST'])
@login_required
def add_comment_to_post(post_id):
    post = Post.query.get_or_404(post_id)
    is_ajax = request.accept_mimetypes.accept_json and not request.accept_mimetypes.accept_html
    text_content, parent_comment_id_val = None, None # Renamed from parent_comment_id

    if is_ajax:
        data = request.get_json();
        if not data: return jsonify({'status': 'error', 'message': 'Invalid JSON.'}), 400
        text_content = data.get('text_content', '').strip()
        parent_comment_id_val = data.get('parent_comment_id')
        if parent_comment_id_val:
            try: parent_comment_id_val = int(parent_comment_id_val)
            except: return jsonify({'status': 'error', 'message': 'Invalid parent_comment_id.'}), 400
    else: # Form submission
        form = CommentForm()
        if form.validate_on_submit():
            text_content = form.text_content.data.strip()
            parent_comment_id_str = request.form.get('parent_comment_id')
            if parent_comment_id_str:
                try: parent_comment_id_val = int(parent_comment_id_str)
                except: flash('Invalid parent comment reference.', 'danger'); return redirect(request.referrer or url_for('.view_single_post', post_id=post_id))
        else:
            for error_list in form.errors.values(): flash(error_list[0], 'danger') # Flash first error
            return redirect(request.referrer or url_for('.view_single_post', post_id=post_id))

    if not text_content or len(text_content) > 1000:
        msg = 'Comment text empty or too long.'
        if is_ajax: return jsonify({'status': 'error', 'message': msg}), 400
        flash(msg, 'warning'); return redirect(request.referrer or url_for('.view_single_post', post_id=post_id))

    parent_comment_obj = None # Renamed
    if parent_comment_id_val:
        parent_comment_obj = Comment.query.filter_by(id=parent_comment_id_val, post_id=post.id).first()
        if not parent_comment_obj:
            msg = 'Parent comment not found or invalid.'
            if is_ajax: return jsonify({'status': 'error', 'message': msg}), 404
            flash(msg, 'danger'); return redirect(url_for('.view_single_post', post_id=post_id))
    try:
        new_comment = Comment(user_id=current_user.id, post_id=post.id, text_content=text_content, parent_id=parent_comment_obj.id if parent_comment_obj else None)
        db.session.add(new_comment)
        if post.author != current_user:
            create_notification(recipient_user=post.author, sender_user=current_user, type='comment_on_post', post=post, comment=new_comment)
        if parent_comment_obj and parent_comment_obj.author != current_user:
            create_notification(recipient_user=parent_comment_obj.author, sender_user=current_user, type='reply_to_comment', post=post, comment=new_comment)
        db.session.commit()
        db.session.refresh(new_comment) # To get author details loaded for to_dict
        _ = new_comment.author # Access to ensure it's loaded if not already by relationship config

        if is_ajax:
            return jsonify({'status': 'success', 'comment': new_comment.to_dict(include_author_details=True),
                            'post_comment_count': len(post.comments),
                            'current_user_id': current_user.id, 'current_user_is_admin': current_user.is_admin}), 201
        flash("Comment posted.", "success")
        return redirect(request.referrer or url_for('.view_single_post', post_id=post_id, _anchor=f"comment-{new_comment.id}"))
    except Exception as e:
        db.session.rollback(); current_app.logger.error(f"Error saving comment for post {post_id}: {e}", exc_info=True)
        msg = 'Could not save comment.'
        if is_ajax: return jsonify({'status': 'error', 'message': msg}), 500
        flash(msg, 'danger'); return redirect(request.referrer or url_for('.view_single_post', post_id=post_id))

@bp.route('/api/comment/<int:comment_id>/delete', methods=['POST'])
@login_required
def api_delete_comment(comment_id):
    comment_to_delete = Comment.query.get_or_404(comment_id) # Renamed
    if not (comment_to_delete.user_id == current_user.id or current_user.is_admin):
        return jsonify({"status": "error", "message": "Permission denied."}), 403
    try:
        post_id_of_comment = comment_to_delete.post_id # Renamed
        db.session.delete(comment_to_delete)
        db.session.commit()
        # Recalculate post comment count
        post_after_delete = Post.query.get(post_id_of_comment)
        post_comment_count = post_after_delete.comments.count() if post_after_delete else 0
        return jsonify({"status": "success", "message": "Comment deleted.", "deleted_comment_id": comment_id, "post_comment_count": post_comment_count})
    except Exception as e:
        db.session.rollback(); current_app.logger.error(f"Error deleting comment {comment_id}: {e}")
        return jsonify({"status": "error", "message": "Could not delete comment."}), 500


@bp.route('/api/comment/<int:comment_id>/like', methods=['POST'])
@login_required
def like_comment(comment_id):
    comment_obj = Comment.query.get_or_404(comment_id) # Renamed
    action = "liked"
    if current_user in comment_obj.dislikers: comment_obj.dislikers.remove(current_user)
    if current_user in comment_obj.likers: comment_obj.likers.remove(current_user); action = "unliked"
    else: comment_obj.likers.append(current_user) # Notify for like will be handled by client or specific notification logic
    try:
        db.session.commit()
        return jsonify({"status": "success", "action": action, "comment_id": comment_obj.id,
                        "likes": len(comment_obj.likers), "dislikes": len(comment_obj.dislikers),
                        "is_liked_by_user": current_user in comment_obj.likers,
                        "is_disliked_by_user": current_user in comment_obj.dislikers})
    except Exception as e:
        db.session.rollback(); current_app.logger.error(f"Error liking comment {comment_id}: {e}")
        return jsonify({"status": "error", "message": "Could not process like."}), 500


@bp.route('/api/comment/<int:comment_id>/dislike', methods=['POST'])
@login_required
def dislike_comment(comment_id):
    comment_obj = Comment.query.get_or_404(comment_id) # Renamed
    action = "disliked"
    if current_user in comment_obj.likers: comment_obj.likers.remove(current_user)
    if current_user in comment_obj.dislikers: comment_obj.dislikers.remove(current_user); action = "undisliked"
    else: comment_obj.dislikers.append(current_user) # Notify for dislike?
    try:
        db.session.commit()
        return jsonify({"status": "success", "action": action, "comment_id": comment_obj.id,
                        "likes": len(comment_obj.likers), "dislikes": len(comment_obj.dislikers),
                        "is_liked_by_user": current_user in comment_obj.likers,
                        "is_disliked_by_user": current_user in comment_obj.dislikers})
    except Exception as e:
        db.session.rollback(); current_app.logger.error(f"Error disliking comment {comment_id}: {e}")
        return jsonify({"status": "error", "message": "Could not process dislike."}), 500


@bp.route('/api/comment/<int:comment_id>/share', methods=['POST'])
@login_required
def share_comment_as_post(comment_id):
    comment_to_share = Comment.query.get_or_404(comment_id)
    data = request.get_json()
    if not data: return jsonify({"status": "error", "message": "Missing data."}), 400
    sharer_text = data.get('text_content', '').strip() # Renamed
    try:
        new_post = Post(user_id=current_user.id, text_content=sharer_text if sharer_text else None, shared_comment_id=comment_to_share.id)
        db.session.add(new_post)
        if comment_to_share.author != current_user:
            create_notification(recipient_user=comment_to_share.author, sender_user=current_user, type='share_comment', post=comment_to_share.post, comment=comment_to_share)
        db.session.commit()
        return jsonify({"status": "success", "message": "Comment shared as post.", "new_post_id": new_post.id}), 201
    except Exception as e:
        db.session.rollback(); current_app.logger.error(f"Error sharing comment {comment_id}: {e}", exc_info=True)
        return jsonify({"status": "error", "message": "Could not share comment."}), 500
