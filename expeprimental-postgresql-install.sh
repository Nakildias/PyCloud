#!/usr/bin/bash
# Might need to run sudo -u postgres initdb --locale=C.UTF-8 --encoding=UTF8 -D '/var/lib/postgres/data'
# Exit immediately if a command exits with a non-zero status.
set -e
# Treat unset variables as an error when substituting.
set -u
# Pipelines return the exit status of the last command that failed, or zero if all succeeded.
set -o pipefail

# --- Configuration ---
APP_NAME="PyCloud" # Updated App Name
VENV_DIR="$HOME/.local/share/${APP_NAME}" # Virtual environment location
APP_INSTALL_DIR="${VENV_DIR}" # Where the Flask app files will live
TARGET_BIN_DIR="/usr/local/bin" # Standard location for user-installed executables
# Source directories/files relative to the script location
SOURCE_APP_DIR="./" # This means run.py, app are in the same dir as install.sh
REQUIRED_ITEMS=( # Items needed from the source directory
    "${SOURCE_APP_DIR}/run.py"
    "${SOURCE_APP_DIR}/app"
)
PYTHON_DEPS=( # Python packages to install via pip
    "pip" # Ensure pip is up-to-date first
    "setuptools"
    "wheel"
    "Flask"
    "Flask-SQLAlchemy"
    "Flask-Login"
    "Flask-WTF"
    "requests"
    "email-validator"
    "flask_mail"
    "pillow"
    "flask-migrate"
    "markdown"
    "humanize"
    "gitpython"
    "yt-dlp"
    "Flask-SocketIO"
    "paramiko"
    "eventlet"
    "psycopg2-binary" # Added for PostgreSQL
    "py7zr"
    "gunicorn"
)
MAIN_EXECUTABLE_NAME="PyCloud" # Name of the script to link in TARGET_BIN_DIR
LINK_NAMES=( "pycloud" ) # Additional names (symlinks)

# --- PostgreSQL Specific Configuration ---
PG_USER="pycloud"
PG_DB="pycloud"
# Generate a random 24-character password for the PostgreSQL user
PG_PASS=$(head /dev/urandom | tr -dc A-Za-z0-9 | head -c 24)
CREDENTIALS_FILE="${APP_INSTALL_DIR}/db_creds.txt" # Save db_creds.txt inside the app directory


# --- Helper Functions ---
info() {
    echo "[INFO] $1"
}

warn() {
    echo "[WARN] $1" >&2
}

error() {
    echo "[ERROR] $1" >&2
    exit 1
}

# Function to check if a command exists
command_exists() {
    command -v "$1" >/dev/null 2>&1
}

# Function to run command with sudo, prompting if needed
run_sudo() {
    if command_exists sudo; then
        info "Requesting sudo privileges for: $*"
        # Prompt for sudo password if needed
        sudo "$@"
    else
        error "sudo command not found. Cannot perform required action: $*"
    fi
}

# --- Pre-flight Checks ---

# This is the primary change: explicitly disallow running with sudo
if [ "$EUID" -eq 0 ]; then
    error "This script should NOT be run with sudo directly. Please run it as a regular user (e.g., bash ./install.sh). The script will prompt for sudo password when needed."
fi

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
info "Script source directory: ${SCRIPT_DIR}"
info "Application source files expected in: ${SCRIPT_DIR}/${SOURCE_APP_DIR}"

for item in "${REQUIRED_ITEMS[@]}"; do
    item_path="${SCRIPT_DIR}/${item#./}"
    if [[ ! -e "${item_path}" ]]; then
        error "Required source item not found: ${item_path}"
    fi
done

# --- System Dependency Installation (Always Run) ---

info "Attempting to install/update system dependencies (Python 3, venv, PostgreSQL)..."
if command_exists apt; then
    PACKAGE_MANAGER="apt"
    run_sudo apt update
    run_sudo apt install -y python3 python3-venv postgresql || error "Failed using apt."
elif command_exists dnf; then
    PACKAGE_MANAGER="dnf"
    run_sudo dnf install -y python3 python3-virtualenv postgresql-server postgresql-contrib || error "Failed using dnf."
