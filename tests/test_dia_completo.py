"""Un día de operación de punta a punta: que el dinero cuadre.

Los tests de los otros módulos verifican piezas. Éste verifica el negocio: se
levantan varias cuentas con distintos meseros y estaciones, se cobra de formas
mezcladas (efectivo con propina, transferencia por verificar), se cancela una y
se aplica un descuento autorizado. Al cerrar, **la suma de pagos verificados
tiene que coincidir con las ventas, con el dashboard, con el reporte y con el
corte de caja**. Si un número no coincide, el negocio no puede confiar en el
sistema para cerrar su día.
"""
from decimal import Decimal

import pytest

from tests.conftest import login


@pytest.fixture
def negocio(db):
    """Taquería con dos estaciones, dos meseros, una dueña y seis mesas."""
    from backend.models.models import (Categoria, ConfiguracionSistema, Estacion,
                                       Mesa, Producto, Sucursal, Usuario)

    db.session.add(Sucursal(nombre='Taqueria La Esquina'))
    ConfiguracionSistema.set('onboarding_completado', 'true')
    ConfiguracionSistema.set('metodos_pago', 'efectivo,transferencia')

    duena = Usuario(nombre='Dona Mari', email='mari@taqueria.mx', rol='superadmin')
    ana = Usuario(nombre='Ana', email='ana@taqueria.mx', rol='mesero')
    beto = Usuario(nombre='Beto', email='beto@taqueria.mx', rol='mesero')
    for u in (duena, ana, beto):
        u.set_password('Test1234!')
    db.session.add_all([duena, ana, beto])

    parrilla = Estacion(nombre='Parrilla')
    barra = Estacion(nombre='Barra')
    db.session.add_all([parrilla, barra])
    db.session.flush()

    cat = Categoria(nombre='Menu')
    db.session.add(cat)
    db.session.flush()
    taco = Producto(nombre='Taco al Pastor', precio=22, categoria_id=cat.id,
                    estacion_id=parrilla.id)
    agua = Producto(nombre='Agua de Horchata', precio=20, categoria_id=cat.id,
                    estacion_id=barra.id)
    db.session.add_all([taco, agua])

    for n in ['1', '2', '3']:
        db.session.add(Mesa(numero=n, capacidad=4, estado='disponible'))
    db.session.commit()

    return {
        'duena': duena, 'ana': ana, 'beto': beto,
        'taco': taco, 'agua': agua,
        'mesas': {m.numero: m for m in Mesa.query.all()},
    }


class _Turno:
    """Maneja las sesiones y los pasos del servicio."""

    def __init__(self, client, db, negocio):
        self.c = client
        self.db = db
        self.n = negocio

    def entrar(self, email):
        login(self.c, email, 'Test1234!')
        return self.c

    def cuenta(self, mesero_email, mesa, personas=None):
        from backend.models.models import Orden

        self.entrar(mesero_email)
        datos = {'mesa_id': self.n['mesas'][mesa].id}
        if personas:
            datos['num_personas'] = str(personas)
        resp = self.c.post('/meseros/seleccionar_mesa', data=datos,
                           follow_redirects=False)
        destino = resp.headers.get('Location') or ''
        oid = int(destino.rstrip('/').split('/')[-2])
        return self.db.session.get(Orden, oid)

    def pedir(self, orden, producto, cantidad):
        return self.c.post(f'/api/ordenes/{orden.id}/detalle',
                           json={'producto_id': producto.id, 'cantidad': cantidad})

    def a_cocina(self, orden):
        return self.c.post(f'/meseros/ordenes/{orden.id}/enviar_a_cocina')

    def cocinar(self, orden):
        """Cada estación marca lo suyo, entrando como la dueña (tiene acceso)."""
        from backend.models.models import OrdenEstado

        mesero_actual = None
        self.entrar('mari@taqueria.mx')
        self.db.session.refresh(orden)
        for d in list(orden.detalles):
            if d.estado == OrdenEstado.LISTO:
                continue
            slug = d.producto.estacion.nombre.lower()
            self.c.post(f'/cocina/{slug}/marcar/{orden.id}/{d.id}')
        return mesero_actual

    def total(self, orden):
        orden.calcular_totales()
        self.db.session.commit()
        return Decimal(str(orden.total or 0))

    def cobrar(self, mesero_email, orden, **pago):
        self.entrar(mesero_email)
        return self.c.post(f'/meseros/ordenes/{orden.id}/pago', json=pago)


