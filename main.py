import os
import uuid
from datetime import timedelta
import json
import logging
import sqlalchemy as sa
from sqlalchemy import or_
from wtforms import BooleanField
from datetime import datetime, timezone, timedelta
from sqlalchemy.orm import relationship, Mapped, mapped_column, backref, aliased
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
from wtforms import URLField, SelectField
from wtforms.validators import URL
from werkzeug.exceptions import BadRequest
import shutil
import zipfile
import mimetypes
import codecs
from sqlalchemy.exc import IntegrityError
from wtforms.validators import Optional, InputRequired
from flask import (Flask, render_template, redirect, url_for, flash, request, session, jsonify, current_app, make_response, abort, g, send_file, Response)
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import Table, Column, Integer, ForeignKey, String, Text, DateTime, Boolean, inspect
from git import Repo as PyGitRepo, InvalidGitRepositoryError, NoSuchPathError
from flask_login import (LoginManager, UserMixin, login_user, logout_user, login_required, current_user)
from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, SubmitField, BooleanField, EmailField
from wtforms.validators import DataRequired, Length, Email, EqualTo, ValidationError
from werkzeug.security import generate_password_hash, check_password_hash
from itsdangerous import URLSafeTimedSerializer
from flask_mail import Mail
from flask_mail import Message
from PIL import Image, ImageSequence
import subprocess
from pathlib import Path
import tempfile
import math
from humanize import naturaltime
from wtforms import TextAreaField, StringField as WTStringField # Renaming to avoid conflict if StringField is used differently
from wtforms.validators import DataRequired as WTDataRequired, Length as WTLength
import markdown # For Markdown to HTML conversion
from markupsafe import Markup # To mark HTML as safe for Jinja
from flask_migrate import Migrate # Import Migrate
from flask_socketio import SocketIO, emit
import paramiko
import threading
import time
import select
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
app.config['SECRET_KEY'] = os.urandom(24)
app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{os.path.join(BASE_DIR, DB_NAME)}'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=7)
app.config['VIEWABLE_MIMES'] = VIEWABLE_MIMES
app.config['EDITABLE_EXTENSIONS'] = EDITABLE_EXTENSIONS
app.config['GIT_REPOSITORIES_ROOT'] = os.path.join(app.instance_path, "git_repositories") # Store in instance folder
app.config['GIT_EXECUTABLE_PATH'] = "git" # Or specify full path if not in system PATH

mail = Mail(app)
# --- Database Setup ---
db = SQLAlchemy(app)
migrate = Migrate(app, db) # Initialize Migrate

followers = db.Table('followers', db.metadata,
    db.Column('follower_id', db.Integer, db.ForeignKey('user.id', name='fk_followers_follower_id', ondelete='CASCADE'), primary_key=True),
    db.Column('followed_id', db.Integer, db.ForeignKey('user.id', name='fk_followers_followed_id', ondelete='CASCADE'), primary_key=True),
    extend_existing=True  # Add this
)

post_likes = db.Table('post_likes', db.metadata,
    db.Column('user_id', db.Integer, db.ForeignKey('user.id', name='fk_post_likes_user_id', ondelete='CASCADE'), primary_key=True),
    db.Column('post_id', db.Integer, db.ForeignKey('post.id', name='fk_post_likes_post_id', ondelete='CASCADE'), primary_key=True),
    extend_existing=True  # Add this
)

post_dislikes = db.Table('post_dislikes', db.metadata,
    db.Column('user_id', db.Integer, db.ForeignKey('user.id', name='fk_post_dislikes_user_id', ondelete='CASCADE'), primary_key=True),
    db.Column('post_id', db.Integer, db.ForeignKey('post.id', name='fk_post_dislikes_post_id', ondelete='CASCADE'), primary_key=True),
    extend_existing=True  # Add this
)

comment_likers = db.Table('comment_likers', db.metadata,
    db.Column('user_id', db.Integer, db.ForeignKey('user.id', name='fk_comment_likers_user_id', ondelete='CASCADE'), primary_key=True),
    db.Column('comment_id', db.Integer, db.ForeignKey('comment.id', name='fk_comment_likers_comment_id', ondelete='CASCADE'), primary_key=True),
    extend_existing=True  # Add this
)

comment_dislikers = db.Table('comment_dislikers', db.metadata,
    db.Column('user_id', db.Integer, db.ForeignKey('user.id', name='fk_comment_dislikers_user_id', ondelete='CASCADE'), primary_key=True),
    db.Column('comment_id', db.Integer, db.ForeignKey('comment.id', name='fk_comment_dislikers_comment_id', ondelete='CASCADE'), primary_key=True),
    extend_existing=True  # Add this
)

repo_stars = db.Table('repo_stars', db.metadata,
    db.Column('user_id', db.Integer, db.ForeignKey('user.id', name='fk_repo_stars_user_id', ondelete='CASCADE'), primary_key=True),
    db.Column('git_repository_id', db.Integer, db.ForeignKey('git_repository.id', name='fk_repo_stars_git_repo_id', ondelete='CASCADE'), primary_key=True),
    db.Column('starred_at', db.DateTime, default=lambda: datetime.now(timezone.utc)), # Use timezone aware now
    extend_existing=True
)

repo_collaborators = db.Table('repo_collaborators', db.metadata,
    db.Column('user_id', db.Integer, db.ForeignKey('user.id', name='fk_repo_collaborators_user_id', ondelete='CASCADE'), primary_key=True),
    db.Column('git_repository_id', db.Integer, db.ForeignKey('git_repository.id', name='fk_repo_collaborators_git_repo_id', ondelete='CASCADE'), primary_key=True),
    # You could add a 'permission_level' column here if needed in the future (e.g., 'read', 'write', 'admin')
    # db.Column('permission', db.String(50), default='write', nullable=False),
    extend_existing=True
)

socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading', manage_session=True)

AVAILABLE_THEMES = {
    "default": "Default (Dark)", # No extra CSS, uses base.css only
    "true_dark_blue.css": "True Dark Blue",
    "true_dark_orange.css": "True Dark Orange",
    "true_dark_red.css": "True Dark Red",
    "breeze_dark.css": "Breeze Dark",
    "breeze_light.css": "Breeze Light",
    "retro_wave_dark.css": "Retro Wave Dark",
    "retro_wave_light.css": "Retro Wave Light",
    # Add more themes here as you create them
}
# BEGIN YOUTUBE DOWNLOADER
import yt_dlp # For downloading YouTube videos
from yt_dlp import YoutubeDL # Specifically for the YoutubeDL class

# Folder for temporary ytdlp downloads before moving to user's main storage
YTDLP_TEMP_DOWNLOAD_FOLDER = os.path.join(INSTANCE_FOLDER_PATH, 'temp_ytdlp_downloads')
os.makedirs(YTDLP_TEMP_DOWNLOAD_FOLDER, exist_ok=True)

# Helper to get user-specific temporary ytdlp download path
def get_user_ytdlp_temp_path(user_id):
    path = os.path.join(YTDLP_TEMP_DOWNLOAD_FOLDER, str(user_id))
    os.makedirs(path, exist_ok=True)
    return path

class YtdlpForm(FlaskForm):
    youtube_url = URLField('YouTube Video URL', validators=[DataRequired(), URL(message="Please enter a valid URL.")])
    download_format = SelectField('Format', choices=[
        ('mp4', 'MP4 Video'),
        ('mp3', 'MP3 Audio')
    ], default='mp4', validators=[DataRequired()])
    video_quality = SelectField('Video Quality (for MP4)', choices=[
        ('best', 'Best Available'), # Default best
        ('1080', '1080p'),
        ('720', '720p'),
        ('480', '480p'),
        ('360', '360p')
    ], default='best', validators=[Optional()]) # Optional as it only applies to MP4
    submit = SubmitField('Download')

@app.route('/ytdlp', methods=['GET', 'POST'])
@login_required
def ytdlp_downloader():
    form = YtdlpForm()
    # downloaded_file_info = None # Using session flash now

    if form.validate_on_submit():
        video_url = form.youtube_url.data
        download_format = form.download_format.data
        video_quality = form.video_quality.data # Only relevant if download_format is 'mp4'

        user_id = current_user.id
        user_temp_ytdlp_path = get_user_ytdlp_temp_path(user_id)

        # Clean the temporary directory for this user before new download
        try:
            for item in os.listdir(user_temp_ytdlp_path):
                item_path = os.path.join(user_temp_ytdlp_path, item)
                if os.path.isfile(item_path) or os.path.islink(item_path):
                    os.unlink(item_path)
                elif os.path.isdir(item_path):
                    shutil.rmtree(item_path)
        except Exception as e_clean:
            app.logger.warning(f"Could not fully clean temp ytdlp dir {user_temp_ytdlp_path}: {e_clean}")

        app.logger.info(f"User {user_id} attempting to download: {video_url} as {download_format} (Quality: {video_quality if download_format == 'mp4' else 'N/A'})")

        video_title_for_filename = "yt_download"
        try:
            with YoutubeDL({'quiet': True, 'noplaylist': True, 'extract_flat': True, 'logger': app.logger}) as ydl_info:
                pre_info_dict = ydl_info.extract_info(video_url, download=False)
            video_title_for_filename = pre_info_dict.get('title', video_title_for_filename)
        except Exception as e_pre_info:
            app.logger.warning(f"Could not pre-fetch video title for {video_url}: {e_pre_info}. Using default.")

        temp_dl_uuid_filename = str(uuid.uuid4())
        # Extension will be determined by yt-dlp based on format choice
        temp_output_template = os.path.join(user_temp_ytdlp_path, f"{temp_dl_uuid_filename}.%(ext)s")

        ydl_opts = {
            'outtmpl': temp_output_template,
            'noplaylist': True,
            'quiet': False,
            'noprogress': True,
            'logger': app.logger,
            'continuedl': True,
            'ignoreerrors': False,
        }

        if download_format == 'mp3':
            ydl_opts.update({
                'format': 'bestaudio/best',
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192', # Bitrate for MP3
                }],
            })
            final_extension_hint = ".mp3"
        else: # mp4
            quality_filter = ""
            if video_quality != 'best':
                quality_filter = f"[height<={video_quality}]" # e.g., [height<=720]

            # Strategy:
            # 1. Try to get the best video and best audio, potentially with quality filter, then merge and convert to mp4.
            # 2. Fallback to just the 'best' overall format (potentially webm, etc.), then convert to mp4.
            # The 'postprocessors' section with FFmpegVideoConvertor will handle the final conversion to MP4.

            # This format string will attempt to download the highest quality video and audio streams
            # (optionally filtered by height) and merge them.
            # If that fails, it falls back to the single 'best' format available.
            ydl_opts['format'] = f"bestvideo{quality_filter}+bestaudio/best{quality_filter}/best"

            ydl_opts['postprocessors'] = [{
                'key': 'FFmpegVideoConvertor',
                'preferedformat': 'mp4',
            }]
            final_extension_hint = ".mp4"


        downloaded_video_actual_path = None
        try:
            with YoutubeDL(ydl_opts) as ydl:
                result_info = ydl.extract_info(video_url, download=True)

            if result_info and result_info.get('filepath'):
                downloaded_video_actual_path = result_info['filepath']
            elif result_info and result_info.get('requested_downloads') and result_info['requested_downloads'][0].get('filepath'):
                downloaded_video_actual_path = result_info['requested_downloads'][0]['filepath']
            elif result_info and result_info.get('_filename'):
                _fn = result_info['_filename']
                downloaded_video_actual_path = os.path.join(user_temp_ytdlp_path, os.path.basename(_fn)) if not os.path.isabs(_fn) else _fn

            if not downloaded_video_actual_path or not os.path.exists(downloaded_video_actual_path):
                app.logger.warning(f"Path from info_dict ('{downloaded_video_actual_path}') not valid. Searching by UUID pattern '{temp_dl_uuid_filename}'.")
                found_files = [f for f in os.listdir(user_temp_ytdlp_path) if f.startswith(temp_dl_uuid_filename)]
                if found_files:
                    full_paths = [os.path.join(user_temp_ytdlp_path, f) for f in found_files]
                    # For MP3, the file might have .mp3. For video, it might be .mp4 or other.
                    # Prefer the one matching the final_extension_hint if possible.
                    preferred_found_file = next((p for p in full_paths if p.endswith(final_extension_hint)), None)
                    if preferred_found_file:
                        downloaded_video_actual_path = preferred_found_file
                    else: # Fallback to largest or first
                        downloaded_video_actual_path = max(full_paths, key=lambda p: os.path.getsize(p) if os.path.exists(p) else -1)
                    app.logger.info(f"Found file by UUID pattern: {downloaded_video_actual_path}")
                else:
                    downloaded_video_actual_path = None

            if not downloaded_video_actual_path:
                app.logger.error(f"yt-dlp finished, but failed to determine the final downloaded file path. Result info: {json.dumps(result_info, indent=2, default=str)}")
                raise Exception("Could not locate the downloaded file after yt-dlp execution.")

            if not os.path.exists(downloaded_video_actual_path):
                app.logger.error(f"File path determined as '{downloaded_video_actual_path}', but it does not exist on disk. Result info: {json.dumps(result_info, indent=2, default=str)}")
                raise Exception(f"Post-download check: File path '{downloaded_video_actual_path}' does not exist.")

            app.logger.info(f"File successfully processed by yt-dlp, final temp path: {downloaded_video_actual_path}")

            file_size_bytes = os.path.getsize(downloaded_video_actual_path)

            actual_extension = os.path.splitext(downloaded_video_actual_path)[1].lower()
            # Ensure final_extension_hint is used if actual_extension is something generic like .tmp
            if not actual_extension or actual_extension == '.tmp':
                actual_extension = final_extension_hint

            original_filename_for_db = secure_filename(video_title_for_filename + actual_extension)
            if not original_filename_for_db.endswith(actual_extension):
                original_filename_for_db = secure_filename(video_title_for_filename) + actual_extension

            stored_filename_on_disk = str(uuid.uuid4()) + actual_extension
            user_main_upload_path = get_user_upload_path(user_id)
            final_file_path_on_disk = os.path.join(user_main_upload_path, stored_filename_on_disk)

            storage_info = get_user_storage_info(current_user)
            available_bytes = storage_info['limit_bytes'] - storage_info['usage_bytes']
            if file_size_bytes > available_bytes:
                os.remove(downloaded_video_actual_path)
                flash(f"Downloaded file size ({file_size_bytes / (1024*1024):.2f}MB) exceeds your available storage ({available_bytes / (1024*1024):.2f}MB).", 'danger')
                return redirect(url_for('ytdlp_downloader'))

            shutil.move(downloaded_video_actual_path, final_file_path_on_disk)
            app.logger.info(f"Moved downloaded file to: {final_file_path_on_disk}")

            mime_type, _ = mimetypes.guess_type(final_file_path_on_disk)
            if not mime_type: # Fallback based on chosen format
                mime_type = 'audio/mpeg' if download_format == 'mp3' else 'video/mp4'

            new_file_db_record = File(
                original_filename=original_filename_for_db,
                stored_filename=stored_filename_on_disk,
                filesize=file_size_bytes,
                mime_type=mime_type,
                user_id=user_id,
                parent_folder_id=None
            )
            db.session.add(new_file_db_record)
            db.session.commit()

            flash(f"Successfully downloaded and saved '{new_file_db_record.original_filename}'!", 'success')
            app.logger.info(f"File '{new_file_db_record.original_filename}' (File ID: {new_file_db_record.id}) saved for user {user_id}.")
            session['last_downloaded_ytdlp_info'] = {
                'original_filename': new_file_db_record.original_filename,
                'filesize': new_file_db_record.filesize,
                'id': new_file_db_record.id
            }
            return redirect(url_for('ytdlp_downloader'))

        except yt_dlp.utils.DownloadError as e:
            app.logger.error(f"yt-dlp DownloadError for {video_url} by user {user_id}: {str(e)}")
            flash(f"Could not download. Error: {str(e)}", 'danger')
        except Exception as e:
            app.logger.error(f"An unexpected error occurred: {str(e)}", exc_info=True)
            flash(f"An unexpected error occurred: {str(e)}", 'danger')
            if downloaded_video_actual_path and os.path.exists(downloaded_video_actual_path):
                 try: os.remove(downloaded_video_actual_path)
                 except OSError: pass

    downloaded_file_info_from_session = session.pop('last_downloaded_ytdlp_info', None)
    return render_template('ytdlp.html',
                           title='YouTube Downloader',
                           form=form,
                           downloaded_file_info=downloaded_file_info_from_session)

# END YOUTUBE DOWNLOADER

# BEGIN SSH CLIENT

class SSHClientSession:
    def __init__(self, ip, port, username, socket_id):
        self.ip = ip
        self.port = port
        self.username = username
        self.socket_id = socket_id
        self.client = None
        self.channel = None
        self.output_thread = None
        self.active = False
        self.lock = threading.Lock()

    # Modify the connect method to accept a password parameter
    def connect(self, password=None): # MODIFY THIS LINE
        try:
            self.client = paramiko.SSHClient()
            self.client.load_system_host_keys()
            self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

            # Pass the password to the connect method if provided.
            # If password is None, paramiko will try key-based auth, then password (if allowed by server config).
            connect_params = {'hostname': self.ip, 'port': self.port, 'username': self.username, 'timeout': 10}
            if password: # Only add password if it's not an empty string
                connect_params['password'] = password

            self.client.connect(**connect_params) # MODIFY THIS LINE

            self.channel = self.client.invoke_shell()
            self.channel.setblocking(0)
            self.active = True
            socketio.emit('ssh_connected', {}, room=self.socket_id)
            self.output_thread = threading.Thread(target=self._read_output, daemon=True)
            self.output_thread.start()
            return True
        except paramiko.AuthenticationException:
            error_msg = 'Authentication failed. Please check your username, password, or SSH keys.'
            app.logger.error(f"SSH Auth Error for {self.username}@{self.ip}: {error_msg}")
            socketio.emit('ssh_error', {'message': error_msg}, room=self.socket_id)
            self.disconnect()
            return False
        except paramiko.ssh_exception.NoValidConnectionsError as e:
            error_msg = f"Could not establish SSH connection. Is the server running and reachable on port {self.port}? Error: {e}"
            app.logger.error(f"SSH Connection Error for {self.username}@{self.ip}:{self.port}: {error_msg}")
            socketio.emit('ssh_error', {'message': error_msg}, room=self.socket_id)
            self.disconnect()
            return False
        except paramiko.SSHException as e:
            error_msg = f'An SSH protocol error occurred: {e}. Ensure the server supports common SSH versions.'
            app.logger.error(f"SSH Protocol Error for {self.username}@{self.ip}: {error_msg}")
            socketio.emit('ssh_error', {'message': error_msg}, room=self.socket_id)
            self.disconnect()
            return False
        except TimeoutError:
            error_msg = f'Connection timed out after 10 seconds. The server might be unreachable or heavily loaded.'
            app.logger.error(f"SSH Timeout Error for {self.username}@{self.ip}")
            socketio.emit('ssh_error', {'message': error_msg}, room=self.socket_id)
            self.disconnect()
            return False
        except Exception as e:
            error_msg = f'An unexpected error occurred during connection: {e}.'
            app.logger.error(f"Unexpected SSH Connection Error for {self.username}@{self.ip}: {error_msg}", exc_info=True)
            socketio.emit('ssh_error', {'message': error_msg}, room=self.socket_id)
            self.disconnect()
            return False

    def _read_output(self):
        while self.active:
            try:
                rlist, _, _ = select.select([self.channel], [], [], 0.1)
                if rlist:
                    output = b''
                    while self.channel.recv_ready():
                        output += self.channel.recv(4096)
                    while self.channel.recv_stderr_ready():
                        output += self.channel.recv_stderr(4096)

                    if output:
                        try:
                            # Use socketio.emit directly
                            socketio.emit('ssh_output', {'output': output.decode('utf-8', errors='replace')}, room=self.socket_id)
                        except Exception as e:
                            app.logger.error(f"Error decoding SSH output: {e}")
                            socketio.emit('ssh_output', {'output': f"[Decoding Error: {e}]\n"}, room=self.socket_id)
                if self.channel and self.channel.exit_status_ready():
                    app.logger.info(f"SSH channel exited with status {self.channel.exit_status}.")
                    socketio.emit('ssh_output', {'output': f"\n--- SSH session ended (exit status: {self.channel.exit_status}) ---\n"}, room=self.socket_id)
                    self.disconnect()
                    break
                elif self.channel and not self.channel.active:
                    app.logger.info("SSH channel became inactive.")
                    self.disconnect()
                    break

                time.sleep(0.01)
            except Exception as e:
                app.logger.error(f"Error in SSH output reading thread: {e}", exc_info=True)
                if self.active:
                    # Use socketio.emit directly
                    socketio.emit('ssh_error', {'message': f'Terminal read error: {e}'}, room=self.socket_id)
                self.disconnect()
                break
        app.logger.info(f"SSH output thread for {self.username}@{self.ip} finished.")

    def execute_command(self, command):
        if not self.active or not self.channel:
            # Use socketio.emit directly
            socketio.emit('ssh_error', {'message': 'Not connected to SSH server.'}, room=self.socket_id)
            return

        try:
            with self.lock:
                self.channel.send(command.encode('utf-8')) # Send the raw command as received from client
        except Exception as e:
            # Use socketio.emit directly
            socketio.emit('ssh_error', {'message': f'Failed to send command: {e}'}, room=self.socket_id)
            self.disconnect()

    def disconnect(self):
        if self.active:
            self.active = False
            if self.channel:
                try:
                    self.channel.close()
                    app.logger.info(f"SSH channel closed for {self.username}@{self.ip}")
                except Exception as e:
                    app.logger.warning(f"Error closing SSH channel: {e}")
            if self.client:
                try:
                    self.client.close()
                    app.logger.info(f"SSH client closed for {self.username}@{self.ip}")
                except Exception as e:
                    app.logger.warning(f"Error closing SSH client: {e}")
            # Use socketio.emit directly
            socketio.emit('ssh_disconnected', {}, room=self.socket_id)
            self._cleanup_session_data()

    def _cleanup_session_data(self):
        global active_ssh_sessions
        if self.socket_id in active_ssh_sessions:
            del active_ssh_sessions[self.socket_id]
            app.logger.info(f"Cleaned up SSH session for socket {self.socket_id}")


active_ssh_sessions = {} # Dictionary to store SSHClientSession instances {socket_id: SSHClientSession}

# Add this route for the SSH Client page
@app.route('/ssh_client')
@login_required
def ssh_client_page():
    """
    Serves the SSH client HTML page.
    """
    # Check if a session already exists for the current user's socket.
    # This might need refinement for actual multi-tab/multi-device handling.
    # For simplicity, we assume one SSH session per browser tab/Socket.IO connection.
    return render_template('ssh_client.html', title='SSH Client')

@app.route('/ssh_terminal_popup')
@login_required # Apply login_required if you want this URL to be protected
def ssh_terminal_popup():
    """
    Serves the HTML content for the SSH terminal pop-out window.
    This page itself does not need a CSRF token directly as it receives
    connection parameters via postMessage from the main window.
    """
    return render_template('ssh_terminal_popup.html')

# Socket.IO Event Handlers for SSH Client
@socketio.on('ssh_connect_request')
@login_required
def handle_ssh_connect_request(data):
    socket_id = request.sid
    app.logger.info(f"SSH connect request from user {current_user.id} (Socket ID: {socket_id})")

    ip = data.get('ip')
    port = int(data.get('port', 22))
    username = data.get('username')
    password = data.get('password') # ADD THIS LINE TO RECEIVE THE PASSWORD

    if not ip or not username:
        socketio.emit('ssh_error', {'message': 'IP address and username are required.'}, room=socket_id)
        return

    # Disconnect any existing session for this socket_id
    if socket_id in active_ssh_sessions:
        app.logger.warning(f"Existing SSH session found for {socket_id}, disconnecting it.")
        active_ssh_sessions[socket_id].disconnect()
        del active_ssh_sessions[socket_id]

    # Pass the password to the SSHClientSession constructor
    ssh_session = SSHClientSession(ip, port, username, socket_id)
    active_ssh_sessions[socket_id] = ssh_session

    app.logger.info(f"Attempting SSH connection for {username}@{ip}:{port} (Socket ID: {socket_id})")
    # Connect in a separate thread. Pass the password to the connect method.
    threading.Thread(target=ssh_session.connect, args=(password,), daemon=True).start() # MODIFY THIS LINE


@socketio.on('ssh_command')
@login_required
def handle_ssh_command(data):
    socket_id = request.sid
    command = data.get('command')

    ssh_session = active_ssh_sessions.get(socket_id)
    if not ssh_session or not ssh_session.active:
        emit('ssh_error', {'message': 'No active SSH connection.'}, room=socket_id)
        return

# DEBUG FOR INPUT
#   app.logger.info(f"Executing command '{command}' for user {current_user.id} (Socket ID: {socket_id})")
    ssh_session.execute_command(command)

@socketio.on('ssh_disconnect_request')
@login_required
def handle_ssh_disconnect_request():
    socket_id = request.sid
    app.logger.info(f"SSH disconnect request from user {current_user.id} (Socket ID: {socket_id})")

    ssh_session = active_ssh_sessions.get(socket_id)
    if ssh_session:
        ssh_session.disconnect()
        # The disconnect method itself cleans up active_ssh_sessions
    else:
        app.logger.warning(f"Disconnect request for non-existent session {socket_id}.")
        emit('ssh_disconnected', {}, room=socket_id) # Send confirmation anyway

@socketio.on('disconnect')
def handle_disconnect():
    # This event fires when a client disconnects from Socket.IO (e.g., closing tab)
    socket_id = request.sid
    app.logger.info(f"Socket.IO client disconnected: {socket_id}")

    # Ensure any active SSH session associated with this socket is also cleaned up
    ssh_session = active_ssh_sessions.get(socket_id)
    if ssh_session:
        app.logger.info(f"Cleaning up SSH session for disconnected Socket.IO client: {socket_id}")
        ssh_session.disconnect() # This will remove it from active_ssh_sessions


@socketio.on('ssh_resize')
@login_required
def handle_ssh_resize(data):
    socket_id = request.sid
    cols = data.get('cols')
    rows = data.get('rows')

    ssh_session = active_ssh_sessions.get(socket_id)
    if ssh_session and ssh_session.active and ssh_session.channel:
        try:
            ssh_session.channel.resize_pty(width=cols, height=rows)
            app.logger.info(f"Resized PTY for socket {socket_id} to {cols}x{rows}")
        except Exception as e:
            app.logger.error(f"Error resizing PTY for socket {socket_id}: {e}")
    else:
        app.logger.warning(f"Resize request for inactive SSH session {socket_id}.")


# END SSH CLIENT


# BEGIN UPSCALER

class ImageUpscalerForm(FlaskForm):

    submit = SubmitField('Upscale Image')


PILLOW_UPSCALING_ONLY = False # Use this to control behavior

UPSCALED_IMAGE_FOLDER = os.path.join(INSTANCE_FOLDER_PATH, 'uploads', 'upscaled_images')
os.makedirs(UPSCALED_IMAGE_FOLDER, exist_ok=True)

ALLOWED_EXTENSIONS_UPSCALER = {'png', 'jpg', 'jpeg', 'webp'}

