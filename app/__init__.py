# app/__init__.py
import os
import logging
from datetime import datetime, timezone
from humanize import naturaltime

from flask import Flask, g, url_for, current_app, session
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, current_user
from flask_wtf.csrf import CSRFProtect
from flask_mail import Mail
from flask_migrate import Migrate
from flask_socketio import SocketIO

# Import the configuration objects and default settings
from .config import config_by_name, DEFAULT_SETTINGS, AVAILABLE_THEMES

# Initialize extensions globally
db = SQLAlchemy()
login_manager = LoginManager()
csrf = CSRFProtect()
mail = Mail() # Flask-Mail instance
migrate = Migrate()
socketio = SocketIO(cors_allowed_origins="*", async_mode='threading', manage_session=True)

# LoginManager configuration
login_manager.login_view = 'auth.login'
login_manager.login_message_category = 'info'

# Helper function to ensure directories exist (moved to global scope for clarity)
def _ensure_directories_exist(app_instance):
    app_instance.logger.info("Ensuring all necessary directories exist...")
    dirs_to_create = [
        app_instance.instance_path, # From app object
        app_instance.config.get('UPLOAD_FOLDER'),
        app_instance.config.get('POST_MEDIA_FOLDER'),
        app_instance.config.get('STATIC_PROFILE_PICS_FOLDER'),
        app_instance.config.get('VIDEO_THUMBNAIL_FOLDER'),
        app_instance.config.get('YTDLP_TEMP_DOWNLOAD_FOLDER'),
        app_instance.config.get('UPSCALED_IMAGE_FOLDER'),
        app_instance.config.get('GIT_REPOSITORIES_ROOT'),
        app_instance.config.get('GBA_ROM_UPLOAD_FOLDER')
    ]
    for path in dirs_to_create:
        if path and not os.path.exists(path):
            try:
                os.makedirs(path, exist_ok=True)
                app_instance.logger.info(f"Created directory: {path}")
            except OSError as e:
                app_instance.logger.error(f"Failed to create directory {path}: {e}")
        elif path:
            app_instance.logger.debug(f"Directory already exists: {path}")
        else:
            app_instance.logger.warning("A directory path configured is None or empty.")


