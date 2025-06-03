# app/config.py
import os
from datetime import timedelta

# --- Basic Configuration ---
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
DB_NAME = 'database.db'

# INSTANCE_FOLDER_PATH needs to be defined before it's used by Config class
INSTANCE_FOLDER_PATH = os.path.join(BASE_DIR, 'instance')

UPLOAD_FOLDER = os.path.join(INSTANCE_FOLDER_PATH, 'uploads')
POST_MEDIA_FOLDER = os.path.join(INSTANCE_FOLDER_PATH, 'uploads', 'post_media')
STATIC_POST_MEDIA_FOLDER = os.path.join(BASE_DIR, 'app', 'static', 'uploads', 'post_media')
STATIC_PROFILE_PICS_FOLDER = os.path.join(BASE_DIR, 'app', 'static', 'uploads', 'profile_pics')
VIDEO_THUMBNAIL_FOLDER = os.path.join(BASE_DIR, 'app', 'static', 'uploads', 'video_thumbnails')
UPSCALED_IMAGE_FOLDER = os.path.join(INSTANCE_FOLDER_PATH, 'uploads', 'upscaled_images')
YTDLP_TEMP_DOWNLOAD_FOLDER = os.path.join(INSTANCE_FOLDER_PATH, 'temp_ytdlp_downloads')
GIT_REPOSITORIES_ROOT = os.path.join(INSTANCE_FOLDER_PATH, "git_repositories")

# --- Default Settings (can be overridden by database AdminSettings/Setting model) ---
DEFAULT_SETTINGS = {
    'allow_registration': 'true',
    'default_storage_limit_mb': '1024',
    'max_upload_size_mb': '8192',
    'ollama_api_url': '',
    'ollama_model': 'llama3.2:3b',
    'MAIL_SERVER': 'smtp.gmail.com',
    'MAIL_PORT': '465',
    'MAIL_USE_TLS': 'false',
    'MAIL_USE_SSL': 'true',
    'MAIL_USERNAME': 'noreply@example.com',
    'MAIL_PASSWORD': '',
    'MAIL_DEFAULT_SENDER_NAME': 'PyCloud',
    'MAIL_DEFAULT_SENDER_EMAIL': 'noreply@example.com',
    'max_photo_upload_mb': '10',
    'max_video_upload_mb': '50',
}

DEFAULT_MAX_UPLOAD_MB_FALLBACK = 100
DEFAULT_MAX_PHOTO_MB = 10
DEFAULT_MAX_VIDEO_MB = 50

# --- Viewable & Editable File Types ---
VIEWABLE_IMAGE_MIMES = {'image/jpeg', 'image/png', 'image/gif', 'image/webp', 'image/svg+xml', 'image/bmp'}
VIEWABLE_VIDEO_MIMES = {'video/mp4', 'video/webm', 'video/ogg', 'video/mkv'}
VIEWABLE_AUDIO_MIMES = {'audio/mpeg', 'audio/ogg', 'audio/wav', 'audio/mp3'}
VIEWABLE_PDF_MIMES = {'application/pdf'}
VIEWABLE_MIMES = VIEWABLE_IMAGE_MIMES.union(VIEWABLE_VIDEO_MIMES).union(VIEWABLE_AUDIO_MIMES).union(VIEWABLE_PDF_MIMES)

EDITABLE_EXTENSIONS = {
    '', 'txt', 'md', 'markdown', 'json', 'yaml', 'yml', 'xml', 'csv', 'log',
    'py', 'js', 'css', 'html', 'htm', 'sh', 'bash', 'ps1', 'ini', 'cfg', 'conf', 'config',
    'sql', 'java', 'c', 'cpp', 'h', 'hpp', 'rb', 'php', 'pl', 'gitignore', 'dockerfile', 'env',
    'bat', 'cmd',
}

ALLOWED_EXTENSIONS_UPSCALER = {'png', 'jpg', 'jpeg', 'webp'}

AVAILABLE_THEMES = {
    "default": "Default (Dark)",
    "true_dark_blue.css": "True Dark Blue",
    "true_dark_orange.css": "True Dark Orange",
    "true_dark_red.css": "True Dark Red",
    "breeze_dark.css": "Breeze Dark",
    "breeze_light.css": "Breeze Light",
    "retro_wave_dark.css": "Retro Wave Dark",
    "retro_wave_light.css": "Retro Wave Light",
}

LANGUAGE_COLORS = {
    "Python": "#3572A5", "JavaScript": "#F1E05A", "HTML": "#E34C26", "CSS": "#563D7C",
    "Java": "#B07219", "Shell": "#89E051", "C++": "#F34B7D", "C": "#555555",
    "TypeScript": "#2B7489", "PHP": "#4F5D95", "Ruby": "#701516", "Go": "#00ADD8",
    "Swift": "#FFAC45", "Kotlin": "#F18E33", "Rust": "#DEA584", "Markdown": "#083FA1",
    "Vue": "#41B883", "Makefile": "#427819", "Dockerfile": "#384D54", "Other": "#DEA584"
}