def allowed_file_upscaler(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS_UPSCALER

@app.route('/image_upscaler', methods=['GET', 'POST'])
@login_required
def image_upscaler():
    form = ImageUpscalerForm()
    original_file_saved_name = None
    upscaled_file_saved_name = None
    original_filename_for_download = None
    upscaled_img_dimensions = {}

    if request.method == 'POST':
        if 'image_file' not in request.files:
            flash('No image file part in the request.', 'danger')
            return redirect(request.url)

        file = request.files['image_file']
        scale_factor = int(request.form.get('scale_factor', 2))

        if file.filename == '':
            flash('No image selected for uploading.', 'warning')
            return redirect(request.url)

        if file and allowed_file_upscaler(file.filename):
            original_filename_for_download = secure_filename(file.filename)
            # original_ext is determined later for the output, input format is handled by Pillow

            # Use a unique name for the initially saved (original) file as well
            temp_original_ext = os.path.splitext(original_filename_for_download)[1].lower()
            temp_original_saved_name = "original_" + str(uuid.uuid4()) + temp_original_ext
            original_file_path = os.path.join(UPSCALED_IMAGE_FOLDER, temp_original_saved_name)
            original_file_saved_name = temp_original_saved_name # To show original in template

            try:
                file.save(original_file_path)
                input_img_pil = Image.open(original_file_path)

                img_to_resize = None
                if input_img_pil.mode in ['RGBA', 'LA']:
                    # Image already has an alpha channel, use it as is (or copy)
                    img_to_resize = input_img_pil.copy()
                    app.logger.info(f"Input image mode {input_img_pil.mode} (has alpha), processing as is.")
                elif input_img_pil.mode == 'P':
                    # Palette-based image, convert to RGBA.
                    # .convert('RGBA') correctly handles transparency in P mode.
                    img_to_resize = input_img_pil.convert('RGBA')
                    app.logger.info(f"Input image mode P, converted to {img_to_resize.mode} for processing (to preserve transparency).")
                else:
                    # For other modes (like RGB, L, CMYK etc.), convert to RGB.
                    img_to_resize = input_img_pil.convert('RGB')
                    app.logger.info(f"Input image mode {input_img_pil.mode}, converted to {img_to_resize.mode} for processing.")

                original_width, original_height = img_to_resize.size # Use size of the processed image
                new_width = original_width * scale_factor
                new_height = original_height * scale_factor

                app.logger.info(f"Resizing image (mode: {img_to_resize.mode}) with Pillow to {new_width}x{new_height}")
                upscaled_img_pil = img_to_resize.resize((new_width, new_height), Image.Resampling.LANCZOS)

                # Determine output extension based on original, defaulting to PNG for wider compatibility if needed
                output_ext = os.path.splitext(original_filename_for_download)[1].lower()
                if output_ext not in ['.png', '.jpg', '.jpeg', '.webp']:
                    output_ext = '.png' # Default to PNG if original extension isn't ideal or for non-web formats

                upscaled_file_saved_name = "upscaled_" + str(uuid.uuid4()) + output_ext
                upscaled_file_path = os.path.join(UPSCALED_IMAGE_FOLDER, upscaled_file_saved_name)

                # Save the upscaled image, respecting its mode and the target extension
                if output_ext in ['.jpg', '.jpeg']:
                    final_save_img = upscaled_img_pil
                    if final_save_img.mode != 'RGB':
                        # JPGs cannot have alpha. Convert to RGB if it has alpha (RGBA, LA) or is grayscale (L).
                        app.logger.info(f"Converting upscaled image from {final_save_img.mode} to RGB for JPG saving.")
                        final_save_img = final_save_img.convert('RGB')
                    final_save_img.save(upscaled_file_path, quality=90, optimize=True)

                elif output_ext == '.png':
                    # PNG supports various modes including RGBA. Save in its current mode.
                    app.logger.info(f"Saving PNG in mode {upscaled_img_pil.mode}")
                    upscaled_img_pil.save(upscaled_file_path, optimize=True)

                elif output_ext == '.webp':
                    # WebP supports RGBA.
                    app.logger.info(f"Saving WebP in mode {upscaled_img_pil.mode}")
                    if upscaled_img_pil.mode in ['RGBA', 'LA']: # Check if it has alpha
                        upscaled_img_pil.save(upscaled_file_path, lossless=True, optimize=True) # Lossless is good for graphics with alpha
                    else:
                        # If not RGBA/LA, ensure it's RGB for quality-based saving
                        img_to_save_webp = upscaled_img_pil
                        if img_to_save_webp.mode != 'RGB':
                           img_to_save_webp = img_to_save_webp.convert('RGB')
                        img_to_save_webp.save(upscaled_file_path, quality=90, optimize=True)

                else: # Should not be reached if output_ext is one of the above or defaulted to .png
                    app.logger.warning(f"Attempting to save with an unexpected extension: {output_ext}. Saving as is.")
                    upscaled_img_pil.save(upscaled_file_path, optimize=True)


                upscaled_img_dimensions = {'width': upscaled_img_pil.width, 'height': upscaled_img_pil.height}
                flash(f'Image resized ({scale_factor}x) using Pillow (basic resize). Processed as {img_to_resize.mode}, saved as {output_ext}.', 'success')

            except Exception as e:
                flash(f'An error occurred during basic resizing: {str(e)}', 'danger')
                app.logger.error(f"Error basic resizing file {original_filename_for_download}: {e}", exc_info=True)
                upscaled_file_saved_name = None # Ensure this is cleared on error
                # original_file_saved_name might still be set if initial save worked, cleanup will handle it or show original.

        else:
            flash('Invalid file type for upscaling. Allowed: PNG, JPG, JPEG, WEBP.', 'warning')
            return redirect(request.url) # Redirect if file type is not allowed

    # ... (rest of your cleanup code and render_template call)
    # Simple cleanup of old files in UPSCALED_IMAGE_FOLDER
    try:
        now_ts = datetime.now().timestamp()
        for f_name in os.listdir(UPSCALED_IMAGE_FOLDER):
            f_path = os.path.join(UPSCALED_IMAGE_FOLDER, f_name)
            # Keep current session's original and upscaled files
            if f_name == original_file_saved_name or f_name == upscaled_file_saved_name:
                continue
            try:
                # Remove files older than 10 minutes (600 seconds)
                if (now_ts - os.path.getmtime(f_path)) > 600:
                    os.remove(f_path)
            except Exception: # pylint: disable=broad-except
                pass # Ignore errors during cleanup of individual files
    except Exception as e_clean: # pylint: disable=broad-except
        app.logger.warning(f"Error during temporary upscaled image cleanup: {e_clean}")

    return render_template('image_upscaler.html',
                           title='Image Upscaler (Basic Resize)',
                           form=form,
                           original_filename=original_file_saved_name,
                           upscaled_filename=upscaled_file_saved_name,
                           original_filename_for_download=original_filename_for_download,
                           upscaled_dimensions=upscaled_img_dimensions
                           )

# Ensure the serve_temp_upscaled_image route is still present
@app.route('/temp_upscaled_images/<filename>')
@login_required
def serve_temp_upscaled_image(filename):
    safe_filename = secure_filename(filename)
    if safe_filename != filename:
        abort(404)
    try:
        return send_from_directory(UPSCALED_IMAGE_FOLDER, safe_filename)
    except FileNotFoundError:
        abort(404)

# END UPSCALER

@app.before_request
def load_selected_theme():
    selected_theme_file = None
    theme_name = "default" # Default theme

    if current_user.is_authenticated:
        # Option 1: Loading from User Model
        try:
            theme_name = getattr(current_user, 'preferred_theme', 'default')
        except AttributeError:
            theme_name = 'default'

        # Option 2: Loading from Session
        # theme_name = session.get('theme', 'default')
        # print(f"Authenticated user. Loaded theme_name from session: '{theme_name}'")

    else: # For anonymous users
        theme_name = session.get('theme', 'default')
        print(f"Anonymous user. Loaded theme_name from session: '{theme_name}'")

    if theme_name != "default" and theme_name in AVAILABLE_THEMES:
        selected_theme_file = url_for('static', filename=f'css/themes/{theme_name}')

    g.selected_theme_css = selected_theme_file
    g.current_theme_name = theme_name

# Make selected_theme_css available to all templates
@app.context_processor
def inject_theme():
    return dict(
        selected_theme_css=getattr(g, 'selected_theme_css', None),
        current_theme_name=getattr(g, 'current_theme_name', 'default'),
        available_themes=AVAILABLE_THEMES
    )

@app.route('/settings', methods=['GET'])
@login_required
def user_settings_page():
    """
    Displays the user settings page.
    Other settings forms could be processed here if combined into a single POST,
    or link to separate pages/routes for editing profile, password, etc.
    """
    return render_template('user_settings.html')

# --- Example Route to Change Theme (e.g., from a settings page) ---
@app.route('/change-theme', methods=['POST'])
@login_required
def change_theme():
    new_theme_file = request.form.get('theme')

    if not new_theme_file:
        flash("No theme value received.", "error")
        return redirect(url_for('user_settings_page'))

    if new_theme_file not in AVAILABLE_THEMES:
        flash(f"Invalid theme value: {new_theme_file}", "error")
        return redirect(url_for('user_settings_page'))

    try:
        print(f"Attempting to set current_user.preferred_theme to: {new_theme_file}")
        current_user.preferred_theme = new_theme_file
        # Assuming 'db' is your SQLAlchemy instance
        # from . import db  # Or however you import your db
        db.session.commit()
        print(f"DB COMMIT SUCCEEDED. current_user.preferred_theme is now: {getattr(current_user, 'preferred_theme', 'ERROR - NOT SET')}")
        flash(f"Theme changed to {AVAILABLE_THEMES[new_theme_file]}.", "success")
    except Exception as e:
        db.session.rollback()
        print(f"!!! DATABASE ERROR during commit: {e} !!!")
        flash(f"Database error saving theme: {e}", "error")

    return redirect(url_for('user_settings_page'))

# Helper to get post media upload path
def get_post_media_path():
    # Path for storing post media (photos, videos)
    # It's generally better to serve user-uploaded static content from a dedicated directory
    # within 'static' or configure the web server (like Nginx/Apache) to serve it.
    # For simplicity, we'll use a subdirectory in 'static'.
    path = os.path.join(app.root_path, 'static', 'uploads', 'post_media')
    try:
        os.makedirs(path, exist_ok=True)
    except OSError as e:
         app.logger.error(f"Could not create post media directory: {path} - Error: {e}", exc_info=True)
         raise # Critical if this fails
    return path

def time_since_filter(dt_str, default="just now"):
    if dt_str is None:
        return default

    dt_actual = None
    if isinstance(dt_str, str):
        try:
            # Parse the ISO string. Python 3.7+ fromisoformat handles 'Z' by interpreting it as UTC.
            # If it has more than 6 decimal places for seconds (nanoseconds), it might cause issues.
            # Standard isoformat() should produce at most 6.
            dt_actual = datetime.fromisoformat(dt_str.replace('Z', '+00:00'))
        except ValueError:
            # Log the error if parsing fails
            current_app.logger.error(f"Could not parse timestamp string in time_since_filter: '{dt_str}'")
            return default # Fallback if parsing fails
    elif isinstance(dt_str, datetime):
        dt_actual = dt_str # If a datetime object was somehow passed directly
    else:
        current_app.logger.warning(f"time_since_filter received unexpected type for dt_str: {type(dt_str)}")
        return default

    if dt_actual is None: # Should be caught by ValueError above, but as a safeguard
        return default

    # Ensure the parsed datetime is timezone-aware (UTC)
    if dt_actual.tzinfo is None:
        dt_actual = dt_actual.replace(tzinfo=timezone.utc)

    now = datetime.now(timezone.utc)  # Use timezone-aware current time in UTC

    try:
        diff = now - dt_actual
    except TypeError as e:
        current_app.logger.error(f"TypeError in time_since_filter during diff: now={now} ({type(now)}), dt_actual={dt_actual} ({type(dt_actual)}). Error: {e}")
        return default


    seconds = diff.total_seconds()
    days = diff.days

    if days < 0: # Timestamp is in the future
        return "in the future"

    # The template already appends " ago", so the filter should just return the duration string
    if days >= 365:
        years = days // 365
        return f"{years} year{'s' if years > 1 else ''}"
    if days >= 30:
        months = days // 30
        return f"{months} month{'s' if months > 1 else ''}"
    if days >= 7:
        weeks = days // 7
        return f"{weeks} week{'s' if weeks > 1 else ''}"
    if days > 0:
        return f"{days} day{'s' if days > 1 else ''}"
    if seconds < 60:
        return default # "just now"
    if seconds < 3600: # Less than an hour
        minutes = int(seconds // 60)
        return f"{minutes} minute{'s' if minutes > 1 else ''}"
    # Less than a day
    hours = int(seconds // 3600)
    return f"{hours} hour{'s' if hours > 1 else ''}"

app.jinja_env.filters['timesince'] = time_since_filter

def localetime_filter(dt):
    """
    Jinja filter to format a datetime object as a valid ISO 8601 string (UTC).
    Ensures the string is correctly parseable by client-side JS Date objects.
    """
    if dt is None:
        # Return an empty string if the datetime object is None
        return ""
    # Ensure it's UTC before converting to ISO
    if dt.tzinfo is None:
        # Assuming naive datetimes stored are implicitly UTC
        dt = dt.replace(tzinfo=timezone.utc)

    # Return the ISO 8601 string.
    # datetime.isoformat() for a timezone-aware UTC object
    # should produce a string ending in +00:00, which is valid.
    # Do NOT manually append 'Z'.
    return dt.isoformat() # REMOVED + 'Z'

app.jinja_env.filters['localetime'] = localetime_filter

app.jinja_env.globals.update(
    datetime=datetime, # CORRECTED: Make the datetime module (which includes the datetime class) available
    naturaltime=naturaltime,
    len=len
)

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

    # This map will store the mapping from temporary disk paths to their corresponding DB folder IDs
    # e.g., { 'temp_extract_dir/folder_name': folder_db_id, 'temp_extract_dir/folder_name/subfolder_name': subfolder_db_id }
    # It starts with the base extraction directory mapping to the initial parent_folder_id_in_db
    newly_created_folder_map = {extract_base_dir: parent_folder_id_in_db}

    # IMPORTANT: Iterate `topdown=False` for robust directory handling in case of empty subdirs being removed
    # or if we need to ensure child items are processed before their parent might be manipulated.
    # However, for creating DB records and physical moves, `topdown=True` is usually better for ensuring parents exist.
    # Let's stick with topdown=True, as we're managing `newly_created_folder_map` carefully.
    for root, dirs, files in os.walk(extract_base_dir, topdown=True):

        # Determine the database parent ID for the current `root` directory being processed
        # This will be the ID of the folder in our DB that corresponds to the `root` path.
        current_db_parent_id = newly_created_folder_map[root]

        # Register Directories first (when topdown=True, dirs list can be modified in-place to prune walk)
        for dirname in dirs:
            dir_path_on_disk = os.path.join(root, dirname)
            sanitized_dirname = secure_filename(dirname) # Sanitize folder name

            if not sanitized_dirname: # Skip folders with unusable names
                app.logger.warning(f"Skipping extracted folder with invalid name: {dirname} in {root}")
                # Remove the directory from `dirs` to prevent os.walk from descending into it
                # when its name is invalid. This means `os.walk` will skip its contents too.
                dirs.remove(dirname)
                continue

            # Check if a folder with this name already exists under the current DB parent
            existing_folder = Folder.query.filter_by(
                user_id=user_id,
                parent_folder_id=current_db_parent_id,
                name=sanitized_dirname
            ).first()

            if not existing_folder:
                try:
                    new_folder = Folder(
                        name=sanitized_dirname,
                        user_id=user_id,
                        parent_folder_id=current_db_parent_id
                    )
                    db.session.add(new_folder)
                    db.session.flush() # Assigns an ID to new_folder without full commit
                    # Store the mapping from the physical path of this new folder to its DB ID
                    newly_created_folder_map[dir_path_on_disk] = new_folder.id
                    app.logger.info(f"Registered extracted folder: {sanitized_dirname} (ID: {new_folder.id}) in DB parent {current_db_parent_id}")
                except Exception as e:
                    app.logger.error(f"Error registering extracted folder '{sanitized_dirname}': {e}", exc_info=True)
                    raise # Re-raise to be caught by the main route's try/except
            else:
                # Folder already exists, so use its existing ID for its children
                newly_created_folder_map[dir_path_on_disk] = existing_folder.id
                app.logger.debug(f"Extracted folder '{sanitized_dirname}' already exists (ID: {existing_folder.id}), using existing record.")


        # Register Files
        for filename in files:
            filepath_in_temp_extract = os.path.join(root, filename) # Full path in the temporary extraction dir
            original_sanitized_filename = secure_filename(filename)

            if not original_sanitized_filename:
                app.logger.warning(f"Skipping extracted file with invalid name: {filename} in {root}")
                continue # Skip this file

            # --- Critical Change: Determine NEW physical destination path based on desired structure ---
            # The destination for the file on disk should be directly within user_upload_root,
            # but its *database parent* (current_db_parent_id) will reflect its logical folder.
            # We will generate a UUID for the stored_filename as you currently do.
            _, ext = os.path.splitext(filename)
            new_stored_filename = str(uuid.uuid4()) + ext

            # The actual path where the file will physically reside on the server
            # This remains flattened in user_upload_root
            final_physical_file_path = os.path.join(user_upload_root, new_stored_filename)

            # --- Perform Physical Move ---
            try:
                # Check if the source file actually exists in the temporary directory
                if not os.path.exists(filepath_in_temp_extract):
                    app.logger.warning(f"Physical extracted source file not found for move: {filepath_in_temp_extract}. Skipping.")
                    continue

                os.rename(filepath_in_temp_extract, final_physical_file_path)
                app.logger.debug(f"Moved extracted file {filepath_in_temp_extract} to {final_physical_file_path}")

            except OSError as e:
                app.logger.error(f"Error moving extracted file '{filename}' from temp to final location: {e}", exc_info=True)
                continue # Skip this file if move fails

            # Create DB record
            try:
                filesize = os.path.getsize(final_physical_file_path) # Get size from the moved file
                mime_type = mimetypes.guess_type(final_physical_file_path)[0] or 'application/octet-stream'

                new_file = File(
                    original_filename=original_sanitized_filename,
                    stored_filename=new_stored_filename, # The UUID-based name
                    filesize=filesize,
                    mime_type=mime_type,
                    user_id=user_id,
                    parent_folder_id=current_db_parent_id # <--- This is KEY: Link to the correct DB folder ID
                )
                db.session.add(new_file)
                app.logger.info(f"Registered extracted file: {original_sanitized_filename} (Stored: {new_stored_filename}, Parent ID: {current_db_parent_id})")

            except Exception as e:
                app.logger.error(f"Error registering extracted file '{original_sanitized_filename}' into DB: {e}", exc_info=True)
                # Clean up the moved file if DB registration fails
                if os.path.exists(final_physical_file_path):
                    try: os.remove(final_physical_file_path)
                    except OSError: pass
                raise # Re-raise to be caught by the main route's try/except

def get_codemirror_mode_from_filename(filename):
    """
    Determines a suitable CodeMirror mode based on the filename's extension.
    Uses CodeMirror.findModeByExtension if available on client,
    otherwise falls back to a basic mapping.
    This function provides a server-side hint. The actual mode loading
    will happen client-side via static/codemirror/mode/meta.js.
    """
    if not filename or '.' not in filename:
        return 'text/plain'
    ext = filename.rsplit('.', 1)[1].lower()

    # More comprehensive mapping can be added here if needed,
    # but meta.js on client-side is preferred.
    # This is just a server-side helper for the template.
    simple_map = {
        'py': 'python',
        'js': 'javascript',
        'json': 'application/json',
        'css': 'css',
        'html': 'htmlmixed',
        'htm': 'htmlmixed',
        'xml': 'xml',
        'md': 'markdown',
        'sh': 'shell',
        'sql': 'sql',
        'yaml': 'yaml',
        'yml': 'yaml',
        'java': 'text/x-java',
        'c': 'text/x-csrc',
        'cpp': 'text/x-c++src',
        'h': 'text/x-c++src',
        'hpp': 'text/x-c++src',
        'cs': 'text/x-csharp',
        # Add more common ones
    }
    return simple_map.get(ext, 'text/plain')

def get_latest_commit_info_for_path(repo_disk_path, item_path_in_repo, ref_name):
    """
    Fetches detailed last commit information for a specific path in a repository.
    Returns a dictionary with id, short_message, message, committer_name, and date,
    or None if no commit is found or an error occurs.
    """
    try:
        pygit_repo = PyGitRepo(repo_disk_path) # Use the aliased GitPython Repo

        # Attempt to resolve the reference to a commit object
        try:
            resolved_ref_commit = pygit_repo.commit(ref_name)
        except Exception as e_ref:
            current_app.logger.warning(f"Could not resolve ref '{ref_name}' to a commit in {repo_disk_path} for path '{item_path_in_repo}': {e_ref}")
            return None

        # Get the last commit that modified this specific path on the given ref
        commits_iter = pygit_repo.iter_commits(rev=resolved_ref_commit.hexsha, paths=item_path_in_repo, max_count=1)
        last_commit = next(commits_iter, None)

        if last_commit:
            commit_info = {
                'id': last_commit.hexsha,
                'message': last_commit.message,
                'short_message': last_commit.message.splitlines()[0] if last_commit.message else "[No commit message]",
                'committer_name': last_commit.committer.name if last_commit.committer else "N/A",
                'date': datetime.fromtimestamp(last_commit.committed_date, tz=timezone.utc)
            }
            return commit_info
        else:
            # No specific commit found for this path on this ref.
            # This can happen for items added in the working tree but not committed,
            # or for paths that genuinely have no history on the ref (e.g. if ref is an old commit before path existed)
            # For ls-tree, items listed should have history. Might indicate an empty repo or very specific edge cases.
            # current_app.logger.info(f"No specific commit history found for path '{item_path_in_repo}' on ref '{ref_name}' in {repo_disk_path}.")
            return None

    except InvalidGitRepositoryError:
        current_app.logger.error(f"InvalidGitRepositoryError for {repo_disk_path} when getting commit info for {item_path_in_repo}.")
        return None
    except NoSuchPathError: # Should be caught by PyGitRepo constructor usually, but as a safeguard
        current_app.logger.error(f"NoSuchPathError for {repo_disk_path} (repo itself) when getting commit info for {item_path_in_repo}.")
        return None
    except Exception as e:
        current_app.logger.error(f"Error getting latest commit info for path '{item_path_in_repo}' in {repo_disk_path} (ref: {ref_name}): {e}", exc_info=True)
        return None

def get_repo_git_details(repo_disk_path):
    """
    Fetches commit count and last commit date for a Git repository using GitPython.
    """
    details = {'commit_count': 0, 'last_commit_date': None, 'error': None}
    if not os.path.isdir(repo_disk_path):
        details['error'] = "Repository disk path not found or not a directory."
        # current_app.logger.warning(f"get_repo_git_details: Path {repo_disk_path} is not a valid directory.") # Already logged by caller if needed
        return details

    try:
        # Use the NEW UNIQUE alias for GitPython's Repo class
        git_py_repo = PyGitRepo(repo_disk_path) # CORRECTED ALIAS USAGE

        if not git_py_repo.head.is_valid() or not git_py_repo.references:
            all_commits_list_check = []
            try:
                all_commits_list_check = list(git_py_repo.iter_commits(all=True, max_count=1))
            except Exception: # Handle rare cases where iter_commits might fail
                pass
            if not all_commits_list_check:
                details['error'] = "Empty repository or no commits yet."
                return details

        commits_iter = git_py_repo.iter_commits()
        first_commit_for_date = next(commits_iter, None)

        if first_commit_for_date:
            # CORRECTED: 'datetime' is the class from 'from datetime import datetime'
            details['last_commit_date'] = datetime.fromtimestamp(first_commit_for_date.committed_date, tz=timezone.utc)
            try:
                if git_py_repo.head.is_detached: # Check if head is detached
                    # Count commits reachable from the detached HEAD
                    details['commit_count'] = sum(1 for _ in git_py_repo.iter_commits(git_py_repo.head.commit.hexsha))
                elif git_py_repo.head.ref: # Check if head.ref exists (active branch)
                    details['commit_count'] = sum(1 for _ in git_py_repo.iter_commits(git_py_repo.head.ref.name))
                else: # Fallback if no active branch name (e.g., repo just initialized)
                    details['commit_count'] = sum(1 for _ in git_py_repo.iter_commits('--all'))
            except Exception as e_count:
                 current_app.logger.warning(f"Could not accurately count commits for {repo_disk_path} on default branch: {e_count}. Falling back to all commits.")
                 details['commit_count'] = sum(1 for _ in git_py_repo.iter_commits('--all')) # Count all commits as fallback
        else:
            all_commits_list = list(git_py_repo.iter_commits(all=True))
            if all_commits_list:
                details['commit_count'] = len(all_commits_list)
                # CORRECTED: 'datetime' is the class here
                details['last_commit_date'] = datetime.fromtimestamp(all_commits_list[0].committed_date, tz=timezone.utc)
            else:
                details['error'] = "No commits found in repository."
                return details

    except InvalidGitRepositoryError:
        details['error'] = "Not a valid Git repository."
    except NoSuchPathError:
        details['error'] = "Repository path does not exist on disk."
    except TypeError as te:
        # This specific error was due to the alias clash. Should be resolved by using PyGitRepo.
        details['error'] = f"Initialization error with Git library. Check logs. ({te})"
        current_app.logger.error(f"GitPython TypeError in get_repo_git_details for {repo_disk_path}: {te}", exc_info=True)
    except Exception as e:
        details['error'] = f"Error accessing Git repository details: {type(e).__name__}"
        current_app.logger.error(f"GitPython error in get_repo_git_details for {repo_disk_path}: {e}", exc_info=True)
    return details


def get_file_git_details(repo_disk_path, file_path_in_repo, branch_or_ref='HEAD'):
    """
    Fetches last commit details (message, date) and creation date for a specific file.
    Uses the specified branch_or_ref.
    """
    details = {'last_commit_message': None, 'last_commit_date': None, 'creation_date': None, 'error': None}
    if not os.path.isdir(repo_disk_path):
        details['error'] = "Repository disk path not found or not a directory."
        return details
    try:
        # CORRECTED: Use the new unique alias for GitPython's Repo class
        git_py_repo = PyGitRepo(repo_disk_path) # CORRECTED ALIAS USAGE

        if not git_py_repo.head.is_valid() and not git_py_repo.references :
            details['error'] = "Repository is empty or has no commits."
            return details

        try:
            resolved_ref = git_py_repo.commit(branch_or_ref)
        except Exception as e_ref: # Catches common errors like BadName
            details['error'] = f"Reference '{branch_or_ref}' not found in repository."
            current_app.logger.warning(f"Ref '{branch_or_ref}' not found in {repo_disk_path} for file {file_path_in_repo}: {e_ref}")
            return details

        file_commits_iter = git_py_repo.iter_commits(rev=resolved_ref.hexsha, paths=file_path_in_repo, max_count=1)
        last_file_commit = next(file_commits_iter, None)

        if last_file_commit:
            details['last_commit_message'] = last_file_commit.message.splitlines()[0] if last_file_commit.message else "[No commit message]"
            # CORRECTED: 'datetime' is the class here
            details['last_commit_date'] = datetime.fromtimestamp(last_file_commit.committed_date, tz=timezone.utc)
        else:
            details['error'] = f"File '{file_path_in_repo}' not found or no history on ref '{branch_or_ref}'."
            return details # If file not found, no creation date is applicable for this ref for this path

        creation_commits_iter = git_py_repo.iter_commits(rev=resolved_ref.hexsha, paths=file_path_in_repo, reverse=True) # Iterate oldest first for this path on this ref
        first_commit_for_file_on_ref = next(creation_commits_iter, None)
        if first_commit_for_file_on_ref:
            # CORRECTED: 'datetime' is the class here
            details['creation_date'] = datetime.fromtimestamp(first_commit_for_file_on_ref.committed_date, tz=timezone.utc)
        else:
             # This case should ideally not be hit if last_file_commit was found.
             if not details['error']:
                details['error'] = (details.get('error') or "") + " Could not determine creation date for this path on ref."

    except InvalidGitRepositoryError:
        details['error'] = "Not a valid Git repository."
    except NoSuchPathError: # This usually means repo_disk_path itself is wrong
        details['error'] = "Repository path does not exist."
    except TypeError as te:
        details['error'] = f"Initialization error with Git library. Check logs. ({te})"
        current_app.logger.error(f"GitPython TypeError in get_file_git_details for {repo_disk_path}, file {file_path_in_repo}: {te}", exc_info=True)
    except Exception as e:
        details['error'] = f"Error accessing file Git history: {type(e).__name__}"
        current_app.logger.error(f"GitPython error in get_file_git_details for {repo_disk_path}, file {file_path_in_repo}, ref {branch_or_ref}: {e}", exc_info=True)
    return details

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
    settings_dict = {}
    try:
        settings_dict['allow_registration'] = (Setting.get('allow_registration', DEFAULT_SETTINGS['allow_registration']) == 'true')
        ollama_url = Setting.get('ollama_api_url', DEFAULT_SETTINGS['ollama_api_url'])
        ollama_model = Setting.get('ollama_model', DEFAULT_SETTINGS['ollama_model'])
        settings_dict['ollama_enabled'] = bool(ollama_url and ollama_model)
        try:
            # Use the defined DEFAULT_MAX_UPLOAD_MB_FALLBACK from your main.py
            max_upload_mb_str = Setting.get('max_upload_size_mb', str(DEFAULT_MAX_UPLOAD_MB_FALLBACK))
            settings_dict['max_upload_mb'] = int(max_upload_mb_str)
        except (ValueError, TypeError):
            settings_dict['max_upload_mb'] = DEFAULT_MAX_UPLOAD_MB_FALLBACK # Fallback on error
            app.logger.warning(f"Invalid max_upload_size_mb setting in inject_settings. Using fallback {DEFAULT_MAX_UPLOAD_MB_FALLBACK}MB.")
    except Exception as e:
        app.logger.error(f"Error injecting settings into context: {e}")
        settings_dict['allow_registration'] = DEFAULT_SETTINGS['allow_registration'] == 'true' # Fallback
        settings_dict['ollama_enabled'] = False # Fallback
        settings_dict['max_upload_mb'] = DEFAULT_MAX_UPLOAD_MB_FALLBACK # Fallback for max_upload_mb too
    return dict(settings=settings_dict)



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
    __tablename__ = 'user'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)
    is_admin = db.Column(db.Boolean, default=False, nullable=False)
    storage_limit_mb = db.Column(db.Integer, nullable=True)
    bio = db.Column(db.String(2500), nullable=True)
    profile_picture_filename = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

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

    # Relationships (ensure all necessary backrefs and cascades are here)
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
        backref=db.backref('followers', lazy='dynamic', cascade="all"), # Added cascade
        lazy='dynamic'
    )

    sent_direct_messages = db.relationship(
        'DirectMessage',
        foreign_keys='DirectMessage.sender_id',
        backref='author',  # Allows DirectMessage.author to get the User object of the sender
        lazy='dynamic',
        cascade="all, delete-orphan",
        order_by='DirectMessage.timestamp'
    )
    # Direct messages received by the user
    received_direct_messages = db.relationship(
        'DirectMessage',
        foreign_keys='DirectMessage.receiver_id',
        backref='recipient', # Allows DirectMessage.recipient to get the User object of the receiver
        lazy='dynamic',
        cascade="all, delete-orphan",
        order_by='DirectMessage.timestamp'
    )

    starred_repositories = db.relationship(
        'GitRepository',  # Use your actual model name GitRepository
        secondary=repo_stars,
        back_populates='starrers',
        lazy='dynamic', # Use dynamic for querying, e.g., count() or applying filters
        cascade="all" # Optional: if a user is deleted, remove their stars
                                      # Be cautious with cascade on many-to-many
    )

    collaborating_repositories = db.relationship(
        'GitRepository',
        secondary=repo_collaborators,
        back_populates='collaborators', # Will be defined in GitRepository model
        lazy='dynamic'
    )

    def is_collaborator_on(self, repo_to_check):
        if not self.is_authenticated:
            return False
        return self.collaborating_repositories.filter(repo_collaborators.c.git_repository_id == repo_to_check.id).count() > 0

    def has_starred_repo(self, repo_to_check): # Changed 'repo' to 'repo_to_check' for clarity
        if not self.is_authenticated: # Anonymous users can't have starred repos
            return False
        return self.starred_repositories.filter(repo_stars.c.git_repository_id == repo_to_check.id).count() > 0

    def star_repo(self, repo_to_star): # Changed 'repo' to 'repo_to_star'
        if not self.has_starred_repo(repo_to_star):
            self.starred_repositories.append(repo_to_star)
            # db.session.commit() # Commit should be handled by the route

    def unstar_repo(self, repo_to_unstar): # Changed 'repo' to 'repo_to_unstar'
        if self.has_starred_repo(repo_to_unstar):
            self.starred_repositories.remove(repo_to_unstar)
            # db.session.commit() # Commit should be handled by the route

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
        # This checks if 'user_to_check' is in the current user's list of followers
        return self.followers.filter(followers.c.follower_id == user_to_check.id).count() > 0

    def get_friends(self):
        """Returns a list of users who mutually follow the current user."""
        friends = []
        # Iterate through users this user is following
        for followed_user in self.followed:
            # Check if that followed_user is also following this user back
            if followed_user.is_following(self): # or self.is_followed_by(followed_user)
                friends.append(followed_user)
        return friends

    def __repr__(self):
        return f'<User {self.username}>'

class GitRepository(db.Model):
    __tablename__ = 'git_repository'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id', name='fk_git_repository_user_id', ondelete='CASCADE'), nullable=False, index=True)
    name = db.Column(db.String(100), nullable=False)  # Repository name (e.g., "my-project")
    description = db.Column(db.Text, nullable=True)
    is_private = db.Column(db.Boolean, default=True, nullable=False)
    disk_path = db.Column(db.String(512), unique=True, nullable=False) # Full path to the .git directory on disk
    forked_from_id = db.Column(db.Integer, db.ForeignKey('git_repository.id', name='fk_git_repository_fork_source_id', ondelete='SET NULL'), nullable=True, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    owner = db.relationship('User', backref=db.backref('git_repositories', lazy='dynamic', cascade="all, delete-orphan"))

    # Self-referential for forks
    # The repository this one was forked from
    source_repo = db.relationship('GitRepository', remote_side=[id], backref=db.backref('forks', lazy='dynamic'), foreign_keys=[forked_from_id])

    # Unique constraint for repository name per user
    __table_args__ = (db.UniqueConstraint('user_id', 'name', name='uq_user_repo_name'),)

    starrers = db.relationship(
        'User', # The User model
        secondary=repo_stars,
        back_populates='starred_repositories',
        lazy='dynamic' # Use dynamic for querying, e.g., count()
        # cascade="all, delete" # Usually not needed here, stars are deleted if user/repo is deleted
    )

    collaborators = db.relationship(
        'User',
        secondary=repo_collaborators,
        back_populates='collaborating_repositories', # Matches User.collaborating_repositories
        lazy='dynamic'
    )

    def add_collaborator(self, user_to_add):
        if not self.is_collaborator(user_to_add) and self.user_id != user_to_add.id: # Owner cannot be a collaborator
            self.collaborators.append(user_to_add)

    def remove_collaborator(self, user_to_remove):
        if self.is_collaborator(user_to_remove):
            self.collaborators.remove(user_to_remove)

    def is_collaborator(self, user_to_check):
        return self.collaborators.filter(repo_collaborators.c.user_id == user_to_check.id).count() > 0

    def __repr__(self):
        return f'<GitRepository {self.id}: {self.owner.username}/{self.name}>'

    def get_clone_url(self, external=False):
        # Generates the HTTP clone URL
        base_url = url_for('git_homepage', _external=True).rstrip('/') if external else url_for('git_homepage').rstrip('/')
        return f"{base_url}/{self.owner.username}/{self.name}.git"

    def get_web_url(self, external=False):
        # Generates the URL to view the repo in the web UI
        return url_for('view_repo_root', owner_username=self.owner.username, repo_short_name=self.name, _external=external)
    @property
    def star_count(self):
        return self.starrers.count()

class CreateFolderForm(FlaskForm):
    """Form for creating a new folder."""
    # Basic validation: required, reasonable length. More could be added.
    name = StringField('Folder Name', validators=[
        DataRequired(message="Folder name cannot be empty."),
        Length(min=1, max=100, message="Folder name must be between 1 and 100 characters.")
        # We'll add custom validation in the route for illegal characters/duplicates
    ])
    submit = SubmitField('Create Folder')

class DirectMessageForm(FlaskForm):
    content = TextAreaField('Message', validators=[Length(max=4000)])
    file = FileField('Attach File', validators=[Optional()])
    # No submit field needed if handled by JS + Enter key

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
    storage_limit_mb = IntegerField(
        'Specific Storage Limit (MB)',
        validators=[
            Optional(),
            NumberRange(min=0, message='Storage limit must be 0 or greater.')
        ],
        # Update description for clarity based on your storage_limit_mb handling
        description=""
    )

    # --- ADD THESE FIELDS ---
    max_file_size = IntegerField(
        'Per User Max File Upload Size (MB)', # Matches the label in admin_edit_user.html
        validators=[Optional(), NumberRange(min=0)], # Allows empty or non-negative numbers
        render_kw={"placeholder": ""}
    )
    password = PasswordField(
        'New Password',
        validators=[
            Optional(), # Password change is optional
            Length(min=6, message="Password must be at least 6 characters long if provided.")
        ]
    )
    confirm_password = PasswordField(
        'Confirm New Password',
        # Only require confirmation if a new password is typed
        validators=[
            EqualTo('password', message='New passwords must match.') if 'password' else Optional()
        ]
    )
    # --- END OF ADDED FIELDS ---

    submit = SubmitField('Update User')

    def __init__(self, original_username=None, original_email=None, *args, **kwargs):
        super(EditUserForm, self).__init__(*args, **kwargs)
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

    # --- ADDED: Custom validator for confirm_password only if password is provided ---
    def validate_confirm_password(self, confirm_password):
        if self.password.data and not confirm_password.data:
            raise ValidationError('Please confirm the new password.')
        if self.password.data and confirm_password.data and self.password.data != confirm_password.data:
            # EqualTo validator should catch this, but an explicit check is fine too
            raise ValidationError('New passwords must match.')
    # --- END ADDED VALIDATOR ---

class EditProfileForm(FlaskForm):
    username = StringField('Username',
                           validators=[DataRequired(), Length(min=4, max=25)],
                           render_kw={'readonly': True})
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
    timestamp = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
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
    upload_date = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
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

    # Relationships
    comments = db.relationship('Comment', foreign_keys='Comment.post_id', backref='post', lazy='select', cascade="all, delete-orphan", order_by=lambda: Comment.timestamp.asc())

    likers = db.relationship('User', secondary=post_likes,
                             lazy='select',  # CHANGED FROM 'dynamic'
                             backref=db.backref('liked_posts', lazy='dynamic', cascade="all"))
    dislikers = db.relationship('User', secondary=post_dislikes,
                                lazy='select',  # CHANGED FROM 'dynamic'
                                backref=db.backref('disliked_posts', lazy='dynamic', cascade="all"))

    original_post = db.relationship('Post', remote_side=[id], backref=db.backref('shares', lazy='dynamic', cascade="all, delete-orphan"))
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

    likers = db.relationship('User', secondary=comment_likers,
                             lazy='select',  # CHANGED FROM 'dynamic'
                             backref=db.backref('liked_comments', lazy='dynamic', cascade="all"))
    dislikers = db.relationship('User', secondary=comment_dislikers,
                                lazy='select',  # CHANGED FROM 'dynamic'
                                backref=db.backref('disliked_comments', lazy='dynamic', cascade="all"))

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
            'reply_count': len(self.replies) if self.replies is not None else 0 # Corrected
        }
        if include_author_details and self.author:
            data['author_username'] = self.author.username
            data['author_profile_pic'] = self.author.profile_picture_filename

        if include_replies and depth < max_depth:
            # self.replies is now a list due to lazy='select'
            data['replies'] = [reply.to_dict(include_author_details=True, include_replies=True, depth=depth+1, max_depth=max_depth) for reply in self.replies]
        else:
            data['replies'] = []

        return data

    def __repr__(self):
        return f'<Comment {self.id} by User {self.user_id} on Post {self.post_id}>'

class Notification(db.Model):
    __tablename__ = 'notification'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=False, index=True)  # The user who receives the notification
    sender_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=True, index=True) # The user who triggered the notification (can be None for system messages)
    type = db.Column(db.String(50), nullable=False, index=True)  # e.g., 'like', 'comment', 'share_post', 'share_comment', 'follow', 'system_message'
    related_post_id = db.Column(db.Integer, db.ForeignKey('post.id', ondelete='CASCADE'), nullable=True, index=True)
    related_comment_id = db.Column(db.Integer, db.ForeignKey('comment.id', ondelete='CASCADE'), nullable=True, index=True)
    related_repo_id = db.Column(db.Integer, db.ForeignKey('git_repository.id', ondelete='CASCADE'), nullable=True, index=True)
    # Add other related_ids if needed, e.g., related_user_id for follows
    message = db.Column(db.Text, nullable=True) # Optional custom message or generated text
    is_read = db.Column(db.Boolean, default=False, nullable=False, index=True)
    timestamp = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False, index=True)

    # Relationships to get sender, post, comment details easily
    recipient = db.relationship('User', foreign_keys=[user_id], backref=db.backref('notifications_received', lazy='dynamic', cascade="all, delete-orphan"))
    sender = db.relationship('User', foreign_keys=[sender_id], backref=db.backref('notifications_sent', lazy='dynamic'))
    post = db.relationship('Post', foreign_keys=[related_post_id], backref=db.backref('related_notifications', lazy='select', cascade="all, delete-orphan"))
    comment = db.relationship('Comment', foreign_keys=[related_comment_id], backref=db.backref('related_notifications', lazy='select', cascade="all, delete-orphan"))
    repository = db.relationship('GitRepository', foreign_keys=[related_repo_id], backref=db.backref('related_notifications_repo', lazy='select', cascade="all, delete-orphan")) # ADD THIS RELATIONSHIP

    def __repr__(self):
        return f'<Notification {self.id} for User {self.user_id} - Type: {self.type}>'

    def to_dict(self):
        sender_username = self.sender.username if self.sender else "System"

        # Initialize default text and link
        text = f"Notification: {self.type}" # Fallback
        primary_link = "#" # Default link for primary_link

        # Initialize URL generating variables
        post_url_val = None
        comment_url_val = None
        repo_url_val = None

        # Construct human-readable message text based on type
        if self.type == 'like_post' and self.post:
            text = f"{sender_username} liked your post: \"{self.post.text_content[:30]}...\"" if self.post.text_content else f"{sender_username} liked your media post."
        elif self.type == 'dislike_post' and self.post:
            text = f"{sender_username} disliked your post: \"{self.post.text_content[:30]}...\"" if self.post.text_content else f"{sender_username} disliked your media post."
        elif self.type == 'comment_on_post' and self.post and self.comment:
            text = f"{sender_username} commented on your post: \"{self.comment.text_content[:30]}...\""
        elif self.type == 'reply_to_comment' and self.post and self.comment and getattr(self.comment, 'parent_comment', None): # Safely check for parent_comment
            text = f"{sender_username} replied to your comment: \"{self.comment.text_content[:30]}...\""
        elif self.type == 'share_post' and self.post:
            text = f"{sender_username} shared your post: \"{self.post.text_content[:30]}...\"" if self.post.text_content else f"{sender_username} shared your media post."
        elif self.type == 'share_comment' and self.comment:
            text = f"{sender_username} shared your comment: \"{self.comment.text_content[:30]}...\""
        elif self.type == 'new_follower':
            text = f"{sender_username} started following you."
        elif self.type == 'new_post_from_followed_user' and self.post:
            text = f"{sender_username} (whom you follow) created a new post: \"{self.post.text_content[:30]}...\"" if self.post.text_content else f"{sender_username} (whom you follow) created a new media post."
        elif self.type == 'repo_collaborator_added' and self.related_repo_id: # We'll add related_repo_id
            # We need to fetch the repo to get its name and owner for the message
            repo = GitRepository.query.get(self.related_repo_id)
            if repo and self.sender: # self.sender is the repo owner who added the collaborator
                text = f"{self.sender.username} added you as a collaborator to the repository: {repo.owner.username}/{repo.name}."
                try:
                    repo_url_val = url_for('view_repo_root', owner_username=repo.owner.username, repo_short_name=repo.name, _external=False)
                except Exception as e:
                    current_app.logger.error(f"Error generating repo_url_val for notification {self.id}: {e}")
            else:
                text = f"You've been added as a collaborator to a repository."

        elif self.type == 'repo_collaborator_removed' and self.related_repo_id: # We'll add related_repo_id
            repo = GitRepository.query.get(self.related_repo_id)
            if repo and self.sender: # self.sender is the repo owner who removed the collaborator
                text = f"{self.sender.username} removed you as a collaborator from the repository: {repo.owner.username}/{repo.name}."
                # No specific link needed for removal, or could link to user's dashboard
                repo_url_val = url_for('git_homepage', _external=False) # Or user's own repo page
            else:
                text = f"You've been removed as a collaborator from a repository."


        # Generate post_url_val if there's a related post
        if self.related_post_id:
            try:
                post_url_val = url_for('view_single_post', post_id=self.related_post_id, _external=False)
            except Exception as e:
                current_app.logger.error(f"Error generating post_url_val for notification {self.id}: {e}")

        # Generate comment_url_val if there's a related comment
        if self.related_comment_id:
            # Try to get the post_id for the comment's URL
            comment_post_id_for_url = None
            if self.post: # If related_post is already loaded via notification.post
                comment_post_id_for_url = self.post.id
            elif self.comment and self.comment.post_id: # Fallback to comment's own post_id
                comment_post_id_for_url = self.comment.post_id

            if comment_post_id_for_url:
                try:
                    comment_url_val = url_for('view_single_post', post_id=comment_post_id_for_url, _anchor=f"comment-{self.related_comment_id}", _external=False)
                except Exception as e:
                    current_app.logger.error(f"Error generating comment_url_val for notification {self.id}: {e}")

        # Determine the primary_link based on notification type and available URLs
        if self.type == 'new_follower' and self.sender_id:
            try:
                primary_link = url_for('user_profile', username=sender_username, _external=False)
            except Exception as e:
                current_app.logger.error(f"Error generating profile_link for new_follower notification {self.id}: {e}")
                primary_link = "#" # Fallback
        elif self.type in ['like_post', 'dislike_post', 'comment_on_post', 'share_post', 'new_post_from_followed_user'] and post_url_val:
            primary_link = post_url_val
        elif self.type == 'reply_to_comment' and comment_url_val:
            primary_link = comment_url_val
        elif self.type == 'share_comment' and self.comment:
            # For shared comments, link to the original comment on its post page
            original_comment_post_id = self.comment.post_id
            if original_comment_post_id:
                try:
                    primary_link = url_for('view_single_post', post_id=original_comment_post_id, _anchor=f"comment-{self.comment.id}", _external=False)
                except Exception as e:
                    current_app.logger.error(f"Error generating link for share_comment notification {self.id}: {e}")
                    primary_link = "#" # Fallback
            else:
                primary_link = "#" # Fallback if no post_id for the comment

        elif self.type == 'repo_collaborator_added' and repo_url_val:
            primary_link = repo_url_val
        elif self.type == 'repo_collaborator_removed' and repo_url_val: # Optional: link somewhere general
            primary_link = repo_url_val

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
            'primary_link': primary_link, # This should now always be defined
            'post_url': post_url_val,     # This should now always be defined (as None or a URL)
            'comment_url': comment_url_val, # This should now always be defined (as None or a URL)
            'repo_url': repo_url_val
        }

