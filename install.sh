#!/usr/bin/bash

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
TARGET_BIN_DIR="/usr/local/bin"         # Standard location for user-installed executables
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
    "py7zr"
)
MAIN_EXECUTABLE_NAME="PyCloud" # Name of the script to link in TARGET_BIN_DIR
LINK_NAMES=( "pycloud" ) # Additional names (symlinks)

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
        sudo "$@"
    else
        error "sudo command not found. Cannot perform required action: $*"
    fi
}

# --- Pre-flight Checks ---

# This is the primary change: explicitly disallow running with sudo
if [ "$EUID" -eq 0 ]; then
   error "This script should NOT be run with sudo. Please run it as a regular user: bash ./install.sh"
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

info "Attempting to install/update system dependencies (Python 3, venv)..."
if command_exists apt; then
    PACKAGE_MANAGER="apt"
    run_sudo apt update
    run_sudo apt install -y python3 python3-venv || error "Failed using apt."
elif command_exists dnf; then
    PACKAGE_MANAGER="dnf"
    run_sudo dnf install -y python3 python3-virtualenv || error "Failed using dnf."
elif command_exists pacman; then
    PACKAGE_MANAGER="pacman"
    run_sudo pacman -S --noconfirm --needed python python-virtualenv || error "Failed using pacman."
elif command_exists emerge; then
    PACKAGE_MANAGER="emerge"
    run_sudo emerge --ask --noreplace dev-lang/python || error "Failed initial emerge for python."
    info "Assuming Python 3 venv module is included with dev-lang/python on Gentoo."
else
    error "Could not detect a supported package manager. Please install Python 3 and venv module manually."
fi
info "System dependency check/installation complete."

if ! command_exists python3; then error "Python 3 installation failed or python3 is not in PATH."; fi
if ! python3 -m venv --help >/dev/null 2>&1; then error "Python 3 'venv' module not available."; fi
info "Python 3 and venv module confirmed."


# --- Cleanup Previous Installation (if VENV_DIR exists) ---
DB_PATH="${VENV_DIR}/instance/database.db"
DB_BACKUP_PATH="${VENV_DIR}/instance/_database.db.bak.$(date +%Y%m%d_%H%M%S)" # Unique backup name
DB_WAS_BACKED_UP=false

if [[ -d "${VENV_DIR}" ]]; then
    info "Existing installation directory found at ${VENV_DIR}. Performing selective update..."

    # 1. Backup database if it exists
    if [[ -f "${DB_PATH}" ]]; then
        info "Backing up existing database from ${DB_PATH} to ${DB_BACKUP_PATH}..."
        cp "${DB_PATH}" "${DB_BACKUP_PATH}" || error "Failed to backup database. Halting to prevent data loss."
        DB_WAS_BACKED_UP=true
        info "Database backed up to ${DB_BACKUP_PATH}"
    fi

    # 2. Remove specific old application files and folders (NOT the VENV_DIR itself)
    info "Removing old application files (run.py, app/routes, app/templates, app/static/codemirror, app/static/css, app/static/icons, app/static/js, app/static/sounds, app/decorators.py, app/forms.py, app/models.py, app/utils.py, app/__init__.py, app/config.py)..."
    rm -f "${VENV_DIR}/run.py" || warn "Could not remove old run.py (might not exist)."
    rm -f "${VENV_DIR}/app/__init__.py" || warn "Could not remove old __init__.py (might not exist)."
    rm -f "${VENV_DIR}/config.py" || warn "Could not remove old config.py (might not exist)."
    rm -f "${VENV_DIR}/decorators.py" || warn "Could not remove old decorators.py (might not exist)."
    rm -f "${VENV_DIR}/forms.py" || warn "Could not remove old forms.py (might not exist)."
    rm -f "${VENV_DIR}/models.py" || warn "Could not remove old models.py (might not exist)."
    rm -f "${VENV_DIR}/utils.py" || warn "Could not remove old utils.py (might not exist)."
    rm -rf "${VENV_DIR}/app/templates" || warn "Could not remove old templates directory (might not exist)."
    rm -rf "${VENV_DIR}/app/static/css" || warn "Could not remove old css directory (might not exist)."
    rm -rf "${VENV_DIR}/app/static/js" || warn "Could not remove old js directory (might not exist)."
    rm -rf "${VENV_DIR}/app/static/icons" || warn "Could not remove old icons directory (might not exist)."
    rm -rf "${VENV_DIR}/app/static/codemirror" || warn "Could not remove old codemirror directory (might not exist)."
    rm -rf "${VENV_DIR}/app/static/sounds" || warn "Could not remove old sounds directory (might not exist)."
    rm -rf "${VENV_DIR}/app/routes" || warn "Could not remove old routes directory (might not exist)."

    # 3. Remove specific static subdirectories as requested
    info "Removing specified static subdirectories (css, js, icons)..."
    STATIC_DIR_BASE="${VENV_DIR}/static" # This is APP_INSTALL_DIR/static
    # Ensure the base static directory exists before trying to remove subdirs
    if [[ -d "${STATIC_DIR_BASE}" ]]; then
        rm -rf "${STATIC_DIR_BASE}/css" || warn "Could not remove old ${STATIC_DIR_BASE}/css (might not exist)."
        rm -rf "${STATIC_DIR_BASE}/js" || warn "Could not remove old ${STATIC_DIR_BASE}/js (might not exist)."
        rm -rf "${STATIC_DIR_BASE}/icons" || warn "Could not remove old ${STATIC_DIR_BASE}/icons (might not exist)."
    else
        info "Base static directory ${STATIC_DIR_BASE} not found, skipping removal of its subdirectories."
    fi
    # The main static folder "${VENV_DIR}/static" itself is NOT deleted.

    # 4. Remove old executable and links
    info "Removing old executable and links from ${TARGET_BIN_DIR}..."
    run_sudo rm -f "${TARGET_BIN_DIR}/${MAIN_EXECUTABLE_NAME}" || warn "Could not remove old executable (might not exist)."
    for link_name in "${LINK_NAMES[@]}"; do
        TARGET_LINK="${TARGET_BIN_DIR}/${link_name}"
        run_sudo rm -f "${TARGET_LINK}" || warn "Could not remove old symlink ${link_name} (might not exist)."
    done
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
mkdir -p "${APP_INSTALL_DIR}/static" || error "Failed to create static directory in venv: ${APP_INSTALL_DIR}/static"
mkdir -p "${APP_INSTALL_DIR}/templates" || error "Failed to create templates directory in venv: ${APP_INSTALL_DIR}/templates"

