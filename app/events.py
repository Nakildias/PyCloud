# in app/events.py

from flask import request, current_app
from flask_login import current_user
from . import socketio

@socketio.on('connect')
def handle_connect():
    """
    Handles a new global namespace connection from a client.
    This function is required to gracefully accept the connection initiated in base.html.
    """
    if current_user.is_authenticated:
        current_app.logger.info(f"Socket.IO Client connected: {current_user.username} (sid: {request.sid})")
    else:
        current_app.logger.info(f"Socket.IO Anonymous client connected (sid: {request.sid})")

@socketio.on('disconnect')
def handle_disconnect():
    """
    Handles a client disconnecting.
    """
    # This handler is not strictly necessary to fix the error, but it's good practice to have.
    if current_user.is_authenticated:
        # It's possible for current_user to be anonymous here if the session is cleared before disconnect.
        current_app.logger.info(f"Socket.IO Client disconnected: {current_user.username or 'Unknown User'} (sid: {request.sid})")
    else:
        current_app.logger.info(f"Socket.IO Anonymous client disconnected (sid: {request.sid})")

def handle_global_connect():
    """
    Handles the global 'connect' event from clients.
    This gracefully accepts the connection initiated in base.html.
    """
    if current_user.is_authenticated:
        current_app.logger.info(f"Socket.IO Client connected: {current_user.username} (sid: {request.sid})")
    else:
        current_app.logger.info(f"Socket.IO Anonymous client connected (sid: {request.sid})")