def create_notification(recipient_user, sender_user, type, post=None, comment=None, repo=None, custom_message=None, cooldown_minutes=5): # MODIFIED DEFINITION
    """
    Helper function to create and save a notification, with spam prevention.
    - recipient_user: The User object who should receive the notification.
    - sender_user: The User object who triggered the notification.
    - type: String representing the notification type.
    - post: Optional Post object related to the notification.
    - comment: Optional Comment object related to the notification.
    - repo: Optional GitRepository object related to the notification. # ADDED
    - custom_message: Optional string for a specific message.
    - cooldown_minutes: Integer, time window in minutes to check for duplicate notifications.
    """
    if not recipient_user: # Removed sender_user from this specific check as system notifications might not have a sender_user in the same way
        app.logger.warning("Attempted to create notification without recipient.")
        return

    # Prevent self-notification for actions where it doesn't make sense
    # Ensure sender_user exists before trying to access its id
    if sender_user and recipient_user.id == sender_user.id and type in ['like_post', 'dislike_post', 'comment_on_post', 'reply_to_comment', 'share_post', 'share_comment', 'new_follower', 'repo_collaborator_added', 'repo_collaborator_removed']: # Added new types
        app.logger.debug(f"Skipping self-notification for user {recipient_user.id} of type {type}")
        return

    # --- Spam Prevention Check ---
    time_threshold = datetime.now(timezone.utc) - timedelta(minutes=cooldown_minutes) #

    query_existing = Notification.query.filter(
        Notification.user_id == recipient_user.id,
        # Allow sender_id to be None for system type messages if that's a use case
        Notification.sender_id == (sender_user.id if sender_user else None),
        Notification.type == type,
        Notification.timestamp >= time_threshold if cooldown_minutes > 0 else True #
    )

    if post:
        query_existing = query_existing.filter(Notification.related_post_id == post.id)
    else:
        query_existing = query_existing.filter(Notification.related_post_id == None)

    if comment:
        query_existing = query_existing.filter(Notification.related_comment_id == comment.id)
    else:
        query_existing = query_existing.filter(Notification.related_comment_id == None)

    # MODIFIED: Check for repo relation in spam prevention
    if repo: #
        query_existing = query_existing.filter(Notification.related_repo_id == repo.id) #
    else: #
        query_existing = query_existing.filter(Notification.related_repo_id == None) #


    existing_notification = query_existing.first()

    if existing_notification:
        app.logger.info(f"Spam prevention: Similar notification (ID: {existing_notification.id}) already exists for User {recipient_user.id} from User {(sender_user.id if sender_user else 'System')} - Type: {type}. Skipping new notification.")
        return
    # --- End Spam Prevention Check ---

    try:
        notification = Notification(
            user_id=recipient_user.id,
            sender_id=sender_user.id if sender_user else None,
            type=type,
            related_post_id=post.id if post else None,
            related_comment_id=comment.id if comment else None,
            related_repo_id=repo.id if repo else None, # ADDED this argument
            message=custom_message,
            timestamp=datetime.now(timezone.utc) #
        )
        db.session.add(notification)
        db.session.commit()
        app.logger.info(f"Notification created for User {recipient_user.id} from User {(sender_user.id if sender_user else 'System')} - Type: {type}")
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Error creating notification: {e}", exc_info=True)



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

class AdminSettings(db.Model):
    __tablename__ = 'admin_settings' # Explicit table name is good practice
    id = db.Column(db.Integer, primary_key=True)
    allow_registration = db.Column(db.Boolean, default=True)
    default_storage_limit_mb = db.Column(db.Integer, nullable=True)  # Nullable for system default/unlimited
    max_upload_size_mb = db.Column(db.Integer, default=100) # Default max upload size in MB

    # Ollama settings
    ollama_api_url = db.Column(db.String(255), nullable=True)
    ollama_model = db.Column(db.String(100), nullable=True)

    # Email settings
    mail_server = db.Column(db.String(120), nullable=True)
    mail_port = db.Column(db.Integer, nullable=True)
    mail_use_tls = db.Column(db.Boolean, default=True)
    mail_use_ssl = db.Column(db.Boolean, default=False)
    mail_username = db.Column(db.String(120), nullable=True)
    mail_password_hashed = db.Column(db.String(255), nullable=True) # Store hash, not plaintext
    mail_default_sender_name = db.Column(db.String(120), nullable=True, default='PyCloud Notifications')
    mail_default_sender_email = db.Column(db.String(120), nullable=True, default='noreply@example.com') # User should change

    def __repr__(self):
        return f'<AdminSettings {self.id}>'

    # Optional: If you had a password hashing mechanism
    # def set_mail_password(self, password):
    #     if password:
    #         self.mail_password_hashed = generate_password_hash(password).decode('utf-8')
    #     else:
    #         self.mail_password_hashed = None

    # def check_mail_password(self, password):
    #     if self.mail_password_hashed is None:
    #         return False
    #     return check_password_hash(self.mail_password_hashed, password)

    @staticmethod
    def get_settings():
        # This method ensures there's always a settings object returned
        # It will be created if it doesn't exist when this is first called
        # within an app context after tables are created.
        settings = AdminSettings.query.first()
        if not settings:
            print("WARNING: No admin settings found in DB by get_settings(), creating defaults. Ensure init-db ran.")
            # This fallback within get_settings is okay but robust initialization is better.
            # Note: This requires an active app and db context.
            try:
                settings = AdminSettings( # Set your desired defaults here
                    allow_registration=True,
                    max_upload_size_mb=100,
                    default_storage_limit_mb=1024,
                    mail_default_sender_name='PyCloud Notifications',
                    mail_default_sender_email='noreply@example.com'
                )
                db.session.add(settings)
                db.session.commit()
            except Exception as e:
                db.session.rollback()
                current_app.logger.error(f"Failed to create default admin settings in get_settings: {e}")
                # Return an in-memory default if commit fails to prevent crashes, but this is a problem.
                return AdminSettings(allow_registration=True, max_upload_size_mb=100)
        return settings

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
        description=""
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
        # --- THIS IS THE KEY CHANGE ---
        # Query by username using form.username.data
        user = User.query.filter_by(username=form.username.data).first()
        # --- END OF KEY CHANGE ---

        if user:
            if user.is_disabled: # Check if the account is disabled
                flash('Your account has been disabled. Please contact an administrator.', 'danger')
                return redirect(url_for('login'))

            if user.check_password(form.password.data): # Check password
                login_user(user, remember=form.remember.data)
                flash('Login successful!', 'success')
                next_page = request.args.get('next')
                return redirect(next_page or url_for('list_files'))
            else:
                # Password was incorrect
                flash('Login Unsuccessful. Please check username and password.', 'danger')
        else:
            # User was not found by username
            flash('Login Unsuccessful. Please check username and password.', 'danger')

    return render_template('login.html', title='Login', form=form)

@app.route('/logout')
@login_required
def logout():
    """Logs the current user out and sets their status to offline."""
    if current_user.is_authenticated:
        current_user.is_online = False
        # last_seen is not updated here, so it will naturally become older
        try:
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            app.logger.error(f"Error setting user {current_user.id} offline during logout: {e}")

    logout_user()
    flash('You have been logged out.', 'info')
    return redirect(url_for('login'))

@app.route('/api/users/activity_status', methods=['POST'])
@login_required
def api_users_activity_status():
    data = request.get_json()
    if not data or 'user_ids' not in data or not isinstance(data['user_ids'], list):
        return jsonify({"status": "error", "message": "Invalid request. 'user_ids' list is required."}), 400

    user_ids_to_check = data['user_ids']
    statuses = {}

    afk_threshold = timedelta(minutes=30)
    now = datetime.now(timezone.utc) # This is offset-aware

    users_found = User.query.filter(User.id.in_(user_ids_to_check)).all()

    for user_obj in users_found: # Renamed loop variable
        status_string = "offline"
        if user_obj.is_online:
            user_last_seen = user_obj.last_seen
            # --- DEFENSIVE CONVERSION for user_last_seen ---
            if user_last_seen and user_last_seen.tzinfo is None:
                user_last_seen = user_last_seen.replace(tzinfo=timezone.utc)
            # --- END DEFENSIVE CONVERSION ---

            if user_last_seen and (now - user_last_seen) < afk_threshold: # Now comparison is safe
                status_string = "online"
            else:
                status_string = "afk"

        statuses[user_obj.id] = status_string

    return jsonify({"status": "success", "user_statuses": statuses})

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
    # Use the static method to get or create settings
    # This requires the AdminSettings model to be defined
    settings_obj = AdminSettings.get_settings() # This will create if not exists
    if settings_obj is None: # Should not happen if get_settings is robust
         flash("Critical error: Could not load or create admin settings.", "danger")
         return redirect(url_for('index')) # Or some other safe page

    form = AdminSettingsForm(obj=settings_obj) # Load form from DB object

    if form.validate_on_submit():
        form.populate_obj(settings_obj) # Populate DB object from form
        # Handle password separately if it's a special field
        if form.mail_password.data: # Assuming you have a set_mail_password method
             settings_obj.mail_password = form.mail_password.data

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
    """Handles editing a specific user's details, including max_file_size."""
    if not current_user.is_admin:
        flash('You do not have permission to perform this action.', 'danger')
        # Assuming you have an admin_dashboard or similar, or redirect to a safe page
        return redirect(url_for('admin_dashboard')) # Or url_for('admin_list_users') if that's your main admin user page

    user_to_edit = User.query.get_or_404(user_id)

    # Ensure EditUserForm is correctly defined and imported
    # For example, if your form is in 'forms.py': from .forms import EditUserForm
    form = EditUserForm(obj=user_to_edit, # Pre-populate form with existing data
                        original_username=user_to_edit.username,
                        original_email=user_to_edit.email)

    if form.validate_on_submit():
        original_username = user_to_edit.username # For logging if username changes
        user_to_edit.username = form.username.data
        user_to_edit.email = form.email.data

        # Prevent admin from unchecking their own admin status
        if user_to_edit.id == current_user.id:
            # If current admin is editing themselves, their admin status cannot be changed
            # via this form (as the checkbox is disabled).
            # We ensure their is_admin status remains True.
            # No flash message is needed here because no change was attempted via the checkbox.
            user_to_edit.is_admin = True
        else:
            # If editing another user, get the status from the form.
            user_to_edit.is_admin = form.is_admin.data

        # Handle total storage limit (storage_limit_mb)
        storage_limit_val = form.storage_limit_mb.data
        storage_limit_log_msg = ""
        if storage_limit_val is None or storage_limit_val <= 0: # Treat None or 0 (or negative) as "use default"
            user_to_edit.storage_limit_mb = None
            storage_limit_log_msg = "default"
        else:
            user_to_edit.storage_limit_mb = storage_limit_val
            storage_limit_log_msg = f"{storage_limit_val} MB"

        # Handle per-file max size limit (max_file_size) - NEW
        max_file_size_val = form.max_file_size.data
        max_file_size_log_msg = ""
        if max_file_size_val is None or max_file_size_val <= 0: # Treat blank or 0 as "use global default"
            user_to_edit.max_file_size = None # Store NULL in DB
            max_file_size_log_msg = "global default"
        else:
            user_to_edit.max_file_size = max_file_size_val
            max_file_size_log_msg = f"{max_file_size_val} MB"

        # Handle password change if a new password is provided
        if form.password.data:
            if form.password.data == form.confirm_password.data:
                user_to_edit.set_password(form.password.data) # Assuming User model has set_password method
                flash('Password updated successfully.', 'info')
                current_app.logger.info(f"Admin {current_user.username} updated password for user {user_to_edit.username} (ID: {user_id}).")
            else:
                form.password.errors.append("Passwords must match.")
                # Do not proceed with other commits if password validation fails here, re-render form.
                return render_template('admin_edit_user.html',
                                       title=f'Edit User: {user_to_edit.username}',
                                       form=form,
                                       user_to_edit=user_to_edit) # Pass user_to_edit for the template context

        try:
            db.session.commit()
            flash(f'User "{user_to_edit.username}" updated successfully.', 'success')
            current_app.logger.info(
                f"Admin {current_user.username} updated user {original_username} (now {user_to_edit.username}, ID: {user_id}). "
                f"Total Storage Limit: {storage_limit_log_msg}. Max File Size Per Upload: {max_file_size_log_msg}."
            )
            return redirect(url_for('admin_list_users')) # Or wherever your user list is
        except IntegrityError as e:
            db.session.rollback()
            current_app.logger.warning(f"Update failed for user {user_id} (username: {user_to_edit.username}) due to integrity error: {e}")
            if 'users.username' in str(e).lower() or 'user.username' in str(e).lower(): # Adapt to your actual constraint name
                form.username.errors.append("This username is already taken.")
            elif 'users.email' in str(e).lower() or 'user.email' in str(e).lower(): # Adapt to your actual constraint name
                form.email.errors.append("This email is already registered.")
            else:
                flash('Database error: Could not update user due to conflicting data. Check logs.', 'danger')
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error updating user {user_id} by admin {current_user.username}: {e}", exc_info=True)
            flash('An unexpected error occurred while updating the user. Please try again.', 'danger')
        # If commit failed and not redirected, form will re-render with errors.

    elif request.method == 'GET':
        # Populate form with existing data from the user_to_edit object
        # WTForms' obj=user_to_edit in constructor usually handles this,
        # but explicit assignment can be clearer or override if needed.
        form.username.data = user_to_edit.username
        form.email.data = user_to_edit.email
        form.is_admin.data = user_to_edit.is_admin
        form.storage_limit_mb.data = user_to_edit.storage_limit_mb
        form.max_file_size.data = user_to_edit.max_file_size # Populate new field
        # Password fields should remain blank on GET for security
        form.password.data = None
        form.confirm_password.data = None

    # Always pass user_to_edit to the template for displaying info outside the form (like status)
    return render_template('admin_edit_user.html',
                           title=f'Edit User: {user_to_edit.username}',
                           form=form,
                           user_to_edit=user_to_edit) # Changed user_id to user_to_edit for consistency with template


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


@app.route('/photos')
@login_required
def photos():
    """Displays a gallery of the current user's image files."""
    user_upload_path_base = get_user_upload_path(current_user.id) # Get base path for user

    # Fetch image files for the current user
    # Assuming VIEWABLE_IMAGE_MIMES is available in the app's config or globally
    image_files = File.query.filter(
        File.user_id == current_user.id,
        File.mime_type.in_(current_app.config.get('VIEWABLE_IMAGE_MIMES', VIEWABLE_IMAGE_MIMES))
    ).order_by(File.upload_date.desc()).all()

    # Add a URL for each image, making sure to use the file owner's ID for the path
    for img_file in image_files:
        # The view_file route should handle serving the file
        # It already uses file_record.user_id to get the correct path
        img_file.view_url = url_for('view_file', file_id=img_file.id)
        # We can also construct a direct static path if needed for display,
        # but view_file is more robust for permissions, etc.
        # For simplicity in the template, we can pass the stored_filename
        # and construct the path there, or pass a fully qualified URL if preferred.

    return render_template('photos.html', title='My Photos', image_files=image_files)

VIDEO_THUMBNAIL_FOLDER = os.path.join(app.root_path, 'static', 'uploads', 'video_thumbnails')
@app.route('/videos')
@login_required
def videos():
    """Displays a gallery of the current user's video files."""
    # Fetch video files for the current user
    video_files = File.query.filter(
        File.user_id == current_user.id,
        File.mime_type.in_(current_app.config.get('VIEWABLE_VIDEO_MIMES', VIEWABLE_VIDEO_MIMES))
    ).order_by(File.upload_date.desc()).all()

    for vid_file in video_files:
        vid_file.view_url = url_for('view_file', file_id=vid_file.id)
        # MODIFIED: Assign a URL for the poster image
        # This assumes a .jpg thumbnail exists with the same ID as the video file
        # in the static/uploads/video_thumbnails directory.
        thumbnail_filename = f"{vid_file.id}.jpg"
        thumbnail_path_on_disk = os.path.join(VIDEO_THUMBNAIL_FOLDER, thumbnail_filename)
        if os.path.exists(thumbnail_path_on_disk):
            vid_file.poster_url = url_for('static', filename=f'uploads/video_thumbnails/{thumbnail_filename}')
        else:
            # Fallback to None if no thumbnail exists
            vid_file.poster_url = None

    return render_template('videos.html', title='My Videos', video_files=video_files)

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
    limit_display = f"{storage_info['limit_mb']} MB" if storage_info['limit_mb'] is not None else "Unlimited"

    # Conditionally set the limit_type_indicator
    limit_type = storage_info['limit_type']
    if limit_type == 'user':
        limit_type_indicator = ""  # Remove the indicator if it's a user-specific limit
    else: # For 'default' or any other types you might add
        limit_type_indicator = f"({limit_type.capitalize()})"
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

    # --- MODIFIED: Determine Effective Max Upload Size for Display ---
    try:
        global_max_upload_mb_str = Setting.get('max_upload_size_mb', str(DEFAULT_MAX_UPLOAD_MB_FALLBACK))
        global_max_upload_mb = int(global_max_upload_mb_str)
    except (ValueError, TypeError):
        app.logger.warning(f"Invalid global 'max_upload_size_mb' setting in list_files. Using fallback {DEFAULT_MAX_UPLOAD_MB_FALLBACK}MB.")
        global_max_upload_mb = DEFAULT_MAX_UPLOAD_MB_FALLBACK

    effective_display_max_upload_mb = global_max_upload_mb # Start with global default

    # Check for user-specific override
    if current_user.max_file_size is not None and current_user.max_file_size > 0:
        effective_display_max_upload_mb = current_user.max_file_size

    # Consider server's MAX_CONTENT_LENGTH as an absolute cap for display if it's lower
    # and if effective_display_max_upload_mb is not already effectively unlimited (e.g. very large)
    server_max_content_bytes = current_app.config.get('MAX_CONTENT_LENGTH')
    if server_max_content_bytes:
        server_max_content_mb = server_max_content_bytes // (1024 * 1024)
        if server_max_content_mb < effective_display_max_upload_mb:
            effective_display_max_upload_mb = server_max_content_mb
    # --- END OF MODIFIED SECTION ---

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
                           max_upload_mb=effective_display_max_upload_mb, # Pass the effective limit
                           upload_form=upload_form,
                           create_folder_form=create_folder_form,
                           clipboard_json=clipboard_json)


def allowed_file(filename):
    return bool(filename) # Returns True if filename is not empty.

@app.route('/files/upload', methods=['POST'])
@login_required
def upload_file():
    if 'file' not in request.files:
        # If the client expects JSON, return JSON error
        if request.accept_mimetypes.accept_json and not request.accept_mimetypes.accept_html:
            return jsonify({"status": "error", "message": "No file part in the request."}), 400
        flash('No file part in the request.', 'danger')
        return redirect(request.referrer or url_for('list_files'))

    file = request.files['file']
    if not file or file.filename == '':
        if request.accept_mimetypes.accept_json and not request.accept_mimetypes.accept_html:
            return jsonify({"status": "error", "message": "No file selected for uploading."}), 400
        flash('No file selected for uploading.', 'warning')
        return redirect(request.referrer or url_for('list_files'))

    # Determine effective limits for the current user
    user_specific_max_file_size_mb = current_user.max_file_size

    system_default_max_file_size_mb_str = Setting.get('max_upload_size_mb', str(DEFAULT_MAX_UPLOAD_MB_FALLBACK))
    try:
        system_default_max_file_size_mb = int(system_default_max_file_size_mb_str)
    except (ValueError, TypeError):
        system_default_max_file_size_mb = DEFAULT_MAX_UPLOAD_MB_FALLBACK
        current_app.logger.warning(
            f"Invalid 'max_upload_size_mb' in Setting table ('{system_default_max_file_size_mb_str}'). "
            f"Falling back to {DEFAULT_MAX_UPLOAD_MB_FALLBACK}MB for system default."
        )

    effective_max_file_size_mb = user_specific_max_file_size_mb if user_specific_max_file_size_mb is not None and user_specific_max_file_size_mb > 0 else system_default_max_file_size_mb
    effective_max_file_size_bytes = effective_max_file_size_mb * 1024 * 1024

    user_specific_storage_limit_mb = current_user.storage_limit_mb
    system_default_storage_limit_mb_str = Setting.get('default_storage_limit_mb', '1024')
    try:
        system_default_storage_limit_mb = int(system_default_storage_limit_mb_str)
    except (ValueError, TypeError):
        system_default_storage_limit_mb = 1024
        current_app.logger.warning(
            f"Invalid 'default_storage_limit_mb' in Setting table ('{system_default_storage_limit_mb_str}'). "
            f"Falling back to {1024}MB for system default."
        )
    effective_storage_limit_mb = user_specific_storage_limit_mb if user_specific_storage_limit_mb is not None else system_default_storage_limit_mb

    global_max_content_bytes = current_app.config.get('MAX_CONTENT_LENGTH')

    if allowed_file(file.filename):
        filename = secure_filename(file.filename)

        file.seek(0, os.SEEK_END)
        file_size_bytes = file.tell()
        file.seek(0)

        error_msg = None
        status_code = 200

        if global_max_content_bytes is not None and file_size_bytes > global_max_content_bytes:
            global_max_content_mb = global_max_content_bytes / (1024 * 1024)
            error_msg = f"File is too large. Maximum allowed request size is {global_max_content_mb:.2f} MB."
            status_code = 413
        elif file_size_bytes > effective_max_file_size_bytes:
            error_msg = f"File exceeds your maximum allowed upload size of {effective_max_file_size_mb} MB."
            status_code = 413
        else:
            storage_info = get_user_storage_info(current_user)
            available_bytes = storage_info['limit_bytes'] - storage_info['usage_bytes']
            if file_size_bytes > available_bytes:
                req_mb = round(file_size_bytes / (1024*1024), 1)
                avail_mb = round(available_bytes / (1024*1024), 1) if available_bytes != float('inf') else float('inf')
                used_mb = round(storage_info['usage_bytes'] / (1024*1024), 1)
                limit_mb_display = f"{storage_info['limit_mb']} MB" if storage_info['limit_mb'] is not None else "Unlimited"
                error_msg = f"Uploading this file would exceed your storage limit. Requires {req_mb} MB, {avail_mb} MB free (Used: {used_mb} MB, Limit: {limit_mb_display})."
                status_code = 413

        if error_msg:
            if request.accept_mimetypes.accept_json and not request.accept_mimetypes.accept_html:
                return jsonify({"status": "error", "message": error_msg}), status_code
            flash(error_msg, "danger")
            return redirect(request.referrer or url_for('list_files'))

        user_upload_folder = get_user_upload_path(current_user.id)
        if not os.path.exists(user_upload_folder):
            try:
                os.makedirs(user_upload_folder)
            except OSError as e:
                current_app.logger.error(f"Could not create upload directory {user_upload_folder}: {e}")
                if request.accept_mimetypes.accept_json and not request.accept_mimetypes.accept_html:
                    return jsonify({"status": "error", "message": "Could not create storage directory."}), 500
                flash("Could not create storage directory. Please contact support.", "danger")
                return redirect(request.referrer or url_for('list_files'))

        target_parent_folder_id = request.form.get('parent_folder_id')
        if target_parent_folder_id == 'None' or target_parent_folder_id == '':
            target_parent_folder_id = None
        elif target_parent_folder_id is not None:
            try:
                target_parent_folder_id = int(target_parent_folder_id)
                if not Folder.query.filter_by(id=target_parent_folder_id, user_id=current_user.id).first():
                    if request.accept_mimetypes.accept_json and not request.accept_mimetypes.accept_html:
                        return jsonify({"status": "error", "message": "Target folder not found or invalid."}), 400
                    flash("Target folder not found or invalid.", "danger")
                    return redirect(request.referrer or url_for('list_files'))
            except ValueError:
                if request.accept_mimetypes.accept_json and not request.accept_mimetypes.accept_html:
                    return jsonify({"status": "error", "message": "Invalid target folder ID."}), 400
                flash("Invalid target folder ID.", "danger")
                return redirect(request.referrer or url_for('list_files'))

        original_filename_for_db = filename
        _, ext = os.path.splitext(filename)
        stored_filename_on_disk = str(uuid.uuid4()) + ext
        file_path_on_disk = os.path.join(user_upload_folder, stored_filename_on_disk)

        counter = 1
        temp_original_filename = original_filename_for_db
        while File.query.filter_by(user_id=current_user.id, parent_folder_id=target_parent_folder_id, original_filename=temp_original_filename).first():
            base, extension = os.path.splitext(original_filename_for_db)
            temp_original_filename = f"{base}_{counter}{extension}"
            counter += 1
        final_original_filename_for_db = temp_original_filename

        try:
            file.save(file_path_on_disk)
            mime_type, _ = mimetypes.guess_type(file_path_on_disk)
            mime_type = mime_type or 'application/octet-stream'

            new_file = File(
                original_filename=final_original_filename_for_db,
                stored_filename=stored_filename_on_disk,
                filesize=file_size_bytes,
                mime_type=mime_type,
                user_id=current_user.id,
                parent_folder_id=target_parent_folder_id
            )
            db.session.add(new_file)
            db.session.commit()

            # --- NEW: Thumbnail Generation for Videos ---
            if new_file.mime_type and new_file.mime_type.startswith('video/'):
                thumbnail_filename = f"{new_file.id}.jpg"
                thumbnail_path = os.path.join(VIDEO_THUMBNAIL_FOLDER, thumbnail_filename)
                video_input_path = file_path_on_disk # The full path to the uploaded video

                # Ensure the thumbnail directory exists (already handled in create_db, but good to be safe)
                os.makedirs(VIDEO_THUMBNAIL_FOLDER, exist_ok=True)

                try:
                    # ffmpeg command to extract a frame at 1 second mark, resize to 320px width, and save as JPG
                    # "-ss 00:00:01" seeks to 1 second
                    # "-vframes 1" extracts only one frame
                    # "-q:v 2" sets video quality (2 is high quality for JPEG)
                    # "-vf scale='min(320,iw):-1'" scales the width to a maximum of 320px, preserving aspect ratio
                    ffmpeg_command = [
                        "ffmpeg", "-i", video_input_path,
                        "-ss", "00:00:01",
                        "-vframes", "1",
                        "-q:v", "2",
                        "-vf", "scale='min(320,iw):-1'",
                        thumbnail_path
                    ]
                    app.logger.info(f"Attempting to generate thumbnail for video ID {new_file.id}: {' '.join(ffmpeg_command)}")
                    subprocess.run(ffmpeg_command, check=True, capture_output=True, text=True, timeout=60)
                    app.logger.info(f"Thumbnail generated successfully for video ID {new_file.id} at {thumbnail_path}")
                except FileNotFoundError:
                    app.logger.warning("ffmpeg not found. Please ensure it is installed and in your system's PATH to enable video thumbnail generation.")
                except subprocess.CalledProcessError as e:
                    app.logger.error(f"ffmpeg failed to generate thumbnail for video ID {new_file.id}. Stderr: {e.stderr}", exc_info=True)
                except subprocess.TimeoutExpired:
                    app.logger.error(f"ffmpeg timed out generating thumbnail for video ID {new_file.id}.")
                except Exception as e:
                    app.logger.error(f"Unexpected error during thumbnail generation for video ID {new_file.id}: {e}", exc_info=True)
            # --- END NEW: Thumbnail Generation ---

            if request.accept_mimetypes.accept_json and not request.accept_mimetypes.accept_html:
                # For AJAX, return JSON success (client should then refresh file list or update UI)
                return jsonify({
                    "status": "success",
                    "message": f"File '{final_original_filename_for_db}' uploaded successfully!",
                    "file": { # Optionally return some info about the uploaded file
                        "id": new_file.id,
                        "original_filename": new_file.original_filename,
                        "filesize": new_file.filesize,
                        "mime_type": new_file.mime_type,
                        "parent_folder_id": new_file.parent_folder_id
                    }
                }), 201 # 201 Created
            else:
                # For standard form submission, flash and redirect
                flash(f"File '{final_original_filename_for_db}' uploaded successfully!", "success")
                redirect_url = url_for('list_files', folder_id=target_parent_folder_id) if target_parent_folder_id else url_for('list_files')
                return redirect(request.referrer or redirect_url)

        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error saving file or DB record: {e}", exc_info=True)
            error_message_commit = f"An error occurred while uploading '{final_original_filename_for_db}'. Error: {e}"
            if os.path.exists(file_path_on_disk):
                try:
                    os.remove(file_path_on_disk)
                except Exception as e_remove:
                    current_app.logger.error(f"Failed to remove partially uploaded file {file_path_on_disk}: {e_remove}")

            if request.accept_mimetypes.accept_json and not request.accept_mimetypes.accept_html:
                return jsonify({"status": "error", "message": error_message_commit}), 500
            else:
                flash(error_message_commit, "danger")
                return redirect(request.referrer or url_for('list_files', folder_id=target_parent_folder_id))
    else:
        # This case now means file.filename was empty, already handled at the top.
        # If allowed_file were more complex, this would be the "file type not allowed" branch.
        if request.accept_mimetypes.accept_json and not request.accept_mimetypes.accept_html:
            return jsonify({"status": "error", "message": "File type not allowed or no file selected."}), 400
        flash('File type not allowed or no file selected.', 'warning')
        return redirect(request.referrer or url_for('list_files'))

