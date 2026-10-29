"""Acceso rápido: sesiones persistentes, usuario corto, PIN y dispositivos autorizados.

Plan y decisiones: docs/PLAN_ACCESO_PIN.md
"""
import time

import pytest

from tests.conftest import login


def _onboarding(db):
    from backend.models.models import ConfiguracionSistema
    if not ConfiguracionSistema.query.filter_by(clave='onboarding_completado').first():
        db.session.add(ConfiguracionSistema(clave='onboarding_completado', valor='true'))
        db.session.commit()


@pytest.fixture
def estacion(db):
    from backend.models.models import Estacion
    e = Estacion(nombre='Comal')
    db.session.add(e)
    db.session.commit()
    return e


@pytest.fixture
def cocinera(db, estacion):
    from backend.models.models import Usuario
    u = Usuario(nombre='Cata Comal', username='cata', rol='cocina', estacion_id=estacion.id)
    u.set_pin('4826')
    db.session.add(u)
    db.session.commit()
    return u


def _vincular(app, client, superadmin_user, db, nombre='Tablet comal'):
    """La dueña genera el código en su sesión; el aparato `client` lo canjea."""
    dueña = app.test_client()
    login(dueña, 'super_test@test.com', 'Test1234!')
    dueña.post('/admin/dispositivos/codigo')
    with dueña.session_transaction() as s:
        codigo = s['codigo_enlace']
    return client.post('/vincular', data={'codigo': codigo, 'nombre': nombre})


def _pin(client, usuario, pin):
    return client.post('/acceso/pin', json={'usuario_id': usuario.id, 'pin': pin})


# ── Sesiones persistentes ──

class TestSesionPersistente:
    def test_la_cookie_lleva_fecha_de_expiracion(self, client, mesero_user, db):
        """Sin Expires la cookie moría al cerrar el navegador (o al matar la app)."""
        _onboarding(db)
        resp = client.post('/login', data={'email': 'mesero_test@test.com', 'password': 'Test1234!'})
        cookies = resp.headers.getlist('Set-Cookie')
        sesion = next(c for c in cookies if c.startswith('session='))
        assert 'Expires=' in sesion

    def test_vence_por_inactividad_segun_rol(self, client, mesero_user, db):
        _onboarding(db)
        login(client, 'mesero_test@test.com', 'Test1234!')
        with client.session_transaction() as s:
            assert s['vence'] - time.time() == pytest.approx(16 * 3600, abs=120)
            s['vence'] = int(time.time()) - 1
        resp = client.get('/meseros/', follow_redirects=False)
        assert resp.status_code == 302 and '/login' in resp.headers['Location']
        with client.session_transaction() as s:
            assert 'user_id' not in s

    def test_cocina_dura_30_dias(self, app, client, cocinera, superadmin_user, db):
        _onboarding(db)
        _vincular(app, client, superadmin_user, db)
        _pin(client, cocinera, '4826')
        with client.session_transaction() as s:
            assert s['vence'] - time.time() == pytest.approx(30 * 24 * 3600, abs=120)

    def test_el_uso_renueva(self, client, mesero_user, db):
        _onboarding(db)
        login(client, 'mesero_test@test.com', 'Test1234!')
        with client.session_transaction() as s:
            s['vence'] = int(time.time()) + 600  # le quedan 10 min
        client.get('/meseros/')
        with client.session_transaction() as s:
            assert s['vence'] - time.time() > 15 * 3600


# ── Usuario corto ──

class TestLoginPorUsuario:
    def test_entra_con_usuario_corto(self, client, db):
        from backend.models.models import Usuario
        _onboarding(db)
        u = Usuario(nombre='María', username='maria', rol='admin')
        u.set_password('Clave2026x')
        db.session.add(u)
        db.session.commit()
        resp = client.post('/login', data={'email': 'Maria', 'password': 'Clave2026x'})
        assert resp.status_code == 302 and '/admin/dashboard' in resp.headers['Location']

    def test_las_cuentas_viejas_siguen_entrando_con_correo(self, client, admin_user, db):
        _onboarding(db)
        resp = client.post('/login', data={'email': 'ADMIN_TEST@test.com', 'password': 'Test1234!'})
        assert resp.status_code == 302 and '/admin/dashboard' in resp.headers['Location']

    def test_personal_con_solo_pin_no_entra_por_contrasena(self, client, cocinera, db):
        _onboarding(db)
        resp = client.post('/login', data={'email': 'cata', 'password': ''})
        assert resp.status_code == 200
        assert 'incorrectos' in resp.get_data(as_text=True)


