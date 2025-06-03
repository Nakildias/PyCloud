# app/utils.py
import os
import uuid
import shutil
import zipfile
import mimetypes
import codecs
import math
import json
import subprocess
import py7zr
from pathlib import Path
from datetime import datetime, timezone, timedelta
from humanize import naturaltime
import requests
from PIL import Image, ImageSequence
from werkzeug.utils import secure_filename
from flask import current_app, url_for

from .models import User, File, Folder, Setting, Notification, GitRepository
from .models import OllamaChatMessage
from .config import ( # Import necessary configs/constants
    DEFAULT_SETTINGS,
    DEFAULT_MAX_UPLOAD_MB_FALLBACK,
    DEFAULT_MAX_PHOTO_MB, DEFAULT_MAX_VIDEO_MB,
    VIEWABLE_MIMES, EDITABLE_EXTENSIONS,
    LANGUAGE_COLORS, LANGUAGE_EXTENSIONS_MAP, IGNORE_PATTERNS_FOR_STATS
)



# --- File/Folder System Helpers ---
def get_user_upload_path(user_id):
    return os.path.join(current_app.config['UPLOAD_FOLDER'], str(user_id))

def get_post_media_path():
    path = current_app.config.get('STATIC_POST_MEDIA_FOLDER', os.path.join(current_app.root_path, 'app', 'static', 'uploads', 'post_media'))
    try:
        os.makedirs(path, exist_ok=True)
    except OSError as e:
        current_app.logger.error(f"Could not create post media directory: {path} - Error: {e}", exc_info=True)
        raise
    return path

def is_file_editable(filename, mime_type):
    if '.' in filename:
        ext = filename.rsplit('.', 1)[1].lower()
    else:
        ext = ''
    if ext in current_app.config.get('EDITABLE_EXTENSIONS', EDITABLE_EXTENSIONS):
        return True
    return False

def allowed_file(filename):
    return bool(filename)

