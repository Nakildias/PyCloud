# PyCloud: Your Personal Cloud & Social Platform 
# One Line Installation 
`git clone https://github.com/Nakildias/PyCloud && cd PyCloud && bash install.sh`

# To monitor servers you'll need to install the [PyCloud Daemon](https://github.com/Nakildias/PyCloudMonitorDaemon)

## 🚀 Overview

PyCloud is a feature-rich, self-hostable web application built with Python and Flask. It aims to provide a comprehensive suite of tools for personal cloud storage, social interaction, developer utilities, and more, all under your control. From managing your files and notes to connecting with friends, running emulators, and even managing Git repositories, PyCloud offers a versatile platform for individuals and small groups.

## 🛠️ Core Technologies

* **Backend**: Python, Flask
* **Database**: Flask-SQLAlchemy SQlite3
* **Authentication**: Flask-Login
* **Forms**: Flask-WTF
* **Real-time Communication**: Flask-SocketIO (used for SSH client, chat features)
* **Frontend**: HTML, CSS, JavaScript, Jinja2 templates
* **Git Integration**: Custom implementation using Python libraries to interact with Git repositories.
* **External Tools Integration**: `yt-dlp` (YouTube downloader), `paramiko` (SSH client), `Pillow` (Image upscaler), `Codemirror` (Code Editor)

## ✨ Features

PyCloud is packed with a wide array of features, categorized below:

### 👤 User Management & Authentication
* **User Registration**: Secure user registration with password hashing.
* **Login/Logout**: Standard session-based authentication.
* **Password Management**:
    * Forgot Password & Reset functionality (likely via email).
    * Email change/reset options.
* **User Profiles**:
    * Viewable user profiles with bio and social links.
    * Profile picture uploads.
    * Ability to edit one's own profile.
* **User Settings**:
    * Theme selection for personalized UI.
    * CodeMirror theme selection for file editor.
    * Other account-specific settings.
* **User Activity**: Tracks user's last seen status and online presence. (WIP)

### ☁️ Cloud Storage & File Management
* **File Uploads**: Upload various file types with configurable size limits.
* **File & Folder Management**:
    * Create, view, and organize files within folders.
    * Hierarchical folder structure.
* **File Viewing**:
    * View plain text files.
    * Preview images and potentially other media types.
* **File Editing**: In-browser text file editor (likely using CodeMirror).
* **Public File Sharing**:
    * Share files publicly via unique links.
    * Option to password-protect shared files.
* **Storage Quotas**: Per-user storage limits configurable by an admin.

### 📝 Notes
* **Note Creation**: Create and save rich-text or plain-text notes.
* **Note Viewing & Management**: List, view, and likely edit/delete notes.

### 💬 Social & Communication
* **Post Feed**: A central feed to view posts from followed users or all users.
* **Create Posts**:
    * Text-based posts.
    * Upload and share photos in posts.
    * Upload and share videos in posts.
* **Interactions**:
    * Like and dislike posts.
    * Comment on posts, with replies to comments.
    * Like and dislike comments.
* **Follow System**: Follow/unfollow other users to customize the feed.
* **Friends System**: Mutual follow likely constitutes a "friend" relationship for direct messaging.
* **Notifications**: Real-time notifications for events like:
    * New followers.
    * Likes/dislikes on posts/comments.
    * Comments/replies on posts.
    * Shares of posts/comments.
    * Repository collaborator invitations.
* **Find People**: Search or browse for other users on the platform.
* **Direct Messaging (DM)**:
    * One-on-one private chats with friends.
    * Send text messages and share files within DMs.
    * Read receipts and message editing/deletion.
    * Embedded chat interface in the base layout.
* **Group Chat**:
    * Public or group-based real-time chat.
    * Send text messages and share files.
* **Ollama AI Chat**:
    * Integration with a self-hosted Ollama instance for AI-powered chat.
    * Users can interact with configured AI models.

### 🔧 Developer Tools & Utilities
* **Git Integration (MyGit)**:
    * **Git Homepage**: Overview of public repositories.
    * **Repository Management**:
        * Create new private or public Git repositories.
        * View owned and collaborated repositories.
        * Star/unstar repositories.
    * **Repository Viewing**:
        * Browse repository file trees.
        * View file content (blobs).
        * View commit history and individual commit details.
        * Language statistics for repositories.
    * **Repository Operations**:
        * Create, edit, and upload files directly through the web interface.
        * Clone repositories via HTTP(S).
    * **Collaboration**: Add and manage collaborators for repositories.
    * **Settings**: Configure repository description, visibility, and manage collaborators.
    * **Forking**: Indication of forked repositories.
* **SSH Client**:
    * Web-based SSH terminal to connect to remote servers.
    * Real-time interaction via SocketIO.
    * Popup terminal option.
* **Server Monitor**:
    * Add and manage a list of servers to monitor.
    * Fetches and displays real-time server information (distro, kernel, uptime, CPU/RAM/Disk usage with progress bars).
    * Allows reordering of monitored servers via drag-and-drop.
* **YouTube Downloader (YT-DLP)**:
    * Download videos or audio from YouTube and other supported sites.
    * Select format (MP4, MP3) and video quality.
    * Downloaded files are saved to the user's cloud storage.
* **Image Upscaler**:
    * Upload images and upscale them by a selected factor (2x, 3x, 4x).
    * Upscaled images can be saved to the user's cloud storage.
* **GBA Emulator**:
    * Web-based Game Boy Advance emulator.
    * Load and play GBA ROMs (requires users to upload their ROMs locally).
    * I do not endorse piracy so only use roms you own.
    * GBA BIOS is not needed as the emulator doesn't need a GBA BIOS to work.

### 🖼️ Media Viewing
* **Photo Viewer**: Dedicated section to browse and view uploaded photos.
* **Video Player**: Dedicated section to browse and play uploaded videos.

### ⚙️ Administration
* **Admin Dashboard**: Central place for site administration.
* **User Management**:
    * List all registered users.
    * Edit user details (username, email, admin status, storage limits, max file size).
    * Disable/enable user accounts.
    * Reset user passwords.
* **Site Settings**:
    * Toggle new user registration.
    * Set default storage limits for new users.
    * Configure maximum single file upload size globally.
    * Configure Ollama API URL and model name.
    * Configure SMTP mail server settings for sending emails (password resets, notifications).

### 🎨 Theming & UI
* **Multiple Themes**: Users can select from available themes to customize their interface.
* **Responsive Design**: The interface is designed to work across different screen sizes.
* **Toast Notifications**: Non-intrusive feedback messages for user actions.
* **Dynamic Time Formatting**: Human-readable time ("2 hours ago") and localized timestamps.
