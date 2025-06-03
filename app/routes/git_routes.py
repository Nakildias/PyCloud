# app/routes/git_routes.py
import os
import subprocess
import tempfile
import shutil
import mimetypes
from pathlib import Path
from datetime import datetime, timezone
import json # For language stats caching, if implemented in future in model

from flask import (
    Blueprint, render_template, redirect, url_for, flash, request,
    g, abort, make_response, current_app, jsonify
)
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename
from markupsafe import Markup
import markdown # For README rendering

# GitPython (ensure it's installed)
from git import Repo as PyGitRepo, InvalidGitRepositoryError, NoSuchPathError

# Import from app package
from app import db, csrf # db and csrf from app/__init__
from app.models import User, GitRepository, Setting, repo_stars # Models
from app.forms import RepoEditFileForm # Forms
from app.utils import ( # Utility functions
    get_repo_disk_path, ensure_repos_dir_exists, get_repo_details_db,
    user_can_write_to_repo, get_default_branch,
    get_latest_commit_info_for_path, get_repo_git_details, get_file_git_details,
    get_codemirror_mode_from_filename, secure_path_component,
    calculate_repo_language_stats, get_language_color, # For language stats display
    create_notification # For collaborator notifications
)
from app.decorators import repo_auth_required_db # Custom decorator
# Assuming GIT_PATH is now configured in app.config via config.py
# from app.config import GIT_PATH # Not needed if using current_app.config['GIT_EXECUTABLE_PATH']


# Define the blueprint
bp = Blueprint('git', __name__, url_prefix='/git') # Using '/git' as a common prefix for web routes
                                                 # HTTP backend routes will have their own specific paths.

# --- Web UI Routes for Git Repositories ---

@bp.route("/") # /git/
def git_homepage():
    public_repos_query = GitRepository.query.filter_by(is_private=False).order_by(GitRepository.updated_at.desc())
    public_repos_list = public_repos_query.all()
    repos_with_details = []
    for repo_obj in public_repos_list:
        git_details = get_repo_git_details(repo_obj.disk_path)
        language_stats = calculate_repo_language_stats(repo_obj.disk_path, get_default_branch(repo_obj.disk_path)) # Recalculate, or use cached
        current_user_has_starred = current_user.has_starred_repo(repo_obj) if current_user.is_authenticated else False
        repos_with_details.append({
            'repo': repo_obj, 'git_details': git_details,
            'language_stats': language_stats,
            'current_user_starred': current_user_has_starred
        })
    return render_template("git/git_homepage.html", public_repos_data=repos_with_details)


@bp.route("/mygit") # /git/mygit
@login_required
def mygit():
    owned_repos_list = GitRepository.query.filter_by(user_id=current_user.id).order_by(GitRepository.updated_at.desc()).all()
    owned_repos_details = []
    for repo_obj in owned_repos_list:
        owned_repos_details.append({
            'repo': repo_obj, 'git_details': get_repo_git_details(repo_obj.disk_path),
            'language_stats': calculate_repo_language_stats(repo_obj.disk_path, get_default_branch(repo_obj.disk_path)),
            'access_type': 'owner'
        })

    collaborated_repos_list = current_user.collaborating_repositories.order_by(GitRepository.updated_at.desc()).all()
    collaborated_repos_details = []
    for repo_obj in collaborated_repos_list:
        if not any(owned_data['repo'].id == repo_obj.id for owned_data in owned_repos_details):
            collaborated_repos_details.append({
                'repo': repo_obj, 'git_details': get_repo_git_details(repo_obj.disk_path),
                'language_stats': calculate_repo_language_stats(repo_obj.disk_path, get_default_branch(repo_obj.disk_path)),
                'access_type': 'collaborator'
            })
    return render_template("git/mygit.html", owned_repos_data=owned_repos_details, collaborated_repos_data=collaborated_repos_details)


@bp.route("/repo/create", methods=["GET", "POST"]) # /git/repo/create
@login_required
def create_repo_route():
    if request.method == "POST":
        repo_name = request.form["repo_name"].strip()
        visibility = request.form["visibility"]
        description = request.form.get("description", "").strip()

        if not repo_name or not all(c.isalnum() or c in ['_', '-'] for c in repo_name) or len(repo_name) > 100:
            flash("Invalid repository name.", "danger")
        elif GitRepository.query.filter_by(user_id=current_user.id, name=repo_name).first():
            flash(f"Repository '{repo_name}' already exists.", "danger")
        else:
            repo_disk_path = get_repo_disk_path(current_user.username, repo_name) # Util function
            if os.path.exists(repo_disk_path):
                flash("Directory for this repository already exists on disk. Inconsistency.", "danger")
            else:
                try:
                    user_repo_base_dir = os.path.dirname(repo_disk_path)
                    os.makedirs(user_repo_base_dir, exist_ok=True)
                    git_exe = current_app.config['GIT_EXECUTABLE_PATH']
                    subprocess.run([git_exe, "init", "--bare", repo_disk_path], check=True, capture_output=True)
                    new_repo_db = GitRepository(user_id=current_user.id, name=repo_name, description=description, is_private=(visibility == "private"), disk_path=repo_disk_path)
                    db.session.add(new_repo_db); db.session.commit()
                    flash(f"Repository '{repo_name}' created!", "success")
                    return redirect(url_for('.view_repo_root', owner_username=current_user.username, repo_short_name=repo_name))
                except Exception as e:
                    db.session.rollback(); flash(f"Error creating repository: {e}", "danger")
                    current_app.logger.error(f"Error creating repo {repo_name} for {current_user.username}: {e}", exc_info=True)
        # Re-render form with submitted values if error
        return render_template("git/create_repo.html", repo_name=repo_name, description=description, visibility=visibility)
    return render_template("git/create_repo.html")


@bp.route("/repo/delete/<int:repo_id>", methods=["POST"]) # /git/repo/delete/...
@login_required
def delete_repo_route(repo_id): # Renamed from delete_repo
    repo = GitRepository.query.get_or_404(repo_id)
    if not (repo.user_id == current_user.id or current_user.is_admin):
        flash("Permission denied.", "danger"); abort(403)
    try:
        repo_name_log, repo_disk_path_log = repo.name, repo.disk_path
        db.session.delete(repo); db.session.commit() # DB first
        if os.path.exists(repo_disk_path_log) and repo_disk_path_log.startswith(current_app.config['GIT_REPOSITORIES_ROOT']):
            shutil.rmtree(repo_disk_path_log)
        flash(f"Repository '{repo_name_log}' deleted.", "success")
    except Exception as e:
        db.session.rollback(); flash(f"Error deleting repository: {e}", "danger")
        current_app.logger.error(f"Error deleting repo {repo_id}: {e}", exc_info=True)
    return redirect(url_for('.mygit') if repo.user_id == current_user.id else url_for('admin.admin_list_users')) # Redirect logic depends on context


