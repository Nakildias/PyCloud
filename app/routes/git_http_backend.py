# app/routes/git_http_backend.py
import os
import subprocess
from flask import Blueprint, request, current_app, abort, make_response
from app.models import User, GitRepository # Assuming your models
# Import any other necessary utilities or csrf if needed for this blueprint
from app import csrf # If you are using CSRF protection from app init

git_http_bp = Blueprint('git_http_backend', __name__) # No url_prefix

# Helper to derive short name (can be shared or duplicated)
def _derive_repo_short_name(repo_path_segment):
    if repo_path_segment.endswith(".git"):
        return repo_path_segment[:-4]
    return repo_path_segment

@git_http_bp.route('/<username>/<path:repo_name_from_url>/info/refs', methods=['GET'])
@csrf.exempt # Apply csrf exemption as needed
def git_info_refs_root(username, repo_name_from_url):
    service = request.args.get('service')
    git_exe = current_app.config.get('GIT_EXECUTABLE_PATH')

    if not git_exe:
        current_app.logger.error("CRITICAL: GIT_EXECUTABLE_PATH is not configured.")
        abort(500, "Server configuration error: Git executable path missing.")
    if not service or not service.startswith('git-'):
        abort(400, "Invalid service parameter")

    repo_short_name = _derive_repo_short_name(repo_name_from_url)

    user_owner_obj = User.query.filter_by(username=username).first()
    if not user_owner_obj:
        abort(404, "Owner not found")
    repo_db_obj = GitRepository.query.filter_by(user_id=user_owner_obj.id, name=repo_short_name).first()
    if not repo_db_obj:
        abort(404, "Repository not found")

    repo_disk_path = repo_db_obj.disk_path
    if not repo_disk_path or not os.path.isdir(repo_disk_path):
        abort(404, "Repository storage not configured or found on server")

    # --- Authentication Logic (Copied and adapted from your working version) ---
    auth_required = repo_db_obj.is_private
    if auth_required:
        auth = request.authorization
        is_authed_and_permitted = False
        if auth and auth.username:
            authed_user = User.query.filter_by(username=auth.username).first()
            if authed_user and authed_user.check_password(auth.password):
                if repo_db_obj.user_id == authed_user.id or repo_db_obj.is_collaborator(authed_user):
                    is_authed_and_permitted = True
        if not is_authed_and_permitted:
            resp = make_response('Authentication required', 401)
            resp.headers['WWW-Authenticate'] = 'Basic realm="Git Access"'
            return resp
    # --- End Authentication ---

    cmd_service_name = service.replace('git-', '')
    cmd = [git_exe, cmd_service_name, '--advertise-refs', repo_disk_path] # Old style

    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        raw_refs_output, stderr_bytes = proc.communicate(timeout=30)

        if proc.returncode != 0:
            error_message = stderr_bytes.decode(errors='ignore').strip()
            current_app.logger.error(f"Git command error (info/refs root - old style) for '{repo_disk_path}': {error_message}.")
            return make_response(f"Git command error: {error_message}", 500, {'Content-Type': 'text/plain'})

        service_line_data = f"# service={service}\n".encode('utf-8')
        pkt1_hex_len = f"{len(service_line_data) + 4:04x}".encode('ascii')
        first_pkt_line_bytes = pkt1_hex_len + service_line_data
        flush_pkt_bytes = b"0000"
        res_content = first_pkt_line_bytes + flush_pkt_bytes + raw_refs_output

        current_app.logger.info(f"Git info/refs (root - old style) response prepared (first 100 bytes): {res_content[:100]!r}")

        response = make_response(res_content)
        response.headers['Content-Type'] = f'application/x-{service}-advertisement'
        response.headers['Content-Length'] = str(len(res_content))
        response.headers['Expires'] = 'Fri, 01 Jan 1980 00:00:00 GMT'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Cache-Control'] = 'no-cache, max-age=0, must-revalidate'
        return response
    except subprocess.TimeoutExpired:
        abort(500, "Git command timed out on server.")
    except FileNotFoundError:
        abort(500, "Server configuration error: Git executable not found.")
    except Exception as e:
        abort(500, f"Server error processing git info/refs request: {str(e)}")

