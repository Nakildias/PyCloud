import os
import uuid
from datetime import timedelta
import json
import logging
import sqlalchemy as sa
from wtforms import BooleanField
from datetime import datetime
from sqlalchemy.orm import relationship, backref
from wtforms import TextAreaField
from flask import abort
from flask_wtf.csrf import CSRFProtect
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
from wtforms.validators import Optional
from flask import (Flask, render_template, redirect, url_for, flash, request, session, jsonify, current_app)
from flask_sqlalchemy import SQLAlchemy
from flask_login import (LoginManager, UserMixin, login_user, logout_user, login_required, current_user)
from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, SubmitField, BooleanField, EmailField
from wtforms.validators import DataRequired, Length, Email, EqualTo, ValidationError
from werkzeug.security import generate_password_hash, check_password_hash

# --- Basic Logging Setup ---
logging.basicConfig(level=logging.INFO) # Log informational messages and above

# --- Configuration ---
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DB_NAME = 'database.db'
INSTANCE_FOLDER_PATH = os.path.join(BASE_DIR, 'instance')
UPLOAD_FOLDER = os.path.join(INSTANCE_FOLDER_PATH, 'uploads')


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
# Increase max content length for uploads (e.g., 100 MB) - adjust as needed
app.config['MAX_CONTENT_LENGTH'] = 1 * 1024 * 1024 * 1024 # 100 Megabytes
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER # Store path for reference if needed
csrf = CSRFProtect(app)
app.config['SECRET_KEY'] = os.urandom(24) # Replace with a static key for production
app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{os.path.join(BASE_DIR, DB_NAME)}'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=7)
app.config['VIEWABLE_MIMES'] = VIEWABLE_MIMES
app.config['EDITABLE_EXTENSIONS'] = EDITABLE_EXTENSIONS

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
    except Exception as e:
        # Handle cases where DB might not be ready yet during initial setup/errors
        app.logger.error(f"Error injecting settings into context: {e}")
        settings_dict['allow_registration'] = True # Default fallback

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
    folders = db.relationship('Folder',
                              foreign_keys='Folder.user_id', # Specify FK for user relationship
                              backref='owner',
                              lazy='dynamic',
                              cascade="all, delete-orphan")

    def set_password(self, password):
        """Hashes and sets the user's password."""
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        """Checks if the provided password matches the stored hash."""
        return check_password_hash(self.password_hash, password)

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
    # --- END ADD ---
    submit = SubmitField('Save Settings')

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
        return redirect(url_for('list_files'))

    form = AdminSettingsForm()
    DEFAULT_MAX_UPLOAD_MB = 100 # Default if setting is missing

    if form.validate_on_submit():
        # --- POST Request ---
        try:
            allow_reg_val = str(form.allow_registration.data).lower()
            limit_val = str(form.default_storage_limit_mb.data)
            max_upload_val_from_form = form.max_upload_size_mb.data # Get integer from form

            # --- Logging before save ---
            app.logger.info(f"Admin settings POST: Attempting to save max_upload_size_mb = {max_upload_val_from_form} (Type: {type(max_upload_val_from_form)})")

            # Convert to string for saving
            max_upload_val_to_save = str(max_upload_val_from_form)
            Setting.set('allow_registration', allow_reg_val)
            Setting.set('default_storage_limit_mb', limit_val)
            Setting.set('max_upload_size_mb', max_upload_val_to_save) # Save as string

            db.session.commit()
            flash('Settings updated successfully!', 'success')
            app.logger.info(f"Admin settings saved successfully by {current_user.username}. max_upload now set to '{max_upload_val_to_save}' in DB.")
            return redirect(url_for('admin_settings'))
        except Exception as e:
            db.session.rollback()
            app.logger.error(f"Error updating settings by {current_user.username}: {e}", exc_info=True)
            flash('Failed to update settings.', 'danger')

    elif request.method == 'GET':
        # --- GET Request ---
        # Populate allow_registration
        allow_reg_current = Setting.get('allow_registration', 'true')
        form.allow_registration.data = (allow_reg_current == 'true')

        # Populate default_storage_limit_mb
        try:
            default_limit_current_str = Setting.get('default_storage_limit_mb', '1024')
            form.default_storage_limit_mb.data = int(default_limit_current_str)
        except (ValueError, TypeError):
             app.logger.warning(f"Invalid default_storage_limit_mb value in settings: '{default_limit_current_str}'. Setting form field to 1024.")
             form.default_storage_limit_mb.data = 1024

        # Populate max_upload_size_mb
        try:
            # --- Logging before reading ---
            max_upload_current_str = Setting.get('max_upload_size_mb') # Try reading without default first
            app.logger.info(f"Admin settings GET: Reading 'max_upload_size_mb' from DB. Raw value = '{max_upload_current_str}' (Type: {type(max_upload_current_str)})")

            if max_upload_current_str is None:
                 app.logger.info(f"Admin settings GET: 'max_upload_size_mb' not found in DB. Using default {DEFAULT_MAX_UPLOAD_MB}.")
                 form.max_upload_size_mb.data = DEFAULT_MAX_UPLOAD_MB
            else:
                 form.max_upload_size_mb.data = int(max_upload_current_str) # Convert DB string value to int for form
                 app.logger.info(f"Admin settings GET: Populating form with {form.max_upload_size_mb.data} from DB value '{max_upload_current_str}'.")

        except (ValueError, TypeError):
             app.logger.warning(f"Invalid max_upload_size_mb value '{max_upload_current_str}' found in settings. Setting form field to default {DEFAULT_MAX_UPLOAD_MB}.")
             form.max_upload_size_mb.data = DEFAULT_MAX_UPLOAD_MB # Fallback for display on error

    # Render the template
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


    # === CHECK 2: Against Admin-Defined Limit (Database Setting) ===
    admin_limit_mb = 100 # Default fallback
    try:
        max_upload_mb_str = Setting.get('max_upload_size_mb', str(admin_limit_mb))
        admin_limit_mb = int(max_upload_mb_str)
        if admin_limit_mb <= 0: # Treat 0 or negative as fallback default
             admin_limit_mb = 100
             app.logger.warning(f"Invalid admin max_upload_size_mb setting '{max_upload_mb_str}'. Using fallback {admin_limit_mb}MB.")

    except (ValueError, TypeError):
        app.logger.error(f"Invalid max_upload_size_mb setting '{max_upload_mb_str}'. Using fallback {admin_limit_mb}MB.")

    admin_limit_bytes = admin_limit_mb * 1024 * 1024
    if uploaded_filesize > admin_limit_bytes:
        message = f'Upload failed: File size ({uploaded_filesize / (1024*1024):.1f} MB) exceeds the allowed upload limit ({admin_limit_mb} MB).'
        app.logger.warning(f"Upload rejected for user {current_user.id}: File size {uploaded_filesize} > Admin limit {admin_limit_bytes}")
        if is_ajax: return jsonify({"status": "error", "message": message}), 413 # Payload Too Large
        else: flash(message, 'danger'); return redirect(redirect_url)


    # === CHECK 3: Against User's Available Storage Space ===
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
    """Handles downloading a specific file."""
    file_record = File.query.get_or_404(file_id)

    # Verify ownership
    if file_record.owner != current_user:
        app.logger.warning(f"User {current_user.id} attempted download of file {file_id} owned by {file_record.user_id}")
        abort(403) # Forbidden

    user_upload_path = get_user_upload_path(current_user.id)

    try:
        return send_from_directory(user_upload_path,
                                   file_record.stored_filename,
                                   as_attachment=True,
                                   download_name=file_record.original_filename) # Send with original name
    except FileNotFoundError:
        app.logger.error(f"File not found on disk for record {file_id}: {file_record.stored_filename} in {user_upload_path}")
        abort(404) # Or flash an error and redirect
    except Exception as e:
        app.logger.error(f"Error downloading file {file_id} for user {current_user.id}: {e}", exc_info=True)
        flash("An error occurred while trying to download the file.", "danger")
        return redirect(url_for('list_files'))

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
        return jsonify({"status": "success", "message": f"Folder '{folder_name}' and all its contents deleted successfully."})

    except Exception as e:
        # If any error occurred during recursion or commit, rollback everything
        db.session.rollback()
        app.logger.error(f"Failed to delete folder {folder_id} ('{folder_name}') for user {current_user.id}: {e}", exc_info=True)
        # *** CHANGED: Return JSON error ***
        return jsonify({"status": "error", "message": f"Error deleting folder '{folder_name}'."}), 500

    # Removed: flash(...)
    # Removed: return redirect(...)

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
    """Serves a file for inline viewing if possible."""
    file_record = File.query.get_or_404(file_id)

    # 1. Verify Ownership
    if file_record.owner != current_user:
        app.logger.warning(f"User {current_user.id} attempted unauthorized view of file {file_id} owned by {file_record.user_id}")
        abort(403) # Forbidden

    # 2. Get path info
    user_upload_path = get_user_upload_path(current_user.id)
    stored_filename = file_record.stored_filename
    mime_type = file_record.mime_type or 'application/octet-stream' # Default if missing

    # Check if file exists physically
    full_file_path = os.path.join(user_upload_path, stored_filename)
    if not os.path.exists(full_file_path):
         app.logger.error(f"File not found on disk for viewing record {file_id}: {stored_filename} in {user_upload_path}")
         abort(404)

    try:
        # 3. Serve the file inline
        # as_attachment=False is the default, but be explicit.
        # conditional=True allows caching and 304 Not Modified responses.
        # explicitly providing mimetype ensures browser handles it correctly.
        return send_from_directory(user_upload_path,
                                   stored_filename,
                                   mimetype=mime_type,
                                   as_attachment=False,
                                   conditional=True)
    except Exception as e:
        app.logger.error(f"Error serving file {file_id} for viewing by user {current_user.id}: {e}", exc_info=True)
        # Return a generic error page or message
        return "Error serving file.", 500

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


