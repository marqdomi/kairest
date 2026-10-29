"""Flujo completo mesero <-> estaciones de cocina, paso a paso.

El hallazgo: agregarle productos a una cuenta que la cocina ya había terminado
la dejaba en `lista_para_entregar`. El KDS sólo muestra órdenes en
enviado/en_preparacion, así que **el producto nuevo no le llegaba a ninguna
estación** y la cuenta se podía cobrar igual: el cliente pagaba comida que
nadie preparó. Pasaba por los dos caminos —la pantalla de "agregar productos" y
el carrito, que guarda cada producto al tocarlo contra la API—, y el carrito
además no validaba el estado, así que aceptaba productos en cuentas ya pagadas.

Es el escenario más común de una taquería: "tráeme otro taco".
"""
import json

import pytest

from tests.conftest import login


def _onboarding_listo(db):
    from backend.models.models import ConfiguracionSistema
    if not ConfiguracionSistema.query.filter_by(clave='onboarding_completado').first():
        db.session.add(ConfiguracionSistema(clave='onboarding_completado', valor='true'))
        db.session.commit()


def _entrar(client, db, email, password='Test1234!'):
    _onboarding_listo(db)
    return login(client, email, password)


@pytest.fixture
def cocina(db, sample_categoria):
    """Dos estaciones con un producto cada una."""
    from backend.models.models import Estacion, Producto

    parrilla = Estacion(nombre='Parrilla')
    bebidas = Estacion(nombre='Bebidas')
    db.session.add_all([parrilla, bebidas])
    db.session.flush()
    taco = Producto(nombre='Taco', precio=25, categoria_id=sample_categoria.id,
                    estacion_id=parrilla.id)
    agua = Producto(nombre='Agua', precio=20, categoria_id=sample_categoria.id,
                    estacion_id=bebidas.id)
    db.session.add_all([taco, agua])
    db.session.commit()
    return {'parrilla': parrilla, 'bebidas': bebidas, 'taco': taco, 'agua': agua}


@pytest.fixture
def mesero(client, db, mesero_user):
    _entrar(client, db, 'mesero_test@test.com')
    return client


@pytest.fixture
def orden_lista(db, mesero, mesero_user, sample_mesa, cocina):
    """Cuenta con un taco, enviada a cocina y ya marcada lista."""
    from backend.models.models import Orden, OrdenDetalle, OrdenEstado

    o = Orden(mesa_id=sample_mesa.id, mesero_id=mesero_user.id, estado=OrdenEstado.ENVIADO)
    db.session.add(o)
    db.session.flush()
    d = OrdenDetalle(orden_id=o.id, producto_id=cocina['taco'].id, cantidad=1,
                     precio_unitario=25, estado=OrdenEstado.LISTO)
    db.session.add(d)
    o.estado = OrdenEstado.LISTA_PARA_ENTREGAR
    db.session.commit()
    return o


