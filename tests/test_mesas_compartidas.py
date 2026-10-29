"""Mesas compartidas: varias cuentas (órdenes) activas en la misma mesa.

Cubre: creación de segunda cuenta con forzar_nueva, redirect al selector,
alias/num_personas persistidos, mesa ocupada hasta cerrar la última cuenta.
"""
import json
from decimal import Decimal
from tests.conftest import login, _make_user


def _setup_onboarding(db):
    from backend.models.models import ConfiguracionSistema
    db.session.add(ConfiguracionSistema(clave='onboarding_completado', valor='true'))
    db.session.commit()


def _con_producto(db, orden_id, producto):
    """Una cuenta sin productos es un borrador invisible: para que cuente como
    cuenta activa de la mesa tiene que tener algo pedido."""
    from backend.models.models import Orden, OrdenDetalle
    from backend.utils import actualizar_estado_mesa
    db.session.add(OrdenDetalle(orden_id=orden_id, producto_id=producto.id,
                                cantidad=1, precio_unitario=Decimal('25')))
    db.session.commit()
    # Igual que la ruta real: con el primer producto la mesa pasa a ocupada
    mesa_id = db.session.get(Orden, orden_id).mesa_id
    if mesa_id:
        actualizar_estado_mesa(mesa_id)
        db.session.commit()


def _ultima_orden_id(db, mesa_id):
    from backend.models.models import Orden
    return db.session.query(Orden.id).filter_by(mesa_id=mesa_id).order_by(Orden.id.desc()).first()[0]


def _crear_cuenta(client, mesa_id, forzar=False, alias='', personas=''):
    data = {'mesa_id': mesa_id}
    if forzar:
        data['forzar_nueva'] = '1'
    if alias:
        data['alias'] = alias
    if personas:
        data['num_personas'] = personas
    return client.post('/meseros/seleccionar_mesa', data=data, follow_redirects=False)