elif command_exists pacman; then
    PACKAGE_MANAGER="pacman"
    run_sudo pacman -S --noconfirm --needed python python-virtualenv postgresql || error "Failed using pacman."
elif command_exists emerge; then
    PACKAGE_MANAGER="emerge"
    run_sudo emerge --ask --noreplace dev-lang/python dev-db/postgresql || error "Failed initial emerge for python."
    info "Assuming Python 3 venv module is included with dev-lang/python on Gentoo."
else
    error "Could not detect a supported package manager. Please install Python 3 and venv module manually."
fi
info "System dependency check/installation complete."

if ! command_exists python3; then error "Python 3 installation failed or python3 is not in PATH."; fi
if ! python3 -m venv --help >/dev/null 2>&1; then error "Python 3 'venv' module not available."; fi
info "Python 3 and venv module confirmed."

# --- PostgreSQL Database Setup (Integrated) ---

echo "--- PostgreSQL Database Setup for ${PG_USER} ---"
echo ""
echo "Database configuration target:"
echo "  Username: ${PG_USER}"
echo "  Database: ${PG_DB}"
echo "  Password: ${PG_PASS} (auto-generated, will be saved to ${CREDENTIALS_FILE})"
echo ""
echo "Attempting to manage PostgreSQL user and database..."
echo "You may be prompted for your system's 'sudo' password."

# Ensure PostgreSQL service is running before attempting psql commands
info "Ensuring PostgreSQL service is running..."
if ! sudo systemctl is-active --quiet postgresql; then
    info "PostgreSQL service is not active. Attempting to start it."
    run_sudo systemctl start postgresql || error "Failed to start PostgreSQL service. Please check its status with 'sudo systemctl status postgresql' and logs with 'sudo journalctl -u postgresql'."
fi
info "PostgreSQL service is active."

# Optional: Delete existing PyCloud database
info "Checking for existing database '${PG_DB}' for optional deletion..."
if sudo -u postgres psql -lqt | cut -d \| -f 1 | grep -wq "${PG_DB}"; then
    read -p "WARNING: Database '${PG_DB}' already exists. Do you want to delete it before proceeding? (y/N): " DELETE_CONFIRM
    if [[ "$DELETE_CONFIRM" =~ ^[yY]$ ]]; then
        info "Attempting to drop database '${PG_DB}'..."
        # Disconnect any active sessions to the database before dropping
        sudo -u postgres psql -c "SELECT pg_terminate_backend(pg_stat_activity.pid) FROM pg_stat_activity WHERE pg_stat_activity.datname = '${PG_DB}';" || true
        sudo -u postgres psql -c "DROP DATABASE ${PG_DB};"
        info "Database '${PG_DB}' deleted successfully."
    else
        info "Skipping database deletion."
    fi
fi

# Create or Update PostgreSQL User
info "Checking for user '${PG_USER}'..."
if sudo -u postgres psql -t -c "\du" | awk '{print $1}' | grep -wq "${PG_USER}"; then
    info "User '${PG_USER}' already exists. Updating password..."
    sudo -u postgres psql -c "ALTER USER ${PG_USER} WITH PASSWORD '${PG_PASS}';"
    info "Password for user '${PG_USER}' updated successfully."
else
    info "User '${PG_USER}' does not exist. Creating user..."
    sudo -u postgres psql -c "CREATE USER ${PG_USER} WITH PASSWORD '${PG_PASS}';"
    info "User '${PG_USER}' created successfully."
fi

# Create PostgreSQL Database (if it doesn't exist)
info "Checking for database '${PG_DB}' again (after optional deletion)..."
if sudo -u postgres psql -lqt | cut -d \| -f 1 | grep -wq "${PG_DB}"; then
    info "Database '${PG_DB}' now exists. Skipping creation."
else
    info "Database '${PG_DB}' does not exist. Creating database..."
    sudo -u postgres psql -c "CREATE DATABASE ${PG_DB} OWNER ${PG_USER};"
    info "Database '${PG_DB}' created and owned by '${PG_USER}'."
