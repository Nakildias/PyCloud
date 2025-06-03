import os

from app import create_app, socketio, db
from app.models import AdminSettings

# Get the configuration name from an environment variable or use default
config_name = os.getenv('FLASK_CONFIG', 'default')

# Create the Flask app instance using the factory
app = create_app(config_name)

if __name__ == '__main__':
    # Use socketio.run() to correctly run a Flask-SocketIO application
    # The host and port can be configured as needed.
    # allow_unsafe_werkzeug=True is for development with newer Werkzeug versions if you encounter issues with reloader.
    # In production, you'd typically use a proper WSGI server like Gunicorn or uWSGI.
    print("INFO: Starting Flask-SocketIO development server from run.py...")
    socketio.run(app,
                 debug=app.config.get('DEBUG', True), # Use debug status from app config
                 host='0.0.0.0',
                 port=int(os.getenv('PORT', 8080)), # Allow port to be set by env var
                 allow_unsafe_werkzeug=True # For development reloader with SocketIO
                )