# --- Routes that require repo_auth_required_db decorator ---
# These routes will have owner_username and repo_short_name in their URL

@bp.route('/<owner_username>/<repo_short_name>') # e.g., /git/user/myrepo
@repo_auth_required_db
def view_repo_root(owner_username, repo_short_name):
    default_branch = get_default_branch(g.repo_disk_path) # Util function
    return redirect(url_for('.view_repo_tree', owner_username=owner_username, repo_short_name=repo_short_name, ref_name=default_branch, object_path=''))


@bp.route('/<owner_username>/<repo_short_name>/tree/<ref_name>/', defaults={'object_path': ''})
@bp.route('/<owner_username>/<repo_short_name>/tree/<ref_name>/<path:object_path>')
@repo_auth_required_db
def view_repo_tree(owner_username, repo_short_name, ref_name, object_path):
    repo_disk_path, repo_db_obj = g.repo_disk_path, g.repo
    items, readme_html, language_stats = [], None, {}
    is_empty_repo = False
    GIT_PATH = current_app.config['GIT_EXECUTABLE_PATH']

    try: subprocess.run([GIT_PATH, "--git-dir=" + repo_disk_path, "rev-parse", "--verify", ref_name + "^{commit}"], check=True, capture_output=True)
    except subprocess.CalledProcessError: is_empty_repo = True

    if not is_empty_repo:
        try:
            ls_tree_target = f"{ref_name}:{object_path}" if object_path else ref_name
            result = subprocess.run([GIT_PATH, "--git-dir=" + repo_disk_path, "ls-tree", "-l", ls_tree_target], capture_output=True, text=True, check=True, errors='ignore')
            readme_content_raw = ""
            for line in result.stdout.strip().split('\n'):
                if not line: continue
                parts = line.split(None, 3)
                if len(parts) < 4: continue
                size_str, name = parts[3].split('\t', 1) if '\t' in parts[3] else ("-", parts[3])
                item_path_in_repo = str(Path(object_path) / name) if object_path else name
                items.append({
                    "mode": parts[0], "type": parts[1], "sha": parts[2], "name": name, "size": size_str,
                    "full_path": item_path_in_repo,
                    "latest_commit_info": get_latest_commit_info_for_path(repo_disk_path, item_path_in_repo, ref_name)
                })
                if name.lower() == 'readme.md' and parts[1] == 'blob':
                    readme_result = subprocess.run([GIT_PATH, "--git-dir=" + repo_disk_path, "show", f"{ref_name}:{item_path_in_repo}"], capture_output=True, text=True, check=True, errors='ignore')
                    readme_content_raw = readme_result.stdout
            if readme_content_raw: readme_html = Markup(markdown.markdown(readme_content_raw, extensions=['extra', 'fenced_code', 'tables']))
        except Exception as e_tree: current_app.logger.error(f"Error listing tree for {repo_short_name}: {e_tree}", exc_info=True); flash("Error listing repository contents.", "danger")

    if not object_path: # Language stats only for root view
        language_stats = calculate_repo_language_stats(repo_disk_path, ref_name) # Util function

    path_parts = list(Path(object_path).parts) if object_path else []
    breadcrumbs = [{"name": repo_short_name, "url": url_for('.view_repo_root', owner_username=owner_username, repo_short_name=repo_short_name)}]
    breadcrumbs.append({"name": ref_name, "url": url_for('.view_repo_tree', owner_username=owner_username, repo_short_name=repo_short_name, ref_name=ref_name, object_path='')})
    current_bc_path = ""
    for part in path_parts: current_bc_path = str(Path(current_bc_path)/part); breadcrumbs.append({"name":part, "url": url_for('.view_repo_tree', owner_username=owner_username, repo_short_name=repo_short_name, ref_name=ref_name, object_path=current_bc_path)})

    return render_template("git/repo_tree_view.html",
                           repo=repo_db_obj, owner_username=owner_username, repo_short_name=repo_short_name, ref_name=ref_name,
                           items=items, current_path=object_path, breadcrumbs=breadcrumbs,
                           is_empty_repo=is_empty_repo and not items,
                           is_true_owner=(current_user.is_authenticated and current_user.id == repo_db_obj.user_id),
                           can_commit=user_can_write_to_repo(current_user, repo_db_obj),
                           overall_repo_git_stats=get_repo_git_details(repo_disk_path),
                           current_user_starred_repo=current_user.has_starred_repo(repo_db_obj) if current_user.is_authenticated else False,
                           readme_content=readme_html, language_stats=language_stats,
                           repo_owner=repo_db_obj.owner, collaborators_list=repo_db_obj.collaborators.all(), # For modal
                           total_contributors_count=1 + repo_db_obj.collaborators.count())


@bp.route('/<owner_username>/<repo_short_name>/blob/<ref_name>/<path:file_path>')
@repo_auth_required_db
def view_repo_blob(owner_username, repo_short_name, ref_name, file_path):
    repo_disk_path, repo_db_obj = g.repo_disk_path, g.repo
    GIT_PATH = current_app.config['GIT_EXECUTABLE_PATH']
    try:
        result = subprocess.run([GIT_PATH, "--git-dir=" + repo_disk_path, "show", f"{ref_name}:{file_path}"], capture_output=True, text=True, check=True, errors='ignore')
        content = result.stdout
    except Exception as e_blob:
        current_app.logger.error(f"Error showing blob {file_path} in {repo_short_name}: {e_blob}", exc_info=True)
        flash(f"Error retrieving file '{file_path}'.", "danger")
        parent_dir = str(Path(file_path).parent)
        parent_dir = '' if parent_dir == '.' else parent_dir # Ensure root path is empty string
        return redirect(url_for('.view_repo_tree', owner_username=owner_username, repo_short_name=repo_short_name, ref_name=ref_name, object_path=parent_dir))

    # Breadcrumbs logic (ensure it's comprehensive)
    path_parts = list(Path(file_path).parts)
    breadcrumbs = [
        {"name": repo_db_obj.name, "url": url_for('.view_repo_root', owner_username=owner_username, repo_short_name=repo_short_name)},
        {"name": ref_name, "url": url_for('.view_repo_tree', owner_username=owner_username, repo_short_name=repo_short_name, ref_name=ref_name, object_path='')}
    ]
    current_path_accumulated = ""
    for part in path_parts[:-1]: # Up to the parent directory
        current_path_accumulated = str(Path(current_path_accumulated) / part)
        breadcrumbs.append({"name": part, "url": url_for('.view_repo_tree', owner_username=owner_username, repo_short_name=repo_short_name, ref_name=ref_name, object_path=current_path_accumulated)})
    if path_parts:
        breadcrumbs.append({"name": path_parts[-1], "url": ""}) # Current file, no link


    # Get user's preferred CodeMirror theme
    user_cm_theme = 'material-darker.css' # Default theme file name
    if current_user.is_authenticated and hasattr(current_user, 'preferred_codemirror_theme') and current_user.preferred_codemirror_theme:
        user_cm_theme = current_user.preferred_codemirror_theme

    can_commit_flag = user_can_write_to_repo(current_user, repo_db_obj) if current_user.is_authenticated else False
    current_user_starred_flag = current_user.has_starred_repo(repo_db_obj) if current_user.is_authenticated else False


    return render_template("git/repo_blob_view.html",
                           repo=repo_db_obj,
                           owner_username=owner_username,
                           repo_short_name=repo_short_name,
                           ref_name=ref_name,
                           file_path=file_path,
                           content=content,
                           breadcrumbs=breadcrumbs,
                           file_git_details=get_file_git_details(repo_disk_path, file_path, ref_name),
                           overall_repo_git_stats=get_repo_git_details(repo_disk_path),
                           current_user_starred=current_user_starred_flag,
                           is_true_owner=(current_user.is_authenticated and current_user.id == repo_db_obj.user_id),
                           can_commit=can_commit_flag,
                           codemirror_mode=get_codemirror_mode_from_filename(file_path),
                           user_codemirror_theme=user_cm_theme) # Pass the theme file name



