"""Tests de lo encontrado en la demo paso a paso con el primer cliente (barbacoa).

Cubren la plantilla del menú real, el aterrizaje por rol en `/`, las páginas de
error en español, la fecha del dashboard y el corte sin tarjeta.
"""
from datetime import date

from tests.conftest import login


def _onboarding(db):
    from backend.models.models import ConfiguracionSistema
    if not ConfiguracionSistema.query.filter_by(clave='onboarding_completado').first():
        db.session.add(ConfiguracionSistema(clave='onboarding_completado', valor='true'))
        db.session.commit()


class TestPlantillaBarbacoa:
    def test_es_la_primera_y_trae_el_menu_completo(self, app, db):
        from backend.services.seeder import get_template_list
        with app.app_context():
            tpls = get_template_list()
        assert tpls[0]['key'] == 'barbacoa'
        assert tpls[0]['productos_count'] == 58
        assert tpls[0]['estaciones'] == ['Taquero', 'Comal', 'Bebidas']

    def test_ningun_producto_queda_sin_estacion(self, app, db):
        from backend.models.models import Producto
        from backend.services.seeder import seed_from_template
        with app.app_context():
            creados = seed_from_template('barbacoa')
            assert creados == 58
            assert Producto.query.filter(Producto.estacion_id.is_(None)).count() == 0
            quesadilla = Producto.query.filter_by(nombre='Quesadilla de queso').first()
            assert quesadilla.estacion.nombre == 'Comal'


class TestIndexPorRol:
    def test_sin_sesion_va_al_login(self, client, db):
        _onboarding(db)
        resp = client.get('/')
        assert resp.status_code == 302
        assert '/login' in resp.headers['Location']

    def test_mesero_aterriza_en_sus_ordenes(self, client, mesero_user, db):
        _onboarding(db)
        login(client, 'mesero_test@test.com', 'Test1234!')
        resp = client.get('/')
        assert resp.status_code == 302
        assert '/meseros' in resp.headers['Location']

    def test_admin_aterriza_en_el_dashboard(self, client, admin_user, db):
        _onboarding(db)
        login(client, 'admin_test@test.com', 'Test1234!')
        resp = client.get('/')
        assert '/admin/dashboard' in resp.headers['Location']


class TestPaginasDeError:
    def test_404_en_espanol_con_salida(self, client, db):
        _onboarding(db)
        resp = client.get('/no-existe-esta-ruta')
        assert resp.status_code == 404
        html = resp.get_data(as_text=True)
        assert 'No encontrado' in html
        assert 'Regresar a mi pantalla' in html

    def test_403_al_abrir_la_estacion_de_otro(self, client, db):
        """El taquero que abre el KDS del comal veía la página cruda de Werkzeug."""
        from backend.models.models import Estacion, Usuario
        _onboarding(db)
        taquero, comal = Estacion(nombre='Taquero'), Estacion(nombre='Comal')
        db.session.add_all([taquero, comal])
        db.session.commit()
        u = Usuario(nombre='Tito', email='tito@test.com', rol='cocina', estacion_id=taquero.id)
        u.set_password('Test1234!')
        db.session.add(u)
        db.session.commit()
        login(client, 'tito@test.com', 'Test1234!')
        resp = client.get('/cocina/comal')
        assert resp.status_code == 403
        html = resp.get_data(as_text=True)
        assert 'Sin acceso' in html
        assert 'Forbidden' not in html

    def test_api_responde_json(self, client, db):
        _onboarding(db)
        resp = client.get('/api/no-existe')
        assert resp.status_code == 404
        assert resp.get_json()['error'] == 'No encontrado'


class TestFechaLarga:
    def test_en_espanol_sin_depender_del_locale(self):
        from backend.services.tiempo import fecha_larga
        assert fecha_larga(date(2026, 10, 29)) == 'jueves 29 de octubre de 2026'
        assert fecha_larga(date(2026, 3, 1)) == 'domingo 1 de marzo de 2026'


class TestCorteSinTarjeta:
    def test_tarjeta_apagada_no_aparece_en_el_desglose(self, client, superadmin_user, db):
        _onboarding(db)
        login(client, 'super_test@test.com', 'Test1234!')
        html = client.get('/admin/corte-caja').get_data(as_text=True)
        assert 'Efectivo' in html
        assert '>Tarjeta</span>' not in html

    def test_tarjeta_habilitada_si_aparece(self, client, superadmin_user, db):
        from backend.models.models import ConfiguracionSistema
        _onboarding(db)
        ConfiguracionSistema.set('metodos_pago', 'efectivo,tarjeta,transferencia')
        db.session.commit()
        login(client, 'super_test@test.com', 'Test1234!')
        html = client.get('/admin/corte-caja').get_data(as_text=True)
        assert '>Tarjeta</span>' in html


class TestOrigenSocketIO:
    """La tablet abre el sistema por la IP de la red, no por localhost."""

    def _env(self, host, scheme='http', **extra):
        return {'HTTP_HOST': host, 'wsgi.url_scheme': scheme, **extra}

    def test_mismo_origen_por_ip_de_la_red(self):
        from backend.extensions import _origen_socket_permitido
        assert _origen_socket_permitido('http://192.168.0.70:5005', self._env('192.168.0.70:5005'))

    def test_dominio_detras_de_proxy_https(self):
        from backend.extensions import _origen_socket_permitido
        env = self._env('web:5005', HTTP_X_FORWARDED_HOST='casaleones.kainet.mx',
                        HTTP_X_FORWARDED_PROTO='https')
        assert _origen_socket_permitido('https://casaleones.kainet.mx', env)

    def test_otro_sitio_se_rechaza(self):
        from backend.extensions import _origen_socket_permitido
        assert not _origen_socket_permitido('https://sitio-malo.com', self._env('192.168.0.70:5005'))