class TestAgregarDespuesDeQueLaCocinaTermino:
    """El cliente pide algo más cuando la cuenta ya estaba lista."""

    def test_por_la_pantalla_de_agregar_vuelve_a_cocina(self, mesero, db, orden_lista, cocina):
        from backend.models.models import OrdenEstado

        resp = mesero.post(f'/meseros/ordenes/{orden_lista.id}/agregar_productos', data={
            'productos_json': json.dumps([{'id': cocina['taco'].id, 'cantidad': 1}]),
        })
        assert resp.status_code in (200, 302)

        db.session.refresh(orden_lista)
        assert orden_lista.estado == OrdenEstado.EN_PREPARACION, \
            'la cuenta se quedó lista con un item sin preparar'

    def test_por_el_carrito_vuelve_a_cocina(self, mesero, db, orden_lista, cocina):
        """El carrito guarda cada producto al tocarlo contra la API."""
        from backend.models.models import OrdenEstado

        resp = mesero.post(f'/api/ordenes/{orden_lista.id}/detalle',
                           json={'producto_id': cocina['agua'].id, 'cantidad': 1})
        assert resp.status_code in (200, 201)

        db.session.refresh(orden_lista)
        assert orden_lista.estado == OrdenEstado.EN_PREPARACION

    def test_el_item_nuevo_llega_a_su_estacion(self, mesero, db, orden_lista, cocina,
                                               superadmin_user):
        mesero.post(f'/api/ordenes/{orden_lista.id}/detalle',
                    json={'producto_id': cocina['agua'].id, 'cantidad': 1})

        _entrar(mesero, db, 'super_test@test.com')
        assert 'Agua' in mesero.get('/cocina/bebidas').data.decode(), \
            'el item agregado no llega a la cocina: nadie lo prepara'

    def test_no_se_cobra_con_un_item_sin_preparar(self, mesero, db, orden_lista, cocina):
        mesero.post(f'/api/ordenes/{orden_lista.id}/detalle',
                    json={'producto_id': cocina['agua'].id, 'cantidad': 1})

        resp = mesero.post(f'/meseros/ordenes/{orden_lista.id}/pago',
                           json={'metodo': 'efectivo', 'monto': 45})
        assert not (resp.status_code == 200 and (resp.get_json() or {}).get('success')), \
            'se cobró comida que nadie preparó'

    def test_cuando_la_cocina_termina_si_se_cobra(self, mesero, db, orden_lista, cocina,
                                                  superadmin_user):
        """Control positivo: el flujo debe poder cerrarse."""
        from backend.models.models import OrdenDetalle, OrdenEstado

        mesero.post(f'/api/ordenes/{orden_lista.id}/detalle',
                    json={'producto_id': cocina['agua'].id, 'cantidad': 1})

        nuevo = OrdenDetalle.query.filter_by(orden_id=orden_lista.id,
                                             estado=OrdenEstado.PENDIENTE).first()
        _entrar(mesero, db, 'super_test@test.com')
        mesero.post(f'/cocina/bebidas/marcar/{orden_lista.id}/{nuevo.id}')

        db.session.refresh(orden_lista)
        assert orden_lista.estado == OrdenEstado.LISTA_PARA_ENTREGAR

        _entrar(mesero, db, 'mesero_test@test.com')
        resp = mesero.post(f'/meseros/ordenes/{orden_lista.id}/pago',
                           json={'metodo': 'efectivo', 'monto': 45})
        assert resp.status_code == 200 and resp.get_json()['success']


class TestNoSeModificaUnaCuentaCerrada:
    @pytest.mark.parametrize('estado_final', ['pagada', 'cancelada'])
    def test_el_carrito_rechaza_cuentas_cerradas(self, mesero, db, orden_lista, cocina,
                                                 estado_final):
        """El carrito no validaba el estado: aceptaba productos en una venta ya
        cerrada."""
        from backend.models.models import OrdenDetalle

        orden_lista.estado = estado_final
        db.session.commit()
        antes = OrdenDetalle.query.filter_by(orden_id=orden_lista.id).count()

        resp = mesero.post(f'/api/ordenes/{orden_lista.id}/detalle',
                           json={'producto_id': cocina['taco'].id, 'cantidad': 1})
        assert resp.status_code >= 400
        assert OrdenDetalle.query.filter_by(orden_id=orden_lista.id).count() == antes


