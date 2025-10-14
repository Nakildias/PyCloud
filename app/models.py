# app/models.py
import uuid
from datetime import datetime, timezone, timedelta
from werkzeug.security import generate_password_hash, check_password_hash
from itsdangerous import URLSafeTimedSerializer
from flask import current_app, url_for
from sqlalchemy.orm import relationship
from sqlalchemy import Table, Column, Integer, ForeignKey, String, Text, DateTime, Boolean, inspect, UniqueConstraint, BigInteger
from flask_login import UserMixin

from . import db

# --- Association Tables (Many-to-Many) ---
followers = db.Table('followers', db.metadata,
    db.Column('follower_id', db.Integer, db.ForeignKey('user.id', name='fk_followers_follower_id', ondelete='CASCADE'), primary_key=True),
    db.Column('followed_id', db.Integer, db.ForeignKey('user.id', name='fk_followers_followed_id', ondelete='CASCADE'), primary_key=True)
)

post_likes = db.Table('post_likes', db.metadata,
    db.Column('user_id', db.Integer, db.ForeignKey('user.id', name='fk_post_likes_user_id', ondelete='CASCADE'), primary_key=True),
    db.Column('post_id', db.Integer, db.ForeignKey('post.id', name='fk_post_likes_post_id', ondelete='CASCADE'), primary_key=True)
)

post_dislikes = db.Table('post_dislikes', db.metadata,
    db.Column('user_id', db.Integer, db.ForeignKey('user.id', name='fk_post_dislikes_user_id', ondelete='CASCADE'), primary_key=True),
    db.Column('post_id', db.Integer, db.ForeignKey('post.id', name='fk_post_dislikes_post_id', ondelete='CASCADE'), primary_key=True)
)

comment_likers = db.Table('comment_likers', db.metadata,
    db.Column('user_id', db.Integer, db.ForeignKey('user.id', name='fk_comment_likers_user_id', ondelete='CASCADE'), primary_key=True),
    db.Column('comment_id', db.Integer, db.ForeignKey('comment.id', name='fk_comment_likers_comment_id', ondelete='CASCADE'), primary_key=True)
)

comment_dislikers = db.Table('comment_dislikers', db.metadata,
    db.Column('user_id', db.Integer, db.ForeignKey('user.id', name='fk_comment_dislikers_user_id', ondelete='CASCADE'), primary_key=True),
    db.Column('comment_id', db.Integer, db.ForeignKey('comment.id', name='fk_comment_dislikers_comment_id', ondelete='CASCADE'), primary_key=True)
)

repo_stars = db.Table('repo_stars', db.metadata,
    db.Column('user_id', db.Integer, db.ForeignKey('user.id', name='fk_repo_stars_user_id', ondelete='CASCADE'), primary_key=True),
    db.Column('git_repository_id', db.Integer, db.ForeignKey('git_repository.id', name='fk_repo_stars_git_repo_id', ondelete='CASCADE'), primary_key=True),
    db.Column('starred_at', db.DateTime, default=lambda: datetime.now(timezone.utc))
)

repo_collaborators = db.Table('repo_collaborators', db.metadata,
    db.Column('user_id', db.Integer, db.ForeignKey('user.id', name='fk_repo_collaborators_user_id', ondelete='CASCADE'), primary_key=True),
    db.Column('git_repository_id', db.Integer, db.ForeignKey('git_repository.id', name='fk_repo_collaborators_git_repo_id', ondelete='CASCADE'), primary_key=True)
)


