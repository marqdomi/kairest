"""Pytest configuration — CasaLeones POS test suite."""
import os
import pytest

# Use SQLite in-memory for tests — must be before importing app
os.environ['DATABASE_URL'] = 'sqlite://'
os.environ['FLASK_ENV'] = 'development'
os.environ['REDIS_URL'] = ''  # Disable Redis in tests
os.environ['TESTING'] = '1'

from backend.app import create_app
from backend.extensions import db as _db


@pytest.fixture(scope='session')
def app():
    """Create a Flask app configured for testing."""
    os.environ['REDIS_URL'] = ''  # Disable Redis in tests
    app = create_app()
    app.config.update({
        'TESTING': True,
        'WTF_CSRF_ENABLED': False,
        'SQLALCHEMY_DATABASE_URI': 'sqlite://',
        'SQLALCHEMY_ENGINE_OPTIONS': {},
        'SESSION_TYPE': 'filesystem',
        'SESSION_REDIS': None,
        'CACHE_TYPE': 'NullCache',
        'RATELIMIT_ENABLED': False,
        'RATELIMIT_STORAGE_URI': 'memory://',
        'SERVER_NAME': 'localhost',
    })
    # Disable rate limiter programmatically (it ignores config after init)
    from backend.extensions import limiter
    limiter.enabled = False
    yield app


@pytest.fixture(scope='function')
def db(app):
    """Create fresh database tables for each test."""
    with app.app_context():
        _db.create_all()
        yield _db
        _db.session.rollback()
        _db.drop_all()


@pytest.fixture
def client(app, db):
    """Test client with clean database."""
    with app.test_client() as client:
        yield client


# ---------------------------------------------------------------------------
# Helper: create a valid Usuario (current ORM uses email, not username)
# ---------------------------------------------------------------------------
def _make_user(db, nombre, email, password, rol):
    """Create and persist a Usuario with current ORM fields."""
    from backend.models.models import Usuario
    user = Usuario(nombre=nombre, email=email, rol=rol)
    user.set_password(password)
    db.session.add(user)
    db.session.commit()
    return user


@pytest.fixture
def admin_user(db):
    """Create and return an admin user."""
    return _make_user(db, 'Admin Test', 'admin_test@test.com', 'Test1234!', 'admin')


@pytest.fixture
def mesero_user(db):
    """Create and return a mesero user."""
    return _make_user(db, 'Mesero Test', 'mesero_test@test.com', 'Test1234!', 'mesero')


@pytest.fixture
def superadmin_user(db):
    """Create and return a superadmin user."""
    return _make_user(db, 'Super Admin', 'super_test@test.com', 'Test1234!', 'superadmin')


# ---------------------------------------------------------------------------
# Helper: create Categoria + Producto (Producto requires FK to Categoria)
# ---------------------------------------------------------------------------
@pytest.fixture
def sample_categoria(db):
    """Create a sample Categoria."""
    from backend.models.models import Categoria
    cat = Categoria(nombre='tacos')
    db.session.add(cat)
    db.session.commit()
    return cat


@pytest.fixture
def sample_producto(db, sample_categoria):
    """Create a sample product (requires Categoria FK)."""
    from backend.models.models import Producto
    prod = Producto(
        nombre='Taco al Pastor',
        precio=45.00,
        categoria_id=sample_categoria.id,
    )
    db.session.add(prod)
    db.session.commit()
    return prod


@pytest.fixture
def sample_mesa(db):
    """Create a sample table (Mesa.numero is String)."""
    from backend.models.models import Mesa
    mesa = Mesa(
        numero='1',
        capacidad=4,
        zona='interior',
        estado='disponible',
    )
    db.session.add(mesa)
    db.session.commit()
    return mesa


def login(client, email, password):
    """Helper to log in a user via the test client (uses email field)."""
    return client.post('/login', data={
        'email': email,
        'password': password,
    }, follow_redirects=True)