class TestFlujoDeServicioCompleto:
    """Un turno de principio a fin con dos estaciones."""

    @pytest.fixture
    def orden_enviada(self, db, mesero, mesero_user, sample_mesa, cocina):
        from backend.models.models import Orden, OrdenDetalle, OrdenEstado

        o = Orden(mesa_id=sample_mesa.id, mesero_id=mesero_user.id,
                  estado=OrdenEstado.PENDIENTE)
        db.session.add(o)
        db.session.flush()
        d_taco = OrdenDetalle(orden_id=o.id, producto_id=cocina['taco'].id, cantidad=2,
                              precio_unitario=25, estado=OrdenEstado.PENDIENTE)
        d_agua = OrdenDetalle(orden_id=o.id, producto_id=cocina['agua'].id, cantidad=1,
                              precio_unitario=20, estado=OrdenEstado.PENDIENTE)
        db.session.add_all([d_taco, d_agua])
        db.session.commit()
        mesero.post(f'/meseros/ordenes/{o.id}/enviar_a_cocina')
        return {'orden': o, 'taco': d_taco, 'agua': d_agua}

    def test_la_cocina_no_ve_una_cuenta_sin_enviar(self, mesero, db, mesero_user,
                                                   sample_mesa, cocina, superadmin_user):
        from backend.models.models import Orden, OrdenDetalle, OrdenEstado

        o = Orden(mesa_id=sample_mesa.id, mesero_id=mesero_user.id,
                  estado=OrdenEstado.PENDIENTE)
        db.session.add(o)
        db.session.flush()
        db.session.add(OrdenDetalle(orden_id=o.id, producto_id=cocina['taco'].id,
                                    cantidad=1, precio_unitario=25,
                                    estado=OrdenEstado.PENDIENTE))
        db.session.commit()

        _entrar(mesero, db, 'super_test@test.com')
        assert 'Taco' not in mesero.get('/cocina/parrilla').data.decode()

    def test_cada_estacion_ve_solo_lo_suyo(self, mesero, db, orden_enviada, superadmin_user):
        _entrar(mesero, db, 'super_test@test.com')
        parrilla = mesero.get('/cocina/parrilla').data.decode()
        bebidas = mesero.get('/cocina/bebidas').data.decode()

        assert 'Taco' in parrilla and 'Agua' not in parrilla
        assert 'Agua' in bebidas and 'Taco' not in bebidas

    def test_la_cuenta_avanza_estacion_por_estacion(self, mesero, db, orden_enviada,
                                                    superadmin_user):
        from backend.models.models import OrdenEstado

        orden = orden_enviada['orden']
        _entrar(mesero, db, 'super_test@test.com')

        mesero.post(f"/cocina/parrilla/marcar/{orden.id}/{orden_enviada['taco'].id}")
        db.session.refresh(orden)
        assert orden.estado == OrdenEstado.EN_PREPARACION
        assert 'Agua' in mesero.get('/cocina/bebidas').data.decode(), \
            'el item de la otra estación desapareció antes de tiempo'

        mesero.post(f"/cocina/bebidas/marcar/{orden.id}/{orden_enviada['agua'].id}")
        db.session.refresh(orden)
        assert orden.estado == OrdenEstado.LISTA_PARA_ENTREGAR
        assert 'Taco' not in mesero.get('/cocina/parrilla').data.decode()

    def test_se_cobra_y_se_libera_la_mesa(self, mesero, db, orden_enviada, sample_mesa,
                                          superadmin_user):
        from backend.models.models import OrdenEstado

        orden = orden_enviada['orden']
        _entrar(mesero, db, 'super_test@test.com')
        mesero.post(f"/cocina/parrilla/marcar/{orden.id}/{orden_enviada['taco'].id}")
        mesero.post(f"/cocina/bebidas/marcar/{orden.id}/{orden_enviada['agua'].id}")

        _entrar(mesero, db, 'mesero_test@test.com')
        resp = mesero.post(f'/meseros/ordenes/{orden.id}/pago',
                           json={'metodo': 'efectivo', 'monto': 70})
        assert resp.status_code == 200 and resp.get_json()['orden_pagada']

        db.session.refresh(orden)
        db.session.refresh(sample_mesa)
        assert orden.estado == OrdenEstado.PAGADA
        assert sample_mesa.estado == 'disponible'

    def test_cancelar_a_media_preparacion_la_saca_de_los_dos_kds(self, mesero, db,
                                                                 orden_enviada,
                                                                 superadmin_user):
        from backend.models.models import OrdenEstado

        orden = orden_enviada['orden']
        _entrar(mesero, db, 'super_test@test.com')
        mesero.post(f"/cocina/parrilla/marcar/{orden.id}/{orden_enviada['taco'].id}")

        _entrar(mesero, db, 'mesero_test@test.com')
        mesero.post(f'/meseros/ordenes/{orden.id}/cancelar', json={'motivo': 'se fue'})
        db.session.refresh(orden)
        assert orden.estado == OrdenEstado.CANCELADA

        _entrar(mesero, db, 'super_test@test.com')
        assert 'Agua' not in mesero.get('/cocina/bebidas').data.decode()
        resp = mesero.post(f"/cocina/bebidas/marcar/{orden.id}/{orden_enviada['agua'].id}")
        assert resp.status_code == 409

    def test_undo_en_una_estacion_no_revierte_la_otra(self, mesero, db, orden_enviada,
                                                      superadmin_user):
        from backend.models.models import OrdenEstado

        orden = orden_enviada['orden']
        _entrar(mesero, db, 'super_test@test.com')
        mesero.post(f"/cocina/parrilla/marcar/{orden.id}/{orden_enviada['taco'].id}")
        mesero.post(f"/cocina/bebidas/marcar/{orden.id}/{orden_enviada['agua'].id}")

        resp = mesero.post(
            f"/cocina/parrilla/desmarcar/{orden.id}/{orden_enviada['taco'].id}")
        assert resp.status_code == 200

        db.session.refresh(orden)
        db.session.refresh(orden_enviada['agua'])
        assert orden.estado == OrdenEstado.EN_PREPARACION
        assert orden_enviada['agua'].estado == OrdenEstado.LISTO, \
            'el undo de una estación revirtió el trabajo de la otra'

        _entrar(mesero, db, 'mesero_test@test.com')
        resp = mesero.post(f'/meseros/ordenes/{orden.id}/pago',
                           json={'metodo': 'efectivo', 'monto': 70})
        assert not (resp.status_code == 200 and (resp.get_json() or {}).get('success'))