# Helper function to load mail config from DB/Defaults into app.config
def load_mail_settings_into_app_config(app_instance):
    from .models import Setting

    app_instance.logger.info("---- Mail Configuration Loading into app.config START ----")
    app_instance.logger.info(f"[Current app.config] MAIL_SERVER: {app_instance.config.get('MAIL_SERVER')}")
    app_instance.logger.info(f"[Current app.config] MAIL_PORT: {app_instance.config.get('MAIL_PORT')}")
    app_instance.logger.info(f"[Current app.config] MAIL_USE_TLS: {app_instance.config.get('MAIL_USE_TLS')}")
    app_instance.logger.info(f"[Current app.config] MAIL_USE_SSL: {app_instance.config.get('MAIL_USE_SSL')}")
    app_instance.logger.info(f"[Current app.config] MAIL_USERNAME (before DB): {app_instance.config.get('MAIL_USERNAME')}")
    app_instance.logger.info(f"[Current app.config] MAIL_PASSWORD is set (before DB): {bool(app_instance.config.get('MAIL_PASSWORD'))}")

    try:
        mail_server_val = Setting.get('MAIL_SERVER', DEFAULT_SETTINGS['MAIL_SERVER'])
        mail_port_val = int(Setting.get('MAIL_PORT', DEFAULT_SETTINGS['MAIL_PORT']))
        mail_use_tls_val = (Setting.get('MAIL_USE_TLS', DEFAULT_SETTINGS['MAIL_USE_TLS']).lower() == 'true')
        mail_use_ssl_val = (Setting.get('MAIL_USE_SSL', DEFAULT_SETTINGS['MAIL_USE_SSL']).lower() == 'true')

        # Explicitly log what Setting.get returns for username and password
        raw_mail_username_from_db = Setting.get('MAIL_USERNAME')
        raw_mail_password_from_db = Setting.get('MAIL_PASSWORD')

        mail_username_val = raw_mail_username_from_db if raw_mail_username_from_db is not None else DEFAULT_SETTINGS['MAIL_USERNAME']
        mail_password_val = raw_mail_password_from_db if raw_mail_password_from_db is not None else DEFAULT_SETTINGS['MAIL_PASSWORD']

        app_instance.logger.info(f"MAIL_USERNAME from DB (raw): '{raw_mail_username_from_db}'")
        app_instance.logger.info(f"MAIL_PASSWORD from DB is set (raw): {bool(raw_mail_password_from_db)}")
        app_instance.logger.info(f"MAIL_USERNAME effective value: '{mail_username_val}'")
        app_instance.logger.info(f"MAIL_PASSWORD effective value is set: {bool(mail_password_val)}")

        sender_name_db = Setting.get('MAIL_DEFAULT_SENDER_NAME', DEFAULT_SETTINGS['MAIL_DEFAULT_SENDER_NAME'])
        sender_email_db = Setting.get('MAIL_DEFAULT_SENDER_EMAIL', DEFAULT_SETTINGS['MAIL_DEFAULT_SENDER_EMAIL'])

        default_sender_val = None
        if sender_name_db and sender_email_db:
            default_sender_val = (sender_name_db, sender_email_db)
        elif sender_email_db:
            default_sender_val = sender_email_db
        else:
            default_sender_val = (DEFAULT_SETTINGS['MAIL_DEFAULT_SENDER_NAME'], DEFAULT_SETTINGS['MAIL_DEFAULT_SENDER_EMAIL'])

        app_instance.config.update(
            MAIL_SERVER=mail_server_val,
            MAIL_PORT=mail_port_val,
            MAIL_USE_TLS=mail_use_tls_val,
            MAIL_USE_SSL=mail_use_ssl_val,
            MAIL_USERNAME=mail_username_val,
            MAIL_PASSWORD=mail_password_val,
            MAIL_DEFAULT_SENDER=default_sender_val
        )
        app_instance.logger.info("Mail settings from DB/Defaults applied to app.config successfully.")
    except Exception as e:
        app_instance.logger.error(f"Error loading mail config from DB into app.config: {e}. Mail will use initial/env settings.", exc_info=True)

    app_instance.logger.info(f"[Final app.config] MAIL_SERVER: {app_instance.config.get('MAIL_SERVER')}")
    app_instance.logger.info(f"[Final app.config] MAIL_PORT: {app_instance.config.get('MAIL_PORT')}")
    app_instance.logger.info(f"[Final app.config] MAIL_USE_TLS: {app_instance.config.get('MAIL_USE_TLS')}")
    app_instance.logger.info(f"[Final app.config] MAIL_USE_SSL: {app_instance.config.get('MAIL_USE_SSL')}")
    app_instance.logger.info(f"[Final app.config] MAIL_USERNAME: {app_instance.config.get('MAIL_USERNAME')}")
    app_instance.logger.info(f"[Final app.config] MAIL_PASSWORD is set: {bool(app_instance.config.get('MAIL_PASSWORD'))}")
    app_instance.logger.info(f"[Final app.config] MAIL_DEFAULT_SENDER: {app_instance.config.get('MAIL_DEFAULT_SENDER')}")
    app_instance.logger.info("---- Mail Configuration Loading into app.config END ----")


