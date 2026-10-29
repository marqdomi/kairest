"""Prueba manual de concurrencia contra PostgreSQL real (SQLite ignora FOR UPDATE).

8 toques simultáneos al mismo producto de una orden nueva. Esperado:
    renglones=1 cantidades=[8] total=8   y la orden con folio 1

Antes del lock en add_product_to_order se perdían cantidades (total=3), y antes del
refresh en asignar_folio cada toque quemaba un folio (la orden quedaba con el 4).

Uso (con el stack de docker-compose arriba, DB expuesta en 5433):
    docker compose exec db psql -U casaleones -c "create database concurrencia"
    ./.venv/bin/python scripts/prueba_concurrencia_pg.py
BORRA Y RECREA las tablas de la base `concurrencia` (no toca la del negocio).
"""
import os, sys, threading
os.environ['DATABASE_URL'] = os.getenv('PG_CONCURRENCIA_URL', 'postgresql://casaleones:casaleones_secret@localhost:5433/concurrencia')
os.environ['REDIS_URL'] = ''
os.environ['RATELIMIT_ENABLED'] = 'false'
sys.path.insert(0, os.getcwd())
from backend.app import create_app
from backend.extensions import db, limiter
app = create_app()
app.config.update(WTF_CSRF_ENABLED=False, SESSION_TYPE='filesystem', CACHE_TYPE='NullCache')
limiter.enabled = False
from backend.models.models import Usuario, Mesa, Producto, Categoria, Estacion, Orden, OrdenDetalle, ConfiguracionSistema
N = 8
with app.app_context():
    db.drop_all(); db.create_all()
    ConfiguracionSistema.set('onboarding_completado', 'true')
    est = Estacion(nombre='Taquero'); cat = Categoria(nombre='Tacos'); db.session.add_all([est, cat]); db.session.commit()
    p = Producto(nombre='Taco de maciza', precio=35, categoria_id=cat.id, estacion_id=est.id)
    u = Usuario(nombre='M', email='m@t.test', rol='mesero'); u.set_password('Test1234!')
    m = Mesa(numero='1', capacidad=4, estado='disponible')
    db.session.add_all([p, u, m]); db.session.commit()
    o = Orden(mesa_id=m.id, mesero_id=u.id, estado='pendiente'); db.session.add(o); db.session.commit()
    oid, pid = o.id, p.id
clients = []
for _ in range(N):
    c = app.test_client(); c.post('/login', data={'email': 'm@t.test', 'password': 'Test1234!'}); clients.append(c)
barrier = threading.Barrier(N); codes = []
def tocar(c):
    barrier.wait()
    codes.append(c.post(f'/api/ordenes/{oid}/detalle', json={'producto_id': pid, 'cantidad': 1}).status_code)
ts = [threading.Thread(target=tocar, args=(c,)) for c in clients]
[t.start() for t in ts]; [t.join() for t in ts]
with app.app_context():
    rows = [(d.cantidad) for d in OrdenDetalle.query.filter_by(orden_id=oid).all()]
    folio = db.session.get(Orden, oid).folio
print(f'folio={folio} respuestas={sorted(codes)} renglones={len(rows)} cantidades={rows} total={sum(rows)}')