fi

# Verify Connection to New Database
echo ""
info "Verifying connection to database '${PG_DB}' with user '${PG_USER}'..."
# Explicitly set PGPASSWORD for non-interactive connection
export PGPASSWORD="${PG_PASS}"
if sudo -u postgres psql -h localhost -p 5432 -U "${PG_USER}" -d "${PG_DB}" -c "\dt" > /dev/null 2>&1; then
    info "Successfully connected to database '${PG_DB}' as user '${PG_USER}'."
    info "Your PostgreSQL setup appears to be correct and accessible!"
else
    error "Failed to connect to database '${PG_DB}' as user '${PG_USER}'. This is a critical error." \
          "Common reasons: incorrect password, database or user not actually created, or pg_hba.conf not allowing connection for this user/host/database." \
          "Check PostgreSQL logs for more details (e.g., 'sudo journalctl -u postgresql')."
fi
# Unset PGPASSWORD immediately after verification
unset PGPASSWORD

info "PostgreSQL database setup complete."

# Save PostgreSQL Credentials to File
info "Saving PostgreSQL credentials to ${CREDENTIALS_FILE}..."
cat <<EOF > "${CREDENTIALS_FILE}"
# PostgreSQL Database Credentials for your Flask app
# Use these to set your DATABASE_URL environment variable.

# Username: ${PG_USER}
# Password: ${PG_PASS}
# Database Name: ${PG_DB}
# Host: localhost (default)
# Port: 5432 (default)

# Full SQLAlchemy Database URI:
DATABASE_URL="postgresql://${PG_USER}:${PG_PASS}@localhost:5432/${PG_DB}"
EOF

info "Credentials saved successfully to '${CREDENTIALS_FILE}'."
info "File permissions for '${CREDENTIALS_FILE}' set to read-only for owner."
chmod 600 "${CREDENTIALS_FILE}" # Set read-only for owner

# --- Cleanup Previous Installation (if VENV_DIR exists) ---
# Removed SQLite specific DB backup logic.
# The `instance` folder will be created by Flask, and specific media folders by _ensure_directories_exist.