@bp.route('/<owner_username>/<repo_short_name>/commit/<commit_id>')
@repo_auth_required_db
def view_commit_route(owner_username, repo_short_name, commit_id):
    repo_db_obj, repo_disk_path = g.repo, g.repo_disk_path
    try:
        pygit_repo = PyGitRepo(repo_disk_path)
        commit = pygit_repo.commit(commit_id)

        commit_details = {
            'hex': commit.hexsha,
            'short_id': commit.hexsha[:7],
            'author_name': commit.author.name,
            'author_email': commit.author.email,
            'authored_date': datetime.fromtimestamp(commit.authored_date, tz=timezone.utc),
            'committer_name': commit.committer.name,
            'committer_email': commit.committer.email,
            'committed_date': datetime.fromtimestamp(commit.committed_date, tz=timezone.utc),
            'message_summary': commit.summary,
            'message_full': commit.message,
            'parents': [{'hex': p.hexsha, 'short_id': p.hexsha[:7]} for p in commit.parents], # Store dict for easier template access
            'stats': commit.stats.total,  # {'files': N, 'insertions': N, 'deletions': N}
            'diffs': []
        }

        # --- Populate Diffs ---
        if commit.parents:
            # For simplicity, diff against the first parent.
            # For merge commits (multiple parents), you might want a more complex display
            # or allow choosing which parent to diff against.
            parent_commit = commit.parents[0]
            diff_index = parent_commit.diff(commit, create_patch=True)
            for diff_item in diff_index:
                commit_details['diffs'].append({
                    'change_type': diff_item.change_type,  # e.g., 'A' (added), 'D' (deleted), 'M' (modified), 'R' (renamed)
                    'a_path': diff_item.a_path,  # Old path
                    'b_path': diff_item.b_path,  # New path
                    # Decode diff text, replacing errors for robustness
                    'diff_text': diff_item.diff.decode('utf-8', errors='replace') if diff_item.diff else ""
                })
        else:
            # This is an initial commit (no parents)
            # Diff against an empty tree (NULL_TREE)
            diff_index = commit.diff(NULL_TREE, create_patch=True)
            for diff_item in diff_index:
                commit_details['diffs'].append({
                    'change_type': diff_item.change_type,
                    'a_path': diff_item.a_path, # Should be None for new files in an initial commit
                    'b_path': diff_item.b_path, # The path of the added file
                    'diff_text': diff_item.diff.decode('utf-8', errors='replace') if diff_item.diff else ""
                })
        # --- End Populate Diffs ---

        breadcrumbs = [
            {"name": repo_db_obj.name, "url": url_for('.view_repo_root', owner_username=owner_username, repo_short_name=repo_short_name)},
            # {"name": "Commits", "url": url_for('.view_repo_commits_list_route', owner_username=owner_username, repo_short_name=repo_short_name, ref_name=get_default_branch(repo_disk_path))}, # <-- Line REMOVED or COMMENTED OUT
            {"name": commit_details['short_id']} # Current page, no URL
        ]

        overall_repo_git_stats = get_repo_git_details(repo_disk_path) # Assuming this utility function exists

        return render_template(
            'git/repo_commit_view.html',
            repo=repo_db_obj,
            commit=commit_details,
            owner_username=owner_username, # Passed for consistency if needed by base templates
            repo_short_name=repo_short_name, # Passed for consistency
            breadcrumbs=breadcrumbs,
            overall_repo_git_stats=overall_repo_git_stats
        )

    except InvalidGitRepositoryError: # More specific exception
        current_app.logger.error(f"Invalid Git repository at {repo_disk_path} for commit view.")
        abort(404, "Repository not found or invalid.")
    except Exception as e_commit: # General exception for other errors (e.g., commit not found, diff errors)
        current_app.logger.error(f"Error viewing commit {commit_id} for {repo_short_name}: {e_commit}", exc_info=True)
        flash(f"Could not display commit '{commit_id}'. It might be invalid or an error occurred.", "danger")
        return redirect(url_for('.view_repo_root', owner_username=owner_username, repo_short_name=repo_short_name))