def allowed_file_upscaler(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in current_app.config.get('ALLOWED_EXTENSIONS_UPSCALER', {'png', 'jpg', 'jpeg', 'webp'})


# --- User Storage and Limits ---
def get_user_storage_info(user):
    from . import db

    limit_type = 'user'
    user_limit_mb = user.storage_limit_mb

    if user_limit_mb is None:
        limit_type = 'default'
        try:
            # DEFAULT_SETTINGS is imported from .config
            default_limit_str = Setting.get('default_storage_limit_mb', DEFAULT_SETTINGS['default_storage_limit_mb'])
            default_limit_mb = int(default_limit_str)
        except (ValueError, TypeError):
            current_app.logger.error(f"Invalid default_storage_limit_mb setting. Using fallback 1024 MB for user {user.id}.")
            default_limit_mb = 1024 # Fallback
        limit_mb = default_limit_mb
    else:
        limit_mb = user_limit_mb

    limit_bytes = limit_mb * 1024 * 1024 if limit_mb > 0 else float('inf')
    current_usage_bytes = db.session.query(db.func.sum(File.filesize)).filter(File.user_id == user.id).scalar() or 0

    return {
        'usage_bytes': current_usage_bytes,
        'limit_bytes': limit_bytes,
        'limit_mb': limit_mb if limit_mb > 0 else None,
        'limit_type': limit_type
    }


# --- Jinja Filters (will be registered in app/__init__.py) ---
def time_since_filter(dt_str, default="just now"):
    if dt_str is None: return default
    dt_actual = None
    if isinstance(dt_str, str):
        try:
            dt_actual = datetime.fromisoformat(dt_str.replace('Z', '+00:00'))
        except ValueError:
            current_app.logger.error(f"Could not parse timestamp string in time_since_filter: '{dt_str}'")
            return default
    elif isinstance(dt_str, datetime):
        dt_actual = dt_str
    else:
        current_app.logger.warning(f"time_since_filter received unexpected type: {type(dt_str)}")
        return default

    if dt_actual is None: return default
    if dt_actual.tzinfo is None: dt_actual = dt_actual.replace(tzinfo=timezone.utc)

    now = datetime.now(timezone.utc)
    try:
        diff = now - dt_actual
    except TypeError as e:
        current_app.logger.error(f"TypeError in time_since_filter diff: now={now}, dt_actual={dt_actual}. Error: {e}")
        return default

    seconds, days = diff.total_seconds(), diff.days
    if days < 0: return "in the future"
    if days >= 365: years = days // 365; return f"{years} year{'s' if years > 1 else ''}"
    if days >= 30: months = days // 30; return f"{months} month{'s' if months > 1 else ''}"
    if days >= 7: weeks = days // 7; return f"{weeks} week{'s' if weeks > 1 else ''}"
    if days > 0: return f"{days} day{'s' if days > 1 else ''}"
    if seconds < 60: return default
    if seconds < 3600: minutes = int(seconds // 60); return f"{minutes} minute{'s' if minutes > 1 else ''}"
    hours = int(seconds // 3600); return f"{hours} hour{'s' if hours > 1 else ''}"

def localetime_filter(dt):
    if dt is None: return ""
    if dt.tzinfo is None: dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()

def get_language_color(language_name): # For Git repo language stats
    # LANGUAGE_COLORS is imported from .config
    return LANGUAGE_COLORS.get(language_name, LANGUAGE_COLORS.get("Other", "#CCCCCC"))

def human_readable_size_filter(size_bytes_str, decimal_places=1): # For Git repo file sizes
    if size_bytes_str == "-": return "-"
    try:
        size_bytes = int(size_bytes_str)
    except (ValueError, TypeError):
        current_app.logger.warning(f"Could not convert size '{size_bytes_str}' to int for humanreadable_size_filter.")
        return size_bytes_str
    if size_bytes < 0: return size_bytes_str
    if size_bytes == 0: return "0 Bytes"
    units = ['Bytes', 'KB', 'MB', 'GB', 'TB', 'PB'] # Simplified units
    power = math.floor(math.log(size_bytes, 1024)) if size_bytes > 0 else 0
    power = max(0, min(power, len(units) - 1))
    converted_size = size_bytes / (1024 ** power)
    if power == 0: return f"{int(converted_size)} {units[power]}"
    return f"{converted_size:.{decimal_places}f} {units[power]}"


# --- Notification Helper ---
def create_notification(recipient_user, sender_user, type, post=None, comment=None, repo=None, custom_message=None, cooldown_minutes=5):
    from . import db
    if not recipient_user:
        current_app.logger.warning("Attempted to create notification without recipient.")
        return

    if sender_user and recipient_user.id == sender_user.id and type in [
        'like_post', 'dislike_post', 'comment_on_post', 'reply_to_comment',
        'share_post', 'share_comment', 'new_follower',
        'repo_collaborator_added', 'repo_collaborator_removed'
    ]:
        current_app.logger.debug(f"Skipping self-notification for user {recipient_user.id} of type {type}")
        return

    time_threshold = datetime.now(timezone.utc) - timedelta(minutes=cooldown_minutes)
    query_existing = Notification.query.filter(
        Notification.user_id == recipient_user.id,
        Notification.sender_id == (sender_user.id if sender_user else None),
        Notification.type == type,
        Notification.timestamp >= time_threshold if cooldown_minutes > 0 else True
    )
    if post: query_existing = query_existing.filter(Notification.related_post_id == post.id)
    else: query_existing = query_existing.filter(Notification.related_post_id.is_(None)) # Use is_ for None checks
    if comment: query_existing = query_existing.filter(Notification.related_comment_id == comment.id)
    else: query_existing = query_existing.filter(Notification.related_comment_id.is_(None))
    if repo: query_existing = query_existing.filter(Notification.related_repo_id == repo.id)
    else: query_existing = query_existing.filter(Notification.related_repo_id.is_(None))

    if query_existing.first():
        current_app.logger.info(f"Spam prevention: Similar notification already exists for User {recipient_user.id}. Skipping.")
        return

    try:
        notification = Notification(
            user_id=recipient_user.id,
            sender_id=sender_user.id if sender_user else None,
            type=type,
            related_post_id=post.id if post else None,
            related_comment_id=comment.id if comment else None,
            related_repo_id=repo.id if repo else None,
            message=custom_message,
            timestamp=datetime.now(timezone.utc)
        )
        db.session.add(notification)
        db.session.commit()
        current_app.logger.info(f"Notification created for User {recipient_user.id} - Type: {type}")
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error creating notification: {e}", exc_info=True)


# --- Ollama Chat Helper ---
def send_message_to_ollama(prompt, history_list):
    ollama_url = Setting.get('ollama_api_url')
    ollama_model = Setting.get('ollama_model')

    if not ollama_url or not ollama_model:
        current_app.logger.warning("Ollama URL or model not configured.")
        return None, "Ollama integration is not configured."

    api_endpoint = ollama_url.rstrip('/') + '/api/chat'
    messages = list(history_list) # Make a copy
    messages.append({"role": "user", "content": prompt})
    payload = {"model": ollama_model, "messages": messages, "stream": False}

    try:
        response = requests.post(api_endpoint, json=payload, timeout=60)
        response.raise_for_status()
        response_data = response.json()
        if response_data and 'message' in response_data and 'content' in response_data['message']:
            return response_data['message']['content'], None
        else:
            current_app.logger.error(f"Unexpected Ollama response format: {response_data}")
            return None, "Received an unexpected response format from Ollama."
    except requests.exceptions.RequestException as e:
        current_app.logger.error(f"Ollama request failed: {e}", exc_info=True)
        error_detail = f"Error: {e}."
        if e.response is not None: error_detail += f" Response: {e.response.text}"
        return None, f"Failed to communicate with Ollama API. {error_detail}"
    except Exception as e:
        current_app.logger.error(f"Unexpected error calling Ollama: {e}", exc_info=True)
        return None, "An unexpected error occurred while contacting the AI."


# --- Archive/Extraction Helpers ---
def get_archive_uncompressed_size(archive_path):
    total_size = 0
    file_ext = os.path.splitext(archive_path)[1].lower()

    if not os.path.exists(archive_path): # Check for file existence first
        raise ValueError("Archive file not found for size check.")

    try:
        if file_ext == '.zip':
            if not zipfile.is_zipfile(archive_path):
                raise ValueError("File is not a valid ZIP archive.")
            with zipfile.ZipFile(archive_path, 'r') as zipf:
                for member in zipf.infolist():
                    if not member.is_dir():
                        total_size += member.file_size
        elif file_ext == '.7z':
            with py7zr.SevenZipFile(archive_path, 'r') as z:
                total_size = sum(f.uncompressed for f in z.list() if not f.is_directory)
        else:
            current_app.logger.warning(f"Cannot determine uncompressed size for unsupported type: {file_ext} in get_archive_uncompressed_size")
            return 0

        return total_size

    except zipfile.BadZipFile:
        raise ValueError("Invalid or corrupted ZIP archive.")
    except py7zr.exceptions.Bad7zFile:
        raise ValueError("Invalid or corrupted .7z archive.")
    except Exception as e:
        current_app.logger.error(f"Error reading archive metadata for size check ({archive_path}, ext: {file_ext}): {e}", exc_info=True)
        raise ValueError(f"Could not read archive ({file_ext}) metadata: {str(e)}")


def add_folder_to_zip(zipf, folder_id, user_id, current_arc_path, user_physical_upload_path):
    # Needs Folder and File models
    subfolders = Folder.query.filter_by(user_id=user_id, parent_folder_id=folder_id).all()
    for subfolder in subfolders:
        subfolder_arc_path = os.path.join(current_arc_path, subfolder.name)
        add_folder_to_zip(zipf, subfolder.id, user_id, subfolder_arc_path, user_physical_upload_path)

    files = File.query.filter_by(user_id=user_id, parent_folder_id=folder_id).all()
    for file_record in files:
        physical_file_path = os.path.join(user_physical_upload_path, file_record.stored_filename)
        file_arc_path = os.path.join(current_arc_path, file_record.original_filename)
        if os.path.exists(physical_file_path):
            try:
                zipf.write(physical_file_path, file_arc_path)
            except Exception as e:
                current_app.logger.warning(f"Could not add file {physical_file_path} to zip: {e}")
        else:
            current_app.logger.warning(f"Physical file not found for DB record {file_record.id} at {physical_file_path}")

def register_extracted_items(extract_base_dir, user_id, parent_folder_id_in_db, user_physical_upload_root):
    from . import db # Local import for db instance
    newly_created_folder_map = {extract_base_dir: parent_folder_id_in_db}
    for root, dirs, files in os.walk(extract_base_dir, topdown=True):
        current_db_parent_id = newly_created_folder_map[root]
        for dirname in list(dirs): # Iterate over a copy of dirs if modifying it
            dir_path_on_disk = os.path.join(root, dirname)
            sanitized_dirname = secure_filename(dirname)
            if not sanitized_dirname:
                current_app.logger.warning(f"Skipping extracted folder with invalid name: {dirname}")
                dirs.remove(dirname) # Prune walk
                continue
            existing_folder = Folder.query.filter_by(user_id=user_id, parent_folder_id=current_db_parent_id, name=sanitized_dirname).first()
            if not existing_folder:
                try:
                    new_folder = Folder(name=sanitized_dirname, user_id=user_id, parent_folder_id=current_db_parent_id)
                    db.session.add(new_folder)
                    db.session.flush()
                    newly_created_folder_map[dir_path_on_disk] = new_folder.id
                except Exception as e:
                    current_app.logger.error(f"Error registering extracted folder '{sanitized_dirname}': {e}", exc_info=True)
                    raise
            else:
                newly_created_folder_map[dir_path_on_disk] = existing_folder.id

        for filename in files:
            filepath_in_temp_extract = os.path.join(root, filename)
            original_sanitized_filename = secure_filename(filename)
            if not original_sanitized_filename:
                current_app.logger.warning(f"Skipping extracted file with invalid name: {filename}")
                continue
            _, ext = os.path.splitext(filename)
            new_stored_filename = str(uuid.uuid4()) + ext
            final_physical_file_path = os.path.join(user_physical_upload_root, new_stored_filename)
            try:
                if not os.path.exists(filepath_in_temp_extract):
                    current_app.logger.warning(f"Physical extracted source file not found for move: {filepath_in_temp_extract}. Skipping.")
                    continue
                os.rename(filepath_in_temp_extract, final_physical_file_path)
            except OSError as e:
                current_app.logger.error(f"Error moving extracted file '{filename}': {e}", exc_info=True)
                continue
            try:
                filesize = os.path.getsize(final_physical_file_path)
                mime_type = mimetypes.guess_type(final_physical_file_path)[0] or 'application/octet-stream'
                new_file = File(
                    original_filename=original_sanitized_filename, stored_filename=new_stored_filename,
                    filesize=filesize, mime_type=mime_type, user_id=user_id, parent_folder_id=current_db_parent_id
                )
                db.session.add(new_file)
            except Exception as e:
                current_app.logger.error(f"Error registering extracted file '{original_sanitized_filename}' into DB: {e}", exc_info=True)
                if os.path.exists(final_physical_file_path):
                    try: os.remove(final_physical_file_path)
                    except OSError: pass
                raise


# --- Git Related Helpers ---
def get_repo_disk_path(owner_username, repo_name):
    safe_username = secure_filename(str(owner_username))
    safe_repo_name = secure_filename(str(repo_name))
    if not safe_username or not safe_repo_name:
        raise ValueError("Invalid username or repository name for path generation.")
    # GIT_REPOSITORIES_ROOT is from config.py via current_app.config
    return os.path.join(current_app.config['GIT_REPOSITORIES_ROOT'], safe_username, f"{safe_repo_name}.git")

def ensure_repos_dir_exists(): # Called during app initialization
    repos_root = current_app.config['GIT_REPOSITORIES_ROOT']
    if not os.path.exists(repos_root):
        os.makedirs(repos_root)
        current_app.logger.info(f"Created Git repositories root directory: {repos_root}")

def get_repo_details_db(owner_username, repo_short_name): # Used by git routes and decorators
    user = User.query.filter_by(username=owner_username).first()
    if not user: return None
    return GitRepository.query.filter_by(user_id=user.id, name=repo_short_name).first()

def user_can_write_to_repo(user, repo_db_obj): # Used by git routes
    if not user or not user.is_authenticated or not repo_db_obj: return False
    if repo_db_obj.user_id == user.id: return True # Owner
    return repo_db_obj.is_collaborator(user) # Collaborator

def get_default_branch(repo_disk_path): # Git helper
    git_exe = current_app.config.get('GIT_EXECUTABLE_PATH', "git")
    if not os.path.exists(os.path.join(repo_disk_path, "HEAD")): return "main" # Default for new/empty
    try:
        result = subprocess.run([git_exe, "--git-dir=" + repo_disk_path, "symbolic-ref", "HEAD"], capture_output=True, text=True, check=False)
        if result.returncode == 0:
            ref_name = result.stdout.strip()
            if ref_name.startswith("refs/heads/"): return ref_name[len("refs/heads/"):]
        # Fallback to checking common branch names if symbolic-ref fails or points elsewhere
        result_branches = subprocess.run([git_exe, "--git-dir=" + repo_disk_path, "branch", "--list"], capture_output=True, text=True, check=False)
        if result_branches.returncode == 0:
            branches = [b.strip().replace("* ", "") for b in result_branches.stdout.strip().split('\n') if b.strip()]
            for common_branch in ['main', 'master']:
                if common_branch in branches: return common_branch
            if branches: return branches[0] # First available branch
        return "main" # Ultimate fallback
    except Exception as e:
        current_app.logger.error(f"Error getting default branch for {repo_disk_path}: {e}")
        return "main"

def get_latest_commit_info_for_path(repo_disk_path, item_path_in_repo, ref_name): # Git helper
    from git import Repo as PyGitRepo, InvalidGitRepositoryError, NoSuchPathError # Local import
    try:
        pygit_repo = PyGitRepo(repo_disk_path)
        resolved_ref_commit = pygit_repo.commit(ref_name)
        commits_iter = pygit_repo.iter_commits(rev=resolved_ref_commit.hexsha, paths=item_path_in_repo, max_count=1)
        last_commit = next(commits_iter, None)
        if last_commit:
            return {
                'id': last_commit.hexsha, 'message': last_commit.message,
                'short_message': last_commit.message.splitlines()[0] if last_commit.message else "[No commit message]",
                'committer_name': last_commit.committer.name if last_commit.committer else "N/A",
                'date': datetime.fromtimestamp(last_commit.committed_date, tz=timezone.utc)
            }
        return None
    except (InvalidGitRepositoryError, NoSuchPathError) as e:
        current_app.logger.error(f"GitPython error for {repo_disk_path} path {item_path_in_repo}: {e}")
        return None
    except Exception as e:
        current_app.logger.error(f"Error getting latest commit for path '{item_path_in_repo}' in {repo_disk_path}: {e}", exc_info=True)
        return None

def get_repo_git_details(repo_disk_path): # Git helper
    from git import Repo as PyGitRepo, InvalidGitRepositoryError, NoSuchPathError # Local import
    details = {'commit_count': 0, 'last_commit_date': None, 'error': None}
    if not os.path.isdir(repo_disk_path):
        details['error'] = "Repo disk path not found."
        return details
    try:
        git_py_repo = PyGitRepo(repo_disk_path)
        if not git_py_repo.head.is_valid() or not git_py_repo.references: # Check for empty repo
            if not list(git_py_repo.iter_commits(all=True, max_count=1)):
                details['error'] = "Empty repository or no commits yet."
                return details

        commits_iter = git_py_repo.iter_commits() # Default branch commits
        first_commit_for_date = next(commits_iter, None)
        if first_commit_for_date:
            details['last_commit_date'] = datetime.fromtimestamp(first_commit_for_date.committed_date, tz=timezone.utc)
            try:
                if git_py_repo.head.is_detached:
                    details['commit_count'] = sum(1 for _ in git_py_repo.iter_commits(git_py_repo.head.commit.hexsha))
                elif git_py_repo.head.ref:
                    details['commit_count'] = sum(1 for _ in git_py_repo.iter_commits(git_py_repo.head.ref.name))
                else: # Fallback for unusual HEAD states
                    details['commit_count'] = sum(1 for _ in git_py_repo.iter_commits('--all'))
            except Exception as e_count:
                current_app.logger.warning(f"Could not accurately count commits for {repo_disk_path}: {e_count}. Falling back.")
                details['commit_count'] = sum(1 for _ in git_py_repo.iter_commits('--all'))
        else: # No commits on default branch, try counting all
            all_commits_list = list(git_py_repo.iter_commits(all=True))
            if all_commits_list:
                details['commit_count'] = len(all_commits_list)
                details['last_commit_date'] = datetime.fromtimestamp(all_commits_list[0].committed_date, tz=timezone.utc)
            else:
                details['error'] = "No commits found."
    except (InvalidGitRepositoryError, NoSuchPathError) as e:
        details['error'] = f"GitPython error: {type(e).__name__}"
    except Exception as e:
        details['error'] = f"Unexpected error: {type(e).__name__}"
        current_app.logger.error(f"Error in get_repo_git_details for {repo_disk_path}: {e}", exc_info=True)
    return details


def get_file_git_details(repo_disk_path, file_path_in_repo, branch_or_ref='HEAD'): # Git helper
    from git import Repo as PyGitRepo, InvalidGitRepositoryError, NoSuchPathError # Local import
    details = {'last_commit_message': None, 'last_commit_date': None, 'creation_date': None, 'error': None}
    if not os.path.isdir(repo_disk_path):
        details['error'] = "Repo disk path not found."
        return details
    try:
        git_py_repo = PyGitRepo(repo_disk_path)
        if not git_py_repo.head.is_valid() and not git_py_repo.references:
            details['error'] = "Repository is empty or has no commits."
            return details
        try:
            resolved_ref = git_py_repo.commit(branch_or_ref)
        except Exception as e_ref:
            details['error'] = f"Reference '{branch_or_ref}' not found."
            return details

        file_commits_iter = git_py_repo.iter_commits(rev=resolved_ref.hexsha, paths=file_path_in_repo, max_count=1)
        last_file_commit = next(file_commits_iter, None)
        if last_file_commit:
            details['last_commit_message'] = last_file_commit.summary
            details['last_commit_date'] = datetime.fromtimestamp(last_file_commit.committed_date, tz=timezone.utc)
        else:
            details['error'] = f"File '{file_path_in_repo}' not found or no history on ref '{branch_or_ref}'."
            return details # No creation date if file not found here

        creation_commits_iter = git_py_repo.iter_commits(rev=resolved_ref.hexsha, paths=file_path_in_repo, reverse=True)
        first_commit_for_file_on_ref = next(creation_commits_iter, None)
        if first_commit_for_file_on_ref:
            details['creation_date'] = datetime.fromtimestamp(first_commit_for_file_on_ref.committed_date, tz=timezone.utc)
        elif not details['error']: # Only add this if no prior error
            details['error'] = (details.get('error') or "") + " Could not determine creation date."
    except (InvalidGitRepositoryError, NoSuchPathError) as e:
        details['error'] = f"GitPython error: {type(e).__name__}"
    except Exception as e:
        details['error'] = f"Unexpected error: {type(e).__name__}"
        current_app.logger.error(f"Error in get_file_git_details for {repo_disk_path}, file {file_path_in_repo}: {e}", exc_info=True)
    return details


def get_codemirror_mode_from_filename(filename): # For Git file editor
    if not filename or '.' not in filename: return 'text/plain'
    ext = filename.rsplit('.', 1)[1].lower()
    simple_map = {
        'py': 'python', 'js': 'javascript', 'json': 'application/json', 'css': 'css',
        'html': 'htmlmixed', 'htm': 'htmlmixed', 'xml': 'xml', 'md': 'markdown',
        'sh': 'shell', 'sql': 'sql', 'yaml': 'yaml', 'yml': 'yaml', 'java': 'text/x-java',
        'c': 'text/x-csrc', 'cpp': 'text/x-c++src', 'h': 'text/x-c++src',
        'hpp': 'text/x-c++src', 'cs': 'text/x-csharp',
    }
    return simple_map.get(ext, 'text/plain')

def secure_path_component(component): # For Git create/upload file routes
    if component == ".." or component == ".": return "_"
    secured_by_werkzeug = secure_filename(component)
    if component.startswith('_') and secured_by_werkzeug and not secured_by_werkzeug.startswith('_') and component[1:] == secured_by_werkzeug:
        final_secured_name = '_' + secured_by_werkzeug
    else:
        final_secured_name = secured_by_werkzeug
    return final_secured_name if final_secured_name else "_"


def calculate_repo_language_stats(repo_disk_path, ref_name="HEAD"): # For Git language stats display
    # LANGUAGE_EXTENSIONS_MAP and IGNORE_PATTERNS_FOR_STATS are imported from .config
    GIT_PATH = current_app.config.get('GIT_EXECUTABLE_PATH', "git")
    language_bytes = {}
    total_code_bytes = 0.0

    if not os.path.isdir(os.path.join(repo_disk_path, 'objects')):
        current_app.logger.warning(f"Invalid Git repo path for stats: {repo_disk_path}")
        return {}
    try:
        subprocess.run([GIT_PATH, "--git-dir=" + repo_disk_path, "rev-parse", "--verify", ref_name + "^{commit}"], check=True, capture_output=True, text=True)
        proc = subprocess.run([GIT_PATH, "--git-dir=" + repo_disk_path, "ls-tree", "-r", "-l", "--full-tree", ref_name], capture_output=True, text=True, check=True, errors='ignore')
        if not proc.stdout.strip(): return {}

        for line in proc.stdout.strip().split('\n'):
            if not line: continue
            parts = line.split(None, 3)
            if len(parts) < 4 or parts[1] != 'blob': continue
            try:
                size_str, file_path_str = parts[3].split('\t', 1)
                if size_str == '-': continue
                file_size = int(size_str)
            except (ValueError, IndexError): continue
            if file_size == 0: continue

            # Filtering logic (simplified for brevity, ensure IGNORE_PATTERNS_FOR_STATS is used correctly)
            if any(patt in file_path_str for patt in IGNORE_PATTERNS_FOR_STATS if patt.endswith('/')) or \
               Path(file_path_str).name.lower() in IGNORE_PATTERNS_FOR_STATS:
                continue

            language = guess_language_from_filename(file_path_str) # Defined below
            if language is None: continue

            language_bytes[language] = language_bytes.get(language, 0) + file_size
            total_code_bytes += file_size

        if total_code_bytes == 0: return {}
        temp_percentages = {lang: (count / total_code_bytes) * 100 for lang, count in language_bytes.items() if (count / total_code_bytes) * 100 >= 0.1}
        return dict(sorted(temp_percentages.items(), key=lambda item: item[1], reverse=True))

    except subprocess.CalledProcessError as e:
        stderr_output = e.stderr if e.stderr else ""
        if "fatal: not a tree object" in stderr_output or "fatal: bad object" in stderr_output:
            return {}
        current_app.logger.error(f"Git command error calculating stats for {repo_disk_path} ref {ref_name}: {stderr_output}")
        return None # Indicate error
    except Exception as e:
        current_app.logger.error(f"Unexpected error calculating stats for {repo_disk_path} ref {ref_name}: {e}", exc_info=True)
        return None

def guess_language_from_filename(filename_str): # Helper for calculate_repo_language_stats
    # LANGUAGE_EXTENSIONS_MAP imported from .config
    if not filename_str: return None
    path = Path(filename_str)
    name_lower = path.name.lower()
    if name_lower in LANGUAGE_EXTENSIONS_MAP: # Filename match (e.g., Makefile)
        lang = LANGUAGE_EXTENSIONS_MAP[name_lower]
        return lang # Can be None if explicitly ignored
    for suffix in reversed(path.suffixes): # Extension match
        s_lower = suffix.lower()
        if s_lower in LANGUAGE_EXTENSIONS_MAP:
            return LANGUAGE_EXTENSIONS_MAP[s_lower] # Can be None
    return None # No rule matched

# --- Clipboard Helpers (File Management) ---
def check_name_conflict(user_id, parent_folder_id, name, item_type, exclude_id=None):
    # Needs Folder and File models
    if item_type == 'folder':
        query = Folder.query.filter_by(user_id=user_id, parent_folder_id=parent_folder_id, name=name)
        if exclude_id: query = query.filter(Folder.id != exclude_id)
        return query.first()
    else: # file
        query = File.query.filter_by(user_id=user_id, parent_folder_id=parent_folder_id, original_filename=name)
        if exclude_id: query = query.filter(File.id != exclude_id)
        return query.first()

def copy_file_record(file_to_copy, target_parent_folder_id, user_id):
    from . import db # Local import
    # Needs User, File models and get_user_storage_info, get_user_upload_path
    original_filename = file_to_copy.original_filename
    if check_name_conflict(user_id, target_parent_folder_id, original_filename, 'file'):
        name_part, ext_part = os.path.splitext(original_filename)
        original_filename = f"{name_part} (copy){ext_part}"
        if check_name_conflict(user_id, target_parent_folder_id, original_filename, 'file'):
            raise ValueError(f"Filename conflict: '{original_filename}' already exists.")

    user_obj = User.query.get(user_id) # Fetch user object for storage info
    if not user_obj: raise ValueError("User not found for storage check.")
    storage_info = get_user_storage_info(user_obj)
    available_bytes = storage_info['limit_bytes'] - storage_info['usage_bytes']
    if file_to_copy.filesize > available_bytes:
        raise ValueError(f"Insufficient storage space for copy.")

    user_upload_path = get_user_upload_path(user_id)
    source_path = os.path.join(user_upload_path, file_to_copy.stored_filename)
    _, ext = os.path.splitext(file_to_copy.original_filename)
    new_stored_filename = str(uuid.uuid4()) + ext
    destination_path = os.path.join(user_upload_path, new_stored_filename)

    try:
        if not os.path.exists(source_path): raise ValueError(f"Original file '{file_to_copy.original_filename}' missing.")
        shutil.copy2(source_path, destination_path)
        new_filesize = os.path.getsize(destination_path)
    except Exception as e:
        current_app.logger.error(f"Error physically copying file {source_path} to {destination_path}: {e}", exc_info=True)
        if os.path.exists(destination_path):
            try:
                os.remove(destination_path)
            except OSError as e_remove: # It's good practice to log this nested error too
                current_app.logger.error(f"Failed to remove partially copied file {destination_path}: {e_remove}")

#        except OSError: pass
#        raise ValueError(f"Failed to copy file '{file_to_copy.original_filename}'.")

    new_file = File(
        original_filename=original_filename, stored_filename=new_stored_filename,
        filesize=new_filesize, mime_type=file_to_copy.mime_type, user_id=user_id,
        parent_folder_id=target_parent_folder_id, is_public=False, public_id=None, public_password_hash=None
    )
    db.session.add(new_file)
    return new_file

def copy_folder_recursive(folder_to_copy, target_parent_folder_id, user_id):
    from . import db # Local import
    # Needs Folder, File models and check_name_conflict, copy_file_record
    files_to_copy = list(folder_to_copy.files_in_folder)
    subfolders_to_copy = list(folder_to_copy.children)

    new_folder_name = folder_to_copy.name
    if check_name_conflict(user_id, target_parent_folder_id, new_folder_name, 'folder'):
        new_folder_name = f"{new_folder_name} (copy)"
        if check_name_conflict(user_id, target_parent_folder_id, new_folder_name, 'folder'):
            raise ValueError(f"Foldername conflict: '{new_folder_name}' already exists.")

    new_folder = Folder(name=new_folder_name, user_id=user_id, parent_folder_id=target_parent_folder_id)
    db.session.add(new_folder)
    db.session.flush() # Get ID for new_folder

    for file_item in files_to_copy:
        copy_file_record(file_item, new_folder.id, user_id)
    for subfolder_item in subfolders_to_copy:
        copy_folder_recursive(subfolder_item, new_folder.id, user_id)
    return new_folder


def delete_folder_recursive(folder, user_id): # Used by file_routes
    from . import db # Local import
    # Needs File, Folder models and get_user_upload_path
    user_upload_dir = get_user_upload_path(user_id)
    for file_item in list(folder.files_in_folder): # Iterate over a copy
        try:
            file_path = os.path.join(user_upload_dir, file_item.stored_filename)
            if os.path.exists(file_path): os.remove(file_path)
            db.session.delete(file_item)
        except Exception as e:
            current_app.logger.error(f"Error deleting file {file_item.id} during recursive folder delete: {e}")
            raise
    for subfolder_item in list(folder.children): # Iterate over a copy
        delete_folder_recursive(subfolder_item, user_id)
    db.session.delete(folder)