@git_http_bp.route('/<username>/<path:repo_name_from_url>/<any("git-upload-pack", "git-receive-pack"):service_rpc>', methods=['POST'])
@csrf.exempt # Apply csrf exemption as needed
def git_service_rpc_root(username, repo_name_from_url, service_rpc):
    git_exe = current_app.config.get('GIT_EXECUTABLE_PATH')
    # ... (Similar logic adaptation as git_info_refs_root for path parsing, auth, subprocess) ...
    # IMPORTANT: For the actual RPC (POST request), you SHOULD use --stateless-rpc in the command
    # as this part of the protocol expects it, and your older main.py (line 1970) also used it.

    if not git_exe:
        abort(500, "Server configuration error: Git executable path missing.")

    content_type = request.headers.get('Content-Type', '')
    if content_type != f'application/x-{service_rpc}-request':
        abort(400, f"Invalid Content-Type: {content_type}")

    repo_short_name = _derive_repo_short_name(repo_name_from_url)

    user_owner_obj = User.query.filter_by(username=username).first()
    if not user_owner_obj: abort(404, "Owner not found")
    repo_db_obj = GitRepository.query.filter_by(user_id=user_owner_obj.id, name=repo_short_name).first()
    if not repo_db_obj: abort(404, "Repository not found")

    repo_disk_path = repo_db_obj.disk_path
    if not repo_disk_path or not os.path.isdir(repo_disk_path):
        abort(404, "Repository storage not configured or found on server")

    # --- Authentication Logic (Copied and adapted) ---
    is_push = (service_rpc == 'git-receive-pack')
    auth_required = repo_db_obj.is_private or is_push
    if auth_required:
        auth = request.authorization
        is_authed_and_permitted = False
        authed_user_for_perms = None
        if auth and auth.username:
            authed_user = User.query.filter_by(username=auth.username).first()
            if authed_user and authed_user.check_password(auth.password):
                authed_user_for_perms = authed_user # Store for permission check
                if repo_db_obj.user_id == authed_user.id or repo_db_obj.is_collaborator(authed_user):
                    # For push, further check if collaborator has write access (if you implement granular perms)
                    if is_push and not (repo_db_obj.user_id == authed_user.id or repo_db_obj.is_collaborator(authed_user)): # Simple check: owner or collaborator can push
                         pass # Will be denied below if not owner/collaborator with push rights
                    else:
                        is_authed_and_permitted = True

        if not is_authed_and_permitted:
            current_app.logger.warning(f"Git RPC root: Auth failed/insufficient permissions for {service_rpc} on repo {username}/{repo_short_name}.")
            resp = make_response('Authentication required', 401)
            resp.headers['WWW-Authenticate'] = 'Basic realm="Git Access"'
            return resp

        # Specific check for push access
        if is_push and not (repo_db_obj.user_id == authed_user_for_perms.id or repo_db_obj.is_collaborator(authed_user_for_perms)):
             current_app.logger.warning(f"Git RPC root: Push access denied for user {authed_user_for_perms.username} on repo {username}/{repo_short_name}.")
             abort(403, "Push access denied.")
    # --- End Authentication ---

    pack_data = request.get_data()
    cmd_service_name = service_rpc.replace('git-', '')
    # For RPC services (POST), --stateless-rpc is standard and was in your old main.py too
    cmd = [git_exe, cmd_service_name, '--stateless-rpc', repo_disk_path]

    try:
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        stdout_bytes, stderr_bytes = proc.communicate(input=pack_data, timeout=300) # Longer timeout for push/fetch

        if proc.returncode != 0:
            error_message = stderr_bytes.decode(errors='ignore').strip()
            current_app.logger.error(f"Git command error (RPC {service_rpc} root) for '{repo_disk_path}': {error_message}.")
            return make_response(f"Git command error: {error_message}", 500, {'Content-Type': 'text/plain'})

        response = make_response(stdout_bytes)
        response.headers['Content-Type'] = f'application/x-{service_rpc}-result'
        response.headers['Cache-Control'] = 'no-cache, max-age=0, must-revalidate'
        return response
    except subprocess.TimeoutExpired:
        abort(500, "Git command timed out on server.")
    except FileNotFoundError:
        abort(500, "Server configuration error: Git executable not found.")
    except Exception as e:
        abort(500, f"Server error processing git {service_rpc} request: {str(e)}")