def create_app(config_name=None):
    if config_name is None:
        config_name = os.getenv('FLASK_CONFIG', 'default')

    app = Flask(__name__, instance_path=config_by_name[config_name].INSTANCE_FOLDER_PATH)
    app.config.from_object(config_by_name[config_name]) # MAX_CONTENT_LENGTH is initially set here from Config object

    logging.basicConfig(level=logging.INFO if not app.debug else logging.DEBUG)
    app.logger.info(f"Flask app '{__name__}' created with config '{config_name}'")
    app.logger.info(f"Instance path: {app.instance_path}")

    db.init_app(app)

    from . import models # Ensure models are imported
    from .models import Setting, User # Ensure Setting is imported

    with app.app_context():
        _ensure_directories_exist(app)
        db.create_all()
        app.logger.info("Database tables checked/created.")

        # Seed default settings if not in DB
        for key, default_value in DEFAULT_SETTINGS.items():
            existing_setting = Setting.query.filter_by(key=key).first()
            if existing_setting is None:
                app.logger.info(f"Setting '{key}' not found in DB. Seeding with default: '{default_value}'.")
                Setting.set(key, default_value)
        db.session.commit() # Crucial: Commit seeded settings so Setting.get() can access them immediately

        load_mail_settings_into_app_config(app)

    mail.init_app(app) # Initialize mail AFTER app.config is finalized
    login_manager.init_app(app)
    csrf.init_app(app)
    migrate.init_app(app, db)
    socketio.init_app(app)

    app.logger.info(f"Upload folder (after all config): {app.config.get('UPLOAD_FOLDER')}")



    # User loader
    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))

    # Request hooks
    @app.before_request
    def before_request_handler():
        selected_theme_file = None
        theme_name = "default"
        if current_user.is_authenticated and hasattr(current_user, 'preferred_theme'):
            theme_name = getattr(current_user, 'preferred_theme', 'default')
        elif 'theme' in session:
            theme_name = session.get('theme', 'default')

        if theme_name != "default" and theme_name in AVAILABLE_THEMES:
            selected_theme_file = url_for('static', filename=f'css/themes/{theme_name}')
        g.selected_theme_css = selected_theme_file
        g.current_theme_name = theme_name

        if current_user.is_authenticated:
            current_user.last_seen = datetime.now(timezone.utc)
            current_user.is_online = True
            try:
                db.session.commit()
            except Exception as e_activity:
                db.session.rollback()
                app.logger.error(f"Error updating user activity for {current_user.id}: {e_activity}")
        session.permanent = True

    # Context processors
    @app.context_processor
    def inject_global_vars():
        theme_context = dict(
            selected_theme_css=getattr(g, 'selected_theme_css', None),
            current_theme_name=getattr(g, 'current_theme_name', 'default'),
            available_themes=AVAILABLE_THEMES
        )
        settings_ui = {}
        try: # Ensure Setting.get() is safe to call here (app_context should be fine)
            settings_ui['allow_registration'] = (Setting.get('allow_registration', DEFAULT_SETTINGS['allow_registration']) == 'true')
            ollama_url_db = Setting.get('ollama_api_url', DEFAULT_SETTINGS['ollama_api_url'])
            ollama_model_db = Setting.get('ollama_model', DEFAULT_SETTINGS['ollama_model'])
            settings_ui['ollama_enabled'] = bool(ollama_url_db and ollama_model_db)
            settings_ui['max_upload_mb'] = int(Setting.get('max_upload_size_mb', str(DEFAULT_SETTINGS['max_upload_size_mb'])))
        except Exception as e_ctx:
            app.logger.error(f"Error injecting settings into context: {e_ctx}")
            settings_ui['allow_registration'] = DEFAULT_SETTINGS['allow_registration'] == 'true'
            settings_ui['ollama_enabled'] = False
            settings_ui['max_upload_mb'] = int(DEFAULT_SETTINGS['max_upload_size_mb'])
        utility_context = dict(datetime=datetime, naturaltime=naturaltime, len=len)
        return {**theme_context, **utility_context, 'settings': settings_ui}

    # Jinja filters
    from .utils import time_since_filter, localetime_filter, get_language_color, human_readable_size_filter
    app.jinja_env.filters['timesince'] = time_since_filter
    app.jinja_env.filters['localetime'] = localetime_filter
    app.jinja_env.filters['language_color'] = get_language_color
    app.jinja_env.filters['humanreadable'] = human_readable_size_filter

    # After request hook
    @app.after_request
    def add_coop_coep_headers(response):
        response.headers['Cross-Origin-Opener-Policy'] = 'same-origin'
        response.headers['Cross-Origin-Embedder-Policy'] = 'require-corp'
        return response

    # Register Blueprints
    from .routes import main_routes, auth_routes, file_routes, note_routes, social_routes, chat_routes, tool_routes, git_routes, admin_routes
    from .routes.git_http_backend import git_http_bp # The new blueprint
    app.register_blueprint(main_routes.bp)
    app.register_blueprint(auth_routes.bp)
    app.register_blueprint(file_routes.bp)
    app.register_blueprint(note_routes.bp)
    app.register_blueprint(social_routes.bp)
    app.register_blueprint(chat_routes.bp)
    app.register_blueprint(tool_routes.bp)
    app.register_blueprint(git_routes.bp)
    app.register_blueprint(git_http_bp)
    app.register_blueprint(admin_routes.bp, url_prefix='/admin')

    # Register SocketIO event handlers
    from .routes.tool_routes import (
        handle_ssh_connect_request, handle_ssh_command,
        handle_ssh_disconnect_request, handle_ssh_resize,
        handle_socket_disconnect
    )
    socketio.on_event('ssh_connect_request', handle_ssh_connect_request)
    socketio.on_event('ssh_command', handle_ssh_command)
    socketio.on_event('ssh_disconnect_request', handle_ssh_disconnect_request)
    socketio.on_event('ssh_resize', handle_ssh_resize)
    socketio.on_event('disconnect', handle_socket_disconnect)

    app.logger.info("Flask app fully initialized and configured.")
    return app