if [[ -d "${VENV_DIR}" ]]; then
    info "Existing installation directory found at ${VENV_DIR}. Performing selective update..."

    # 1. Remove specific old application files and folders (NOT the VENV_DIR itself)
    info "Removing old application files (run.py, app/routes, app/templates, app/static/codemirror, app/static/css, app/static/icons, app/static/js, app/static/sounds, app/decorators.py, app/forms.py, app/models.py, app/utils.py, app/__init__.py, app/config.py, app/events.py)..."
    rm -f "${VENV_DIR}/run.py" || warn "Could not remove old run.py (might not exist)."
    rm -f "${VENV_DIR}/app/__init__.py" || warn "Could not remove old __init__.py (might not exist)."
    rm -f "${VENV_DIR}/app/config.py" || warn "Could not remove old config.py (might not exist)."
    rm -f "${VENV_DIR}/app/decorators.py" || warn "Could not remove old decorators.py (might not exist)."
    rm -f "${VENV_DIR}/app/forms.py" || warn "Could not remove old forms.py (might not exist)."
    rm -f "${VENV_DIR}/app/models.py" || warn "Could not remove old models.py (might not exist)."
    rm -f "${VENV_DIR}/app/utils.py" || warn "Could not remove old utils.py (might not exist)."
    rm -f "${VENV_DIR}/app/events.py" || warn "Could not remove old events.py (might not exist)." # Added events.py
    rm -rf "${VENV_DIR}/app/templates" || warn "Could not remove old templates directory (might not exist)."
    rm -rf "${VENV_DIR}/app/static/css" || warn "Could not remove old css directory (might not exist)."
    rm -rf "${VENV_DIR}/app/static/js" || warn "Could not remove old js directory (might not exist)."
    rm -rf "${VENV_DIR}/app/static/icons" || warn "Could not remove old icons directory (might not exist)."
    rm -rf "${VENV_DIR}/app/static/codemirror" || warn "Could not remove old codemirror directory (might not exist)."
    rm -rf "${VENV_DIR}/app/static/sounds" || warn "Could not remove old sounds directory (might not exist)."
    rm -rf "${VENV_DIR}/app/routes" || warn "Could not remove old routes directory (might not exist)."
    rm -rf "${VENV_DIR}/app/static/uploads/post_media" || warn "Could not remove old post_media (might not exist)."
    rm -rf "${VENV_DIR}/app/static/uploads/profile_pics" || warn "Could not remove old profile_pics (might not exist)."
    rm -rf "${VENV_DIR}/app/static/uploads/video_thumbnails" || warn "Could not remove old video_thumbnails (might not exist)."
    
    # 3. Remove specific static subdirectories as requested (this block is redundant if the above rm -rf of static/* subdirs is thorough)
    # Keeping it here for clarity if certain static subdirectories were intended to be selectively removed.
    # If app/static/css, app/static/js etc. are already removed above, this is unnecessary.
    info "Removing specified static subdirectories (css, js, icons)..."
    STATIC_DIR_BASE="${VENV_DIR}/app/static" # Corrected path to app/static
    if [[ -d "${STATIC_DIR_BASE}" ]]; then
        rm -rf "${STATIC_DIR_BASE}/css" || warn "Could not remove old ${STATIC_DIR_BASE}/css (might not exist)."
        rm -rf "${STATIC_DIR_BASE}/js" || warn "Could not remove old ${STATIC_DIR_BASE}/js (might not exist)."
        rm -rf "${STATIC_DIR_BASE}/icons" || warn "Could not remove old ${STATIC_DIR_BASE}/icons (might not exist)."
        rm -rf "${STATIC_DIR_BASE}/codemirror" || warn "Could not remove old ${STATIC_DIR_BASE}/codemirror (might not exist)."
        rm -rf "${STATIC_DIR_BASE}/sounds" || warn "Could not remove old ${STATIC_DIR_BASE}/sounds (might not exist)."
    else
        info "Base static directory ${STATIC_DIR_BASE} not found, skipping removal of its subdirectories."
    fi

    # 4. Remove old executable and links (requires sudo as they are in /usr/local/bin)
    info "Removing old executable and links from ${TARGET_BIN_DIR}..."
    run_sudo rm -f "${TARGET_BIN_DIR}/${MAIN_EXECUTABLE_NAME}" || warn "Could not remove old executable (might not exist)."
    for link_name in "${LINK_NAMES[@]}"; do
        TARGET_LINK="${TARGET_BIN_DIR}/${link_name}"
        run_sudo rm -f "${TARGET_LINK}" || warn "Could not remove old symlink ${TARGET_LINK}"
        run_sudo ln -sf "${TARGET_BIN_DIR}/${MAIN_EXECUTABLE_NAME}" "${TARGET_LINK}" || error "Failed to create symlink ${link_name}"
    fi
    info "Selective cleanup of previous installation parts complete."
else
    info "No previous installation directory found at ${VENV_DIR}. Proceeding with new installation."
    # Ensure parent directory for VENV_DIR exists for the next step if VENV_DIR itself is new
    mkdir -p "$(dirname "${VENV_DIR}")" || error "Failed to create parent directory for ${VENV_DIR}"
fi

# --- Virtual Environment Setup, Application Deployment, and Database Migration ---

# Ensure the main VENV_DIR exists before trying to create a venv in it or check its subdirs
mkdir -p "${VENV_DIR}" || error "Failed to create application directory ${VENV_DIR}"

if [[ ! -d "${VENV_DIR}/bin" ]]; then # Check if it looks like a venv (e.g., bin dir is missing)
    info "Virtual environment structure not found or incomplete in ${VENV_DIR}. Creating/Recreating venv components..."
    python3 -m venv "${VENV_DIR}" || error "Failed to create/initialize virtual environment."
else
    info "Existing virtual environment structure found in ${VENV_DIR}."
fi

info "Activating virtual environment..."
# shellcheck source=/dev/null
source "${VENV_DIR}/bin/activate" || error "Failed to activate virtual environment."