class TestMesasCompartidas:

    def test_segunda_cuenta_redirige_al_selector(self, client, db, mesero_user,
                                                 sample_mesa, sample_producto):
        _setup_onboarding(db)
        login(client, mesero_user.email, 'Test1234!')

        r1 = _crear_cuenta(client, sample_mesa.id)
        assert '/detalle_orden' in r1.headers['Location']
        _con_producto(db, _ultima_orden_id(db, sample_mesa.id), sample_producto)

        # Segundo intento SIN forzar → selector de cuentas, no crea orden
        r2 = _crear_cuenta(client, sample_mesa.id)
        assert f'/meseros/mesa/{sample_mesa.id}/cuentas' in r2.headers['Location']

        from backend.models.models import Orden
        assert Orden.query.filter_by(mesa_id=sample_mesa.id).count() == 1

    def test_forzar_nueva_crea_segunda_cuenta_con_alias(self, client, db, mesero_user,
                                                        sample_mesa, sample_producto):
        _setup_onboarding(db)
        login(client, mesero_user.email, 'Test1234!')

        _crear_cuenta(client, sample_mesa.id)
        _con_producto(db, _ultima_orden_id(db, sample_mesa.id), sample_producto)
        r = _crear_cuenta(client, sample_mesa.id, forzar=True,
                          alias='los de la esquina', personas='3')
        assert '/detalle_orden' in r.headers['Location']

        from backend.models.models import Orden
        cuentas = Orden.query.filter_by(mesa_id=sample_mesa.id).order_by(Orden.id).all()
        assert len(cuentas) == 2
        assert cuentas[1].alias == 'los de la esquina'
        assert cuentas[1].num_personas == 3

        # La mesa sigue ocupada
        db.session.refresh(sample_mesa)
        assert sample_mesa.estado == 'ocupada'

    def test_selector_lista_ambas_cuentas(self, client, db, mesero_user, sample_mesa,
                                          sample_producto):
        _setup_onboarding(db)
        login(client, mesero_user.email, 'Test1234!')
        _crear_cuenta(client, sample_mesa.id)
        _con_producto(db, _ultima_orden_id(db, sample_mesa.id), sample_producto)
        _crear_cuenta(client, sample_mesa.id, forzar=True, alias='pareja ventana')
        _con_producto(db, _ultima_orden_id(db, sample_mesa.id), sample_producto)

        r = client.get(f'/meseros/mesa/{sample_mesa.id}/cuentas')
        html = r.data.decode()
        assert r.status_code == 200
        assert 'pareja ventana' in html
        assert '2 cuentas' in html
        assert 'Abrir cuenta nueva' in html

    def test_mesa_se_libera_solo_al_cerrar_la_ultima_cuenta(self, client, db, mesero_user,
                                                            sample_mesa, sample_producto):
        _setup_onboarding(db)
        login(client, mesero_user.email, 'Test1234!')
        _crear_cuenta(client, sample_mesa.id)
        _con_producto(db, _ultima_orden_id(db, sample_mesa.id), sample_producto)
        _crear_cuenta(client, sample_mesa.id, forzar=True)
        _con_producto(db, _ultima_orden_id(db, sample_mesa.id), sample_producto)

        from backend.models.models import Orden, OrdenEstado
        c1, c2 = Orden.query.filter_by(mesa_id=sample_mesa.id).order_by(Orden.id).all()

        def _pagar(orden):
            client.post(f'/meseros/ordenes/{orden.id}/agregar_productos', data={
                'productos_json': json.dumps([{'id': sample_producto.id, 'cantidad': 1, 'notas': ''}])
            })
            orden.estado = OrdenEstado.COMPLETADA
            db.session.commit()
            r = client.post(f'/meseros/ordenes/{orden.id}/pago',
                            json={'metodo': 'efectivo', 'monto': 999, 'propina': 0})
            assert r.get_json()['orden_pagada'] is True

        _pagar(c1)
        db.session.refresh(sample_mesa)
        assert sample_mesa.estado == 'ocupada', 'con una cuenta abierta la mesa sigue ocupada'

        _pagar(c2)
        db.session.refresh(sample_mesa)
        assert sample_mesa.estado == 'disponible', 'al cerrar la última cuenta la mesa se libera'

    def test_api_mesa_devuelve_lista_de_cuentas(self, client, db, mesero_user, sample_mesa,
                                                sample_producto):
        _setup_onboarding(db)
        login(client, mesero_user.email, 'Test1234!')
        _crear_cuenta(client, sample_mesa.id)
        _con_producto(db, _ultima_orden_id(db, sample_mesa.id), sample_producto)
        _crear_cuenta(client, sample_mesa.id, forzar=True, alias='grupo 2')
        _con_producto(db, _ultima_orden_id(db, sample_mesa.id), sample_producto)

        r = client.get(f'/api/ordenes/mesa/{sample_mesa.id}')
        body = r.get_json()
        assert len(body['ordenes']) == 2
        assert body['orden_id'] == body['ordenes'][0]['orden_id']
        assert body['ordenes'][1]['alias'] == 'grupo 2'

    def test_cancelar_una_cuenta_no_libera_mesa_con_otra_abierta(self, client, db, mesero_user,
                                                                 sample_mesa, sample_producto):
        _setup_onboarding(db)
        login(client, mesero_user.email, 'Test1234!')
        _crear_cuenta(client, sample_mesa.id)
        _con_producto(db, _ultima_orden_id(db, sample_mesa.id), sample_producto)
        _crear_cuenta(client, sample_mesa.id, forzar=True)
        _con_producto(db, _ultima_orden_id(db, sample_mesa.id), sample_producto)

        from backend.models.models import Orden, OrdenEstado
        c1, c2 = Orden.query.filter_by(mesa_id=sample_mesa.id).order_by(Orden.id).all()

        client.post(f'/meseros/ordenes/{c1.id}/cancelar', data={'motivo_cancelacion': 'cliente_solicito'})
        db.session.refresh(c1)
        assert c1.estado == OrdenEstado.CANCELADA
        db.session.refresh(sample_mesa)
        assert sample_mesa.estado == 'ocupada', 'la otra cuenta sigue abierta'