@bp.route('/<owner_username>/<repo_short_name>/settings', methods=['GET', 'POST'])
@login_required
@repo_auth_required_db
def repo_settings(owner_username, repo_short_name):
    repo_db_obj = g.repo
    if repo_db_obj.user_id != current_user.id: # Only owner can change settings
        flash("Only the repository owner can change settings.", "danger")
        return redirect(url_for('.view_repo_root', owner_username=owner_username, repo_short_name=repo_short_name))

    if request.method == 'POST':
        original_name = repo_db_obj.name
        new_name_for_redirect = original_name
        settings_updated = False

        # Visibility
        new_visibility_str = request.form.get('visibility')
        if new_visibility_str is not None:
            new_is_private = (new_visibility_str == 'private')
            if repo_db_obj.is_private != new_is_private:
                repo_db_obj.is_private = new_is_private; settings_updated = True

        # Description
        new_description = request.form.get('description', '').strip()
        if (repo_db_obj.description or "") != new_description: # Handle None from DB
            repo_db_obj.description = new_description if new_description else None; settings_updated = True

        # Name Change
        new_repo_name_form = request.form.get('repo_name', '').strip()
        if new_repo_name_form and new_repo_name_form != original_name:
            if not all(c.isalnum() or c in ['_', '-'] for c in new_repo_name_form) or len(new_repo_name_form) > 100:
                flash("Invalid new repository name.", "danger")
            elif GitRepository.query.filter(GitRepository.user_id == current_user.id, GitRepository.name == new_repo_name_form, GitRepository.id != repo_db_obj.id).first():
                flash(f"You already have a repository named '{new_repo_name_form}'.", "danger")
            else:
                old_disk_path = repo_db_obj.disk_path
                new_intended_disk_path = get_repo_disk_path(owner_username, new_repo_name_form)
                try:
                    if os.path.exists(old_disk_path) and not os.path.exists(new_intended_disk_path):
                        os.makedirs(os.path.dirname(new_intended_disk_path), exist_ok=True)
                        os.rename(old_disk_path, new_intended_disk_path)
                        repo_db_obj.name = new_repo_name_form
                        repo_db_obj.disk_path = new_intended_disk_path
                        new_name_for_redirect = new_repo_name_form; settings_updated = True
                    elif not os.path.exists(old_disk_path): flash("Original repository path not found.", "danger")
                    else: flash(f"Target path for '{new_repo_name_form}' already exists.", "danger")
                except OSError as e: flash(f"Error renaming directory: {e}", "danger")

        if settings_updated:
            try: db.session.commit(); flash("Settings updated!", "success"); return redirect(url_for('.repo_settings', owner_username=owner_username, repo_short_name=new_name_for_redirect))
            except Exception as e: db.session.rollback(); flash(f"Error saving settings: {e}", "danger")
        elif not request.form: flash("No changes submitted.", "info")

    return render_template("git/repo_settings.html", repo=repo_db_obj, owner_username=owner_username, repo_short_name=repo_db_obj.name)


# ... (Other Git routes like edit, save, createfile, uploadfiles, deleteitem, fork, star/unstar, collaborators) ...
# These will be very similar in structure, using @repo_auth_required_db and PyGitRepo/subprocess calls.
# Due to length, I'll stop here for this file and assume you can adapt the remaining Git routes.
# Remember to adjust url_for calls and template paths.

# --- Git HTTP Backend Routes (Should NOT have /git prefix from blueprint if clients expect root paths) ---
# These are typically registered without a blueprint prefix, or the blueprint is registered at root.
# For now, defined here. Careful registration needed in app/__init__.py if this blueprint is prefixed.


@bp.route('/<username>/<path:repo_name_from_url>/info/refs', methods=['GET'], endpoint='git_info_refs_custom')
@csrf.exempt
def git_info_refs(username, repo_name_from_url): # Using repo_name_from_url for clarity
    service = request.args.get('service')
    git_exe = current_app.config.get('GIT_EXECUTABLE_PATH')

    if not git_exe:
        current_app.logger.error("CRITICAL: GIT_EXECUTABLE_PATH is not configured.")
        abort(500, "Server configuration error: Git executable path missing.")
    if not service or not service.startswith('git-'):
        abort(400, "Invalid service parameter")

    # --- Flexible repository short name derivation ---
    if repo_name_from_url.endswith(".git"):
        repo_short_name = repo_name_from_url[:-4]
    else:
        repo_short_name = repo_name_from_url
    # --- End flexible name derivation ---

    user_owner_obj = User.query.filter_by(username=username).first()
    if not user_owner_obj:
        current_app.logger.info(f"Git info/refs (bp): Owner '{username}' not found.")
        abort(404, "Owner not found")

    repo_db_obj = GitRepository.query.filter_by(user_id=user_owner_obj.id, name=repo_short_name).first()
    if not repo_db_obj:
        current_app.logger.info(f"Git info/refs (bp): Repository '{repo_short_name}' by '{username}' not found.")
        abort(404, "Repository not found")

    repo_disk_path = repo_db_obj.disk_path
    if not repo_disk_path or not os.path.isdir(repo_disk_path):
        current_app.logger.error(f"Git info/refs (bp): Repository disk path invalid for repo ID {repo_db_obj.id}: '{repo_disk_path}'")
        abort(404, "Repository storage error.")

    # --- Authentication Logic (ensure this matches your User model methods) ---
    auth_required = repo_db_obj.is_private
    if auth_required:
        auth = request.authorization
        is_authed_and_permitted = False
        if auth and auth.username:
            authed_user = User.query.filter_by(username=auth.username).first()
            if authed_user and authed_user.check_password(auth.password): # check_password method
                if repo_db_obj.user_id == authed_user.id or repo_db_obj.is_collaborator(authed_user): # is_collaborator method
                    is_authed_and_permitted = True
        if not is_authed_and_permitted:
            resp = make_response('Authentication required', 401)
            resp.headers['WWW-Authenticate'] = 'Basic realm="Git Access"'
            return resp
    # --- End Authentication ---

    # Use the older Git command style (no --stateless-rpc for this part's stdout)
    cmd_service_name = service.replace('git-', '')
    cmd = [git_exe, cmd_service_name, '--advertise-refs', repo_disk_path]

    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        raw_refs_output, stderr_bytes = proc.communicate(timeout=30)

        if proc.returncode != 0:
            error_msg = stderr_bytes.decode(errors='ignore').strip()
            current_app.logger.error(f"Git command error (info/refs bp - old style) for '{repo_disk_path}': {error_msg}.")
            return make_response(f"Git command error: {error_msg}", 500, {'Content-Type': 'text/plain'})

        service_line_data = f"# service={service}\n".encode('utf-8')
        pkt1_hex_len = f"{len(service_line_data) + 4:04x}".encode('ascii')
        first_pkt_line_bytes = pkt1_hex_len + service_line_data
        flush_pkt_bytes = b"0000"
        res_content = first_pkt_line_bytes + flush_pkt_bytes + raw_refs_output

        current_app.logger.info(f"Git info/refs (bp - old style) response body prepared (first 100 bytes): {res_content[:100]!r}")

        response = make_response(res_content)
        response.headers['Content-Type'] = f'application/x-{service}-advertisement'
        response.headers['Content-Length'] = str(len(res_content))
        response.headers['Expires'] = 'Fri, 01 Jan 1980 00:00:00 GMT'; response.headers['Pragma'] = 'no-cache'
        response.headers['Cache-Control'] = 'no-cache, max-age=0, must-revalidate'
        return response
    except subprocess.TimeoutExpired:
        current_app.logger.error(f"Git command timed out (info/refs bp) for '{repo_disk_path}'.")
        abort(500, "Git command timed out on server.")
    except FileNotFoundError:
        current_app.logger.error(f"GIT_EXECUTABLE_PATH '{git_exe}' not found (info/refs bp).")
        abort(500, "Server configuration error: Git executable not found.")
    except Exception as e:
        current_app.logger.error(f"Unexpected exception in git_info_refs (bp) for '{repo_disk_path}': {e}", exc_info=True)
        abort(500, f"Server error processing git info/refs request: {str(e)}")




