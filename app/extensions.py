"""Shared extension instances.

These are initialized without an app and later bound via init_app()
inside the application factory, avoiding circular imports.
"""

from flask_sqlalchemy import SQLAlchemy
from flask_socketio import SocketIO
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_migrate import Migrate

db = SQLAlchemy()
socketio = SocketIO()
cors = CORS()
limiter = Limiter(key_func=get_remote_address)
migrate = Migrate()
