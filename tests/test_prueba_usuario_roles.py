"""Prueba como usuario real, roles mesero y cocina (v6.8). Ver docs/PRUEBA_USUARIO_REAL.md."""
from pathlib import Path

from tests.conftest import login
from tests.test_transferencias import _setup_onboarding


class TestMesero:

    def _orden(self, db, mesero, sample_mesa):
        from backend.models.models import Orden, OrdenEstado
        o = Orden(mesa_id=sample_mesa.id, mesero_id=mesero.id, estado=OrdenEstado.ENVIADO)
        db.session.add(o)
        db.session.commit()
        return o

    def test_cancelar_exige_motivo(self, client, db, mesero_user, sample_mesa):
        from backend.models.models import OrdenEstado
        _setup_onboarding(db)
        orden = self._orden(db, mesero_user, sample_mesa)
        login(client, mesero_user.email, 'Test1234!')
        resp = client.post(f'/meseros/ordenes/{orden.id}/cancelar', follow_redirects=True)
        assert 'Elige el motivo' in resp.get_data(as_text=True)
        db.session.refresh(orden)
        assert orden.estado != OrdenEstado.CANCELADA

        client.post(f'/meseros/ordenes/{orden.id}/cancelar',
                    data={'motivo_cancelacion': 'otro', 'motivo_otro': ''})
        db.session.refresh(orden)
        assert orden.estado != OrdenEstado.CANCELADA, '"Otro" sin explicar no basta'

    def test_motivo_queda_en_auditoria(self, client, db, mesero_user, sample_mesa):
        from backend.models.models import AuditLog, OrdenEstado
        _setup_onboarding(db)
        orden = self._orden(db, mesero_user, sample_mesa)
        login(client, mesero_user.email, 'Test1234!')
        client.post(f'/meseros/ordenes/{orden.id}/cancelar',
                    data={'motivo_cancelacion': 'otro', 'motivo_otro': '<b>se</b> fue sin pagar'})
        db.session.refresh(orden)
        assert orden.estado == OrdenEstado.CANCELADA
        log = AuditLog.query.filter_by(accion='cancelar').one()
        assert 'Otro: se fue sin pagar' in log.descripcion

    def test_peticion_sin_json_responde_en_espanol(self, client, db, mesero_user, sample_mesa):
        _setup_onboarding(db)
        orden = self._orden(db, mesero_user, sample_mesa)
        login(client, mesero_user.email, 'Test1234!')
        resp = client.post(f'/api/ordenes/{orden.id}/detalle', data='no es json',
                           content_type='text/plain')
        assert resp.status_code in (400, 415)
        assert 'Bad Request' not in resp.get_data(as_text=True)
        assert 'Unsupported Media Type' not in resp.get_data(as_text=True)


class TestAccesoConPin:

    def test_usuario_id_de_texto_no_truena(self, client, db, monkeypatch):
        from backend.services import acceso
        _setup_onboarding(db)
        monkeypatch.setattr(acceso, 'dispositivo_actual', lambda: object())
        resp = client.post('/acceso/pin', json={'usuario_id': 'abc', 'pin': '1234'})
        assert resp.status_code == 404


class TestCocina:

    def test_nota_larga_no_saca_el_boton_de_la_tarjeta(self):
        """Sin min-width:0 el bloque de texto crecía a lo ancho de la nota y el botón de
        marcar listo quedaba fuera de la tarjeta."""
        html = (Path(__file__).resolve().parent.parent / 'backend' / 'templates' / 'cocina'
                / '_kds_cards_fragment.html').read_text(encoding='utf-8')
        assert 'style="flex:1;min-width:0;"' in html
        css = (Path(__file__).resolve().parent.parent / 'backend' / 'static' / 'css'
               / 'v7-kds.css').read_text(encoding='utf-8')
        nota = css[css.index('.cl-kds-item__note {'):]
        assert 'overflow-wrap: anywhere' in nota[:nota.index('}')]


class TestSesiones:

    def test_sesiones_en_archivo_no_se_borran_a_las_500(self, app):
        """Sin Redis, cachelib borraba sesiones al azar al pasar de 500 archivos."""
        assert app.config.get('SESSION_FILE_THRESHOLD', 500) >= 10000
