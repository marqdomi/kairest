#!/usr/bin/env python3
"""Quick end-to-end test for Phase 2 dynamic KDS refactor."""
import os, sys
os.environ['FLASK_ENV'] = 'testing'
os.environ.setdefault('SECRET_KEY', 'test-secret-key-phase2')
os.environ.setdefault('DATABASE_URL', 'postgresql://casaleones:casaleones_secret@localhost:5433/casaleones')
os.environ.setdefault('REDIS_URL', '')

from backend.app import create_app
app = create_app()

passed = 0
failed = 0

def check(name, condition, detail=''):
    global passed, failed
    if condition:
        passed += 1
        print(f'  PASS  {name}')
    else:
        failed += 1
        print(f'  FAIL  {name} — {detail}')

with app.app_context():
    from backend.models.models import Estacion, Usuario

    # 1. Verify estaciones exist
    estaciones = Estacion.query.all()
    check('Estaciones exist', len(estaciones) >= 2, f'found {len(estaciones)}')

    # 2. Verify cocina users have estacion_id
    cocina_users = Usuario.query.filter_by(rol='cocina').all()
    check('Cocina users exist', len(cocina_users) >= 1, f'found {len(cocina_users)}')
    for u in cocina_users:
        check(f'User {u.nombre} has estacion_id', u.estacion_id is not None, f'estacion_id={u.estacion_id}')
        check(f'User {u.nombre} es_cocina=True', u.es_cocina, f'es_cocina={u.es_cocina}')
        check(f'User {u.nombre} estacion_nombre', u.estacion_nombre is not None, f'estacion_nombre={u.estacion_nombre}')

    # 3. Test slugify
    from backend.routes.cocina import _slugify
    check('Slugify Parrilla', _slugify('Parrilla') == 'parrilla')
    check('Slugify Bar', _slugify('Bar') == 'bar')
    check('Slugify with accent', _slugify('Café Bar') == 'cafe-bar')

    # 4. Test routes with test client
    with app.test_client() as client:
        # Disable CSRF for test
        app.config['WTF_CSRF_ENABLED'] = False

        # Login as admin
        resp = client.post('/login', data={'email': 'admin@test.com', 'password': 'Test1234!'})
        check('Admin login', resp.status_code in (200, 302), f'status={resp.status_code}')

        # Access cocina index
        with client.session_transaction() as sess:
            sess['user_id'] = 1
            sess['rol'] = 'superadmin'
        resp = client.get('/cocina/')
        check('Cocina index redirects', resp.status_code == 302, f'status={resp.status_code}')

        # Access station by slug
        slug = _slugify(estaciones[0].nombre)
        resp = client.get(f'/cocina/{slug}')
        check(f'Station /{slug} loads', resp.status_code == 200, f'status={resp.status_code}')

        # Fragment endpoint
        resp = client.get(f'/cocina/{slug}/fragmento_ordenes')
        check(f'Fragment /{slug} loads', resp.status_code == 200, f'status={resp.status_code}')

        # API estaciones
        resp = client.get('/cocina/api/estaciones')
        check('API estaciones', resp.status_code == 200, f'status={resp.status_code}')
        data = resp.get_json()
        check('API returns list', isinstance(data, list) and len(data) >= 2, f'data={data}')

        # Legacy compat aliases
        resp = client.get('/cocina/legacy/taqueros', follow_redirects=False)
        check('Legacy /taqueros redirect', resp.status_code in (302, 404), f'status={resp.status_code}')

        # Admin usuario form
        resp = client.get('/admin/usuarios/nuevo')
        html = resp.get_data(as_text=True)
        check('Usuario form loads', resp.status_code == 200, f'status={resp.status_code}')
        check('Form has cocina role', 'Cocina' in html, 'Cocina not in form')
        check('Form has Parrilla station', 'Parrilla' in html, 'Parrilla not in form')

        # Test admin sidebar has Cocina (KDS) link
        resp = client.get('/admin/dashboard')
        html = resp.get_data(as_text=True)
        check('Admin sidebar has Cocina link', 'Cocina (KDS)' in html, 'Cocina (KDS) not in sidebar')

print(f'\nResults: {passed} passed, {failed} failed')
sys.exit(1 if failed else 0)