info "Upgrading pip, setuptools, and wheel..."
python -m pip install --upgrade pip || error "Failed to upgrade pip in venv."
python -m pip install --upgrade setuptools wheel || error "Failed to upgrade setuptools/wheel."

info "Installing/Updating Python dependencies into virtual environment..."
python -m pip install --upgrade "${PYTHON_DEPS[@]}" || error "Failed to install/upgrade Python dependencies."

info "Copying application files into virtual environment..."
# APP_INSTALL_DIR is VENV_DIR. Ensure subdirectories for static and templates exist.
mkdir -p "${APP_INSTALL_DIR}/app/static" || error "Failed to create static directory in venv: ${APP_INSTALL_DIR}/app/static"
mkdir -p "${APP_INSTALL_DIR}/app/templates" || error "Failed to create templates directory in venv: ${APP_INSTALL_DIR}/app/templates"

cp "${SCRIPT_DIR}/${SOURCE_APP_DIR}/run.py" "${APP_INSTALL_DIR}/run.py" || error "Failed to copy run.py"
info "Copying contents of app directory..."
cp -r "${SCRIPT_DIR}/${SOURCE_APP_DIR}/app/." "${APP_INSTALL_DIR}/app/" || error "Failed to copy contents of app directory"
# Add copy for default manager_settings.json if needed
# if [[ -f "${SCRIPT_DIR}/${SOURCE_APP_DIR}/manager_settings.json" ]]; then
#         cp "${SCRIPT_DIR}/${SOURCE_APP_DIR}/manager_settings.json" "${APP_INSTALL_DIR}/" || error "Failed to copy manager_settings.json"
# fi
info "Application files copied."


info "Performing database migrations..."
ORIGINAL_PWD=$(pwd)
cd "${APP_INSTALL_DIR}" || error "Failed to change directory to ${APP_INSTALL_DIR}"

# Export DATABASE_URL for Flask-Migrate commands
export DATABASE_URL="postgresql://${PG_USER}:${PG_PASS}@localhost:5432/${PG_DB}"
info "DATABASE_URL environment variable set for migrations."

export FLASK_APP=run.py
info "FLASK_APP set to run.py"

if [[ ! -d "${APP_INSTALL_DIR}/migrations" ]]; then
    info "Migrations directory not found. Initializing Flask-Migrate..."
    flask db init || error "Failed to initialize Flask-Migrate (flask db init)."
    info "Flask-Migrate initialized."
else
    info "Migrations directory already exists. Skipping flask db init."
fi

info "Running database migration generation..."
flask db migrate -m "Initial PostgreSQL schema or updates" || error "Failed to generate database migration (flask db migrate)."
info "Database migration generated."

info "Applying database upgrade..."
flask db upgrade || error "Failed to apply database upgrade (flask db upgrade)."
info "Database upgrade applied."

cd "${ORIGINAL_PWD}" || error "Failed to change directory back to original path."
info "Database migrations completed."

info "Deactivating virtual environment"
deactivate


# --- Executable Setup ---
info "Copying ${MAIN_EXECUTABLE_NAME} executable to ${TARGET_BIN_DIR}/"
# Assuming MAIN_EXECUTABLE_NAME points to a simple script or a wrapper
# If it's your run.py, you probably want to link to a wrapper script that activates the venv and runs it.
# For now, keeping the original logic.
run_sudo cp "${SCRIPT_DIR}/${SOURCE_APP_DIR}/${MAIN_EXECUTABLE_NAME}" "${TARGET_BIN_DIR}/${MAIN_EXECUTABLE_NAME}" || error "Failed to copy ${MAIN_EXECUTABLE_NAME} to ${TARGET_BIN_DIR}"
run_sudo chmod +x "${TARGET_BIN_DIR}/${MAIN_EXECUTABLE_NAME}" || error "Failed to set executable permission."

