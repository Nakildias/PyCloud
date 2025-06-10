#!/bin/bash

# This script helps create a PostgreSQL user and database,
# and saves the credentials to a local file.
# It includes robust error checking for user and database existence.
# This version hardcodes the username and database name to 'PyCloud',
# generates a random password, and offers to delete the database if it exists.

# Exit immediately if a command exits with a non-zero status.
set -e

echo "--- PostgreSQL Database Setup ---"

# --- Hardcoded User and Database Names ---
PG_USER="pycloud"
PG_DB="pycloud"

# --- Generate a Random 24-character Password ---
# Using /dev/urandom for cryptographically secure random bytes
# tr -dc A-Za-z0-9 removes non-alphanumeric characters
# head -c 24 takes the first 24 characters
PG_PASS=$(head /dev/urandom | tr -dc A-Za-z0-9 | head -c 24)

echo ""
echo "Database configuration target:"
echo "  Username: ${PG_USER}"
echo "  Database: ${PG_DB}"
echo "  Password: ${PG_PASS} (auto-generated, will be saved to db_creds.txt)"
echo ""
echo "Attempting to manage PostgreSQL user and database..."
echo "You may be prompted for your system's 'sudo' password."

# --- Step 1: Optional: Delete existing PyCloud database ---
echo "Checking for existing database '${PG_DB}'..."
if sudo -u postgres psql -lqt | cut -d \| -f 1 | grep -wq "${PG_DB}"; then
    read -p "WARNING: Database '${PG_DB}' already exists. Do you want to delete it before proceeding? (y/N): " DELETE_CONFIRM
    if [[ "$DELETE_CONFIRM" =~ ^[yY]$ ]]; then
        echo "Attempting to drop database '${PG_DB}'..."
        # Disconnect any active sessions to the database before dropping
        sudo -u postgres psql -c "SELECT pg_terminate_backend(pg_stat_activity.pid) FROM pg_stat_activity WHERE pg_stat_activity.datname = '${PG_DB}';" || true
        sudo -u postgres psql -c "DROP DATABASE ${PG_DB};"
        echo "Database '${PG_DB}' deleted successfully."
    else
        echo "Skipping database deletion."
    fi
fi

# --- Step 2: Create or Update PostgreSQL User ---
echo "Checking for user '${PG_USER}'..."
if sudo -u postgres psql -t -c "\du" | awk '{print $1}' | grep -wq "${PG_USER}"; then
    echo "User '${PG_USER}' already exists. Updating password..."
    sudo -u postgres psql -c "ALTER USER ${PG_USER} WITH PASSWORD '${PG_PASS}';"
    echo "Password for user '${PG_USER}' updated successfully."
else
    echo "User '${PG_USER}' does not exist. Creating user..."
    sudo -u postgres psql -c "CREATE USER ${PG_USER} WITH PASSWORD '${PG_PASS}';"
    echo "User '${PG_USER}' created successfully."
fi

# --- Step 3: Create PostgreSQL Database (if it doesn't exist) ---
echo "Checking for database '${PG_DB}' again (after optional deletion)..."
if sudo -u postgres psql -lqt | cut -d \| -f 1 | grep -wq "${PG_DB}"; then
    echo "Database '${PG_DB}' now exists. Skipping creation."
else
    echo "Database '${PG_DB}' does not exist. Creating database..."
    sudo -u postgres psql -c "CREATE DATABASE ${PG_DB} OWNER ${PG_USER};"
    echo "Database '${PG_DB}' created and owned by '${PG_USER}'."
fi

# --- Step 4: Verify Connection to New Database ---
echo ""
echo "Verifying connection to database '${PG_DB}' with user '${PG_USER}'..."
# Attempt to connect and run a simple command like \dt (list tables) in quiet mode
if sudo -u postgres psql -h localhost -p 5432 -U "${PG_USER}" -d "${PG_DB}" -c "\dt" > /dev/null 2>&1; then
    echo "Successfully connected to database '${PG_DB}' as user '${PG_USER}'."
    echo "Your PostgreSQL setup appears to be correct and accessible!"
else
    echo "ERROR: Failed to connect to database '${PG_DB}' as user '${PG_USER}'."
    echo "This is a critical error. Please investigate further."
    echo "Common reasons: incorrect password, database or user not actually created, or pg_hba.conf not allowing connection."
    echo "Check PostgreSQL logs for more details (e.g., 'sudo journalctl -u postgresql')."
    exit 1 # Exit on critical failure
fi

# --- Step 5: Save Credentials to File ---
CREDENTIALS_FILE="db_creds.txt"

if [ -f "$CREDENTIALS_FILE" ]; then
    echo ""
    read -p "WARNING: '${CREDENTIALS_FILE}' already exists. Overwrite? (y/N): " OVERWRITE_CONFIRM
    if [[ ! "$OVERWRITE_CONFIRM" =~ ^[yY]$ ]]; then
        echo "Operation cancelled. Credentials not saved to '${CREDENTIALS_FILE}'."
        exit 1
    fi
fi

# Construct the SQLAlchemy database URI
DB_URI="postgresql://${PG_USER}:${PG_PASS}@localhost:5432/${PG_DB}"

echo ""
echo "Saving credentials to ${CREDENTIALS_FILE}..."
cat <<EOF > "${CREDENTIALS_FILE}"
# PostgreSQL Database Credentials for your Flask app
# Use these to set your DATABASE_URL environment variable.

# Username: ${PG_USER}
# Password: ${PG_PASS}
# Database Name: ${PG_DB}
# Host: localhost (default)
# Port: 5432 (default)

# Full SQLAlchemy Database URI:
DATABASE_URL="${DB_URI}"
EOF

echo "Credentials saved successfully to '${CREDENTIALS_FILE}'."
echo "File permissions for '${CREDENTIALS_FILE}' set to read-only for owner."
chmod 600 "${CREDENTIALS_FILE}" # Set read-only for owner

echo ""
echo "--- Next Steps ---"
echo "1. The PostgreSQL database and user appear to be correctly set up and accessible."
echo "2. To use these credentials with your Flask application, set the DATABASE_URL environment variable:"
echo "   export DATABASE_URL=\"${DB_URI}\""
echo "   (Remember this export is for the current terminal session. For systemd, set it in the service file.)"
echo "3. Then, run your Flask-Migrate commands (from your virtual environment):"
echo "   flask db init (only if you haven't done it before for Alembic)"
echo "   flask db migrate -m \"Initial PostgreSQL schema\""
echo "   flask db upgrade"
echo "4. Remember to keep your 'db_creds.txt' file secure."
echo ""
