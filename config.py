# config.py
import os
import secrets
from datetime import timedelta

basedir = os.path.abspath(os.path.dirname(__file__))


class Config:
    # SECRET_KEY: obligatoria en producción, auto-generada solo en desarrollo
    SECRET_KEY = os.getenv('SECRET_KEY')
    if not SECRET_KEY:
        if os.getenv('FLASK_ENV') == 'production':
            raise RuntimeError(
                'SECRET_KEY no configurada. Genera una con: '
                'python -c "import secrets; print(secrets.token_hex(32))"'
            )
        SECRET_KEY = secrets.token_hex(32)

    SQLALCHEMY_DATABASE_URI = os.getenv(
        'DATABASE_URL',
        'postgresql://casaleones:casaleones_secret@localhost:5432/casaleones'
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Connection pooling (Sprint 2 — 2.4) — only for non-SQLite
    if 'sqlite' not in SQLALCHEMY_DATABASE_URI:
        SQLALCHEMY_ENGINE_OPTIONS = {
            'pool_size': int(os.getenv('DB_POOL_SIZE', '5')),
            'max_overflow': int(os.getenv('DB_MAX_OVERFLOW', '10')),
            'pool_recycle': int(os.getenv('DB_POOL_RECYCLE', '1800')),
            'pool_pre_ping': True,
            'pool_timeout': int(os.getenv('DB_POOL_TIMEOUT', '30')),
        }
    else:
        SQLALCHEMY_ENGINE_OPTIONS = {}

    # El token CSRF no caduca por tiempo, sólo con la sesión. El default de Flask-WTF
    # (3600 s) rompía las pantallas que se quedan abiertas todo el turno: el KDS sólo
    # refresca fragmentos, así que a la hora su token (el de la carga de la página) ya
    # no valía y cada "listo" regresaba 400. El token sigue atado a la sesión y se
    # valida igual; sólo se quita el reloj.
    WTF_CSRF_TIME_LIMIT = None

    # Versión ÚNICA del producto: se muestra en el sidebar del admin y es el `?v=` de
    # todos los CSS/JS. Subirla en cada release — si no, una tablet con caché sigue con
    # los estilos viejos después de update.sh (estuvo congelada en 5.5.0 hasta v6.8).
    VERSION = '6.8.0'

    # ── Compresión de respuestas ──
    # Los estáticos viajaban sin comprimir (lucide.min.js son 356 KB en crudo).
    # Se listan br y gzip: brotli comprime más, pero los WebView viejos de gama
    # baja no lo soportan y sin gzip de respaldo se quedaban sin comprimir.
    COMPRESS_ALGORITHM = ['br', 'gzip', 'deflate']
    # Los estáticos se sirven en streaming y usan su propia lista; sin gzip aquí,
    # un navegador que sólo pida gzip se queda sin comprimir.
    COMPRESS_ALGORITHM_STREAMING = ['br', 'gzip', 'deflate']
    COMPRESS_MIMETYPES = [
        'text/html', 'text/css', 'text/xml', 'text/plain',
        'application/json', 'application/javascript', 'text/javascript',
        'image/svg+xml',
    ]
    COMPRESS_MIN_SIZE = 500
    COMPRESS_LEVEL = 6


    # --- Redis ---
    REDIS_URL = os.getenv('REDIS_URL', 'redis://localhost:6379')

    # Flask-Session (server-side sessions via Redis)
    SESSION_TYPE = 'redis'
    # Permanente = la cookie lleva fecha y sobrevive al cierre del navegador. La vigencia
    # real (por rol, renovada con el uso) la controla services/sesion.py; esto es el tope.
    SESSION_PERMANENT = True
    PERMANENT_SESSION_LIFETIME = timedelta(days=30)
    REMEMBER_COOKIE_DURATION = timedelta(days=30)
    SESSION_KEY_PREFIX = 'casaleones:session:'

    # Flask-Caching (Redis backend)
    CACHE_TYPE = 'RedisCache'
    CACHE_REDIS_URL = os.getenv('CACHE_REDIS_URL', 'redis://localhost:6379/2')
    CACHE_DEFAULT_TIMEOUT = 300

    # CORS — dominios permitidos (separados por coma en producción)
    CORS_ORIGINS = os.getenv('CORS_ORIGINS', 'http://localhost:5005').split(',')

    # Webhook secrets para delivery
    UBER_EATS_WEBHOOK_SECRET = os.getenv('UBER_EATS_WEBHOOK_SECRET', '')
    RAPPI_WEBHOOK_KEY = os.getenv('RAPPI_WEBHOOK_KEY', '')
    DIDI_WEBHOOK_SECRET = os.getenv('DIDI_WEBHOOK_SECRET', '')

    # Validación de stock al agregar productos
    INVENTARIO_VALIDAR_STOCK = os.getenv('INVENTARIO_VALIDAR_STOCK', 'false').lower() == 'true'

    # Sólo para desarrollo local: la sonda de salud del preview hace HEAD / varias
    # veces por segundo desde 127.0.0.1 y agota el límite global de 200/min.
    RATELIMIT_ENABLED = os.getenv('RATELIMIT_ENABLED', 'true').lower() != 'false'

    # Sprint 3 — Impresión ESC/POS
    PRINTER_TYPE = os.getenv('PRINTER_TYPE', 'none')  # none, usb, network
    PRINTER_HOST = os.getenv('PRINTER_HOST', '192.168.1.100')
    PRINTER_PORT = int(os.getenv('PRINTER_PORT', '9100'))
    AUTO_PRINT_COMANDA = os.getenv('AUTO_PRINT_COMANDA', 'false').lower() == 'true'

    # Sprint 3 — Facturapi CFDI
    FACTURAPI_KEY = os.getenv('FACTURAPI_KEY', '')
    FACTURAPI_URL = os.getenv('FACTURAPI_URL', 'https://www.facturapi.io/v2')

    # ── Modo sistema: módulos visibles por modo ──
    # basico: solo lo esencial para operar un puesto pequeño
    # avanzado: todas las funcionalidades habilitadas
    MODULOS_BASICOS = {
        'dashboard', 'operaciones', 'catalogo', 'ventas',
    }
    MODULOS_AVANZADOS = {
        'dashboard', 'operaciones', 'catalogo', 'inventario',
        'ventas', 'crm', 'fiscal', 'configuracion',
    }


class DevelopmentConfig(Config):
    """Configuración para desarrollo local."""
    DEBUG = True
    if 'sqlite' not in Config.SQLALCHEMY_DATABASE_URI:
        SQLALCHEMY_ENGINE_OPTIONS = {
            **Config.SQLALCHEMY_ENGINE_OPTIONS,
            'pool_size': 2,
            'max_overflow': 3,
        }


class ProductionConfig(Config):
    """Configuración para producción (gunicorn + Docker)."""
    DEBUG = False
    SESSION_COOKIE_SECURE = True
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    if 'sqlite' not in Config.SQLALCHEMY_DATABASE_URI:
        SQLALCHEMY_ENGINE_OPTIONS = {
            **Config.SQLALCHEMY_ENGINE_OPTIONS,
            'pool_size': int(os.getenv('DB_POOL_SIZE', '10')),
            'max_overflow': int(os.getenv('DB_MAX_OVERFLOW', '20')),
        }


config_by_name = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'default': Config,
}