# --- Main Models ---
class User(db.Model, UserMixin):
    __tablename__ = 'user'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(1024), nullable=False)
    is_admin = db.Column(db.Boolean, default=False, nullable=False)
    storage_limit_mb = db.Column(db.Integer, nullable=True)
    bio = db.Column(db.String(2500), nullable=True)
    profile_picture_filename = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    last_seen = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    is_online = db.Column(db.Boolean, default=False, index=True)
    is_disabled = db.Column(db.Boolean, default=False)
    max_file_size = db.Column(db.Integer, nullable=True) # Stores size in MB

    github_url = db.Column(db.String(255), nullable=True)
    spotify_url = db.Column(db.String(255), nullable=True)
    youtube_url = db.Column(db.String(255), nullable=True)
    twitter_url = db.Column(db.String(255), nullable=True)
    steam_url = db.Column(db.String(255), nullable=True)
    twitch_url = db.Column(db.String(255), nullable=True)
    discord_server_url = db.Column(db.String(255), nullable=True)
    reddit_url = db.Column(db.String(255), nullable=True)
    preferred_theme = db.Column(db.String(100), nullable=True, default='default')
    preferred_codemirror_theme = db.Column(db.String(100), nullable=True, default='default')

    files = db.relationship('File', backref='owner', lazy='dynamic', cascade="all, delete-orphan")
    notes = db.relationship('Note', backref='author', lazy='dynamic', cascade="all, delete-orphan")
    folders = db.relationship('Folder', foreign_keys='Folder.user_id', backref='owner', lazy='dynamic', cascade="all, delete-orphan")
    ollama_chat_messages = db.relationship('OllamaChatMessage', backref='user', lazy='dynamic', order_by='OllamaChatMessage.timestamp', cascade="all, delete-orphan")
    group_chat_messages = db.relationship('GroupChatMessage', foreign_keys='GroupChatMessage.user_id', backref='sender', lazy='dynamic', order_by='GroupChatMessage.timestamp', cascade="all, delete-orphan")
    posts = db.relationship('Post', foreign_keys='Post.user_id', backref='author', lazy='dynamic', order_by=lambda: Post.timestamp.desc(), cascade="all, delete-orphan")
    comments_authored = db.relationship('Comment', foreign_keys='Comment.user_id', backref='author', lazy='dynamic', cascade="all, delete-orphan")

    followed = db.relationship(
        'User', secondary=followers,
        primaryjoin=(followers.c.follower_id == id),
        secondaryjoin=(followers.c.followed_id == id),
        backref=db.backref('followers', lazy='dynamic', cascade="all"),
        lazy='dynamic'
    )
    sent_direct_messages = db.relationship(
        'DirectMessage',
        foreign_keys='DirectMessage.sender_id',
        backref='author',
        lazy='dynamic',
        cascade="all, delete-orphan",
        order_by='DirectMessage.timestamp'
    )
    received_direct_messages = db.relationship(
        'DirectMessage',
        foreign_keys='DirectMessage.receiver_id',
        backref='recipient',
        lazy='dynamic',
        cascade="all, delete-orphan",
        order_by='DirectMessage.timestamp'
    )
    starred_repositories = db.relationship(
        'GitRepository',
        secondary=repo_stars,
        back_populates='starrers',
        lazy='dynamic',
        cascade="all"
    )
    collaborating_repositories = db.relationship(
        'GitRepository',
        secondary=repo_collaborators,
        back_populates='collaborators',
        lazy='dynamic'
    )
    links = db.relationship('UserLink', backref='user', lazy='dynamic', cascade="all, delete-orphan")


    def is_collaborator_on(self, repo_to_check):
        if not self.is_authenticated:
            return False
        return self.collaborating_repositories.filter(repo_collaborators.c.git_repository_id == repo_to_check.id).count() > 0

    def has_starred_repo(self, repo_to_check):
        if not self.is_authenticated:
            return False
        return self.starred_repositories.filter(repo_stars.c.git_repository_id == repo_to_check.id).count() > 0

    def star_repo(self, repo_to_star):
        if not self.has_starred_repo(repo_to_star):
            self.starred_repositories.append(repo_to_star)

    def unstar_repo(self, repo_to_unstar):
        if self.has_starred_repo(repo_to_unstar):
            self.starred_repositories.remove(repo_to_unstar)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def get_reset_token(self, expires_sec=1800):
        s = URLSafeTimedSerializer(current_app.config['SECRET_KEY'])
        return s.dumps({'user_id': self.id})

    @staticmethod
    def verify_reset_token(token, expires_sec=1800):
        s = URLSafeTimedSerializer(current_app.config['SECRET_KEY'])
        try:
            data = s.loads(token, max_age=expires_sec)
            user_id = data.get('user_id')
        except Exception:
            return None
        return User.query.get(user_id)

    def follow(self, user_to_follow):
        if not self.is_following(user_to_follow) and self.id != user_to_follow.id:
            self.followed.append(user_to_follow)

    def unfollow(self, user_to_unfollow):
        if self.is_following(user_to_unfollow):
            self.followed.remove(user_to_unfollow)

    def is_following(self, user_to_check):
        return self.followed.filter(followers.c.followed_id == user_to_check.id).count() > 0

    def is_followed_by(self, user_to_check):
        return self.followers.filter(followers.c.follower_id == user_to_check.id).count() > 0

    def get_friends(self):
        friends = []
        for followed_user in self.followed:
            if followed_user.is_following(self):
                friends.append(followed_user)
        return friends

    def __repr__(self):
        return f'<User {self.username}>'


