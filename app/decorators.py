# app/decorators.py
from functools import wraps
from flask import g, request, abort, flash, redirect, url_for
from flask_login import current_user

from .utils import get_repo_details_db
from .models import User, GitRepository


def repo_auth_required_db(f):
    @wraps(f)
    def decorated_function(owner_username, repo_short_name, *args, **kwargs):
        # Use the utility function to get repo details from DB
        repo_db_obj = get_repo_details_db(owner_username, repo_short_name)

        if not repo_db_obj:
            abort(404, "Repository not found.")

        g.repo = repo_db_obj
        g.repo_disk_path = repo_db_obj.disk_path

        if repo_db_obj.is_private:
            if not current_user.is_authenticated:

                if request.endpoint not in ['git.git_info_refs', 'git.git_service_rpc']: # Assuming blueprint names
                    flash("You must be logged in to view this private repository.", "warning")
                    return redirect(url_for('auth.login', next=request.url))
            else:
                # Authenticated, now check if owner or collaborator
                is_owner = (current_user.id == repo_db_obj.user_id)
                # Ensure is_collaborator method exists and works correctly
                is_collaborator = repo_db_obj.is_collaborator(current_user)

                if not (is_owner or is_collaborator):
                    # For Git HTTP backend access to private repos
                    if request.endpoint in ['git.git_info_refs', 'git.git_service_rpc']:

                        service = request.args.get('service') # For info/refs
                        service_rpc_from_url = kwargs.get('service_rpc') # For service_rpc route

                        abort(403, "Access denied to this private repository.")
                    else:
                        # For regular web views
                        flash("You do not have permission to view this private repository.", "danger")
                        return redirect(url_for('git.git_homepage')) # Assuming blueprint 'git' for homepage

        # If public, or private and checks passed, proceed to the route
        return f(owner_username, repo_short_name, *args, **kwargs)
    return decorated_function