@app.route('/files/download/<int:file_id>')
@login_required
def download_file(file_id):
    file_record = File.query.get_or_404(file_id)

    can_access = False
    # 1. Check if current user is the owner
    if file_record.owner == current_user:
        can_access = True
    else:
        # 2. Check if file is in a GroupChatMessage (existing logic)
        if GroupChatMessage.query.filter_by(file_id=file_record.id).first():
            can_access = True # Authenticated users can access files shared in the global group chat

        # 3. ADD THIS: Check if file is in a DirectMessage involving the current user
    if not can_access:
        app.logger.warning(f"Access denied: User {current_user.id} attempted download of file {file_id}. Owner: {file_record.user_id}. Not shared in chat or user is not owner.")
        abort(403)  # Forbidden

    user_upload_path = get_user_upload_path(file_record.user_id)
    full_file_path = os.path.join(user_upload_path, file_record.stored_filename)

    try:
        if not os.path.exists(full_file_path):
            app.logger.error(f"File not found on disk for record {file_id}: {file_record.stored_filename} in {user_upload_path}")
            abort(404)

        safe_original_filename = file_record.original_filename.replace('"', '\\"')

        # Determine if it's a problematic image type (like .webp for you)
        # You might extend this to other image/video types if they also misbehave
        _, file_extension = os.path.splitext(file_record.original_filename)
        file_extension = file_extension.lower()

        if file_extension == '.webp' or file_extension == '.avif': # Add other problematic extensions
            # --- Handle problematic files by zipping on the fly ---
            with tempfile.TemporaryDirectory() as temp_dir:
                zip_file_path = os.path.join(temp_dir, f"{os.path.splitext(file_record.original_filename)[0]}.zip")

                with zipfile.ZipFile(zip_file_path, 'w', zipfile.ZIP_DEFLATED) as zf:
                    zf.write(full_file_path, arcname=file_record.original_filename) # Add original file to zip

                # Now send the zip file
                response = send_file(
                    zip_file_path,
                    mimetype='application/zip', # Explicitly zip MIME type
                    as_attachment=True,
                    download_name=f"{os.path.splitext(file_record.original_filename)[0]}.zip", # Suggest .zip filename
                    conditional=True # Enable browser caching headers
                )
                response.headers['X-Content-Type-Options'] = 'nosniff'
                return response
        else:
            # --- For non-problematic files, send as is ---
            mime_type = file_record.mime_type or mimetypes.guess_type(full_file_path)[0] or 'application/octet-stream'
            response = send_file(
                full_file_path,
                mimetype=mime_type,
                as_attachment=True,
                download_name=safe_original_filename,
                conditional=True
            )
            response.headers['X-Content-Type-Options'] = 'nosniff'
            return response

    except FileNotFoundError:
        app.logger.error(f"File not found on disk for record {file_id}: {file_record.stored_filename} in {user_upload_path}")
        abort(404)
    except Exception as e:
        app.logger.error(f"Error downloading file {file_id} for user {current_user.id}: {e}", exc_info=True)
        flash("An error occurred while trying to download the file.", "danger")
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
        # 2. Check if file is in a GroupChatMessage (existing logic)
        if GroupChatMessage.query.filter_by(file_id=file_record.id).first():
            can_access = True

        # 3. ADD THIS: Check if file is in a DirectMessage involving the current user
        if not can_access:
            dm_association = DirectMessage.query.filter(
                DirectMessage.file_id == file_record.id,
                ((DirectMessage.sender_id == current_user.id) | (DirectMessage.receiver_id == current_user.id))
            ).first()
            if dm_association:
                if file_record.user_id == dm_association.sender_id or file_record.user_id == dm_association.receiver_id:
                    can_access = True

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
        # Eager load the 'user' relationship to get sender details (username, profile_picture_filename)
        db_messages = current_user.ollama_chat_messages.options(
            db.joinedload(OllamaChatMessage.user)
        ).order_by(OllamaChatMessage.timestamp).all()
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
        # Eager load the 'user' relationship for history context
        db_messages = current_user.ollama_chat_messages.options(
            db.joinedload(OllamaChatMessage.user)
        ).order_by(OllamaChatMessage.timestamp).all()
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
            db.session.add(user_msg_db)
            db.session.add(ai_msg_db)
            db.session.commit()
            # Refresh the AI message object to ensure it has its 'id' and any relationships loaded
            # before calling to_dict().
            db.session.refresh(ai_msg_db)
            app.logger.info(f"API: Saved user/ollama chat messages for user {current_user.id}")

            return jsonify({
                "status": "success",
                "ai_message": ai_msg_db.to_dict() # NOW it returns a dict with all sender details
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

@app.route('/admin/disable_user/<int:user_id>', methods=['POST'])
@login_required
# @admin_required # Make sure you have or implement this decorator
def disable_user(user_id):
    if not current_user.is_admin: # Example check, adapt to your admin logic
        flash('You are not authorized to perform this action.', 'danger')
        return redirect(url_for('admin_list_users'))
    user = User.query.get_or_404(user_id)
    if user.id == current_user.id:
        flash('You cannot disable yourself.', 'danger')
        return redirect(url_for('admin_list_users'))
    user.is_disabled = True
    db.session.commit()
    flash(f'User {user.username} has been disabled.', 'success')
    return redirect(url_for('admin_list_users'))

@app.route('/admin/enable_user/<int:user_id>', methods=['POST'])
@login_required
# @admin_required
def enable_user(user_id):
    if not current_user.is_admin: # Example check
        flash('You are not authorized to perform this action.', 'danger')
        return redirect(url_for('admin_list_users'))
    user = User.query.get_or_404(user_id)
    user.is_disabled = False
    db.session.commit()
    flash(f'User {user.username} has been enabled.', 'success')
    return redirect(url_for('admin_list_users'))

@app.route('/admin/delete_user/<int:user_id>', methods=['POST'])
@login_required
# @admin_required
def delete_user(user_id):
    if not current_user.is_admin: # Example check
        flash('You are not authorized to perform this action.', 'danger')
        return redirect(url_for('admin_list_users'))
    user_to_delete = User.query.get_or_404(user_id)

    if user_to_delete.id == current_user.id:
        flash("You cannot delete yourself.", "danger")
        return redirect(url_for('admin_list_users'))

    if not user_to_delete.is_disabled:
        flash(f'User {user_to_delete.username} must be disabled before they can be deleted.', 'warning')
        return redirect(url_for('admin_list_users'))

    # Optional: Add more cleanup here, e.g., delete user's posts, files, etc.
    # Example:
    # Post.query.filter_by(author=user_to_delete).delete()
    # UploadedFile.query.filter_by(user_id=user_to_delete.id).delete()
    # Friend.query.filter((Friend.user_id == user_id) | (Friend.friend_id == user_id)).delete()
    # ... and so on for all related data

    db.session.delete(user_to_delete)
    db.session.commit()
    flash(f'User {user_to_delete.username} has been deleted.', 'success')
    return redirect(url_for('admin_list_users'))

# You'll likely integrate the max_file_size update into your existing admin_edit_user route
# or create a dedicated one. For now, let's assume it's part of admin_edit_user.


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

@app.before_request
def update_user_activity():
    if current_user.is_authenticated:
        current_user.last_seen = datetime.now(timezone.utc)
        current_user.is_online = True
        # Commit directly here or rely on other operations to commit.
        # For frequent updates, consider committing less often if performance becomes an issue,
        # but for last_seen, immediate commit is usually fine.
        try:
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            app.logger.error(f"Error updating user activity for {current_user.id}: {e}")

@app.route('/profile/edit', methods=['GET', 'POST'])
@login_required
def edit_profile():
    form = EditProfileForm(original_username=current_user.username, original_email=current_user.email)
    if form.validate_on_submit():
        # Update user text data (username, email, bio, links...)
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
    try:
        db.session.commit()
        flash(f'You are now following {username}.', 'success')
        # Notify the user who was followed
        create_notification(
            recipient_user=user_to_follow,
            sender_user=current_user,
            type='new_follower'
        )
        app.logger.info(f"User {current_user.username} started following {user_to_follow.username}. Notification created for {user_to_follow.username}.")

    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Error during follow action or notification creation by {current_user.username} for {username}: {e}", exc_info=True)
        flash('An error occurred while trying to follow the user.', 'danger')

    return redirect(request.referrer or url_for('user_profile', username=username))

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
    return redirect(request.referrer or url_for('user_profile', username=username))


@app.route('/notifications')
@login_required
def notifications_page():
    page = request.args.get('page', 1, type=int)

    # Fetch unread notifications for the current user to mark them as read
    unread_notifications_to_mark = current_user.notifications_received.filter_by(is_read=False).all()
    if unread_notifications_to_mark:
        for notification_instance in unread_notifications_to_mark:
            notification_instance.is_read = True
        try:
            db.session.commit()
            app.logger.info(f"Marked {len(unread_notifications_to_mark)} notifications as read for user {current_user.id} upon visiting notifications page.")
        except Exception as e:
            db.session.rollback()
            app.logger.error(f"Error marking notifications as read for user {current_user.id} on page visit: {e}", exc_info=True)
            # Optionally flash a message, though it might be too noisy for an automatic background action
            # flash("Could not update notification read status.", "warning")

    # Now fetch the paginated list for display (they will all appear as read for this view)
    notifications_pagination_obj = current_user.notifications_received.order_by(
        Notification.timestamp.desc() # Now primarily order by timestamp descending, as is_read is less relevant after marking all
    ).paginate(page=page, per_page=15)

    current_page_notification_instances = notifications_pagination_obj.items
    processed_notifications_list = [notification.to_dict() for notification in current_page_notification_instances]

    return render_template('notifications.html',
                           title='My Notifications',
                           processed_notifications=processed_notifications_list,
                           notifications_pagination_obj=notifications_pagination_obj)


@app.route('/api/notifications/unread_count')
@login_required
def api_unread_notification_count():
    try:
        count = current_user.notifications_received.filter_by(is_read=False).count()
        return jsonify({'status': 'success', 'unread_count': count})
    except Exception as e:
        app.logger.error(f"Error fetching unread notification count for user {current_user.id}: {e}", exc_info=True)
        return jsonify({'status': 'error', 'message': 'Could not fetch unread count.'}), 500

@app.route('/api/notifications/dismiss/<int:notification_id>', methods=['POST'])
@login_required
def api_dismiss_notification(notification_id):
    notification = Notification.query.filter_by(id=notification_id, user_id=current_user.id).first_or_404()
    try:
        db.session.delete(notification) # Changed from marking as read to deleting
        db.session.commit()
        app.logger.info(f"Notification {notification_id} deleted for user {current_user.id}")

        # Recalculate unread count to send back (and for navbar update)
        unread_count = current_user.notifications_received.filter_by(is_read=False).count()
        return jsonify({'status': 'success', 'message': 'Notification deleted.', 'unread_count': unread_count})
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Error deleting notification {notification_id} for user {current_user.id}: {e}", exc_info=True)
        return jsonify({'status': 'error', 'message': 'Could not delete notification.'}), 500


@app.route('/api/notifications/mark_all_read', methods=['POST'])
@login_required
def api_mark_all_notifications_read():
    try:
        unread_notifications = current_user.notifications_received.filter_by(is_read=False).all()
        for notification in unread_notifications:
            notification.is_read = True
        db.session.commit()
        app.logger.info(f"All unread notifications marked as read for user {current_user.id}")
        return jsonify({'status': 'success', 'message': 'All notifications marked as read.', 'unread_count': 0})
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Error marking all notifications as read for user {current_user.id}: {e}", exc_info=True)
        return jsonify({'status': 'error', 'message': 'Could not mark all notifications as read.'}), 500


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
        query = query.outerjoin(Comment, Post.id == Comment.post_id)\
                       .group_by(Post.id)\
                       .order_by(db.func.count(Comment.id).desc(), Post.timestamp.desc())
    elif sort_by == 'comments_asc':
         query = query.outerjoin(Comment, Post.id == Comment.post_id)\
                        .group_by(Post.id)\
                        .order_by(db.func.count(Comment.id).asc(), Post.timestamp.desc())
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
            db.selectinload(Comment.replies).options(
                db.joinedload(Comment.author).load_only(User.username, User.profile_picture_filename, User.id),
                db.selectinload(Comment.likers).load_only(User.id),
                db.selectinload(Comment.dislikers).load_only(User.id)
            )
        ),
        db.selectinload(Post.likers).load_only(User.id),
        db.selectinload(Post.dislikers).load_only(User.id)
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
    # Apply the same eager loading options as in post_feed
    post = Post.query.options(
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
            db.selectinload(Comment.replies).options(
                db.joinedload(Comment.author).load_only(User.username, User.profile_picture_filename, User.id),
                db.selectinload(Comment.likers).load_only(User.id),
                db.selectinload(Comment.dislikers).load_only(User.id)
            )
        ),
        db.selectinload(Post.likers).load_only(User.id),
        db.selectinload(Post.dislikers).load_only(User.id)
    ).get_or_404(post_id)

    comment_form = CommentForm()
    return render_template('view_single_post.html',
                           title=f"Post by {post.author.username}",
                           post=post,
                           comment_form=comment_form,
                           csrf_token=generate_csrf)

@app.route('/post/new', methods=['GET', 'POST'])
@login_required
def create_post():
    form = CreatePostForm()
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
        upload_path = get_post_media_path()
        picture_path = None # Initialize for potential cleanup
        video_path = None   # Initialize for potential cleanup

        if form.photo.data:
            try:
                picture_file = form.photo.data
                # Basic file size check example (can be more robust)
                picture_file.seek(0, os.SEEK_END)
                file_size = picture_file.tell()
                picture_file.seek(0)
                if file_size > max_photo_mb * 1024 * 1024:
                    flash(f'Photo exceeds the maximum size of {max_photo_mb} MB.', 'danger')
                    # Need to return render_template here to show the form again with error
                    return render_template('create_post.html', title='New Post', form=form, max_photo_upload_mb=max_photo_mb, max_video_upload_mb=max_video_mb)

                ext = os.path.splitext(secure_filename(picture_file.filename))[1].lower()
                photo_fn = str(uuid.uuid4()) + ext
                picture_path = os.path.join(upload_path, photo_fn)
                picture_file.save(picture_path)
                app.logger.info(f"Post photo saved: {photo_fn}")
            except Exception as e:
                app.logger.error(f"Error uploading post photo: {e}", exc_info=True)
                flash("Error uploading photo.", "danger")
                photo_fn = None

        if form.video.data and not photo_fn:
            try:
                video_file = form.video.data
                video_file.seek(0, os.SEEK_END)
                file_size = video_file.tell()
                video_file.seek(0)
                if file_size > max_video_mb * 1024 * 1024:
                    flash(f'Video exceeds the maximum size of {max_video_mb} MB.', 'danger')
                    return render_template('create_post.html', title='New Post', form=form, max_photo_upload_mb=max_photo_mb, max_video_upload_mb=max_video_mb)

                ext = os.path.splitext(secure_filename(video_file.filename))[1].lower()
                video_fn = str(uuid.uuid4()) + ext
                video_path = os.path.join(upload_path, video_fn)
                video_file.save(video_path)
                app.logger.info(f"Post video saved: {video_fn}")
            except Exception as e:
                app.logger.error(f"Error uploading post video: {e}", exc_info=True)
                flash("Error uploading video.", "danger")
                video_fn = None
        elif form.video.data and photo_fn:
            flash("You can upload a photo OR a video, not both.", "warning")

        if not form.text_content.data and not photo_fn and not video_fn:
            flash('A post must have text, a photo, or a video.', 'warning')
        elif form.video.data and photo_fn:
            pass # Flash message already shown
        else:
            try:
                new_post = Post(user_id=current_user.id,
                            text_content=form.text_content.data if form.text_content.data else None,
                            photo_filename=photo_fn,
                            video_filename=video_fn)
                db.session.add(new_post)
                db.session.commit()
                flash('Post created!', 'success')
                app.logger.info(f"Post {new_post.id} created by user {current_user.id}")

                # The 'current_user.followers' relationship should give a list of User objects who follow current_user.
                # If 'followers' is on the 'User' who *is followed* (i.e., user.followers gives who follows them), this is correct.
                if current_user.followers: # Check if the collection exists and is not None
                    for follower in current_user.followers:
                        if follower.id != current_user.id: # Don't notify self
                            create_notification(
                                recipient_user=follower,
                                sender_user=current_user,
                                type='new_post_from_followed_user',
                                post=new_post
                            )
                            app.logger.info(f"Notified follower {follower.username} about new post {new_post.id} from {current_user.username}")

                return redirect(url_for('user_profile', username=current_user.username))
            except Exception as e:
                db.session.rollback()
                app.logger.error(f"Error saving post to DB or notifying followers: {e}", exc_info=True)
                flash("An error occurred while saving the post.", "danger")
                if photo_fn and picture_path and os.path.exists(picture_path): os.remove(picture_path)
                if video_fn and video_path and os.path.exists(video_path): os.remove(video_path)

    return render_template('create_post.html',
                           title='New Post',
                           form=form,
                           max_photo_upload_mb=max_photo_mb,
                           max_video_upload_mb=max_video_mb)

@app.route('/api/files/batch_delete', methods=['POST'])
@login_required
def api_batch_delete():
    data = request.get_json()
    if not data or 'items' not in data or not isinstance(data['items'], list):
        app.logger.error(f"Batch delete request failed for user {current_user.id}: Invalid payload format. Data: {data}")
        return jsonify({"status": "error", "message": "Invalid request payload. 'items' array is required."}), 400

    items_to_delete = data['items']
    if not items_to_delete:
        return jsonify({"status": "success", "message": "No items specified for deletion."}), 200

    deleted_count = 0
    errors = []
    user_upload_path = get_user_upload_path(current_user.id)

    # It's crucial to handle this as a single transaction or be very careful about partial deletions.
    # For simplicity, we'll try to delete all and report errors.
    # A more robust solution might group DB operations and commit at the end,
    # or handle each deletion individually with its own error reporting.

    for item_data in items_to_delete:
        item_id = item_data.get('id')
        item_type = item_data.get('type')
        item_name_for_log = item_data.get('name', f'{item_type} ID {item_id}') # For logging

        if not item_id or not item_type:
            errors.append({"item": item_name_for_log, "error": "Missing ID or type."})
            app.logger.warning(f"Batch delete: Skipping item due to missing ID/type for user {current_user.id}. Item data: {item_data}")
            continue

        try:
            item_id = int(item_id) # Ensure ID is integer for DB query
        except ValueError:
            errors.append({"item": item_name_for_log, "error": "Invalid item ID format."})
            app.logger.warning(f"Batch delete: Skipping item due to invalid ID format for user {current_user.id}. Item ID: {item_data.get('id')}")
            continue

        if item_type == 'file':
            file_record = File.query.get(item_id) # Use get() for PK lookup
            if not file_record:
                errors.append({"item": item_name_for_log, "error": "File not found."})
                app.logger.warning(f"Batch delete: File ID {item_id} not found for user {current_user.id}.")
                continue
            if file_record.user_id != current_user.id:
                errors.append({"item": item_name_for_log, "error": "Permission denied."})
                app.logger.warning(f"Batch delete: User {current_user.id} lacks permission for file {item_id}.")
                continue

            try:
                full_file_path = os.path.join(user_upload_path, file_record.stored_filename)
                if os.path.exists(full_file_path):
                    os.remove(full_file_path)
                db.session.delete(file_record)
                # Commit after each successful deletion to make it more atomic per item,
                # or collect all operations and commit once at the end.
                # Committing per item means partial success is possible.
                db.session.commit()
                deleted_count += 1
                app.logger.info(f"Batch delete: Successfully deleted file '{file_record.original_filename}' (ID: {item_id}) for user {current_user.id}.")
            except Exception as e:
                db.session.rollback()
                error_msg = f"Error deleting file '{file_record.original_filename}': {str(e)}"
                errors.append({"item": item_name_for_log, "error": error_msg})
                app.logger.error(f"Batch delete: {error_msg} for user {current_user.id}", exc_info=True)

        elif item_type == 'folder':
            folder_record = Folder.query.get(item_id) # Use get() for PK lookup
            if not folder_record:
                errors.append({"item": item_name_for_log, "error": "Folder not found."})
                app.logger.warning(f"Batch delete: Folder ID {item_id} not found for user {current_user.id}.")
                continue
            if folder_record.user_id != current_user.id:
                errors.append({"item": item_name_for_log, "error": "Permission denied."})
                app.logger.warning(f"Batch delete: User {current_user.id} lacks permission for folder {item_id}.")
                continue

            try:
                # delete_folder_recursive handles its own DB operations but expects an outer commit.
                # For batch, we need to adjust or ensure it's compatible.
                # Let's assume delete_folder_recursive is designed to be called and then committed.
                delete_folder_recursive(folder_record, current_user.id) # This function should add to session
                db.session.commit() # Commit after this folder and its contents are processed
                deleted_count += 1
                app.logger.info(f"Batch delete: Successfully deleted folder '{folder_record.name}' (ID: {item_id}) and its contents for user {current_user.id}.")
            except Exception as e:
                db.session.rollback() # Rollback if delete_folder_recursive or the commit fails
                error_msg = f"Error deleting folder '{folder_record.name}': {str(e)}"
                errors.append({"item": item_name_for_log, "error": error_msg})
                app.logger.error(f"Batch delete: {error_msg} for user {current_user.id}", exc_info=True)
        else:
            errors.append({"item": item_name_for_log, "error": f"Unknown item type: {item_type}."})
            app.logger.warning(f"Batch delete: Unknown item type '{item_type}' for item ID {item_id}, user {current_user.id}.")

    if errors:
        if deleted_count > 0:
            message = f"Batch deletion partially completed. {deleted_count} item(s) deleted. {len(errors)} error(s) occurred."
            return jsonify({"status": "partial_success", "message": message, "errors": errors, "deleted_count": deleted_count}), 207 # Multi-Status
        else:
            message = f"Batch deletion failed. {len(errors)} error(s) occurred."
            return jsonify({"status": "error", "message": message, "errors": errors}), 500
    else:
        return jsonify({"status": "success", "message": f"Successfully deleted {deleted_count} item(s)."}), 200

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

@app.route('/api/comment/<int:comment_id>/delete', methods=['POST'])
@login_required
def api_delete_comment(comment_id):
    comment = Comment.query.get_or_404(comment_id)

    if not (comment.user_id == current_user.id or current_user.is_admin):
        app.logger.warning(
            f"User {current_user.id} (Admin: {current_user.is_admin}) "
            f"attempted to delete comment {comment_id} owned by user {comment.user_id}."
        )
        return jsonify({"status": "error", "message": "You do not have permission to delete this comment."}), 403

    try:
        post_id_of_deleted_comment = comment.post_id # Get post_id before deleting comment

        comment_text_for_log = comment.text_content[:50]
        db.session.delete(comment)
        db.session.commit()
        app.logger.info(
            f"Comment {comment_id} ('{comment_text_for_log}...') deleted by user {current_user.username} "
            f"(ID: {current_user.id}, Admin: {current_user.is_admin})."
        )

        post_comment_count = 0
        # Query for the post again to get an updated comment list after deletion
        post = Post.query.get(post_id_of_deleted_comment)
        if post:
            post_comment_count = len(post.comments) if post.comments is not None else 0 # Corrected

        return jsonify({
            "status": "success",
            "message": "Comment deleted successfully.",
            "deleted_comment_id": comment_id,
            "post_comment_count": post_comment_count
            })

    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Error deleting comment {comment_id} by user {current_user.id}: {e}", exc_info=True)
        return jsonify({"status": "error", "message": "Could not delete comment due to a server error."}), 500


@app.route('/find_people', methods=['GET'])
@login_required
def find_people():
    """
    Route for the 'Find People' page.
    Displays all users by default, filters by username or name on search.
    Shows follow/unfollow status for each user.
    """
    search_query = request.args.get('search_query', '').strip()

    # Base query: get all users except the current one
    # User model is assumed to be imported at the top of the file
    users_query_builder = User.query.filter(User.id != current_user.id)

    if search_query:
        # Filter by username, first name, or last name (case-insensitive)
        search_term = f"%{search_query}%"
        search_conditions = []
        # Check if attributes exist before trying to use them in a query
        if hasattr(User, 'username'):
            search_conditions.append(User.username.ilike(search_term))
        if hasattr(User, 'first_name'): # Assuming your User model has 'first_name'
            search_conditions.append(User.first_name.ilike(search_term))
        if hasattr(User, 'last_name'):  # Assuming your User model has 'last_name'
            search_conditions.append(User.last_name.ilike(search_term))

        if search_conditions:
            # This is where or_ is used. Ensure it's imported from sqlalchemy.
            users_query_builder = users_query_builder.filter(or_(*search_conditions))

    all_users_profiles = users_query_builder.order_by(User.username).all()

    users_with_follow_status = []
    if all_users_profiles:
        for user_profile in all_users_profiles:
            is_following = False
            if hasattr(current_user, 'is_following') and isinstance(user_profile, User):
                try:
                    is_following = current_user.is_following(user_profile)
                except Exception as e:
                    app.logger.error(f"Error checking follow status for {current_user.username} -> {user_profile.username}: {e}")
                    is_following = False

            users_with_follow_status.append({
                'profile': user_profile,
                'is_following': is_following
            })

    return render_template('find_people.html',
                           title="Find People",
                           users_data=users_with_follow_status,
                           search_query=search_query)

@app.route('/friends')
@login_required
def friends_interface():
    user_friends = current_user.get_friends()
    message_form = DirectMessageForm()

    try:
        max_upload_mb_str = Setting.get('max_upload_size_mb', str(DEFAULT_MAX_UPLOAD_MB_FALLBACK))
        max_upload_mb = int(max_upload_mb_str)
    except (ValueError, TypeError):
        max_upload_mb = DEFAULT_MAX_UPLOAD_MB_FALLBACK
        app.logger.warning(f"Invalid max_upload_size_mb setting. Using fallback {max_upload_mb}MB.")

    friend_activity_statuses = {}
    if user_friends:
        friend_ids = [friend.id for friend in user_friends]
        afk_threshold = timedelta(minutes=30)
        now = datetime.now(timezone.utc) # This is offset-aware

        friends_for_status_check = User.query.filter(User.id.in_(friend_ids)).all()
        for friend_obj in friends_for_status_check: # Renamed loop variable
            status_string = "offline"
            if friend_obj.is_online:
                friend_last_seen_val = friend_obj.last_seen # Get the value

                # --- DEFENSIVE CONVERSION for friend_last_seen_val ---
                # This is the critical fix for the traceback line
                if friend_last_seen_val and friend_last_seen_val.tzinfo is None:
                    # If last_seen is naive, assume it's UTC and make it offset-aware
                    friend_last_seen_val = friend_last_seen_val.replace(tzinfo=timezone.utc)
                # --- END DEFENSIVE CONVERSION ---

                if friend_last_seen_val and (now - friend_last_seen_val) < afk_threshold: # Now comparison is safe
                    status_string = "online"
                else:
                    status_string = "afk"
            friend_activity_statuses[friend_obj.id] = status_string

    return render_template('friends.html',
                           title='Direct Messages',
                           friends=user_friends,
                           message_form=message_form,
                           max_upload_mb=max_upload_mb,
                           initial_friend_statuses=friend_activity_statuses
                           )


@app.route('/api/friends/recent_messages')
@login_required
def api_recent_direct_messages():
    try:
        # Fetch recent messages where the current user is the receiver
        # and they are unread, or alternatively, just the latest N messages from distinct senders.
        # For simplicity, let's fetch the most recent message from each friend
        # who has sent a message to the current user.

        # Subquery to find the latest message_id for each sender to current_user
        latest_message_subquery = db.session.query(
            DirectMessage.sender_id,
            db.func.max(DirectMessage.timestamp).label('max_timestamp')
        ).filter(DirectMessage.receiver_id == current_user.id)\
         .group_by(DirectMessage.sender_id).subquery()

        # Join with DirectMessage again to get the full message details
        recent_messages = db.session.query(DirectMessage).join(
            latest_message_subquery,
            db.and_(
                DirectMessage.sender_id == latest_message_subquery.c.sender_id,
                DirectMessage.timestamp == latest_message_subquery.c.max_timestamp,
                DirectMessage.receiver_id == current_user.id # Ensure it's for the current user
            )
        ).options(
            db.joinedload(DirectMessage.sender).load_only(User.username, User.profile_picture_filename, User.id)
        ).order_by(DirectMessage.timestamp.desc()).limit(5).all() # Limit to, say, 5 most recent distinct senders

        # We might also want to prioritize unread messages.
        # A more complex query could be built to fetch specifically unread messages
        # or a mix. For this example, focusing on latest from each sender.

        messages_data = []
        for msg in recent_messages:
            # Only include if the message is unread by the current user for the bubble
            # Or, always include and let JS decide if bubble was already shown/dismissed.
            # For now, let's assume we only create bubbles for unread.
            # However, the current query doesn't filter by `is_read`.
            # This part needs to align with how `updateNotificationBubbles` in JS works.
            # If JS manages "already shown" state, we don't need to filter by is_read here.

            # Let's send recent messages, and JS can decide if a bubble is needed.
            messages_data.append({
                'message_id': msg.id,
                'sender_id': msg.sender_id,
                'sender_username': msg.sender.username,
                'sender_profile_picture_filename': msg.sender.profile_picture_filename,
                'content_snippet': (msg.content[:30] + '...' if msg.content and len(msg.content) > 30 else msg.content) if msg.content else "Sent a file",
                'timestamp': msg.timestamp.isoformat() + 'Z',
                'is_read': msg.is_read # Send read status
            })

        return jsonify({'status': 'success', 'recent_messages': messages_data})
    except Exception as e:
        current_app.logger.error(f"Error fetching recent direct messages for user {current_user.id}: {e}", exc_info=True)
        return jsonify({'status': 'error', 'message': 'Could not fetch recent messages.'}), 500


@app.route('/api/direct_chat/history/<string:friend_username>')
@login_required
def api_direct_chat_history(friend_username):
    friend_user = User.query.filter_by(username=friend_username).first()
    if not friend_user:
        return jsonify({"status": "error", "message": "Friend not found."}), 404

    if friend_user == current_user:
        return jsonify({"status": "error", "message": "Cannot chat with yourself."}), 400

    # Check if they are actually friends (mutual follow)
    if not (current_user.is_following(friend_user) and friend_user.is_following(current_user)):
        return jsonify({"status": "error", "message": "You are not friends with this user."}), 403

    last_message_id = request.args.get('last_message_id', type=int, default=0)
    limit = 50 # Number of messages to fetch

    # Query messages between current_user and friend_user
    messages_query = DirectMessage.query.filter(
        ((DirectMessage.sender_id == current_user.id) & (DirectMessage.receiver_id == friend_user.id)) |
        ((DirectMessage.sender_id == friend_user.id) & (DirectMessage.receiver_id == current_user.id))
    ).options(
        db.joinedload(DirectMessage.sender).load_only(User.username, User.profile_picture_filename),
        db.joinedload(DirectMessage.receiver).load_only(User.username, User.profile_picture_filename), # Though less critical if always between current_user and friend_user
        db.joinedload(DirectMessage.shared_file)
    ).order_by(DirectMessage.timestamp.desc()) # Fetch newest first for limit, then reverse for display

    if last_message_id > 0:
        # This logic is for fetching messages *older* than a certain ID (infinite scroll up)
        messages_query = messages_query.filter(DirectMessage.id < last_message_id)

    messages = messages_query.limit(limit).all()
    messages.reverse() # Reverse to get them in chronological order for display

    # Mark fetched messages as read by the current_user
    unread_message_ids_to_mark = []
    for msg in messages:
        if msg.receiver_id == current_user.id and not msg.is_read:
            msg.is_read = True
            unread_message_ids_to_mark.append(msg.id)

    if unread_message_ids_to_mark:
        try:
            db.session.commit()
            app.logger.info(f"Marked {len(unread_message_ids_to_mark)} direct messages as read for user {current_user.id} from user {friend_user.id}.")
        except Exception as e:
            db.session.rollback()
            app.logger.error(f"Error marking direct messages as read: {e}")


    message_dicts = [msg.to_dict(current_user_id_for_context=current_user.id) for msg in messages]

    return jsonify({"status": "success", "messages": message_dicts})