class GitRepository(db.Model):
    __tablename__ = 'git_repository'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id', name='fk_git_repository_user_id', ondelete='CASCADE'), nullable=False, index=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text, nullable=True)
    is_private = db.Column(db.Boolean, default=True, nullable=False)
    disk_path = db.Column(db.String(512), unique=True, nullable=False)
    forked_from_id = db.Column(db.Integer, db.ForeignKey('git_repository.id', name='fk_git_repository_fork_source_id', ondelete='SET NULL'), nullable=True, index=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)

    owner = db.relationship('User', backref=db.backref('git_repositories', lazy='dynamic', cascade="all, delete-orphan"))
    source_repo = db.relationship('GitRepository', remote_side=[id], backref=db.backref('forks', lazy='dynamic'), foreign_keys=[forked_from_id])
    starrers = db.relationship('User', secondary=repo_stars, back_populates='starred_repositories', lazy='dynamic')
    collaborators = db.relationship('User', secondary=repo_collaborators, back_populates='collaborating_repositories', lazy='dynamic')

    __table_args__ = (db.UniqueConstraint('user_id', 'name', name='uq_user_repo_name'),)

    def add_collaborator(self, user_to_add):
        if not self.is_collaborator(user_to_add) and self.user_id != user_to_add.id:
            self.collaborators.append(user_to_add)

    def remove_collaborator(self, user_to_remove):
        if self.is_collaborator(user_to_remove):
            self.collaborators.remove(user_to_remove)

    def is_collaborator(self, user_to_check):
        return self.collaborators.filter(repo_collaborators.c.user_id == user_to_check.id).count() > 0

    def get_clone_url(self, external=False):
        base_url = url_for('git.git_homepage', _external=True).rstrip('/') if external else url_for('git.git_homepage').rstrip('/') # Assuming blueprint named 'git'
        return f"{base_url}/{self.owner.username}/{self.name}.git"

    def get_web_url(self, external=False):
        return url_for('git.view_repo_root', owner_username=self.owner.username, repo_short_name=self.name, _external=external) # Assuming blueprint

    @property
    def star_count(self):
        return self.starrers.count()

    def __repr__(self):
        return f'<GitRepository {self.id}: {self.owner.username}/{self.name}>'

class UserLink(db.Model):
    __tablename__ = 'user_link'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    platform_name = db.Column(db.String(50), nullable=False)
    url = db.Column(db.String(500), nullable=False)

    def __repr__(self):
        return f'<UserLink {self.id} for User {self.user_id} - {self.platform_name}>'


class Folder(db.Model):
    __tablename__ = 'folder'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    timestamp = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    parent_folder_id = db.Column(db.Integer, db.ForeignKey('folder.id'), nullable=True)

    # Sharing attributes
    is_public = db.Column(db.Boolean, default=False)
    public_id = db.Column(db.String(36), unique=True, nullable=True)
    public_password_hash = db.Column(db.String(256), nullable=True)

    children = db.relationship('Folder',
                               backref=db.backref('parent', remote_side=[id]),
                               lazy='dynamic',
                               cascade="all, delete-orphan")
    files_in_folder = db.relationship('File',
                                      foreign_keys='File.parent_folder_id',
                                      backref='parent_folder',
                                      lazy='dynamic',
                                      cascade="all, delete-orphan")
    def __repr__(self):
        return f'<Folder {self.id}: {self.name}>'


class Setting(db.Model):
    __tablename__ = 'setting'
    key = db.Column(db.Text, primary_key=True, nullable=False)
    value = db.Column(db.Text, nullable=True)

    @staticmethod
    def get(key, default=None):
        setting = db.session.get(Setting, key)
        return setting.value if setting else default

    @staticmethod
    def set(key, value):
        setting = db.session.get(Setting, key)
        if setting:
            setting.value = str(value)
        else:
            setting = Setting(key=key, value=str(value))
            db.session.add(setting)

    def __repr__(self):
        return f'<Setting {self.key}={self.value}>'


