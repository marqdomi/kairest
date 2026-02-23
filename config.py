# config.py
import os
import secrets

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

    # Bump this whenever any static asset (CSS/JS) changes, to force browser reload
    VERSION = '5.5.0'

    # --- Redis ---
    REDIS_URL = os.getenv('REDIS_URL', 'redis://localhost:6379')

    # Flask-Session (server-side sessions via Redis)
    SESSION_TYPE = 'redis'
    SESSION_PERMANENT = False
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