@app.route('/api/direct_chat/send/<string:friend_username>', methods=['POST'])
@login_required
def api_direct_chat_send(friend_username):
    friend_user = User.query.filter_by(username=friend_username).first()
    if not friend_user:
        return jsonify({"status": "error", "message": "Recipient not found."}), 404

    if friend_user == current_user:
        return jsonify({"status": "error", "message": "Cannot send a message to yourself."}), 400

    # Ensure they are friends
    if not (current_user.is_following(friend_user) and friend_user.is_following(current_user)):
        return jsonify({"status": "error", "message": "You can only message your friends."}), 403

    content = request.form.get('content', '').strip()
    file = request.files.get('file')
    new_file_record = None
    error_message = None
    status_code = 200
    file_path_on_disk = None # For cleanup on error

    if not content and (not file or file.filename == ''):
        return jsonify({"status": "error", "message": "Message content or file attachment required."}), 400

    # --- Handle File Upload (if present) ---
    if file and file.filename != '':
        original_filename = secure_filename(file.filename)

        # File size determination and checks (similar to api_group_chat_send)
        uploaded_filesize = None
        try:
            file.seek(0, os.SEEK_END)
            uploaded_filesize = file.tell()
            file.seek(0)
        except Exception:
            uploaded_filesize = request.content_length

        if uploaded_filesize is None:
            return jsonify({"status": "error", "message": "Could not determine file size."}), 400

        # CHECK 1: Server Limit (MAX_CONTENT_LENGTH)
        hard_limit_bytes = current_app.config.get('MAX_CONTENT_LENGTH')
        if hard_limit_bytes and uploaded_filesize > hard_limit_bytes:
            error_message = f'File exceeds server limit ({hard_limit_bytes // (1024*1024)} MB).'
            status_code = 413

        # CHECK 2: Admin Max Upload Limit
        if not error_message:
            try:
                max_upload_mb_str = Setting.get('max_upload_size_mb', str(DEFAULT_MAX_UPLOAD_MB_FALLBACK))
                admin_limit_bytes = int(max_upload_mb_str) * 1024 * 1024
                if uploaded_filesize > admin_limit_bytes:
                    error_message = f'File exceeds max upload size ({max_upload_mb_str} MB).'
                    status_code = 413
            except (ValueError, TypeError):
                error_message = "Server configuration error for upload limit."
                status_code = 500

        # CHECK 3: User Storage Limit
        if not error_message:
            storage_info = get_user_storage_info(current_user)
            available_bytes = float('inf') if storage_info['limit_bytes'] == float('inf') else storage_info['limit_bytes'] - storage_info['usage_bytes']
            if uploaded_filesize > available_bytes:
                error_message = 'Insufficient storage space for this file.'
                status_code = 413

        if not error_message:
            try:
                _, ext = os.path.splitext(original_filename)
                stored_filename = str(uuid.uuid4()) + ext
                user_upload_path = get_user_upload_path(current_user.id)
                os.makedirs(user_upload_path, exist_ok=True)
                file_path_on_disk = os.path.join(user_upload_path, stored_filename)

                file.save(file_path_on_disk)

                mime_type, _ = mimetypes.guess_type(file_path_on_disk)
                mime_type = mime_type or 'application/octet-stream'

                new_file_record = File(
                    original_filename=original_filename,
                    stored_filename=stored_filename,
                    filesize=uploaded_filesize,
                    mime_type=mime_type,
                    owner=current_user,
                    parent_folder_id=None # DM files are not in user's browsable folders
                )
                db.session.add(new_file_record)
                db.session.flush() # Get ID for new_file_record
            except Exception as e:
                db.session.rollback()
                if file_path_on_disk and os.path.exists(file_path_on_disk):
                    try: os.remove(file_path_on_disk)
                    except OSError: pass
                error_message = f"Error processing file: {str(e)}"
                status_code = 500

    if error_message:
        return jsonify({"status": "error", "message": error_message}), status_code

    # --- Save Direct Message Record ---
    try:
        new_dm = DirectMessage(
            sender_id=current_user.id,
            receiver_id=friend_user.id,
            content=content if content else None,
            file_id=new_file_record.id if new_file_record else None,
            is_read=False # New message is initially unread by receiver
        )
        db.session.add(new_dm)
        db.session.commit()

        db.session.refresh(new_dm) # Load relationships for to_dict
        if new_file_record: db.session.refresh(new_file_record)

        # Return the newly created message data
        message_data = new_dm.to_dict(current_user_id_for_context=current_user.id)

        return jsonify({"status": "success", "message": message_data}), 201

    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Error saving direct message for user {current_user.id} to {friend_user.id}: {e}", exc_info=True)
        # Clean up physical file if it was part of this failed transaction
        if file_path_on_disk and os.path.exists(file_path_on_disk) and new_file_record: # Only if file was for this DM
            try: os.remove(file_path_on_disk)
            except OSError: pass
        return jsonify({"status": "error", "message": "Error saving message to database."}), 500

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
        if action == 'liked' and post.author != current_user: # Only notify if liked and not self-like
            create_notification(recipient_user=post.author, sender_user=current_user, type='like_post', post=post)
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
        query = query.outerjoin(Comment, Post.id == Comment.post_id)\
                       .group_by(Post.id)\
                       .order_by(db.func.count(Comment.id).desc(), Post.timestamp.desc())
    elif sort_by == 'comments_asc':
         query = query.outerjoin(Comment, Post.id == Comment.post_id)\
                        .group_by(Post.id)\
                        .order_by(db.func.count(Comment.id).asc(), Post.timestamp.desc())
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
        db.joinedload(Post.author).load_only(User.username, User.profile_picture_filename, User.id),
        # Eager load the shared_comment and its author if it's a shared comment post
        db.joinedload(Post.shared_comment).options(
            db.joinedload(Comment.author).load_only(User.username, User.profile_picture_filename, User.id),
            db.selectinload(Comment.likers).load_only(User.id), # For like count on shared comment
            db.selectinload(Comment.dislikers).load_only(User.id) # For dislike count on shared comment
        ),
        # Eager load comments on the post
        db.selectinload(Post.comments).options( # Use selectinload for collections
            db.joinedload(Comment.author).load_only(User.username, User.profile_picture_filename, User.id),
            db.selectinload(Comment.likers).load_only(User.id), # For like counts on comments
            db.selectinload(Comment.dislikers).load_only(User.id), # For dislike counts on comments
            db.selectinload(Comment.replies).options( # Eager load replies to comments
                db.joinedload(Comment.author).load_only(User.username, User.profile_picture_filename, User.id),
                db.selectinload(Comment.likers).load_only(User.id),
                db.selectinload(Comment.dislikers).load_only(User.id)
                # Potentially recursive loading for replies to replies if needed, but can get complex
            )
        ),
        db.selectinload(Post.likers).load_only(User.id), # For post's own like status
        db.selectinload(Post.dislikers).load_only(User.id) # For post's own dislike status
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
        if action == 'disliked' and post.author != current_user: # Only notify if disliked and not self-dislike
            create_notification(recipient_user=post.author, sender_user=current_user, type='dislike_post', post=post)
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
    is_ajax = request.accept_mimetypes.accept_json and not request.accept_mimetypes.accept_html

    parent_comment_id = None
    text_content = None

    if is_ajax:
        data = request.get_json()
        if not data:
            return jsonify({'status': 'error', 'message': 'Invalid JSON data.'}), 400
        text_content = data.get('text_content', '').strip()
        parent_comment_id = data.get('parent_comment_id')
        if parent_comment_id:
            try:
                parent_comment_id = int(parent_comment_id)
            except (ValueError, TypeError):
                return jsonify({'status': 'error', 'message': 'Invalid parent_comment_id format.'}), 400
    else:
        form = CommentForm()
        if form.validate_on_submit():
            text_content = form.text_content.data.strip()
            parent_comment_id_str = request.form.get('parent_comment_id')
            if parent_comment_id_str:
                try:
                    parent_comment_id = int(parent_comment_id_str)
                except (ValueError, TypeError):
                    flash('Invalid parent comment reference.', 'danger')
                    return redirect(request.referrer or url_for('view_single_post', post_id=post_id))
        else:
            for field, errors_list in form.errors.items():
                for error in errors_list:
                    flash(f"Comment error: {error}", 'danger')
            return redirect(request.referrer or url_for('view_single_post', post_id=post_id))

    if not text_content:
        message = 'Comment text cannot be empty.'
        if is_ajax: return jsonify({'status': 'error', 'message': message}), 400
        else: flash(message, 'warning'); return redirect(request.referrer or url_for('view_single_post', post_id=post_id))

    if len(text_content) > 1000:
        message = 'Comment is too long (max 1000 characters).'
        if is_ajax: return jsonify({'status': 'error', 'message': message}), 400
        else: flash(message, 'warning'); return redirect(request.referrer or url_for('view_single_post', post_id=post_id))

    parent_comment = None
    if parent_comment_id:
        parent_comment = Comment.query.filter_by(id=parent_comment_id, post_id=post.id).first()
        if not parent_comment:
            message = 'Parent comment not found or does not belong to this post.'
            if is_ajax: return jsonify({'status': 'error', 'message': message}), 404
            else: flash(message, 'danger'); return redirect(url_for('view_single_post', post_id=post_id))

    try:
        new_comment = Comment(
            user_id=current_user.id,
            post_id=post.id,
            text_content=text_content,
            parent_id=parent_comment.id if parent_comment else None
        )
        db.session.add(new_comment)
        if post.author != current_user:
            create_notification(
                recipient_user=post.author,
                sender_user=current_user,
                type='comment_on_post',
                post=post,
                comment=new_comment
            )

        # Notify parent comment author if it's a reply (and not to themselves)
        if parent_comment and parent_comment.author != current_user:
            create_notification(
                recipient_user=parent_comment.author,
                sender_user=current_user,
                type='reply_to_comment',
                post=post, # The post the original comment belongs to
                comment=new_comment # The new reply
            )
        db.session.commit()

        db.session.refresh(new_comment)
        _ = new_comment.author

        app.logger.info(f"Comment {new_comment.id} {'(reply to ' + str(parent_comment_id) + ')' if parent_comment_id else ''} added to post {post_id} by user {current_user.id}")

        if is_ajax:
            return jsonify({
                'status': 'success',
                'message': 'Comment posted successfully.',
                'comment': new_comment.to_dict(include_author_details=True, include_replies=False),
                'post_comment_count': len(post.comments) if post.comments is not None else 0,
                'current_user_id': current_user.id,  # Add this line
                'current_user_is_admin': current_user.is_admin  # Add this line
            }), 201

    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Error saving comment for post {post_id} by user {current_user.id}: {e}", exc_info=True)
        message = 'Could not save comment due to a server error.'
        if is_ajax: return jsonify({'status': 'error', 'message': message}), 500
        else: flash(message, 'danger'); return redirect(request.referrer or url_for('view_single_post', post_id=post_id))


@app.route('/api/comment/<int:comment_id>/like', methods=['POST'])
@login_required
def like_comment(comment_id):
    comment = Comment.query.get_or_404(comment_id)
    action_taken = "none"

    if current_user in comment.dislikers:
        comment.dislikers.remove(current_user)

    if current_user in comment.likers:
        comment.likers.remove(current_user)
        action_taken = "unliked"
    else:
        comment.likers.append(current_user)
        action_taken = "liked"

    try:
        db.session.commit()
        return jsonify({
            "status": "success",
            "action": action_taken,
            "comment_id": comment.id,
            "likes": len(comment.likers),         # Corrected
            "dislikes": len(comment.dislikers),   # Corrected
            "is_liked_by_user": current_user in comment.likers,
            "is_disliked_by_user": current_user in comment.dislikers
        }), 200
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Error liking/unliking comment {comment_id} for user {current_user.id}: {e}", exc_info=True)
        return jsonify({"status": "error", "message": "Could not process like/unlike for comment."}), 500


@app.route('/api/comment/<int:comment_id>/dislike', methods=['POST'])
@login_required
def dislike_comment(comment_id):
    comment = Comment.query.get_or_404(comment_id)
    action_taken = "none"

    if current_user in comment.likers:
        comment.likers.remove(current_user)

    if current_user in comment.dislikers:
        comment.dislikers.remove(current_user)
        action_taken = "undisliked"
    else:
        comment.dislikers.append(current_user)
        action_taken = "disliked"

    try:
        db.session.commit()
        return jsonify({
            "status": "success",
            "action": action_taken,
            "comment_id": comment.id,
            "likes": len(comment.likers),         # Corrected
            "dislikes": len(comment.dislikers),   # Corrected
            "is_liked_by_user": current_user in comment.likers,
            "is_disliked_by_user": current_user in comment.dislikers
        }), 200
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Error disliking/undisliking comment {comment_id} for user {current_user.id}: {e}", exc_info=True)
        return jsonify({"status": "error", "message": "Could not process dislike/undislike for comment."}), 500


@app.route('/api/comment/<int:comment_id>/share', methods=['POST'])
@login_required
def share_comment_as_post(comment_id):
    comment_to_share = Comment.query.get_or_404(comment_id)

    data = request.get_json()
    if not data:
        return jsonify({"status": "error", "message": "Missing data in request."}), 400

    sharer_text_content = data.get('text_content', '').strip() # User's own text for the share

    # Optional: Validate sharer_text_content length, etc.
    # if not sharer_text_content: # If you require text from the sharer
    #     return jsonify({"status": "error", "message": "Your thoughts cannot be empty when sharing."}), 400

    try:
        new_post = Post(
            user_id=current_user.id,
            text_content=sharer_text_content if sharer_text_content else None, # Allow empty sharer text
            shared_comment_id=comment_to_share.id,
            timestamp=datetime.utcnow()
            # photo_filename and video_filename are None for this type of post
        )
        db.session.add(new_post)

        # Optional: Increment a share counter on the Comment model
        # if hasattr(comment_to_share, 'times_shared_as_post'):
        #     comment_to_share.times_shared_as_post += 1
        #     db.session.add(comment_to_share)
        if comment_to_share.author != current_user: # Don't notify if sharing own comment
            create_notification(
                recipient_user=comment_to_share.author,
                sender_user=current_user,
                type='share_comment',
                post=comment_to_share.post, # The post the original comment belonged to
                comment=comment_to_share   # The original comment that was shared
            )
        db.session.commit()
        app.logger.info(f"User {current_user.username} shared comment {comment_to_share.id} as new post {new_post.id}")

        # You might want to return data about the new post
        return jsonify({
            "status": "success",
            "message": "Comment shared successfully as a new post.",
            "new_post_id": new_post.id,
            # "new_post_url": url_for('view_single_post', post_id=new_post.id, _external=True) # If needed
        }), 201

    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Error sharing comment {comment_id} as post for user {current_user.id}: {e}", exc_info=True)
        return jsonify({"status": "error", "message": "Could not share comment as post."}), 500

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
    if original_post.author != current_user: # Don't notify if sharing own original post (though UI prevents this)
        create_notification(
            recipient_user=original_post.author,
            sender_user=current_user,
            type='share_post',
            post=original_post # The original post that was shared
            # The 'shared_post' object itself is the new post by current_user
        )
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
        try:
            if not os.path.exists(app_instance.instance_path):
                os.makedirs(app_instance.instance_path)
                app_instance.logger.info(f"Created instance folder: {app_instance.instance_path}")

            upload_folder_path = app_instance.config.get('UPLOAD_FOLDER')
            if not upload_folder_path:
                upload_folder_path = os.path.join(app_instance.instance_path, 'uploads')
                app_instance.config['UPLOAD_FOLDER'] = upload_folder_path
            if not os.path.exists(upload_folder_path):
                os.makedirs(upload_folder_path)
                app_instance.logger.info(f"Created base upload folder: {upload_folder_path}")

            # Ensure post media static folder exists
            static_post_media_path = os.path.join(app_instance.root_path, 'static', 'uploads', 'post_media')
            if not os.path.exists(static_post_media_path):
                 os.makedirs(static_post_media_path, exist_ok=True)
                 app_instance.logger.info(f"Created static post media folder: {static_post_media_path}")

            # Ensure user-specific profile picture static folder exists (if not done elsewhere)
            static_profile_pics_path = os.path.join(app_instance.root_path, 'static', 'uploads', 'profile_pics')
            if not os.path.exists(static_profile_pics_path):
                 os.makedirs(static_profile_pics_path, exist_ok=True)
                 app_instance.logger.info(f"Created static profile picture folder: {static_profile_pics_path}")

            # NEW: Ensure video thumbnail folder exists
            if not os.path.exists(VIDEO_THUMBNAIL_FOLDER):
                os.makedirs(VIDEO_THUMBNAIL_FOLDER, exist_ok=True)
                app_instance.logger.info(f"Created video thumbnail folder: {VIDEO_THUMBNAIL_FOLDER}")


        except OSError as e:
            app_instance.logger.error(f"OSError creating instance or upload folders: {e}", exc_info=True)

        db_path_in_instance = os.path.join(app_instance.instance_path, DB_NAME)
        expected_db_uri = f'sqlite:///{db_path_in_instance}'
        if app_instance.config.get('SQLALCHEMY_DATABASE_URI') != expected_db_uri:
            app_instance.config['SQLALCHEMY_DATABASE_URI'] = expected_db_uri
            app_instance.logger.info(f"Updated SQLALCHEMY_DATABASE_URI to: {expected_db_uri}")
            # db.init_app(app_instance) # If db was initialized globally without app

        if not os.path.exists(db_path_in_instance):
            app_instance.logger.info(f"Database file not found at {db_path_in_instance}. Creating tables...")
        else:
            app_instance.logger.info(f"Database file found at {db_path_in_instance}. Ensuring all tables exist...")

        try:
            ensure_repos_dir_exists()
            db.create_all() # This will create all tables defined in models if they don't exist
            app_instance.logger.info("Database tables checked/created successfully.")
        except Exception as e:
            db.session.rollback() # Should not be necessary if create_all is before data ops
            app_instance.logger.error(f"Failed to create/check database tables: {e}", exc_info=True)
            return

        settings_changed_in_db = False
        try:
            for key, default_value in DEFAULT_SETTINGS.items():
                current_value = Setting.get(key)
                if current_value is None:
                    app_instance.logger.info(f"Setting '{key}' not found. Seeding with default: '{default_value}'.")
                    Setting.set(key, default_value)
                    settings_changed_in_db = True
            if settings_changed_in_db:
                db.session.commit()
                app_instance.logger.info("Committed new/updated default settings to the database.")
            else:
                app_instance.logger.info("All essential settings are already present.")
        except Exception as e:
            db.session.rollback()
            app_instance.logger.error(f"Error verifying/seeding settings: {e}", exc_info=True)

        app_instance.logger.info("Database initialization and settings check complete.")

class DirectMessage(db.Model):
    __tablename__ = 'direct_message'
    id = db.Column(db.Integer, primary_key=True)
    sender_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=False, index=True)
    receiver_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=False, index=True)
    timestamp = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False, index=True)
    content = db.Column(db.Text, nullable=True)
    file_id = db.Column(db.Integer, db.ForeignKey('file.id', ondelete='SET NULL'), nullable=True, index=True)
    edited_at = db.Column(db.DateTime, nullable=True)
    is_deleted = db.Column(db.Boolean, default=False, nullable=False, index=True) # For soft deletes
    deleted_at = db.Column(db.DateTime, nullable=True)
    is_read = db.Column(db.Boolean, default=False, nullable=False, index=True) # To track read status

    # Relationships
    sender = db.relationship('User', foreign_keys=[sender_id], backref=db.backref('sent_direct_messages_rel', lazy='dynamic'))
    receiver = db.relationship('User', foreign_keys=[receiver_id], backref=db.backref('received_direct_messages_rel', lazy='dynamic'))

    shared_file = db.relationship('File', foreign_keys=[file_id], backref=db.backref('direct_message_shares', lazy='joined', uselist=False))

    def __repr__(self):
        return f'<DirectMessage {self.id} from {self.sender_id} to {self.receiver_id}>'

    def to_dict(self, current_user_id_for_context=None):
        """
        Converts the direct message to a dictionary.
        current_user_id_for_context helps determine if the message is 'outgoing' or 'incoming'
        from the perspective of the user requesting the data.
        """
        sender_username = self.sender.username if self.sender else None
        sender_profile_pic = self.sender.profile_picture_filename if self.sender else None
        receiver_username = self.receiver.username if self.receiver else None

        # Determine message direction if context is provided
        direction = None
        if current_user_id_for_context:
            if self.sender_id == current_user_id_for_context:
                direction = 'outgoing'
            elif self.receiver_id == current_user_id_for_context:
                direction = 'incoming'

        data = {
            'id': self.id,
            'sender_id': self.sender_id,
            'sender_username': sender_username,
            'sender_profile_picture_filename': sender_profile_pic,
            'receiver_id': self.receiver_id,
            'receiver_username': receiver_username,
            'timestamp': self.timestamp.isoformat() + 'Z',
            'content': self.content,
            'file_id': self.file_id,
            'shared_file': None,
            'is_edited': bool(self.edited_at),
            'edited_at': self.edited_at.isoformat() + 'Z' if self.edited_at else None,
            'is_deleted': self.is_deleted,
            'is_read': self.is_read,
            'direction': direction # Add direction based on context
        }

        if self.shared_file:
            file_data = {
                'id': self.shared_file.id,
                'original_filename': self.shared_file.original_filename,
                'mime_type': self.shared_file.mime_type,
                'filesize': self.shared_file.filesize,
                'is_editable': is_file_editable(self.shared_file.original_filename, self.shared_file.mime_type),
                'view_url': url_for('view_file', file_id=self.shared_file.id, _external=False) if self.shared_file.mime_type in current_app.config.get('VIEWABLE_MIMES', {}) else None,
                'download_url': url_for('download_file', file_id=self.shared_file.id, _external=False)
            }
            # Add text file preview similar to GroupChatMessage if desired
            if self.shared_file.mime_type == 'text/plain':
                try:
                    file_owner_user_id = self.shared_file.user_id # Get the owner of the file
                    file_path = os.path.join(get_user_upload_path(file_owner_user_id), self.shared_file.stored_filename)
                    if os.path.exists(file_path):
                        with codecs.open(file_path, 'r', encoding='utf-8', errors='replace') as f:
                            content_plus_one = f.read(501)
                            preview_content = content_plus_one[:500]
                            file_data['preview_content'] = preview_content
                            file_data['has_more_content'] = len(content_plus_one) > 500
                    else:
                        file_data['preview_content'] = "[Preview unavailable: File missing]"
                        file_data['has_more_content'] = False
                except Exception as e:
                    current_app.logger.warning(f"Could not read preview for DM txt file {self.shared_file.id}: {e}")
                    file_data['preview_content'] = "[Error reading preview]"
                    file_data['has_more_content'] = False
            data['shared_file'] = file_data
        return data

class OllamaChatMessage(db.Model):
    """Model for storing individual ollama chat messages per user."""
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    role = db.Column(db.String(10), nullable=False) # 'user' or 'assistant'
    content = db.Column(db.Text, nullable=False)
    timestamp = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False, index=True)

    # Add relationship back to User (optional but useful)
    # The backref allows accessing messages via user.ollama_chat_messages

    def __repr__(self):
        return f'<OllamaChatMessage {self.id} (User: {self.user_id}, Role: {self.role})>'

    # Helper to convert DB object to the dictionary format Ollama/template expects
    def to_dict(self):
        # Access the 'user' relationship (the sender of the message)
        sender_username = None
        sender_profile_picture_filename = None

        # For 'user' role messages, fetch the actual sender details from the User model
        if self.role == 'user' and self.user: # self.user refers to the User object linked by user_id
            sender_username = self.user.username
            sender_profile_picture_filename = self.user.profile_picture_filename
        # For 'assistant' role messages, hardcode Ollama AI details
        elif self.role == 'assistant':
            sender_username = 'Ollama AI'
            sender_profile_picture_filename = 'ollama_pfp.png' # Assuming this is in static/icons/
        # For 'thinking' or other system messages, hardcode System details (using Ollama's pfp for consistency)
        elif self.role == 'thinking':
            sender_username = 'System'
            sender_profile_picture_filename = 'ollama_pfp.png' # Using Ollama pfp for system messages too

        return {
            "id": self.id, # Include ID for frontend to track messages
            "user_id": self.user_id, # Include user_id for frontend to determine current-user class
            "role": self.role,
            "content": self.content,
            "timestamp": self.timestamp.isoformat() + 'Z' if self.timestamp else None,
            "sender_username": sender_username,
            "sender_profile_picture_filename": sender_profile_picture_filename
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
    timestamp = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False, index=True)
    content = db.Column(db.Text, nullable=True) # Text content of the message
    file_id = db.Column(db.Integer, db.ForeignKey('file.id', ondelete='SET NULL'), nullable=True, index=True) # Added ondelete, allows keeping file if msg deleted
    edited_at = db.Column(db.DateTime, nullable=True)
    is_deleted = db.Column(db.Boolean, default=False, nullable=False, index=True)
    deleted_at = db.Column(db.DateTime, nullable=True)

    # Relationships

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


@app.after_request
def add_coop_coep_headers(response):
    """
    Add Cross-Origin Opener Policy (COOP) and Cross-Origin Embedder Policy (COEP)
    headers. These are necessary for SharedArrayBuffer, which is often used by
    WASM modules (like mGBA WASM) for features like multithreading. [7, 2, 8, 9]
    """
    response.headers['Cross-Origin-Opener-Policy'] = 'same-origin'
    response.headers['Cross-Origin-Embedder-Policy'] = 'require-corp'
    return response


# EMULATORS #
#GBA EMULATOR

from functools import wraps

@app.after_request
def add_coop_coep_headers(response):
    """
    Add Cross-Origin Opener Policy (COOP) and Cross-Origin Embedder Policy (COEP)
    headers. These are necessary for SharedArrayBuffer, which is often used by
    WASM modules (like mGBA WASM) for features like multithreading. [7, 2, 8, 9]
    """
    response.headers['Cross-Origin-Opener-Policy'] = 'same-origin'
    response.headers['Cross-Origin-Embedder-Policy'] = 'require-corp'
    return response

@app.route('/emulator_gba')
@login_required
def emulator_gba():
    """
    Serves the main HTML page that will host the GBA emulator.
    """
    return render_template('emulator_gba.html')

@app.route('/emulator_gba/roms/<filename>')
@login_required
def serve_gba_rom(filename):
    """
    Serves uploaded ROM files from the GBA_ROM_UPLOAD_FOLDER.
    """
    return send_from_directory(app.config['GBA_ROM_UPLOAD_FOLDER'], filename)



# GIT SERVER


LANGUAGE_COLORS = {
    "Python": "#3572A5",
    "JavaScript": "#F1E05A",
    "HTML": "#E34C26",
    "CSS": "#563D7C",
    "Java": "#B07219",
    "Shell": "#89E051",
    "C++": "#F34B7D",
    "C": "#555555",
    "TypeScript": "#2B7489",
    "PHP": "#4F5D95",
    "Ruby": "#701516",
    "Go": "#00ADD8",
    "Swift": "#FFAC45",
    "Kotlin": "#F18E33",
    "Rust": "#DEA584",
    "Markdown": "#083FA1", # Often included in stats
    "Vue": "#41B883",
    "Makefile": "#427819",
    "Dockerfile": "#384D54",
    "Other": "#DEA584" # A fallback color
}


LANGUAGE_EXTENSIONS_MAP = {
    '.py': 'Python', '.pyc': None, '.pyo': None, '.pyd': None, # Python and compiled
    '.js': 'JavaScript', '.mjs': 'JavaScript', '.cjs': 'JavaScript',
    '.html': 'HTML', '.htm': 'HTML',
    '.css': 'CSS',
    '.java': 'Java', '.class': None, # Java and compiled
    '.sh': 'Shell', '.bash': 'Shell', '.zsh': 'Shell',
    '.c': 'C', '.h': 'C', # C and its headers
    '.cpp': 'C++', '.hpp': 'C++', '.cxx': 'C++', '.hxx': 'C++', '.cc': 'C++', '.hh': 'C++',
    '.cs': 'C#',
    '.ts': 'TypeScript', '.tsx': 'TypeScript', # TSX often treated as TypeScript for stats
    '.php': 'PHP',
    '.rb': 'Ruby',
    '.go': 'Go',
    '.swift': 'Swift',
    '.kt': 'Kotlin', '.kts': 'Kotlin',
    '.rs': 'Rust',
    '.md': 'Markdown', '.markdown': 'Markdown',
    '.json': 'JSON', # Data, but often shown
    '.xml': 'XML',   # Data/Markup
    '.yaml': 'YAML', '.yml': 'YAML', # Data
    '.vue': 'Vue',
    'makefile': 'Makefile', # Filename match
    'dockerfile': 'Dockerfile', # Filename match
    # Common binary/non-code extensions to explicitly ignore (return None)
    '.png': None, '.jpg': None, '.jpeg': None, '.gif': None, '.bmp': None, '.tiff': None,
    '.svg': None, # SVGs can be code-like but often treated as assets
    '.ico': None, '.webp': None,
    '.pdf': None, '.doc': None, '.docx': None, '.xls': None, '.xlsx': None,
    '.ppt': None, '.pptx': None, '.odt': None, '.ods': None, '.odp': None,
    '.zip': None, '.tar': None, '.gz': None, '.rar': None, '.7z': None, '.bz2': None, '.xz': None,
    '.exe': None, '.dll': None, '.so': None, '.dylib': None, '.o': None, '.a': None, '.lib': None,
    '.obj': None,
    '.mp3': None, '.wav': None, '.aac': None, '.flac': None,
    '.mp4': None, '.mov': None, '.avi': None, '.mkv': None, '.webm': None,
    '.ttf': None, '.otf': None, '.woff': None, '.woff2': None, '.eot': None,
    '.DS_Store': None, '.db': None, '.sqlite': None, '.sqlite3': None,
    '.log': None,
    '.bak': None, '.tmp': None, '.swp': None,
    '.lock': None, # e.g. package-lock.json, composer.lock - could be JSON/YAML or None
    '.sum': None, # e.g. go.sum
    # Source map files
    '.js.map': None, '.css.map': None,
}

IGNORE_PATTERNS_FOR_STATS = {
    '.git/',
    'node_modules/',
    'bower_components/',
    'vendor/', # Common for PHP, Ruby, Go
    'venv/',
    'env/',
    '.venv/',
    '.env/',
    '__pycache__/',
    '.pytest_cache/',
    '.mypy_cache/',
    '.tox/',
    '.idea/',
    '.vscode/',
    '.settings/',
    'build/',
    'dist/',
    'target/', # Common for Java/Rust
    'out/',   # Common for compiled output
    'bin/',   # Often compiled binaries
    'obj/',   # Often compiled objects
    'coverage/',
    'docs/', # Optional: some might want to exclude docs from "code" stats
    'examples/', # Optional
    'test/', 'tests/', # Optional
    # Specific config files that are not "code" in the typical sense
    '.gitignore',
    '.gitattributes',
    '.editorconfig',
    '.eslintignore',
    '.eslintrc.js', '.eslintrc.json', '.eslintrc.yaml', '.eslintrc.yml',
    '.prettierrc', '.prettierignore',
    'license', 'licence', 'copying', # Often plain text or MD
    'readme', # Handled separately or could be Markdown
    'contributing',
    'changelog',
    'package.json', 'package-lock.json', # Could be JSON or special
    'composer.json', 'composer.lock',   # Could be JSON or special
    'go.mod', 'go.sum',
    'gemfile', 'gemfile.lock',
    'requirements.txt',
    'pipfile', 'pipfile.lock',
    'pyproject.toml',
    'webpack.config.js',
    'babel.config.js',
    'tsconfig.json'
}

# Helper to get language color, can be registered as a Jinja filter
def get_language_color(language_name):
    return LANGUAGE_COLORS.get(language_name, LANGUAGE_COLORS.get("Other", "#CCCCCC"))

# Register as Jinja filter/global
app.jinja_env.globals['get_language_color'] = get_language_color
# or app.jinja_env.filters['language_color'] = get_language_color


def guess_language_from_filename(filename_str):
    """Guesses language primarily by extension, with some filename checks."""
    if not filename_str:
        return None

    path = Path(filename_str)
    name_lower = path.name.lower()

    # Check for exact filename matches first (e.g., Makefile, Dockerfile)
    if name_lower in LANGUAGE_EXTENSIONS_MAP: # Assuming these are mapped directly if no ext
        lang = LANGUAGE_EXTENSIONS_MAP[name_lower]
        return lang if lang is not None else "Other" # Return "Other" if explicitly mapped to None

    # Check extensions
    # Iterate through suffixes: .tar.gz -> .gz then .tar
    for suffix in reversed(path.suffixes):
        s_lower = suffix.lower()
        if s_lower in LANGUAGE_EXTENSIONS_MAP:
            lang = LANGUAGE_EXTENSIONS_MAP[s_lower]
            return lang # This will return None if explicitly mapped to None (binary/ignored)

    # If no extension matched, or no extension present, return None or "Other"
    # For this function, let's return None if no specific rule matched.
    # The main calculator can then decide to categorize as "Other".
    return None


# @lru_cache(maxsize=128) # Example of basic caching for the function itself
def calculate_repo_language_stats(repo_disk_path, ref_name="HEAD"):
    """
    Calculates language statistics for a repository at a specific ref.
    Returns a dictionary like {'Python': 60.5, 'JavaScript': 39.5}
    or None if an error occurs or repo is empty.
    """
    GIT_PATH = current_app.config.get('GIT_EXECUTABLE_PATH', "git")
    language_bytes = {}
    total_code_bytes = 0.0 # Use float for precision in division

    # Check if repo exists and is valid before proceeding
    if not os.path.isdir(os.path.join(repo_disk_path, 'objects')): # Basic check for a git repo
        current_app.logger.warning(f"Invalid or non-existent Git repo path for stats: {repo_disk_path}")
        return {} # Return empty if not a valid repo path

    try:
        # Ensure ref_name is valid before ls-tree
        subprocess.run(
            [GIT_PATH, "--git-dir=" + repo_disk_path, "rev-parse", "--verify", ref_name + "^{commit}"],
            check=True, capture_output=True, text=True
        )

        proc = subprocess.run(
            [GIT_PATH, "--git-dir=" + repo_disk_path, "ls-tree", "-r", "-l", "--full-tree", ref_name],
            capture_output=True, text=True, check=True, errors='ignore'
        )

        if not proc.stdout.strip():
            return {} # Empty repo or ref

        for line in proc.stdout.strip().split('\n'):
            if not line:
                continue

            parts = line.split(None, 3)
            if len(parts) < 4 or parts[1] != 'blob': # Only process blobs (files)
                continue

            size_and_name_part = parts[3]
            try:
                size_str, file_path_str = size_and_name_part.split('\t', 1)
                if size_str == '-': # Symlinks or other non-blob entries might have '-'
                    continue
                file_size = int(size_str)
            except (ValueError, IndexError):
                current_app.logger.debug(f"Skipping unparsable ls-tree line for stats: {line}")
                continue

            if file_size == 0: # Skip empty files
                continue

            # --- Filtering ---
            # Check if any part of the path starts with an ignored directory pattern
            path_parts = Path(file_path_str).parts
            if any(patt in file_path_str for patt in IGNORE_PATTERNS_FOR_STATS if patt.endswith('/')) or \
               Path(file_path_str).name.lower() in IGNORE_PATTERNS_FOR_STATS or \
               any(p in IGNORE_PATTERNS_FOR_STATS for p in path_parts):
                # current_app.logger.debug(f"Ignoring by pattern: {file_path_str}")
                continue

            language = guess_language_from_filename(file_path_str)

            if language is None: # If explicitly None (e.g. binary, config), or no rule matched
                # Optionally, we could try a more advanced guess here or assign to "Other"
                # For now, if guess_language_from_filename returns None, we skip it
                # or we can assign it to an "Other" category if it wasn't a known non-code file.
                # Let's refine: if it's None from a specific rule (like .png:None), it's truly ignored.
                # If it's None because no extension matched, it could be "Other".
                # For simplicity, if it's not a recognized code extension, it won't be counted.
                # To count as "Other", `guess_language_from_filename` would need to return "Other".
                # This means only explicitly mapped languages get counted.
                continue

            # If you want to categorize truly unknown extensions as "Other":
            # if language is None:
            #     # Before assigning to other, double check it's not a known binary via suffix again
            #     ext_lower = Path(file_path_str).suffix.lower()
            #     if ext_lower in LANGUAGE_EXTENSIONS_MAP and LANGUAGE_EXTENSIONS_MAP[ext_lower] is None:
            #         continue # It was explicitly ignored
            #     language = "Other"


            language_bytes[language] = language_bytes.get(language, 0) + file_size
            total_code_bytes += file_size

        if total_code_bytes == 0:
            return {}

        language_percentages = {}
        # Ensure consistent sorting for display, and handle small percentages
        # Sort languages alphabetically for consistent bar segment order if percentages are same
        sorted_languages = sorted(language_bytes.keys())

        temp_percentages = {}
        for lang in sorted_languages:
            bytes_count = language_bytes[lang]
            percentage = (bytes_count / total_code_bytes) * 100
            if percentage >= 0.1: # Only include if reasonably significant
                 temp_percentages[lang] = percentage

        # Sort final dict by percentage descending for display in legend
        language_percentages = dict(sorted(temp_percentages.items(), key=lambda item: item[1], reverse=True))

        return language_percentages

    except subprocess.CalledProcessError as e:
        # --- CORRECTED ERROR HANDLING ---
        # e.stderr is already a string because text=True was used in subprocess.run
        stderr_output = e.stderr if e.stderr else "" # Ensure it's not None

        if "fatal: not a tree object" in stderr_output or \
           "fatal: bad object" in stderr_output:
            current_app.logger.info(f"Ref '{ref_name}' is not a valid tree or object in {repo_disk_path}. Likely empty or invalid ref.")
            return {} # Treat as empty or error state for stats

        current_app.logger.error(f"Git command error calculating language stats for {repo_disk_path} ref {ref_name}: {stderr_output}")
        return None
    except Exception as e:
        current_app.logger.error(f"Unexpected error calculating language stats for {repo_disk_path} ref {ref_name}: {e}", exc_info=True)
        return None # Indicate error