@pytest.fixture
def turno(client, db, negocio, app):
    from backend.extensions import limiter
    limiter.enabled = False   # un turno entero en segundos no debe throttlearse
    return _Turno(client, db, negocio)


class TestUnDiaDeOperacion:
    def test_el_dinero_cuadra_al_cerrar_el_dia(self, turno, db, negocio):
        """La prueba que de verdad importa: cuatro vistas, un solo número."""
        from backend.models.models import Orden, OrdenEstado, Pago, Sale

        # -- Mesa 1: efectivo con propina --
        o1 = turno.cuenta('ana@taqueria.mx', '1', personas=2)
        turno.pedir(o1, negocio['taco'], 2)
        turno.pedir(o1, negocio['agua'], 2)
        turno.a_cocina(o1)
        turno.cocinar(o1)
        t1 = turno.total(o1)
        resp = turno.cobrar('ana@taqueria.mx', o1, metodo='efectivo',
                            monto=float(t1) + 50, propina=20)
        assert resp.get_json()['orden_pagada'] is True

        # -- Mesa 2: transferencia, queda pendiente hasta verificarla --
        o2 = turno.cuenta('beto@taqueria.mx', '2', personas=3)
        turno.pedir(o2, negocio['taco'], 3)
        turno.a_cocina(o2)
        turno.cocinar(o2)
        t2 = turno.total(o2)
        turno.cobrar('beto@taqueria.mx', o2, metodo='transferencia',
                     monto=float(t2), referencia='SPEI-001')
        db.session.refresh(o2)
        assert o2.estado != OrdenEstado.PAGADA, 'se cerró sin confirmar el depósito'

        # -- Mesa 3: se cancela --
        o3 = turno.cuenta('ana@taqueria.mx', '3', personas=2)
        turno.pedir(o3, negocio['agua'], 1)
        turno.a_cocina(o3)
        turno.entrar('ana@taqueria.mx')
        turno.c.post(f'/meseros/ordenes/{o3.id}/cancelar', json={'motivo': 'se fue'})

        # -- La dueña confirma el depósito --
        turno.entrar('mari@taqueria.mx')
        pago2 = Pago.query.filter_by(orden_id=o2.id).first()
        turno.c.post(f'/admin/pagos/{pago2.id}/verificar')
        db.session.refresh(o2)
        assert o2.estado == OrdenEstado.PAGADA

        # ---------- CIERRE: todo tiene que dar el mismo número ----------
        pagos = Pago.query.filter_by(verificado=True).all()
        suma_pagos = sum(Decimal(str(p.monto)) for p in pagos)
        suma_propinas = sum(Decimal(str(p.propina or 0)) for p in pagos)
        ventas = Sale.query.all()
        suma_ventas = sum(Decimal(str(v.total)) for v in ventas)
        pagadas = Orden.query.filter_by(estado=OrdenEstado.PAGADA).count()

        assert len(ventas) == pagadas, 'hay órdenes pagadas sin su venta'
        assert suma_pagos == suma_ventas, f'pagos {suma_pagos} != ventas {suma_ventas}'

        turno.entrar('mari@taqueria.mx')
        dashboard = turno.c.get('/admin/api/dashboard/ventas_hoy').get_json()
        assert Decimal(str(dashboard['ventasHoy'])) == suma_ventas

        propinas = turno.c.get('/admin/api/dashboard/propinas_hoy').get_json()
        assert Decimal(str(propinas['propinas'])) == suma_propinas

        reporte = turno.c.get('/admin/reportes/api/ventas').get_json()
        total_reporte = sum(Decimal(str(x)) for x in reporte['por_dia']['totales'])
        assert total_reporte == suma_ventas, 'el reporte no coincide con las ventas'

    def test_el_corte_de_caja_cuadra_contando_el_cajon(self, turno, db, negocio):
        """El efectivo esperado incluye las propinas: contarlas de menos daba un
        'sobrante' fantasma exactamente igual a las propinas del día."""
        from backend.models.models import CorteCaja, Pago

        o1 = turno.cuenta('ana@taqueria.mx', '1', personas=2)
        turno.pedir(o1, negocio['taco'], 2)
        turno.a_cocina(o1)
        turno.cocinar(o1)
        t1 = turno.total(o1)
        turno.cobrar('ana@taqueria.mx', o1, metodo='efectivo',
                     monto=float(t1) + 100, propina=30)

        pagos = Pago.query.filter_by(verificado=True, metodo='efectivo').all()
        esperado = (sum(Decimal(str(p.monto)) for p in pagos)
                    + sum(Decimal(str(p.propina or 0)) for p in pagos))

        turno.entrar('mari@taqueria.mx')
        turno.c.post('/admin/corte-caja', data={'efectivo_contado': str(esperado)})

        corte = CorteCaja.query.order_by(CorteCaja.id.desc()).first()
        assert corte is not None
        assert abs(Decimal(str(corte.diferencia or 0))) < Decimal('0.01'), \
            f'contando el cajón exacto la diferencia debería ser 0, es {corte.diferencia}'

    def test_una_cancelacion_no_entra_al_corte(self, turno, db, negocio):
        from backend.models.models import OrdenEstado, Sale

        o = turno.cuenta('ana@taqueria.mx', '1', personas=2)
        turno.pedir(o, negocio['taco'], 3)
        turno.a_cocina(o)
        turno.entrar('ana@taqueria.mx')
        turno.c.post(f'/meseros/ordenes/{o.id}/cancelar', json={'motivo': 'se fue'})

        db.session.refresh(o)
        assert o.estado == OrdenEstado.CANCELADA
        assert Sale.query.count() == 0, 'una cancelación generó venta'

    def test_las_mesas_quedan_libres_al_cerrar(self, turno, db, negocio):
        from backend.models.models import Mesa

        o = turno.cuenta('ana@taqueria.mx', '1', personas=2)
        turno.pedir(o, negocio['taco'], 1)
        db.session.refresh(negocio['mesas']['1'])
        assert negocio['mesas']['1'].estado == 'ocupada'

        turno.a_cocina(o)
        turno.cocinar(o)
        turno.cobrar('ana@taqueria.mx', o, metodo='efectivo',
                     monto=float(turno.total(o)))

        assert Mesa.query.filter(Mesa.estado != 'disponible').count() == 0


