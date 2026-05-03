"""Shared extension instances.

These are initialized without an app and later bound via init_app()
inside the application factory, avoiding circular imports.
"""

from flask_sqlalchemy import SQLAlchemy
from flask_socketio import SocketIO
from flask_cors import CORS

db = SQLAlchemy()
socketio = SocketIO()
cors = CORS()