@bp.route('/<username>/<path:repo_name_from_url>/<any("git-upload-pack", "git-receive-pack"):service_rpc>', methods=['POST'], endpoint='git_service_rpc_custom')
@csrf.exempt
def git_service_rpc(username, repo_name_from_url, service_rpc): # Using repo_name_from_url
    git_exe = current_app.config.get('GIT_EXECUTABLE_PATH')

    if not git_exe:
        current_app.logger.error("CRITICAL: GIT_EXECUTABLE_PATH is not configured.")
        abort(500, "Server configuration error: Git executable path missing.")

    content_type_header = request.headers.get('Content-Type', '') # Renamed for clarity
    expected_content_type = f'application/x-{service_rpc}-request'
    if content_type_header != expected_content_type:
        abort(400, f"Invalid Content-Type: {content_type_header}, expected {expected_content_type}")

    # --- Flexible repository short name derivation ---
    if repo_name_from_url.endswith(".git"):
        repo_short_name = repo_name_from_url[:-4]
    else:
        repo_short_name = repo_name_from_url
    # --- End flexible name derivation ---

    user_owner_obj = User.query.filter_by(username=username).first()
    if not user_owner_obj:
        current_app.logger.info(f"Git RPC (bp): Owner '{username}' not found.")
        abort(404, "Owner not found")

    repo_db_obj = GitRepository.query.filter_by(user_id=user_owner_obj.id, name=repo_short_name).first()
    if not repo_db_obj:
        current_app.logger.info(f"Git RPC (bp): Repository '{repo_short_name}' by '{username}' not found.")
        abort(404, "Repository not found")

    repo_disk_path = repo_db_obj.disk_path
    if not repo_disk_path or not os.path.isdir(repo_disk_path):
        current_app.logger.error(f"Git RPC (bp): Repository disk path invalid for repo ID {repo_db_obj.id}: '{repo_disk_path}'")
        abort(404, "Repository storage error.")

    # --- Authentication Logic (ensure this matches your User model methods) ---
    is_push_operation = (service_rpc == 'git-receive-pack')
    auth_required = repo_db_obj.is_private or is_push_operation
    authed_user_for_permissions = None # To store the User object after successful auth

    if auth_required:
        auth = request.authorization
        is_authed_and_permitted = False
        if auth and auth.username:
            authed_user = User.query.filter_by(username=auth.username).first()
            if authed_user and authed_user.check_password(auth.password):
                authed_user_for_permissions = authed_user # Store the authenticated user object
                if repo_db_obj.user_id == authed_user.id or repo_db_obj.is_collaborator(authed_user):
                    is_authed_and_permitted = True # Basic permission to access/check private or attempt push

        if not is_authed_and_permitted:
            current_app.logger.warning(f"Git RPC (bp): Auth failed/insufficient base permissions for {service_rpc} on repo {username}/{repo_short_name}.")
            resp = make_response('Authentication required', 401)
            resp.headers['WWW-Authenticate'] = 'Basic realm="Git Access"'
            return resp

        # Specific check for push: Must be owner or collaborator (assuming collaborators have write)
        if is_push_operation and not (repo_db_obj.user_id == authed_user_for_permissions.id or repo_db_obj.is_collaborator(authed_user_for_permissions)):
            current_app.logger.warning(f"Git RPC (bp): Push access denied for user {authed_user_for_permissions.username} on repo {username}/{repo_short_name}.")
            abort(403, "Push access denied. Not an owner or collaborator.")
    # --- End Authentication ---

    pack_data = request.get_data()
    cmd_service_name = service_rpc.replace('git-', '')
    # For RPC services (POST), --stateless-rpc is standard.
    cmd = [git_exe, cmd_service_name, '--stateless-rpc', repo_disk_path]

    try:
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        stdout_bytes, stderr_bytes = proc.communicate(input=pack_data, timeout=300) # Longer timeout for potentially large data

        if proc.returncode != 0:
            error_message = stderr_bytes.decode(errors='ignore').strip()
            current_app.logger.error(f"Git command error (RPC {service_rpc} bp) for '{repo_disk_path}': {error_message}.")
            return make_response(f"Git command error: {error_message}", 500, {'Content-Type': 'text/plain'})

        response = make_response(stdout_bytes)
        response.headers['Content-Type'] = f'application/x-{service_rpc}-result'
        response.headers['Content-Length'] = str(len(stdout_bytes))
        response.headers['Cache-Control'] = 'no-cache, max-age=0, must-revalidate'
        return response
    except subprocess.TimeoutExpired:
        current_app.logger.error(f"Git command timed out (RPC {service_rpc} bp) for '{repo_disk_path}'.")
        abort(500, "Git command timed out on server.")
    except FileNotFoundError:
        current_app.logger.error(f"GIT_EXECUTABLE_PATH '{git_exe}' not found (RPC {service_rpc} bp).")
        abort(500, "Server configuration error: Git executable not found.")
    except Exception as e:
        current_app.logger.error(f"Unexpected exception in git_service_rpc (bp) for '{repo_disk_path}', service {service_rpc}: {e}", exc_info=True)
        abort(500, f"Server error processing git {service_rpc} request: {str(e)}")


# --- Other Git Actions (Starring, Collaborators - simplified for this example) ---
@bp.route('/repo/<int:repo_id>/star', methods=['POST'])
@login_required
def star_repo_route(repo_id):
    repo = GitRepository.query.get_or_404(repo_id)
    if current_user.has_starred_repo(repo): return jsonify({'status': 'error', 'message': 'Already starred.'}), 400
    current_user.star_repo(repo); db.session.commit()
    return jsonify({'status': 'success', 'message': 'Starred!', 'star_count': repo.star_count, 'starred': True})

@bp.route('/repo/<int:repo_id>/unstar', methods=['POST'])
@login_required
def unstar_repo_route(repo_id):
    repo = GitRepository.query.get_or_404(repo_id)
    if not current_user.has_starred_repo(repo): return jsonify({'status': 'error', 'message': 'Not starred.'}), 400
    current_user.unstar_repo(repo); db.session.commit()
    return jsonify({'status': 'success', 'message': 'Unstarred!', 'star_count': repo.star_count, 'starred': False})

@bp.route('/starred') # /git/starred
@login_required
def starred_repositories_page():
    starred_data = db.session.query(GitRepository, repo_stars.c.starred_at)\
        .join(repo_stars, repo_stars.c.git_repository_id == GitRepository.id)\
        .filter(repo_stars.c.user_id == current_user.id)\
        .order_by(repo_stars.c.starred_at.desc()).all()
    repos_for_template = [{'repo': r, 'starred_at': sa, 'git_details': get_repo_git_details(r.disk_path), 'language_stats': calculate_repo_language_stats(r.disk_path, get_default_branch(r.disk_path))} for r, sa in starred_data]
    return render_template('git/starred_repos.html', title="Starred Repositories", repos_data=repos_for_template)