class Note(db.Model):
    __tablename__ = 'note'
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(150), nullable=False)
    content = db.Column(db.Text, nullable=False)
    timestamp = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

    def __repr__(self):
        return f'<Note {self.id}: {self.title}>'


class File(db.Model):
    __tablename__ = 'file'
    id = db.Column(db.Integer, primary_key=True)
    original_filename = db.Column(db.String(255), nullable=False)
    stored_filename = db.Column(db.String(255), unique=True, nullable=False)
    filesize = db.Column(db.BigInteger, nullable=False)
    mime_type = db.Column(db.String(100), nullable=True)
    upload_date = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    parent_folder_id = db.Column(db.Integer, db.ForeignKey('folder.id'), nullable=True)
    is_public = db.Column(db.Boolean, default=False, nullable=False, index=True)
    public_id = db.Column(db.String(36), unique=True, nullable=True, index=True)
    public_password_hash = db.Column(db.String(1024), nullable=True)

    def __repr__(self):
        return f'<File {self.id}: {self.original_filename}>'


class Post(db.Model):
    __tablename__ = 'post'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id', name='fk_post_user_id', ondelete='CASCADE'), nullable=False, index=True)
    text_content = db.Column(db.Text, nullable=True)
    photo_filename = db.Column(db.String(255), nullable=True)
    video_filename = db.Column(db.String(255), nullable=True)
    timestamp = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False, index=True)
    original_post_id = db.Column(db.Integer, db.ForeignKey('post.id', name='fk_post_original_post_id', ondelete='SET NULL'), nullable=True, index=True)
    shared_comment_id = db.Column(db.Integer, db.ForeignKey('comment.id', name='fk_post_shared_comment_id', ondelete='SET NULL'), nullable=True, index=True)

    comments = db.relationship('Comment', foreign_keys='Comment.post_id', backref='post', lazy='select', cascade="all, delete-orphan", order_by=lambda: Comment.timestamp.asc())
    likers = db.relationship('User', secondary=post_likes, lazy='select', backref=db.backref('liked_posts', lazy='dynamic', cascade="all"))
    dislikers = db.relationship('User', secondary=post_dislikes, lazy='select', backref=db.backref('disliked_posts', lazy='dynamic', cascade="all"))
    original_post = db.relationship('Post', remote_side=[id], backref=db.backref('shares', lazy='dynamic', cascade="all, delete-orphan")) # self-referential for shares
    shared_comment = db.relationship('Comment', foreign_keys=[shared_comment_id], backref=db.backref('referenced_in_posts', lazy='select'))


    def __repr__(self):
        return f'<Post {self.id} by User {self.user_id}>'


class Comment(db.Model):
    __tablename__ = 'comment'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id', name='fk_comment_user_id', ondelete='CASCADE'), nullable=False, index=True)
    post_id = db.Column(db.Integer, db.ForeignKey('post.id', name='fk_comment_post_id', ondelete='CASCADE'), nullable=False, index=True)
    text_content = db.Column(db.Text, nullable=False)
    timestamp = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False, index=True)
    parent_id = db.Column(db.Integer, db.ForeignKey('comment.id', name='fk_comment_parent_id', ondelete='CASCADE'), nullable=True, index=True)

    replies = db.relationship('Comment',
                              backref=db.backref('parent_comment', remote_side=[id]),
                              lazy='select',
                              cascade="all, delete-orphan",
                              order_by=lambda: Comment.timestamp.asc())
    likers = db.relationship('User', secondary=comment_likers, lazy='select', backref=db.backref('liked_comments', lazy='dynamic', cascade="all"))
    dislikers = db.relationship('User', secondary=comment_dislikers, lazy='select', backref=db.backref('disliked_comments', lazy='dynamic', cascade="all"))

    def to_dict(self, include_author_details=True, include_replies=False, depth=0, max_depth=1):
        data = {
            'id': self.id,
            'user_id': self.user_id,
            'post_id': self.post_id,
            'parent_id': self.parent_id,
            'text_content': self.text_content,
            'timestamp': self.timestamp.isoformat() + 'Z',
            'like_count': len(self.likers) if self.likers is not None else 0,
            'dislike_count': len(self.dislikers) if self.dislikers is not None else 0,
            'reply_count': len(self.replies) if self.replies is not None else 0,
            'author_username': None, # Initialize
            'author_profile_pic': None # Initialize
        }
        if include_author_details and self.author: # self.author comes from backref
            data['author_username'] = self.author.username
            data['author_profile_pic'] = self.author.profile_picture_filename

        if include_replies and depth < max_depth and self.replies:
            data['replies'] = [reply.to_dict(include_author_details=True, include_replies=True, depth=depth + 1, max_depth=max_depth) for reply in self.replies]
        else:
            data['replies'] = []
        return data

    def __repr__(self):
        return f'<Comment {self.id} by User {self.user_id} on Post {self.post_id}>'