# ── PIN y dispositivos ──

class TestPin:
    def test_sin_aparato_autorizado_el_pin_no_sirve(self, client, cocinera, db):
        _onboarding(db)
        assert _pin(client, cocinera, '4826').status_code == 403

    def test_flujo_completo_vincular_y_entrar(self, app, client, cocinera, superadmin_user, db):
        _onboarding(db)
        resp = _vincular(app, client, superadmin_user, db)
        assert resp.status_code == 302
        assert 'kr_dispositivo=' in ' '.join(resp.headers.getlist('Set-Cookie'))

        html = client.get('/login').get_data(as_text=True)
        assert '¿Quién eres?' in html and 'Cata Comal' in html

        resp = _pin(client, cocinera, '4826')
        assert resp.status_code == 200 and resp.get_json()['ok']
        # Las mismas llaves que el login por contraseña (de ellas depende toda la autorización)
        with client.session_transaction() as s:
            assert s['user_id'] == cocinera.id
            assert s['rol'] == 'cocina'
            assert s['estacion_id'] == cocinera.estacion_id
        assert client.get('/cocina/comal').status_code == 200

    def test_cinco_fallos_bloquean_aunque_luego_acierte(self, app, client, cocinera, superadmin_user, db):
        _onboarding(db)
        _vincular(app, client, superadmin_user, db)
        for i in range(4):
            r = _pin(client, cocinera, '0000')
            assert r.status_code == 401 and r.get_json()['restantes'] == 4 - i
        assert _pin(client, cocinera, '0000').status_code == 423
        assert _pin(client, cocinera, '4826').status_code == 423  # bloqueado aunque sea el bueno

        dueña = app.test_client()
        login(dueña, 'super_test@test.com', 'Test1234!')
        dueña.post(f'/admin/usuarios/{cocinera.id}/desbloquear')
        assert _pin(client, cocinera, '4826').status_code == 200

    def test_admin_no_entra_con_pin(self, app, client, superadmin_user, db):
        _onboarding(db)
        _vincular(app, client, superadmin_user, db)
        superadmin_user.set_pin('4826')
        db.session.commit()
        assert _pin(client, superadmin_user, '4826').status_code == 404

    def test_desautorizado_ya_no_entra(self, app, client, cocinera, superadmin_user, db):
        from backend.models.models import DispositivoAutorizado
        _onboarding(db)
        _vincular(app, client, superadmin_user, db)
        disp = DispositivoAutorizado.query.one()
        dueña = app.test_client()
        login(dueña, 'super_test@test.com', 'Test1234!')
        dueña.post(f'/admin/dispositivos/{disp.id}/desautorizar')
        assert _pin(client, cocinera, '4826').status_code == 403
        assert '¿Quién eres?' not in client.get('/login').get_data(as_text=True)


class TestCodigoDeEnlace:
    def test_sirve_una_sola_vez(self, app, client, superadmin_user, db):
        _onboarding(db)
        dueña = app.test_client()
        login(dueña, 'super_test@test.com', 'Test1234!')
        dueña.post('/admin/dispositivos/codigo')
        with dueña.session_transaction() as s:
            codigo = s['codigo_enlace']
        assert client.post('/vincular', data={'codigo': codigo, 'nombre': 'A'}).status_code == 302
        otro = app.test_client()
        assert otro.post('/vincular', data={'codigo': codigo, 'nombre': 'B'}).status_code == 400

    def test_cinco_intentos_lo_anulan(self, app, client, superadmin_user, db):
        _onboarding(db)
        dueña = app.test_client()
        login(dueña, 'super_test@test.com', 'Test1234!')
        dueña.post('/admin/dispositivos/codigo')
        with dueña.session_transaction() as s:
            codigo = s['codigo_enlace']
        malo = '000000' if codigo != '000000' else '111111'
        for _ in range(5):
            client.post('/vincular', data={'codigo': malo, 'nombre': 'X'})
        assert client.post('/vincular', data={'codigo': codigo, 'nombre': 'X'}).status_code == 400

    def test_vencido_no_sirve(self, app, client, superadmin_user, db):
        import json
        from backend.models.models import ConfiguracionSistema
        from backend.services import acceso
        _onboarding(db)
        with app.test_request_context():
            codigo = acceso.crear_codigo(superadmin_user.id)
            datos = json.loads(ConfiguracionSistema.get(acceso._CLAVE_CODIGO))
            datos['vence'] = int(time.time()) - 1
            ConfiguracionSistema.set(acceso._CLAVE_CODIGO, json.dumps(datos))
            db.session.commit()
        assert client.post('/vincular', data={'codigo': codigo, 'nombre': 'X'}).status_code == 400