@bp.route('/<owner_username>/<repo_short_name>/settings/collaborators/add', methods=['POST'])
@login_required
@repo_auth_required_db
def add_collaborator_route(owner_username, repo_short_name):
    repo_db_obj = g.repo
    if repo_db_obj.user_id != current_user.id:
        flash("Only owner can add collaborators.", "danger")
        return redirect(url_for('.repo_settings', owner_username=owner_username, repo_short_name=repo_short_name))
    username_to_add = request.form.get('username_to_add', '').strip()
    user_to_add = User.query.filter_by(username=username_to_add).first()
    if not user_to_add: flash(f"User '{username_to_add}' not found.", "danger")
    elif user_to_add.id == current_user.id: flash("Cannot add yourself.", "warning")
    elif repo_db_obj.is_collaborator(user_to_add): flash(f"'{username_to_add}' is already a collaborator.", "info")
    else:
        try:
            repo_db_obj.add_collaborator(user_to_add); db.session.commit()
            flash(f"'{username_to_add}' added as collaborator.", "success")
            create_notification(recipient_user=user_to_add, sender_user=current_user, type='repo_collaborator_added', repo=repo_db_obj)
        except Exception as e: db.session.rollback(); flash(f"Error adding collaborator: {e}", "danger")
    return redirect(url_for('.repo_settings', owner_username=owner_username, repo_short_name=repo_short_name) + "#collaborators-section")


@bp.route('/<owner_username>/<repo_short_name>/settings/collaborators/remove/<int:collaborator_user_id>', methods=['POST'])
@login_required
@repo_auth_required_db
def remove_collaborator_route(owner_username, repo_short_name, collaborator_user_id):
    repo_db_obj = g.repo
    if repo_db_obj.user_id != current_user.id:
        flash("Only owner can remove collaborators.", "danger")
        return redirect(url_for('.repo_settings', owner_username=owner_username, repo_short_name=repo_short_name))
    user_to_remove = User.query.get(collaborator_user_id)
    if not user_to_remove: flash("Collaborator not found.", "danger")
    elif not repo_db_obj.is_collaborator(user_to_remove): flash(f"'{user_to_remove.username}' is not a collaborator.", "info")
    else:
        try:
            repo_db_obj.remove_collaborator(user_to_remove); db.session.commit()
            flash(f"'{user_to_remove.username}' removed as collaborator.", "success")
            create_notification(recipient_user=user_to_remove, sender_user=current_user, type='repo_collaborator_removed', repo=repo_db_obj)
        except Exception as e: db.session.rollback(); flash(f"Error removing collaborator: {e}", "danger")
    return redirect(url_for('.repo_settings', owner_username=owner_username, repo_short_name=repo_short_name) + "#collaborators-section")


@bp.route('/<owner_username>/<repo_short_name>/createfile/<ref_name>/', defaults={'dir_path': ''}, methods=["GET", "POST"])
@bp.route('/<owner_username>/<repo_short_name>/createfile/<ref_name>/<path:dir_path>', methods=["GET", "POST"])
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
                redirect_url = url_for('.view_repo_tree', owner_username=owner_username, repo_short_name=repo_short_name, ref_name=ref_name, object_path=redirect_target_path_str)

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
    current_breadcrumbs = [{"name": repo_short_name, "url": url_for('git.view_repo_tree', owner_username=owner_username, repo_short_name=repo_short_name, ref_name=ref_name, object_path='')}]
    current_breadcrumb_path_builder = ""
    for part in path_parts_for_breadcrumbs:
        current_breadcrumb_path_builder = str(Path(current_breadcrumb_path_builder) / part)
        current_breadcrumbs.append({"name": part, "url": url_for('git.view_repo_tree', owner_username=owner_username, repo_short_name=repo_short_name, ref_name=ref_name, object_path=current_breadcrumb_path_builder)})
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
@bp.route('/<owner_username>/<repo_short_name>/deleteitem/<ref_name>/<path:item_full_path>', methods=['POST'])
@login_required
@repo_auth_required_db # g.repo and g.repo_disk_path should be set by this
def delete_repo_item(owner_username, repo_short_name, ref_name, item_full_path):
    if not user_can_write_to_repo(current_user, g.repo):
        flash("You do not have permission to delete items in this repository.", "danger")
        parent_dir_path = str(Path(item_full_path).parent)
        if parent_dir_path == '.': parent_dir_path = ''
        return redirect(url_for('.view_repo_tree', owner_username=owner_username, repo_short_name=repo_short_name, ref_name=ref_name, object_path=parent_dir_path))

    commit_message = request.form.get("commit_message")
    if not commit_message or not commit_message.strip():
        flash("Commit message is required for deletion.", "danger")
        parent_dir_path = str(Path(item_full_path).parent)
        if parent_dir_path == '.': parent_dir_path = ''
        return redirect(url_for('.view_repo_tree', owner_username=owner_username, repo_short_name=repo_short_name, ref_name=ref_name, object_path=parent_dir_path))

    repo_disk_path = g.repo.disk_path
    GIT_PATH = current_app.config.get('GIT_EXECUTABLE_PATH', "git") # Define GIT_PATH

    committer_name = current_user.username
    committer_email = current_user.email if hasattr(current_user, 'email') and current_user.email else f"{current_user.username}@example.com"
    author_string = f"{committer_name} <{committer_email}>"

    parent_path_obj = Path(item_full_path).parent
    redirect_object_path = str(parent_path_obj) if str(parent_path_obj) != '.' else ''

    with tempfile.TemporaryDirectory() as temp_clone_dir:
        try:
            # Check if the target branch/ref exists.
            try:
                subprocess.run([GIT_PATH, "--git-dir=" + repo_disk_path, "rev-parse", "--verify", ref_name + "^{commit}"], check=True, capture_output=True, text=True)
            except subprocess.CalledProcessError:
                flash(f"Branch or reference '{ref_name}' not found in repository.", "danger")
                return redirect(url_for('.view_repo_tree', owner_username=owner_username, repo_short_name=repo_short_name, ref_name=ref_name, object_path=redirect_object_path))

            subprocess.run([GIT_PATH, "clone", "--branch", ref_name, repo_disk_path, temp_clone_dir], check=True, capture_output=True)
            subprocess.run([GIT_PATH, "-C", temp_clone_dir, "config", "user.name", f'"{committer_name}"'], check=True, capture_output=True)
            subprocess.run([GIT_PATH, "-C", temp_clone_dir, "config", "user.email", f'"{committer_email}"'], check=True, capture_output=True)

            path_in_clone = Path(temp_clone_dir) / item_full_path
            if not path_in_clone.exists():
                flash(f"Item '{item_full_path}' not found in the repository branch '{ref_name}'.", "warning")
                return redirect(url_for('.view_repo_tree', owner_username=owner_username, repo_short_name=repo_short_name, ref_name=ref_name, object_path=redirect_object_path))

            rm_command = [GIT_PATH, "-C", temp_clone_dir, "rm", "-r", item_full_path]
            current_app.logger.info(f"Executing delete command: {' '.join(rm_command)}")
            rm_result = subprocess.run(rm_command, capture_output=True, text=True, errors='replace')

            if rm_result.returncode != 0:
                flash(f"Error removing item '{item_full_path}' using Git: {rm_result.stderr or rm_result.stdout}", "danger")
                current_app.logger.error(f"git rm failed for '{item_full_path}'. Stderr: {rm_result.stderr}, Stdout: {rm_result.stdout}")
                return redirect(url_for('.view_repo_tree', owner_username=owner_username, repo_short_name=repo_short_name, ref_name=ref_name, object_path=redirect_object_path))

            status_result = subprocess.run([GIT_PATH, "-C", temp_clone_dir, "status", "--porcelain"], capture_output=True, text=True)
            if not status_result.stdout.strip(): # If nothing was staged for commit
                flash(f"No changes to commit after attempting to delete '{item_full_path}'. It might not have been tracked or an issue occurred.", "info")
                return redirect(url_for('.view_repo_tree', owner_username=owner_username, repo_short_name=repo_short_name, ref_name=ref_name, object_path=redirect_object_path))

            commit_command = [GIT_PATH, "-C", temp_clone_dir, "commit", "-m", commit_message, f"--author={author_string}"]
            current_app.logger.info(f"Executing commit command: {' '.join(commit_command)}")
            subprocess.run(commit_command, check=True, capture_output=True)

            push_command = [GIT_PATH, "-C", temp_clone_dir, "push", "origin", ref_name]
            current_app.logger.info(f"Executing push command: {' '.join(push_command)}")
            subprocess.run(push_command, check=True, capture_output=True)

            flash(f"Successfully deleted '{item_full_path}' from branch '{ref_name}'.", "success")
            return redirect(url_for('.view_repo_tree', owner_username=owner_username, repo_short_name=repo_short_name, ref_name=ref_name, object_path=redirect_object_path))

        except subprocess.CalledProcessError as e:
            error_msg = e.stderr.decode(errors='replace') if e.stderr else (e.stdout.decode(errors='replace') if e.stdout else str(e))
            current_app.logger.error(f"Git operation failed during delete of '{item_full_path}': {error_msg} (Command: {e.cmd})")
            flash(f"Error deleting item: {error_msg}", "danger")
        except Exception as e_generic:
            current_app.logger.error(f"Unexpected error in delete_repo_item for '{item_full_path}': {str(e_generic)}", exc_info=True)
            flash(f"An unexpected error occurred: {str(e_generic)}", "danger")

    # Fallback redirect
    return redirect(url_for('.view_repo_tree', owner_username=owner_username, repo_short_name=repo_short_name, ref_name=ref_name, object_path=redirect_object_path))