for link_name in "${LINK_NAMES[@]}"; do
    if [[ "${link_name}" != "${MAIN_EXECUTABLE_NAME}" ]]; then
        TARGET_LINK="${TARGET_BIN_DIR}/${link_name}"
        run_sudo rm -f "${TARGET_LINK}" || warn "Could not remove potentially existing symlink ${TARGET_LINK}"
        run_sudo ln -sf "${TARGET_BIN_DIR}/${MAIN_EXECUTABLE_NAME}" "${TARGET_LINK}" || error "Failed to create symlink ${link_name}"
    fi
done
info "Executable setup completed."

# --- Systemd Service Setup (System-wide) ---
info "Setting up systemd system service for ${APP_NAME}..."

SERVICE_NAME="pycloud.service"
SERVICE_FILE_DIR="/etc/systemd/system" # System-wide service directory
SERVICE_FILE_PATH="${SERVICE_FILE_DIR}/${SERVICE_NAME}"
USERNAME=$(whoami) # Get the current username to set as User/Group in service file

# Create the service file content. This requires sudo.
run_sudo bash -c "cat <<EOF > \"${SERVICE_FILE_PATH}\"
[Unit]
Description=${APP_NAME} Flask Application
After=network.target

[Service]
ExecStart=${VENV_DIR}/bin/gunicorn --worker-class eventlet -w 1 --bind 0.0.0.0:8888 run:app
WorkingDirectory=${APP_INSTALL_DIR}
Environment="FLASK_APP=run.py"
Environment="DATABASE_URL=postgresql://${PG_USER}:${PG_PASS}@localhost:5432/${PG_DB}" # <--- Integrated DB URL
Restart=always
User=${USERNAME}
Group=${USERNAME}
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF"

info "Systemd service file created at ${SERVICE_FILE_PATH}"

info "Enabling and starting the ${SERVICE_NAME} system service..."
run_sudo systemctl daemon-reload || error "Failed to reload systemd daemon."
run_sudo systemctl enable "${SERVICE_NAME}" || error "Failed to enable ${SERVICE_NAME}."
run_sudo systemctl restart "${SERVICE_NAME}" || error "Failed to restart ${SERVICE_NAME}."
info "${SERVICE_NAME} enabled and restarted successfully."

# --- Final Check ---
if [[ -x "${TARGET_BIN_DIR}/${MAIN_EXECUTABLE_NAME}" ]]; then
    if command_exists "${MAIN_EXECUTABLE_NAME}"; then
        info "-------------------------------------------"
        info " Installation successful!"
        info " Virtual Environment: ${VENV_DIR}"
        info " App Files: ${APP_INSTALL_DIR}"
        info " Database: PostgreSQL (${PG_DB})"
        info " Credentials: ${CREDENTIALS_FILE}"
        info " Static files in ${APP_INSTALL_DIR}/app/static (updated/preserved)"
        info " Executable: ${TARGET_BIN_DIR}/${MAIN_EXECUTABLE_NAME}"
        info " Symlinks: ${LINK_NAMES[*]} (if any) in ${TARGET_BIN_DIR}"
        info " Systemd System Service: ${SERVICE_NAME} is enabled and running."
        info " To check service status: sudo systemctl status ${SERVICE_NAME}"
        info " To view logs: journalctl -u ${SERVICE_NAME}"
        info " You should now be able to run the application using: ${MAIN_EXECUTABLE_NAME} or pycloud"
        info " If the command isn't found immediately, try opening a new terminal session."
        info "-------------------------------------------"
    else
        warn "-------------------------------------------"
        warn " Installation seems complete, but '${MAIN_EXECUTABLE_NAME}' not found in current PATH."
        warn " Executable is located at: ${TARGET_BIN_DIR}/${MAIN_EXECUTABLE_NAME}"
        warn " Please ensure '${TARGET_BIN_DIR}' is in your PATH environment variable."
        warn " You might need to restart your shell, log out and back in, or manually add it."
        warn " Example (add to ~/.bashrc or ~/.zshrc): export PATH=\"${TARGET_BIN_DIR}:\$PATH\""
        warn "-------------------------------------------"
    fi
else
    error "Installation failed. Could not find executable file at '${TARGET_BIN_DIR}/${MAIN_EXECUTABLE_NAME}' or it lacks execute permissions."
fi

exit 0
