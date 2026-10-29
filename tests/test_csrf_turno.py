"""CSRF en pantallas que se quedan abiertas todo el turno (KDS) + errores en español.

El KDS sólo refresca fragmentos por fetch: su token CSRF es el de la carga de la página.
Con el default de Flask-WTF (3600 s), a la hora cada "listo" regresaba 400 y la tablet
ponía la palomita igual. Estos tests corren con CSRF ENCENDIDO (el resto de la suite lo
apaga en conftest).
"""
import re
import time
from unittest import mock

import pytest

from tests.conftest import login
from tests.test_kds_undo import _setup, _orden_enviada

OCHO_HORAS = 8 * 3600


def _token_de_la_pagina(client, url):
    html = client.get(url).get_data(as_text=True)
    m = re.search(r'<meta name="csrf-token" content="([^"]+)"', html)
    assert m, f'{url} no trae el meta csrf-token'
    return m.group(1)


def _en_el_futuro(segundos):
    """Adelanta el reloj con el que itsdangerous firma/valida el token."""
    real = time.time
    return mock.patch('itsdangerous.timed.time.time', lambda: real() + segundos)


@pytest.fixture
def kds_con_csrf(app, client, db, mesero_user, sample_categoria, monkeypatch):
    """Cocinero logueado en su estación, CSRF encendido, token tomado de la página."""
    est, prod, coci = _setup(db, sample_categoria)
    orden, (d1,) = _orden_enviada(db, mesero_user, prod, 1)
    login(client, coci.email, 'Test1234!')        # antes de encender CSRF
    monkeypatch.setitem(app.config, 'WTF_CSRF_ENABLED', True)
    token = _token_de_la_pagina(client, '/cocina/barbacoa')
    return orden, d1, token


class TestTokenDelTurno:

    def test_kds_abierto_8_horas_puede_marcar(self, client, db, kds_con_csrf):
        from backend.models.models import OrdenEstado
        orden, d1, token = kds_con_csrf
        with _en_el_futuro(OCHO_HORAS):
            r = client.post(f'/cocina/barbacoa/marcar/{orden.id}/{d1.id}',
                            headers={'X-CSRFToken': token})
        assert r.status_code == 200, r.get_data(as_text=True)[:200]
        db.session.refresh(d1)
        assert d1.estado == OrdenEstado.LISTO

    def test_control_con_limite_de_una_hora_falla(self, app, client, db, kds_con_csrf, monkeypatch):
        """Control negativo: con el default de Flask-WTF el mismo POST se rechaza."""
        from backend.models.models import OrdenEstado
        orden, d1, token = kds_con_csrf
        monkeypatch.setitem(app.config, 'WTF_CSRF_TIME_LIMIT', 3600)
        with _en_el_futuro(OCHO_HORAS):
            r = client.post(f'/cocina/barbacoa/marcar/{orden.id}/{d1.id}',
                            headers={'X-CSRFToken': token})
        assert r.status_code == 400
        db.session.refresh(d1)
        assert d1.estado == OrdenEstado.PENDIENTE

    def test_sin_token_sigue_rechazando(self, client, kds_con_csrf):
        """Quitar el reloj no apaga la protección."""
        orden, d1, _ = kds_con_csrf
        r = client.post(f'/cocina/barbacoa/marcar/{orden.id}/{d1.id}')
        assert r.status_code == 400

    def test_token_de_otra_sesion_rechaza(self, app, client, kds_con_csrf):
        orden, d1, token = kds_con_csrf
        with app.test_client() as otro:
            r = otro.post(f'/cocina/barbacoa/marcar/{orden.id}/{d1.id}',
                          headers={'X-CSRFToken': token})
        assert r.status_code == 400


class TestErroresEnEspanol:

    def test_csrf_rechazado_muestra_sesion_expirada(self, client, kds_con_csrf):
        orden, d1, _ = kds_con_csrf
        r = client.post(f'/cocina/barbacoa/marcar/{orden.id}/{d1.id}')
        html = r.get_data(as_text=True)
        assert r.status_code == 400
        assert 'La sesión expiró' in html
        assert 'Bad Request' not in html

    def test_csrf_rechazado_en_json(self, client, kds_con_csrf):
        orden, d1, _ = kds_con_csrf
        r = client.post(f'/cocina/barbacoa/marcar/{orden.id}/{d1.id}',
                        headers={'Accept': 'application/json'})
        assert r.status_code == 400
        assert r.get_json()['error'] == 'La sesión expiró'

    def test_405_en_espanol(self, client, db, mesero_user):
        from backend.models.models import ConfiguracionSistema
        db.session.add(ConfiguracionSistema(clave='onboarding_completado', valor='true'))
        db.session.commit()
        login(client, mesero_user.email, 'Test1234!')
        r = client.get('/meseros/ordenes/1/pago')    # la ruta sólo acepta POST
        html = r.get_data(as_text=True)
        assert r.status_code == 405
        assert 'Acción no válida' in html
        assert 'Method Not Allowed' not in html
