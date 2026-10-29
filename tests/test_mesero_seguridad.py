"""Regression tests: IDOR protection on cancel/deliver/discount, and the
mesa-selection race-condition guard (audit hardening for the mesero-cocina flow)."""
import json
from tests.conftest import login, _make_user


def _crear_mesero_b(db):
    return _make_user(db, 'Mesero B', 'mesero_b@test.com', 'Test1234!', 'mesero')


def _marcar_onboarding_completo(db):
    from backend.models.models import ConfiguracionSistema
    db.session.add(ConfiguracionSistema(clave='onboarding_completado', valor='true'))
    db.session.commit()


def test_idor_blocked_on_cancelar_entregar_descuento(client, db, mesero_user, sample_producto, sample_mesa):
    _marcar_onboarding_completo(db)
    mesero_b = _crear_mesero_b(db)

    # Mesero A logs in, takes the table, adds a product, sends to kitchen.
    login(client, mesero_user.email, 'Test1234!')
    resp = client.post('/meseros/seleccionar_mesa', data={'mesa_id': sample_mesa.id}, follow_redirects=True)
    assert resp.status_code == 200

    from backend.models.models import Orden, OrdenDetalle
    orden = Orden.query.filter_by(mesa_id=sample_mesa.id).first()
    assert orden is not None
    orden_id = orden.id

    resp = client.post(f'/meseros/ordenes/{orden_id}/agregar_productos', data={
        'productos_json': json.dumps([{'id': sample_producto.id, 'cantidad': 1, 'notas': ''}])
    }, follow_redirects=True)
    assert resp.status_code == 200

    detalle = OrdenDetalle.query.filter_by(orden_id=orden_id).first()
    detalle_id = detalle.id

    client.get('/logout')  # just drop session; POST-only logout would need csrf-free client anyway
    with client.session_transaction() as sess:
        sess.clear()

    # Mesero B logs in and tries to act on A's order.
    login(client, mesero_b.email, 'Test1234!')

    # Form POSTs (not XHR/JSON) get redirected with a flash message by the
    # ownership decorator, rather than a bare 403 — verify the redirect target
    # and that the order was NOT actually cancelled/modified.
    r_cancel = client.post(f'/meseros/ordenes/{orden_id}/cancelar', data={'motivo_cancelacion': 'cliente_solicito'})
    assert r_cancel.status_code == 302, f'cancelar_orden should redirect non-owner, got {r_cancel.status_code}'
    assert '/meseros/' in r_cancel.headers['Location']

    r_entregar = client.post(f'/meseros/entregar_item/{orden_id}/{detalle_id}')
    assert r_entregar.status_code == 302, f'entregar_item should redirect non-owner, got {r_entregar.status_code}'

    from backend.models.models import OrdenEstado
    db.session.refresh(orden)
    db.session.refresh(detalle)
    assert orden.estado != OrdenEstado.CANCELADA, 'mesero B must not be able to cancel a foreign order'
    assert detalle.estado != 'entregado', 'mesero B must not be able to mark a foreign item as delivered'

    r_descuento = client.post(f'/meseros/ordenes/{orden_id}/descuento',
                               data=json.dumps({'tipo': 'porcentaje', 'valor': 10,
                                                 'auth_email': mesero_b.email, 'auth_password': 'Test1234!'}),
                               content_type='application/json')
    assert r_descuento.status_code == 403, f'aplicar_descuento should block non-owner, got {r_descuento.status_code}'

    # Owner can still cancel their own order.
    with client.session_transaction() as sess:
        sess.clear()
    login(client, mesero_user.email, 'Test1234!')
    r_cancel_owner = client.post(f'/meseros/ordenes/{orden_id}/cancelar', data={'motivo_cancelacion': 'cliente_solicito'}, follow_redirects=True)
    assert r_cancel_owner.status_code == 200

    from backend.models.models import OrdenEstado
    db.session.refresh(orden)
    assert orden.estado == OrdenEstado.CANCELADA


def test_mesa_ocupada_redirige_al_selector_sin_duplicar(client, db, mesero_user, sample_mesa):
    """Un segundo POST sin forzar_nueva no crea otra orden.

    Si la cuenta previa es el borrador vacío del MISMO mesero, se reutiliza y se
    vuelve a la captura; el resguardo que importa es que no se duplique la orden.
    """
    _marcar_onboarding_completo(db)
    login(client, mesero_user.email, 'Test1234!')
    r1 = client.post('/meseros/seleccionar_mesa', data={'mesa_id': sample_mesa.id}, follow_redirects=True)
    assert r1.status_code == 200

    r2 = client.post('/meseros/seleccionar_mesa', data={'mesa_id': sample_mesa.id}, follow_redirects=False)
    assert r2.status_code == 302
    assert '/detalle_orden' in r2.headers['Location']

    from backend.models.models import Orden
    count = Orden.query.filter_by(mesa_id=sample_mesa.id).count()
    assert count == 1, f'expected exactly 1 order for the table, got {count}'


def test_borrador_de_otro_mesero_si_avisa(client, db, mesero_user, sample_mesa):
    """El borrador ajeno sí debe verse: si no, dos meseros levantan la misma mesa
    sin enterarse el uno del otro."""
    from backend.models.models import Orden, OrdenEstado
    from tests.conftest import _make_user

    _marcar_onboarding_completo(db)
    otro = _make_user(db, 'Otro Mesero', 'otro_mesero@test.com', 'Test1234!', 'mesero')
    db.session.add(Orden(mesero_id=otro.id, mesa_id=sample_mesa.id,
                         estado=OrdenEstado.PENDIENTE))
    db.session.commit()

    login(client, mesero_user.email, 'Test1234!')
    r = client.post('/meseros/seleccionar_mesa', data={'mesa_id': sample_mesa.id},
                    follow_redirects=False)
    assert f'/meseros/mesa/{sample_mesa.id}/cuentas' in r.headers['Location'], \
        'no avisó que otro mesero ya está en esa mesa'


def test_mesero_puede_ver_cualquier_estacion(client, db, mesero_user):
    """Meseros pueden abrir el KDS de cualquier estación (ej. sirven bebidas) —
    y los links de estación aparecen en su barra de navegación."""
    from backend.models.models import Estacion
    _marcar_onboarding_completo(db)
    db.session.add(Estacion(nombre='Bebidas'))
    db.session.commit()

    login(client, mesero_user.email, 'Test1234!')
    r = client.get('/cocina/bebidas')
    assert r.status_code == 200, f'mesero debe poder ver la estación, got {r.status_code}'

    # La barra de operaciones del mesero muestra el link a la estación
    r2 = client.get('/meseros/')
    assert b'/cocina/bebidas' in r2.data, 'el link a la estación debe aparecer en el panel del mesero'