LANGUAGE_EXTENSIONS_MAP = {
    '.py': 'Python', '.pyc': None, '.pyo': None, '.pyd': None, '.js': 'JavaScript', '.mjs': 'JavaScript',
    '.cjs': 'JavaScript', '.html': 'HTML', '.htm': 'HTML', '.css': 'CSS', '.java': 'Java', '.class': None,
    '.sh': 'Shell', '.bash': 'Shell', '.zsh': 'Shell', '.c': 'C', '.h': 'C', '.cpp': 'C++', '.hpp': 'C++',
    '.cxx': 'C++', '.hxx': 'C++', '.cc': 'C++', '.hh': 'C++', '.cs': 'C#', '.ts': 'TypeScript',
    '.tsx': 'TypeScript', '.php': 'PHP', '.rb': 'Ruby', '.go': 'Go', '.swift': 'Swift', '.kt': 'Kotlin',
    '.kts': 'Kotlin', '.rs': 'Rust', '.md': 'Markdown', '.markdown': 'Markdown', '.json': 'JSON',
    '.xml': 'XML', '.yaml': 'YAML', '.yml': 'YAML', '.vue': 'Vue', 'makefile': 'Makefile',
    'dockerfile': 'Dockerfile', '.png': None, '.jpg': None, '.jpeg': None, '.gif': None, '.bmp': None,
    '.tiff': None, '.svg': None, '.ico': None, '.webp': None, '.pdf': None, '.doc': None, '.docx': None,
    '.xls': None, '.xlsx': None, '.ppt': None, '.pptx': None, '.odt': None, '.ods': None, '.odp': None,
    '.zip': None, '.tar': None, '.gz': None, '.rar': None, '.7z': None, '.bz2': None, '.xz': None,
    '.exe': None, '.dll': None, '.so': None, '.dylib': None, '.o': None, '.a': None, '.lib': None,
    '.obj': None, '.mp3': None, '.wav': None, '.aac': None, '.flac': None, '.mp4': None, '.mov': None,
    '.avi': None, '.mkv': None, '.webm': None, '.ttf': None, '.otf': None, '.woff': None, '.woff2': None,
    '.eot': None, '.DS_Store': None, '.db': None, '.sqlite': None, '.sqlite3': None, '.log': None,
    '.bak': None, '.tmp': None, '.swp': None, '.lock': None, '.sum': None, '.js.map': None, '.css.map': None,
}

IGNORE_PATTERNS_FOR_STATS = {
    '.git/', 'node_modules/', 'bower_components/', 'vendor/', 'venv/', 'env/', '.venv/', '.env/',
    '__pycache__/', '.pytest_cache/', '.mypy_cache/', '.tox/', '.idea/', '.vscode/', '.settings/',
    'build/', 'dist/', 'target/', 'out/', 'bin/', 'obj/', 'coverage/', 'docs/', 'examples/',
    'test/', 'tests/', '.gitignore', '.gitattributes', '.editorconfig', '.eslintignore',
    '.eslintrc.js', '.eslintrc.json', '.eslintrc.yaml', '.eslintrc.yml', '.prettierrc',
    '.prettierignore', 'license', 'licence', 'copying', 'readme', 'contributing', 'changelog',
    'package.json', 'package-lock.json', 'composer.json', 'composer.lock', 'go.mod', 'go.sum',
    'gemfile', 'gemfile.lock', 'requirements.txt', 'pipfile', 'pipfile.lock', 'pyproject.toml',
    'webpack.config.js', 'babel.config.js', 'tsconfig.json'
}

class Config:
    SECRET_KEY = os.urandom(24)
    INSTANCE_FOLDER_PATH = INSTANCE_FOLDER_PATH
    SQLALCHEMY_DATABASE_URI = f'sqlite:///{os.path.join(INSTANCE_FOLDER_PATH, DB_NAME)}'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    PERMANENT_SESSION_LIFETIME = timedelta(days=7)

    UPLOAD_FOLDER = UPLOAD_FOLDER
    GIT_REPOSITORIES_ROOT = GIT_REPOSITORIES_ROOT
    GIT_EXECUTABLE_PATH = "git"

    VIEWABLE_MIMES = VIEWABLE_MIMES
    EDITABLE_EXTENSIONS = EDITABLE_EXTENSIONS

    MAIL_SERVER = os.environ.get('MAIL_SERVER') or 'smtp.gmail.com'
    MAIL_PORT = int(os.environ.get('MAIL_PORT') or 587)
    MAIL_USE_TLS = os.environ.get('MAIL_USE_TLS', 'true').lower() in ['true', 'on', '1']
    MAIL_USE_SSL = os.environ.get('MAIL_USE_SSL', 'false').lower() in ['true', 'on', '1']
    MAIL_USERNAME = os.environ.get('MAIL_USERNAME')
    MAIL_PASSWORD = os.environ.get('MAIL_PASSWORD')
    MAIL_DEFAULT_SENDER = os.environ.get('MAIL_DEFAULT_SENDER') or MAIL_USERNAME


    GBA_ROM_UPLOAD_FOLDER = os.path.join(INSTANCE_FOLDER_PATH, 'uploads', 'gba_roms')
    MAX_CONTENT_LENGTH = int(DEFAULT_SETTINGS['max_upload_size_mb']) * 1024 * 1024
    # Static asset folders (can be useful if accessed via app.config in templates or routes)
    STATIC_PROFILE_PICS_FOLDER = STATIC_PROFILE_PICS_FOLDER
    VIDEO_THUMBNAIL_FOLDER = VIDEO_THUMBNAIL_FOLDER
    POST_MEDIA_FOLDER = POST_MEDIA_FOLDER # From original main.py, if serving from instance
    STATIC_POST_MEDIA_FOLDER = STATIC_POST_MEDIA_FOLDER # If serving from static

class DevelopmentConfig(Config):
    DEBUG = True
    SQLALCHEMY_ECHO = False

class ProductionConfig(Config):
    DEBUG = False


config_by_name = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'default': DevelopmentConfig
}