cp "${SCRIPT_DIR}/${SOURCE_APP_DIR}/run.py" "${APP_INSTALL_DIR}/run.py" || error "Failed to copy run.py"
info "Copying contents of app directory..."
cp -r "${SCRIPT_DIR}/${SOURCE_APP_DIR}/app/." "${APP_INSTALL_DIR}/app/" || error "Failed to copy contents of app directory"
# Add copy for default manager_settings.json if needed
# if [[ -f "${SCRIPT_DIR}/${SOURCE_APP_DIR}/manager_settings.json" ]]; then
#      cp "${SCRIPT_DIR}/${SOURCE_APP_DIR}/manager_settings.json" "${APP_INSTALL_DIR}/" || error "Failed to copy manager_settings.json"
# fi
info "Application files copied."

# Restore database if it was backed up
if [[ "${DB_WAS_BACKED_UP}" == true ]]; then
    if [[ -f "${DB_BACKUP_PATH}" ]]; then
        info "Restoring database to ${DB_PATH}..."
        # Ensure target directory exists (it should, as VENV_DIR was created/exists)
        mv "${DB_BACKUP_PATH}" "${DB_PATH}" || error "Failed to restore database from ${DB_BACKUP_PATH}."
        info "Database restored. Original backup is at ${DB_BACKUP_PATH} (can be manually deleted if desired)."
    else
        warn "Database backup was indicated but not found at ${DB_BACKUP_PATH}. Database may not have been restored."
    fi
fi

info "Performing database migrations..."
ORIGINAL_PWD=$(pwd)
cd "${APP_INSTALL_DIR}" || error "Failed to change directory to ${APP_INSTALL_DIR}"

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
flask db migrate -m "Creates new tables and other initial tables" || error "Failed to generate database migration (flask db migrate)."
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
run_sudo cp "${SCRIPT_DIR}/${SOURCE_APP_DIR}/${MAIN_EXECUTABLE_NAME}" "${TARGET_BIN_DIR}/${MAIN_EXECUTABLE_NAME}" || error "Failed to copy ${MAIN_EXECUTABLE_NAME} to ${TARGET_BIN_DIR}"
run_sudo chmod +x "${TARGET_BIN_DIR}/${MAIN_EXECUTABLE_NAME}" || error "Failed to set executable permission."

for link_name in "${LINK_NAMES[@]}"; do
    if [[ "${link_name}" != "${MAIN_EXECUTABLE_NAME}" ]]; then
        TARGET_LINK="${TARGET_BIN_DIR}/${link_name}"
        info "Creating symlink: ${TARGET_LINK} -> ${MAIN_EXECUTABLE_NAME}"
        run_sudo rm -f "${TARGET_LINK}" || warn "Could not remove potentially existing symlink ${TARGET_LINK}"
        run_sudo ln -sf "${TARGET_BIN_DIR}/${MAIN_EXECUTABLE_NAME}" "${TARGET_LINK}" || error "Failed to create symlink ${link_name}"
    fi
done
info "Executable setup completed."


# --- Final Check ---
if [[ -x "${TARGET_BIN_DIR}/${MAIN_EXECUTABLE_NAME}" ]]; then
    if command_exists "${MAIN_EXECUTABLE_NAME}"; then
        info "-------------------------------------------"
        info " Installation successful!"
        info " Virtual Environment: ${VENV_DIR}"
        info " App Files: ${APP_INSTALL_DIR}"
        info " Database: ${DB_PATH} (should be preserved/migrated)"
        info " Static files in ${APP_INSTALL_DIR}/static (css,js,icons updated, others preserved)"
        info " Executable: ${TARGET_BIN_DIR}/${MAIN_EXECUTABLE_NAME}"
        info " Symlinks: ${LINK_NAMES[*]} (if any) in ${TARGET_BIN_DIR}"
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