class Notification(db.Model):
    __tablename__ = 'notification'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=False, index=True)
    sender_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=True, index=True)
    type = db.Column(db.String(50), nullable=False, index=True)
    related_post_id = db.Column(db.Integer, db.ForeignKey('post.id', ondelete='CASCADE'), nullable=True, index=True)
    related_comment_id = db.Column(db.Integer, db.ForeignKey('comment.id', ondelete='CASCADE'), nullable=True, index=True)
    related_repo_id = db.Column(db.Integer, db.ForeignKey('git_repository.id', ondelete='CASCADE'), nullable=True, index=True)
    message = db.Column(db.Text, nullable=True)
    is_read = db.Column(db.Boolean, default=False, nullable=False, index=True)
    timestamp = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False, index=True)

    recipient = db.relationship('User', foreign_keys=[user_id], backref=db.backref('notifications_received', lazy='dynamic', cascade="all, delete-orphan"))
    sender = db.relationship('User', foreign_keys=[sender_id], backref=db.backref('notifications_sent', lazy='dynamic')) # No cascade needed for sender
    post = db.relationship('Post', foreign_keys=[related_post_id], backref=db.backref('related_notifications', lazy='select', cascade="all, delete-orphan"))
    comment = db.relationship('Comment', foreign_keys=[related_comment_id], backref=db.backref('related_notifications', lazy='select', cascade="all, delete-orphan"))
    repository = db.relationship('GitRepository', foreign_keys=[related_repo_id], backref=db.backref('related_notifications_repo', lazy='select', cascade="all, delete-orphan"))

    def to_dict(self):
        sender_username = self.sender.username if self.sender else "System"
        text = f"Notification: {self.type}" # Fallback text
        primary_link = "#"

        try:
            if self.type == 'like_post' and self.post:
                text = f"{sender_username} liked your post: \"{self.post.text_content[:30]}...\"" if self.post.text_content else f"{sender_username} liked your media post."
                primary_link = url_for('social.view_single_post', post_id=self.related_post_id)
            elif self.type == 'dislike_post' and self.post:
                text = f"{sender_username} disliked your post: \"{self.post.text_content[:30]}...\"" if self.post.text_content else f"{sender_username} disliked your media post."
                primary_link = url_for('social.view_single_post', post_id=self.related_post_id)
            elif self.type == 'comment_on_post' and self.post and self.comment:
                text = f"{sender_username} commented on your post: \"{self.comment.text_content[:30]}...\""
                primary_link = url_for('social.view_single_post', post_id=self.related_post_id, _anchor=f"comment-{self.related_comment_id}")
            elif self.type == 'reply_to_comment' and self.post and self.comment and getattr(self.comment, 'parent_comment', None):
                text = f"{sender_username} replied to your comment: \"{self.comment.text_content[:30]}...\""
                primary_link = url_for('social.view_single_post', post_id=self.related_post_id, _anchor=f"comment-{self.related_comment_id}")
            elif self.type == 'share_post' and self.post:
                text = f"{sender_username} shared your post: \"{self.post.text_content[:30]}...\"" if self.post.text_content else f"{sender_username} shared your media post."
                primary_link = url_for('social.view_single_post', post_id=self.related_post_id) # Link to original post
            elif self.type == 'share_comment' and self.comment:
                text = f"{sender_username} shared your comment: \"{self.comment.text_content[:30]}...\""
                if self.comment.post:
                    primary_link = url_for('social.view_single_post', post_id=self.comment.post.id, _anchor=f"comment-{self.comment.id}")
            elif self.type == 'new_follower' and self.sender:
                text = f"{sender_username} started following you."
                primary_link = url_for('social.user_profile', username=sender_username) # Assuming 'social' blueprint for profiles
            elif self.type == 'new_post_from_followed_user' and self.post and self.sender:
                text = f"{self.sender.username} (whom you follow) created a new post: \"{self.post.text_content[:30]}...\"" if self.post.text_content else f"{self.sender.username} (whom you follow) created a new media post."
                primary_link = url_for('social.view_single_post', post_id=self.related_post_id)
            elif self.type == 'repo_collaborator_added' and self.repository and self.sender:
                text = f"{self.sender.username} added you as a collaborator to the repository: {self.repository.owner.username}/{self.repository.name}."
                primary_link = url_for('git.view_repo_root', owner_username=self.repository.owner.username, repo_short_name=self.repository.name)
            elif self.type == 'repo_collaborator_removed' and self.repository and self.sender:
                text = f"{self.sender.username} removed you as a collaborator from the repository: {self.repository.owner.username}/{self.repository.name}."
                primary_link = url_for('git.git_homepage') # Or user's own repo page
        except Exception as e:
            current_app.logger.error(f"Error generating notification URL in to_dict for NID {self.id}: {e}")

        return {
            'id': self.id,
            'user_id': self.user_id,
            'sender_id': self.sender_id,
            'sender_username': sender_username,
            'sender_profile_pic': self.sender.profile_picture_filename if self.sender else None,
            'type': self.type,
            'related_post_id': self.related_post_id,
            'related_comment_id': self.related_comment_id,
            'message_text': text,
            'is_read': self.is_read,
            'timestamp': self.timestamp.isoformat() + 'Z' if self.timestamp else None,
            'primary_link': primary_link,
        }

    def __repr__(self):
        return f'<Notification {self.id} for User {self.user_id} - Type: {self.type}>'