class TestDescuentoAutorizado:
    """Un mesero no puede regalar dinero del negocio por su cuenta."""

    def _cuenta_lista(self, turno, negocio):
        o = turno.cuenta('beto@taqueria.mx', '1', personas=2)
        turno.pedir(o, negocio['taco'], 5)
        turno.a_cocina(o)
        turno.cocinar(o)
        turno.entrar('beto@taqueria.mx')
        return o

    def test_sin_autorizacion_no_se_aplica(self, turno, db, negocio):
        o = self._cuenta_lista(turno, negocio)
        antes = turno.total(o)

        resp = turno.c.post(f'/meseros/ordenes/{o.id}/descuento',
                            json={'tipo': 'porcentaje', 'valor': 10})
        assert resp.status_code == 403
        assert turno.total(o) == antes

    def test_el_mesero_no_se_autoriza_a_si_mismo(self, turno, db, negocio):
        o = self._cuenta_lista(turno, negocio)
        antes = turno.total(o)

        resp = turno.c.post(f'/meseros/ordenes/{o.id}/descuento', json={
            'tipo': 'porcentaje', 'valor': 10,
            'auth_email': 'beto@taqueria.mx', 'auth_password': 'Test1234!',
        })
        assert resp.status_code == 403
        assert turno.total(o) == antes

    def test_la_duena_autoriza_y_queda_registrado(self, turno, db, negocio):
        o = self._cuenta_lista(turno, negocio)
        antes = turno.total(o)

        resp = turno.c.post(f'/meseros/ordenes/{o.id}/descuento', json={
            'tipo': 'porcentaje', 'valor': 10, 'motivo': 'cliente inconforme',
            'auth_email': 'mari@taqueria.mx', 'auth_password': 'Test1234!',
        })
        assert resp.status_code == 200

        db.session.refresh(o)
        assert abs(turno.total(o) - antes * Decimal('0.9')) < Decimal('0.5')
        assert o.descuento_autorizado_por == negocio['duena'].id, \
            'no queda rastro de quién autorizó el descuento'
