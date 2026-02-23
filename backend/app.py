import os
import sys
import secrets
import logging
from flask_migrate import Migrate

# Add the project root to Python path so the 'backend' package can be found
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from flask import Flask, g, request as flask_request

from backend.models.models import Usuario
from backend.models.database import init_db
from backend.extensions import db, socketio, login_manager, cors, csrf, limiter, cache, server_session
from backend.routes.auth import auth_bp
from backend.routes.cocina import cocina_bp
from backend.routes.meseros import meseros_bp
from backend.routes.admin_routes import admin_bp
from backend.routes.api import api_bp
from backend.routes.orders import orders_bp
from backend.routes.ventas import ventas_bp
from backend.routes.productos import productos_bp
# Fase 3
from backend.routes.inventario import inventario_bp
from backend.routes.reportes import reportes_bp
from backend.routes.facturacion import facturacion_bp
from backend.routes.clientes import clientes_bp
from backend.routes.reservaciones import reservaciones_bp
# Fase 4
from backend.routes.delivery import delivery_bp
from backend.routes.sucursales import sucursales_bp
# Sprint 6
from backend.routes.auditoria import auditoria_bp
# Onboarding
from backend.routes.setup import setup_bp

# ---------------------------------------------------------------------------
# Logging configuration
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
)
logger = logging.getLogger(__name__)

login_manager.login_view = 'auth.login'


def load_user(user_id):
    return Usuario.query.get(int(user_id))