class AdminSettings(db.Model):
    __tablename__ = 'admin_settings'
    id = db.Column(db.Integer, primary_key=True)
    allow_registration = db.Column(db.Boolean, default=True)
    default_storage_limit_mb = db.Column(db.Integer, nullable=True)
    max_upload_size_mb = db.Column(db.Integer, default=100)
    ollama_api_url = db.Column(db.String(255), nullable=True)
    ollama_model = db.Column(db.String(100), nullable=True)
    mail_server = db.Column(db.String(120), nullable=True)
    mail_port = db.Column(db.Integer, nullable=True)
    mail_use_tls = db.Column(db.Boolean, default=True)
    mail_use_ssl = db.Column(db.Boolean, default=False)
    mail_username = db.Column(db.String(120), nullable=True)
    mail_password_hashed = db.Column(db.String(255), nullable=True)
    mail_default_sender_name = db.Column(db.String(120), nullable=True, default='PyCloud Notifications')
    mail_default_sender_email = db.Column(db.String(120), nullable=True, default='noreply@example.com')

    # Max media sizes for Posts
    max_photo_upload_mb = db.Column(db.Integer, default=10)
    max_video_upload_mb = db.Column(db.Integer, default=50)


    def __repr__(self):
        return f'<AdminSettings {self.id}>'