# --- Add a new field to GitRepository model for caching (optional but recommended) ---
# This requires a database migration (e.g., using Flask-Migrate)
# class GitRepository(db.Model):
#     # ... other fields ...
#     language_stats_json = db.Column(db.Text, nullable=True) # Store as JSON string
#     language_stats_updated_at = db.Column(db.DateTime, nullable=True)

# --- Modify relevant routes ---

# Helper to get or calculate stats (illustrative, caching not fully implemented here)
def get_or_calculate_language_stats(repo_db_obj, ref_name=None):
    """
    Placeholder for fetching cached stats or calculating them.
    For now, it always recalculates for the default branch if ref_name is not specific.
    """
    # Real implementation would check repo_db_obj.language_stats_json and language_stats_updated_at
    # For now, always recalculate.
    # If no specific ref_name, try to get the default branch for the calculation.
    actual_ref_to_calc = ref_name
    if not actual_ref_to_calc:
        try:
            # Try to get default branch for calculation if no specific ref is asked
            # This is usually what's displayed on the main repo page
            actual_ref_to_calc = get_default_branch(repo_db_obj.disk_path)
        except Exception:
            actual_ref_to_calc = "HEAD" # Fallback

    stats = calculate_repo_language_stats(repo_db_obj.disk_path, actual_ref_to_calc)

    # Example: Update cache (if you add the model fields)
    # if stats is not None:
    #     repo_db_obj.language_stats_json = json.dumps(stats)
    #     repo_db_obj.language_stats_updated_at = datetime.utcnow()
    #     try:
    #         db.session.commit()
    #     except Exception as e:
    #         db.session.rollback()
    #         current_app.logger.error(f"Error caching language stats for repo {repo_db_obj.id}: {e}")
    return stats if stats is not None else {}






class RepoEditFileForm(FlaskForm):
    file_content = TextAreaField('File Content', validators=[WTDataRequired()])
    commit_message = WTStringField('Commit Message', validators=[WTDataRequired(), WTLength(min=1, max=200)])
    submit = SubmitField('Save Changes')

REPOS_DIR = os.path.join(os.getcwd(), "git_repositories")
GIT_PATH = "git"  # Path to git executable, ensure it's in your system's PATH

# --- Helper Functions ---
def allowed_file(filename):
    """
    Modified to allow all file extensions and files with no extensions.
    The function still exists in case future filtering logic is desired,
    but for now, it permits everything.
    """
    return True

def secure_path_component(component):
    """
    Secures a single path component.
    Prevents directory traversal and sanitizes the name,
    while attempting to preserve a leading underscore if it's otherwise safe.
    """
    if component == ".." or component == ".":
        return "_"  # Basic traversal prevention

    # Apply Werkzeug's secure_filename for general sanitization
    # This handles spaces, unsafe characters, reserved names etc.
    secured_by_werkzeug = secure_filename(component)

    # If the original component started with an underscore,
    # and secure_filename appears to have removed ONLY that leading underscore,
    # and the rest of the component was otherwise "secure" (not empty),
    # then restore the leading underscore.
    if component.startswith('_') and \
       secured_by_werkzeug and \
       not secured_by_werkzeug.startswith('_') and \
       component[1:] == secured_by_werkzeug:
        # This implies secure_filename just stripped the leading underscore.
        # We re-add it here.
        # Example: component = "_post_macros.html", secured_by_werkzeug = "post_macros.html"
        # Result should be "_post_macros.html"
        final_secured_name = '_' + secured_by_werkzeug
    else:
        # Otherwise, use the name as secured by Werkzeug,
        # or if the component didn't start with '_' in the first place.
        final_secured_name = secured_by_werkzeug

    if not final_secured_name: # If the name became empty after all this processing
        return "_"

    return final_secured_name

def get_repo_disk_path(owner_username, repo_name): # Changed signature
    """
    Generates the standardized disk path for a bare repository.
    Example: <INSTANCE_PATH>/git_repositories/username/reponame.git
    """
    # Sanitize username and repo_name for filesystem path components
    safe_username = secure_filename(str(owner_username)) # Ensure username is filesystem-safe
    safe_repo_name = secure_filename(str(repo_name))     # Ensure repo_name is filesystem-safe

    if not safe_username or not safe_repo_name:
        # This should ideally not happen if usernames/repo_names are validated at creation
        raise ValueError("Invalid username or repository name for path generation.")

    return os.path.join(current_app.config['GIT_REPOSITORIES_ROOT'], safe_username, f"{safe_repo_name}.git")


def ensure_repos_dir_exists():
    repos_root = current_app.config['GIT_REPOSITORIES_ROOT']
    if not os.path.exists(repos_root):
        os.makedirs(repos_root)
        current_app.logger.info(f"Created Git repositories root directory: {repos_root}")


def get_repo_details_db(owner_username, repo_short_name):
    """Gets repository data from DB by owner's username and repo's short name."""
    user = User.query.filter_by(username=owner_username).first()
    if not user:
        return None
    return GitRepository.query.filter_by(user_id=user.id, name=repo_short_name).first()


def user_can_write_to_repo(user, repo_db_obj):
    """Checks if a user can write to (commit to) a repository."""
    if not user or not user.is_authenticated or not repo_db_obj:
        return False
    # Owner can always write
    if repo_db_obj.user_id == user.id:
        return True
    # Check if the user is a collaborator
    if repo_db_obj.is_collaborator(user): # Assumes GitRepository.is_collaborator(user_obj) method exists
        return True
    return False


def get_default_branch(repo_disk_path):
    """Gets the default branch of a repository (e.g., main, master)."""
    git_exe = current_app.config['GIT_EXECUTABLE_PATH']
    if not os.path.exists(os.path.join(repo_disk_path, "HEAD")):
        return "main"

    try:
        result = subprocess.run(
            [git_exe, "--git-dir=" + repo_disk_path, "symbolic-ref", "HEAD"],
            capture_output=True, text=True, check=False
        )
        if result.returncode == 0:
            ref_name = result.stdout.strip()
            if ref_name.startswith("refs/heads/"):
                return ref_name[len("refs/heads/"):]

        result_branches = subprocess.run(
            [git_exe, "--git-dir=" + repo_disk_path, "branch", "--list"],
            capture_output=True, text=True, check=False
        )
        if result_branches.returncode == 0:
            branches = result_branches.stdout.strip().split('\n')
            cleaned_branches = [b.strip().replace("* ", "") for b in branches if b.strip()]
            for common_branch in ['main', 'master']:
                if common_branch in cleaned_branches:
                    return common_branch
            if cleaned_branches:
                return cleaned_branches[0]

        current_app.logger.info(f"No branches found or symbolic-ref failed for {repo_disk_path}, assuming 'main'.")
        return "main"
    except Exception as e:
        current_app.logger.error(f"Error getting default branch for {repo_disk_path}: {e}")
        return "main"

def repo_auth_required_db(f):
    @wraps(f)
    def decorated_function(owner_username, repo_short_name, *args, **kwargs):
        repo_db_obj = get_repo_details_db(owner_username, repo_short_name)
        if not repo_db_obj:
            abort(404, "Repository not found.")

        g.repo = repo_db_obj
        g.repo_disk_path = repo_db_obj.disk_path

        if repo_db_obj.is_private:
            if not current_user.is_authenticated:
                flash("You must be logged in to view this private repository.", "warning")
                if request.endpoint not in ['git_info_refs', 'git_service_rpc']:
                    return redirect(url_for('login', next=request.url))
                else:
                    # For Git HTTP backend, let specific routes handle 401/403.
                    # If we reach here for git operations, it means no WWW-Authenticate was sent yet.
                    # The git_info_refs and git_service_rpc will trigger the 401 if needed.
                    pass


            # Check if the authenticated user is the owner OR a collaborator
            is_owner = (current_user.id == repo_db_obj.user_id)
            is_collaborator = repo_db_obj.is_collaborator(current_user) # Assuming current_user is authenticated

            if not (is_owner or is_collaborator):
                flash("You do not have permission to view this private repository.", "danger")
                if request.endpoint not in ['git_info_refs', 'git_service_rpc']:
                    return redirect(url_for('git_homepage'))
                else:
                    # For Git HTTP backend on private repos, if not owner or collaborator, deny.
                    # This logic is now more aligned with the checks within git_info_refs/git_service_rpc
                    # based on whether those routes themselves require auth.
                    # The main denial for git operations will happen within those routes if auth fails.
                    # Here, we just ensure that if it's private, the user has some link (owner/collaborator).
                     service = request.args.get('service') # For info/refs
                     service_rpc_from_url = kwargs.get('service_rpc') # For service_rpc routes

                     if service == 'git-receive-pack' or service_rpc_from_url == 'git-receive-pack': # Pushing
                         abort(403, "Write access denied to private repository.")
                     elif service == 'git-upload-pack' or service_rpc_from_url == 'git-upload-pack': # Pulling/Cloning
                         abort(403, "Read access denied to private repository.")

        return f(owner_username, repo_short_name, *args, **kwargs)
    return decorated_function


# --- Flask Routes (Authentication, Dashboard, Repo Creation/Deletion) ---
@app.before_request
def make_session_permanent():
    session.permanent = True # Or use app.permanent_session_lifetime

@app.route("/git")
def git_homepage():
    public_repos_query = GitRepository.query.filter_by(is_private=False).order_by(GitRepository.updated_at.desc())
    public_repos_list = public_repos_query.all()

    repos_with_details = []
    for repo_obj in public_repos_list: # Renamed repo to repo_obj for clarity
        git_details = get_repo_git_details(repo_obj.disk_path)
        language_stats = get_or_calculate_language_stats(repo_obj) # Calculate for default branch
        # --- NEW: Check if current user has starred this repo ---
        current_user_has_starred_this_repo = False
        if current_user.is_authenticated:
            # Assuming current_user.has_starred_repo(repo_object) method exists and works
            current_user_has_starred_this_repo = current_user.has_starred_repo(repo_obj)
        # --- END NEW ---

        repos_with_details.append({
            'repo': repo_obj,
            'git_details': git_details,
            'language_stats': language_stats, # Add language stats
            'current_user_starred': current_user_has_starred_this_repo # Add this status
        })

    return render_template("git/git_homepage.html",
                           public_repos_data=repos_with_details) # Pass the enhanced data


@app.route("/git/mygit")
@login_required
def mygit():
    # 1. Repositories owned by the current user
    owned_repos_query = GitRepository.query.filter_by(user_id=current_user.id).order_by(GitRepository.updated_at.desc()) #
    owned_repos_list = owned_repos_query.all() #

    owned_repos_details = []
    for repo_obj in owned_repos_list:
        git_details = get_repo_git_details(repo_obj.disk_path) #
        language_stats = get_or_calculate_language_stats(repo_obj) #
        owned_repos_details.append({
            'repo': repo_obj,
            'git_details': git_details,
            'language_stats': language_stats,
            'access_type': 'owner' # Explicitly mark as owner
        })

    # 2. Repositories the current user collaborates on
    collaborated_repos_query = current_user.collaborating_repositories.order_by(GitRepository.updated_at.desc()) #
    collaborated_repos_list = collaborated_repos_query.all() #

    collaborated_repos_details = []
    for repo_obj in collaborated_repos_list:
        # Ensure we don't list a repo here if it's already in owned_repos_list
        # (though current logic prevents owner from being a collaborator on their own repo)
        if not any(owned_repo_data['repo'].id == repo_obj.id for owned_repo_data in owned_repos_details):
            git_details = get_repo_git_details(repo_obj.disk_path) #
            language_stats = get_or_calculate_language_stats(repo_obj) #
            collaborated_repos_details.append({
                'repo': repo_obj,
                'git_details': git_details,
                'language_stats': language_stats,
                'access_type': 'collaborator' # Explicitly mark as collaborator
            })

    return render_template(
        "git/mygit.html",
        owned_repos_data=owned_repos_details,
        collaborated_repos_data=collaborated_repos_details
    )


@app.route("/git/repo/create", methods=["GET", "POST"])
@login_required
def create_repo_route():
    if request.method == "POST":
        repo_name = request.form["repo_name"].strip()
        visibility = request.form["visibility"]
        description = request.form.get("description", "").strip()

        if not repo_name or not all(c.isalnum() or c in ['_', '-'] for c in repo_name) or len(repo_name) > 100:
            flash("Invalid repository name. Max 100 chars, use alphanumeric, underscores, hyphens.", "danger")
            return render_template("git/create_repo.html", description=description) # Pass back description

        # Check DB for existing repo by this user with the same name
        existing_repo_db = GitRepository.query.filter_by(user_id=current_user.id, name=repo_name).first()
        if existing_repo_db:
            flash(f"Repository '{repo_name}' already exists for your account.", "danger")
            return render_template("git/create_repo.html", repo_name=repo_name, description=description)

        repo_disk_path = get_repo_disk_path(current_user.username, repo_name)

        if os.path.exists(repo_disk_path):
            flash(f"A directory for '{repo_name}' already exists on disk. This indicates an inconsistency. Please contact support or try a different name.", "danger")
            current_app.logger.error(f"Disk path conflict during repo creation: {repo_disk_path} for user {current_user.username}")
            return render_template("git/create_repo.html", repo_name=repo_name, description=description)

        try:
            user_repo_base_dir = os.path.dirname(repo_disk_path) # e.g., .../git_repositories/username/
            if not os.path.exists(user_repo_base_dir):
                os.makedirs(user_repo_base_dir)

            git_exe = current_app.config['GIT_EXECUTABLE_PATH']
            subprocess.run([git_exe, "init", "--bare", repo_disk_path], check=True, capture_output=True)

            new_repo_db = GitRepository(
                user_id=current_user.id,
                name=repo_name,
                description=description,
                is_private=(visibility == "private"),
                disk_path=repo_disk_path
            )
            db.session.add(new_repo_db)
            db.session.commit()

            flash(f"Repository '{repo_name}' created successfully!", "success")
            # Redirect to the new repository's page
            return redirect(url_for('view_repo_root', owner_username=current_user.username, repo_short_name=repo_name))
        except subprocess.CalledProcessError as e:
            flash(f"Error initializing Git repository: {e.stderr.decode(errors='ignore') or str(e)}", "danger")
            current_app.logger.error(f"Git init error for {repo_disk_path}: {e.stderr.decode(errors='ignore')}")
        except Exception as e:
            db.session.rollback()
            flash(f"An unexpected error occurred: {str(e)}", "danger")
            current_app.logger.error(f"Unexpected error creating repo {repo_name} for {current_user.username}: {e}", exc_info=True)
            # Cleanup if repo dir was created but DB entry failed
            if os.path.exists(repo_disk_path):
                # Be cautious with rmtree. Only remove if we are sure it was *just* created.
                # For now, we will not auto-delete to prevent accidental data loss if the dir pre-existed due to an error.
                current_app.logger.warning(f"Repository directory {repo_disk_path} might need manual cleanup after creation failure.")

        return render_template("git/create_repo.html", repo_name=repo_name, description=description) # Re-render form with data

    return render_template("git/create_repo.html") # For GET request

@app.route('/<owner_username>/<repo_short_name>/settings/collaborators/add', methods=['POST'])
@login_required
@repo_auth_required_db
def add_collaborator_route(owner_username, repo_short_name):
    repo_db_obj = g.repo
    if repo_db_obj.user_id != current_user.id:
        flash("Only the repository owner can add collaborators.", "danger")
        return redirect(url_for('repo_settings', owner_username=owner_username, repo_short_name=repo_short_name))

    username_to_add = request.form.get('username_to_add', '').strip()
    if not username_to_add:
        flash("Please enter a username to add as a collaborator.", "warning")
        return redirect(url_for('repo_settings', owner_username=owner_username, repo_short_name=repo_short_name) + "#collaborators-section")

    user_to_add = User.query.filter_by(username=username_to_add).first()

    if not user_to_add:
        flash(f"User '{username_to_add}' not found.", "danger")
    elif user_to_add.id == current_user.id:
        flash("You cannot add yourself as a collaborator.", "warning")
    elif repo_db_obj.is_collaborator(user_to_add):
        flash(f"User '{username_to_add}' is already a collaborator on this repository.", "info")
    else:
        try:
            repo_db_obj.add_collaborator(user_to_add)
            db.session.commit()
            flash(f"User '{username_to_add}' has been added as a collaborator.", "success")
            current_app.logger.info(f"User {user_to_add.username} added as collaborator to {repo_db_obj.name} by {current_user.username}")

            # --- SEND NOTIFICATION ---
            create_notification(
                recipient_user=user_to_add,
                sender_user=current_user, # The repo owner
                type='repo_collaborator_added',
                repo=repo_db_obj
            )
            # --- END NOTIFICATION ---

        except Exception as e:
            db.session.rollback()
            flash(f"Error adding collaborator: {str(e)}", "danger")
            current_app.logger.error(f"Error adding collaborator {username_to_add} to repo {repo_db_obj.id}: {e}", exc_info=True)

    return redirect(url_for('repo_settings', owner_username=owner_username, repo_short_name=repo_short_name) + "#collaborators-section")



@app.route('/<owner_username>/<repo_short_name>/settings/collaborators/remove/<int:collaborator_user_id>', methods=['POST'])
@login_required
@repo_auth_required_db
def remove_collaborator_route(owner_username, repo_short_name, collaborator_user_id):
    repo_db_obj = g.repo
    if repo_db_obj.user_id != current_user.id:
        flash("Only the repository owner can remove collaborators.", "danger")
        return redirect(url_for('repo_settings', owner_username=owner_username, repo_short_name=repo_short_name))

    user_to_remove = User.query.get(collaborator_user_id)

    if not user_to_remove:
        flash("Collaborator not found.", "danger")
    elif not repo_db_obj.is_collaborator(user_to_remove):
        flash(f"User '{user_to_remove.username}' is not a collaborator on this repository.", "info")
    else:
        try:
            repo_db_obj.remove_collaborator(user_to_remove)
            db.session.commit()
            flash(f"User '{user_to_remove.username}' has been removed as a collaborator.", "success")
            current_app.logger.info(f"User {user_to_remove.username} removed as collaborator from {repo_db_obj.name} by {current_user.username}")

            # --- SEND NOTIFICATION ---
            create_notification(
                recipient_user=user_to_remove,
                sender_user=current_user, # The repo owner
                type='repo_collaborator_removed',
                repo=repo_db_obj
            )
            # --- END NOTIFICATION ---

        except Exception as e:
            db.session.rollback()
            flash(f"Error removing collaborator: {str(e)}", "danger")
            current_app.logger.error(f"Error removing collaborator {user_to_remove.username} from repo {repo_db_obj.id}: {e}", exc_info=True)

    return redirect(url_for('repo_settings', owner_username=owner_username, repo_short_name=repo_short_name) + "#collaborators-section")


@app.route("/git/repo/delete/<int:repo_id>", methods=["POST"]) # Use repo_id from DB
@login_required
def delete_repo(repo_id):
    repo = GitRepository.query.get_or_404(repo_id)

    if repo.user_id != current_user.id and not current_user.is_admin: # Allow admin to delete any repo
        flash("You do not have permission to delete this repository.", "danger")
        abort(403)

    repo_name_log = repo.name
    repo_disk_path_log = repo.disk_path

    try:
        # Delete the GitRepository record (cascades should handle User backref if setup, or handle manually)
        # Also consider what happens to forks if a source repo is deleted.
        # For now, `ondelete='SET NULL'` for `forked_from_id` means forks will lose their source link.
        db.session.delete(repo)
        db.session.commit() # Commit DB change first

        # Then delete from disk
        if os.path.exists(repo_disk_path_log) and repo_disk_path_log.startswith(current_app.config['GIT_REPOSITORIES_ROOT']):
            shutil.rmtree(repo_disk_path_log)
            current_app.logger.info(f"Deleted repository directory: {repo_disk_path_log}")
        else:
            current_app.logger.warning(f"Repository directory not found or path suspicious during delete: {repo_disk_path_log}")

        flash(f"Repository '{repo_name_log}' deleted successfully.", "success")
    except Exception as e:
        db.session.rollback() # Rollback DB changes if disk deletion or other error occurs after commit attempt
        flash(f"Error deleting repository '{repo_name_log}': {str(e)}", "danger")
        current_app.logger.error(f"Error deleting repo {repo_id} ({repo_name_log}): {e}", exc_info=True)

    if current_user.is_admin and current_user.id != repo.user_id:
        return redirect(url_for('admin_list_users')) # Or an admin dashboard for repos
    return redirect(url_for('mygit'))


# --- Repository Browsing and File Operation Routes ---

@app.route('/<owner_username>/<repo_short_name>')
@repo_auth_required_db # Ensures repo exists and handles private access
def view_repo_root(owner_username, repo_short_name):
    repo_disk_path = g.repo_disk_path # from @repo_auth_required
    default_branch = get_default_branch(repo_disk_path)
    # Redirect to the tree view of the default branch
    return redirect(url_for('view_repo_tree', owner_username=owner_username, repo_short_name=repo_short_name, ref_name=default_branch, object_path=''))