def create_app():
    app = Flask(__name__, template_folder='templates', static_folder='static')

    # Load configuration
    env = os.getenv('FLASK_ENV', 'development')
    from config import config_by_name
    app.config.from_object(config_by_name.get(env, config_by_name['default']))

    @app.route('/')
    def index():
        from flask import redirect, url_for
        return redirect(url_for('auth.login'))

    # Development settings
    if app.config.get('DEBUG') or os.getenv('FLASK_ENV') == 'development':
        app.config['DEBUG'] = True
        app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0
        app.config['TEMPLATES_AUTO_RELOAD'] = True
        app.jinja_env.auto_reload = True

    # Extensions
    cors.init_app(app, resources={
        r"/api/*": {"origins": app.config.get('CORS_ORIGINS', ['http://localhost:5005'])},
    })
    db.init_app(app)
    Migrate(app, db)
    login_manager.init_app(app)
    socketio.init_app(app)
    csrf.init_app(app)
    limiter.init_app(app)
    cache.init_app(app)

    # Flask-Session (Redis server-side sessions)
    redis_url = app.config.get('REDIS_URL', '')
    if redis_url:
        import redis as _redis
        app.config['SESSION_REDIS'] = _redis.from_url(redis_url + '/1')
    else:
        app.config['SESSION_TYPE'] = 'filesystem'
    server_session.init_app(app)

    # Sentry (Fase 4 - Item 25)
    sentry_dsn = os.getenv('SENTRY_DSN', '')
    if sentry_dsn:
        import sentry_sdk
        from sentry_sdk.integrations.flask import FlaskIntegration
        sentry_sdk.init(dsn=sentry_dsn, integrations=[FlaskIntegration()],
                        traces_sample_rate=float(os.getenv('SENTRY_TRACES_RATE', '0.1')))
        logger.info('Sentry inicializado.')

    # ---- CSP nonce (generated per-request) ----
    @app.before_request
    def _set_csp_nonce():
        g.csp_nonce = secrets.token_hex(16)

    # ---- Onboarding redirect: force setup wizard if not completed ----
    @app.before_request
    def _check_onboarding():
        from backend.models.models import ConfiguracionSistema
        # Skip for static files, health, and setup itself
        if flask_request.endpoint and (
            flask_request.endpoint.startswith('setup.') or
            flask_request.endpoint == 'static' or
            flask_request.endpoint == 'health_check'
        ):
            return
        try:
            if not ConfiguracionSistema.get_bool('onboarding_completado', False):
                from flask import redirect, url_for
                return redirect(url_for('setup.index'))
        except Exception:
            pass  # Table may not exist yet during migrations

    # ---- Multi-sucursal: inyectar sucursal activa (Sprint 2 — 2.2) ----
    @app.before_request
    def _set_sucursal_activa():
        from flask import session as flask_session
        g.sucursal_id = flask_session.get('sucursal_id')  # None = "Todas"

    # Inject nonce into all templates
    @app.context_processor
    def _inject_csp_nonce():
        return dict(csp_nonce=getattr(g, 'csp_nonce', ''))

    # Inject modo_sistema for sidebar/navbar filtering
    @app.context_processor
    def _inject_modo_sistema():
        try:
            from backend.models.models import ConfiguracionSistema
            modo = ConfiguracionSistema.get('modo_sistema', 'basico')
        except Exception:
            modo = 'basico'
        return dict(modo_sistema=modo)

    # Inject branding for white-label support
    @app.context_processor
    def _inject_branding():
        from flask import url_for as _url_for
        try:
            from backend.models.models import Sucursal
            sucursal = Sucursal.query.first()
            brand_name = sucursal.nombre if sucursal else 'KaiRest'
            brand_logo = getattr(sucursal, 'logo_url', None) or _url_for(
                'static', filename='img/kairest-logo.svg')
        except Exception:
            brand_name = 'KaiRest'
            brand_logo = _url_for('static', filename='img/kairest-logo.svg')
        return dict(
            brand_name=brand_name,
            brand_logo=brand_logo,
            product_name='KaiRest',
        )

    # Custom Jinja filter for Next-Gen money formatting
    @app.template_filter('money')
    def format_money(amount):
        if amount is None:
            return '<span class="cl-money"><span class="cl-money-symbol">$</span>0<span class="cl-money-decimal">.00</span></span>'
        amount_str = f"{float(amount):,.2f}"
        parts = amount_str.split('.')
        enteros = parts[0]
        decimales = parts[1]
        return f'<span class="cl-money"><span class="cl-money-symbol">$</span>{enteros}<span class="cl-money-decimal">.{decimales}</span></span>'

    # Security headers (Fase 4 - Item 24) + CSP (Fase 5 - Sprint 1)
    @app.after_request
    def set_security_headers(response):
        nonce = getattr(g, 'csp_nonce', '')
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'SAMEORIGIN'
        response.headers['X-XSS-Protection'] = '1; mode=block'
        response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        response.headers['Permissions-Policy'] = 'camera=(), microphone=(), geolocation=()'
        # Content Security Policy
        csp = (
            f"default-src 'self'; "
            f"script-src 'self' 'nonce-{nonce}' cdn.jsdelivr.net cdnjs.cloudflare.com; "
            f"style-src 'self' 'unsafe-inline' cdn.jsdelivr.net; "
            f"img-src 'self' data:; "
            f"connect-src 'self' ws: wss:; "
            f"font-src 'self' cdn.jsdelivr.net; "
            f"frame-ancestors 'none'; "
            f"base-uri 'self'; "
            f"form-action 'self';"
        )
        response.headers['Content-Security-Policy'] = csp
        if not app.debug:
            response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
        return response

    # Exempt API blueprints from CSRF (they use JSON, not forms)
    csrf.exempt(api_bp)
    csrf.exempt(orders_bp)
    csrf.exempt(ventas_bp)
    csrf.exempt(setup_bp)

    login_manager.user_loader(load_user)

    with app.app_context():
        init_db()

    # Register blueprints
    app.register_blueprint(auth_bp)
    app.register_blueprint(cocina_bp, url_prefix="/cocina")
    app.register_blueprint(meseros_bp, url_prefix='/meseros')
    app.register_blueprint(admin_bp, url_prefix='/admin')
    app.register_blueprint(api_bp)
    app.register_blueprint(orders_bp)
    app.register_blueprint(ventas_bp)
    app.register_blueprint(productos_bp, url_prefix='/admin/productos')
    # Fase 3
    app.register_blueprint(inventario_bp)
    app.register_blueprint(reportes_bp)
    app.register_blueprint(facturacion_bp)
    app.register_blueprint(clientes_bp)
    app.register_blueprint(reservaciones_bp)

    # Fase 4
    app.register_blueprint(delivery_bp)
    app.register_blueprint(sucursales_bp)
    # Sprint 6
    app.register_blueprint(auditoria_bp)
    # Onboarding
    app.register_blueprint(setup_bp)

    # Exempt API routes from CSRF
    csrf.exempt(inventario_bp)
    csrf.exempt(clientes_bp)
    csrf.exempt(delivery_bp)

    # Rate limiting — rutas sensibles (Fase 4 - Item 24)
    limiter.limit("10 per minute")(auth_bp)
    limiter.limit("30 per minute")(delivery_bp)

    # Health check (Fase 4 - Item 25 + Sprint 2 pool stats)
    @app.route('/health')
    def health_check():
        from flask import jsonify as jf
        try:
            db.session.execute(db.text('SELECT 1'))
            db_ok = True
        except Exception:
            db_ok = False

        # Connection pool stats
        pool_info = {}
        try:
            pool = db.engine.pool
            pool_info = {
                'pool_size': pool.size(),
                'checked_in': pool.checkedin(),
                'checked_out': pool.checkedout(),
                'overflow': pool.overflow(),
            }
        except Exception:
            pass

        return jf(status='ok' if db_ok else 'degraded', db=db_ok,
                   pool=pool_info,
                   version=app.config.get('VERSION', '?')), 200 if db_ok else 503

    logger.info('App creada — blueprints registrados.')
    return app


def _get_app():
    """Get or create the app (called at module level for gunicorn/socketio)."""
    if os.getenv('TESTING'):
        return None
    return create_app()


app = _get_app()

if __name__ == "__main__":
    if app is None:
        app = create_app()
    socketio.run(app, debug=True, use_reloader=False, host='0.0.0.0', port=5005)
