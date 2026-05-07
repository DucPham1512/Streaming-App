"""Entry point — runs the Flask-SocketIO development server."""

import os

from app import create_app
from app.extensions import socketio

app = create_app()

if __name__ == "__main__":
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "5001"))
    socketio.run(app, host=host, port=port, debug=True)