class TestReglasDelPin:
    @pytest.mark.parametrize('pin', ['0000', '1111', '1234', '4321', '0123', '9876', '123', '12345', 'abcd', ''])
    def test_rechaza_obvios_y_mal_formados(self, pin):
        from backend.services.acceso import validar_pin
        assert not validar_pin(pin)[0]

    def test_acepta_normales_y_genera_validos(self):
        from backend.services.acceso import generar_pin, validar_pin
        assert validar_pin('4826')[0]
        assert all(validar_pin(generar_pin())[0] for _ in range(200))


# ── Alta de personal ──

class TestAltaDePersonal:
    def test_wizard_paso5_crea_con_pin_sin_correo(self, app, client, db, estacion):
        from backend.models.models import ConfiguracionSistema, Mesa, Usuario
        db.session.add(Mesa(numero='1', capacidad=4, estado='disponible'))
        a = Usuario(nombre='Dueña', username='duena', rol='superadmin', email='d@t.test')
        a.set_password('Clave2026x')
        db.session.add(a)
        ConfiguracionSistema.set('nombre_negocio', 'Casa Leones')
        db.session.commit()
        resp = client.post('/setup/paso/5', data={
            'user_nombre[]': ['Pepe Mesero', 'Cata Comal', 'Pepe Otro'],
            'user_rol[]': ['mesero', 'cocina:Comal', 'mesero'],
            'user_pin[]': ['4826', '7391', '1234'],  # el tercero es obvio: no se crea
            'autorizar_este': '1',
        })
        assert resp.status_code == 302
        assert 'kr_dispositivo=' in ' '.join(resp.headers.getlist('Set-Cookie'))
        pepe = Usuario.query.filter_by(username='pepe').one()
        assert pepe.email is None and pepe.check_pin('4826') and pepe.rol == 'mesero'
        cata = Usuario.query.filter_by(username='cata').one()
        assert cata.rol == 'cocina' and cata.estacion_id == estacion.id
        assert Usuario.query.filter_by(nombre='Pepe Otro').first() is None

    def test_admin_da_de_alta_mesero_con_pin(self, client, superadmin_user, db):
        from backend.models.models import Usuario
        _onboarding(db)
        login(client, 'super_test@test.com', 'Test1234!')
        resp = client.post('/admin/usuarios/nuevo', data={
            'nombre': 'Pepe Mesero', 'usuario': '', 'rol': 'mesero', 'pin': '4826', 'email': ''})
        assert resp.status_code == 302
        u = Usuario.query.filter_by(username='pepe').one()
        assert u.email is None and u.check_pin('4826')

    def test_admin_nuevo_exige_contrasena(self, client, superadmin_user, db):
        from backend.models.models import Usuario
        _onboarding(db)
        login(client, 'super_test@test.com', 'Test1234!')
        resp = client.post('/admin/usuarios/nuevo', data={
            'nombre': 'Otra Admin', 'usuario': 'otra', 'rol': 'admin', 'pin': '4826', 'password': ''})
        assert resp.status_code == 200
        assert Usuario.query.filter_by(username='otra').first() is None

    def test_usuario_repetido_se_rechaza(self, client, superadmin_user, cocinera, db):
        _onboarding(db)
        login(client, 'super_test@test.com', 'Test1234!')
        resp = client.post('/admin/usuarios/nuevo', data={
            'nombre': 'Catalina', 'usuario': 'cata', 'rol': 'mesero', 'pin': '4826'})
        assert resp.status_code == 200
        assert 'ya existe' in resp.get_data(as_text=True)


class TestCli:
    def test_reset_pin_desbloquea(self, app, cocinera, db):
        from backend.cli import reset_pin
        from backend.models.models import Usuario, utc_now
        cocinera.pin_bloqueado_hasta = utc_now().replace(tzinfo=None).replace(year=2099)
        db.session.commit()
        resultado = app.test_cli_runner().invoke(reset_pin, ['cata', '--pin', '5937'])
        assert resultado.exit_code == 0, resultado.output
        u = db.session.get(Usuario, cocinera.id)
        assert u.check_pin('5937') and not u.pin_bloqueado