@app.route('/<owner_username>/<repo_short_name>/tree/<ref_name>/', defaults={'object_path': ''})
@app.route('/<owner_username>/<repo_short_name>/tree/<ref_name>/<path:object_path>')
@repo_auth_required_db
def view_repo_tree(owner_username, repo_short_name, ref_name, object_path):
    repo_disk_path = g.repo_disk_path
    items_for_template = []
    is_empty_repo = False
    repo_db = g.repo
    readme_html_content = None
    language_stats_for_view = {}

    # --- Fetch Owner and Collaborators ---
    repo_owner = repo_db.owner # Assuming repo_db.owner is the User object for the owner
    collaborators_list = repo_db.collaborators.all() # Get all collaborator User objects

    # Combine owner and collaborators for the modal list, ensure owner is listed first or distinctly
    # For simplicity, we can pass them separately or combine them here.
    # Let's pass owner and collaborators_list separately to the template.
    # The count should be owner + collaborators.
    total_contributors_count = 1 + len(collaborators_list) # Owner + collaborators
    # --- End Fetch Owner and Collaborators ---


    if not object_path:
        language_stats_for_view = get_or_calculate_language_stats(repo_db, ref_name)

    GIT_PATH = current_app.config.get('GIT_EXECUTABLE_PATH', "git")

    try:
        subprocess.run([GIT_PATH, "--git-dir=" + repo_disk_path, "rev-parse", "--verify", ref_name + "^{commit}"], check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError:
        is_empty_repo = True
        current_app.logger.info(f"Ref '{ref_name}' not found or no commits in {repo_disk_path}. Treating as empty for tree view.")

    if not is_empty_repo:
        try:
            ls_tree_target = f"{ref_name}:{object_path}" if object_path else ref_name
            result = subprocess.run(
                [GIT_PATH, "--git-dir=" + repo_disk_path, "ls-tree", "-l", ls_tree_target],
                capture_output=True, text=True, check=True, errors='ignore'
            )

            readme_found_in_listing = False
            readme_content_raw = ""

            for line in result.stdout.strip().split('\n'):
                if not line: continue
                parts = line.split(None, 3)
                if len(parts) < 4:
                    current_app.logger.warning(f"Could not parse ls-tree line: '{line}' in {repo_disk_path}")
                    continue

                name_part_from_ls_tree = parts[3]
                size_str, name = name_part_from_ls_tree.split('\t', 1) if '\t' in name_part_from_ls_tree else ("-", name_part_from_ls_tree)
                item_path_in_repo = str(Path(object_path) / name) if object_path else name
                latest_commit_details = get_latest_commit_info_for_path(repo_disk_path, item_path_in_repo, ref_name)

                current_item = {
                    "mode": parts[0],
                    "type": parts[1],
                    "sha": parts[2],
                    "name": name,
                    "size": size_str,
                    "full_path": item_path_in_repo,
                    "latest_commit_info": latest_commit_details
                }
                items_for_template.append(current_item)

                if name.lower() == 'readme.md' and parts[1] == 'blob':
                    readme_found_in_listing = True
                    try:
                        readme_show_target = f"{ref_name}:{item_path_in_repo}"
                        readme_result = subprocess.run(
                            [GIT_PATH, "--git-dir=" + repo_disk_path, "show", readme_show_target],
                            capture_output=True, text=True, check=True, errors='ignore'
                        )
                        readme_content_raw = readme_result.stdout
                    except subprocess.CalledProcessError as e_readme:
                        current_app.logger.error(f"Error reading README.md content ({item_path_in_repo}) from {repo_disk_path}: {e_readme.stderr.decode(errors='ignore')}")
                    except Exception as e_readme_general:
                        current_app.logger.error(f"Unexpected error reading README.md content ({item_path_in_repo}): {e_readme_general}", exc_info=True)

            if readme_found_in_listing and readme_content_raw:
                html = markdown.markdown(readme_content_raw, extensions=['extra', 'fenced_code', 'codehilite', 'tables'])
                readme_html_content = Markup(html)

        except subprocess.CalledProcessError as e:
            current_app.logger.warning(f"git ls-tree failed for '{ls_tree_target}' in {repo_disk_path}: {e.stderr.decode(errors='ignore')}")
            flash(f"Could not list contents for '{object_path or '<root>'}'. Path may not exist on branch '{ref_name}'.", "warning")
        except Exception as e_general:
            current_app.logger.error(f"Unexpected error processing tree for {repo_disk_path}, ref {ref_name}, path '{object_path}': {e_general}", exc_info=True)
            flash("An unexpected error occurred while listing repository contents.", "danger")

    path_parts = list(Path(object_path).parts) if object_path else []
    breadcrumbs = [{"name": repo_short_name, "url": url_for('view_repo_root', owner_username=owner_username, repo_short_name=repo_short_name)}]
    breadcrumbs.append({"name": ref_name, "url": url_for('view_repo_tree', owner_username=owner_username, repo_short_name=repo_short_name, ref_name=ref_name, object_path='')})

    current_breadcrumb_path = ""
    for part in path_parts:
        current_breadcrumb_path = str(Path(current_breadcrumb_path) / part)
        breadcrumbs.append({"name": part, "url": url_for('view_repo_tree', owner_username=owner_username, repo_short_name=repo_short_name, ref_name=ref_name, object_path=current_breadcrumb_path)})

    is_true_owner = current_user.is_authenticated and current_user.id == repo_db.user_id
    can_commit = user_can_write_to_repo(current_user, repo_db)

    overall_repo_git_stats = get_repo_git_details(repo_disk_path)
    current_user_starred_repo = False
    if current_user.is_authenticated:
        current_user_starred_repo = current_user.has_starred_repo(repo_db)

    return render_template("git/repo_tree_view.html",
                             owner_username=owner_username,
                             repo_short_name=repo_short_name,
                             ref_name=ref_name,
                             items=items_for_template,
                             current_path=object_path,
                             breadcrumbs=breadcrumbs,
                             is_empty_repo=is_empty_repo and not items_for_template,
                             is_true_owner=is_true_owner,
                             can_commit=can_commit,
                             repo_is_private=repo_db.is_private,
                             repo=repo_db,
                             overall_repo_git_stats=overall_repo_git_stats,
                             current_user_starred_repo=current_user_starred_repo,
                             readme_content=readme_html_content,
                             language_stats=language_stats_for_view,
                             # --- ADDED FOR COLLABORATORS MODAL ---
                             repo_owner=repo_owner,
                             collaborators_list=collaborators_list,
                             total_contributors_count=total_contributors_count
                             # --- END ADDED ---
                            )

@app.route('/<owner_username>/<repo_short_name>/commit/<commit_id>')
@repo_auth_required_db # You'll likely want to use your existing auth decorator
def view_commit(owner_username, repo_short_name, commit_id):
    # g.repo is the GitRepository SQLAlchemy object from @repo_auth_required_db
    # g.repo_disk_path is the physical disk path

    repo_db_model = g.repo
    repo_disk_path = g.repo_disk_path

    try:
        pygit_repo = PyGitRepo(repo_disk_path) # Use your aliased GitPython Repo
        commit = pygit_repo.commit(commit_id)

        # Basic commit details
        commit_details = {
            'hex': commit.hexsha,
            'short_id': commit.hexsha[:7], # Commonly used short hash
            'author_name': commit.author.name,
            'author_email': commit.author.email,
            'authored_date': datetime.fromtimestamp(commit.authored_date, tz=timezone.utc),
            'committer_name': commit.committer.name,
            'committer_email': commit.committer.email,
            'committed_date': datetime.fromtimestamp(commit.committed_date, tz=timezone.utc),
            'message_summary': commit.summary, # First line of message
            'message_full': commit.message,
            'parents': [p.hexsha for p in commit.parents],
            'stats': commit.stats.total, # Dictionary: {'files': N, 'insertions': N, 'deletions': N}
            'diffs': [] # You would populate this by iterating through commit.diff()
        }

        # Example: Getting diffs (can be extensive)
        # for parent_commit in commit.parents: # Usually one parent, more for merges
        #     diff_index = parent_commit.diff(commit, create_patch=True)
        #     for diff_item in diff_index:
        #         commit_details['diffs'].append({
        #             'change_type': diff_item.change_type, # A (added), D (deleted), M (modified), R (renamed), etc.
        #             'a_path': diff_item.a_path,
        #             'b_path': diff_item.b_path,
        #             'diff_text': diff_item.diff.decode('utf-8', errors='ignore') if diff_item.diff else ""
        #         })
        # if not commit.parents: # Initial commit
        #     diff_index = commit.diff(pygit_repo.tree(), create_patch=True) # Diff against empty tree
        #     for diff_item in diff_index:
        #          commit_details['diffs'].append({
        #             'change_type': diff_item.change_type,
        #             'a_path': diff_item.a_path,
        #             'b_path': diff_item.b_path,
        #             'diff_text': diff_item.diff.decode('utf-8', errors='ignore') if diff_item.diff else ""
        #         })


        # Breadcrumbs (similar to other views)
        breadcrumbs = [
            {"name": repo_db_model.owner.username, "url": url_for('user_profile', username=repo_db_model.owner.username)},
            {"name": repo_db_model.name, "url": url_for('view_repo_root', owner_username=repo_db_model.owner.username, repo_short_name=repo_db_model.name)},
            # Optional: Add a link to the list of commits for the current branch if you have such a page
            # {"name": "Commits", "url": url_for('view_repo_commits', owner_username=repo_db_model.owner.username, repo_short_name=repo_db_model.name, ref_name=g.repo.default_branch_or_current_ref_name_if_available)},
            {"name": commit_details['short_id'], "url": ""} # Current page
        ]

        # Pass overall repo stats as well for context in the base template
        overall_repo_git_stats = get_repo_git_details(repo_disk_path)


        # You'll need to create a 'repo_commit_view.html' template
        return render_template('git/repo_commit_view.html',
                               repo=repo_db_model,
                               commit=commit_details,
                               owner_username=owner_username,
                               repo_short_name=repo_short_name,
                               breadcrumbs=breadcrumbs,
                               overall_repo_git_stats=overall_repo_git_stats)

    except InvalidGitRepositoryError:
        current_app.logger.error(f"Invalid Git repository at {repo_disk_path} for commit view.")
        abort(404, "Repository not found or invalid.")
    except Exception as e: # Catches errors from pygit_repo.commit(commit_id) if commit_id is invalid
        current_app.logger.error(f"Error viewing commit '{commit_id}' in '{repo_disk_path}': {e}", exc_info=True)
        flash(f"Could not display commit '{commit_id}'. It might be invalid.", "danger")
        # Redirect to the repo's root or a commits list page
        return redirect(url_for('view_repo_root', owner_username=owner_username, repo_short_name=repo_short_name))

@app.route('/<owner_username>/<repo_short_name>/edit/<ref_name>/<path:file_path>', methods=['GET'])
@login_required
@repo_auth_required_db
def repo_edit_view(owner_username, repo_short_name, ref_name, file_path):
    repo_db_model = g.repo
    repo_disk_path = g.repo_disk_path

    if not user_can_write_to_repo(current_user, repo_db_model): # MODIFIED
        flash("You do not have permission to edit files in this repository.", "danger")
        return redirect(url_for('view_repo_blob', owner_username=owner_username, repo_short_name=repo_short_name, ref_name=ref_name, file_path=file_path))

    # Also update is_owner passed to template, or add can_commit
    can_commit_to_repo = user_can_write_to_repo(current_user, repo_db_model) # NEW VARIABLE


    content = ""
    try:
        show_target = f"{ref_name}:{file_path}"
        git_exe_path = current_app.config.get('GIT_EXECUTABLE_PATH', "git")
        result = subprocess.run(
            [git_exe_path, "--git-dir=" + repo_disk_path, "show", show_target],
            capture_output=True, text=True, check=True, errors='ignore'
        )
        content = result.stdout
    except subprocess.CalledProcessError as e:
        flash(f"Error retrieving file content for editing: {e.stderr.decode(errors='ignore')}", "danger")
        return redirect(url_for('view_repo_blob', owner_username=owner_username, repo_short_name=repo_short_name, ref_name=ref_name, file_path=file_path))
    except Exception as e_show:
        current_app.logger.error(f"Error showing blob content for edit: {e_show}", exc_info=True)
        flash("Could not retrieve file content for editing.", "danger")
        return redirect(url_for('view_repo_blob', owner_username=owner_username, repo_short_name=repo_short_name, ref_name=ref_name, file_path=file_path))

    form = RepoEditFileForm(file_content=content)

    # Determine CodeMirror mode
    codemirror_mode = get_codemirror_mode_from_filename(file_path)

    # Breadcrumbs
    path_parts = list(Path(file_path).parts)
    breadcrumbs = [
        {"name": repo_short_name, "url": url_for('view_repo_tree', owner_username=owner_username, repo_short_name=repo_short_name, ref_name=ref_name, object_path='')},
    ]
    current_breadcrumb_path = ""
    for part in path_parts[:-1]: # Up to parent directory
        current_breadcrumb_path = str(Path(current_breadcrumb_path) / part)
        breadcrumbs.append({"name": part, "url": url_for('view_repo_tree', owner_username=owner_username, repo_short_name=repo_short_name, ref_name=ref_name, object_path=current_breadcrumb_path)})

    # Add the file being viewed/edited itself (non-clickable or links to blob view)
    blob_view_url = url_for('view_repo_blob', owner_username=owner_username, repo_short_name=repo_short_name, ref_name=ref_name, file_path=file_path)
    breadcrumbs.append({"name": path_parts[-1] if path_parts else file_path, "url": blob_view_url})
    breadcrumbs.append({"name": "Edit", "url": ""})


    return render_template('git/repo_edit_view.html',
                           title=f"Edit {file_path.split('/')[-1]}",
                           repo=repo_db_model,
                           owner_username=owner_username,
                           repo_short_name=repo_short_name,
                           ref_name=ref_name,
                           file_path=file_path,
                           original_file_content=content, # Pass original content
                           form=form,
                           breadcrumbs=breadcrumbs,
                           codemirror_mode=codemirror_mode,
                           is_owner=can_commit_to_repo,
                           is_true_owner=(current_user.is_authenticated and current_user.id == repo_db_model.user_id),
                           can_commit=can_commit_to_repo
                           )


@app.route('/<owner_username>/<repo_short_name>/savefile/<ref_name>/<path:original_file_path>', methods=['POST'])
@login_required
@repo_auth_required_db # g.repo, g.repo_disk_path are set
def save_repo_file(owner_username, repo_short_name, ref_name, original_file_path):
    repo_db_model = g.repo
    repo_disk_path = repo_db_model.disk_path
    git_exe_path = current_app.config.get('GIT_EXECUTABLE_PATH', "git")

    if not user_can_write_to_repo(current_user, repo_db_model): # MODIFIED
        if request.is_json:
            return jsonify({"status": "error", "message": "You do not have permission to save files in this repository."}), 403
        flash("You do not have permission to save files in this repository.", "danger")
        return redirect(url_for('view_repo_blob', owner_username=owner_username, repo_short_name=repo_short_name, ref_name=ref_name, file_path=original_file_path))


    if not request.is_json:
        flash("Invalid request format. Expected JSON.", "danger")
        return redirect(url_for('repo_edit_view', owner_username=owner_username, repo_short_name=repo_short_name, ref_name=ref_name, file_path=original_file_path))

    data = request.get_json()
    new_content = data.get('file_content')
    commit_message_input = data.get('commit_message', '').strip()

    # Get the new file path from the payload, default to original if not provided or empty
    new_file_path_str_raw = data.get('new_file_path', original_file_path).strip()
    if not new_file_path_str_raw: # If user clears it, treat as error or revert to original
        new_file_path_str_raw = original_file_path

    # Sanitize the new_file_path_str_raw (crucial for security)
    # Remove leading/trailing slashes, disallow '..'
    path_parts = [secure_path_component(part) for part in Path(new_file_path_str_raw).parts if part and part != '.']
    if not path_parts: # e.g., if path was "/" or "///" or "."
         return jsonify({"status": "error", "message": "Invalid file path specified."}), 400
    new_file_path_str = str(Path(*path_parts))


    if new_content is None:
        return jsonify({"status": "error", "message": "File content is missing."}), 400
    if not commit_message_input:
        return jsonify({"status": "error", "message": "Commit message is required."}), 400

    committer_name = current_user.username
    committer_email = current_user.email if hasattr(current_user, 'email') and current_user.email else f"{current_user.username}@example.com"
    author_string = f"{committer_name} <{committer_email}>"

    is_rename = (new_file_path_str != original_file_path)
    commit_message_to_use = commit_message_input

    if is_rename:
        commit_message_to_use = f"Rename {original_file_path} to {new_file_path_str}\n\n{commit_message_input}".strip()
        # Check for self-overwrite which isn't a rename (e.g. case change on case-insensitive system handled by Git)
        # A true rename means the old path and new path are different entities.
        if Path(temp_clone_dir if 'temp_clone_dir' in locals() else '.') / new_file_path_str == Path(temp_clone_dir if 'temp_clone_dir' in locals() else '.') / original_file_path and new_file_path_str != original_file_path:
            # This handles case changes like file.txt -> File.txt on systems where git might see them as same initially
            # but we still want to record the intent or ensure the casing.
            # For simplicity, we'll let git handle this; if it's just a case change, git mv might not be needed or might error.
            # The `git rm` then `git add` below will handle it.
            pass


    with tempfile.TemporaryDirectory() as temp_clone_dir:
        try:
            is_empty_or_new_branch = False
            try:
                subprocess.run([git_exe_path, "--git-dir=" + repo_disk_path, "rev-parse", "--verify", ref_name + "^{commit}"], check=True, capture_output=True, text=True)
            except subprocess.CalledProcessError:
                result_refs = subprocess.run([git_exe_path, "--git-dir=" + repo_disk_path, "show-ref"], capture_output=True, text=True)
                if not result_refs.stdout.strip():
                    is_empty_or_new_branch = True
                else:
                    return jsonify({"status": "error", "message": f"Branch or reference '{ref_name}' not found."}), 400

            if is_empty_or_new_branch:
                subprocess.run([git_exe_path, "init", temp_clone_dir], check=True, capture_output=True)
                subprocess.run([git_exe_path, "-C", temp_clone_dir, "remote", "add", "origin", repo_disk_path], check=True, capture_output=True)
            else:
                subprocess.run([git_exe_path, "clone", "--branch", ref_name, repo_disk_path, temp_clone_dir], check=True, capture_output=True)

            subprocess.run([git_exe_path, "-C", temp_clone_dir, "config", "user.name", f'"{committer_name}"'], check=True, capture_output=True)
            subprocess.run([git_exe_path, "-C", temp_clone_dir, "config", "user.email", f'"{committer_email}"'], check=True, capture_output=True)

            path_in_clone_original_obj = Path(temp_clone_dir) / original_file_path
            path_in_clone_new_obj = Path(temp_clone_dir) / new_file_path_str

            existing_content_in_repo = ""
            original_file_existed_in_clone = path_in_clone_original_obj.is_file()

            if original_file_existed_in_clone and not is_empty_or_new_branch:
                try:
                    with open(path_in_clone_original_obj, "r", encoding='utf-8', errors='replace') as f_read:
                        existing_content_in_repo = f_read.read()
                except Exception as e_read:
                    current_app.logger.warning(f"Could not read existing file {path_in_clone_original_obj} for comparison: {e_read}")

            # Determine if a commit is actually needed
            content_changed = (new_content != existing_content_in_repo)
            needs_commit = content_changed or is_rename or (is_empty_or_new_branch and not path_in_clone_new_obj.exists()) # Always commit if new branch/file

            if not needs_commit and not original_file_existed_in_clone and not is_empty_or_new_branch:
                 # If original file didn't exist in clone (and not a new branch), and no rename, means we are trying to edit a non-existent file.
                 # This state should ideally be caught by `repo_edit_view` not allowing edit of non-existent files.
                return jsonify({"status": "error", "message": f"Original file '{original_file_path}' not found in repository to edit."}), 404


            if needs_commit:
                if is_rename and original_file_existed_in_clone and original_file_path != new_file_path_str:
                    # If the target for the new name already exists (and it's not the original file just changing case), error.
                    if path_in_clone_new_obj.exists() and not path_in_clone_new_obj.samefile(path_in_clone_original_obj):
                        return jsonify({"status": "error", "message": f"Target path '{new_file_path_str}' already exists. Cannot rename."}), 409

                    # Perform git mv if the original file exists. This handles history better.
                    # Ensure parent dirs for new path exist for git mv
                    path_in_clone_new_obj.parent.mkdir(parents=True, exist_ok=True)
                    subprocess.run([git_exe_path, "-C", temp_clone_dir, "mv", original_file_path, new_file_path_str], check=True, capture_output=True)
                    current_app.logger.info(f"Git mv {original_file_path} to {new_file_path_str} in clone.")
                    # Now write the new content to the new path
                    with open(path_in_clone_new_obj, "w", encoding='utf-8', errors='replace') as f_write:
                        f_write.write(new_content)
                    # `git mv` already stages the move. If content changed, the write ensures new content is staged.
                    # `git add` below will catch any further changes or ensure it's staged if `mv` didn't.
                else: # Not a rename, or original file didn't exist (new file on new branch)
                    path_in_clone_new_obj.parent.mkdir(parents=True, exist_ok=True)
                    with open(path_in_clone_new_obj, "w", encoding='utf-8', errors='replace') as f_write:
                        f_write.write(new_content)

                # Add the new/modified path. If `git mv` was used, this ensures content changes are staged.
                # If only content changed, this stages the modified file.
                # If new file, this stages the new file.
                subprocess.run([git_exe_path, "-C", temp_clone_dir, "add", new_file_path_str], check=True, capture_output=True)

                status_result = subprocess.run([git_exe_path, "-C", temp_clone_dir, "status", "--porcelain"], capture_output=True, text=True)
                if not status_result.stdout.strip() and not is_empty_or_new_branch : # Check if there are actual changes staged
                    # This might happen if content was identical and only case of filename changed on a case-insensitive system
                    # where git considers them the same file after `git add`.
                    return jsonify({"status": "info", "message": "No effective changes to commit."}), 200

                subprocess.run([git_exe_path, "-C", temp_clone_dir, "commit", "-m", commit_message_to_use, f"--author={author_string}"], check=True, capture_output=True)

                if is_empty_or_new_branch:
                    subprocess.run([git_exe_path, "-C", temp_clone_dir, "push", "-u", "origin", f"HEAD:{ref_name}"], check=True, capture_output=True)
                else:
                    subprocess.run([git_exe_path, "-C", temp_clone_dir, "push", "origin", ref_name], check=True, capture_output=True)

                final_redirect_path = new_file_path_str
                success_message = f"File '{Path(new_file_path_str).name}' saved successfully to branch '{ref_name}'."
                if is_rename:
                    success_message = f"File renamed to '{Path(new_file_path_str).name}' and saved to branch '{ref_name}'."

                redirect_url = url_for('view_repo_blob', owner_username=owner_username, repo_short_name=repo_short_name, ref_name=ref_name, file_path=final_redirect_path)
                return jsonify({"status": "success", "message": success_message, "redirect_url": redirect_url}), 200
            else:
                return jsonify({"status": "info", "message": "No changes detected in file content or path. Nothing to commit."}), 200

        except subprocess.CalledProcessError as e:
            error_msg = e.stderr.decode(errors='ignore') if e.stderr else (e.stdout.decode(errors='ignore') if e.stdout else str(e))
            current_app.logger.error(f"Git operation failed during save of '{original_file_path}' to '{new_file_path_str}': {error_msg} (Command: {e.cmd})")
            return jsonify({"status": "error", "message": f"Error saving file via Git: {error_msg}"}), 500
        except Exception as e_save:
            current_app.logger.error(f"Unexpected error saving repo file '{original_file_path}' to '{new_file_path_str}': {str(e_save)}", exc_info=True)
            return jsonify({"status": "error", "message": f"An unexpected server error occurred: {str(e_save)}"}), 500


@app.route('/<owner_username>/<repo_short_name>/raw/<ref_name>/<path:file_path>')
@repo_auth_required_db
def download_repo_file_raw(owner_username, repo_short_name, ref_name, file_path):
    repo_disk_path = g.repo_disk_path
    content_bytes = b""
    try:
        show_target = f"{ref_name}:{file_path}"
        git_exe_path = current_app.config.get('GIT_EXECUTABLE_PATH', "git")
        # Get raw bytes for download
        result = subprocess.run(
            [git_exe_path, "--git-dir=" + repo_disk_path, "show", show_target],
            capture_output=True, check=True # errors='ignore' removed to catch issues
        )
        content_bytes = result.stdout # stdout is already bytes if text=False (default)

        # Try to guess MIME type, default to application/octet-stream
        mime_type = mimetypes.guess_type(file_path)[0] or 'application/octet-stream'

        response = make_response(content_bytes)
        response.headers['Content-Type'] = mime_type
        # Suggest original filename for download
        response.headers['Content-Disposition'] = f'attachment; filename="{Path(file_path).name}"'
        return response

    except subprocess.CalledProcessError as e:
        current_app.logger.error(f"Error getting raw file content: {e.stderr.decode(errors='ignore') if e.stderr else e.stdout.decode(errors='ignore')}", exc_info=True)
        abort(404, "File not found or error retrieving content.")
    except Exception as e_raw:
        current_app.logger.error(f"Unexpected error getting raw file: {e_raw}", exc_info=True)
        abort(500, "Server error retrieving raw file.")

@app.route('/<owner_username>/<repo_short_name>/blob/<ref_name>/<path:file_path>')
@repo_auth_required_db # This decorator should set g.repo and g.repo_disk_path
def view_repo_blob(owner_username, repo_short_name, ref_name, file_path):
    # g.repo is the GitRepository SQLAlchemy object
    # g.repo_disk_path is the physical disk path to the .git folder
    repo_db_model = g.repo
    repo_disk_path = g.repo_disk_path
    content = ""

    try:
        show_target = f"{ref_name}:{file_path}"
        # GIT_PATH is defined globally in your file
        result = subprocess.run(
            [GIT_PATH, "--git-dir=" + repo_disk_path, "show", show_target],
            capture_output=True, text=True, check=True, errors='ignore'
        )
        content = result.stdout
    except subprocess.CalledProcessError as e:
        flash(f"Error retrieving file '{file_path}': {e.stderr.decode(errors='ignore')}", "danger")
        parent_dir_path = str(Path(file_path).parent)
        if parent_dir_path == '.': parent_dir_path = '' # Handle root
        return redirect(url_for('view_repo_tree', owner_username=owner_username, repo_short_name=repo_short_name, ref_name=ref_name, object_path=parent_dir_path))
    except Exception as e_show: # Catch other potential errors during git show
        current_app.logger.error(f"Error showing blob content for {repo_disk_path} - {file_path}: {e_show}", exc_info=True)
        flash(f"Could not display file content for '{file_path}'.", "danger")
        parent_dir_path = str(Path(file_path).parent)
        if parent_dir_path == '.': parent_dir_path = ''
        return redirect(url_for('view_repo_tree', owner_username=owner_username, repo_short_name=repo_short_name, ref_name=ref_name, object_path=parent_dir_path))


    # Breadcrumbs logic (assuming this is correct from your existing code)
    path_parts = list(Path(file_path).parts)
    breadcrumbs = [{"name": repo_short_name, "url": url_for('view_repo_tree', owner_username=owner_username, repo_short_name=repo_short_name, ref_name=ref_name, object_path='')}]
    current_breadcrumb_path = ""
    for part in path_parts[:-1]:
        current_breadcrumb_path = str(Path(current_breadcrumb_path) / part)
        breadcrumbs.append({"name": part, "url": url_for('view_repo_tree', owner_username=owner_username, repo_short_name=repo_short_name, ref_name=ref_name, object_path=current_breadcrumb_path)})
    if path_parts: # Add the current file name as the last, non-clickable breadcrumb
        breadcrumbs.append({"name": path_parts[-1], "url": ""})


    # +++ Get file-specific Git details +++
    file_git_details = get_file_git_details(repo_disk_path, file_path, branch_or_ref=ref_name)

    # +++ ADDED: Get overall repo stats for context (like star count, total commits) +++
    overall_repo_git_stats = get_repo_git_details(repo_disk_path)

    is_true_owner = current_user.is_authenticated and current_user.id == repo_db_model.user_id
    can_commit_to_repo = user_can_write_to_repo(current_user, repo_db_model)

    current_user_starred_status = False
    if current_user.is_authenticated:
        current_user_starred_status = current_user.has_starred_repo(repo_db_model)


    return render_template("git/repo_blob_view.html",
                           owner_username=owner_username,
                           repo_short_name=repo_short_name,
                           ref_name=ref_name,
                           file_path=file_path,
                           content=content,
                           breadcrumbs=breadcrumbs,
                           repo=repo_db_model, # Pass the GitRepository SQLAlchemy object
                           file_git_details=file_git_details,
                           overall_repo_git_stats=overall_repo_git_stats, # Ensure this is passed
                           current_user_starred=current_user_starred_status, # Pass starring status
                           is_true_owner=is_true_owner,
                           can_commit=can_commit_to_repo,
                           # PYGMENTS_AVAILABLE and highlighted_content are removed as per your request
                           )




@app.route('/<owner_username>/<repo_short_name>/createfile/<ref_name>/', defaults={'dir_path': ''}, methods=["GET", "POST"])
@app.route('/<owner_username>/<repo_short_name>/createfile/<ref_name>/<path:dir_path>', methods=["GET", "POST"])
@login_required
@repo_auth_required_db
def create_repo_file(owner_username, repo_short_name, ref_name, dir_path):
    repo_db_model = g.repo
    repo_disk_path = repo_db_model.disk_path
    git_exe_path = current_app.config.get('GIT_EXECUTABLE_PATH', "git")

    if not user_can_write_to_repo(current_user, repo_db_model): # MODIFIED
        if request.method == 'POST' and request.is_json: # Check if POST and JSON for API-like response
             return jsonify({"status": "error", "message": "You do not have permission to create files/folders in this repository."}), 403
        flash("You do not have permission to create files/folders in this repository.", "danger")
        return redirect(url_for('view_repo_root', owner_username=owner_username, repo_short_name=repo_short_name))


    committer_name = current_user.username
    committer_email = current_user.email if hasattr(current_user, 'email') and current_user.email else f"{current_user.username}@example.com"
    author_string = f"{committer_name} <{committer_email}>"

    if request.method == "POST":
        if not request.is_json:
            # This case should ideally not be hit if JS is working
            flash("Invalid request format. Expected JSON.", "danger")
            return render_template("git/repo_create_file.html", owner_username=owner_username, repo_short_name=repo_short_name, ref_name=ref_name, dir_path=dir_path, breadcrumbs=g.get('breadcrumbs', []), repo=repo_db_model)


        data = request.get_json()
        file_name_input = data.get("file_name", "").strip()
        file_content_from_payload = data.get("file_content", "") # Can be empty for folders
        commit_message_input = data.get("commit_message", "").strip()

        if not file_name_input:
            return jsonify({"status": "error", "message": "Path/Filename is required."}), 400
        if not commit_message_input:
            return jsonify({"status": "error", "message": "Commit message is required."}), 400

        is_folder_creation = file_name_input.endswith('/')

        prospective_path_obj = None
        if file_name_input.startswith('/'):
            # Absolute path from repo root
            cleaned_input = file_name_input.lstrip('/')
            if is_folder_creation:
                cleaned_input = cleaned_input.rstrip('/')
            prospective_path_obj = Path(cleaned_input)
        else:
            # Relative to current dir_path
            base_dir = Path(dir_path)
            temp_path = file_name_input
            if is_folder_creation:
                temp_path = temp_path.rstrip('/')
            prospective_path_obj = base_dir / temp_path

        # Security check for '..'
        if '..' in prospective_path_obj.parts:
            return jsonify({"status": "error", "message": "Invalid path: '..' component is not allowed."}), 400
        if str(prospective_path_obj) == '.':
             return jsonify({"status": "error", "message": "Invalid path: A file or folder name must be specified."}), 400


        path_for_git_operations_str = ""
        actual_file_content_to_write = ""
        commit_message_to_use = ""
        final_item_name_for_message = prospective_path_obj.name

        redirect_target_path_str = ""


        if is_folder_creation:
            folder_to_create_path_obj = prospective_path_obj
            # For empty folders, create a .gitkeep file
            path_for_git_operations_obj = folder_to_create_path_obj / ".gitkeep"
            actual_file_content_to_write = "" # .gitkeep is empty
            commit_message_to_use = commit_message_input or f"Create folder {str(folder_to_create_path_obj)}"
            final_item_name_for_message = str(folder_to_create_path_obj)
            redirect_target_path_str = str(folder_to_create_path_obj)
        else:
            # File creation
            path_for_git_operations_obj = prospective_path_obj
            actual_file_content_to_write = file_content_from_payload
            commit_message_to_use = commit_message_input or f"Create file {path_for_git_operations_obj.name}"
            # final_item_name_for_message is already prospective_path_obj.name
            redirect_target_path_str = str(path_for_git_operations_obj.parent if str(path_for_git_operations_obj.parent) != '.' else '')


        path_for_git_operations_str = str(path_for_git_operations_obj)
        if redirect_target_path_str == '.': redirect_target_path_str = ''


        with tempfile.TemporaryDirectory() as temp_clone_dir:
            try:
                is_empty_or_new_branch = False
                try:
                    subprocess.run([git_exe_path, "--git-dir=" + repo_disk_path, "rev-parse", "--verify", ref_name + "^{commit}"], check=True, capture_output=True, text=True)
                except subprocess.CalledProcessError:
                    result_refs = subprocess.run([git_exe_path, "--git-dir=" + repo_disk_path, "show-ref"], capture_output=True, text=True)
                    if not result_refs.stdout.strip(): # No refs at all = empty repo
                        is_empty_or_new_branch = True
                    else: # Ref doesn't exist but repo is not empty
                        return jsonify({"status": "error", "message": f"Branch or reference '{ref_name}' not found."}), 400

                if is_empty_or_new_branch:
                    subprocess.run([git_exe_path, "init", temp_clone_dir], check=True, capture_output=True)
                    subprocess.run([git_exe_path, "-C", temp_clone_dir, "remote", "add", "origin", repo_disk_path], check=True, capture_output=True)
                else:
                    subprocess.run([git_exe_path, "clone", "--branch", ref_name, repo_disk_path, temp_clone_dir], check=True, capture_output=True)

                subprocess.run([git_exe_path, "-C", temp_clone_dir, "config", "user.name", f'"{committer_name}"'], check=True, capture_output=True)
                subprocess.run([git_exe_path, "-C", temp_clone_dir, "config", "user.email", f'"{committer_email}"'], check=True, capture_output=True)

                target_path_in_clone_obj = Path(temp_clone_dir) / path_for_git_operations_str

                # Security check: path should be within temp_clone_dir
                if not target_path_in_clone_obj.resolve().is_relative_to(Path(temp_clone_dir).resolve()):
                    current_app.logger.error(f"Path traversal attempt: {target_path_in_clone_obj} is outside {temp_clone_dir}")
                    return jsonify({"status": "error", "message": "Invalid file path detected."}), 400

                if target_path_in_clone_obj.exists() and not is_folder_creation: # For files, check if it exists to prevent accidental overwrite via create
                     return jsonify({"status": "error", "message": f"File '{path_for_git_operations_str}' already exists. Use edit instead."}), 409 # Conflict

                target_path_in_clone_obj.parent.mkdir(parents=True, exist_ok=True)
                with open(target_path_in_clone_obj, "w", encoding='utf-8') as f:
                    f.write(actual_file_content_to_write)

                subprocess.run([git_exe_path, "-C", temp_clone_dir, "add", path_for_git_operations_str], check=True, capture_output=True)

                subprocess.run([git_exe_path, "-C", temp_clone_dir, "commit", "-m", commit_message_to_use, f"--author={author_string}"], check=True, capture_output=True)

                if is_empty_or_new_branch:
                    subprocess.run([git_exe_path, "-C", temp_clone_dir, "push", "-u", "origin", f"HEAD:{ref_name}"], check=True, capture_output=True)
                else:
                    subprocess.run([git_exe_path, "-C", temp_clone_dir, "push", "origin", ref_name], check=True, capture_output=True)

                item_type_msg = "Folder" if is_folder_creation else "File"
                success_message = f"{item_type_msg} '{final_item_name_for_message}' created successfully in branch '{ref_name}'."
                redirect_url = url_for('view_repo_tree', owner_username=owner_username, repo_short_name=repo_short_name, ref_name=ref_name, object_path=redirect_target_path_str)

                return jsonify({"status": "success", "message": success_message, "redirect_url": redirect_url}), 201 # 201 Created

            except subprocess.CalledProcessError as e:
                error_msg = e.stderr.decode(errors='ignore') if e.stderr else (e.stdout.decode(errors='ignore') if e.stdout else str(e))
                current_app.logger.error(f"Git operation failed during create: {error_msg} (Command: {e.cmd})")
                return jsonify({"status": "error", "message": f"Error creating item via Git: {error_msg}"}), 500
            except Exception as e_create:
                current_app.logger.error(f"Unexpected error creating repo item: {str(e_create)}", exc_info=True)
                return jsonify({"status": "error", "message": f"An unexpected server error occurred: {str(e_create)}"}), 500

    # --- GET request ---
    # Breadcrumbs for GET request
    path_parts_for_breadcrumbs = list(Path(dir_path).parts) if dir_path else []
    current_breadcrumbs = [{"name": repo_short_name, "url": url_for('view_repo_tree', owner_username=owner_username, repo_short_name=repo_short_name, ref_name=ref_name, object_path='')}]
    current_breadcrumb_path_builder = ""
    for part in path_parts_for_breadcrumbs:
        current_breadcrumb_path_builder = str(Path(current_breadcrumb_path_builder) / part)
        current_breadcrumbs.append({"name": part, "url": url_for('view_repo_tree', owner_username=owner_username, repo_short_name=repo_short_name, ref_name=ref_name, object_path=current_breadcrumb_path_builder)})
    current_breadcrumbs.append({"name": "Create New File/Folder", "url": ""}) # Current action

    # For GET, we just render the form. No WTForm instance is strictly needed if parsing JSON on POST.
    # However, if you want to use WTForms for CSRF protection, you'd instantiate it.
    # For simplicity here, assuming CSRF is handled by a macro or a global setup.
    return render_template("git/repo_create_file.html",
                           owner_username=owner_username,
                           repo_short_name=repo_short_name,
                           ref_name=ref_name,
                           dir_path=dir_path,
                           breadcrumbs=current_breadcrumbs,
                           repo=repo_db_model,
                           # Pass empty strings for pre-filling on GET if needed, or handle in template
                           file_name = request.args.get("file_name", ""),
                           file_content = request.args.get("file_content", ""),
                           commit_message = request.args.get("commit_message", "")
                           )

@app.route('/<owner_username>/<repo_short_name>/uploadfiles/<ref_name>/', defaults={'dir_path': ''}, methods=["GET", "POST"])
@app.route('/<owner_username>/<repo_short_name>/uploadfiles/<ref_name>/<path:dir_path>', methods=["GET", "POST"])
@login_required
@repo_auth_required_db # g.repo is the GitRepository SQLAlchemy object
def upload_repo_files(owner_username, repo_short_name, ref_name, dir_path):
    # Corrected permission check
    if not user_can_write_to_repo(current_user, g.repo): # MODIFIED
        flash("You do not have permission to upload files to this repository.", "danger")
        return redirect(url_for('view_repo_root', owner_username=owner_username, repo_short_name=repo_short_name))


    repo_disk_path = g.repo.disk_path # Access attribute from the object

    if not current_user.is_authenticated: # Should be caught by @login_required
        flash("Authentication required.", "danger")
        return redirect(url_for('login'))

    committer_name = current_user.username # Use current_user
    # Assuming current_user object has an email attribute directly:
    committer_email = current_user.email if hasattr(current_user, 'email') and current_user.email else f"{current_user.username}@example.com"
    author_string = f"{committer_name} <{committer_email}>"

    # Breadcrumbs logic (ensure it's present from previous steps)
    path_parts_for_breadcrumbs = list(Path(dir_path).parts) if dir_path else []
    current_breadcrumbs = [{"name": repo_short_name, "url": url_for('view_repo_tree', owner_username=owner_username, repo_short_name=repo_short_name, ref_name=ref_name, object_path='')}]
    current_breadcrumb_path_builder = ""
    for part in path_parts_for_breadcrumbs:
        current_breadcrumb_path_builder = str(Path(current_breadcrumb_path_builder) / part)
        current_breadcrumbs.append({"name": part, "url": url_for('view_repo_tree', owner_username=owner_username, repo_short_name=repo_short_name, ref_name=ref_name, object_path=current_breadcrumb_path_builder)})
    current_breadcrumbs.append({"name": "Upload files", "url": ""})


    if request.method == "POST":
        uploaded_file_storage_objects = request.files.getlist("uploaded_files[]")
        # Get relative paths sent by the client-side script
        uploaded_files_relative_paths = request.form.getlist("uploaded_files_relative_paths[]")
        custom_commit_message = request.form.get("commit_message", "").strip()

        if not uploaded_file_storage_objects or all(not f.filename for f in uploaded_file_storage_objects):
            flash("No files selected for upload.", "danger")
            return render_template("git/repo_upload_files.html", owner_username=owner_username, repo_short_name=repo_short_name, ref_name=ref_name, dir_path=dir_path, breadcrumbs=current_breadcrumbs, commit_message=custom_commit_message)

        if len(uploaded_file_storage_objects) != len(uploaded_files_relative_paths):
            flash("File and path information mismatch. Please try uploading again.", "danger")
            app.logger.error(f"Upload mismatch: {len(uploaded_file_storage_objects)} files, {len(uploaded_files_relative_paths)} paths.")
            return render_template("git/repo_upload_files.html", owner_username=owner_username, repo_short_name=repo_short_name, ref_name=ref_name, dir_path=dir_path, breadcrumbs=current_breadcrumbs, commit_message=custom_commit_message)

        processed_commit_msg_filenames = []
        files_to_add_to_git = [] # Store paths relative to repo root for `git add`

        with tempfile.TemporaryDirectory() as temp_clone_dir:
            try:
                is_empty_or_new_branch = False
                try:
                    subprocess.run([GIT_PATH, "--git-dir=" + repo_disk_path, "rev-parse", "--verify", ref_name + "^{commit}"], check=True, capture_output=True)
                except subprocess.CalledProcessError:
                    is_empty_or_new_branch = True

                if is_empty_or_new_branch:
                    subprocess.run([GIT_PATH, "init", temp_clone_dir], check=True, capture_output=True)
                    subprocess.run([GIT_PATH, "-C", temp_clone_dir, "remote", "add", "origin", repo_disk_path], check=True, capture_output=True)
                else:
                    subprocess.run([GIT_PATH, "clone", "--branch", ref_name, repo_disk_path, temp_clone_dir], check=True, capture_output=True)

                subprocess.run([GIT_PATH, "-C", temp_clone_dir, "config", "user.name", f'"{committer_name}"'], check=True, capture_output=True)
                subprocess.run([GIT_PATH, "-C", temp_clone_dir, "config", "user.email", f'"{committer_email}"'], check=True, capture_output=True)

                for i, file_storage_obj in enumerate(uploaded_file_storage_objects):
                    if file_storage_obj and file_storage_obj.filename:
                        # No longer checking allowed_file, as it always returns True

                        client_relative_path_str = uploaded_files_relative_paths[i]
                        if not client_relative_path_str: # Should be provided by JS
                            app.logger.warning(f"Missing relative path for uploaded file: {file_storage_obj.filename}")
                            continue # Skip this file or handle error

                        # Sanitize each path component of the client-provided relative path
                        path_components = Path(client_relative_path_str).parts
                        sanitized_components = [secure_path_component(part) for part in path_components if part] # Filter empty parts from Path()

                        if not sanitized_components: # e.g. if client_relative_path_str was ".." or similar
                            app.logger.warning(f"Invalid relative path after sanitization: {client_relative_path_str}")
                            continue

                        sanitized_relative_path = Path(*sanitized_components)

                        # Final path within the repository structure
                        target_repo_path = Path(dir_path) / sanitized_relative_path

                        # Full disk path in the temporary clone
                        target_disk_path_in_clone = (Path(temp_clone_dir) / target_repo_path).resolve()


                        # Security check: Ensure the resolved path is still within the temp_clone_dir
                        if not str(target_disk_path_in_clone).startswith(str(Path(temp_clone_dir).resolve())):
                            app.logger.error(f"Path traversal attempt detected or path resolution error. Skipping file: {client_relative_path_str}")
                            flash(f"Skipping file '{client_relative_path_str}' due to invalid path.", "warning")
                            continue

                        target_disk_path_in_clone.parent.mkdir(parents=True, exist_ok=True)
                        file_storage_obj.save(str(target_disk_path_in_clone))

                        files_to_add_to_git.append(str(target_repo_path))
                        processed_commit_msg_filenames.append(Path(client_relative_path_str).name) # Use original basename for message

                if not files_to_add_to_git:
                    flash("No valid files were processed for upload.", "warning")
                    return render_template("git/repo_upload_files.html", owner_username=owner_username, repo_short_name=repo_short_name, ref_name=ref_name, dir_path=dir_path, breadcrumbs=current_breadcrumbs, commit_message=custom_commit_message)

                for file_to_add in files_to_add_to_git:
                     subprocess.run([GIT_PATH, "-C", temp_clone_dir, "add", file_to_add], check=True, capture_output=True)

                commit_message_to_use = custom_commit_message
                if not commit_message_to_use:
                    if len(processed_commit_msg_filenames) == 1:
                        commit_message_to_use = f"Uploaded {processed_commit_msg_filenames[0]}"
                    else:
                        commit_message_to_use = f"Uploaded {len(processed_commit_msg_filenames)} files (e.g., {processed_commit_msg_filenames[0]})"

                status_result = subprocess.run([GIT_PATH, "-C", temp_clone_dir, "status", "--porcelain"], capture_output=True, text=True)
                if not status_result.stdout.strip() and not is_empty_or_new_branch:
                    flash("No changes to commit. Files might be identical or not added.", "info")
                    return redirect(url_for('view_repo_tree', owner_username=owner_username, repo_short_name=repo_short_name, ref_name=ref_name, object_path=dir_path))

                subprocess.run([GIT_PATH, "-C", temp_clone_dir, "commit", "-m", commit_message_to_use, f"--author={author_string}"], check=True, capture_output=True)

                if is_empty_or_new_branch:
                    subprocess.run([GIT_PATH, "-C", temp_clone_dir, "push", "-u", "origin", f"HEAD:{ref_name}"], check=True, capture_output=True)
                else:
                    subprocess.run([GIT_PATH, "-C", temp_clone_dir, "push", "origin", ref_name], check=True, capture_output=True)

                flash(f"{len(files_to_add_to_git)} file(s) uploaded successfully to branch '{ref_name}'.", "success")
                return redirect(url_for('view_repo_tree', owner_username=owner_username, repo_short_name=repo_short_name, ref_name=ref_name, object_path=dir_path))

            except subprocess.CalledProcessError as e:
                error_msg = e.stderr.decode(errors='ignore') or e.stdout.decode(errors='ignore') or str(e)
                app.logger.error(f"Git operation failed during upload: {error_msg} (Command: {e.cmd})")
                flash(f"Error uploading files: {error_msg}", "danger")
            except Exception as e:
                app.logger.error(f"Unexpected error in upload_repo_files: {str(e)}")
                flash(f"An unexpected error occurred during upload: {str(e)}", "danger")

        return render_template("git/repo_upload_files.html", owner_username=owner_username, repo_short_name=repo_short_name, ref_name=ref_name, dir_path=dir_path, breadcrumbs=current_breadcrumbs, commit_message=custom_commit_message)

    # For GET request
    return render_template("git/repo_upload_files.html",
                           owner_username=owner_username,
                           repo_short_name=repo_short_name,
                           ref_name=ref_name,
                           dir_path=dir_path,
                           repo=g.repo,
                           breadcrumbs=current_breadcrumbs,
                           commit_message=""
                          )


# NEW: Fork Repository Route
@app.route('/<owner_username>/<repo_short_name>/action/fork', methods=['POST'])
@login_required
@repo_auth_required_db # Ensures g.repo (source_repo_obj) is set
def fork_repo(owner_username, repo_short_name):
    source_repo_obj = g.repo # The GitRepository SQLAlchemy object of the source
    # source_repo_disk_path = source_repo_obj.disk_path # Already correct via g.repo_disk_path

    fork_owner = current_user # The user performing the fork

    if source_repo_obj.is_private and source_repo_obj.user_id != fork_owner.id:
        flash("You can only fork public repositories or your own private repositories.", "danger")
        return redirect(url_for('view_repo_root', owner_username=owner_username, repo_short_name=repo_short_name))

    fork_repo_name = source_repo_obj.name # Fork usually keeps the same name

    existing_fork = GitRepository.query.filter_by(user_id=fork_owner.id, name=fork_repo_name).first()
    if existing_fork:
        flash(f"You already have a repository named '{fork_repo_name}'.", "danger")
        return redirect(url_for('view_repo_root', owner_username=fork_owner.username, repo_short_name=fork_repo_name)) # Redirect to their existing repo

    new_fork_disk_path = get_repo_disk_path(fork_owner.username, fork_repo_name)

    if os.path.exists(new_fork_disk_path):
        flash(f"A directory for the forked repository '{fork_repo_name}' already exists on your server space. Please resolve this conflict.", "danger")
        return redirect(url_for('view_repo_root', owner_username=owner_username, repo_short_name=repo_short_name))

    try:
        user_forks_base_dir = os.path.dirname(new_fork_disk_path)
        if not os.path.exists(user_forks_base_dir):
            os.makedirs(user_forks_base_dir)

        git_exe = current_app.config['GIT_EXECUTABLE_PATH']
        subprocess.run([git_exe, "clone", "--bare", source_repo_obj.disk_path, new_fork_disk_path], check=True, capture_output=True)

        new_forked_repo_db = GitRepository(
            user_id=fork_owner.id,
            name=fork_repo_name,
            description=source_repo_obj.description,
            is_private=True, # Forks are private by default
            disk_path=new_fork_disk_path,
            forked_from_id=source_repo_obj.id # Link to the source repository
        )
        db.session.add(new_forked_repo_db)
        db.session.commit()

        flash(f"Repository '{owner_username}/{repo_short_name}' successfully forked as '{fork_owner.username}/{fork_repo_name}'. Your fork is private by default.", "success")
        return redirect(url_for('view_repo_root', owner_username=fork_owner.username, repo_short_name=fork_repo_name))

    except subprocess.CalledProcessError as e:
        error_msg = e.stderr.decode(errors='ignore') or str(e)
        current_app.logger.error(f"Git clone error during fork: {error_msg} (Command: {e.cmd})")
        flash(f"Error forking repository: {error_msg}", "danger")
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Unexpected error during fork: {str(e)}", exc_info=True)
        flash(f"An unexpected error occurred while forking: {str(e)}", "danger")
        # Cleanup if disk path was created but DB failed
        if os.path.exists(new_fork_disk_path) and not GitRepository.query.filter_by(disk_path=new_fork_disk_path).first():
            shutil.rmtree(new_fork_disk_path, ignore_errors=True)

    return redirect(url_for('view_repo_root', owner_username=owner_username, repo_short_name=repo_short_name))


@app.route('/<owner_username>/<repo_short_name>/settings', methods=['GET', 'POST'])
@login_required
@repo_auth_required_db # g.repo is the GitRepository SQLAlchemy object
def repo_settings(owner_username, repo_short_name): # repo_short_name is the name from URL
    repo_db_obj = g.repo

    # --- START MODIFICATION ---
    if request.method == 'GET':
        # Explicitly refresh the object and its 'collaborators' collection
        # to ensure we have the absolute latest state from the DB.
        db.session.refresh(repo_db_obj)
        # You might also need to expire the collection attribute if refresh alone isn't enough,
        # though for lazy='dynamic', accessing it should re-query.
        # If the problem persists after refresh, uncomment the line below:
        # db.session.expire(repo_db_obj, ['collaborators'])

        # For debugging, log the state after refresh
        collaborators_after_refresh = repo_db_obj.collaborators.all()
        count_after_refresh = len(collaborators_after_refresh)
        current_app.logger.info(f"[repo_settings GET] Repo '{repo_db_obj.name}' (ID: {repo_db_obj.id}) has {count_after_refresh} collaborator(s) after explicit refresh.")
        for collab in collaborators_after_refresh:
            current_app.logger.info(f"[repo_settings GET]   - Collaborator: {collab.username} (ID: {collab.id})")
    # --- END MODIFICATION ---


    if request.method == 'POST':
        original_repo_name_in_db = repo_db_obj.name
        new_name_for_redirect = original_repo_name_in_db # Start with current name
        settings_updated_successfully = False

        # 1. Handle Visibility Change
        new_visibility_str = request.form.get('visibility')
        if new_visibility_str is not None:
            new_is_private = (new_visibility_str == 'private')
            if repo_db_obj.is_private != new_is_private:
                repo_db_obj.is_private = new_is_private
                settings_updated_successfully = True
                current_app.logger.info(f"Visibility for repo {repo_db_obj.id} changed to {'private' if new_is_private else 'public'}")


        # 2. Handle Description Change
        new_description = request.form.get('description', '').strip()
        # Ensure comparison handles None from DB vs empty string from form correctly.
        current_description = repo_db_obj.description if repo_db_obj.description is not None else ""
        if current_description != new_description:
            repo_db_obj.description = new_description if new_description else None # Store None if empty
            settings_updated_successfully = True
            current_app.logger.info(f"Description for repo {repo_db_obj.id} changed.")

        # 3. Handle Repository Name Change
        new_repo_name_from_form = request.form.get('repo_name', '').strip()
        if new_repo_name_from_form and new_repo_name_from_form != original_repo_name_in_db:
            if not all(c.isalnum() or c in ['_', '-'] for c in new_repo_name_from_form) or len(new_repo_name_from_form) > 100:
                flash("Invalid new repository name. Max 100 chars, use alphanumeric, underscores, hyphens.", "danger")
            elif GitRepository.query.filter(GitRepository.user_id == current_user.id, GitRepository.name == new_repo_name_from_form, GitRepository.id != repo_db_obj.id).first():
                flash(f"You already have a repository named '{new_repo_name_from_form}'.", "danger")
            else:
                old_disk_path = repo_db_obj.disk_path
                new_intended_disk_path = get_repo_disk_path(owner_username, new_repo_name_from_form)

                try:
                    if os.path.exists(old_disk_path):
                        if not os.path.exists(new_intended_disk_path):
                             # Ensure parent directory of new_intended_disk_path exists
                            os.makedirs(os.path.dirname(new_intended_disk_path), exist_ok=True)
                            os.rename(old_disk_path, new_intended_disk_path)
                            repo_db_obj.name = new_repo_name_from_form
                            repo_db_obj.disk_path = new_intended_disk_path
                            settings_updated_successfully = True
                            new_name_for_redirect = new_repo_name_from_form # Update for redirect
                            current_app.logger.info(f"Repo '{original_repo_name_in_db}' renamed to '{new_repo_name_from_form}'. Path: {new_intended_disk_path}")
                        else:
                            flash(f"Error renaming: Target path for '{new_repo_name_from_form}' ({new_intended_disk_path}) already exists.", "danger")
                            current_app.logger.error(f"Path conflict for rename: {new_intended_disk_path} already exists.")
                    else:
                        flash(f"Error renaming: Original repository path for '{original_repo_name_in_db}' not found. Inconsistency detected.", "danger")
                        current_app.logger.error(f"Path not found for rename: {old_disk_path}")
                except OSError as e:
                    flash(f"Error renaming repository directory: {e}", "danger")
                    current_app.logger.error(f"OSError renaming {old_disk_path} to {new_intended_disk_path}: {e}")
        elif not new_repo_name_from_form and request.form.get('repo_name') is not None: # Check if field was submitted empty
             flash("Repository name cannot be empty.", "danger")


        if settings_updated_successfully:
            try:
                db.session.commit()
                flash("Repository settings updated successfully!", "success")
                return redirect(url_for('repo_settings', owner_username=owner_username, repo_short_name=new_name_for_redirect))
            except Exception as e:
                db.session.rollback()
                flash(f"Error saving settings to database: {str(e)}", "danger")
                current_app.logger.error(f"Error committing repo settings for {repo_db_obj.id}: {e}", exc_info=True)
        elif not request.form:
            flash("No changes submitted.", "info")
        # If errors occurred, page will re-render with flashed messages.

    # For GET or if POST had errors and didn't redirect successfully
    return render_template("git/repo_settings.html",
                           repo=repo_db_obj,
                           owner_username=owner_username,
                           repo_short_name=repo_db_obj.name, # Use current name from DB for display
                           current_repo_name_for_url=repo_db_obj.name) # current name for form actions


# --- Git HTTP Backend ---
def get_repo_obj_for_git_http(username_from_url, repo_name_url_part):
    """
    Fetches GitRepository object based on URL parts.
    repo_name_url_part is expected to be "reponame.git".
    """
    if not repo_name_url_part.endswith(".git"):
        return None # Or raise error
    repo_short_name = repo_name_url_part[:-4] # Remove ".git"

    user_owner = User.query.filter_by(username=username_from_url).first()
    if not user_owner:
        return None
    return GitRepository.query.filter_by(user_id=user_owner.id, name=repo_short_name).first()

@app.route('/<username>/<path:repo_name_with_git>/info/refs', methods=['GET'])
@csrf.exempt
def git_info_refs(username, repo_name_with_git):
    service = request.args.get('service')
    git_exe = current_app.config['GIT_EXECUTABLE_PATH']

    if not service or not service.startswith('git-'):
        abort(400, "Invalid service parameter")

    repo_db_obj = get_repo_obj_for_git_http(username, repo_name_with_git)
    if not repo_db_obj:
        current_app.logger.info(f"Git info/refs: Repository not found in DB for {username}/{repo_name_with_git}")
        abort(404, "Repository not found")

    repo_disk_path = repo_db_obj.disk_path
    if not os.path.isdir(repo_disk_path):
        current_app.logger.error(f"Git info/refs: Repository disk path not found or not a directory: {repo_disk_path}")
        abort(404, "Repository storage not found on server")

    authenticated_username_for_git = None # For Basic Auth primarily
    auth_required_for_operation = repo_db_obj.is_private

    if auth_required_for_operation:
        auth = request.authorization
        if auth and auth.username:
            user_from_auth = User.query.filter_by(username=auth.username).first()
            if user_from_auth and user_from_auth.check_password(auth.password):
                authenticated_username_for_git = user_from_auth.username

        if not authenticated_username_for_git:
            # If basic auth failed or not provided for a private repo, demand it.
            resp = make_response('Authentication required for private repository.', 401)
            resp.headers['WWW-Authenticate'] = 'Basic realm="Git Repository Access"'
            return resp

        # If authenticated, check ownership for private repo access
        if repo_db_obj.owner.username != authenticated_username_for_git:
             # TODO: Add collaborator check here in future
            current_app.logger.warning(f"Git info/refs: User {authenticated_username_for_git} denied access to private repo {repo_db_obj.owner.username}/{repo_db_obj.name}")
            abort(403, "Access denied to private repository.")

    # Public repos are readable by anyone for 'git-upload-pack'

    cmd_short_service_name = service.replace('git-', '')
    cmd = [git_exe, cmd_short_service_name, '--advertise-refs', repo_disk_path]

    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        refs_advertisement_output, stderr = proc.communicate()

        if proc.returncode != 0:
            error_output = stderr.decode(errors='ignore').strip()
            current_app.logger.error(f"Git command error (info/refs) for {repo_disk_path}: {error_output}. Command: {' '.join(cmd)}")
            return make_response(f"Git command failed on server: {error_output}", 500, {'Content-Type': 'text/plain'})

        service_line_str = f"# service={service}\n"
        service_line_bytes = service_line_str.encode('utf-8')
        pkt_line_length = len(service_line_bytes) + 4
        hex_pkt_line_length_str = f"{pkt_line_length:04x}"
        first_pkt_line = hex_pkt_line_length_str.encode('utf-8') + service_line_bytes
        flush_pkt = b"0000"
        response_content = first_pkt_line + flush_pkt + refs_advertisement_output

        res = make_response(response_content)
        res.headers['Content-Type'] = f'application/x-{service}-advertisement'
        res.headers['Expires'] = 'Fri, 01 Jan 1980 00:00:00 GMT'
        res.headers['Pragma'] = 'no-cache'
        res.headers['Cache-Control'] = 'no-cache, max-age=0, must-revalidate'
        return res

    except FileNotFoundError:
        current_app.logger.error(f"GIT_EXECUTABLE_PATH '{git_exe}' not found.")
        abort(500, "Git executable not found on server.")
    except Exception as e:
        current_app.logger.error(f"Exception in git_info_refs for {repo_disk_path}: {e}", exc_info=True)
        abort(500, f"Server error processing git request: {str(e)}")



@app.route('/<username>/<path:repo_name_with_git>/<any("git-upload-pack", "git-receive-pack"):service_rpc>', methods=['POST'])
@csrf.exempt
def git_service_rpc(username, repo_name_with_git, service_rpc):
    git_exe = current_app.config['GIT_EXECUTABLE_PATH']
    content_type = request.headers.get('Content-Type', '')
    if content_type != f'application/x-{service_rpc}-request':
        abort(400, f"Invalid Content-Type: {content_type}, expected application/x-{service_rpc}-request")

    repo_db_obj = get_repo_obj_for_git_http(username, repo_name_with_git)
    if not repo_db_obj:
        current_app.logger.info(f"Git RPC: Repository not found in DB for {username}/{repo_name_with_git}")
        abort(404, "Repository not found")

    repo_disk_path = repo_db_obj.disk_path
    if not os.path.isdir(repo_disk_path):
        current_app.logger.error(f"Git RPC: Repository disk path not found: {repo_disk_path}")
        abort(404, "Repository storage not found on server")

    is_push_operation = (service_rpc == 'git-receive-pack')
    authenticated_username_for_git = None # For Basic Auth

    # ALL push operations require auth AND ownership.
    # Private repo pull operations also require auth AND ownership (or collaboration in future).
    auth_required_for_operation = repo_db_obj.is_private or is_push_operation

    if auth_required_for_operation:
        auth = request.authorization
        if auth and auth.username:
            user_from_auth = User.query.filter_by(username=auth.username).first()
            if user_from_auth and user_from_auth.check_password(auth.password):
                authenticated_username_for_git = user_from_auth.username

        if not authenticated_username_for_git:
            resp = make_response('Authentication required.', 401)
            resp.headers['WWW-Authenticate'] = 'Basic realm="Git Repository Access"'
            return resp

        # Permission Check: Owner OR Collaborator (for private repos or push)
        user_is_owner = (repo_db_obj.owner.username == authenticated_username_for_git)

        # FETCH THE AUTHENTICATED USER OBJECT TO CHECK COLLABORATION STATUS
        authenticated_user_object = User.query.filter_by(username=authenticated_username_for_git).first()
        user_is_collaborator = False
        if authenticated_user_object:
            user_is_collaborator = repo_db_obj.is_collaborator(authenticated_user_object)
        if not (user_is_owner or user_is_collaborator):
            current_app.logger.warning(f"Git RPC: User {authenticated_username_for_git} denied access (not owner or collaborator) to repo {repo_db_obj.owner.username}/{repo_db_obj.name} for {service_rpc}")
            abort(403, "Access denied. You are not the owner or a collaborator on this repository.")

        # Further refine push access: Only owner or collaborator (assuming collaborators get write access)
        if is_push_operation and not (user_is_owner or user_is_collaborator):
            current_app.logger.warning(f"Git RPC: User {authenticated_username_for_git} push denied (not owner or collaborator) to repo {repo_db_obj.owner.username}/{repo_db_obj.name}")
            abort(403, "Push access denied. Only the repository owner or collaborators can push.")

        # Check ownership
        if repo_db_obj.owner.username != authenticated_username_for_git:
            # TODO: Add collaborator check here if relevant for read access on private repos
            current_app.logger.warning(f"Git RPC: User {authenticated_username_for_git} denied access (not owner) to repo {repo_db_obj.owner.username}/{repo_db_obj.name} for {service_rpc}")
            abort(403, "Access denied. You are not the owner of this repository.")

        # Explicitly, only owner can push, even if private status was the trigger for auth
        if is_push_operation and repo_db_obj.owner.username != authenticated_username_for_git:
            current_app.logger.warning(f"Git RPC: User {authenticated_username_for_git} push denied (not owner) to repo {repo_db_obj.owner.username}/{repo_db_obj.name}")
            abort(403, "Push access denied. Only the repository owner can push.")

    # For public repos, 'git-upload-pack' (pull/clone) is allowed without auth.
    # 'git-receive-pack' (push) to a public repo would have been caught by `auth_required_for_operation` and required owner auth.

    pack_data = request.get_data()
    cmd_short_service_name = service_rpc.replace('git-', '')
    cmd = [git_exe, cmd_short_service_name, '--stateless-rpc', repo_disk_path]

    try:
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        stdout, stderr = proc.communicate(input=pack_data)

        if proc.returncode != 0:
            error_output = stderr.decode(errors='ignore').strip()
            current_app.logger.error(f"Git command error (RPC {service_rpc}) for {repo_disk_path}: {error_output}. Command: {' '.join(cmd)}")
            return make_response(f"Git command failed:\n{error_output}", 500, {'Content-Type': 'text/plain'})

        res = make_response(stdout)
        res.headers['Content-Type'] = f'application/x-{service_rpc}-result'
        res.headers['Cache-Control'] = 'no-cache, max-age=0, must-revalidate'
        # ... (other headers)
        return res

    except FileNotFoundError:
        current_app.logger.error(f"GIT_EXECUTABLE_PATH '{git_exe}' not found.")
        abort(500, "Git executable not found on server.")
    except Exception as e:
        current_app.logger.error(f"Exception in git_service_rpc for {repo_disk_path}, service {service_rpc}: {e}", exc_info=True)
        abort(500, f"Server error processing git {service_rpc} request: {str(e)}")


@app.route('/<owner_username>/<repo_short_name>/deleteitem/<ref_name>/<path:item_full_path>', methods=['POST'])
@login_required
@repo_auth_required_db # g.repo is the GitRepository SQLAlchemy object
def delete_repo_item(owner_username, repo_short_name, ref_name, item_full_path):
    # Corrected permission check
    if not user_can_write_to_repo(current_user, g.repo): # MODIFIED
        flash("You do not have permission to delete items in this repository.", "danger")
        parent_dir_path = str(Path(item_full_path).parent)
        if parent_dir_path == '.': parent_dir_path = ''
        return redirect(url_for('view_repo_tree', owner_username=owner_username, repo_short_name=repo_short_name, ref_name=ref_name, object_path=parent_dir_path))


    commit_message = request.form.get("commit_message")
    if not commit_message or not commit_message.strip():
        flash("Commit message is required for deletion.", "danger")
        parent_dir_path = str(Path(item_full_path).parent)
        if parent_dir_path == '.': parent_dir_path = ''
        return redirect(url_for('view_repo_tree', owner_username=owner_username, repo_short_name=repo_short_name, ref_name=ref_name, object_path=parent_dir_path))

    repo_disk_path = g.repo.disk_path # Access attribute from the object

    if not current_user.is_authenticated: # Should be caught by @login_required
        flash("Authentication required.", "danger")
        parent_dir_path = str(Path(item_full_path).parent)
        if parent_dir_path == '.': parent_dir_path = ''
        return redirect(url_for('view_repo_tree', owner_username=owner_username, repo_short_name=repo_short_name, ref_name=ref_name, object_path=parent_dir_path))

    committer_name = current_user.username # Use current_user
    # Assuming current_user object has an email attribute directly:
    committer_email = current_user.email if hasattr(current_user, 'email') and current_user.email else f"{current_user.username}@example.com"
    author_string = f"{committer_name} <{committer_email}>"

    # Parent directory for redirection after successful deletion (already defined if error, but good here too)
    parent_path_obj = Path(item_full_path).parent
    redirect_object_path = str(parent_path_obj) if str(parent_path_obj) != '.' else ''

    # Define GIT_PATH from app config or global
    GIT_PATH = current_app.config.get('GIT_EXECUTABLE_PATH', "git")


    with tempfile.TemporaryDirectory() as temp_clone_dir:
        try:
            # Check if the target branch/ref exists.
            is_empty_or_new_branch = False
            try:
                subprocess.run([GIT_PATH, "--git-dir=" + repo_disk_path, "rev-parse", "--verify", ref_name + "^{commit}"], check=True, capture_output=True)
            except subprocess.CalledProcessError:
                # This should ideally not happen if we are deleting from an existing ref view
                flash(f"Branch or reference '{ref_name}' not found in repository.", "danger")
                return redirect(url_for('view_repo_tree', owner_username=owner_username, repo_short_name=repo_short_name, ref_name=ref_name, object_path=redirect_object_path))

            # Clone the specific branch
            subprocess.run([GIT_PATH, "clone", "--branch", ref_name, repo_disk_path, temp_clone_dir], check=True, capture_output=True)

            subprocess.run([GIT_PATH, "-C", temp_clone_dir, "config", "user.name", f'"{committer_name}"'], check=True, capture_output=True)
            subprocess.run([GIT_PATH, "-C", temp_clone_dir, "config", "user.email", f'"{committer_email}"'], check=True, capture_output=True)

            # Check if the item exists in the clone before attempting to remove
            path_in_clone = Path(temp_clone_dir) / item_full_path
            if not path_in_clone.exists():
                flash(f"Item '{item_full_path}' not found in the repository branch '{ref_name}'. It might have been already deleted.", "warning")
                return redirect(url_for('view_repo_tree', owner_username=owner_username, repo_short_name=repo_short_name, ref_name=ref_name, object_path=redirect_object_path))

            # Perform git rm. Use -r for directories, also works for files.
            # Use --ignore-unmatch to prevent error if file is somehow already gone (though we check above).
            # However, an error might be better if our path_in_clone.exists() check was somehow wrong.
            # For simplicity, let's rely on the exists check and expect `git rm` to find it.
            rm_command = [GIT_PATH, "-C", temp_clone_dir, "rm", "-r", item_full_path]
            app.logger.info(f"Executing delete command: {' '.join(rm_command)}")
            rm_result = subprocess.run(rm_command, capture_output=True, text=True) # Don't check=True immediately

            if rm_result.returncode != 0:
                flash(f"Error removing item '{item_full_path}' using Git: {rm_result.stderr or rm_result.stdout}", "danger")
                app.logger.error(f"git rm failed for '{item_full_path}'. Stderr: {rm_result.stderr}, Stdout: {rm_result.stdout}")
                return redirect(url_for('view_repo_tree', owner_username=owner_username, repo_short_name=repo_short_name, ref_name=ref_name, object_path=redirect_object_path))

            # Check git status; if `git rm` removed something, there should be changes.
            status_result = subprocess.run([GIT_PATH, "-C", temp_clone_dir, "status", "--porcelain"], capture_output=True, text=True)
            if not status_result.stdout.strip():
                flash(f"No changes to commit after attempting to delete '{item_full_path}'. It might not have been tracked or was already deleted.", "info")
                return redirect(url_for('view_repo_tree', owner_username=owner_username, repo_short_name=repo_short_name, ref_name=ref_name, object_path=redirect_object_path))

            # Commit the deletion
            commit_command = [GIT_PATH, "-C", temp_clone_dir, "commit", "-m", commit_message, f"--author={author_string}"]
            app.logger.info(f"Executing commit command: {' '.join(commit_command)}")
            subprocess.run(commit_command, check=True, capture_output=True)

            # Push the changes
            push_command = [GIT_PATH, "-C", temp_clone_dir, "push", "origin", ref_name]
            app.logger.info(f"Executing push command: {' '.join(push_command)}")
            subprocess.run(push_command, check=True, capture_output=True)

            flash(f"Successfully deleted '{item_full_path}' from branch '{ref_name}'.", "success")
            return redirect(url_for('view_repo_tree', owner_username=owner_username, repo_short_name=repo_short_name, ref_name=ref_name, object_path=redirect_object_path))

        except subprocess.CalledProcessError as e:
            error_msg = e.stderr.decode(errors='ignore') if e.stderr else (e.stdout.decode(errors='ignore') if e.stdout else str(e))
            app.logger.error(f"Git operation failed during delete: {error_msg} (Command: {e.cmd})")
            flash(f"Error deleting item: {error_msg}", "danger")
        except Exception as e:
            app.logger.error(f"Unexpected error in delete_repo_item: {str(e)}")
            flash(f"An unexpected error occurred: {str(e)}", "danger")

        # Fallback redirect if errors occurred within the try block
        return redirect(url_for('view_repo_tree', owner_username=owner_username, repo_short_name=repo_short_name, ref_name=ref_name, object_path=redirect_object_path))

@app.route('/git/repo/<int:repo_id>/star', methods=['POST'])
@login_required
def star_repo_route(repo_id):
    # Use your GitRepository model
    repo = GitRepository.query.get_or_404(repo_id)

    if current_user.has_starred_repo(repo):
        return jsonify({'status': 'error', 'message': 'Already starred.'}), 400

    current_user.star_repo(repo)
    try:
        db.session.commit()
        return jsonify({'status': 'success', 'message': 'Repository starred!', 'star_count': repo.star_count, 'starred': True})
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error starring repo {repo_id} for user {current_user.id}: {e}")
        return jsonify({'status': 'error', 'message': 'Could not star repository due to a server error.'}), 500


@app.route('/git/repo/<int:repo_id>/unstar', methods=['POST'])
@login_required
def unstar_repo_route(repo_id):
    repo = GitRepository.query.get_or_404(repo_id)

    if not current_user.has_starred_repo(repo):
        return jsonify({'status': 'error', 'message': 'Not starred yet.'}), 400

    current_user.unstar_repo(repo)
    try:
        db.session.commit()
        return jsonify({'status': 'success', 'message': 'Repository unstarred!', 'star_count': repo.star_count, 'starred': False})
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error unstarring repo {repo_id} for user {current_user.id}: {e}")
        return jsonify({'status': 'error', 'message': 'Could not unstar repository due to a server error.'}), 500


@app.route('/git/starred')
@login_required
def starred_repositories_page():
    # Fetch starred repositories and their starred_at time
    starred_repo_data = db.session.query(
        GitRepository,
        repo_stars.c.starred_at
    ).join(
        repo_stars, repo_stars.c.git_repository_id == GitRepository.id
    ).filter(
        repo_stars.c.user_id == current_user.id
    ).order_by(
        repo_stars.c.starred_at.desc()
    ).all()

    repos_for_template = []
    for repo_obj, starred_at_time in starred_repo_data: # Renamed 'repo' to 'repo_obj' for clarity
        # Fetch git_details for each repository
        # Ensure get_repo_git_details function can handle if repo.disk_path is None or invalid,
        # though for starred repos, they should exist.
        git_details_for_this_repo = get_repo_git_details(repo_obj.disk_path)
        language_stats = get_or_calculate_language_stats(repo_obj)

        repos_for_template.append({
            'repo': repo_obj, # The GitRepository SQLAlchemy object
            'starred_at': starred_at_time,
            'git_details': git_details_for_this_repo, # Add the fetched git_details
            'language_stats': language_stats # Add language stats
        })

    return render_template('git/starred_repos.html',
                           title="Starred Repositories",
                           # The key passed to the template is 'repos_data'
                           # The template will iterate through this list.
                           # Each item in 'repos_data' will be a dictionary.
                           repos_data=repos_for_template)


@app.template_filter('humanreadable')
def human_readable_size_filter(size_bytes_str, decimal_places=1):
    """
    Converts a size in bytes (or a string representing bytes)
    into a human-readable string (e.g., 1.5 KB, 10 MB).
    Handles "-" for non-applicable sizes (like directories).
    """
    if size_bytes_str == "-":  # Placeholder for trees or items with no size
        return "-"
    try:
        size_bytes = int(size_bytes_str)
    except (ValueError, TypeError):
        app.logger.warning(f"Could not convert size '{size_bytes_str}' to int for humanreadable filter.")
        return size_bytes_str # Return original string if conversion fails (or handle as 'N/A')

    if size_bytes < 0: # Should not happen for file sizes
        app.logger.warning(f"Received negative size '{size_bytes_str}' for humanreadable filter.")
        return size_bytes_str # Return original
    if size_bytes == 0:
        return "0 Bytes"

    # Using base 1024 (for KiB, MiB, etc., though commonly labeled KB, MB)
    units = ['Bytes', 'KB', 'MB', 'GB', 'TB', 'PB', 'EB', 'ZB', 'YB']

    # Calculate the power. math.log for 0 or negative is undefined, handled by checks above.
    power = math.floor(math.log(size_bytes, 1024)) if size_bytes > 0 else 0

    # Ensure power is within the bounds of the units array
    power = max(0, min(power, len(units) - 1))

    converted_size = size_bytes / (1024 ** power)

    if power == 0:  # Bytes
        return f"{int(converted_size)} {units[power]}" # No decimal places for Bytes
    else:
        # Format with specified decimal places for KB and above
        return f"{converted_size:.{decimal_places}f} {units[power]}"


# --- Run Application ---
if __name__ == '__main__':
    # --- Directory Creation ---
    # Use the app.config value for profile pictures directory
    # This assumes 'app' is your Flask app instance and is configured before this block
    profile_pics_dir_from_config = app.config.get('PROFILE_PICS_FOLDER')
    if profile_pics_dir_from_config:
        if not os.path.exists(profile_pics_dir_from_config):
            os.makedirs(profile_pics_dir_from_config)
            print(f"INFO: Created directory: {profile_pics_dir_from_config}")
        else:
            print(f"INFO: Directory already exists: {profile_pics_dir_from_config}")
    else:
        print("WARNING: app.config['PROFILE_PICS_FOLDER'] is not set. Cannot create profile_pics directory.")

    # Assuming NOTE_FOLDER is a globally defined variable
    if 'NOTE_FOLDER' in globals() or 'NOTE_FOLDER' in locals():
        if not os.path.exists(NOTE_FOLDER):
            os.makedirs(NOTE_FOLDER)
            print(f"INFO: Created directory: {NOTE_FOLDER}")
        else:
            print(f"INFO: Directory already exists: {NOTE_FOLDER}")
    else:
        print("WARNING: Global variable NOTE_FOLDER is not defined. Cannot create notes directory.")

    # --- Database Initialization ---
    print("INFO: Attempting database initialization within app_context...")
    with app.app_context():
        inspector = inspect(db.engine)
        # Ensure the table name matches your AdminSettings.__tablename__ or default convention
        admin_settings_table_name = AdminSettings.__table__.name # Get table name from model
        admin_settings_table_exists = inspector.has_table(admin_settings_table_name)

        if not admin_settings_table_exists:
            print(f"INFO: Database table '{admin_settings_table_name}' not found. Attempting to create all tables now...")
            try:
                db.create_all()
                print("SUCCESS: db.create_all() executed.")
                if inspect(db.engine).has_table(admin_settings_table_name):
                    print(f"SUCCESS: '{admin_settings_table_name}' table confirmed to exist after creation.")
                else:
                    print(f"CRITICAL_ERROR: '{admin_settings_table_name}' table STILL DOES NOT EXIST after db.create_all(). Check model name or other issues.")
            except Exception as e_create:
                print(f"CRITICAL_ERROR: Failed to run db.create_all(): {e_create}")
        else:
            print(f"INFO: Database table '{admin_settings_table_name}' already exists.")

        if inspect(db.engine).has_table(admin_settings_table_name):
            current_settings_row = AdminSettings.query.first()
            if current_settings_row is None:
                print(f"INFO: No admin settings row found in '{admin_settings_table_name}' table. Initializing one now.")
                default_settings = AdminSettings(
                    allow_registration=True, default_storage_limit_mb=1024, max_upload_size_mb=100,
                    ollama_api_url=None, ollama_model=None, mail_server=None, mail_port=None,
                    mail_use_tls=True, mail_use_ssl=False, mail_username=None, mail_password_hashed=None,
                    mail_default_sender_name='PyCloud Notifications', mail_default_sender_email='noreply@example.com' # Change this
                )
                db.session.add(default_settings)
                try:
                    db.session.commit()
                    print("SUCCESS: Default admin settings row created and committed.")
                except Exception as e_commit_new_row:
                    db.session.rollback()
                    print(f"CRITICAL_ERROR: Failed to commit new admin settings row: {e_commit_new_row}")
            else:
                print("INFO: Admin settings row already exists. Checking if updates are needed for new fields...")
                updated = False
                default_values_for_update = {
                    'allow_registration': True, 'default_storage_limit_mb': 1024, 'max_upload_size_mb': 100,
                    'ollama_api_url': None, 'ollama_model': None, 'mail_server': None, 'mail_port': None,
                    'mail_use_tls': True, 'mail_use_ssl': False, 'mail_username': None, 'mail_password_hashed': None,
                    'mail_default_sender_name': 'PyCloud Notifications', 'mail_default_sender_email': 'noreply@example.com' # Change this
                }
                for key, default_value in default_values_for_update.items():
                    if not hasattr(current_settings_row, key) or \
                       (getattr(current_settings_row, key) is None and key in ['allow_registration', 'default_storage_limit_mb', 'max_upload_size_mb', 'mail_use_tls', 'mail_use_ssl', 'mail_default_sender_name', 'mail_default_sender_email']):
                        print(f"INFO: Updating missing/None admin setting: {key} to '{default_value}'")
                        setattr(current_settings_row, key, default_value)
                        updated = True
                if updated:
                    try:
                        db.session.commit()
                        print("SUCCESS: Existing admin settings updated with default values for new/missing fields.")
                    except Exception as e_commit_update:
                        db.session.rollback()
                        print(f"ERROR: Failed to commit updates to existing admin settings: {e_commit_update}")
                else:
                    print("INFO: Admin settings row exists and no new default fields needed to be set or updated.")
        else:
            print(f"CRITICAL_INFO: '{admin_settings_table_name}' table does not exist, cannot populate settings. Uploads will likely fail.")

    print("INFO: Starting Flask development server...")
    configure_mail_from_db(app)
    mail.init_app(app)
    socketio.run(app, debug=True, host='0.0.0.0', port=8080, allow_unsafe_werkzeug=True) # Use socketio.run
