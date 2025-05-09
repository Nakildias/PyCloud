import os
import uuid
from datetime import timedelta
import json
import logging
import sqlalchemy as sa
from wtforms import BooleanField
from datetime import datetime
from sqlalchemy.orm import relationship, backref, aliased
from wtforms import TextAreaField
from flask import abort
from flask_wtf.csrf import CSRFProtect, generate_csrf
from werkzeug.utils import secure_filename
from flask import send_from_directory
from flask_wtf.file import FileField, FileAllowed, FileRequired
import requests
from wtforms import BooleanField, IntegerField
from wtforms.validators import NumberRange
import re
from wtforms import URLField
from wtforms.validators import URL
from werkzeug.exceptions import BadRequest
import shutil
import zipfile
import mimetypes
import codecs
from sqlalchemy.exc import IntegrityError
from wtforms.validators import Optional, InputRequired
from flask import (Flask, render_template, redirect, url_for, flash, request, session, jsonify, current_app)
from flask_sqlalchemy import SQLAlchemy
from flask_login import (LoginManager, UserMixin, login_user, logout_user, login_required, current_user)
from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, SubmitField, BooleanField, EmailField
from wtforms.validators import DataRequired, Length, Email, EqualTo, ValidationError
from werkzeug.security import generate_password_hash, check_password_hash
from itsdangerous import URLSafeTimedSerializer
from flask_mail import Mail
from flask_mail import Message
from PIL import Image, ImageSequence

# --- Basic Logging Setup ---
logging.basicConfig(level=logging.INFO) # Log informational messages and above

# --- Configuration ---
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DB_NAME = 'database.db'
INSTANCE_FOLDER_PATH = os.path.join(BASE_DIR, 'instance')
UPLOAD_FOLDER = os.path.join(INSTANCE_FOLDER_PATH, 'uploads')
POST_MEDIA_FOLDER = os.path.join(INSTANCE_FOLDER_PATH, 'uploads', 'post_media')

DEFAULT_SETTINGS = {
    'allow_registration': 'true',
    'default_storage_limit_mb': '1024',
    'max_upload_size_mb': '100', # Default max file upload size
    'ollama_api_url': '',
    'ollama_model': 'llama3.2:3b',
    'MAIL_SERVER': 'smtp.gmail.com',
    'MAIL_PORT': '465',
    'MAIL_USE_TLS': 'false',
    'MAIL_USE_SSL': 'true',
    'MAIL_USERNAME': 'noreply@example.com',
    'MAIL_PASSWORD': '', # Store sensitive defaults securely if possible (e.g., env vars)
    'MAIL_DEFAULT_SENDER_NAME': 'PyCloud',
    'MAIL_DEFAULT_SENDER_EMAIL': 'noreply@example.com'
}

DEFAULT_MAX_UPLOAD_MB_FALLBACK = 100
# --- ADDED: Define defaults for post media limits ---
DEFAULT_MAX_PHOTO_MB = 10
DEFAULT_MAX_VIDEO_MB = 50

# --- Viewable MIME Types ---
# Common types browsers can typically display directly
VIEWABLE_IMAGE_MIMES = {'image/jpeg', 'image/png', 'image/gif', 'image/webp', 'image/svg+xml', 'image/bmp'}
VIEWABLE_VIDEO_MIMES = {'video/mp4', 'video/webm', 'video/ogg', 'video/mkv'}
# Could also add audio, pdf etc. if desired
VIEWABLE_AUDIO_MIMES = {'audio/mpeg', 'audio/ogg', 'audio/wav', 'audio/mp3'}
VIEWABLE_PDF_MIMES = {'application/pdf'}

# Combine them for easier checking
VIEWABLE_MIMES = VIEWABLE_IMAGE_MIMES.union(VIEWABLE_VIDEO_MIMES).union(VIEWABLE_AUDIO_MIMES).union(VIEWABLE_PDF_MIMES)

EDITABLE_EXTENSIONS = {
    '', 'txt', 'md', 'markdown', 'json', 'yaml', 'yml', 'xml', 'csv', 'log',
    'py', 'js', 'css', 'html', 'htm', 'sh', 'bash', 'ps1', 'ini', 'cfg', 'conf', 'config',
    'sql', 'java', 'c', 'cpp', 'h', 'hpp', 'rb', 'php', 'pl', 'gitignore', 'dockerfile', 'env',
    'bat', 'cmd', # Add other common plain text formats as needed
}

app = Flask(__name__, instance_path=INSTANCE_FOLDER_PATH) # Tell Flask about the instance folder
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER # Store path for reference if needed
csrf = CSRFProtect(app)
app.config['SECRET_KEY'] = os.urandom(24) # Replace with a static key for production
app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{os.path.join(BASE_DIR, DB_NAME)}'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=7)
app.config['VIEWABLE_MIMES'] = VIEWABLE_MIMES
app.config['EDITABLE_EXTENSIONS'] = EDITABLE_EXTENSIONS
mail = Mail(app)

# Helper to get post media upload path
def get_post_media_path():
    """Helper function to get the upload path for post media INSIDE static folder."""
    # Use app.root_path to get project root, then navigate to static/uploads/post_media
    path = os.path.join(app.root_path, 'static', 'uploads', 'post_media')
    # Ensure the directory exists
    try:
        os.makedirs(path, exist_ok=True)
    except OSError as e:
         # Log error if directory creation fails
         app.logger.error(f"Could not create post media directory: {path} - Error: {e}", exc_info=True)
         # Depending on desired behavior, you might raise the error
         # or return None to indicate failure, which should be handled in create_post
         raise  # Re-raise the error to prevent saving if directory fails
    return path

def configure_mail_from_db(current_app):
    with current_app.app_context(): # Ensure DB operations are within context
        current_app.config.update(
            MAIL_SERVER = Setting.get('MAIL_SERVER', 'your_smtp_server'),
            MAIL_PORT = int(Setting.get('MAIL_PORT', 587)),
            MAIL_USE_TLS = Setting.get('MAIL_USE_TLS', 'true').lower() == 'true',
            MAIL_USE_SSL = Setting.get('MAIL_USE_SSL', 'false').lower() == 'true',
            MAIL_USERNAME = Setting.get('MAIL_USERNAME', 'your_email_username'),
            MAIL_PASSWORD = Setting.get('MAIL_PASSWORD', 'your_email_password')
            # MAIL_DEFAULT_SENDER = Setting.get('MAIL_DEFAULT_SENDER', ('Your App Name', 'noreply@yourapp.com'))
        )
        # Handle MAIL_DEFAULT_SENDER separately as it might be a tuple
        sender_name_db = Setting.get('MAIL_DEFAULT_SENDER_NAME', 'Your App Name')
        sender_email_db = Setting.get('MAIL_DEFAULT_SENDER_EMAIL', 'noreply@yourapp.com')
        if sender_name_db:
            current_app.config['MAIL_DEFAULT_SENDER'] = (sender_name_db, sender_email_db)
        else:
            current_app.config['MAIL_DEFAULT_SENDER'] = sender_email_db
# --- Helper function to recursively register extracted items ---
def register_extracted_items(extract_base_dir, user_id, parent_folder_id_in_db, user_upload_root):

    newly_created_folder_map = {} # Maps disk path -> new DB Folder ID

    for root, dirs, files in os.walk(extract_base_dir, topdown=True): # topdown=True helps create parent folders first
        # Determine current parent folder ID in DB for items in this 'root'
        current_parent_db_id = parent_folder_id_in_db
        relative_path_from_extract_base = os.path.relpath(root, extract_base_dir)

        if relative_path_from_extract_base != '.':
             # It's a sub-directory within the extracted structure
             parent_disk_path = os.path.dirname(root)
             if parent_disk_path in newly_created_folder_map:
                 current_parent_db_id = newly_created_folder_map[parent_disk_path]
             # else: it should theoretically be the initial parent_folder_id_in_db
             #      or an error occurred. More robust path mapping needed for deep nesting.

        # Register Directories first
        for dirname in dirs:
            dir_path_on_disk = os.path.join(root, dirname)
            sanitized_dirname = secure_filename(dirname) # Sanitize folder name

            if not sanitized_dirname: # Skip folders with unusable names
                app.logger.warning(f"Skipping extracted folder with invalid name: {dirname} in {root}")
                # Remove the directory from 'dirs' so os.walk doesn't descend into it
                dirs.remove(dirname) # Careful when modifying dirs list during iteration
                continue

            # Check if folder already exists in DB under this parent
            existing_folder = Folder.query.filter_by(
                user_id=user_id,
                parent_folder_id=current_parent_db_id,
                name=sanitized_dirname
            ).first()

            if not existing_folder:
                try:
                    new_folder = Folder(
                        name=sanitized_dirname,
                        user_id=user_id,
                        parent_folder_id=current_parent_db_id
                    )
                    db.session.add(new_folder)
                    db.session.flush() # Assigns an ID to new_folder without full commit
                    newly_created_folder_map[dir_path_on_disk] = new_folder.id
                    app.logger.info(f"Registered extracted folder: {sanitized_dirname} (ID: {new_folder.id})")
                except Exception as e:
                    app.logger.error(f"Error registering extracted folder '{sanitized_dirname}': {e}", exc_info=True)
                    # Should ideally trigger a rollback of the whole extraction registration
                    raise # Re-raise to be caught by the main route's try/except

            else:
                 # Folder already exists, map its path to its existing ID
                 newly_created_folder_map[dir_path_on_disk] = existing_folder.id


        # Register Files
        for filename in files:
            filepath_on_disk = os.path.join(root, filename)
            original_sanitized_filename = secure_filename(filename)

            if not original_sanitized_filename:
                 app.logger.warning(f"Skipping extracted file with invalid name: {filename} in {root}")
                 continue # Skip this file

            # --- Rename file to UUID on disk ---
            try:
                _, ext = os.path.splitext(filename)
                new_stored_filename = str(uuid.uuid4()) + ext
                new_filepath_on_disk = os.path.join(user_upload_root, new_stored_filename) # Save in user's flat root dir
                os.rename(filepath_on_disk, new_filepath_on_disk)
                app.logger.debug(f"Renamed extracted file {filepath_on_disk} to {new_filepath_on_disk}")
                filepath_on_disk = new_filepath_on_disk # Update path for DB record
            except OSError as e:
                app.logger.error(f"Error renaming extracted file '{filename}' to UUID: {e}", exc_info=True)
                continue # Skip this file if rename fails

            # Create DB record
            try:
                filesize = os.path.getsize(filepath_on_disk)
                mime_type = mimetypes.guess_type(filepath_on_disk)[0] or 'application/octet-stream'

                new_file = File(
                    original_filename=original_sanitized_filename,
                    stored_filename=new_stored_filename, # The UUID-based name
                    filesize=filesize,
                    mime_type=mime_type,
                    user_id=user_id,
                    parent_folder_id=current_parent_db_id # Belongs to the folder it was found in
                )
                db.session.add(new_file)
                app.logger.info(f"Registered extracted file: {original_sanitized_filename} (Stored: {new_stored_filename}, Parent ID: {current_parent_db_id})")

            except Exception as e:
                 app.logger.error(f"Error registering extracted file '{original_sanitized_filename}': {e}", exc_info=True)
                 # Clean up the renamed file if DB registration fails
                 if os.path.exists(filepath_on_disk):
                     try: os.remove(filepath_on_disk)
                     except OSError: pass
                 raise # Re-raise to be caught by the main route's try/except

# --- Recursive Helper Function ---
def add_folder_to_zip(zipf, folder_id, user_id, current_arc_path, user_upload_path):
    # Find immediate subfolders
    subfolders = Folder.query.filter_by(user_id=user_id, parent_folder_id=folder_id).all()
    for subfolder in subfolders:
        # Define the path for this subfolder inside the archive
        subfolder_arc_path = os.path.join(current_arc_path, subfolder.name)
        # Optional: Add empty directory entry (often not needed, zipfile creates dirs)
        # zipf.writestr(subfolder_arc_path + '/', '')
        # Recurse into the subfolder
        add_folder_to_zip(zipf, subfolder.id, user_id, subfolder_arc_path, user_upload_path)

    # Find immediate files in this folder
    files = File.query.filter_by(user_id=user_id, parent_folder_id=folder_id).all()
    for file_record in files:
        physical_file_path = os.path.join(user_upload_path, file_record.stored_filename)
        file_arc_path = os.path.join(current_arc_path, file_record.original_filename)

        if os.path.exists(physical_file_path):
            try:
                zipf.write(physical_file_path, file_arc_path)
                app.logger.debug(f"Added to zip: {physical_file_path} as {file_arc_path}")
            except Exception as e:
                app.logger.warning(f"Could not add file {physical_file_path} to zip: {e}")
                # Decide: continue or raise error? Continue for now.
        else:
            app.logger.warning(f"Physical file not found for DB record {file_record.id} at {physical_file_path}")

def get_archive_uncompressed_size(archive_path):
    """
    Calculates the total uncompressed size of files within an archive.
    Currently supports ZIP files. Returns total size in bytes or raises error.
    """
    total_size = 0
    file_ext = os.path.splitext(archive_path)[1].lower()

    try:
        if file_ext == '.zip':
            if not zipfile.is_zipfile(archive_path):
                 raise ValueError("File is not a valid ZIP archive.")
            with zipfile.ZipFile(archive_path, 'r') as zipf:
                for member in zipf.infolist():
                    # Ignore directories, only sum file sizes
                    if not member.is_dir():
                        total_size += member.file_size
        # --- Add support for other types here if needed ---
        # elif file_ext == '.7z':
        #     # Requires py7zr library: pip install py7zr
        #     try:
        #         import py7zr
        #         with py7zr.SevenZipFile(archive_path, mode='r') as z:
        #             # py7zr might not directly expose uncompressed size easily in metadata
        #             # You might need to iterate and sum 'size' attribute if available,
        #             # but be aware this might be compressed size for some formats/libs.
        #             # Consult py7zr documentation for best way to get uncompressed sizes.
        #             # Placeholder: Assume 'size' is uncompressed (NEEDS VERIFICATION)
        #             total_size = sum(f.size for f in z.list() if not f.is_directory) # Example, needs check!
        #     except ImportError:
        #         raise NotImplementedError("7z extraction requires 'py7zr' library.")
        #     except Exception as e: # Catch py7zr specific errors
        #          raise ValueError(f"Failed to read 7z archive metadata: {e}")

        # elif file_ext == '.rar':
        #    # Requires rarfile library and potentially unrar command line tool
        #    # Implementation depends heavily on rarfile library capabilities
        #    raise NotImplementedError("RAR metadata reading not implemented.")
        else:
            # Don't raise error, just return 0 if type unknown/unsupported by this function
            # The main route will still check if extraction is supported at all later.
            app.logger.warning(f"Cannot determine uncompressed size for unknown type: {file_ext}")
            return 0 # Or perhaps raise NotImplementedError? Returning 0 skips pre-check.

        return total_size

    except zipfile.BadZipFile: # Specific error for zip
         raise ValueError("Invalid or corrupted ZIP archive.")
    except FileNotFoundError:
         raise ValueError("Archive file not found for size check.")
    except Exception as e: # Catch other potential errors during file read
        app.logger.error(f"Error reading archive metadata for size check ({archive_path}): {e}", exc_info=True)
        raise ValueError(f"Could not read archive metadata: {e}")

@app.context_processor
def inject_settings():
    """Inject settings into template context."""
    settings_dict = {}
    try:
        # Fetch commonly needed settings here
        settings_dict['allow_registration'] = (Setting.get('allow_registration', 'true') == 'true')
        # Add other settings as needed:
        # settings_dict['site_name'] = Setting.get('site_name', 'My Web Service')

        # --- Add Ollama Enabled Check ---
        ollama_url = Setting.get('ollama_api_url', '') # Get URL, default to empty string
        ollama_model = Setting.get('ollama_model', '') # Get model, default to empty string
        # Consider enabled only if both URL and Model have non-empty values
        settings_dict['ollama_enabled'] = bool(ollama_url and ollama_model)
        # --- End Ollama Check ---

    except Exception as e:
        # Handle cases where DB might not be ready yet during initial setup/errors
        app.logger.error(f"Error injecting settings into context: {e}")
        settings_dict['allow_registration'] = True # Default fallback
        settings_dict['allow_registration'] = True # Default fallback
        settings_dict['ollama_enabled'] = False # Default fallback for Ollama

    return dict(settings=settings_dict)


# --- Database Setup ---
db = SQLAlchemy(app)

# --- Login Manager Setup ---
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login' # Route function name for the login page
login_manager.login_message_category = 'info' # Flash message category

@login_manager.user_loader
def load_user(user_id):
    """Loads user from the database based on user_id stored in session."""
    return db.session.get(User, int(user_id))

# --- Database Models ---
followers = db.Table('followers',
    db.Column('follower_id', db.Integer, db.ForeignKey('user.id')),
    db.Column('followed_id', db.Integer, db.ForeignKey('user.id'))
)
class User(db.Model, UserMixin):
    """User model for storing user details."""
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)
    is_admin = db.Column(db.Boolean, default=False, nullable=False)
    storage_limit_mb = db.Column(db.Integer, nullable=True) # NULL means use default
    files = db.relationship('File', backref='owner', lazy='dynamic', cascade="all, delete-orphan")
    notes = db.relationship('Note', backref='author', lazy=True, cascade="all, delete-orphan")
    bio = db.Column(db.String(2500), nullable=True)
    profile_picture_filename = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    # --- Link Fields ---
    github_url = db.Column(db.String(255), nullable=True)
    spotify_url = db.Column(db.String(255), nullable=True)
    youtube_url = db.Column(db.String(255), nullable=True)
    twitter_url = db.Column(db.String(255), nullable=True)
    steam_url = db.Column(db.String(255), nullable=True)
    twitch_url = db.Column(db.String(255), nullable=True)
    discord_server_url = db.Column(db.String(255), nullable=True)
    reddit_url = db.Column(db.String(255), nullable=True)
    # --- End Link Fields ---
    folders = db.relationship('Folder',
                              foreign_keys='Folder.user_id', # Specify FK for user relationship
                              backref='owner',
                              lazy='dynamic',
                              cascade="all, delete-orphan")

    followed = db.relationship(
        'User', secondary=followers,
        primaryjoin=(followers.c.follower_id == id),
        secondaryjoin=(followers.c.followed_id == id),
        backref=db.backref('followers', lazy='dynamic'), # Users who follow this user
        lazy='dynamic'
    )

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    # --- ADD THESE METHODS ---
    def get_reset_token(self, expires_sec=1800): # 1800 seconds = 30 minutes
        s = URLSafeTimedSerializer(current_app.config['SECRET_KEY'])
        return s.dumps({'user_id': self.id})

    @staticmethod
    def verify_reset_token(token, expires_sec=1800): # Match expiration time
        s = URLSafeTimedSerializer(current_app.config['SECRET_KEY'])
        try:
            # Pass max_age to loads() to check expiration
            data = s.loads(token, max_age=expires_sec)
            user_id = data.get('user_id')
        except Exception: # Catches BadSignature, SignatureExpired, etc.
            return None
        return User.query.get(user_id)
    # --- END OF METHODS TO ADD ---

    # Helper methods for following
    def follow(self, user):
        if not self.is_following(user):
            self.followed.append(user)
            return self

    def unfollow(self, user):
        if self.is_following(user):
            self.followed.remove(user)
            return self

    def is_following(self, user):
        return self.followed.filter(followers.c.followed_id == user.id).count() > 0

    def __repr__(self):
        return f'<User {self.username}>'

class CreateFolderForm(FlaskForm):
    """Form for creating a new folder."""
    # Basic validation: required, reasonable length. More could be added.
    name = StringField('Folder Name', validators=[
        DataRequired(message="Folder name cannot be empty."),
        Length(min=1, max=100, message="Folder name must be between 1 and 100 characters.")
        # We'll add custom validation in the route for illegal characters/duplicates
    ])
    submit = SubmitField('Create Folder')

