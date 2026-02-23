# backend/extensions.py
import os

from flask_socketio import SocketIO
from flask_login import LoginManager
from flask_cors import CORS
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_wtf.csrf import CSRFProtect
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_caching import Cache
from flask_session import Session

migrate = Migrate()
login_manager = LoginManager()
cors = CORS()
db = SQLAlchemy()

# Socket.IO — orígenes restringidos desde config (fallback dev)
_cors_origins = os.getenv('CORS_ORIGINS', 'http://localhost:5005').split(',')
socketio = SocketIO(cors_allowed_origins=_cors_origins)

csrf = CSRFProtect()

_redis_url = os.getenv('REDIS_URL', '')
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["200 per minute"],
    storage_uri=(_redis_url + '/0') if _redis_url else 'memory://',
)
cache = Cache()
server_session = Session()
