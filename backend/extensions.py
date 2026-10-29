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
from flask_compress import Compress

migrate = Migrate()
login_manager = LoginManager()
cors = CORS()
db = SQLAlchemy()

# Socket.IO — orígenes restringidos desde config (fallback dev)
# Use eventlet in production (gunicorn --worker-class eventlet), threading in dev/tests
_cors_origins = os.getenv('CORS_ORIGINS', 'http://localhost:5005').split(',')


def _detect_async_mode():
    """Auto-detect best async mode: eventlet if monkey-patched, else threading."""
    try:
        import eventlet.patcher
        if eventlet.patcher.is_monkey_patched('socket'):
            return 'eventlet'
    except (ImportError, AttributeError):
        pass
    return 'threading'


def _origen_socket_permitido(origin, environ):
    """Mismo origen siempre, más los de CORS_ORIGINS.

    Con sólo la lista, una tablet que abre el sistema por la IP de la red
    (http://192.168.x.x:5005) era rechazada con 400 en el handshake: la página cargaba
    pero nunca llegaban los avisos en tiempo real. Lo mismo con el dominio en la nube.
    La página que sirvió este mismo servidor no es un riesgo de cross-site.
    """
    if not origin:
        return True  # cliente sin navegador (no manda Origin)
    if origin in _cors_origins:
        return True
    host = environ.get('HTTP_X_FORWARDED_HOST', environ.get('HTTP_HOST', '')).split(',')[0].strip()
    scheme = environ.get('HTTP_X_FORWARDED_PROTO', environ.get('wsgi.url_scheme', 'http')).split(',')[0].strip()
    return bool(host) and origin == f'{scheme}://{host}'


socketio = SocketIO(cors_allowed_origins=_origen_socket_permitido, async_mode=_detect_async_mode())

csrf = CSRFProtect()

_redis_url = os.getenv('REDIS_URL', '')
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["200 per minute"],
    storage_uri=(_redis_url + '/0') if _redis_url else 'memory://',
)
cache = Cache()
server_session = Session()
# Compresión gzip/brotli: los estáticos viajaban sin comprimir (lucide.min.js son
# 356 KB en crudo). Pesa sobre todo en celulares de gama baja con datos móviles.
compress = Compress()