# --- Utility Function to Create Database ---
def create_db(app_instance):
    """Creates instance folder, upload folder, DB tables, and seeds settings."""
    DEFAULT_STORAGE_LIMIT_MB = 1024 # 1 GB

    with app_instance.app_context():
        # --- Ensure Instance and Upload Folders Exist ---
        try:
            if not os.path.exists(app_instance.instance_path):
                os.makedirs(app_instance.instance_path)
                app.logger.info(f"Created instance folder: {app_instance.instance_path}")
            upload_folder_path = app.config.get('UPLOAD_FOLDER', UPLOAD_FOLDER) # Get path from config
            if not os.path.exists(upload_folder_path):
                os.makedirs(upload_folder_path)
                app.logger.info(f"Created base upload folder: {upload_folder_path}")
        except OSError as e:
            app.logger.error(f"Error creating instance or upload folders: {e}", exc_info=True)
            # Consider how critical this is - maybe raise the error?

        # --- Database Checks ---
        db_path = os.path.join(app_instance.instance_path, DB_NAME) # DB should be in instance folder
        app_instance.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{db_path}' # Update URI to use instance path

        db_exists = os.path.exists(db_path)

        if not db_exists:
            app.logger.info(f"Database file not found at {db_path}. Creating database and all tables...")
            try:
                db.create_all()
                app.logger.info("Database and tables created successfully.")

                # --- Safer Initial Seeding ---
                app.logger.info("Seeding initial settings...")
                settings_to_add = []
                # Check and add allow_registration
                if not Setting.query.filter_by(key='allow_registration').first():
                    settings_to_add.append(Setting(key='allow_registration', value='true'))
                # Check and add default_storage_limit_mb
                if not Setting.query.filter_by(key='default_storage_limit_mb').first():
                    settings_to_add.append(Setting(key='default_storage_limit_mb', value=str(DEFAULT_STORAGE_LIMIT_MB)))

                if settings_to_add:
                    db.session.add_all(settings_to_add)
                    db.session.commit()
                    app.logger.info(f"Initial settings seeded: {[s.key for s in settings_to_add]}")
                else:
                    app.logger.info("Essential settings already exist, skipping initial seed.")
                    db.session.rollback()

            except Exception as e:
                db.session.rollback()
                app.logger.error(f"Failed to create database/tables/seed settings: {e}", exc_info=True)
        else:
            # Database exists, check tables and ensure essential settings are present
            app.logger.info(f"Database file found at {db_path}. Checking structure...")
            try:
                inspector = db.inspect(db.engine)
                all_tables = inspector.get_table_names()
                required_tables = {
                    User.__tablename__: ['storage_limit_mb'],
                    Setting.__tablename__: [],
                    Note.__tablename__: [],
                    Folder.__tablename__: ['parent_folder_id'], # Check new Folder table
                    File.__tablename__: ['parent_folder_id', 'is_public', 'public_id', 'public_password_hash'], # <-- Check new column
                }

                # Check for missing tables
                missing_tables = [tbl for tbl in required_tables if tbl not in all_tables]
                if missing_tables:
                     app.logger.warning(f"Missing tables found: {missing_tables}. Attempting creation...")
                     db.create_all() # Try creating only missing tables

                # Check for missing columns in existing tables
                for table_name, req_columns in required_tables.items():
                    if table_name in all_tables: # Only check if table exists
                        columns = [c['name'] for c in inspector.get_columns(table_name)]
                        for req_col in req_columns:
                            if req_col not in columns:
                                app.logger.critical(f"CRITICAL: Column '{req_col}' missing from '{table_name}'.")
                                app.logger.critical("ALERT: Database schema mismatch. For dev, DELETE '{db_path}' and restart. For prod, use migrations.")
                                # In a real app, you might raise an error or exit here

                # Check and seed essential settings if missing
                settings_to_commit = False
                if Setting.get('allow_registration') is None:
                    app.logger.warning("Setting 'allow_registration' missing. Seeding default ('true').")
                    Setting.set('allow_registration', 'true')
                    settings_to_commit = True
                if Setting.get('default_storage_limit_mb') is None:
                     app.logger.warning(f"Setting 'default_storage_limit_mb' missing. Seeding default ('{DEFAULT_STORAGE_LIMIT_MB}').")
                     Setting.set('default_storage_limit_mb', str(DEFAULT_STORAGE_LIMIT_MB))
                     settings_to_commit = True

                if settings_to_commit:
                    db.session.commit()

                app.logger.info("Database structure and settings checks complete.")

            except Exception as e:
                db.session.rollback()
                app.logger.error(f"Error inspecting database or ensuring settings: {e}", exc_info=True)

# --- Update URI config *after* create_db definition ---
# This ensures the app object uses the correct path when create_db is called below
app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{os.path.join(INSTANCE_FOLDER_PATH, DB_NAME)}'


# --- Run Application ---
if __name__ == '__main__':
    create_db(app)
    app.run(debug=False, host='127.0.0.1', port=8080)