class DirectMessage(db.Model):
    __tablename__ = 'direct_message'
    id = db.Column(db.Integer, primary_key=True)
    sender_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=False, index=True)
    receiver_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=False, index=True)
    timestamp = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False, index=True)
    content = db.Column(db.Text, nullable=True)
    file_id = db.Column(db.Integer, db.ForeignKey('file.id', ondelete='SET NULL'), nullable=True, index=True)
    edited_at = db.Column(db.DateTime, nullable=True)
    is_deleted = db.Column(db.Boolean, default=False, nullable=False, index=True)
    deleted_at = db.Column(db.DateTime, nullable=True)
    is_read = db.Column(db.Boolean, default=False, nullable=False, index=True)

    shared_file = db.relationship('File', foreign_keys=[file_id], backref=db.backref('direct_message_shares', lazy='joined', uselist=False))


    def to_dict(self, current_user_id_for_context=None):
        from .utils import is_file_editable
        from .config import VIEWABLE_MIMES
        from .utils import get_user_upload_path

        sender_username = self.author.username if self.author else None
        sender_profile_pic = self.author.profile_picture_filename if self.author else None
        receiver_username = self.recipient.username if self.recipient else None
        direction = None
        if current_user_id_for_context:
            if self.sender_id == current_user_id_for_context: direction = 'outgoing'
            elif self.receiver_id == current_user_id_for_context: direction = 'incoming'

        data = {
            'id': self.id, 'sender_id': self.sender_id, 'sender_username': sender_username,
            'sender_profile_picture_filename': sender_profile_pic,
            'receiver_id': self.receiver_id, 'receiver_username': receiver_username,
            'timestamp': self.timestamp.isoformat() + 'Z', 'content': self.content,
            'file_id': self.file_id, 'shared_file': None,
            'is_edited': bool(self.edited_at),
            'edited_at': self.edited_at.isoformat() + 'Z' if self.edited_at else None,
            'is_deleted': self.is_deleted, 'is_read': self.is_read, 'direction': direction
        }
        if self.shared_file:
            file_data = {
                'id': self.shared_file.id, 'original_filename': self.shared_file.original_filename,
                'mime_type': self.shared_file.mime_type, 'filesize': self.shared_file.filesize,
                'is_editable': is_file_editable(self.shared_file.original_filename, self.shared_file.mime_type),
                'view_url': None, 'download_url': None, 'preview_content': None, 'has_more_content': False
            }
            try:
                if self.shared_file.mime_type in current_app.config.get('VIEWABLE_MIMES', VIEWABLE_MIMES):
                    file_data['view_url'] = url_for('file_routes.view_file', file_id=self.shared_file.id) # Assuming blueprint
                file_data['download_url'] = url_for('file_routes.download_file', file_id=self.shared_file.id) # Assuming blueprint

                if self.shared_file.mime_type == 'text/plain':
                    import os, codecs
                    file_owner_user_id = self.shared_file.user_id
                    _upload_folder_from_config = current_app.config.get("UPLOAD_FOLDER")
                    if _upload_folder_from_config:
                        path_to_file = os.path.join(_upload_folder_from_config, str(file_owner_user_id), self.shared_file.stored_filename)
                        if os.path.exists(path_to_file):
                            with codecs.open(path_to_file, 'r', encoding='utf-8', errors='replace') as f:
                                content_plus_one = f.read(501)
                                file_data['preview_content'] = content_plus_one[:500]
                                file_data['has_more_content'] = len(content_plus_one) > 500
                        else: file_data['preview_content'] = "[Preview unavailable: File missing]"
                    else: file_data['preview_content'] = "[Preview unavailable: Config missing]"

            except Exception as e_url:
                current_app.logger.warning(f"Could not generate URLs or preview for DM file {self.shared_file.id}: {e_url}")
            data['shared_file'] = file_data
        return data

    def __repr__(self):
        return f'<DirectMessage {self.id} from {self.sender_id} to {self.receiver_id}>'


class OllamaChatMessage(db.Model):
    __tablename__ = 'ollama_chat_message'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    role = db.Column(db.String(10), nullable=False)
    content = db.Column(db.Text, nullable=False)
    timestamp = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False, index=True)

    def to_dict(self):
        sender_username = None
        sender_profile_picture_filename = None
        if self.role == 'user' and self.user:
            sender_username = self.user.username
            sender_profile_picture_filename = self.user.profile_picture_filename
        elif self.role == 'assistant':
            sender_username = 'Ollama AI'
            sender_profile_picture_filename = 'ollama_pfp.png'
        elif self.role == 'thinking':
            sender_username = 'System'
            sender_profile_picture_filename = 'ollama_pfp.png'
        return {
            "id": self.id, "user_id": self.user_id, "role": self.role, "content": self.content,
            "timestamp": self.timestamp.isoformat() + 'Z' if self.timestamp else None,
            "sender_username": sender_username,
            "sender_profile_picture_filename": sender_profile_picture_filename
        }
    def __repr__(self):
        return f'<OllamaChatMessage {self.id} (User: {self.user_id}, Role: {self.role})>'