@bp.route('/<owner_username>/<repo_short_name>/uploadfiles/<ref_name>/', defaults={'dir_path': ''}, methods=["GET", "POST"])
@bp.route('/<owner_username>/<repo_short_name>/uploadfiles/<ref_name>/<path:dir_path>', methods=["GET", "POST"])
@login_required
@repo_auth_required_db
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
    current_breadcrumbs = [{"name": repo_short_name, "url": url_for('git.view_repo_tree', owner_username=owner_username, repo_short_name=repo_short_name, ref_name=ref_name, object_path='')}]
    current_breadcrumb_path_builder = ""
    for part in path_parts_for_breadcrumbs:
        current_breadcrumb_path_builder = str(Path(current_breadcrumb_path_builder) / part)
        current_breadcrumbs.append({"name": part, "url": url_for('git.view_repo_tree', owner_username=owner_username, repo_short_name=repo_short_name, ref_name=ref_name, object_path=current_breadcrumb_path_builder)})
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
            current_app.logger.error(f"Upload mismatch: {len(uploaded_file_storage_objects)} files, {len(uploaded_files_relative_paths)} paths.")
            return render_template("git/repo_upload_files.html", owner_username=owner_username, repo_short_name=repo_short_name, ref_name=ref_name, dir_path=dir_path, breadcrumbs=current_breadcrumbs, commit_message=custom_commit_message)

        processed_commit_msg_filenames = []
        files_to_add_to_git = [] # Store paths relative to repo root for `git add`

        with tempfile.TemporaryDirectory() as temp_clone_dir:
            try:
                GIT_PATH = current_app.config['GIT_EXECUTABLE_PATH'] # Add this line
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
                            current_app.logger.warning(f"Missing relative path for uploaded file: {file_storage_obj.filename}")
                            continue # Skip this file or handle error

                        # Sanitize each path component of the client-provided relative path
                        path_components = Path(client_relative_path_str).parts
                        sanitized_components = [secure_path_component(part) for part in path_components if part] # Filter empty parts from Path()

                        if not sanitized_components: # e.g. if client_relative_path_str was ".." or similar
                            current_app.logger.warning(f"Invalid relative path after sanitization: {client_relative_path_str}")
                            continue

                        sanitized_relative_path = Path(*sanitized_components)

                        # Final path within the repository structure
                        target_repo_path = Path(dir_path) / sanitized_relative_path

                        # Full disk path in the temporary clone
                        target_disk_path_in_clone = (Path(temp_clone_dir) / target_repo_path).resolve()


                        # Security check: Ensure the resolved path is still within the temp_clone_dir
                        if not str(target_disk_path_in_clone).startswith(str(Path(temp_clone_dir).resolve())):
                            current_app.logger.error(f"Path traversal attempt detected or path resolution error. Skipping file: {client_relative_path_str}")
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
                    return redirect(url_for('.view_repo_tree', owner_username=owner_username, repo_short_name=repo_short_name, ref_name=ref_name, object_path=dir_path))

                subprocess.run([GIT_PATH, "-C", temp_clone_dir, "commit", "-m", commit_message_to_use, f"--author={author_string}"], check=True, capture_output=True)

                if is_empty_or_new_branch:
                    subprocess.run([GIT_PATH, "-C", temp_clone_dir, "push", "-u", "origin", f"HEAD:{ref_name}"], check=True, capture_output=True)
                else:
                    subprocess.run([GIT_PATH, "-C", temp_clone_dir, "push", "origin", ref_name], check=True, capture_output=True)

                flash(f"{len(files_to_add_to_git)} file(s) uploaded successfully to branch '{ref_name}'.", "success")
                return redirect(url_for('.view_repo_tree', owner_username=owner_username, repo_short_name=repo_short_name, ref_name=ref_name, object_path=dir_path))

            except subprocess.CalledProcessError as e:
                error_msg = e.stderr.decode(errors='ignore') or e.stdout.decode(errors='ignore') or str(e)
                current_app.logger.error(f"Git operation failed during upload: {error_msg} (Command: {e.cmd})")
                flash(f"Error uploading files: {error_msg}", "danger")
            except Exception as e:
                current_app.logger.error(f"Unexpected error in upload_repo_files: {str(e)}")
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