class UserLink(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    platform_name = db.Column(db.String(50), nullable=False) # e.g., "GitHub", "Spotify"
    url = db.Column(db.String(500), nullable=False)
    user = db.relationship('User', backref=db.backref('links', lazy='dynamic', cascade="all, delete-orphan"))

class EditFileForm(FlaskForm):
    """Form for editing file content."""
    content = TextAreaField('File Content', validators=[DataRequired()]) # Basic validation
    submit = SubmitField('Save Changes')

class EditUserForm(FlaskForm):
    """Form for administrators to edit user details."""
    username = StringField('Username',
                           validators=[DataRequired(), Length(min=4, max=25)])
    email = EmailField('Email',
                       validators=[DataRequired(), Email()])
    is_admin = BooleanField('Administrator Status')
    # Storage limit field: Optional() allows it to be empty
    # If empty, we'll interpret as "use default" (set DB field to None)
    storage_limit_mb = IntegerField(
        'Specific Storage Limit (MB)',
        validators=[
            Optional(), # Makes the field optional
            NumberRange(min=0, message='Storage limit must be 0 or greater.')
        ],
        description="Leave blank to use the default limit. Enter 0 for explicitly unlimited."
    )
    submit = SubmitField('Update User')

    # Need to store the original user ID to check for duplicate username/email correctly
    def __init__(self, original_username=None, original_email=None, *args, **kwargs):
        super(EditUserForm, self).__init__(*args, **kwargs)
        self.original_username = original_username
        self.original_email = original_email

    # Custom validator to check if username already exists (ignoring the current user)
    def validate_username(self, username):
        if username.data != self.original_username:
            user = User.query.filter_by(username=username.data).first()
            if user:
                raise ValidationError('That username is already taken. Please choose another.')

    # Custom validator to check if email already exists (ignoring the current user)
    def validate_email(self, email):
        if email.data != self.original_email:
            user = User.query.filter_by(email=email.data).first()
            if user:
                raise ValidationError('That email is already registered. Please use another.')

class EditProfileForm(FlaskForm):
    username = StringField('Username', validators=[DataRequired(), Length(min=4, max=25)])
    email = EmailField('Email', validators=[DataRequired(), Email()])
    bio = TextAreaField('Bio', validators=[Optional(), Length(max=2500)])
    profile_picture = FileField('Profile Picture', validators=[
        Optional(),
        FileAllowed(['jpg', 'png', 'jpeg', 'gif'], 'Images only!')
    ])
    # Add fields for links here (see section 3)
    github_url = URLField('GitHub URL', validators=[Optional(), URL()])
    spotify_url = URLField('Spotify URL', validators=[Optional(), URL()])
    youtube_url = URLField('YouTube URL', validators=[Optional(), URL()])
    twitter_url = URLField('X (Twitter) URL', validators=[Optional(), URL()])
    steam_url = URLField('Steam URL', validators=[Optional(), URL()])
    twitch_url = URLField('Twitch URL', validators=[Optional(), URL()])
    discord_server_url = URLField('Discord Server URL', validators=[Optional(), URL()])
    reddit_url = URLField('Reddit URL', validators=[Optional(), URL()])
    # Add more as needed

    submit = SubmitField('Update Profile')

    def __init__(self, original_username=None, original_email=None, *args, **kwargs):
        super(EditProfileForm, self).__init__(*args, **kwargs)
        self.original_username = original_username
        self.original_email = original_email

    def validate_username(self, username):
        if username.data != self.original_username:
            user = User.query.filter_by(username=username.data).first()
            if user:
                raise ValidationError('That username is already taken. Please choose another.')

    def validate_email(self, email):
        if email.data != self.original_email:
            user = User.query.filter_by(email=email.data).first()
            if user:
                raise ValidationError('That email is already registered. Please use another.')

class Folder(db.Model):
    """Model for storing folders."""
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    # Foreign key to link Folder to a User
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

    # Self-referential foreign key for parent folder
    parent_folder_id = db.Column(db.Integer, db.ForeignKey('folder.id'), nullable=True) # Nullable for root folders

    # Relationship to child folders (self-referential)
    # 'children' accesses sub-folders (e.g., current_folder.children)
    # backref 'parent' adds parent attribute to access parent folder (e.g., sub_folder.parent)
    # remote_side=[id] is needed for self-referential one-to-many
    children = db.relationship('Folder',
                               backref=db.backref('parent', remote_side=[id]),
                               lazy='dynamic',
                               cascade="all, delete-orphan")

    # Relationship to files within this folder
    # 'files_in_folder' accesses files (e.g., current_folder.files_in_folder)
    # Use a different backref name than User.files to avoid conflict
    files_in_folder = db.relationship('File',
                                      foreign_keys='File.parent_folder_id', # Specify FK
                                      backref='parent_folder',
                                      lazy='dynamic',
                                      cascade="all, delete-orphan")

    def __repr__(self):
        return f'<Folder {self.id}: {self.name}>'

class Setting(db.Model):
    """Model for storing application settings."""
    # Use Text for key for flexibility, ensure it's the primary key
    key = db.Column(db.Text, primary_key=True, nullable=False)
    # Use Text for value to store various types (e.g., 'true'/'false', numbers as strings)
    value = db.Column(db.Text, nullable=True)

    def __repr__(self):
        return f'<Setting {self.key}={self.value}>'

    @staticmethod
    def get(key, default=None):
        """Helper method to get a setting value."""
        setting = db.session.get(Setting, key) # Use db.session.get for PK lookups
        return setting.value if setting else default

    @staticmethod
    def set(key, value):
        """Helper method to set or update a setting value."""
        setting = db.session.get(Setting, key)
        if setting:
            setting.value = str(value) # Store as string
        else:
            setting = Setting(key=key, value=str(value))
            db.session.add(setting)
        # Commit should happen within the route after calling set
        # db.session.commit() # Avoid committing here directly

class Note(db.Model):
    """Model for storing user notes."""
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(150), nullable=False)
    content = db.Column(db.Text, nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    # Foreign Key to link Note to a User
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

    def __repr__(self):
        return f'<Note {self.id}: {self.title}>'

class NoteForm(FlaskForm):
    """Form for creating and editing notes."""
    title = StringField('Title', validators=[DataRequired(), Length(max=150)])
    content = TextAreaField('Content', validators=[DataRequired()])
    submit = SubmitField('Save Note')

class File(db.Model):
    """Model for storing uploaded file metadata."""
    id = db.Column(db.Integer, primary_key=True)
    original_filename = db.Column(db.String(255), nullable=False)
    # Store a unique name on disk to prevent collisions and handle funny characters
    stored_filename = db.Column(db.String(255), unique=True, nullable=False)
    # Store relative path within user's dir (often just the stored_filename itself if flat)
    # filepath = db.Column(db.String(512), nullable=False) # Might not be needed if always stored_filename
    filesize = db.Column(db.Integer, nullable=False) # Size in bytes
    mime_type = db.Column(db.String(100), nullable=True) # Detected MIME type
    upload_date = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    # Add foreign key to link File to a Folder (nullable for root files)
    parent_folder_id = db.Column(db.Integer, db.ForeignKey('folder.id'), nullable=True)

    # --- Add Sharing Fields ---
    is_public = db.Column(db.Boolean, default=False, nullable=False, index=True)
    # Store UUID as string. Ensure unique=True constraint is added.
    public_id = db.Column(db.String(36), unique=True, nullable=True, index=True)
    # --- End Sharing Fields ---
    public_password_hash = db.Column(db.String(128), nullable=True) # Store hash, not plain text

    # Add relationship back to User if needed (User model already has 'files' potentially)
    # owner = db.relationship('User', backref=backref('files', lazy=True))

    def __repr__(self):
        return f'<File {self.id}: {self.original_filename}>'

# Association table for Post Likes
post_likes = db.Table('post_likes',
    db.Column('user_id', db.Integer, db.ForeignKey('user.id'), primary_key=True),
    db.Column('post_id', db.Integer, db.ForeignKey('post.id'), primary_key=True)
)

# Association table for Post Dislikes
post_dislikes = db.Table('post_dislikes',
    db.Column('user_id', db.Integer, db.ForeignKey('user.id'), primary_key=True),
    db.Column('post_id', db.Integer, db.ForeignKey('post.id'), primary_key=True)
)

class Post(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    text_content = db.Column(db.Text, nullable=True)
    photo_filename = db.Column(db.String(255), nullable=True)
    video_filename = db.Column(db.String(255), nullable=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)
    original_post_id = db.Column(db.Integer, db.ForeignKey('post.id'), nullable=True, index=True)

    author = db.relationship('User', backref=db.backref('posts', lazy='dynamic', order_by='Post.timestamp.desc()'))
    comments = db.relationship('Comment', backref='post', lazy='dynamic', cascade="all, delete-orphan", order_by='Comment.timestamp.asc()')

    # Relationships for likes and dislikes
    comments = db.relationship('Comment', backref='post',
                               lazy='select',  # CHANGED FROM 'dynamic'
                               cascade="all, delete-orphan",
                               order_by='Comment.timestamp.asc()')
    likers = db.relationship('User', secondary=post_likes,
                             lazy='select',  # CHANGED FROM 'dynamic'
                             backref=db.backref('liked_posts', lazy='dynamic'))
    dislikers = db.relationship('User', secondary=post_dislikes,
                                lazy='select',  # CHANGED FROM 'dynamic'
                                backref=db.backref('disliked_posts', lazy='dynamic'))

    # Relationship for shared posts (reposts)
    original_post = db.relationship('Post', remote_side=[id], backref=db.backref('shares', lazy='dynamic'))

    def __repr__(self):
        return f'<Post {self.id} by User {self.user_id}>'

class Comment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    post_id = db.Column(db.Integer, db.ForeignKey('post.id'), nullable=False, index=True)
    text_content = db.Column(db.Text, nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)

    author = db.relationship('User', backref=db.backref('comments', lazy='dynamic'))
    # 'post' backref is already defined in Post.comments

    def __repr__(self):
        return f'<Comment {self.id} by User {self.user_id} on Post {self.post_id}>'

# --- Forms ---

class RegistrationForm(FlaskForm):
    """Form for user registration."""
    username = StringField('Username',
                           validators=[DataRequired(), Length(min=4, max=25)])
    email = EmailField('Email',
                       validators=[DataRequired(), Email()])
    password = PasswordField('Password',
                             validators=[DataRequired(), Length(min=6)])
    confirm_password = PasswordField('Confirm Password',
                                     validators=[DataRequired(), EqualTo('password')])
    submit = SubmitField('Register')

    # Custom validators to check if username/email already exists
    def validate_username(self, username):
        user = User.query.filter_by(username=username.data).first()
        if user:
            raise ValidationError('That username is already taken. Please choose another.')

    def validate_email(self, email):
        user = User.query.filter_by(email=email.data).first()
        if user:
            raise ValidationError('That email is already registered. Please use another.')

class LoginForm(FlaskForm):
    """Form for user login."""
    username = StringField('Username', validators=[DataRequired()])
    password = PasswordField('Password', validators=[DataRequired()])
    remember = BooleanField('Remember Me') # For persistent sessions
    submit = SubmitField('Login')

class UploadFileForm(FlaskForm):
    """Form for uploading files."""
    file = FileField('File', validators=[
        FileRequired(message='No file selected!'),
    ])
    submit = SubmitField('Upload')

class CreatePostForm(FlaskForm):
    text_content = TextAreaField('What\'s on your mind?', validators=[Length(max=5000)]) # Optional text
    photo = FileField('Upload Photo', validators=[
        Optional(),
        FileAllowed(['jpg', 'png', 'jpeg', 'gif', 'webp'], 'Images only!')
    ])
    video = FileField('Upload Video', validators=[
        Optional(),
        FileAllowed(['mp4', 'webm', 'ogg', 'mov'], 'Videos only!') # Adjust allowed video types
    ])
    submit = SubmitField('Post')

class CommentForm(FlaskForm):
    text_content = TextAreaField('Write a comment...', validators=[DataRequired(), Length(min=1, max=1000)])
    submit = SubmitField('Comment')

class AdminSettingsForm(FlaskForm):
    """Form for administrator settings."""
    allow_registration = BooleanField('Allow New User Registrations')
    default_storage_limit_mb = IntegerField(
        'Default Storage Limit per User (MB)',
        validators=[
            DataRequired(),
            NumberRange(min=0, message='Storage limit cannot be negative. Enter 0 for unlimited.')
            # Add a reasonable upper bound? e.g., max=1024*10=10240 (10 GB)
        ]
    )
    # --- ADD MAX UPLOAD SIZE FIELD ---
    max_upload_size_mb = IntegerField(
        'Max Single File Upload Size (MB)',
        validators=[
            DataRequired(message="Please specify a maximum upload size."),
            NumberRange(min=1, message='Maximum upload size must be at least 1 MB.')
            # Add a reasonable upper bound? e.g., max=1024*2 (2 GB) depending on server capacity
            # NumberRange(min=1, max=2048, message='Maximum upload size must be between 1 and 2048 MB.')
        ],
        description="Maximum size allowed for a single file upload."
    )
    ollama_api_url = URLField(
        'Ollama API Base URL',
        validators=[Optional(), URL(message='Please enter a valid URL.')],
        description="URL for your Ollama instance (e.g., http://localhost:11434). Leave blank to disable Ollama integration."
    )
    ollama_model = StringField(
        'Ollama Model Name',
        validators=[Optional(), Length(min=1, max=100)],
        description="The name of the Ollama model to use (e.g., 'llama3', 'mistral'). Required if URL is set."
    )
    # --- END ADD ---

    # --- NEW SMTP Fields ---
    mail_server = StringField('SMTP Server Host',
                              validators=[Optional(), Length(max=100)])
    mail_port = IntegerField('SMTP Port',
                             validators=[Optional(), NumberRange(min=1, max=65535)])
    mail_use_tls = BooleanField('Use TLS')
    mail_use_ssl = BooleanField('Use SSL')
    mail_username = StringField('SMTP Username/Email',
                                validators=[Optional(), Length(max=100)])
    # For mail_password, use Optional() so it's not required on every form submission
    # The logic in the route will only update the password if a new value is provided.
    mail_password = PasswordField('SMTP Password',
                                  validators=[Optional(), Length(min=1, max=100)]) # Min length if provided
    mail_default_sender_name = StringField('Default Sender Name',
                                           validators=[Optional(), Length(max=100)],
                                           description='The "From" name displayed in emails.')
    mail_default_sender_email = EmailField('Default Sender Email',
                                           validators=[Optional(), Email(), Length(max=120)],
                                           description='The "From" email address.')
    # --- END NEW SMTP Fields ---

    submit = SubmitField('Save Settings')

class ForgotPasswordForm(FlaskForm):
    email = EmailField('Email', validators=[DataRequired(), Email()])
    submit = SubmitField('Request Password Reset')

class ResetPasswordForm(FlaskForm):
    password = PasswordField('New Password', validators=[DataRequired(), Length(min=6)])
    confirm_password = PasswordField('Confirm New Password', validators=[DataRequired(), EqualTo('password')])
    submit = SubmitField('Reset Password')

# --- Routes ---
@app.route('/')
def index():
    """Homepage: Redirects to files if logged in, else to login."""
    if current_user.is_authenticated:
        return redirect(url_for('list_files'))
    return redirect(url_for('login'))

@app.route('/register', methods=['GET', 'POST'])
def register():
    # --- Check if registration is allowed ---
    registration_allowed = Setting.get('allow_registration', 'true') == 'true'
    if not registration_allowed:
        flash('New user registration is currently disabled.', 'info')
        return redirect(url_for('login'))
    # --- End check ---

    if current_user.is_authenticated:
        return redirect(url_for('list_files'))

    form = RegistrationForm()
    if form.validate_on_submit():
        is_first_user = User.query.count() == 0

        # --- FETCH DEFAULT STORAGE LIMIT ---
        default_limit_mb = 1024 # Fallback value
        try:
            default_limit_str = Setting.get('default_storage_limit_mb', '1024')
            default_limit_mb = int(default_limit_str)
            if default_limit_mb < 0: # Ensure it's not negative
                default_limit_mb = 0 # Treat negative as 0 (unlimited)
            app.logger.info(f"Using default storage limit for new user: {default_limit_mb} MB")
        except (ValueError, TypeError):
            app.logger.error(f"Invalid default_storage_limit_mb setting '{default_limit_str}'. Falling back to {default_limit_mb} MB.")
        # --- END FETCH ---

        new_user = User(
            username=form.username.data,
            email=form.email.data,
            is_admin=is_first_user,
            # --- ASSIGN STORAGE LIMIT ---
            # Assign the fetched integer value. 0 means unlimited in get_user_storage_info logic.
            # NULL could also mean use default, but explicit 0 is clearer here if limit is truly unlimited.
            storage_limit_mb = default_limit_mb if default_limit_mb > 0 else None # Store None if 0 MB means use default/unlimited logic elsewhere
            # OR, if you want 0MB to mean literally 0MB allowed (very restrictive):
            # storage_limit_mb = default_limit_mb
            # --- END ASSIGN ---
        )
        new_user.set_password(form.password.data)

        try:
            db.session.add(new_user)
            db.session.commit()
            # Create user's upload directory immediately after successful registration
            try:
                user_upload_path = get_user_upload_path(new_user.id)
                os.makedirs(user_upload_path, exist_ok=True)
                app.logger.info(f"Created upload directory for new user {new_user.id}: {user_upload_path}")
            except OSError as e:
                 app.logger.error(f"Failed to create upload directory for user {new_user.id} during registration: {e}", exc_info=True)
                 # Decide if this should prevent login or just log an error. Currently just logs.

            flash(f'Account created for {form.username.data}! You can now log in.', 'success')
            if is_first_user:
                 flash('You have been registered as the first user (Admin).', 'info')
            return redirect(url_for('login'))
        except IntegrityError as e: # Catch potential duplicate username/email race conditions
             db.session.rollback()
             app.logger.warning(f"Registration failed for {form.username.data} due to integrity error (likely duplicate): {e}")
             # Check which field caused the error (more complex, might need specific DB error parsing)
             if User.query.filter_by(username=form.username.data).first():
                 form.username.errors.append("This username was just taken. Please choose another.")
             elif User.query.filter_by(email=form.email.data).first():
                 form.email.errors.append("This email was just registered. Please use another.")
             else: # Generic fallback
                 flash(f'An error occurred during registration. Please check your details and try again.', 'danger')
        except Exception as e:
            db.session.rollback()
            app.logger.error(f"Error during registration for {form.username.data}: {e}", exc_info=True)
            flash(f'An error occurred during registration. Please try again later.', 'danger')

    # Render template only if registration is allowed and not already logged in
    return render_template('register.html', title='Register', form=form)

@app.route('/login', methods=['GET', 'POST'])
def login():
    """Handles user login."""
    if current_user.is_authenticated:
        return redirect(url_for('list_files'))

    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(username=form.username.data).first()
        if user and user.check_password(form.password.data):
            login_user(user, remember=form.remember.data)
            flash('Login successful!', 'success')
            # Redirect to the page the user was trying to access, or list_files
            next_page = request.args.get('next')
            return redirect(next_page or url_for('list_files')) # Simplified redirect
        else:
            flash('Login Unsuccessful. Please check username and password.', 'danger')

    return render_template('login.html', title='Login', form=form)

@app.route('/logout')
@login_required # User must be logged in to log out
def logout():
    """Logs the current user out."""
    logout_user()
    flash('You have been logged out.', 'info')
    return redirect(url_for('login'))

@app.route('/files/folder/archive/<int:folder_id>', methods=['POST'])
@login_required
def archive_folder(folder_id):
    folder = Folder.query.get_or_404(folder_id)
    if folder.owner != current_user:
        abort(403)

    # Define archive name and path (save in the parent folder's DB location)
    archive_basename = secure_filename(f"{folder.name}.zip")
    user_upload_path = get_user_upload_path(current_user.id)
    # Final location where the zip file itself will be stored physically
    archive_final_physical_path = os.path.join(user_upload_path, archive_basename) # Store flat in user's dir for now

    # Avoid overwriting existing file/folder with the same name as the archive
    if (File.query.filter_by(user_id=current_user.id, parent_folder_id=folder.parent_folder_id, original_filename=archive_basename).first() or
        Folder.query.filter_by(user_id=current_user.id, parent_folder_id=folder.parent_folder_id, name=archive_basename).first()):
        return jsonify({"status": "error", "message": f"An item named '{archive_basename}' already exists where the archive would be saved."}), 409 # Conflict


    try:
        app.logger.info(f"Starting archive creation for folder '{folder.name}' (ID: {folder_id}) -> {archive_basename}")
        with zipfile.ZipFile(archive_final_physical_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            # Start the recursive process. The base path inside the zip will be the folder's name.
            add_folder_to_zip(zipf, folder.id, current_user.id, folder.name, user_upload_path)

        # Check archive size after creation
        filesize = os.path.getsize(archive_final_physical_path)

        # Check storage limit before adding DB record
        storage_info = get_user_storage_info(current_user)
        # Calculate usage *after* archive creation but *before* adding its record
        current_usage_bytes = db.session.query(db.func.sum(File.filesize)).filter(File.user_id == current_user.id).scalar() or 0
        available_bytes = storage_info['limit_bytes'] - current_usage_bytes # Space *before* adding archive record

        if filesize > available_bytes:
             os.remove(archive_final_physical_path) # Clean up created archive
             app.logger.warning(f"Storage limit exceeded after creating archive for folder {folder_id}. Archive deleted.")
             # Format for user message
             req_mb = round(filesize / (1024*1024), 1)
             avail_mb = round(available_bytes / (1024*1024), 1) if available_bytes != float('inf') else float('inf')
             used_mb = round(current_usage_bytes / (1024*1024), 1)
             limit_mb = storage_info['limit_mb'] if storage_info['limit_mb'] is not None else "Unlimited"
             return jsonify({
                  "status": "error",
                  "message": f"Insufficient storage. Archive requires ~{req_mb} MB, but only {avail_mb} MB is free (Used: {used_mb} MB, Limit: {limit_mb} MB)."
                  }), 413 # Payload Too Large

        # Add DB record for the new archive file
        new_file = File(
            original_filename=archive_basename,
            stored_filename=archive_basename, # Store physically with the same name in user's root
            filesize=filesize,
            mime_type='application/zip',
            owner=current_user,
            parent_folder_id=folder.parent_folder_id # Archive appears alongside the original folder
        )
        db.session.add(new_file)
        db.session.commit()
        app.logger.info(f"Folder '{folder.name}' (ID: {folder_id}) successfully archived to '{archive_basename}' by user {current_user.id}")

        return jsonify({"status": "success", "message": f"Folder '{folder.name}' archived as '{archive_basename}'."})

    except Exception as e:
        db.session.rollback()
        # Clean up potentially incomplete archive
        if os.path.exists(archive_final_physical_path):
            try: os.remove(archive_final_physical_path)
            except OSError: pass
        app.logger.error(f"Error archiving folder {folder_id} for user {current_user.id}: {e}", exc_info=True)
        return jsonify({"status": "error", "message": "Failed to archive folder."}), 500


@app.route('/files/extract/<int:file_id>', methods=['POST'])
@login_required
def extract_file(file_id):
    file_record = File.query.get_or_404(file_id)
    if file_record.owner != current_user:
        abort(403)

    # --- Get File Path ---
    user_upload_path = get_user_upload_path(current_user.id)
    archive_path = os.path.join(user_upload_path, file_record.stored_filename)
    file_ext = os.path.splitext(file_record.original_filename)[1].lower() # Get extension

    if not os.path.isfile(archive_path):
        app.logger.error(f"Archive file not found on disk: {archive_path}")
        return jsonify({"status": "error", "message": "Archive file not found."}), 404

    # --- Check if Extraction is Supported AT ALL (basic check) ---
    # (You might have slightly different lists here vs. the size check function)
    supported_extract_extensions = {'.zip'} # Only supporting zip pre-check for now
    # Add '.7z', '.rar' etc. if you implement size check & extraction for them

    if file_ext not in supported_extract_extensions:
         # Maybe allow extraction even if size check not possible? Or deny?
         # For now, let's deny if size check not possible for consistency.
         app.logger.warning(f"Extraction attempt for unsupported/uncheckable type: {file_ext}")
         return jsonify({"status": "error", "message": f"Extraction currently not supported for {file_ext} files or size check failed."}), 400


    # === *** NEW: Pre-Extraction Storage Check *** ===
    try:
        required_space = get_archive_uncompressed_size(archive_path)
        app.logger.info(f"Archive {file_id} requires approx {required_space / (1024*1024):.2f} MB uncompressed.")

        if required_space > 0: # Only check if we got a valid size
            storage_info = get_user_storage_info(current_user)
            available_space = storage_info['limit_bytes'] - storage_info['usage_bytes']

            app.logger.info(f"User {current_user.id} has {available_space / (1024*1024):.2f} MB available.")

            if required_space > available_space:
                app.logger.warning(f"Insufficient storage for user {current_user.id} to extract archive {file_id}. Required: {required_space}, Available: {available_space}")
                # Format for user message
                req_mb = round(required_space / (1024*1024), 1)
                avail_mb = round(available_space / (1024*1024), 1) if available_space != float('inf') else float('inf')
                used_mb = round(storage_info['usage_bytes'] / (1024*1024), 1)
                limit_mb = storage_info['limit_mb'] if storage_info['limit_mb'] is not None else "Unlimited"

                return jsonify({
                    "status": "error",
                    "message": f"Insufficient storage. Extraction requires ~{req_mb} MB, but only {avail_mb} MB is free (Used: {used_mb} MB, Limit: {limit_mb} MB)."
                }), 413 # 413 Payload Too Large might be appropriate status code

    except (ValueError, NotImplementedError) as e:
         # Handle errors from get_archive_uncompressed_size (e.g., corrupt archive, unsupported type)
         app.logger.error(f"Failed storage pre-check for archive {file_id}: {e}", exc_info=True)
         return jsonify({"status": "error", "message": f"Storage check failed: {e}"}), 400
    # === *** END of Pre-Extraction Storage Check *** ===


    # --- Proceed with extraction if checks passed ---
    temp_extract_dir = os.path.join(user_upload_path, f"temp_extract_{uuid.uuid4()}")

    try:
        os.makedirs(temp_extract_dir, exist_ok=True)
        app.logger.info(f"Extracting archive {file_id} to temporary dir: {temp_extract_dir}")

        # Extract using shutil (currently assumes zip only due to pre-check)
        shutil.unpack_archive(archive_path, temp_extract_dir)

        # --- Register extracted items ---
        app.logger.info(f"Starting registration scan for {temp_extract_dir}")
        target_parent_folder_id = file_record.parent_folder_id
        # Call the registration function (ensure it handles potential errors)
        register_extracted_items(temp_extract_dir, current_user.id, target_parent_folder_id, user_upload_path)

        # --- If registration successful, commit all DB changes ---
        db.session.commit()
        app.logger.info(f"Successfully registered items from archive {file_id}")

        # --- Clean up the temporary extraction directory ---
        try:
            shutil.rmtree(temp_extract_dir)
            app.logger.info(f"Cleaned up temporary extraction directory: {temp_extract_dir}")
        except OSError as e:
             app.logger.error(f"Error cleaning up temp directory {temp_extract_dir}: {e}", exc_info=True)

        return jsonify({"status": "success", "message": f"Archive '{file_record.original_filename}' extracted and registered."})

    except ValueError as e: # Catch specific errors like storage limit from helper during registration (if re-enabled)
         db.session.rollback()
         app.logger.error(f"Extraction registration failed for archive {file_id}: {e}", exc_info=True)
         if os.path.exists(temp_extract_dir): shutil.rmtree(temp_extract_dir) # Cleanup temp
         return jsonify({"status": "error", "message": str(e)}), 400
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Error during extraction or registration for archive {file_id}: {e}", exc_info=True)
        if os.path.exists(temp_extract_dir):
            try: shutil.rmtree(temp_extract_dir)
            except OSError as clean_e: app.logger.error(f"Error cleaning up temp directory {temp_extract_dir} after failure: {clean_e}", exc_info=True)
        return jsonify({"status": "error", "message": "Failed to extract or register archive contents."}), 500


# --- Admin Routes ---
@app.route('/admin/settings', methods=['GET', 'POST'])
@login_required
def admin_settings():
    if not current_user.is_admin:
        flash('You do not have permission to access this page.', 'danger')
        return redirect(url_for('list_files')) # Or your main page

    form = AdminSettingsForm()
    # Define default values here for clarity, especially for GET requests
    # These match the DEFAULT_SETTINGS dictionary used in create_db
    # (It would be good to have DEFAULT_SETTINGS accessible here too, e.g., from a config file or app.config)
    default_mail_settings = {
        'MAIL_SERVER': 'smtp.example.com',
        'MAIL_PORT': 587, # Integer
        'MAIL_USE_TLS': True, # Boolean
        'MAIL_USE_SSL': False, # Boolean
        'MAIL_USERNAME': '',
        'MAIL_PASSWORD': '', # Password is not pre-filled for security
        'MAIL_DEFAULT_SENDER_NAME': 'PyCloud',
        'MAIL_DEFAULT_SENDER_EMAIL': 'noreply@example.com'
    }


    if form.validate_on_submit():
        # --- POST Request: Save settings ---
        try:
            # General Settings
            Setting.set('allow_registration', str(form.allow_registration.data).lower())
            Setting.set('default_storage_limit_mb', str(form.default_storage_limit_mb.data))
            Setting.set('max_upload_size_mb', str(form.max_upload_size_mb.data))

            # Ollama Settings
            Setting.set('ollama_api_url', form.ollama_api_url.data or '')
            Setting.set('ollama_model', form.ollama_model.data or '')

            # --- SMTP Settings ---
            Setting.set('MAIL_SERVER', form.mail_server.data or '')
            Setting.set('MAIL_PORT', str(form.mail_port.data) if form.mail_port.data is not None else str(default_mail_settings['MAIL_PORT']))
            Setting.set('MAIL_USE_TLS', str(form.mail_use_tls.data).lower())
            Setting.set('MAIL_USE_SSL', str(form.mail_use_ssl.data).lower())
            Setting.set('MAIL_USERNAME', form.mail_username.data or '')

            # Only update password if a new one is provided
            if form.mail_password.data:
                Setting.set('MAIL_PASSWORD', form.mail_password.data)
            # Else, the existing password in the DB (or empty if never set) remains unchanged

            Setting.set('MAIL_DEFAULT_SENDER_NAME', form.mail_default_sender_name.data or '')
            Setting.set('MAIL_DEFAULT_SENDER_EMAIL', form.mail_default_sender_email.data or '')

            db.session.commit()
            flash('Settings updated successfully!', 'success')
            app.logger.info(f"Admin settings saved by {current_user.username}.")

            # Reload mail configuration in the app context if settings changed
            # This is important if your app.config mail settings are loaded at startup
            # and need to be refreshed without restarting the whole app.
            with app.app_context():
                app.config['MAIL_SERVER'] = Setting.get('MAIL_SERVER', default_mail_settings['MAIL_SERVER'])
                app.config['MAIL_PORT'] = int(Setting.get('MAIL_PORT', default_mail_settings['MAIL_PORT']))
                app.config['MAIL_USE_TLS'] = Setting.get('MAIL_USE_TLS', 'true').lower() == 'true'
                app.config['MAIL_USE_SSL'] = Setting.get('MAIL_USE_SSL', 'false').lower() == 'true'
                app.config['MAIL_USERNAME'] = Setting.get('MAIL_USERNAME', default_mail_settings['MAIL_USERNAME'])
                # MAIL_PASSWORD is used by Flask-Mail directly from app.config,
                # but we don't re-set it here from DB to avoid logging it if it's sensitive.
                # Flask-Mail will pick up the new password if it was updated in the DB and
                # the mail object is re-initialized or if it reads from app.config dynamically.
                # For simplicity, assume Flask-Mail re-reads or you handle its re-init elsewhere if needed.

                sender_name_db = Setting.get('MAIL_DEFAULT_SENDER_NAME', default_mail_settings['MAIL_DEFAULT_SENDER_NAME'])
                sender_email_db = Setting.get('MAIL_DEFAULT_SENDER_EMAIL', default_mail_settings['MAIL_DEFAULT_SENDER_EMAIL'])
                if sender_name_db:
                     app.config['MAIL_DEFAULT_SENDER'] = (sender_name_db, sender_email_db)
                else:
                     app.config['MAIL_DEFAULT_SENDER'] = sender_email_db
                app.logger.info("App mail config reloaded from DB settings.")


            return redirect(url_for('admin_settings'))

        except Exception as e:
            db.session.rollback()
            app.logger.error(f"Error updating settings by {current_user.username}: {e}", exc_info=True)
            flash('Failed to update settings.', 'danger')

    elif request.method == 'GET':
        # --- GET Request: Populate form with current settings ---
        try:
            # General Settings
            form.allow_registration.data = (Setting.get('allow_registration', 'true') == 'true')
            form.default_storage_limit_mb.data = int(Setting.get('default_storage_limit_mb', '1024'))
            form.max_upload_size_mb.data = int(Setting.get('max_upload_size_mb', str(DEFAULT_MAX_UPLOAD_MB_FALLBACK))) # Ensure DEFAULT_MAX_UPLOAD_MB_FALLBACK is defined

            # Ollama Settings
            form.ollama_api_url.data = Setting.get('ollama_api_url', '')
            form.ollama_model.data = Setting.get('ollama_model', 'llama3')

            # --- SMTP Settings ---
            form.mail_server.data = Setting.get('MAIL_SERVER', default_mail_settings['MAIL_SERVER'])
            form.mail_port.data = int(Setting.get('MAIL_PORT', default_mail_settings['MAIL_PORT']))
            form.mail_use_tls.data = (Setting.get('MAIL_USE_TLS', 'true').lower() == 'true')
            form.mail_use_ssl.data = (Setting.get('MAIL_USE_SSL', 'false').lower() == 'true')
            form.mail_username.data = Setting.get('MAIL_USERNAME', default_mail_settings['MAIL_USERNAME'])
            # Do NOT pre-fill form.mail_password.data for security reasons.
            # It should always be blank on GET, and only if the admin types something, it gets updated.
            form.mail_default_sender_name.data = Setting.get('MAIL_DEFAULT_SENDER_NAME', default_mail_settings['MAIL_DEFAULT_SENDER_NAME'])
            form.mail_default_sender_email.data = Setting.get('MAIL_DEFAULT_SENDER_EMAIL', default_mail_settings['MAIL_DEFAULT_SENDER_EMAIL'])

        except ValueError as ve:
            app.logger.error(f"ValueError populating admin settings form: {ve}. Check if DB settings are valid integers/booleans where expected.", exc_info=True)
            flash("Error loading some settings. Values might be corrupted in the database.", "warning")
        except Exception as e:
            app.logger.error(f"Unexpected error populating admin_settings form: {e}", exc_info=True)
            flash("An unexpected error occurred while loading settings.", "danger")


    return render_template('admin_settings.html', title='Admin Settings', form=form)

@app.route('/admin/users')
@login_required
def admin_list_users():
    """Lists all users for administrators."""
    if not current_user.is_admin:
        flash('You do not have permission to access this page.', 'danger')
        return redirect(url_for('list_files'))

    try:
        users = User.query.order_by(User.username).all()
        users_with_storage = []
        for user in users:
            storage_info = get_user_storage_info(user)
            users_with_storage.append({'user': user, 'storage': storage_info})

    except Exception as e:
        app.logger.error(f"Error fetching users for admin list: {e}", exc_info=True)
        flash("Error retrieving user list.", "danger")
        users_with_storage = [] # Ensure it's an empty list on error

    return render_template('admin_users.html',
                           title='Manage Users',
                           users_with_storage=users_with_storage)


@app.route('/admin/user/edit/<int:user_id>', methods=['GET', 'POST'])
@login_required
def admin_edit_user(user_id):
    """Handles editing a specific user's details."""
    if not current_user.is_admin:
        flash('You do not have permission to perform this action.', 'danger')
        return redirect(url_for('admin_list_users'))

    user_to_edit = User.query.get_or_404(user_id)
    # Pass original username/email to form for validation checks
    form = EditUserForm(original_username=user_to_edit.username,
                        original_email=user_to_edit.email)

    if form.validate_on_submit():
        # --- Update User Fields ---
        user_to_edit.username = form.username.data
        user_to_edit.email = form.email.data
        user_to_edit.is_admin = form.is_admin.data

        # Handle storage limit: None from form means NULL in DB (use default)
        # 0 from form means 0 in DB (explicitly unlimited or 0 based on interpretation elsewhere)
        limit_value = form.storage_limit_mb.data
        if limit_value is None:
            user_to_edit.storage_limit_mb = None # Use default
            limit_log_msg = "default"
        # Optional: Treat 0 as "use default" as well, if preferred
        # elif limit_value == 0:
        #     user_to_edit.storage_limit_mb = None
        #     limit_log_msg = "default (set via 0)"
        else:
            user_to_edit.storage_limit_mb = limit_value # Set specific limit (could be 0)
            limit_log_msg = f"{limit_value} MB"

        try:
            db.session.commit()
            flash(f'User "{user_to_edit.username}" updated successfully.', 'success')
            app.logger.info(f"Admin {current_user.username} updated user {user_to_edit.username} (ID: {user_id}). Storage limit set to: {limit_log_msg}")
            return redirect(url_for('admin_list_users'))
        except IntegrityError as e: # Catch duplicate username/email if validation somehow missed it
             db.session.rollback()
             app.logger.warning(f"Update failed for user {user_id} due to integrity error: {e}")
             # Add errors back to the specific fields if possible
             if 'users.username' in str(e):
                 form.username.errors.append("This username is already taken.")
             elif 'users.email' in str(e):
                 form.email.errors.append("This email is already registered.")
             else:
                flash('Database error: Could not update user due to conflicting data.', 'danger')
        except Exception as e:
            db.session.rollback()
            app.logger.error(f"Error updating user {user_id} by admin {current_user.id}: {e}", exc_info=True)
            flash('An unexpected error occurred while updating the user.', 'danger')
        # Re-render form with errors if commit failed

    elif request.method == 'GET':
        # --- Populate Form for GET request ---
        form.username.data = user_to_edit.username
        form.email.data = user_to_edit.email
        form.is_admin.data = user_to_edit.is_admin
        # If DB value is None, form field remains empty (due to Optional())
        # If DB value is 0 or more, set form field data
        form.storage_limit_mb.data = user_to_edit.storage_limit_mb

    return render_template('admin_edit_user.html',
                           title=f'Edit User: {user_to_edit.username}',
                           form=form,
                           user_id=user_id) # Pass user_id for form action URL

# --- File Routes ---

def is_file_editable(filename, mime_type):
    """Checks if a file is likely editable based on extension or MIME type."""
    # Prioritize extension check
    if '.' in filename:
        ext = filename.rsplit('.', 1)[1].lower()
    else:
        ext = '' # Handle files with no extension

    if ext in app.config.get('EDITABLE_EXTENSIONS', {}):
        return True

    # Fallback: Check MIME type (optional, can be less reliable)
    # if mime_type:
    #     for editable_prefix in app.config.get('EDITABLE_MIMETYPES', {'text/'}):
    #         if mime_type.startswith(editable_prefix):
    #             return True

    return False

def get_user_upload_path(user_id):
    """Helper function to get the upload path for a specific user."""
    return os.path.join(app.config['UPLOAD_FOLDER'], str(user_id))

# --- Helper Function for Storage Info ---
def get_user_storage_info(user):
    """Calculates user's storage usage and limit in bytes."""
    limit_type = 'user' # Assume user-specific first
    user_limit_mb = user.storage_limit_mb # May be None

    if user_limit_mb is None:
        limit_type = 'default' # It's the default limit
        try:
            default_limit_str = Setting.get('default_storage_limit_mb', '1024')
            default_limit_mb = int(default_limit_str)
        except (ValueError, TypeError):
            app.logger.error(f"Invalid default_storage_limit_mb setting value: {default_limit_str}. Using fallback 1024 MB for user {user.id}.")
            default_limit_mb = 1024 # Fallback default
        limit_mb = default_limit_mb
    else:
        limit_mb = user_limit_mb

    # Convert MB to bytes (0 or negative means unlimited)
    limit_bytes = limit_mb * 1024 * 1024 if limit_mb > 0 else float('inf')

    current_usage_bytes = db.session.query(db.func.sum(File.filesize)).filter(File.user_id == user.id).scalar() or 0

    return {
        'usage_bytes': current_usage_bytes,
        'limit_bytes': limit_bytes,
        'limit_mb': limit_mb if limit_mb > 0 else None, # Return None for unlimited MB
        'limit_type': limit_type # ADDED: 'user' or 'default'
    }

# --- Helper Function for Password Reset ---
def get_reset_token(self, expires_sec=1800): # 1800 seconds = 30 minutes
    s = URLSafeTimedSerializer(current_app.config['SECRET_KEY'])
    return s.dumps({'user_id': self.id})

@staticmethod
def verify_reset_token(token):
    s = URLSafeTimedSerializer(current_app.config['SECRET_KEY'])
    try:
        data = s.loads(token)
        user_id = data.get('user_id')
    except Exception: # Catches BadSignature, SignatureExpired, etc.
        return None
    return User.query.get(user_id)

@app.route('/files/edit/<int:file_id>', methods=['GET', 'POST'])
@login_required
def edit_file(file_id):
    file_record = File.query.get_or_404(file_id)
    if file_record.owner != current_user:
        abort(403) # Forbidden

    # Check if the file type is designated as editable
    if not is_file_editable(file_record.original_filename, file_record.mime_type):
        flash(f"File '{file_record.original_filename}' is not editable.", 'warning')
        return redirect(url_for('list_files', folder_id=file_record.parent_folder_id))

    form = EditFileForm()
    user_upload_path = get_user_upload_path(current_user.id)
    file_path = os.path.join(user_upload_path, file_record.stored_filename)

    if not os.path.exists(file_path):
         app.logger.error(f"File not found on disk for editing: {file_path} (DB ID: {file_id})")
         flash("Error: File not found in storage.", "danger")
         return redirect(url_for('list_files', folder_id=file_record.parent_folder_id))

    if form.validate_on_submit(): # POST request
        new_content = form.content.data
        # Important: Ensure consistent line endings (e.g., replace \r\n with \n)
        # new_content = new_content.replace('\r\n', '\n') # Uncomment if needed

        try:
            # Get original size before writing
            original_size = file_record.filesize

            # Write content back using UTF-8 encoding, handle errors
            # codecs.open provides better encoding handling than standard open
            with codecs.open(file_path, 'w', encoding='utf-8', errors='replace') as f:
                f.write(new_content)

            # Get new size after writing
            new_size = os.path.getsize(file_path)
            size_difference = new_size - original_size

            # Check storage limit *if file grew*
            if size_difference > 0:
                storage_info = get_user_storage_info(current_user)
                available_bytes = storage_info['limit_bytes'] - storage_info['usage_bytes']
                if size_difference > available_bytes:
                    # Rollback: Re-read original content (or better, save it before write)
                    # This is a simplified rollback, might lose original if read fails
                    try:
                         with codecs.open(file_path, 'r', encoding='utf-8', errors='replace') as f_orig:
                             original_content_temp = f_orig.read()
                         # Now try to write original content back
                         with codecs.open(file_path, 'w', encoding='utf-8', errors='replace') as f_revert:
                              f_revert.write(original_content_temp)
                              # Reset size just in case
                              os.truncate(file_path, original_size)

                    except Exception as revert_err:
                         app.logger.error(f"CRITICAL: Failed to revert file {file_path} after storage limit error during edit: {revert_err}")
                         # File might be in inconsistent state now

                    limit_mb_display = storage_info['limit_mb'] if storage_info['limit_mb'] is not None else "Unlimited"
                    usage_mb = round(storage_info['usage_bytes'] / (1024*1024), 1)
                    required_mb = round(size_difference / (1024*1024), 1)
                    flash(f'Save failed: Storage limit exceeded. Requires additional {required_mb} MB. Limit: {limit_mb_display} MB, Used: {usage_mb} MB.', 'danger')
                    # Re-render form with old content (from DB record initially read)
                    try:
                       with codecs.open(file_path, 'r', encoding='utf-8', errors='replace') as f_read:
                           form.content.data = f_read.read()
                    except Exception as read_err:
                         app.logger.error(f"Error re-reading file {file_path} for form after storage error: {read_err}")
                         form.content.data = "[Error reading file content]"

                    return render_template('edit.html', form=form, file_id=file_id,
                                       original_filename=file_record.original_filename,
                                       stored_filename=file_record.stored_filename,
                                       parent_folder_id=file_record.parent_folder_id)


            # Update database if storage check passed (or file didn't grow)
            file_record.filesize = new_size
            # Optionally update a modified timestamp if you add one to the File model
            # file_record.last_modified = datetime.utcnow()
            db.session.commit()

            flash(f"File '{file_record.original_filename}' saved successfully.", 'success')
            app.logger.info(f"File {file_id} edited and saved by user {current_user.id}. New size: {new_size} bytes.")
            return redirect(url_for('list_files', folder_id=file_record.parent_folder_id))

        except OSError as e:
            db.session.rollback()
            app.logger.error(f"OSError saving edited file {file_path}: {e}", exc_info=True)
            flash(f"Error saving file: Could not write to storage. ({e})", 'danger')
        except Exception as e:
            db.session.rollback()
            app.logger.error(f"Error saving edited file {file_path}: {e}", exc_info=True)
            flash("An unexpected error occurred while saving the file.", 'danger')

        # If save failed, re-render form with submitted (unsaved) content
        # No need to re-read file here, form already has the data
        return render_template('edit.html', form=form, file_id=file_id,
                               original_filename=file_record.original_filename,
                               stored_filename=file_record.stored_filename,
                               parent_folder_id=file_record.parent_folder_id)

    elif request.method == 'GET': # GET request
        try:
            # Read content using UTF-8, replace errors for display
            with codecs.open(file_path, 'r', encoding='utf-8', errors='replace') as f:
                current_content = f.read()
            form.content.data = current_content
        except OSError as e:
            app.logger.error(f"OSError reading file {file_path} for edit: {e}", exc_info=True)
            flash(f"Error reading file content. ({e})", "danger")
            form.content.data = "[Error reading file content]" # Show error in textarea
        except Exception as e:
            app.logger.error(f"Error reading file {file_path} for edit: {e}", exc_info=True)
            flash("An unexpected error occurred while reading the file.", "danger")
            form.content.data = "[Error reading file content]"

    # Render the template for GET requests or if POST validation failed (though unlikely here)
    return render_template('edit.html', form=form, file_id=file_id,
                           original_filename=file_record.original_filename,
                           stored_filename=file_record.stored_filename,
                           parent_folder_id=file_record.parent_folder_id)

# Route for root file listing
@app.route('/files/', defaults={'folder_id': None}, methods=['GET'])
@app.route('/files/folder/<int:folder_id>', methods=['GET'])
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

    # *** VERIFY THIS LOOP IS EXACTLY AS SHOWN BELOW ***
    # Add the is_editable flag to each file object AFTER fetching the list
    for file_record in files:
        # Add a log statement here for debugging
        is_edit = is_file_editable(file_record.original_filename, file_record.mime_type)
    #    app.logger.info(f"Checking editability for {file_record.original_filename}: {is_edit}") # DEBUG LOG
        file_record.is_editable = is_edit
    # *** END VERIFICATION ***

    # --- CORRECTED STORAGE INFO HANDLING ---
    storage_info = get_user_storage_info(current_user) # Get the full dictionary
    usage_mb = round(storage_info['usage_bytes'] / (1024 * 1024), 2)
    # Define limit_display correctly
    limit_display = f"{storage_info['limit_mb']} MB" if storage_info['limit_mb'] is not None else "Unlimited"
    # Define limit_type_indicator correctly
    limit_type_indicator = f"({storage_info['limit_type'].capitalize()})"
    # --- END CORRECTION ---

    breadcrumbs = []
    temp_folder = current_folder
    while temp_folder:
        breadcrumbs.append({'id': temp_folder.id, 'name': temp_folder.name})
        temp_folder = temp_folder.parent
    breadcrumbs.reverse()

    # *** ADD THIS: Get clipboard data from session ***
    clipboard_session_data = session.get('clipboard', None)
    # Safely serialize it for JavaScript (handle potential None)
    clipboard_json = json.dumps(clipboard_session_data) if clipboard_session_data else 'null'
    # *** END ADDITION ***

    # --- Fetch Max Upload Size Setting ---
    try:
        max_upload_mb_str = Setting.get('max_upload_size_mb', '100') # Default 100MB
        max_upload_mb = int(max_upload_mb_str)
    except (ValueError, TypeError):
        max_upload_mb = 100 # Fallback on error
        app.logger.warning(f"Invalid max_upload_size_mb setting '{max_upload_mb_str}'. Using fallback {max_upload_mb}MB for display.")
    # --- End Fetch ---

    return render_template('files.html',
                           title='My Files' + (f' - {current_folder.name}' if current_folder else ''),
                           files=files,
                           subfolders=subfolders,
                           current_folder=current_folder,
                           parent_folder=parent_folder,
                           breadcrumbs=breadcrumbs,
                           usage_mb=usage_mb,
                           limit_display=limit_display,
                           limit_type_indicator=limit_type_indicator,
                           max_upload_mb=max_upload_mb, # Pass the admin limit
                           upload_form=upload_form,
                           create_folder_form=create_folder_form,
                           # *** ADD THIS: Pass clipboard data to template ***
                           clipboard_json=clipboard_json)


@app.route('/files/upload', methods=['POST'])
@login_required
def upload_file():
    app.logger.info("--- Entering upload_file route ---") # Or print()
    app.logger.info(f"Request Headers: {request.headers}")
    app.logger.info(f"Request Form Data: {request.form}")
    app.logger.info(f"Request Files: {request.files}")
    """Handles file uploads, checking against server, admin, and user limits."""

    # Determine if the request is likely AJAX (for JSON responses)
    is_ajax = request.accept_mimetypes.accept_json and \
              not request.accept_mimetypes.accept_html

    # --- Get Target Folder ---
    parent_folder_id_str = request.form.get('parent_folder_id')
    parent_folder_id = int(parent_folder_id_str) if parent_folder_id_str else None
    redirect_url = url_for('list_files', folder_id=parent_folder_id) # URL for standard redirects

    if parent_folder_id:
        # Ensure the target folder exists and belongs to the user
        target_folder = Folder.query.filter_by(id=parent_folder_id, user_id=current_user.id).first()
        if not target_folder:
            message = 'Target folder not found or invalid.'
            if is_ajax: return jsonify({"status": "error", "message": message}), 404
            else: flash(message, 'danger'); return redirect(url_for('list_files')) # Redirect to root if target invalid

    # --- Validate File Presence ---
    if 'file' not in request.files:
         message = 'No file part in the request.'
         if is_ajax: return jsonify({"status": "error", "message": message}), 400
         else: flash(message, 'danger'); return redirect(redirect_url)

    f = request.files['file']

    if f.filename == '':
         message = 'No selected file.'
         if is_ajax: return jsonify({"status": "error", "message": message}), 400
         else: flash(message, 'danger'); return redirect(redirect_url)

    original_filename = secure_filename(f.filename)

    # --- Determine File Size ---
    uploaded_filesize = None
    try:
        # More reliable way: check stream size directly
        f.seek(0, os.SEEK_END)
        uploaded_filesize = f.tell()
        f.seek(0) # IMPORTANT: Reset stream position!
        if uploaded_filesize is None:
            raise ValueError("Could not determine file size using stream.tell().")
    except Exception as e:
        # Fallback using content_length header (less reliable)
        app.logger.warning(f"Could not determine file size using stream: {e}. Falling back to Content-Length.")
        uploaded_filesize = request.content_length

    # If size still unknown, reject
    if uploaded_filesize is None:
         app.logger.error(f"Critical: Could not determine file size for upload '{original_filename}' by user {current_user.id}.")
         message = 'Could not determine file size.'
         if is_ajax: return jsonify({"status": "error", "message": message}), 400
         else: flash(message, 'danger'); return redirect(redirect_url)


    # === CHECK 1: Against Hardcoded Server Limit (MAX_CONTENT_LENGTH) ===
    # Note: Flask usually rejects the request *before* reaching the route if this limit
    # is exceeded based on Content-Length header. This check is an extra safeguard
    # and useful if size was determined via stream.tell().
    hard_limit_bytes = current_app.config.get('MAX_CONTENT_LENGTH')
    if hard_limit_bytes and uploaded_filesize > hard_limit_bytes:
         limit_mb = hard_limit_bytes // (1024 * 1024)
         message = f'Upload failed: File size ({uploaded_filesize / (1024*1024):.1f} MB) exceeds the maximum server limit ({limit_mb} MB).'
         app.logger.warning(f"Upload rejected for user {current_user.id}: File size {uploaded_filesize} > MAX_CONTENT_LENGTH {hard_limit_bytes}")
         if is_ajax: return jsonify({"status": "error", "message": message}), 413 # Payload Too Large
         else: flash(message, 'danger'); return redirect(redirect_url)


    # === CHECK 2: Against User's Available Storage Space ===
    storage_info = get_user_storage_info(current_user)
    # Available space calculation must handle potential infinite limit
    if storage_info['limit_bytes'] == float('inf'):
        available_bytes = float('inf')
    else:
        available_bytes = storage_info['limit_bytes'] - storage_info['usage_bytes']

    if uploaded_filesize > available_bytes:
        limit_mb_display = f"{storage_info['limit_mb']} MB" if storage_info['limit_mb'] is not None else 'Unlimited'
        usage_mb = round(storage_info['usage_bytes'] / (1024*1024), 1)
        required_mb = round(uploaded_filesize / (1024*1024), 1)
        available_mb_display = f"{available_bytes / (1024*1024):.1f}" if available_bytes != float('inf') else 'unlimited' # Handle display
        message = f'Upload failed: Insufficient storage space. Requires {required_mb} MB, but only {available_mb_display} MB free (Usage: {usage_mb} MB, Limit: {limit_mb_display}).'
        app.logger.warning(f"Upload rejected for user {current_user.id}: File size {uploaded_filesize} > Available space {available_bytes}")
        if is_ajax: return jsonify({"status": "error", "message": message}), 413 # Payload Too Large
        else: flash(message, 'danger'); return redirect(redirect_url)


    # === All Checks Passed: Proceed with Saving ===
    _, ext = os.path.splitext(original_filename)
    stored_filename = str(uuid.uuid4()) + ext
    user_upload_path = get_user_upload_path(current_user.id)

    # Ensure user directory exists (important for first upload)
    try:
        os.makedirs(user_upload_path, exist_ok=True)
    except OSError as e:
        app.logger.error(f"Failed to create upload directory {user_upload_path} for user {current_user.id}: {e}", exc_info=True)
        message = 'A server error occurred (could not prepare storage).'
        if is_ajax: return jsonify({"status": "error", "message": message}), 500
        else: flash(message, 'danger'); return redirect(redirect_url)

    file_path = os.path.join(user_upload_path, stored_filename)

    # --- Save File and DB Record ---
    try:
        f.save(file_path) # Save the actual file to disk

        # Guess mime type after saving
        mime_type, _ = mimetypes.guess_type(file_path)
        mime_type = mime_type or 'application/octet-stream'

        # Create the database record
        new_file = File(original_filename=original_filename,
                        stored_filename=stored_filename,
                        filesize=uploaded_filesize, # Use the size determined earlier
                        mime_type=mime_type,
                        owner=current_user, # Or user_id=current_user.id
                        parent_folder_id=parent_folder_id)
        db.session.add(new_file)
        db.session.commit()

        message = f'File "{original_filename}" uploaded successfully!'
        app.logger.info(f"File '{original_filename}' ({uploaded_filesize} bytes) uploaded via {'AJAX' if is_ajax else 'Form'} to folder {parent_folder_id} by user {current_user.id}")

        # Return success response
        if is_ajax: return jsonify({"status": "success", "message": message})
        else: flash(message, 'success'); return redirect(redirect_url)

    except Exception as e:
        # --- Handle Save/Commit Errors ---
        db.session.rollback() # Rollback DB changes

        # Attempt to clean up the partially saved file
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
                app.logger.info(f"Cleaned up partially saved file after error: {file_path}")
            except OSError as remove_err:
                app.logger.error(f"Error removing partially saved file {file_path} after main error: {remove_err}")

        app.logger.error(f"Error saving uploaded file '{original_filename}' for user {current_user.id}: {e}", exc_info=True)
        message = 'An error occurred while saving the file. Please try again.'

        if is_ajax: return jsonify({"status": "error", "message": message}), 500
        else: flash(message, 'danger'); return redirect(redirect_url)

@app.route('/files/download/<int:file_id>')
@login_required
def download_file(file_id):
    file_record = File.query.get_or_404(file_id)

    # --- MODIFIED PERMISSION CHECK ---
    can_access = False
    # 1. Check if current user is the owner
    if file_record.owner == current_user:
        can_access = True
    else:
        # 2. Check if the file is referenced in any GroupChatMessage.
        #    If yes, any authenticated user in the group chat can access it.
        if GroupChatMessage.query.filter_by(file_id=file_record.id).first():
            can_access = True # Authenticated users can access files shared in the global group chat
    # --- END MODIFIED PERMISSION CHECK ---

    if not can_access:
        app.logger.warning(f"Access denied: User {current_user.id} attempted download of file {file_id}. Owner: {file_record.user_id}. Not shared in chat or user is not owner.")
        abort(403)  # Forbidden

    # IMPORTANT: Use the actual file owner's ID to construct the path
    user_upload_path = get_user_upload_path(file_record.user_id)

    try:
        return send_from_directory(user_upload_path,
                                   file_record.stored_filename,
                                   as_attachment=True,
                                   download_name=file_record.original_filename)
    except FileNotFoundError:
        app.logger.error(f"File not found on disk for record {file_id}: {file_record.stored_filename} in {user_upload_path}")
        abort(404)
    except Exception as e:
        app.logger.error(f"Error downloading file {file_id} for user {current_user.id}: {e}", exc_info=True)
        flash("An error occurred while trying to download the file.", "danger")
        # Redirect to a sensible page, maybe where the link originated if possible,
        # or to the main files page. For chat, redirecting to chat might be best.
        return redirect(url_for('group_chat'))

@app.route('/files/delete/<int:file_id>', methods=['POST'])
@login_required
def delete_file(file_id):
    file_record = File.query.get_or_404(file_id)

    # 1. Verify Ownership
    if file_record.owner != current_user:
        app.logger.warning(f"User {current_user.id} attempted unauthorized delete of file {file_id} owned by {file_record.user_id}")
        # Return JSON error for permission denied
        return jsonify({"status": "error", "message": "Permission denied."}), 403

    # Store info before deleting for logging/messages
    original_filename = file_record.original_filename
    stored_filename = file_record.stored_filename
    user_upload_path = get_user_upload_path(current_user.id)
    full_file_path = os.path.join(user_upload_path, stored_filename)

    try:
        # 2. Delete Physical File (keep existing logic and logging)
        if os.path.exists(full_file_path):
            os.remove(full_file_path)
            app.logger.info(f"Physical file deleted: {full_file_path}")
        else:
            app.logger.warning(f"File record {file_id} existed in DB but physical file not found at {full_file_path} during delete request by user {current_user.id}.")

        # 3. Delete Database Record
        db.session.delete(file_record)
        db.session.commit()

        # *** CHANGED: Return JSON success instead of flash/redirect ***
        app.logger.info(f"File record '{original_filename}' (ID: {file_id}, Stored: {stored_filename}) deleted by user {current_user.id}")
        return jsonify({"status": "success", "message": f"File '{original_filename}' deleted successfully."})

    except OSError as e:
        # Error deleting physical file
        db.session.rollback()
        app.logger.error(f"Error deleting physical file {full_file_path} for user {current_user.id}: {e}", exc_info=True)
        # *** CHANGED: Return JSON error ***
        return jsonify({"status": "error", "message": f"Error deleting file '{original_filename}' from storage."}), 500
    except Exception as e:
        # Error deleting DB record or other unexpected error
        db.session.rollback()
        app.logger.error(f"Error deleting file record {file_id} for user {current_user.id} from DB: {e}", exc_info=True)
        # *** CHANGED: Return JSON error ***
        return jsonify({"status": "error", "message": f"Error deleting file '{original_filename}'."}), 500

    # Removed: return redirect(url_for('list_files'))

# --- Clipboard Helper Functions (Add these) ---

def check_name_conflict(user_id, parent_folder_id, name, item_type, exclude_id=None):
    """Checks if a file or folder with the given name exists in the target folder."""
    if item_type == 'folder':
        query = Folder.query.filter_by(user_id=user_id, parent_folder_id=parent_folder_id, name=name)
        if exclude_id:
            query = query.filter(Folder.id != exclude_id)
        return query.first()
    else: # item_type == 'file'
        query = File.query.filter_by(user_id=user_id, parent_folder_id=parent_folder_id, original_filename=name)
        if exclude_id:
            query = query.filter(File.id != exclude_id)
        return query.first()

# --- REPLACE the existing copy_file_record function with this ---
def copy_file_record(file_to_copy, target_parent_folder_id, user_id):
    """
    Performs a PHYSICAL copy of a file.
    Generates a new stored_filename (UUID), copies the file on disk,
    and creates a new File DB record. Handles potential name conflicts
    for the original_filename and checks storage limits.
    Returns the new File object or raises ValueError on conflict/error.
    """
    original_filename = file_to_copy.original_filename
    # Basic conflict check for original_filename in the target folder
    if check_name_conflict(user_id, target_parent_folder_id, original_filename, 'file'):
        name_part, ext_part = os.path.splitext(original_filename)
        original_filename = f"{name_part} (copy){ext_part}"
        # Check again after modifying
        if check_name_conflict(user_id, target_parent_folder_id, original_filename, 'file'):
            raise ValueError(f"Filename conflict: '{original_filename}' already exists in the target folder.")

    # Check storage limit BEFORE attempting the physical copy
    storage_info = get_user_storage_info(User.query.get(user_id))
    available_bytes = storage_info['limit_bytes'] - storage_info['usage_bytes']
    if file_to_copy.filesize > available_bytes:
        req_mb = round(file_to_copy.filesize / (1024*1024), 1)
        avail_mb = round(available_bytes / (1024*1024), 1) if available_bytes != float('inf') else float('inf')
        raise ValueError(f"Insufficient storage space. Copy requires {req_mb} MB, but only {avail_mb} MB is free.")

    # --- Perform Physical Copy ---
    user_upload_path = get_user_upload_path(user_id)
    source_path = os.path.join(user_upload_path, file_to_copy.stored_filename)

    # Generate a NEW stored_filename (UUID) for the copy
    _, ext = os.path.splitext(file_to_copy.original_filename) # Use original ext
    new_stored_filename = str(uuid.uuid4()) + ext
    destination_path = os.path.join(user_upload_path, new_stored_filename)

    try:
        # Ensure source exists before copying
        if not os.path.exists(source_path):
            app.logger.error(f"Source file not found for copy: {source_path} (DB ID: {file_to_copy.id})")
            raise ValueError(f"Original file '{file_to_copy.original_filename}' is missing from storage.")

        # Copy the file physically (shutil.copy2 preserves metadata like timestamps)
        shutil.copy2(source_path, destination_path)
        app.logger.info(f"Physically copied {source_path} to {destination_path}")

        # Get actual size of the copied file (should be same, but good practice)
        new_filesize = os.path.getsize(destination_path)

    except OSError as e:
        app.logger.error(f"Error copying file from {source_path} to {destination_path}: {e}", exc_info=True)
        # Clean up partially copied file if it exists
        if os.path.exists(destination_path):
            try: os.remove(destination_path)
            except OSError: pass
        raise ValueError(f"Failed to copy file '{file_to_copy.original_filename}' due to storage error.")
    except Exception as e: # Catch other potential errors
        app.logger.error(f"Unexpected error during file copy ({source_path} to {destination_path}): {e}", exc_info=True)
        if os.path.exists(destination_path):
            try: os.remove(destination_path)
            except OSError: pass
        raise ValueError(f"An unexpected error occurred while copying '{file_to_copy.original_filename}'.")


    # --- Create the new DB record ---
    new_file = File(
        original_filename=original_filename, # Use potentially modified name "(copy)"
        stored_filename=new_stored_filename, # Use the NEW unique UUID filename
        filesize=new_filesize, # Use the size of the new file
        mime_type=file_to_copy.mime_type,
        user_id=user_id,
        parent_folder_id=target_parent_folder_id,
        # Reset sharing status on copy
        is_public=False,
        public_id=None,
        public_password_hash=None
    )
    db.session.add(new_file)
    # Let the calling function (paste_from_clipboard) handle commit/rollback
    return new_file
# --- END REPLACEMENT ---

def copy_folder_recursive(folder_to_copy, target_parent_folder_id, user_id):
    """
    Recursively copies a folder structure and associated file records (performing
    physical file copies via copy_file_record).
    Handles name conflicts for the top-level folder being copied.
    Returns the new top-level Folder object or raises ValueError.
    """
    app.logger.debug(f"Attempting to copy folder '{folder_to_copy.name}' (ID: {folder_to_copy.id}) into parent ID: {target_parent_folder_id}")

    # *** STEP 1: Get lists of items to copy from original folder BEFORE creating new one ***
    try:
        # Eagerly load files and subfolders to avoid issues during recursion/flush
        files_to_copy = list(folder_to_copy.files_in_folder) # Use list() to execute query now
        subfolders_to_copy = list(folder_to_copy.children) # Use list() to execute query now
        app.logger.debug(f"Found {len(files_to_copy)} files and {len(subfolders_to_copy)} subfolders in original folder {folder_to_copy.id}")
    except Exception as e:
        app.logger.error(f"DATABASE ERROR loading children/files for folder {folder_to_copy.id}: {e}", exc_info=True)
        raise ValueError(f"Could not read contents of folder '{folder_to_copy.name}'.")


    # *** STEP 2: Handle name conflict and create the new folder record ***
    new_folder_name = folder_to_copy.name
    if check_name_conflict(user_id, target_parent_folder_id, new_folder_name, 'folder'):
        app.logger.debug(f"Name conflict for folder '{new_folder_name}'. Trying '(copy)'.")
        new_folder_name = f"{new_folder_name} (copy)"
        if check_name_conflict(user_id, target_parent_folder_id, new_folder_name, 'folder'):
             app.logger.error(f"Foldername conflict unresolved: '{new_folder_name}' already exists in target parent ID: {target_parent_folder_id}")
             raise ValueError(f"Foldername conflict: '{new_folder_name}' already exists in the target folder.")

    app.logger.debug(f"Creating new folder record: Name='{new_folder_name}', ParentID={target_parent_folder_id}")
    new_folder = Folder(
        name=new_folder_name,
        user_id=user_id,
        parent_folder_id=target_parent_folder_id
    )
    db.session.add(new_folder)
    try:
        # Still flush here to get the ID needed for child items
        db.session.flush()
        app.logger.debug(f"Successfully flushed new folder record (New ID: {new_folder.id})")
    except Exception as e:
         app.logger.error(f"DATABASE ERROR during flush for new folder '{new_folder_name}': {e}", exc_info=True)
         # Rollback might be needed here if flush fails, but paste_from_clipboard should handle it
         raise # Re-raise to be caught by paste_from_clipboard

    # *** STEP 3: Copy files using the pre-fetched list ***
    app.logger.debug(f"Processing {len(files_to_copy)} files for new folder ID {new_folder.id}")
    for file_to_copy in files_to_copy:
        app.logger.debug(f"  Copying file '{file_to_copy.original_filename}' (ID: {file_to_copy.id}) into new folder ID {new_folder.id}")
        try:
            # This still does the physical copy and adds file record
            copy_file_record(file_to_copy, new_folder.id, user_id)
            app.logger.debug(f"  Successfully copied file record for '{file_to_copy.original_filename}'")
        except ValueError as e:
             app.logger.error(f"  ERROR copying file '{file_to_copy.original_filename}' during recursive folder copy: {e}")
             raise # Re-raise to trigger rollback in the main paste route
        except Exception as e:
             app.logger.error(f"  UNEXPECTED ERROR copying file '{file_to_copy.original_filename}': {e}", exc_info=True)
             raise

    # *** STEP 4: Recursively copy subfolders using the pre-fetched list ***
    app.logger.debug(f"Processing {len(subfolders_to_copy)} subfolders for new folder ID {new_folder.id}")
    for subfolder_to_copy in subfolders_to_copy:
        app.logger.debug(f"  Recursively copying subfolder '{subfolder_to_copy.name}' (ID: {subfolder_to_copy.id}) into new folder ID {new_folder.id}")
        try:
            copy_folder_recursive(subfolder_to_copy, new_folder.id, user_id)
            app.logger.debug(f"  Successfully returned from recursive copy of subfolder '{subfolder_to_copy.name}'")
        except ValueError as e:
            app.logger.error(f"  ERROR copying subfolder '{subfolder_to_copy.name}' during recursive folder copy: {e}")
            raise # Re-raise
        except Exception as e:
             app.logger.error(f"  UNEXPECTED ERROR during recursive copy of subfolder '{subfolder_to_copy.name}': {e}", exc_info=True)
             raise

    app.logger.debug(f"Finished copying folder '{folder_to_copy.name}' (ID: {folder_to_copy.id}) as '{new_folder_name}' (New ID: {new_folder.id})")
    return new_folder


# --- Clipboard Routes (Add these) ---

@app.route('/api/files/clipboard/set', methods=['POST'])
@login_required
def set_clipboard():
    """Stores item IDs and operation type (copy/cut) in the session."""
    data = request.get_json()
    if not data or 'items' not in data or 'operation' not in data:
        return jsonify({"status": "error", "message": "Invalid clipboard data."}), 400

    items = data.get('items')
    operation = data.get('operation')

    if not isinstance(items, list) or not items:
        return jsonify({"status": "error", "message": "Clipboard items must be a non-empty list."}), 400
    if operation not in ['copy', 'cut']:
        return jsonify({"status": "error", "message": "Invalid operation type."}), 400

    # Validate items structure and ownership (basic check)
    validated_items = []
    for item in items:
        if not isinstance(item, dict) or 'id' not in item or 'type' not in item:
            return jsonify({"status": "error", "message": "Invalid item structure in clipboard."}), 400
        item_id = item.get('id')
        item_type = item.get('type')
        if item_type not in ['file', 'folder']:
             return jsonify({"status": "error", "message": f"Invalid item type: {item_type}"}), 400

        # TODO: Add stricter ownership check here if needed, fetching each item
        # For now, assume items passed from frontend belong to user.

        validated_items.append({'id': item_id, 'type': item_type})

    session['clipboard'] = {'items': validated_items, 'operation': operation}
    app.logger.info(f"User {current_user.id} set clipboard: {operation} {len(validated_items)} items.")
    return jsonify({"status": "success", "message": "Items added to clipboard."})


@app.route('/api/files/clipboard/paste', methods=['POST'])
@login_required
def paste_from_clipboard():
    """Pastes items from the session clipboard into the target folder."""
    data = request.get_json()
    target_folder_id_str = data.get('target_folder_id') # Can be None or empty string for root
    target_folder_id = int(target_folder_id_str) if target_folder_id_str else None

    clipboard_data = session.get('clipboard')
    if not clipboard_data or 'items' not in clipboard_data or 'operation' not in clipboard_data:
        return jsonify({"status": "error", "message": "Clipboard is empty or invalid."}), 400

    items_to_process = clipboard_data['items']
    operation = clipboard_data['operation']
    user_id = current_user.id

    # Validate target folder (if not root)
    if target_folder_id:
        target_folder = Folder.query.filter_by(id=target_folder_id, user_id=user_id).first()
        if not target_folder:
            return jsonify({"status": "error", "message": "Target folder not found or access denied."}), 404

    processed_count = 0
    errors = []

    try:
        for item_data in items_to_process:
            item_id = item_data['id']
            item_type = item_data['type']

            app.logger.debug(f"Processing {operation} for {item_type} ID {item_id} into target {target_folder_id}")

            if item_type == 'file':
                item_to_process = File.query.filter_by(id=item_id, user_id=user_id).first()
            else: # folder
                item_to_process = Folder.query.filter_by(id=item_id, user_id=user_id).first()

            if not item_to_process:
                 app.logger.warning(f"Item {item_type} ID {item_id} not found for user {user_id} during paste.")
                 errors.append(f"Item ID {item_id} not found.")
                 continue # Skip to the next item

            # Prevent pasting folder into itself or its own descendant (complex check, omitted for brevity)
            # Prevent pasting into the same folder it's already in for 'move'
            if operation == 'cut' and item_to_process.parent_folder_id == target_folder_id:
                 app.logger.info(f"Skipping move of {item_type} {item_id}: already in target folder {target_folder_id}.")
                 # errors.append(f"Item {item_id} already in target folder.") # Or just silently succeed?
                 processed_count += 1 # Count as processed if no action needed
                 continue

            # --- Perform Copy or Move ---
            try:
                if operation == 'copy':
                    if item_type == 'file':
                        copy_file_record(item_to_process, target_folder_id, user_id)
                    else: # folder
                        copy_folder_recursive(item_to_process, target_folder_id, user_id)
                    processed_count += 1
                elif operation == 'cut':
                    # Check for name conflict before changing parent_id
                    new_name = item_to_process.name if item_type == 'folder' else item_to_process.original_filename
                    if check_name_conflict(user_id, target_folder_id, new_name, item_type, exclude_id=item_id):
                         raise ValueError(f"Name conflict: '{new_name}' already exists in the target folder.")
                    # Change parent ID
                    item_to_process.parent_folder_id = target_folder_id
                    db.session.add(item_to_process) # Mark for update
                    processed_count += 1

            except ValueError as e: # Catch errors from helpers (name conflict, storage limit)
                 app.logger.error(f"Error processing {item_type} {item_id}: {e}")
                 errors.append(f"Error processing item {item_id}: {e}")
            except Exception as e: # Catch unexpected errors
                 app.logger.error(f"Unexpected error processing {item_type} {item_id}: {e}", exc_info=True)
                 errors.append(f"Server error processing item {item_id}.")

        # --- Commit or Rollback ---
        if errors:
             db.session.rollback()
             # Clear clipboard only if cut operation failed completely? Or always clear? Let's always clear.
             session.pop('clipboard', None)
             return jsonify({
                 "status": "error",
                 "message": f"Paste operation failed for {len(errors)} items. See errors.",
                 "errors": errors,
                 "processed_count": processed_count
             }), 500
        else:
             db.session.commit()
             app.logger.info(f"{operation.capitalize()} completed for {processed_count} items by user {user_id} into folder {target_folder_id}.")
             # Clear clipboard after successful paste
             session.pop('clipboard', None)
             return jsonify({
                 "status": "success",
                 "message": f"{processed_count} items successfully {operation}ed.",
                 "processed_count": processed_count
             })

    except Exception as e: # Catch broader errors during loop/validation
        db.session.rollback()
        session.pop('clipboard', None) # Clear clipboard on any major failure
        app.logger.error(f"Major error during paste operation for user {user_id}: {e}", exc_info=True)
        return jsonify({"status": "error", "message": "A server error occurred during the paste operation."}), 500

# --- Folder Actions ---

def delete_folder_recursive(folder, user_id):
    """
    Recursively deletes a folder, its contents (files and subfolders),
    and associated database records within a single transaction context.
    NOTE: This function expects to be called within a try/except block
          in the route that handles db.session.commit() or rollback().
          It does NOT commit the session itself.
    """
    user_upload_dir = get_user_upload_path(user_id) # Get base upload dir for user

    # 1. Delete Files in the current folder
    files_in_folder = folder.files_in_folder.all() # Use relationship
    for file in files_in_folder:
        try:
            file_path = os.path.join(user_upload_dir, file.stored_filename)
            if os.path.exists(file_path):
                os.remove(file_path)
                app.logger.debug(f"Recursively deleted physical file: {file_path}")
            else:
                 app.logger.warning(f"Physical file not found during recursive delete: {file_path} (DB ID: {file.id})")
            # Delete DB record for the file
            db.session.delete(file)
            app.logger.debug(f"Recursively deleted file DB record: {file.id} ({file.original_filename})")
        except OSError as e:
             app.logger.error(f"OSError deleting physical file {file_path} during recursive delete: {e}")
             raise # Re-raise the exception to trigger rollback in the main route
        except Exception as e:
             app.logger.error(f"Error deleting file DB record {file.id} during recursive delete: {e}")
             raise # Re-raise

    # 2. Delete Subfolders recursively
    subfolders = folder.children.all() # Use relationship
    for subfolder in subfolders:
        try:
            delete_folder_recursive(subfolder, user_id) # Recursive call
        except Exception as e:
            app.logger.error(f"Error during recursive delete of subfolder {subfolder.id} ('{subfolder.name}'): {e}")
            raise # Re-raise to ensure transaction rollback

    # 3. Delete the current folder DB record itself (after contents are gone)
    try:
        folder_name = folder.name # Get name for logging before delete
        folder_id_log = folder.id
        db.session.delete(folder)
        app.logger.debug(f"Recursively deleted folder DB record: {folder_id_log} ('{folder_name}')")
    except Exception as e:
        app.logger.error(f"Error deleting folder DB record {folder.id} during recursive delete: {e}")
        raise # Re-raise


@app.route('/files/folder/delete/<int:folder_id>', methods=['POST'])
@login_required
def delete_folder(folder_id):
    """Deletes a folder and all its contents recursively."""
    folder_to_delete = Folder.query.get_or_404(folder_id)

    # 1. Verify Ownership
    if folder_to_delete.owner != current_user:
        app.logger.warning(f"User {current_user.id} attempted unauthorized delete of folder {folder_id}")
        # *** CHANGED: Return JSON error for permission denied ***
        return jsonify({"status": "error", "message": "Permission denied."}), 403

    # Store info before deleting for logging/messages
    folder_name = folder_to_delete.name # For logging/message

    try:
        # 2. Perform recursive deletion (handles files, subfolders, and the folder itself)
        # Ensure delete_folder_recursive does NOT commit the session itself
        delete_folder_recursive(folder_to_delete, current_user.id)

        # 3. Commit the transaction if everything succeeded
        db.session.commit()

        # *** CHANGED: Return JSON success instead of flash/redirect ***
        app.logger.info(f"Folder '{folder_name}' (ID: {folder_id}) and contents recursively deleted by user {current_user.id}")
        return jsonify({"status": "success", "message": f"Folder '{folder_name}' was deleted successfully."})

    except Exception as e:
        # If any error occurred during recursion or commit, rollback everything
        db.session.rollback()
        app.logger.error(f"Failed to delete folder {folder_id} ('{folder_name}') for user {current_user.id}: {e}", exc_info=True)
        # *** CHANGED: Return JSON error ***
        return jsonify({"status": "error", "message": f"Error deleting folder '{folder_name}'."}), 500

@app.route('/files/folder/new', methods=['POST'])
@login_required
def create_folder():
    """Handles creation of a new folder."""
    form = CreateFolderForm() # Process incoming form data
    parent_folder_id_str = request.form.get('parent_folder_id')
    parent_folder_id = int(parent_folder_id_str) if parent_folder_id_str else None

    # --- Validate parent folder ---
    parent_folder = None
    if parent_folder_id:
        parent_folder = Folder.query.filter_by(id=parent_folder_id, user_id=current_user.id).first()
        if not parent_folder:
            flash('Cannot create folder: Parent folder not found.', 'danger')
            return redirect(url_for('list_files')) # Redirect to root

    # --- Validate form data (name) ---
    if form.validate_on_submit():
        new_name = form.name.data.strip()

        # --- Additional Validation ---
        # Check for invalid characters (slashes)
        if '/' in new_name or '\\' in new_name:
            flash('Folder name cannot contain slashes.', 'danger')
        # Check for duplicate name within the same parent folder
        elif Folder.query.filter_by(user_id=current_user.id,
                                    parent_folder_id=parent_folder_id,
                                    name=new_name).first():
            flash(f'A folder named "{new_name}" already exists here.', 'danger')
        else:
            # --- Create Folder ---
            try:
                new_folder = Folder(name=new_name,
                                    user_id=current_user.id, # Or use owner=current_user backref
                                    parent_folder_id=parent_folder_id)
                db.session.add(new_folder)
                db.session.commit()
                flash(f'Folder "{new_name}" created successfully.', 'success')
                app.logger.info(f"Folder '{new_name}' created in parent {parent_folder_id} by user {current_user.id}")
            except Exception as e:
                db.session.rollback()
                app.logger.error(f"Error creating folder for user {current_user.id}: {e}", exc_info=True)
                flash('Failed to create folder due to a server error.', 'danger')

    else: # Form validation failed (e.g., empty name)
        for field, errors in form.errors.items():
            for error in errors:
                 flash(f"{error}", 'danger') # Show validation errors directly

    # Redirect back to the folder where creation was attempted
    return redirect(url_for('list_files', folder_id=parent_folder_id) if parent_folder_id else url_for('list_files'))

@app.route('/files/folder/rename/<int:folder_id>', methods=['POST'])
@login_required
def rename_folder(folder_id):
    """Renames a folder."""
    folder_record = Folder.query.get_or_404(folder_id)

    # 1. Verify Ownership
    if folder_record.owner != current_user:
        app.logger.warning(f"User {current_user.id} attempted unauthorized rename of folder {folder_id}")
        return jsonify({"status": "error", "message": "Permission denied."}), 403

    # 2. Get and Validate New Name
    data = request.get_json()
    if not data or 'new_name' not in data:
        return jsonify({"status": "error", "message": "Missing new folder name."}), 400

    new_name_raw = data['new_name'].strip()

    # Basic Validation
    if not new_name_raw:
        return jsonify({"status": "error", "message": "Folder name cannot be empty."}), 400
    if len(new_name_raw) > 100: # Match form validator length
        return jsonify({"status": "error", "message": "Folder name is too long."}), 400
    if '/' in new_name_raw or '\\' in new_name_raw:
         return jsonify({"status": "error", "message": "Folder name cannot contain slashes."}), 400

    sanitized_new_name = new_name_raw # Use raw name after basic checks

    # 3. Check for Duplicates within the same parent folder
    existing_folder = Folder.query.filter(
        Folder.user_id == current_user.id,
        Folder.parent_folder_id == folder_record.parent_folder_id, # Check siblings
        Folder.name == sanitized_new_name,
        Folder.id != folder_id # Exclude self
    ).first()

    if existing_folder:
         return jsonify({"status": "error", "message": f"A folder named '{sanitized_new_name}' already exists here."}), 400

    # 4. Update Database Record
    if folder_record.name == sanitized_new_name:
        return jsonify({"status": "success", "message": "Folder name unchanged.", "new_name": sanitized_new_name}), 200

    try:
        folder_record.name = sanitized_new_name
        # Update timestamp maybe? folder_record.timestamp = datetime.utcnow()
        db.session.commit()
        app.logger.info(f"Folder {folder_id} renamed to '{sanitized_new_name}' by user {current_user.id}")
        return jsonify({"status": "success", "message": "Folder renamed successfully.", "new_name": sanitized_new_name})

    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Error renaming folder {folder_id} in DB for user {current_user.id}: {e}", exc_info=True)
        return jsonify({"status": "error", "message": "Database error occurred during rename."}), 500

@app.route('/files/rename/<int:file_id>', methods=['POST'])
@login_required
def rename_file(file_id):
    """Renames a file."""
    file_record = File.query.get_or_404(file_id)

    # 1. Verify Ownership
    if file_record.owner != current_user:
        app.logger.warning(f"User {current_user.id} attempted unauthorized rename of file {file_id}")
        return jsonify({"status": "error", "message": "Permission denied."}), 403

    # 2. Get and Validate New Name from JSON request body
    data = request.get_json()
    if not data or 'new_name' not in data:
        return jsonify({"status": "error", "message": "Missing new filename."}), 400

    new_name_raw = data['new_name'].strip()

    # Basic Validation (prevent empty, excessive length, slashes)
    if not new_name_raw:
        return jsonify({"status": "error", "message": "Filename cannot be empty."}), 400
    if len(new_name_raw) > 250: # Max length check
        return jsonify({"status": "error", "message": "Filename is too long."}), 400
    # Prevent path traversal characters
    if '/' in new_name_raw or '\\' in new_name_raw:
         return jsonify({"status": "error", "message": "Filename cannot contain slashes."}), 400
    # You might want more validation here (e.g., allowed characters)
    # Using a simple approach here, not werkzeug.secure_filename which is often too restrictive
    sanitized_new_name = new_name_raw # Use raw name after basic checks for now

    # 3. Update Database Record
    if file_record.original_filename == sanitized_new_name:
        return jsonify({"status": "success", "message": "Filename unchanged.", "new_name": sanitized_new_name}), 200 # OK, but no change

    try:
        file_record.original_filename = sanitized_new_name
        db.session.commit()
        app.logger.info(f"File {file_id} renamed to '{sanitized_new_name}' by user {current_user.id}")
        return jsonify({"status": "success", "message": "File renamed successfully.", "new_name": sanitized_new_name})

    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Error renaming file {file_id} in DB for user {current_user.id}: {e}", exc_info=True)
        return jsonify({"status": "error", "message": "Database error occurred during rename."}), 500

@app.route('/files/view/<int:file_id>')
@login_required
def view_file(file_id):
    file_record = File.query.get_or_404(file_id)

    can_access = False
    # 1. Check if current user is the owner
    if file_record.owner == current_user:
        can_access = True
    else:
        # 2. Check if the file is referenced in any GroupChatMessage.
        if GroupChatMessage.query.filter_by(file_id=file_record.id).first():
            can_access = True # Authenticated users can access files shared in the global group chat

    if not can_access:
        app.logger.warning(f"Access denied: User {current_user.id} attempted view of file {file_id}. Owner: {file_record.user_id}. Not shared in chat or user is not owner.")
        abort(403)  # Forbidden

    # IMPORTANT: Use the actual file owner's ID to construct the path
    user_upload_path = get_user_upload_path(file_record.user_id)
    stored_filename = file_record.stored_filename
    mime_type = file_record.mime_type or 'application/octet-stream'

    full_file_path = os.path.join(user_upload_path, stored_filename)
    if not os.path.exists(full_file_path):
         app.logger.error(f"File not found on disk for viewing record {file_id}: {stored_filename} in {user_upload_path}")
         abort(404)

    try:
        return send_from_directory(user_upload_path,
                                   stored_filename,
                                   mimetype=mime_type,
                                   as_attachment=False, # Serve inline for viewing
                                   conditional=True)    # Enable browser caching
    except Exception as e:
        app.logger.error(f"Error serving file {file_id} for viewing by user {current_user.id}: {e}", exc_info=True)
        # You might want a more user-friendly error page than just text
        return "Error serving file.", 500

# Add this new route function
@app.route('/ollama_chat', methods=['GET', 'POST'])
@login_required
def ollama_chat():
    app.logger.info(f"--- ollama_chat route hit --- METHOD: {request.method}") # Keep logging for now
    form = OllamaChatForm()
    error_message = None
    history_for_template = []

    # --- Fetch history (runs on GET and POST) ---
    try:
        db_messages = current_user.ollama_chat_messages.order_by(OllamaChatMessage.timestamp).all()
        history_for_ollama = [msg.to_dict() for msg in db_messages]
        history_for_template = list(history_for_ollama)
    except Exception as e:
        app.logger.error(f"Error fetching ollama chat history for user {current_user.id}: {e}", exc_info=True)
        flash("Could not load ollama chat history.", "danger")
        history_for_ollama = []
        history_for_template = []

    is_valid_submit = form.validate_on_submit()
    app.logger.info(f"form.validate_on_submit() returned: {is_valid_submit}") # Keep logging

    if is_valid_submit:
        app.logger.info(f"!!! Processing form submission in ollama_chat route !!!") # Keep logging
        user_message_content = form.message.data
        # Don't clear form.message.data here if redirecting, it won't matter

        ai_response_content, error_message = send_message_to_ollama( # AI Call
            user_message_content,
            history_for_ollama
        )

        if error_message:
            flash(error_message, 'danger')
            # Don't redirect on error, just re-render the template below
        elif ai_response_content:
            try:
                user_msg_db = OllamaChatMessage(
                    user_id=current_user.id, role='user', content=user_message_content
                )
                ai_msg_db = OllamaChatMessage(
                    user_id=current_user.id, role='assistant', content=ai_response_content
                )
                db.session.add(user_msg_db)
                db.session.add(ai_msg_db)
                db.session.commit()
                app.logger.info(f"Saved user/ollama chat messages for user {current_user.id} via direct POST")
                # --- ADD REDIRECT HERE ---
                # After successful processing and commit, redirect back to the chat page via GET
                return redirect(url_for('ollama_chat'))
                # -------------------------
            except Exception as e:
                 db.session.rollback()
                 app.logger.error(f"Error saving ollama chat messages for user {current_user.id} via direct POST: {e}", exc_info=True)
                 flash("Failed to save ollama chat message.", "danger")
                 # Don't redirect on error, just re-render the template below
        else:
            flash("Received no response from the AI.", "warning")
            # Don't redirect, just re-render the template below

        # If we reached here due to an error or no AI content, we fall through to render_template

    # --- Render template (runs on GET and POST failures/edge cases) ---
    app.logger.info(f"Rendering ollama_chat.html template...")
    return render_template('ollama_chat.html',
                           title='Ollama Chat',
                           form=form,
                           ollama_chat_history=history_for_template)

@app.route('/ollama_chat/clear', methods=['GET']) # Or POST if preferred
@login_required
def clear_ollama_chat_history():
    try:
        # Delete all ollama ChatMessage records for the current user
        num_deleted = OllamaChatMessage.query.filter_by(user_id=current_user.id).delete()
        db.session.commit()
        flash(f'Ollama chat history cleared ({num_deleted} messages removed).', 'info')
        app.logger.info(f"Cleared {num_deleted} ollama chat messages for user {current_user.id}")
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Error clearing ollama chat history for user {current_user.id}: {e}", exc_info=True)
        flash('Failed to clear ollama chat history.', 'danger')

    return redirect(url_for('ollama_chat'))

@app.route('/api/ollama_chat/send', methods=['POST'])
@login_required
def api_ollama_chat_send():
    data = request.get_json()
    if not data or 'message' not in data:
        return jsonify({"status": "error", "message": "Missing message content."}), 400

    user_message_content = data['message'].strip()
    if not user_message_content:
        return jsonify({"status": "error", "message": "Message cannot be empty."}), 400

    # --- Fetch CURRENT history from DB before sending ---
    history_for_ollama = []
    try:
        db_messages = current_user.ollama_chat_messages.order_by(OllamaChatMessage.timestamp).all()
        history_for_ollama = [msg.to_dict() for msg in db_messages]
    except Exception as e:
        app.logger.error(f"API: Error fetching ollama chat history for user {current_user.id}: {e}", exc_info=True)
        # Decide if you want to proceed with empty history or return error
        # Let's return an error for consistency
        return jsonify({"status": "error", "message": "Could not retrieve ollama chat history context."}), 500

    # --- Call Ollama ---
    ai_response_content, error_message = send_message_to_ollama(
        user_message_content,
        history_for_ollama
    )

    if error_message:
        # Don't save if Ollama failed
        app.logger.error(f"Ollama error for user {current_user.id}: {error_message}")
        return jsonify({"status": "error", "message": error_message}), 500 # 500 for server-side/API issues

    elif ai_response_content:
        # --- Save BOTH user message and AI response to DB ---
        try:
            user_msg_db = OllamaChatMessage(
                user_id=current_user.id,
                role='user',
                content=user_message_content
            )
            ai_msg_db = OllamaChatMessage(
                user_id=current_user.id,
                role='assistant',
                content=ai_response_content
             )
            # Add user message first, then AI response
            db.session.add(user_msg_db)
            db.session.add(ai_msg_db)
            db.session.commit()
            app.logger.info(f"API: Saved user/ollama chat messages for user {current_user.id}")

            # --- Return success with AI response ---
            return jsonify({
                "status": "success",
                "ai_message": ai_response_content
            })

        except Exception as e:
             db.session.rollback()
             app.logger.error(f"API: Error saving ollama chat messages for user {current_user.id}: {e}", exc_info=True)
             return jsonify({"status": "error", "message": "Failed to save ollama chat messages to database."}), 500
    else:
        # Handle unexpected case where Ollama returns no content and no error
        app.logger.warning(f"API: Ollama returned no content and no error for user {current_user.id}")
        return jsonify({"status": "error", "message": "Received no response content from the AI."}), 500

@app.route('/group_chat')
@login_required
def group_chat():
    """Displays the main group chat interface."""
    form = GroupChatForm()
    # Fetch all messages for simplicity initially. Consider pagination for large histories.
    try:
        # Eager load sender and file info to optimize
        messages = GroupChatMessage.query.options(
                db.joinedload(GroupChatMessage.sender),
                db.joinedload(GroupChatMessage.shared_file) # Ensure File model is joinedloadable
            ).order_by(GroupChatMessage.timestamp.asc()).all()

        # Convert messages to dicts for easier handling in template/JS
        # Use the to_dict method defined in the model
        message_dicts = [msg.to_dict() for msg in messages]

    except Exception as e:
        app.logger.error(f"Error fetching group chat messages: {e}", exc_info=True)
        flash("Could not load chat history.", "danger")
        message_dicts = []

    # --- Fetch Max Upload Size Setting (Used by template's dropzone/input hints) ---
    try:
        max_upload_mb_str = Setting.get('max_upload_size_mb', str(DEFAULT_MAX_UPLOAD_MB_FALLBACK))
        max_upload_mb = int(max_upload_mb_str)
    except (ValueError, TypeError):
        max_upload_mb = DEFAULT_MAX_UPLOAD_MB_FALLBACK
        app.logger.warning(f"Invalid max_upload_size_mb setting '{max_upload_mb_str}'. Using fallback {max_upload_mb}MB for display.")
    # --- End Fetch ---

    return render_template('group_chat.html', # Ensure this template exists later
                           title="Group Chat",
                           form=form,
                           chat_history=message_dicts, # Pass the processed list of dicts
                           max_upload_mb=max_upload_mb)


@app.route('/api/group_chat/send', methods=['POST'])
@login_required
def api_group_chat_send():
    """Handles sending new messages (text or file) to the group chat via API."""
    content = request.form.get('content', '').strip()
    file = request.files.get('file')
    new_file_record = None
    error_message = None
    status_code = 200
    file_path = None # Define file_path here for broader scope in error handling

    # Validate: Must have content or a file
    if not content and (not file or file.filename == ''): # Check if file exists and has a name
        return jsonify({"status": "error", "message": "Message content or file attachment required."}), 400

    # --- Handle File Upload (if present) ---
    if file and file.filename != '':
        original_filename = secure_filename(file.filename)
        app.logger.info(f"Processing chat file upload: {original_filename}")

        # --- Determine File Size ---
        uploaded_filesize = None
        try:
            # Try reading stream size first
            current_pos = file.tell()
            file.seek(0, os.SEEK_END)
            uploaded_filesize = file.tell()
            file.seek(current_pos) # Reset to original position
            if uploaded_filesize is None: raise ValueError("Stream tell() returned None.")
        except Exception as e:
            app.logger.warning(f"Could not determine file size using stream: {e}. Trying Content-Length.")
            uploaded_filesize = request.content_length # Fallback

        if uploaded_filesize is None:
            return jsonify({"status": "error", "message": "Could not determine file size."}), 400

        # --- File Size Checks ---
        # 1. Server Limit (MAX_CONTENT_LENGTH)
        hard_limit_bytes = current_app.config.get('MAX_CONTENT_LENGTH')
        if hard_limit_bytes and uploaded_filesize > hard_limit_bytes:
             limit_mb = hard_limit_bytes // (1024 * 1024)
             error_message = f'Upload failed: File size ({uploaded_filesize / (1024*1024):.1f} MB) exceeds server limit ({limit_mb} MB).'
             status_code = 413

        # 2. Admin Max Upload Limit (From Settings)
        if not error_message:
            try:
                max_upload_mb_str = Setting.get('max_upload_size_mb', str(DEFAULT_MAX_UPLOAD_MB_FALLBACK))
                admin_limit_bytes = int(max_upload_mb_str) * 1024 * 1024
                if uploaded_filesize > admin_limit_bytes:
                    error_message = f'Upload failed: File size exceeds the maximum allowed ({max_upload_mb_str} MB).'
                    status_code = 413
            except (ValueError, TypeError) as e:
                 app.logger.error(f"Admin setting error for max_upload_size_mb: {e}", exc_info=True)
                 error_message = "Server configuration error reading upload limit."
                 status_code = 500

        # 3. User Storage Limit
        if not error_message:
            storage_info = get_user_storage_info(current_user)
            # Handle infinite limit correctly
            available_bytes = float('inf') if storage_info['limit_bytes'] == float('inf') else storage_info['limit_bytes'] - storage_info['usage_bytes']

            if uploaded_filesize > available_bytes:
                 limit_mb_display = f"{storage_info['limit_mb']} MB" if storage_info['limit_mb'] is not None else 'Unlimited'
                 usage_mb = round(storage_info['usage_bytes'] / (1024*1024), 1)
                 required_mb = round(uploaded_filesize / (1024*1024), 1)
                 available_mb_display = f"{available_bytes / (1024*1024):.1f}" if available_bytes != float('inf') else 'unlimited'
                 error_message = f'Upload failed: Insufficient storage. Requires {required_mb} MB, {available_mb_display} free (Usage: {usage_mb} MB, Limit: {limit_mb_display}).'
                 status_code = 413

        # --- If Checks Pass, Prepare to Save File ---
        if not error_message:
            try:
                _, ext = os.path.splitext(original_filename)
                stored_filename = str(uuid.uuid4()) + ext
                user_upload_path = get_user_upload_path(current_user.id)
                os.makedirs(user_upload_path, exist_ok=True)
                file_path = os.path.join(user_upload_path, stored_filename) # Assign here

                # Save the file physically FIRST
                file.save(file_path)
                app.logger.info(f"Chat file saved physically: {file_path}")

                mime_type, _ = mimetypes.guess_type(file_path)
                mime_type = mime_type or 'application/octet-stream'

                # Create File DB record, but DO NOT commit yet
                new_file_record = File(
                    original_filename=original_filename,
                    stored_filename=stored_filename,
                    filesize=uploaded_filesize,
                    mime_type=mime_type,
                    owner=current_user, # Link to the user who uploaded it
                    parent_folder_id=None # Chat uploads are not in a specific "folder"
                )
                db.session.add(new_file_record)
                db.session.flush() # Assigns an ID to new_file_record
                app.logger.info(f"Chat File record created (ID: {new_file_record.id}), pending commit.")

            except OSError as e:
                db.session.rollback()
                app.logger.error(f"OSError saving chat file {original_filename} to {file_path}: {e}", exc_info=True)
                error_message = "Error saving uploaded file to storage."
                status_code = 500
                # No need to clean up file here, as save likely failed before file existed fully
            except Exception as e:
                db.session.rollback()
                app.logger.error(f"Unexpected error preparing chat file record for {original_filename}: {e}", exc_info=True)
                error_message = "An unexpected error occurred during file processing."
                status_code = 500
                # Clean up physical file if save succeeded but DB ops failed
                if file_path and os.path.exists(file_path):
                     try: os.remove(file_path); app.logger.info(f"Cleaned up orphaned chat file: {file_path}")
                     except OSError: pass

    # --- Return error response if file upload failed ---
    if error_message:
        return jsonify({"status": "error", "message": error_message}), status_code

    # --- Save Chat Message Record (linking file if needed) ---
    try:
        new_message = GroupChatMessage(
            user_id=current_user.id,
            content=content if content else None, # Store text content (or None if file-only)
            file_id=new_file_record.id if new_file_record else None # Link File record ID
        )
        db.session.add(new_message)
        db.session.commit() # Commit message record (and file record if applicable)
        app.logger.info(f"Group chat message saved (ID: {new_message.id}, FileID: {new_message.file_id}) by user {current_user.id}")

        # Send back the newly created message data, formatted for the client
        # Need to refresh to load relationships properly after commit
        db.session.refresh(new_message)
        if new_file_record: # Also refresh file if it was just added
            db.session.refresh(new_file_record)

        message_data = new_message.to_dict() # Use the helper

        return jsonify({"status": "success", "message": message_data}), 201 # 201 Created

    except Exception as e:
        db.session.rollback() # Rollback message and file records
        app.logger.error(f"Error saving group chat message DB record for user {current_user.id}: {e}", exc_info=True)
        # Clean up the physical file if it was part of this failed transaction
        if file_path and os.path.exists(file_path):
            try: os.remove(file_path); app.logger.info(f"Cleaned up chat file after DB error: {file_path}")
            except OSError as rm_err: app.logger.error(f"Error cleaning up chat file {file_path}: {rm_err}")
        return jsonify({"status": "error", "message": "Error saving chat message to database."}), 500

@app.route('/api/group_chat/edit/<int:message_id>', methods=['POST'])
@login_required
def api_group_chat_edit_message(message_id):
    """Handles editing an existing group chat message via API."""
    message = GroupChatMessage.query.get_or_404(message_id)

    # Check if the current user is the sender of the message
    if message.user_id != current_user.id:
        app.logger.warning(f"User {current_user.id} attempted to edit message {message_id} not belonging to them.")
        return jsonify({"status": "error", "message": "Permission denied. You can only edit your own messages."}), 403

    data = request.get_json()
    new_content = data.get('content', '').strip()

    if not new_content:
        return jsonify({"status": "error", "message": "New message content cannot be empty."}), 400

    # Prevent editing if the message has a file attachment (for simplicity)
    # More complex logic would be needed to allow changing text of a message with a file.
    if message.file_id:
        return jsonify({"status": "error", "message": "Cannot edit messages with file attachments through this endpoint."}), 400

    try:
        message.content = new_content
        message.edited_at = datetime.utcnow()
        db.session.commit()
        app.logger.info(f"Group chat message {message_id} edited by user {current_user.id}")

        # Return the updated message data
        db.session.refresh(message) # Refresh to get any db-generated changes
        return jsonify({"status": "success", "message": "Message updated successfully.", "updated_message": message.to_dict()})

    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Error editing group chat message {message_id} for user {current_user.id}: {e}", exc_info=True)
        return jsonify({"status": "error", "message": "Failed to update message."}), 500

@app.route('/api/group_chat/delete/<int:message_id>', methods=['POST'])
@login_required
def api_group_chat_delete_message(message_id):
    message = GroupChatMessage.query.get_or_404(message_id)
    file_to_delete_permanently = None # Variable to hold the File record if we decide to delete it

    # Permission check: User can delete their own message, or an admin can delete any message.
    if not (message.user_id == current_user.id or current_user.is_admin):
        app.logger.warning(f"User {current_user.id} attempted to delete message {message_id} without permission.")
        return jsonify({"status": "error", "message": "Permission denied."}), 403

    try:
        if message.file_id:
            # --- New Logic: Prepare to delete the associated file ---
            file_record = File.query.get(message.file_id)
            if file_record:
                # Additional permission check for file deletion:
                # Only the file owner or an admin should be able to trigger permanent file deletion.
                # If the message sender is not the file owner, but is an admin, they can delete.
                # If the message sender is the file owner, they can delete.
                if file_record.user_id == current_user.id or current_user.is_admin:
                    file_to_delete_permanently = file_record
                    app.logger.info(f"Message {message_id} has attachment File ID {file_record.id}. Marked for permanent deletion by User {current_user.id} (Admin: {current_user.is_admin}). File Owner: {file_record.user_id}")
                else:
                    # This case means the user deleting the message is the message sender
                    # but NOT the file owner, AND is NOT an admin.
                    # In this scenario, we should probably only soft-delete the message
                    # and leave the file intact.
                    app.logger.warning(f"User {current_user.id} (message sender) is deleting message {message_id} but does not own attached File ID {file_record.id} and is not admin. File will not be deleted.")
            else:
                app.logger.warning(f"Message {message_id} had a file_id {message.file_id} but the File record was not found. Cannot delete file.")
        # --- End of New Logic for file deletion preparation ---

        # Soft-delete the message itself
        message.is_deleted = True
        message.deleted_at = datetime.utcnow()
        message.edited_at = message.deleted_at # To trigger updates for clients

        # If a file was marked for deletion, proceed with deleting it
        if file_to_delete_permanently:
            original_filename_log = file_to_delete_permanently.original_filename
            stored_filename_log = file_to_delete_permanently.stored_filename
            file_id_log = file_to_delete_permanently.id

            # Determine the correct user_upload_path based on the file's actual owner
            user_upload_path = get_user_upload_path(file_to_delete_permanently.user_id)
            full_file_path = os.path.join(user_upload_path, file_to_delete_permanently.stored_filename)

            # 1. Delete Physical File
            if os.path.exists(full_file_path):
                os.remove(full_file_path)
                app.logger.info(f"Permanently deleted physical file: {full_file_path} (associated with deleted chat message {message_id})")
            else:
                app.logger.warning(f"Physical file not found at {full_file_path} during permanent delete for File ID {file_id_log} (associated with chat message {message_id}).")

            # 2. Delete File Database Record
            # Important: Before deleting the File record, ensure no other GroupChatMessage
            # still references it (if you decide not to delete files if they are multi-referenced in chat).
            # For simplicity here, we are deleting if this message deletion triggers it.
            # A more complex system might check `file_to_delete_permanently.group_chat_shares`
            # and only delete if the count is 1 (or 0 after this message is unlinked).
            # However, `ondelete='SET NULL'` on GroupChatMessage.file_id means this message's link
            # would be nullified first, so we'd always see 0 or more *other* shares.

            # Given ondelete='SET NULL', we must nullify the reference from the message
            # *before* deleting the File object to avoid foreign key issues if the File
            # object is deleted first and the message session isn't yet committed.
            # However, we are deleting the message (soft delete) anyway.
            # The File model relationship `group_chat_shares` is `lazy='joined'` and `uselist=False` which is odd for a backref typically being a list.
            # Assuming `file.group_chat_shares` is meant to be a collection or that the ondelete behavior is primary.
            # Let's ensure message.file_id is cleared if the file is deleted.
            message.file_id = None # Explicitly unlink before committing File deletion

            db.session.delete(file_to_delete_permanently)
            app.logger.info(f"Permanently deleted File record ID {file_id_log} ('{original_filename_log}', Stored: '{stored_filename_log}') associated with chat message {message_id}.")

        db.session.commit()
        app.logger.info(f"Group chat message {message_id} soft-deleted by user {current_user.id} (Admin: {current_user.is_admin}). Associated file action taken if applicable.")
        return jsonify({"status": "success", "message": "Message deleted successfully."})

    except OSError as e:
        db.session.rollback()
        app.logger.error(f"OSError during message/file deletion for message ID {message_id} by user {current_user.id}: {e}", exc_info=True)
        return jsonify({"status": "error", "message": "Error during file system operation while deleting."}), 500
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Error soft-deleting group chat message {message_id} or its attachment by user {current_user.id}: {e}", exc_info=True)
        return jsonify({"status": "error", "message": "Failed to delete message or its attachment."}), 500

@app.route('/api/group_chat/history')
@login_required
def api_group_chat_history():
    last_message_id = request.args.get('last_message_id', type=int, default=0)
    # New parameter: client's latest known edit timestamp (globally for any message)
    # Client would need to track the max(edited_at) it has seen.
    client_last_edit_ts_str = request.args.get('last_edit_ts', None)
    limit = 100 # Example limit

    try:
        query = GroupChatMessage.query.options(
            db.joinedload(GroupChatMessage.sender).load_only(User.username),
            db.joinedload(GroupChatMessage.shared_file)
        )

        # Conditions for fetching
        conditions = []
        if last_message_id > 0:
            conditions.append(GroupChatMessage.id > last_message_id)

        if client_last_edit_ts_str:
            try:
                # Parse the timestamp, assuming ISO format from client
                client_last_edit_dt = datetime.fromisoformat(client_last_edit_ts_str.replace('Z', '+00:00'))
                conditions.append(GroupChatMessage.edited_at > client_last_edit_dt)
            except ValueError:
                app.logger.warning(f"Invalid last_edit_ts format: {client_last_edit_ts_str}")
                # Optionally, ignore this condition or return an error

        if conditions:
            query = query.filter(db.or_(*conditions))

        # Always order by original timestamp for consistency, then perhaps by ID or edited_at
        messages = query.order_by(GroupChatMessage.timestamp.asc(), GroupChatMessage.id.asc()).limit(limit).all()

        message_dicts = [msg.to_dict() for msg in messages]

        # Server should also send back its current latest edit timestamp so client can update
        # This would be max(edited_at) from all messages, or just server's current time.
        # server_latest_edit_ts = datetime.utcnow().isoformat() + 'Z'

        return jsonify({
            "status": "success",
            "messages": message_dicts
            # "latest_server_edit_ts": latest_ts_iso # Include if client uses it
        })

    except Exception as e:
        app.logger.error(f"Error fetching group chat history with edit detection: {e}", exc_info=True)
        return jsonify({"status": "error", "message": "Could not retrieve chat history."}), 500

@app.route('/admin/group_chat/delete/<int:message_id>', methods=['POST'])
@login_required
def admin_delete_group_chat_message(message_id):
    """Allows admin to delete a specific group chat message."""
    if not current_user.is_admin:
        # Check Accept header for AJAX request
        is_ajax = request.accept_mimetypes.accept_json and \
                  not request.accept_mimetypes.accept_html
        if is_ajax:
             return jsonify({"status": "error", "message": "Permission denied."}), 403
        else:
             flash("Permission denied.", "danger")
             return redirect(request.referrer or url_for('group_chat')) # Redirect back


    message = GroupChatMessage.query.get_or_404(message_id)
    # Note: Associated file record/physical file is NOT deleted here by default.
    # The File record might be referenced elsewhere or deletion might be undesirable.
    # If you WANT to delete the associated file, add that logic here carefully.

    try:
        db.session.delete(message)
        db.session.commit()
        app.logger.info(f"Admin {current_user.username} deleted group chat message {message_id}")
        # Return JSON for AJAX requests, otherwise flash/redirect
        is_ajax = request.accept_mimetypes.accept_json and \
                  not request.accept_mimetypes.accept_html
        if is_ajax:
            return jsonify({"status": "success", "message": "Message deleted."})
        else:
            flash("Message deleted successfully.", "success")
            return redirect(url_for('group_chat')) # Redirect to chat after deletion

    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Admin {current_user.username} failed to delete group chat message {message_id}: {e}", exc_info=True)
        is_ajax = request.accept_mimetypes.accept_json and \
                  not request.accept_mimetypes.accept_html
        if is_ajax:
            return jsonify({"status": "error", "message": "Failed to delete message."}), 500
        else:
            flash("Failed to delete message.", "danger")
            return redirect(url_for('group_chat'))

# --- Public Sharing Route ---

# Use '/s/' for short shared links
@app.route('/s/<string:public_id>', methods=['GET', 'POST']) # Allow POST for password submission
# NO @login_required here!
def serve_shared_file(public_id):
    """Serves a publicly shared file, prompting for password if needed."""
    # 1. Find file by public_id, ensure it's public
    file_record = File.query.filter_by(public_id=public_id, is_public=True).first_or_404()

    # 2. Check if password protected
    is_protected = bool(file_record.public_password_hash)
    password_ok = not is_protected # If not protected, password check passes automatically

    # 3. Handle password check if protected
    if is_protected and request.method == 'POST':
        # Check submitted password from form
        submitted_password = request.form.get('password')
        if submitted_password and check_password_hash(file_record.public_password_hash, submitted_password):
            password_ok = True
            # Optionally store success in session briefly? Maybe not needed.
        else:
            flash('Incorrect password.', 'danger')
            # Fall through to re-render password form below

    # 4. Serve file OR render password form
    if password_ok:
        # Password check passed (or wasn't needed), serve the file
        user_id = file_record.user_id
        stored_filename = file_record.stored_filename
        original_filename = file_record.original_filename
        user_upload_path = get_user_upload_path(user_id)

        full_file_path = os.path.join(user_upload_path, stored_filename)
        if not os.path.exists(full_file_path): abort(404)

        try:
            app.logger.info(f"Serving public file {file_record.id} ('{original_filename}') via link {public_id}")
            return send_from_directory(user_upload_path, stored_filename,
                                       as_attachment=True, download_name=original_filename, conditional=True)
        except Exception as e:
            app.logger.error(f"Error serving public file {file_record.id}: {e}", exc_info=True)
            return "Error serving file.", 500
    elif is_protected:
        # Needs password, and it wasn't provided correctly via POST or it's a GET request
        return render_template('share_password.html', public_id=public_id, file_name=file_record.original_filename)
    else:
        # Should not happen if logic is correct, but catch just in case
        app.logger.error(f"Logic error in serve_shared_file for {public_id}. Not protected but password_ok is false.")
        abort(500)

@app.route('/files/share/<int:file_id>', methods=['POST'])
@login_required
def share_file(file_id):
    """Generates a public share link for a file, optionally with a password."""
    file_record = File.query.get_or_404(file_id)
    if file_record.owner != current_user:
        abort(403)

    data = request.get_json() or {} # Get JSON data, default to empty dict if none
    password = data.get('password') # Get optional password from request body

    try:
        # Generate public ID if it doesn't exist
        if not file_record.public_id:
            file_record.public_id = str(uuid.uuid4())

        # Set password hash if password provided, else clear it
        if password: # Check if password is provided and not empty
            file_record.public_password_hash = generate_password_hash(password)
            password_protected = True
            app.logger.info(f"Password set for share link of file {file_id}")
        else:
            file_record.public_password_hash = None
            password_protected = False
            app.logger.info(f"Password NOT set for share link of file {file_id}")

        file_record.is_public = True
        db.session.commit()

        share_url = url_for('serve_shared_file', public_id=file_record.public_id, _external=True)
        app.logger.info(f"File {file_id} shared by user {current_user.id}. Link: {share_url}")
        return jsonify({
            "status": "success",
            "message": "File is now shared publicly" + (" (password protected)." if password_protected else "."),
            "share_url": share_url,
            "public_id": file_record.public_id,
            "password_protected": password_protected # Indicate if password was set
        })
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Error sharing file {file_id} for user {current_user.id}: {e}", exc_info=True)
        return jsonify({"status": "error", "message": "Failed to share file."}), 500


@app.route('/files/unshare/<int:file_id>', methods=['POST'])
@login_required
def unshare_file(file_id):
    """Disables the public share link for a file."""
    file_record = File.query.get_or_404(file_id)
    if file_record.owner != current_user:
        abort(403)

    try:
        file_record.is_public = False
        file_record.public_password_hash = None # Clear password hash too
        # Optionally clear public_id? Depends on desired behavior. Let's keep it for now.
        # file_record.public_id = None
        db.session.commit()
        app.logger.info(f"File {file_id} unshared by user {current_user.id}")
        return jsonify({"status": "success", "message": "File sharing disabled."})
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Error unsharing file {file_id} for user {current_user.id}: {e}", exc_info=True)
        return jsonify({"status": "error", "message": "Failed to unshare file."}), 500


# --- Note Routes ---

@app.route('/notes')
@login_required
def list_notes():
    """Displays a list of the current user's notes."""
    # Query notes belonging to the current user, order by timestamp descending
    user_notes = Note.query.filter_by(author=current_user).order_by(Note.timestamp.desc()).all()
    return render_template('notes.html', title='My Notes', notes=user_notes)

@app.route('/notes/new', methods=['GET', 'POST'])
@login_required
def new_note():
    """Handles creation of a new note."""
    form = NoteForm()
    if form.validate_on_submit():
        try:
            note = Note(title=form.title.data,
                        content=form.content.data,
                        author=current_user) # Associate with logged-in user
            db.session.add(note)
            db.session.commit()
            flash('Note created successfully!', 'success')
            app.logger.info(f"Note '{note.title}' (ID: {note.id}) created by user {current_user.id}")
            return redirect(url_for('list_notes'))
        except Exception as e:
            db.session.rollback()
            app.logger.error(f"Error creating note for user {current_user.id}: {e}", exc_info=True)
            flash('Failed to create note.', 'danger')
    # For GET request, just render the empty form
    return render_template('note_form.html', title='New Note', form=form, legend='Create New Note')

@app.route('/notes/<int:note_id>')
@login_required
def view_note(note_id):
    """Displays a single note."""
    # Fetch the note by ID, ensuring it belongs to the current user
    note = Note.query.get_or_404(note_id) # Get note or raise 404 if not found
    if note.author != current_user:
        app.logger.warning(f"User {current_user.id} attempted to access note {note_id} owned by user {note.user_id}")
        abort(403) # Forbidden access

    return render_template('view_note.html', title=note.title, note=note)

@app.route('/notes/<int:note_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_note(note_id):
    """Handles editing an existing note."""
    note = Note.query.get_or_404(note_id)
    if note.author != current_user:
        app.logger.warning(f"User {current_user.id} attempted to edit note {note_id} owned by user {note.user_id}")
        abort(403) # Forbidden

    form = NoteForm()
    if form.validate_on_submit(): # Process POST request
        try:
            note.title = form.title.data
            note.content = form.content.data
            # Optionally update timestamp on edit: note.timestamp = datetime.utcnow()
            db.session.commit()
            flash('Note updated successfully!', 'success')
            app.logger.info(f"Note {note_id} updated by user {current_user.id}")
            return redirect(url_for('view_note', note_id=note.id))
        except Exception as e:
            db.session.rollback()
            app.logger.error(f"Error editing note {note_id} for user {current_user.id}: {e}", exc_info=True)
            flash('Failed to update note.', 'danger')
    elif request.method == 'GET': # Populate form for GET request
        form.title.data = note.title
        form.content.data = note.content

    return render_template('note_form.html', title='Edit Note', form=form, legend=f'Edit Note: "{note.title}"', note_id=note_id)


@app.route('/notes/<int:note_id>/delete', methods=['POST']) # Use POST for deletion
@login_required
def delete_note(note_id):
    """Deletes a note."""
    note = Note.query.get_or_404(note_id)
    if note.author != current_user:
        app.logger.warning(f"User {current_user.id} attempted to delete note {note_id} owned by user {note.user_id}")
        abort(403) # Forbidden

    try:
        note_title = note.title # Get title before deleting for logging
        db.session.delete(note)
        db.session.commit()
        flash(f'Note "{note_title}" deleted successfully!', 'success')
        app.logger.info(f"Note '{note_title}' (ID: {note_id}) deleted by user {current_user.id}")
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Error deleting note {note_id} for user {current_user.id}: {e}", exc_info=True)
        flash('Failed to delete note.', 'danger')

    return redirect(url_for('list_notes'))

@app.route('/forgot_password', methods=['GET', 'POST'])
def forgot_password():
    if current_user.is_authenticated:
        return redirect(url_for('list_files')) # Or your main authenticated page

    form = ForgotPasswordForm() # Assuming you have this form defined
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data).first()
        if user:
            token = user.get_reset_token() # Assuming get_reset_token method on User model
            reset_url = url_for('reset_token', token=token, _external=True)

            # --- Prepare Email ---
            subject = "Password Reset Request"

            # Get sender from app config, provide a fallback
            # Ensure MAIL_DEFAULT_SENDER_NAME and MAIL_DEFAULT_SENDER_EMAIL are set in admin settings
            sender_name = Setting.get('MAIL_DEFAULT_SENDER_NAME', 'PyCloud')
            sender_email = Setting.get('MAIL_DEFAULT_SENDER_EMAIL', 'noreply@example.com')

            actual_sender = (str(sender_name), str(sender_email)) if sender_name else str(sender_email)

            # Plain text body (for email clients that don't support HTML)
            text_body = f"""Hello {user.username},

We received a request to reset the password for your account.
To reset your password, please visit the following link:
{reset_url}

This link is valid for approximately 30 minutes.

If you did not request a password reset, please ignore this email. No changes will be made to your account.

Thank you,
The {sender_name} Team
"""
            # HTML body (rendered from the new template)
            html_body = render_template(
                'reset_email.html', # Your new HTML email template
                subject=subject,
                username=user.username,
                reset_url=reset_url,
                app_name=sender_name, # Use the configured sender name as app_name
            )

            msg = Message(subject,
                          sender=actual_sender,
                          recipients=[user.email])
            msg.body = text_body # Set the plain text part
            msg.html = html_body # Set the HTML part

            try:
                current_app.logger.info(f"Attempting to send password reset email to {user.email} from {actual_sender}")
                mail.send(msg)
                flash('An email has been sent with instructions to reset your password.', 'info')
            except Exception as e:
                current_app.logger.error(f"Failed to send password reset email to {user.email}: {e}", exc_info=True)
                flash('There was an error sending the password reset email. Please try again later or contact support.', 'danger')
        else:
            # To prevent email enumeration, show the same message whether the user exists or not.
            flash('If an account with that email exists, an email has been sent with instructions to reset your password.', 'info')

        return redirect(url_for('login'))

    return render_template('forgot_password.html', title='Forgot Password', form=form)

@app.route('/reset_password/<token>', methods=['GET', 'POST'])
def reset_token(token):
    if current_user.is_authenticated:
        return redirect(url_for('list_files'))
    user = User.verify_reset_token(token)
    if user is None:
        flash('That is an invalid or expired token.', 'warning')
        return redirect(url_for('forgot_password'))

    form = ResetPasswordForm()
    if form.validate_on_submit():
        user.set_password(form.password.data)
        db.session.commit()
        flash('Your password has been updated! You are now able to log in.', 'success')
        return redirect(url_for('login'))
    return render_template('reset_password.html', title='Reset Password', form=form, token=token)

@app.route('/profile/edit', methods=['GET', 'POST'])
@login_required
def edit_profile():
    form = EditProfileForm(original_username=current_user.username, original_email=current_user.email)
    if form.validate_on_submit():
        # Update user text data (username, email, bio, links...)
        current_user.username = form.username.data
        current_user.email = form.email.data
        current_user.bio = form.bio.data
        filename = None # Initialize filename
        if hasattr(current_user, 'github_url'): current_user.github_url = form.github_url.data
        if hasattr(current_user, 'spotify_url'): current_user.spotify_url = form.spotify_url.data
        if hasattr(current_user, 'youtube_url'): current_user.youtube_url = form.youtube_url.data
        if hasattr(current_user, 'twitter_url'): current_user.twitter_url = form.twitter_url.data
        if hasattr(current_user, 'steam_url'): current_user.steam_url = form.steam_url.data
        if hasattr(current_user, 'twitch_url'): current_user.twitch_url = form.twitch_url.data
        if hasattr(current_user, 'discord_server_url'): current_user.discord_server_url = form.discord_server_url.data
        if hasattr(current_user, 'reddit_url'): current_user.reddit_url = form.reddit_url.data

        # --- Profile Picture Processing ---
        if form.profile_picture.data:
            picture_file = form.profile_picture.data
            picture_path = None # Initialize path

            try:
                img = Image.open(picture_file)

                # --- Check if it's an animated GIF ---
                is_animated = getattr(img, 'is_animated', False)
                file_format = img.format # Get original format

                filename_base = secure_filename(str(current_user.id))
                static_profile_pics_path = os.path.join(app.root_path, 'static', 'uploads', 'profile_pics')
                os.makedirs(static_profile_pics_path, exist_ok=True)

                max_size = (256, 256) # Define your desired max dimensions

                if is_animated and file_format == 'GIF':
                    app.logger.info(f"Processing animated GIF for user {current_user.id}")
                    filename = f"{filename_base}.gif" # Save as GIF
                    picture_path = os.path.join(static_profile_pics_path, filename)

                    frames = []
                    duration = img.info.get('duration', 100) # Default duration per frame
                    loop = img.info.get('loop', 0) # Default loop count (0 means infinite)

                    for frame in ImageSequence.Iterator(img):
                        # Create a copy to resize
                        frame_copy = frame.copy()
                        # Convert palette ('P') or RGBA to RGB if needed for consistency before thumbnail?
                        # Often needed if saving palette-based GIFs gives issues. Test this.
                        if frame_copy.mode == 'P':
                           frame_copy = frame_copy.convert('RGBA') # Convert via RGBA often preserves palette better
                        if frame_copy.mode == 'RGBA':
                           frame_copy = frame_copy.convert('RGB') # Or handle transparency differently if needed

                        frame_copy.thumbnail(max_size, Image.Resampling.LANCZOS) # Use LANCZOS for better quality resize
                        frames.append(frame_copy)

                    if frames: # Ensure we have frames
                        # Save the sequence
                        frames[0].save(picture_path,
                                       format='GIF',
                                       save_all=True,
                                       append_images=frames[1:],
                                       duration=duration,
                                       loop=loop,
                                       optimize=False) # Optimize=False often more reliable for animated GIFs
                        app.logger.info(f"Saved resized animated GIF: {picture_path}")
                    else:
                         raise ValueError("Could not process frames from animated GIF.")

                else:
                    # --- Process as static image ---
                    app.logger.info(f"Processing static image (Format: {file_format}) for user {current_user.id}")
                    filename = f"{filename_base}.jpg" # Save static images as JPEG (or PNG)
                    picture_path = os.path.join(static_profile_pics_path, filename)

                    img.thumbnail(max_size, Image.Resampling.LANCZOS)

                    # Convert to RGB if necessary (for JPEG)
                    if img.mode in ("RGBA", "P"):
                        img = img.convert("RGB")

                    img.save(picture_path, format='JPEG', quality=85, optimize=True)
                    app.logger.info(f"Saved resized static image as JPEG: {picture_path}")

                # Update DB field *only if* processing and saving were successful
                if filename: # Check if filename was successfully set by processing
                    current_user.profile_picture_filename = filename

            except Exception as e:
                app.logger.error(f"Error processing profile picture for user {current_user.id}: {e}", exc_info=True)
                flash(f'Could not process the profile picture ({e}). Please try a different image.', 'danger')
                filename = None # Ensure filename isn't saved to DB on error
                # Optional: Delete partially saved file if it exists
                if picture_path and os.path.exists(picture_path):
                     try: os.remove(picture_path)
                     except OSError: pass

        # --- Commit DB Changes ---
        # This commits username, email, bio, links, and potentially profile_picture_filename
        try:
            db.session.commit()
            if filename: # Only flash success if PFP was part of the update
                 flash('Your profile (including picture) has been updated!', 'success')
            else: # Only text fields were updated
                 flash('Your profile has been updated!', 'success')
        except Exception as e:
             db.session.rollback()
             app.logger.error(f"Error committing profile update for user {current_user.id}: {e}", exc_info=True)
             flash('An error occurred saving your profile.', 'danger')

        return redirect(url_for('user_profile', username=current_user.username))

    # --- GET Request Logic ---
    elif request.method == 'GET':
        # (Populate form fields as before)
        form.username.data = current_user.username
        form.email.data = current_user.email
        form.bio.data = current_user.bio
        if hasattr(current_user, 'github_url'): form.github_url.data = current_user.github_url
        if hasattr(current_user, 'spotify_url'): form.spotify_url.data = current_user.spotify_url
        if hasattr(current_user, 'youtube_url'): form.youtube_url.data = current_user.youtube_url
        if hasattr(current_user, 'twitter_url'): form.twitter_url.data = current_user.twitter_url
        if hasattr(current_user, 'steam_url'): form.steam_url.data = current_user.steam_url
        if hasattr(current_user, 'twitch_url'): form.twitch_url.data = current_user.twitch_url
        if hasattr(current_user, 'discord_server_url'): form.discord_server_url.data = current_user.discord_server_url
        if hasattr(current_user, 'reddit_url'): form.reddit_url.data = current_user.reddit_url

    profile_picture_url = None
    if current_user.profile_picture_filename:
        profile_picture_url = url_for('static', filename=f'uploads/profile_pics/{current_user.profile_picture_filename}')

    return render_template('edit_profile.html', title='Edit Profile', form=form, profile_picture_url=profile_picture_url)

@app.route('/follow/<username>', methods=['POST'])
@login_required
def follow_user(username):
    user_to_follow = User.query.filter_by(username=username).first_or_404()
    if user_to_follow == current_user:
        flash('You cannot follow yourself!', 'warning')
        return redirect(url_for('user_profile', username=username))
    current_user.follow(user_to_follow)
    db.session.commit()
    flash(f'You are now following {username}.', 'success')
    return redirect(url_for('user_profile', username=username))

@app.route('/unfollow/<username>', methods=['POST'])
@login_required
def unfollow_user(username):
    user_to_unfollow = User.query.filter_by(username=username).first_or_404()
    if user_to_unfollow == current_user:
        flash('You cannot unfollow yourself!', 'warning') # Should not happen if UI is correct
        return redirect(url_for('user_profile', username=username))
    current_user.unfollow(user_to_unfollow)
    db.session.commit()
    flash(f'You have unfollowed {username}.', 'info')
    return redirect(url_for('user_profile', username=username))

@app.route('/user/<username>')
@login_required
def user_profile(username):
    user = User.query.filter_by(username=username).first_or_404()
    profile_picture_url = None
    if user.profile_picture_filename:
        profile_picture_url = url_for('static', filename=f'uploads/profile_pics/{user.profile_picture_filename}')

    # Member since calculation (keep existing)
    member_since_date = user.created_at.strftime("%B %d, %Y")
    now = datetime.utcnow()
    time_difference = now - user.created_at
    days = time_difference.days
    if days < 30: member_for = f"{days} day{'s' if days != 1 else ''}"
    elif days < 365: months = days // 30; member_for = f"{months} month{'s' if months != 1 else ''}"
    else: years = days // 365; member_for = f"{years} year{'s' if years != 1 else ''}"

    # --- MODIFIED: Query and paginate user's posts ---
    page = request.args.get('page', 1, type=int)
    sort_by = request.args.get('sort', 'recent_desc') # Default sort for profile posts
    comment_form = CommentForm() # Instantiate comment form

    # Base query for this user's posts
    query = Post.query.filter(Post.user_id == user.id) # Use the relationship backref

    # Apply sorting (similar to feed, but on user.posts)
    if sort_by == 'recent_desc':
        query = query.order_by(Post.timestamp.desc())
    elif sort_by == 'recent_asc':
        query = query.order_by(Post.timestamp.asc())
    elif sort_by == 'likes_desc':
        query = query.outerjoin(post_likes).group_by(Post.id).order_by(db.func.count(post_likes.c.user_id).desc(), Post.timestamp.desc())
    elif sort_by == 'comments_desc':
        query = query.outerjoin(Comment).group_by(Post.id).order_by(db.func.count(Comment.id).desc(), Post.timestamp.desc())
    elif sort_by == 'shares_desc':
        SharedPostAlias = aliased(Post, name='shares_alias')
        query = query.outerjoin(SharedPostAlias, Post.shares) \
                       .group_by(Post.id) \
                       .order_by(db.func.count(SharedPostAlias.id).desc(), Post.timestamp.desc())

    # ... add other sorting options if desired ...
    else: # Default
        query = query.order_by(Post.timestamp.desc())

    # Eager load relationships needed by the macro
    query = query.options(
        db.joinedload(Post.author).load_only(User.username, User.profile_picture_filename), # Already have user, but good practice
        db.joinedload(Post.comments).subqueryload(Comment.author).load_only(User.username, User.profile_picture_filename),
        db.joinedload(Post.likers).load_only(User.id),
        db.joinedload(Post.dislikers).load_only(User.id),
        db.joinedload(Post.original_post).joinedload(Post.author).load_only(User.username)
    )

    posts = query.paginate(page=page, per_page=10) # Paginate the user's posts
    # --- END MODIFIED ---

    return render_template('user_profile.html', title=f"{user.username}'s Profile",
                           user=user,
                           profile_picture_url=profile_picture_url,
                           member_since_date=member_since_date,
                           member_for=member_for,
                           posts=posts, # Pass paginated posts
                           current_sort=sort_by, # Pass current sort order
                           comment_form=comment_form, # Pass the form
                           csrf_token=generate_csrf) # Pass the function

@app.route('/post/<int:post_id>')
@login_required
def view_single_post(post_id):
    post = Post.query.options( # Eager load necessary data
        db.joinedload(Post.author).load_only(User.username, User.profile_picture_filename),
        db.joinedload(Post.comments).subqueryload(Comment.author).load_only(User.username, User.profile_picture_filename),
        db.joinedload(Post.likers).load_only(User.id),
        db.joinedload(Post.dislikers).load_only(User.id),
        db.joinedload(Post.original_post).joinedload(Post.author).load_only(User.username)
    ).get_or_404(post_id)

    comment_form = CommentForm()
    # You might want a dedicated template like 'view_single_post.html'
    # Or reuse the feed/profile template structure if it makes sense
    # For simplicity, let's reuse post_feed.html but only pass the single post
    # A better approach is a dedicated template.
    return render_template('view_single_post.html', # Create this template
                           title=f"Post by {post.author.username}",
                           post=post,
                           comment_form=comment_form,
                           csrf_token=generate_csrf)

@app.route('/post/new', methods=['GET', 'POST'])
@login_required
def create_post():
    form = CreatePostForm()
    # Fetch upload limits from settings for the template
    try:
        max_photo_mb = int(Setting.get('max_photo_upload_mb', str(DEFAULT_MAX_PHOTO_MB)))
    except (ValueError, TypeError):
        max_photo_mb = DEFAULT_MAX_PHOTO_MB
    try:
        max_video_mb = int(Setting.get('max_video_upload_mb', str(DEFAULT_MAX_VIDEO_MB)))
    except (ValueError, TypeError):
        max_video_mb = DEFAULT_MAX_VIDEO_MB

    if form.validate_on_submit():
        photo_fn = None
        video_fn = None
        upload_path = get_post_media_path() # Use helper function

        # --- Handle Photo Upload ---
        if form.photo.data:
            try:
                picture_file = form.photo.data
                # Add file size check here against max_photo_mb * 1024 * 1024
                # ...
                ext = os.path.splitext(secure_filename(picture_file.filename))[1]
                photo_fn = str(uuid.uuid4()) + ext
                picture_path = os.path.join(upload_path, photo_fn)
                # Add image processing/resizing if needed (like profile pics)
                picture_file.save(picture_path)
                app.logger.info(f"Post photo saved: {photo_fn}")
            except Exception as e:
                app.logger.error(f"Error uploading post photo: {e}", exc_info=True)
                flash("Error uploading photo.", "danger")
                photo_fn = None # Ensure it's None on error

        # --- Handle Video Upload ---
        if form.video.data and not photo_fn: # Only allow one media type for now
            try:
                video_file = form.video.data
                # Add file size check here against max_video_mb * 1024 * 1024
                # ...
                ext = os.path.splitext(secure_filename(video_file.filename))[1]
                video_fn = str(uuid.uuid4()) + ext
                video_path = os.path.join(upload_path, video_fn)
                video_file.save(video_path)
                app.logger.info(f"Post video saved: {video_fn}")
            except Exception as e:
                app.logger.error(f"Error uploading post video: {e}", exc_info=True)
                flash("Error uploading video.", "danger")
                video_fn = None # Ensure it's None on error
        elif form.video.data and photo_fn:
             flash("You can upload a photo OR a video, not both.", "warning")


        if not form.text_content.data and not photo_fn and not video_fn:
            flash('A post must have text, a photo, or a video.', 'warning')
        elif form.video.data and photo_fn:
             # Flash message already shown above, just prevent post creation
             pass
        else:
            try:
                post = Post(user_id=current_user.id,
                            text_content=form.text_content.data if form.text_content.data else None,
                            photo_filename=photo_fn,
                            video_filename=video_fn)
                db.session.add(post)
                db.session.commit()
                flash('Post created!', 'success')
                return redirect(url_for('user_profile', username=current_user.username)) # Redirect to profile after post
            except Exception as e:
                db.session.rollback()
                app.logger.error(f"Error saving post to DB: {e}", exc_info=True)
                flash("An error occurred while saving the post.", "danger")
                # Clean up saved files if DB commit fails
                if photo_fn and 'picture_path' in locals() and os.path.exists(picture_path): os.remove(picture_path)
                if video_fn and 'video_path' in locals() and os.path.exists(video_path): os.remove(video_path)


    # For GET request, or if form validation fails
    return render_template('create_post.html',
                            title='New Post',
                            form=form,
                            max_photo_upload_mb=max_photo_mb,
                            max_video_upload_mb=max_video_mb)

@app.route('/post/<int:post_id>/delete', methods=['POST'])
@login_required
def delete_post(post_id):
    post_to_delete = Post.query.get_or_404(post_id)

    # Check permissions:
    # User must be the author of the post OR an admin
    if not (post_to_delete.author == current_user or current_user.is_admin):
        flash('You do not have permission to delete this post.', 'danger')
        # Redirect to a relevant page, e.g., the post itself or the feed
        return redirect(request.referrer or url_for('post_feed'))

    try:
        # --- Delete Associated Media Files (if any) ---
        upload_path = get_post_media_path() # Your helper function for post media

        if post_to_delete.photo_filename:
            photo_path = os.path.join(upload_path, post_to_delete.photo_filename)
            if os.path.exists(photo_path):
                os.remove(photo_path)
                app.logger.info(f"Deleted post photo: {photo_path}")

        if post_to_delete.video_filename:
            video_path = os.path.join(upload_path, post_to_delete.video_filename)
            if os.path.exists(video_path):
                os.remove(video_path)
                app.logger.info(f"Deleted post video: {video_path}")

        # --- Delete Post from Database ---
        db.session.delete(post_to_delete)
        db.session.commit()
        flash('Post deleted successfully.', 'success')
        app.logger.info(f"Post ID {post_id} deleted by user {current_user.username} (Admin: {current_user.is_admin})")

    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Error deleting post {post_id}: {e}", exc_info=True)
        flash('An error occurred while deleting the post.', 'danger')

    # Redirect to the feed or the user's profile page after deletion
    return redirect(url_for('post_feed')) # Or perhaps url_for('user_profile', username=current_user.username)

@app.route('/post/<int:post_id>/like', methods=['POST'])
@login_required
def like_post(post_id):
    post = Post.query.get_or_404(post_id)
    # Prevent liking own post? Optional, depends on requirements.
    # if post.author == current_user:
    #     return jsonify({'status': 'error', 'message': 'You cannot like your own post.'}), 403

    action = 'liked' # Default action
    if current_user in post.dislikers: # If previously disliked, remove dislike first
        post.dislikers.remove(current_user)

    if current_user in post.likers:
        post.likers.remove(current_user)
        action = 'unliked'
    else:
        post.likers.append(current_user)
        # action remains 'liked'

    try:
        db.session.commit()
        # Use .count() for potentially better performance on large numbers
        like_count = db.session.query(post_likes).filter_by(post_id=post.id).count()
        dislike_count = db.session.query(post_dislikes).filter_by(post_id=post.id).count()
        return jsonify({
            'status': 'success',
            'action': action,
            'likes': like_count,
            'dislikes': dislike_count
        })
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Error liking post {post_id} for user {current_user.id}: {e}", exc_info=True)
        return jsonify({'status': 'error', 'message': 'Database error during like.'}), 500


# --- Post Feed ---
@app.route('/feed')
@login_required
def post_feed():
    page = request.args.get('page', 1, type=int)
    sort_by = request.args.get('sort', 'recent_desc') # Default sort
    comment_form = CommentForm() # Instantiate comment form

    followed_users_ids = [user.id for user in current_user.followed]
    # --- ADDED: Also include the current user's own posts in the feed ---
    followed_users_ids.append(current_user.id)
    # Remove duplicates if the user follows themselves
    followed_users_ids = list(set(followed_users_ids))
    # --- END ADDITION ---


    # Base query for posts from followed users and self
    query = Post.query.filter(Post.user_id.in_(followed_users_ids))

    # Apply sorting (ensure correct joins/counts for complex sorts)
    if sort_by == 'recent_desc':
        query = query.order_by(Post.timestamp.desc())
    elif sort_by == 'recent_asc':
        query = query.order_by(Post.timestamp.asc())
    elif sort_by == 'likes_desc':
        query = query.outerjoin(post_likes).group_by(Post.id).order_by(db.func.count(post_likes.c.user_id).desc(), Post.timestamp.desc())
    elif sort_by == 'likes_asc':
        query = query.outerjoin(post_likes).group_by(Post.id).order_by(db.func.count(post_likes.c.user_id).asc(), Post.timestamp.desc())
    elif sort_by == 'comments_desc':
        query = query.outerjoin(Comment).group_by(Post.id).order_by(db.func.count(Comment.id).desc(), Post.timestamp.desc())
    elif sort_by == 'comments_asc':
         query = query.outerjoin(Comment).group_by(Post.id).order_by(db.func.count(Comment.id).asc(), Post.timestamp.desc())
    elif sort_by == 'shares_desc':
        SharedPostAlias = aliased(Post, name='shares_alias')
        query = query.outerjoin(SharedPostAlias, Post.shares) \
                       .group_by(Post.id) \
                       .order_by(db.func.count(SharedPostAlias.id).desc(), Post.timestamp.desc())

    # ... other sort options ...
    else: # Default
        query = query.order_by(Post.timestamp.desc())

    # Eager load relationships for efficiency in the template macro
    query = query.options(
        db.joinedload(Post.author).load_only(User.username, User.profile_picture_filename),
        db.joinedload(Post.comments).subqueryload(Comment.author).load_only(User.username, User.profile_picture_filename),
        db.joinedload(Post.likers).load_only(User.id), # Only need ID to check if current_user liked
        db.joinedload(Post.dislikers).load_only(User.id), # Only need ID to check if current_user disliked
        db.joinedload(Post.original_post).joinedload(Post.author).load_only(User.username) # Load original post author if it's a share
    )

    posts = query.paginate(page=page, per_page=10) # Example pagination

    return render_template('post_feed.html',
                           title='My Feed',
                           posts=posts,
                           current_sort=sort_by,
                           comment_form=comment_form, # Pass the form
                           csrf_token=generate_csrf) # Pass the function to generate tokens


@app.route('/post/<int:post_id>/dislike', methods=['POST'])
@login_required
def dislike_post(post_id):
    post = Post.query.get_or_404(post_id)
    # Prevent disliking own post? Optional.
    # if post.author == current_user:
    #     return jsonify({'status': 'error', 'message': 'You cannot dislike your own post.'}), 403

    action = 'disliked' # Default action
    if current_user in post.likers: # If previously liked, remove like first
        post.likers.remove(current_user)

    if current_user in post.dislikers:
        post.dislikers.remove(current_user)
        action = 'undisliked'
    else:
        post.dislikers.append(current_user)
        # action remains 'disliked'

    try:
        db.session.commit()
        like_count = db.session.query(post_likes).filter_by(post_id=post.id).count()
        dislike_count = db.session.query(post_dislikes).filter_by(post_id=post.id).count()
        return jsonify({
            'status': 'success',
            'action': action,
            'likes': like_count,
            'dislikes': dislike_count
        })
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Error disliking post {post_id} for user {current_user.id}: {e}", exc_info=True)
        return jsonify({'status': 'error', 'message': 'Database error during dislike.'}), 500


@app.route('/post/<int:post_id>/comment', methods=['POST'])
@login_required
def add_comment_to_post(post_id):
    post = Post.query.get_or_404(post_id)
    # Use request.form for standard form submission, request.json for AJAX
    is_ajax = request.accept_mimetypes.accept_json and not request.accept_mimetypes.accept_html

    if is_ajax:
        data = request.get_json()
        if not data:
             return jsonify({'status': 'error', 'message': 'Invalid JSON data.'}), 400
        text_content = data.get('text_content')
    else: # Handle standard form submission
        form = CommentForm()
        if form.validate_on_submit():
            text_content = form.text_content.data
        else:
            # Handle form validation errors if needed, maybe flash messages
            flash('Comment could not be posted. Please check the content.', 'danger')
            return redirect(request.referrer or url_for('post_feed')) # Redirect back

    if not text_content or len(text_content.strip()) == 0:
        if is_ajax: return jsonify({'status': 'error', 'message': 'Comment text cannot be empty.'}), 400
        else: flash('Comment text cannot be empty.', 'warning'); return redirect(request.referrer or url_for('post_feed'))

    if len(text_content) > 1000: # Match form validator length
        if is_ajax: return jsonify({'status': 'error', 'message': 'Comment is too long.'}), 400
        else: flash('Comment is too long (max 1000 characters).', 'warning'); return redirect(request.referrer or url_for('post_feed'))

    try:
        comment = Comment(user_id=current_user.id, post_id=post.id, text_content=text_content.strip())
        db.session.add(comment)
        db.session.commit()
        app.logger.info(f"Comment {comment.id} added to post {post_id} by user {current_user.id}")

        if is_ajax:
            # Return the created comment data for dynamic insertion into the page
            return jsonify({
                'status': 'success',
                'message': 'Comment added.',
                'comment': {
                    'id': comment.id,
                    'text_content': comment.text_content,
                    'timestamp': comment.timestamp.isoformat() + 'Z',
                    'author_username': current_user.username,
                    'author_profile_pic': current_user.profile_picture_filename # Or full URL
                },
                'comment_count': len(post.comments) # Use len() for a list
            }), 201
        else:
             flash('Comment posted!', 'success')
             return redirect(request.referrer or url_for('post_feed'))

    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Error saving comment for post {post_id} by user {current_user.id}: {e}", exc_info=True)
        if is_ajax: return jsonify({'status': 'error', 'message': 'Could not save comment.'}), 500
        else: flash('Error saving comment.', 'danger'); return redirect(request.referrer or url_for('post_feed'))


# --- CORRECTED Share Post Route ---
@app.route('/post/<int:post_id>/share', methods=['POST'])
@login_required
def share_post(post_id):
    # Correctly fetch the original post using its ID
    original_post = Post.query.get_or_404(post_id) # Use post_id from the route

    if original_post.author == current_user:
        return jsonify({'status': 'error', 'message': 'You cannot share your own post directly this way (already on your profile).'}), 400

    # Check if this user has already shared this specific original post
    existing_share = Post.query.filter_by(user_id=current_user.id, original_post_id=original_post.id).first()
    if existing_share:
        return jsonify({'status': 'info', 'message': 'You have already shared this post.'}), 200

    # Create a new post that is a "share" of the original_post
    shared_post = Post(
        user_id=current_user.id,
        original_post_id=original_post.id, # Link to the original post
        # text_content for the share itself can be None, or you can add a form field for the user to add their own text to the share
        # photo_filename and video_filename for the share itself are None, as it's sharing the original's media
    )
    db.session.add(shared_post)
    db.session.commit()

    return jsonify({
        'status': 'success',
        'message': 'Post shared successfully!',
        'share_count': original_post.shares.count() # Count shares of the original post
    }), 201
# --- END CORRECTED Share Post Route ---


# --- Utility Function to Create Database ---
def create_db(app_instance):
    """
    Creates instance folder, upload folder, database tables, and seeds essential settings.
    This function is designed to be idempotent.
    """
    with app_instance.app_context():
        # --- 1. Ensure Folders Exist ---
        try:
            # Instance folder
            if not os.path.exists(app_instance.instance_path):
                os.makedirs(app_instance.instance_path)
                app_instance.logger.info(f"Created instance folder: {app_instance.instance_path}")

            # Upload folder (defined in app.config)
            upload_folder_path = app_instance.config.get('UPLOAD_FOLDER')
            if not upload_folder_path:
                # Fallback if UPLOAD_FOLDER is not in config for some reason during early init
                upload_folder_path = os.path.join(app_instance.instance_path, 'uploads')
                app_instance.config['UPLOAD_FOLDER'] = upload_folder_path # Ensure it's set
                app_instance.logger.warning(f"UPLOAD_FOLDER not in app.config, using default: {upload_folder_path}")

            if not os.path.exists(upload_folder_path):
                os.makedirs(upload_folder_path)
                app_instance.logger.info(f"Created base upload folder: {upload_folder_path}")

            # --- ADDED: Ensure post media folder exists ---
            post_media_folder_path = app_instance.config.get('POST_MEDIA_FOLDER')
            if not post_media_folder_path:
                post_media_folder_path = os.path.join(app_instance.instance_path, 'uploads', 'post_media')
                app_instance.config['POST_MEDIA_FOLDER'] = post_media_folder_path
                app_instance.logger.warning(f"POST_MEDIA_FOLDER not in app.config, using default: {post_media_folder_path}")

            if not os.path.exists(post_media_folder_path):
                os.makedirs(post_media_folder_path)
                app_instance.logger.info(f"Created post media folder: {post_media_folder_path}")
            # --- END ADDED ---

        except OSError as e:
            app_instance.logger.error(f"OSError creating instance or upload folders: {e}", exc_info=True)
            # Depending on severity, you might want to raise the error or exit
            # For now, we'll log and continue, as DB creation might still be possible
            # if instance_path itself is writable.

        # --- 2. Database URI and Path ---
        # Ensure the DB is in the instance folder for portability and security
        db_path_in_instance = os.path.join(app_instance.instance_path, DB_NAME) # DB_NAME should be a global constant

        # Crucially update the app's config if it's not already pointing to the instance path
        # This ensures SQLAlchemy uses the correct path, especially if create_db is called early.
        expected_db_uri = f'sqlite:///{db_path_in_instance}'
        if app_instance.config.get('SQLALCHEMY_DATABASE_URI') != expected_db_uri:
            app_instance.config['SQLALCHEMY_DATABASE_URI'] = expected_db_uri
            app_instance.logger.info(f"Updated SQLALCHEMY_DATABASE_URI to: {expected_db_uri}")
            # Re-initialize db with the app if it was initialized before this config change
            # This depends on how `db` is initialized. If `db = SQLAlchemy()` then `db.init_app(app_instance)`
            # If `db = SQLAlchemy(app_instance)`, this update should be fine.

        db_exists = os.path.exists(db_path_in_instance)

        # --- 3. Create Tables if Database is New ---
        if not db_exists:
            app_instance.logger.info(f"Database file not found at {db_path_in_instance}. Creating database and all tables...")
            try:
                db.create_all() # `db` is your SQLAlchemy instance
                app_instance.logger.info("Database and tables created successfully.")
                # After creating tables, we will proceed to seed all settings.
            except Exception as e:
                db.session.rollback()
                app_instance.logger.error(f"Failed to create database/tables: {e}", exc_info=True)
                return # Stop if DB creation fails
        else:
            app_instance.logger.info(f"Database file found at {db_path_in_instance}. Checking structure and settings...")
            # If DB exists, still run create_all() - it's safe and creates missing tables.
            try:
                db.create_all()
                app_instance.logger.info("db.create_all() run on existing database (creates missing tables if any).")
            except Exception as e:
                app_instance.logger.error(f"Error running db.create_all() on existing database: {e}", exc_info=True)
                # Continue to settings check even if this fails, as tables might mostly be okay.

        # --- 4. Seed/Verify Essential Settings ---
        app_instance.logger.info("Verifying and seeding essential application settings...")
        settings_changed_in_db = False
        try:
            for key, default_value in DEFAULT_SETTINGS.items():
                # Setting.get() is assumed to work correctly within app_context
                current_value = Setting.get(key)
                if current_value is None:
                    app_instance.logger.info(f"Setting '{key}' not found. Seeding with default: '{default_value}'.")
                    Setting.set(key, default_value) # Setting.set() handles add/update
                    settings_changed_in_db = True

            if settings_changed_in_db:
                db.session.commit()
                app_instance.logger.info("Committed new/updated default settings to the database.")
            else:
                app_instance.logger.info("All essential settings are already present in the database.")

        except Exception as e:
            db.session.rollback()
            app_instance.logger.error(f"Error verifying/seeding settings: {e}", exc_info=True)

        # --- 5. (Optional) Further Schema/Column Checks for Existing DBs ---
        # This part can be extensive. For now, db.create_all() handles missing tables.
        # If you need to check for missing columns in *existing* tables,
        # you'd use SQLAlchemy's inspection tools (inspector.get_columns),
        # which is more advanced and often handled by migration tools like Alembic in larger apps.
        # For simplicity in this context, we rely on db.create_all() for table presence
        # and assume model definitions are the source of truth for columns in new tables.

        app_instance.logger.info("Database initialization and settings check complete.")


class OllamaChatMessage(db.Model):
    """Model for storing individual ollama chat messages per user."""
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    role = db.Column(db.String(10), nullable=False) # 'user' or 'assistant'
    content = db.Column(db.Text, nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)

    # Add relationship back to User (optional but useful)
    # The backref allows accessing messages via user.ollama_chat_messages
    user = db.relationship('User', backref=db.backref('ollama_chat_messages', lazy='dynamic', order_by='OllamaChatMessage.timestamp', cascade="all, delete-orphan"))

    def __repr__(self):
        return f'<OllamaChatMessage {self.id} (User: {self.user_id}, Role: {self.role})>'

    # Helper to convert DB object to the dictionary format Ollama/template expects
    def to_dict(self):
        return {
            "role": self.role,
            "content": self.content,
            "timestamp": self.timestamp.isoformat() + 'Z' if self.timestamp else None
        }

class OllamaChatForm(FlaskForm):
    message = TextAreaField('You: ', validators=[DataRequired(), Length(max=4000)])
    submit = SubmitField('Send')

def send_message_to_ollama(prompt, history_list):
    """
    Sends a prompt and history list to the configured Ollama API.
    Returns the AI response content string or None if error, plus an error message string or None.
    """
    ollama_url = Setting.get('ollama_api_url')
    ollama_model = Setting.get('ollama_model')

    if not ollama_url or not ollama_model:
        app.logger.warning("Ollama URL or model not configured in settings.")
        return None, "Ollama integration is not configured in Admin Settings." # Correct: 2 values

    api_endpoint = ollama_url.rstrip('/') + '/api/chat'
    messages = list(history_list)
    messages.append({"role": "user", "content": prompt})

    payload = {
        "model": ollama_model,
        "messages": messages,
        "stream": False
    }

    try:
        response = requests.post(api_endpoint, json=payload, timeout=60)
        response.raise_for_status()
        response_data = response.json()

        if response_data and 'message' in response_data and 'content' in response_data['message']:
             ai_response_content = response_data['message']['content']
             return ai_response_content, None # Correct: 2 values (content, no error)
        else:
             app.logger.error(f"Unexpected Ollama response format: {response_data}")
             return None, "Received an unexpected response format from Ollama." # Correct: 2 values

    except requests.exceptions.ConnectionError as e:
        app.logger.error(f"Ollama connection error: {e}", exc_info=True)
        # FIX HERE: Return only 2 values
        return None, f"Could not connect to Ollama API at {ollama_url}. Is it running?"
    except requests.exceptions.Timeout:
         app.logger.error(f"Ollama request timed out to {api_endpoint}")
         # FIX HERE: Return only 2 values
         return None, "The request to Ollama timed out."
    except requests.exceptions.RequestException as e:
        app.logger.error(f"Ollama request failed: {e}", exc_info=True)
        error_detail = f"Error: {e}."
        if e.response is not None:
             try:
                 error_detail += f" Response: {e.response.text}"
             except Exception:
                 pass
        # FIX HERE: Return only 2 values
        return None, f"Failed to communicate with Ollama API. {error_detail}"
    except Exception as e:
        app.logger.error(f"Unexpected error calling Ollama: {e}", exc_info=True)
        # FIX HERE: Return only 2 values
        return None, "An unexpected error occurred while contacting the AI."

class GroupChatForm(FlaskForm):
    """Form for sending group chat messages."""
    content = TextAreaField('Message', validators=[Length(max=4000)]) # Max length, but not strictly required
    # Add file size validation potentially using custom validator or checking in route
    file = FileField('Attach File', validators=[Optional()]) # File upload is optional
    submit = SubmitField('Send')

class GroupChatMessage(db.Model):
    """Model for storing group chat messages."""
    __tablename__ = 'group_chat_message' # Explicit table name is good practice
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=False, index=True) # Added ondelete
    timestamp = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)
    content = db.Column(db.Text, nullable=True) # Text content of the message
    file_id = db.Column(db.Integer, db.ForeignKey('file.id', ondelete='SET NULL'), nullable=True, index=True) # Added ondelete, allows keeping file if msg deleted
    edited_at = db.Column(db.DateTime, nullable=True)
    is_deleted = db.Column(db.Boolean, default=False, nullable=False, index=True)
    deleted_at = db.Column(db.DateTime, nullable=True, index=True)

    # Relationships
    # Use explicit foreign_keys for clarity, especially with multiple FKs to User potentially
    sender = db.relationship('User',
                             foreign_keys=[user_id],
                             backref=db.backref('group_chat_messages',
                                                lazy='dynamic',
                                                order_by='GroupChatMessage.timestamp',
                                                cascade="all, delete-orphan")) # Cascade delete messages if user is deleted

    # Use lazy='joined' to potentially reduce queries when accessing file info often
    shared_file = db.relationship('File',
                                  foreign_keys=[file_id],
                                  backref=db.backref('group_chat_shares',
                                                     lazy='joined',
                                                     uselist=False), # One message <-> One file (optional)
                                  single_parent=True, # Ensures file_id is cleared if message is deleted
                                  post_update=True) # Helps with ordering updates

    def __repr__(self):
        file_info = f", FileID: {self.file_id}" if self.file_id else ""
        return f'<GroupChatMessage {self.id} (User: {self.user_id}{file_info})>'

    def to_dict(self, include_sender=True, include_file=True):
        """Helper to convert message to dictionary for JSON responses/template."""
        sender_username = None
        sender_profile_pic = None # Initialize profile pic filename as None
        if include_sender and self.sender:
            sender_username = self.sender.username
            sender_profile_pic = self.sender.profile_picture_filename

        data = {
            'id': self.id,
            'user_id': self.user_id,
            'timestamp': self.timestamp.isoformat() + 'Z', # ISO format with Z for UTC is standard
            'content': self.content,
            'file_id': self.file_id,
            'sender_username': self.sender.username if include_sender and self.sender else None,
            'sender_profile_picture_filename': sender_profile_pic,
            'shared_file': None, # Initialize as None
            'is_edited': bool(self.edited_at),
            'is_deleted': self.is_deleted,
            'edited_at': self.edited_at.isoformat() + 'Z' if self.edited_at else None
        }

        if include_file and self.shared_file:
            file_data = {
                'id': self.shared_file.id,
                'original_filename': self.shared_file.original_filename,
                'mime_type': self.shared_file.mime_type,
                'filesize': self.shared_file.filesize,
                'is_editable': is_file_editable(self.shared_file.original_filename, self.shared_file.mime_type),
                'view_url': url_for('view_file', file_id=self.shared_file.id, _external=False) if self.shared_file.mime_type in app.config.get('VIEWABLE_MIMES', {}) else None,
                'download_url': url_for('download_file', file_id=self.shared_file.id, _external=False)
            }

            # Add text file preview content only if it's a text file
            if self.shared_file.mime_type == 'text/plain':
                try:
                    # Ensure the file owner's ID is used for the path
                    file_path = os.path.join(get_user_upload_path(self.shared_file.user_id), self.shared_file.stored_filename)
                    if os.path.exists(file_path):
                         # Use codecs for reliable encoding handling
                         with codecs.open(file_path, 'r', encoding='utf-8', errors='replace') as f:
                            # Read a bit more to check if there's content beyond the preview limit
                            content_plus_one = f.read(501)
                            preview_content = content_plus_one[:500]
                            file_data['preview_content'] = preview_content
                            file_data['has_more_content'] = len(content_plus_one) > 500
                    else:
                        app.logger.warning(f"Physical file not found for txt preview: {file_path} (File ID: {self.shared_file.id})")
                        file_data['preview_content'] = "[Preview unavailable: File missing]"
                        file_data['has_more_content'] = False
                except Exception as e:
                    app.logger.warning(f"Could not read preview for txt file {self.shared_file.id}: {e}")
                    file_data['preview_content'] = "[Error reading preview]"
                    file_data['has_more_content'] = False

            data['shared_file'] = file_data # Assign the populated file_data dict

        return data

# --- Update URI config *after* create_db definition ---
# This ensures the app object uses the correct path when create_db is called below
app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{os.path.join(INSTANCE_FOLDER_PATH, DB_NAME)}'


# --- Run Application ---
if __name__ == '__main__':
    create_db(app)
    configure_mail_from_db(app)
    mail.init_app(app)
    app.run(debug=True, host='0.0.0.0', port=8080)