class GroupChatMessage(db.Model):
    __tablename__ = 'group_chat_message'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=False, index=True)
    timestamp = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False, index=True)
    content = db.Column(db.Text, nullable=True)
    file_id = db.Column(db.Integer, db.ForeignKey('file.id', ondelete='SET NULL'), nullable=True, index=True)
    edited_at = db.Column(db.DateTime, nullable=True)
    is_deleted = db.Column(db.Boolean, default=False, nullable=False, index=True)
    deleted_at = db.Column(db.DateTime, nullable=True)

    shared_file = db.relationship('File', foreign_keys=[file_id], backref=db.backref('group_chat_shares', lazy='joined', uselist=False), single_parent=True, post_update=True)


    def to_dict(self, include_sender=True, include_file=True):
        from .utils import is_file_editable
        from .config import VIEWABLE_MIMES

        sender_username = self.sender.username if include_sender and self.sender else None
        sender_profile_pic = self.sender.profile_picture_filename if include_sender and self.sender else None

        data = {
            'id': self.id, 'user_id': self.user_id,
            'timestamp': self.timestamp.isoformat() + 'Z', 'content': self.content,
            'file_id': self.file_id, 'sender_username': sender_username,
            'sender_profile_picture_filename': sender_profile_pic, 'shared_file': None,
            'is_edited': bool(self.edited_at), 'is_deleted': self.is_deleted,
            'edited_at': self.edited_at.isoformat() + 'Z' if self.edited_at else None
        }
        if include_file and self.shared_file:
            file_data = {
                'id': self.shared_file.id, 'original_filename': self.shared_file.original_filename,
                'mime_type': self.shared_file.mime_type, 'filesize': self.shared_file.filesize,
                'is_editable': is_file_editable(self.shared_file.original_filename, self.shared_file.mime_type),
                'view_url': None, 'download_url': None, 'preview_content': None, 'has_more_content': False
            }
            try:
                if self.shared_file.mime_type in current_app.config.get('VIEWABLE_MIMES', VIEWABLE_MIMES):
                    file_data['view_url'] = url_for('file_routes.view_file', file_id=self.shared_file.id)
                file_data['download_url'] = url_for('file_routes.download_file', file_id=self.shared_file.id)

                if self.shared_file.mime_type == 'text/plain':
                    import os, codecs
                    _upload_folder_from_config = current_app.config.get("UPLOAD_FOLDER")
                    if _upload_folder_from_config:
                        path_to_file = os.path.join(_upload_folder_from_config, str(self.shared_file.user_id), self.shared_file.stored_filename)
                        if os.path.exists(path_to_file):
                            with codecs.open(path_to_file, 'r', encoding='utf-8', errors='replace') as f:
                                content_plus_one = f.read(501)
                                file_data['preview_content'] = content_plus_one[:500]
                                file_data['has_more_content'] = len(content_plus_one) > 500
                        else: file_data['preview_content'] = "[Preview unavailable: File missing]"
                    else: file_data['preview_content'] = "[Preview unavailable: Config missing]"
            except Exception as e_url_file:
                 current_app.logger.warning(f"Could not generate URLs/preview for GCM file {self.shared_file.id}: {e_url_file}")
            data['shared_file'] = file_data
        return data

    def __repr__(self):
        file_info = f", FileID: {self.file_id}" if self.file_id else ""
        return f'<GroupChatMessage {self.id} (User: {self.user_id}{file_info})>'


class MonitoredServer(db.Model):
    __tablename__ = 'monitored_server'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=False, index=True)
    name = db.Column(db.String(100), nullable=False)
    host = db.Column(db.String(255), nullable=False)
    port = db.Column(db.Integer, nullable=False, default=65432)
    password = db.Column(db.String(255), nullable=False)
    display_order = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    owner = db.relationship('User', backref=db.backref('monitored_servers', lazy='dynamic', cascade="all, delete-orphan"))

    __table_args__ = (
        UniqueConstraint('user_id', 'name', name='uq_user_server_name'),
        UniqueConstraint('user_id', 'host', 'port', name='uq_user_server_host_port'), # <-- ADD THIS
    )

    def __repr__(self):
        return f'<MonitoredServer {self.name} ({self.host}:{self.port}) for User {self.user_id}>'