@bp.route('/<owner_username>/<repo_short_name>/fork', methods=['POST'])
@login_required
@repo_auth_required_db
def fork_repo(owner_username, repo_short_name):
    source_repo_obj = g.repo # The GitRepository SQLAlchemy object of the source
    fork_owner = current_user # The user performing the fork

    if source_repo_obj.is_private and source_repo_obj.user_id != fork_owner.id:
        flash("You can only fork public repositories or your own private repositories.", "danger")
        # Corrected url_for
        return redirect(url_for('.view_repo_root', owner_username=owner_username, repo_short_name=repo_short_name))

    fork_repo_name = source_repo_obj.name # Fork usually keeps the same name

    existing_fork = GitRepository.query.filter_by(user_id=fork_owner.id, name=fork_repo_name).first()
    if existing_fork:
        flash(f"You already have a repository named '{fork_repo_name}'.", "danger")
        # Corrected url_for
        return redirect(url_for('.view_repo_root', owner_username=fork_owner.username, repo_short_name=fork_repo_name)) # Redirect to their existing repo

    new_fork_disk_path = get_repo_disk_path(fork_owner.username, fork_repo_name)

    if os.path.exists(new_fork_disk_path):
        flash(f"A directory for the forked repository '{fork_repo_name}' already exists on your server space. Please resolve this conflict.", "danger")
        # Corrected url_for
        return redirect(url_for('.view_repo_root', owner_username=owner_username, repo_short_name=repo_short_name))

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
        # Corrected url_for
        return redirect(url_for('.view_repo_root', owner_username=fork_owner.username, repo_short_name=fork_repo_name))

    except subprocess.CalledProcessError as e:
        error_msg = e.stderr.decode(errors='ignore') or str(e)
        current_app.logger.error(f"Git clone error during fork: {error_msg} (Command: {e.cmd})")
        flash(f"Error forking repository: {error_msg}", "danger")
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Unexpected error during fork: {str(e)}", exc_info=True)
        flash(f"An unexpected error occurred while forking: {str(e)}", "danger")
        if os.path.exists(new_fork_disk_path) and not GitRepository.query.filter_by(disk_path=new_fork_disk_path).first():
            shutil.rmtree(new_fork_disk_path, ignore_errors=True)

    # This one was already correct in your provided snippet
    return redirect(url_for('.view_repo_root', owner_username=owner_username, repo_short_name=repo_short_name))

@bp.route('/<owner_username>/<repo_short_name>/raw/<ref_name>/<path:file_path>') # Changed app.route to bp.route
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

@bp.route('/<owner_username>/<repo_short_name>/edit/<ref_name>/<path:file_path>', methods=['GET'])
@login_required
@repo_auth_required_db
def repo_edit_view_route(owner_username, repo_short_name, ref_name, file_path): # Renamed in original
    repo_db_obj, repo_disk_path = g.repo, g.repo_disk_path
    if not user_can_write_to_repo(current_user, repo_db_obj):
        flash("Permission denied to edit.", "danger")
        return redirect(url_for('.view_repo_blob', owner_username=owner_username, repo_short_name=repo_short_name, ref_name=ref_name, file_path=file_path))

    GIT_PATH = current_app.config['GIT_EXECUTABLE_PATH']
    try:
        result = subprocess.run([GIT_PATH, "--git-dir=" + repo_disk_path, "show", f"{ref_name}:{file_path}"], capture_output=True, text=True, check=True, errors='ignore')
        content = result.stdout
    except Exception as e_show:
        flash(f"Could not retrieve file for editing: {e_show}", "danger")
        return redirect(url_for('.view_repo_blob', owner_username=owner_username, repo_short_name=repo_short_name, ref_name=ref_name, file_path=file_path))

    form = RepoEditFileForm(file_content=content) # From app.forms

    # Breadcrumbs logic (ensure it's comprehensive if needed)
    path_parts = list(Path(file_path).parts)
    breadcrumbs = [
        {"name": repo_short_name, "url": url_for('.view_repo_root', owner_username=owner_username, repo_short_name=repo_short_name)},
        {"name": ref_name, "url": url_for('.view_repo_tree', owner_username=owner_username, repo_short_name=repo_short_name, ref_name=ref_name, object_path='')}
    ]
    current_path_accumulated = ""
    # Iterate up to the parent of the file for tree links
    for part in path_parts[:-1]:
        current_path_accumulated = str(Path(current_path_accumulated) / part)
        breadcrumbs.append({"name": part, "url": url_for('.view_repo_tree', owner_username=owner_username, repo_short_name=repo_short_name, ref_name=ref_name, object_path=current_path_accumulated)})
    # Add the current file being edited (not a link)
    if path_parts:
        breadcrumbs.append({"name": path_parts[-1], "url": ""})


    # Get user's preferred CodeMirror theme
    user_cm_theme = current_user.preferred_codemirror_theme if hasattr(current_user, 'preferred_codemirror_theme') and current_user.preferred_codemirror_theme else 'material.css'

    return render_template('git/repo_edit_view.html',
                           repo=repo_db_obj,
                           owner_username=owner_username,
                           repo_short_name=repo_short_name,
                           ref_name=ref_name,
                           file_path=file_path,
                           form=form,
                           breadcrumbs=breadcrumbs,
                           codemirror_mode=get_codemirror_mode_from_filename(file_path), # Util
                           can_commit=user_can_write_to_repo(current_user, repo_db_obj),
                           user_codemirror_theme=user_cm_theme) # Pass the theme

@bp.route('/<owner_username>/<repo_short_name>/savefile/<ref_name>/<path:original_file_path>', methods=['POST'])
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
        return redirect(url_for('.view_repo_blob', owner_username=owner_username, repo_short_name=repo_short_name, ref_name=ref_name, file_path=original_file_path))


    if not request.is_json:
        flash("Invalid request format. Expected JSON.", "danger")
        return redirect(url_for('.repo_edit_view_route', owner_username=owner_username, repo_short_name=repo_short_name, ref_name=ref_name, file_path=original_file_path))

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

                redirect_url = url_for('.view_repo_blob', owner_username=owner_username, repo_short_name=repo_short_name, ref_name=ref_name, file_path=final_redirect_path)
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
