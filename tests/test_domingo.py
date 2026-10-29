"""Un domingo completo en "Barbacoa Don Chema": de la primera mesa al corte de caja.

A diferencia de `test_dia_completo.py` (pocas cuentas "de libro"), aquí pasa lo que pasa
un domingo de verdad, a la hora en que pasa:

  09:10  familia que pide más cuando la orden ya está en cocina
  09:30  para llevar pagado por transferencia (la dueña la confirma)
  09:50  un mesero abre una mesa y se va sin pedir nada
  10:15  pareja que modifica la orden antes de enviarla; paga mitad transferencia
  11:00  mesa grande compartida: tres cuentas, tres meseros, tres formas de pago
  12:20  para llevar que se cancela: el cliente se cansó de esperar
  12:40  cliente frecuente con descuento autorizado por la dueña
  13:10  el taquero marca "listo" por dedazo y lo deshace; la transferencia no llega
  13:30  transferencia "en camino" que el cliente termina pagando en efectivo
  14:00  mesa de 6 que paga en partes, con propina en el primer pago
  15:00  orden capturada mal: se cancela y se vuelve a levantar
  15:30  hora pico: seis para llevar seguidos
  19:40  cena (ya es lunes en UTC: aquí se perdían las ventas por la zona horaria)
  20:15  para llevar por transferencia con propina
  21:00  última mesa: su transferencia sigue sin confirmar al cerrar
  22:30  corte de caja contando el cajón
  00:10  ya es lunes: el día nuevo arranca en cero y el domingo no se mueve

El test lleva su propia cuenta de lo que DEBERÍA pasar (precios del menú, cantidades,
descuentos, propinas, cambio) y al cierre la compara con la base, el dashboard, los
reportes y el corte. Cada persona usa su propio cliente HTTP (su propia sesión), como
en el puesto: tres celulares de meseros, tres tablets de cocina y la de la dueña.
"""
import os
import sqlite3
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

ZONA = ZoneInfo('America/Mexico_City')
DOMINGO = date(2026, 10, 25)
LUNES = DOMINGO + timedelta(days=1)
D = Decimal


# ── Reloj ─────────────────────────────────────────────────────────────────────

class _Reloj:
    """La hora que ve el sistema. Se mueve con `a(hh, mm)` como avanza el día."""
    def __init__(self):
        self.ahora = datetime.combine(DOMINGO, time(8, 0), ZONA)

    def a(self, hh, mm=0, dia=DOMINGO):
        self.ahora = datetime.combine(dia, time(hh, mm), ZONA)


def _datetime_falso(reloj):
    class _FalsoDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            momento = reloj.ahora.astimezone(tz) if tz else reloj.ahora.astimezone(timezone.utc).replace(tzinfo=None)
            return cls.fromtimestamp(momento.timestamp(), tz) if tz else cls(*momento.timetuple()[:6])

        @classmethod
        def utcnow(cls):
            return cls.now(timezone.utc).replace(tzinfo=None)
    return _FalsoDatetime


# ── Personas ──────────────────────────────────────────────────────────────────

class _Persona:
    def __init__(self, app, nombre):
        self.c = app.test_client()
        self.nombre = nombre

    def ok(self, resp, *codigos):
        codigos = codigos or (200, 201, 302)
        assert resp.status_code in codigos, \
            f'{self.nombre}: {resp.request.method} {resp.request.path} → {resp.status_code} ' \
            f'{resp.get_data(as_text=True)[:200]}'
        return resp


class _Mesero(_Persona):
    def __init__(self, app, usuario, pin, menu):
        super().__init__(app, usuario.nombre)
        self.usuario, self.menu = usuario, menu
        self.ok(self.c.post('/acceso/pin', json={'usuario_id': usuario.id, 'pin': pin}))

    def _orden_de(self, resp):
        destino = resp.headers.get('Location', '')
        assert '/ordenes/' in destino, f'{self.nombre}: no abrió orden ({destino})'
        return int(destino.split('/ordenes/')[1].split('/')[0])

    def abrir_mesa(self, mesa, personas=None, alias=None, nueva=False):
        datos = {'mesa_id': mesa.id}
        if personas:
            datos['num_personas'] = str(personas)
        if alias:
            datos['alias'] = alias
        if nueva:
            datos['forzar_nueva'] = '1'
        return self._orden_de(self.ok(self.c.post('/meseros/seleccionar_mesa', data=datos)))

    def para_llevar(self):
        return self._orden_de(self.ok(self.c.post('/meseros/crear_orden_para_llevar')))

    def pedir(self, oid, producto, cantidad=1, notas=''):
        r = self.ok(self.c.post(f'/api/ordenes/{oid}/detalle', json={
            'producto_id': self.menu[producto].id, 'cantidad': cantidad, 'notas': notas}), 201)
        return r.get_json()['detalle']['id'] if 'detalle' in (r.get_json() or {}) else None

    def cambiar(self, oid, did, cantidad):
        self.ok(self.c.patch(f'/api/ordenes/{oid}/detalle/{did}', json={'cantidad': cantidad}))

    def quitar(self, oid, did):
        self.ok(self.c.delete(f'/api/ordenes/{oid}/detalle/{did}'))

    def a_cocina(self, oid):
        self.ok(self.c.post(f'/meseros/ordenes/{oid}/enviar_a_cocina'))

    def entregar(self, oid):
        from backend.models.models import OrdenDetalle
        for d in OrdenDetalle.query.filter_by(orden_id=oid).all():
            if d.estado == 'listo':
                self.ok(self.c.post(f'/meseros/entregar_item/{oid}/{d.id}'))

    def cobrar(self, oid, metodo, monto, propina=0, referencia=None, esperar=200):
        cuerpo = {'metodo': metodo, 'monto': float(monto), 'propina': float(propina)}
        if referencia:
            cuerpo['referencia'] = referencia
        r = self.c.post(f'/meseros/ordenes/{oid}/pago', json=cuerpo)
        assert r.status_code == esperar, f'{self.nombre} cobro {oid}: {r.status_code} {r.get_json()}'
        return r.get_json()

    def cancelar(self, oid, motivo, otro=''):
        self.ok(self.c.post(f'/meseros/ordenes/{oid}/cancelar',
                            data={'motivo_cancelacion': motivo, 'motivo_otro': otro}))

    def descuento(self, oid, porcentaje, motivo, autoriza_email, autoriza_password):
        return self.ok(self.c.post(f'/meseros/ordenes/{oid}/descuento', json={
            'tipo': 'porcentaje', 'valor': porcentaje, 'motivo': motivo,
            'auth_email': autoriza_email, 'auth_password': autoriza_password}))


class _Cocina(_Persona):
    def __init__(self, app, usuario, pin, estacion):
        super().__init__(app, usuario.nombre)
        self.estacion = estacion
        self.slug = estacion.nombre.lower()
        self.ok(self.c.post('/acceso/pin', json={'usuario_id': usuario.id, 'pin': pin}))

    def _mios(self, oid, pendientes=True):
        from backend.models.models import OrdenDetalle, Producto
        q = OrdenDetalle.query.join(Producto).filter(
            OrdenDetalle.orden_id == oid, Producto.estacion_id == self.estacion.id)
        if pendientes:
            q = q.filter(OrdenDetalle.estado != 'listo')
        return q.all()

    def terminar(self, oid):
        ids = [d.id for d in self._mios(oid)]
        if ids:
            self.ok(self.c.post(f'/cocina/{self.slug}/batch-listo',
                                json={'orden_id': oid, 'detalle_ids': ids}))

    def marcar(self, oid, did):
        self.ok(self.c.post(f'/cocina/{self.slug}/marcar/{oid}/{did}'))

    def deshacer(self, oid, did):
        self.ok(self.c.post(f'/cocina/{self.slug}/desmarcar/{oid}/{did}'))


class _Duena(_Persona):
    def __init__(self, app, usuario, password):
        super().__init__(app, usuario.nombre)
        self.email, self.password = usuario.email, password
        self.ok(self.c.post('/login', data={'email': usuario.email, 'password': password}))

    def pago_pendiente(self, oid):
        from backend.models.models import Pago
        return Pago.query.filter_by(orden_id=oid, verificado=False).one()

    def confirmar(self, oid, esperar=200):
        r = self.c.post(f'/admin/pagos/{self.pago_pendiente(oid).id}/verificar')
        assert r.status_code == esperar, f'confirmar {oid}: {r.status_code} {r.get_json()}'
        return r

    def rechazar(self, oid):
        self.ok(self.c.post(f'/admin/pagos/{self.pago_pendiente(oid).id}/rechazar'))

    def json(self, url):
        return self.ok(self.c.get(url)).get_json()


# ── El negocio ────────────────────────────────────────────────────────────────

@pytest.fixture
def domingo(app, db, monkeypatch):
    from backend.extensions import limiter
    from backend.models import models as modelos
    from backend.models.models import (ConfiguracionSistema, Estacion, Mesa, Producto,
                                       Sucursal, Usuario)
    from backend.services import acceso, tiempo
    from backend.services.seeder import seed_from_template

    limiter.enabled = False
    reloj = _Reloj()
    falso = _datetime_falso(reloj)
    monkeypatch.setattr(modelos, 'datetime', falso)
    monkeypatch.setattr(tiempo, 'datetime', falso)
    # La tablet del puesto ya está autorizada para entrar con PIN
    monkeypatch.setattr(acceso, 'dispositivo_actual',
                        lambda: SimpleNamespace(id=1, nombre='Tablet del puesto', ultimo_uso=None))

    db.session.add(Sucursal(nombre='Barbacoa Don Chema'))
    ConfiguracionSistema.set('onboarding_completado', 'true')
    ConfiguracionSistema.set('metodos_pago', 'efectivo,transferencia')
    seed_from_template('barbacoa')
    for n in range(1, 11):
        db.session.add(Mesa(numero=str(n), capacidad=6, estado='disponible'))

    est = {e.nombre: e for e in Estacion.query.all()}
    gente = {}
    duena = Usuario(nombre='Doña Chela', email='chela@donchema.mx', username='chela', rol='superadmin')
    duena.set_password('Chela2026x')
    gente['duena'] = duena
    for clave, nombre, pin in [('ana', 'Ana', '3691'), ('beto', 'Beto', '4826'), ('caro', 'Caro', '5937')]:
        u = Usuario(nombre=nombre, username=clave, rol='mesero')
        u.set_pin(pin)
        gente[clave] = (u, pin)
    for clave, nombre, pin, estacion in [('tono', 'Toño', '6148', 'Taquero'),
                                          ('lupe', 'Lupe', '7259', 'Comal'),
                                          ('memo', 'Memo', '8361', 'Bebidas')]:
        u = Usuario(nombre=nombre, username=clave, rol='cocina', estacion_id=est[estacion].id)
        u.set_pin(pin)
        gente[clave] = (u, pin, est[estacion])
    db.session.add(duena)
    db.session.add_all([v[0] for k, v in gente.items() if k != 'duena'])
    db.session.commit()

    menu = {p.nombre: p for p in Producto.query.all()}
    mesas = {m.numero: m for m in Mesa.query.all()}
    return SimpleNamespace(
        reloj=reloj, menu=menu, mesas=mesas,
        duena=_Duena(app, duena, 'Chela2026x'),
        ana=_Mesero(app, *gente['ana'], menu), beto=_Mesero(app, *gente['beto'], menu),
        caro=_Mesero(app, *gente['caro'], menu),
        tono=_Cocina(app, *gente['tono']), lupe=_Cocina(app, *gente['lupe']),
        memo=_Cocina(app, *gente['memo']),
        usuarios={'ana': gente['ana'][0], 'beto': gente['beto'][0], 'caro': gente['caro'][0]},
    )


# ── El libro de la dueña: lo que debió pasar ──────────────────────────────────

class _Libro:
    def __init__(self, menu):
        self.menu = menu
        self.ordenes = {}        # oid -> dict
        self.efectivo_caja = D('0')   # lo que debe haber en el cajón (venta + propinas)

    def orden(self, oid, mesero):
        self.ordenes[oid] = {'mesero': mesero, 'items': {}, 'descuento': D('0'),
                             'estado': 'abierta', 'propina': D('0'), 'pagos': []}

    def item(self, oid, producto, cantidad):
        items = self.ordenes[oid]['items']
        items[producto] = items.get(producto, 0) + cantidad
        if items[producto] == 0:
            del items[producto]

    def total(self, oid):
        o = self.ordenes[oid]
        bruto = sum(D(str(self.menu[p].precio)) * q for p, q in o['items'].items())
        return (bruto * (1 - o['descuento'] / 100)).quantize(D('0.01'))

    def pago(self, oid, metodo, aplicado, propina=D('0'), verificado=True):
        o = self.ordenes[oid]
        o['pagos'].append({'metodo': metodo, 'aplicado': D(str(aplicado)),
                           'propina': D(str(propina)), 'verificado': verificado})
        o['propina'] += D(str(propina))
        if metodo == 'efectivo':
            self.efectivo_caja += D(str(aplicado)) + D(str(propina))

    def verificar_ultimo(self, oid):
        """La dueña confirma la transferencia pendiente más reciente de la cuenta."""
        pendientes = [p for p in self.ordenes[oid]['pagos'] if not p['verificado']]
        pendientes[-1]['verificado'] = True

    def quitar_ultimo(self, oid):
        p = self.ordenes[oid]['pagos'].pop()
        self.ordenes[oid]['propina'] -= p['propina']

    def pagadas(self):
        return {oid: o for oid, o in self.ordenes.items() if o['estado'] == 'pagada'}


# ── El domingo ────────────────────────────────────────────────────────────────

def test_un_domingo_completo(domingo, db):
    from backend.models.models import (AuditLog, CorteCaja, Mesa, Orden, OrdenDetalle,
                                       OrdenEstado, Pago, Sale)

    d, libro = domingo, _Libro(domingo.menu)
    M = d.mesas
    cambios = []   # (escenario, cambio esperado, cambio que dio el sistema)

    def servir(oid, mesero, *cocinas):
        for c in cocinas or (d.tono, d.lupe, d.memo):
            c.terminar(oid)
        mesero.entregar(oid)

    def cobro_efectivo(escenario, oid, mesero, recibido, propina=0):
        r = mesero.cobrar(oid, 'efectivo', recibido, propina)
        saldo = libro.total(oid) - sum(p['aplicado'] for p in libro.ordenes[oid]['pagos'] if p['verificado'])
        aplicado = min(D(str(recibido)), saldo)
        libro.pago(oid, 'efectivo', aplicado, propina)
        if r.get('orden_pagada'):
            libro.ordenes[oid]['estado'] = 'pagada'
            cambios.append((escenario, max(D(str(recibido)) - saldo - D(str(propina)), D('0')),
                            D(str(r.get('cambio', 0))).quantize(D('0.01'))))
        return r

    # 09:10 · Familia López, mesa 1, 5 personas. Piden más con la orden ya en cocina.
    d.reloj.a(9, 10)
    o1 = d.ana.abrir_mesa(M['1'], personas=5)
    libro.orden(o1, 'Ana')
    for prod, q in [('1 kg Barbacoa', 1), ('Plato de consomé', 3),
                    ('Tortillas hechas a mano (kg)', 1), ('Refresco Coca-Cola', 2)]:
        d.ana.pedir(o1, prod, q)
        libro.item(o1, prod, q)
    d.ana.a_cocina(o1)
    d.reloj.a(9, 25)
    for prod in ['1/2 kg Barbacoa', 'Café']:
        d.ana.pedir(o1, prod, 1, notas='lo pidió la abuela')
        libro.item(o1, prod, 1)
    d.reloj.a(9, 40)
    servir(o1, d.ana)
    d.reloj.a(10, 5)
    assert libro.total(o1) == D('1040.00')
    cobro_efectivo('familia', o1, d.ana, 1200, propina=100)        # cambio 60

    # 09:30 · Para llevar por transferencia; la dueña la confirma 15 min después.
    d.reloj.a(9, 30)
    o2 = d.beto.para_llevar()
    libro.orden(o2, 'Beto')
    for prod in ['Paquete: 1 kg barbacoa + 2 lt consomé', 'Tortillas hechas a mano (kg)']:
        d.beto.pedir(o2, prod)
        libro.item(o2, prod, 1)
    d.beto.a_cocina(o2)
    servir(o2, d.beto, d.tono, d.lupe)
    d.beto.cobrar(o2, 'transferencia', libro.total(o2), referencia='SPEI 4471')
    libro.pago(o2, 'transferencia', libro.total(o2), verificado=False)
    d.reloj.a(9, 45)
    d.duena.confirmar(o2)
    libro.verificar_ultimo(o2)
    libro.ordenes[o2]['estado'] = 'pagada'

    # 09:50 · Caro abre la mesa 9 y se va sin pedir nada: no debe quedar nada de eso.
    d.reloj.a(9, 50)
    borrador = d.caro.abrir_mesa(M['9'])

    # 10:15 · Pareja, mesa 2: modifican antes de enviar; pagan $200 por transferencia
    # y el resto en efectivo. La cuenta se cierra hasta que la dueña confirma.
    d.reloj.a(10, 15)
    o4 = d.caro.abrir_mesa(M['2'], personas=2)
    libro.orden(o4, 'Caro')
    d.caro.pedir(o4, 'Taco de maciza', 2)
    d.caro.pedir(o4, 'Taco de espinazo (surtida)', 2)
    d.caro.pedir(o4, 'Quesadilla de queso', 2)
    d.caro.pedir(o4, 'Café', 2)
    det = {dd.producto.nombre: dd for dd in OrdenDetalle.query.filter_by(orden_id=o4)}
    d.caro.cambiar(o4, det['Taco de maciza'].id, 3)
    d.caro.cambiar(o4, det['Café'].id, 1)
    d.caro.quitar(o4, det['Quesadilla de queso'].id)
    d.caro.pedir(o4, 'Quesadilla flor de calabaza', 1)
    for prod, q in [('Taco de maciza', 3), ('Taco de espinazo (surtida)', 2),
                    ('Quesadilla flor de calabaza', 1), ('Café', 1)]:
        libro.item(o4, prod, q)
    d.caro.a_cocina(o4)
    d.reloj.a(10, 35)
    servir(o4, d.caro)
    assert libro.total(o4) == D('233.00')
    d.caro.cobrar(o4, 'transferencia', 200, referencia='Mercado Pago Lalo')
    libro.pago(o4, 'transferencia', 200, verificado=False)
    cobro_efectivo('pareja', o4, d.caro, 33)
    assert db.session.get(Orden, o4).estado != OrdenEstado.PAGADA, \
        'la cuenta se cerró con $200 sin confirmar'
    d.reloj.a(10, 50)
    d.duena.confirmar(o4)
    libro.verificar_ultimo(o4)
    libro.ordenes[o4]['estado'] = 'pagada'

    # 11:00 · Mesa 3 compartida: tres cuentas, tres meseros, tres formas de pago.
    d.reloj.a(11, 0)
    c_fondo = d.ana.abrir_mesa(M['3'], personas=4, alias='Los del fondo')
    libro.orden(c_fondo, 'Ana')
    for prod, q in [('1 kg Carnitas', 1), ('1 litro de consomé', 1), ('Refresco Coca-Cola', 4)]:
        d.ana.pedir(c_fondo, prod, q)
        libro.item(c_fondo, prod, q)
    c_senores = d.beto.abrir_mesa(M['3'], personas=2, alias='Los señores', nueva=True)
    libro.orden(c_senores, 'Beto')
    for prod, q in [('1/2 kg Barbacoa', 1), ('Café', 2)]:
        d.beto.pedir(c_senores, prod, q)
        libro.item(c_senores, prod, q)
    c_ninos = d.caro.abrir_mesa(M['3'], personas=3, alias='Los niños', nueva=True)
    libro.orden(c_ninos, 'Caro')
    for prod, q in [('Orden de tacos dorados (3 flautas)', 1), ('Jugo Boing (mango)', 3)]:
        d.caro.pedir(c_ninos, prod, q)
        libro.item(c_ninos, prod, q)
    assert len({c_fondo, c_senores, c_ninos}) == 3, 'las cuentas compartidas se mezclaron'
    for oid, mesero in [(c_fondo, d.ana), (c_senores, d.beto), (c_ninos, d.caro)]:
        mesero.a_cocina(oid)
    d.reloj.a(11, 30)
    for oid, mesero in [(c_fondo, d.ana), (c_senores, d.beto), (c_ninos, d.caro)]:
        servir(oid, mesero)
    d.reloj.a(12, 0)
    cobro_efectivo('mesa compartida: fondo', c_fondo, d.ana, 500, propina=40)   # exacto
    d.beto.cobrar(c_senores, 'transferencia', libro.total(c_senores), referencia='BBVA 0091')
    libro.pago(c_senores, 'transferencia', libro.total(c_senores), verificado=False)
    assert db.session.get(Mesa, M['3'].id).estado == 'ocupada', \
        'la mesa se liberó con dos cuentas abiertas'
    cobro_efectivo('mesa compartida: niños', c_ninos, d.caro, 200)              # cambio 35
    d.reloj.a(12, 10)
    d.duena.confirmar(c_senores)
    libro.verificar_ultimo(c_senores)
    libro.ordenes[c_senores]['estado'] = 'pagada'
    db.session.expire_all()
    assert db.session.get(Mesa, M['3'].id).estado == 'disponible', \
        'la mesa no se liberó al pagar la última cuenta'

    # 12:20 · Para llevar cancelado: el taquero ya había marcado un pollo.
    d.reloj.a(12, 20)
    o6 = d.beto.para_llevar()
    libro.orden(o6, 'Beto')
    d.beto.pedir(o6, '1 Pollo para llevar', 2)
    d.beto.a_cocina(o6)
    d.tono.marcar(o6, OrdenDetalle.query.filter_by(orden_id=o6).first().id)
    d.reloj.a(12, 50)
    d.beto.cancelar(o6, 'tiempo_espera')
    libro.ordenes[o6]['estado'] = 'cancelada'

    # 12:40 · Cliente frecuente, mesa 4: 10% de descuento autorizado por la dueña.
    d.reloj.a(12, 40)
    o7 = d.ana.abrir_mesa(M['4'], personas=3)
    libro.orden(o7, 'Ana')
    for prod, q in [('Paquete: 1/2 kg barbacoa + 1 lt consomé', 1), ('Tlacoyo de requesón', 3),
                    ('Agua fresca (Jamaica)', 3)]:
        d.ana.pedir(o7, prod, q)
        libro.item(o7, prod, q)
    d.ana.a_cocina(o7)
    servir(o7, d.ana)
    d.ana.descuento(o7, 10, 'cliente de cada domingo', d.duena.email, d.duena.password)
    libro.ordenes[o7]['descuento'] = D('10')
    assert libro.total(o7) == D('503.10')
    cobro_efectivo('frecuente con descuento', o7, d.ana, 600, propina=50)       # cambio 46.90

    # 13:10 · Mesa 5: dedazo en el KDS; la transferencia nunca llega y pagan en efectivo.
    d.reloj.a(13, 10)
    o8 = d.caro.abrir_mesa(M['5'], personas=2)
    libro.orden(o8, 'Caro')
    for prod, q in [('1/4 kg Barbacoa', 1), ('Tlacoyo de frijol', 2), ('Refresco Coca-Cola', 1)]:
        d.caro.pedir(o8, prod, q)
        libro.item(o8, prod, q)
    d.caro.a_cocina(o8)
    barbacoa = OrdenDetalle.query.filter_by(orden_id=o8).first()
    d.tono.marcar(o8, barbacoa.id)
    d.tono.deshacer(o8, barbacoa.id)
    db.session.expire_all()
    assert db.session.get(OrdenDetalle, barbacoa.id).estado != 'listo'
    d.reloj.a(13, 25)
    servir(o8, d.caro)
    d.caro.cobrar(o8, 'transferencia', libro.total(o8), referencia='nombre: Paty R.')
    libro.pago(o8, 'transferencia', libro.total(o8), verificado=False)
    d.reloj.a(13, 50)
    d.duena.rechazar(o8)
    libro.quitar_ultimo(o8)
    cobro_efectivo('transferencia rechazada', o8, d.caro, 300)                  # cambio 69

    # 13:30 · Mesa 6: transferencia "en camino", el cliente se desespera y paga en
    # efectivo. Más tarde la dueña intenta confirmar la transferencia vieja.
    d.reloj.a(13, 30)
    o9 = d.beto.abrir_mesa(M['6'], personas=4)
    libro.orden(o9, 'Beto')
    d.beto.pedir(o9, '1 kg Barbacoa')
    libro.item(o9, '1 kg Barbacoa', 1)
    d.beto.a_cocina(o9)
    servir(o9, d.beto, d.tono)
    d.beto.cobrar(o9, 'transferencia', 550, referencia='SPEI 8820')
    libro.pago(o9, 'transferencia', 550, verificado=False)
    libro.quitar_ultimo(o9)   # en el libro no cuenta: nunca se confirma
    cobro_efectivo('pagó en efectivo con transferencia pendiente', o9, d.beto, 600)  # cambio 50
    d.reloj.a(14, 40)
    d.duena.confirmar(o9, esperar=409)
    d.duena.rechazar(o9)

    # 14:00 · Mesa 7, seis personas: pagan en partes. El primero da $600 de los
    # cuales $100 son propina; el resto llega por transferencia confirmada.
    d.reloj.a(14, 0)
    o10 = d.ana.abrir_mesa(M['7'], personas=6)
    libro.orden(o10, 'Ana')
    for prod, q in [('Paquete: 1 kg barbacoa + 2 lt consomé', 1), ('Plato de consomé', 6),
                    ('Refresco Coca-Cola', 6)]:
        d.ana.pedir(o10, prod, q)
        libro.item(o10, prod, q)
    d.ana.a_cocina(o10)
    servir(o10, d.ana)
    assert libro.total(o10) == D('1030.00')
    d.ana.cobrar(o10, 'efectivo', 600, propina=100)
    libro.pago(o10, 'efectivo', 500, propina=100)     # $500 a la cuenta + $100 de propina
    resto = libro.total(o10) - D('500')
    info = d.ana.c.get(f'/meseros/ordenes/{o10}/cobrar_info').get_json()
    assert D(str(info['saldo_pendiente'])).quantize(D('0.01')) == resto, \
        f'tras $600 con $100 de propina debían faltar ${resto}, el sistema dice ' \
        f'${info["saldo_pendiente"]}: tomó la propina como abono a la cuenta'
    d.ana.cobrar(o10, 'transferencia', resto, referencia='SPEI 3315')
    libro.pago(o10, 'transferencia', resto, verificado=False)
    d.reloj.a(14, 20)
    d.duena.confirmar(o10)
    libro.verificar_ultimo(o10)
    libro.ordenes[o10]['estado'] = 'pagada'

    # 15:00 · Mesa 8: se capturó mal, se cancela y se levanta otra vez.
    d.reloj.a(15, 0)
    o11 = d.caro.abrir_mesa(M['8'], personas=2)
    libro.orden(o11, 'Caro')
    d.caro.pedir(o11, '1 kg Carnitas')
    d.caro.a_cocina(o11)
    d.caro.cancelar(o11, 'error_orden')
    libro.ordenes[o11]['estado'] = 'cancelada'
    assert db.session.get(Mesa, M['8'].id).estado == 'disponible'
    o12 = d.caro.abrir_mesa(M['8'], personas=2)
    libro.orden(o12, 'Caro')
    d.caro.pedir(o12, '1/2 kg Carnitas')
    libro.item(o12, '1/2 kg Carnitas', 1)
    d.caro.a_cocina(o12)
    servir(o12, d.caro, d.tono)
    cobro_efectivo('relevantada', o12, d.caro, 150)

    # 15:30 · Hora pico: seis para llevar seguidos entre los tres meseros.
    pico = [(d.ana, 'Ana', [('Taco de cabeza', 4), ('Refresco Coca-Cola', 1)], 200, 0),
            (d.beto, 'Beto', [('1/2 kg Barbacoa', 1), ('1/2 litro de consomé', 2)], 350, 0),
            (d.caro, 'Caro', [('Quesadilla tinga', 3), ('Café', 2)], 160, 11),
            (d.ana, 'Ana', [('2 Pollos con 1 lt consomé', 1)], 200, 10),
            (d.beto, 'Beto', [('Taco de lengua', 2), ('Taco de ojo', 2)], 140, 0),
            (d.caro, 'Caro', [('Paquete: 1/4 kg barbacoa + 1 plato consomé', 2)], 400, 20)]
    for i, (mesero, nombre, items, recibido, propina) in enumerate(pico):
        d.reloj.a(15, 30 + i * 4)
        oid = mesero.para_llevar()
        libro.orden(oid, nombre)
        for prod, q in items:
            mesero.pedir(oid, prod, q)
            libro.item(oid, prod, q)
        mesero.a_cocina(oid)
        servir(oid, mesero)
        cobro_efectivo(f'pico {i + 1}', oid, mesero, recibido, propina)

    # 19:40 · Cena. Para UTC ya es lunes: estas ventas son del domingo.
    d.reloj.a(19, 40)
    o20 = d.ana.abrir_mesa(M['1'], personas=2)
    libro.orden(o20, 'Ana')
    for prod, q in [('1 Pollo para comer aquí', 2), ('Café', 2)]:
        d.ana.pedir(o20, prod, q)
        libro.item(o20, prod, q)
    d.ana.a_cocina(o20)
    servir(o20, d.ana)
    d.reloj.a(20, 30)
    cobro_efectivo('cena', o20, d.ana, 250, propina=20)

    # 20:15 · Para llevar por transferencia que además deja propina.
    d.reloj.a(20, 15)
    o21 = d.beto.para_llevar()
    libro.orden(o21, 'Beto')
    d.beto.pedir(o21, '2 Pollos con 1 lt consomé')
    libro.item(o21, '2 Pollos con 1 lt consomé', 1)
    d.beto.a_cocina(o21)
    servir(o21, d.beto, d.tono)
    d.beto.cobrar(o21, 'transferencia', libro.total(o21) + 30, propina=30, referencia='SPEI 5510')
    libro.pago(o21, 'transferencia', libro.total(o21), propina=30, verificado=False)
    d.reloj.a(20, 40)
    d.duena.confirmar(o21)
    libro.verificar_ultimo(o21)
    libro.ordenes[o21]['estado'] = 'pagada'

    # 21:00 · Última mesa: la transferencia sigue sin confirmar cuando se hace el corte.
    d.reloj.a(21, 0)
    o22 = d.caro.abrir_mesa(M['10'], personas=2)
    libro.orden(o22, 'Caro')
    d.caro.pedir(o22, '3/4 kg Barbacoa')
    libro.item(o22, '3/4 kg Barbacoa', 1)
    d.caro.a_cocina(o22)
    servir(o22, d.caro, d.tono)
    d.caro.cobrar(o22, 'transferencia', libro.total(o22), referencia='SPEI 9001')

    # ═════════ 22:30 · CIERRE ═════════
    d.reloj.a(22, 30)
    db.session.expire_all()
    pagadas = libro.pagadas()
    venta_esperada = sum(libro.total(oid) for oid in pagadas)
    propinas_esperadas = sum(o['propina'] for o in pagadas.values())

    # Cada cuenta, con el total que debió tener
    for oid in pagadas:
        orden = db.session.get(Orden, oid)
        assert orden.estado == OrdenEstado.PAGADA, f'orden {oid} no quedó pagada'
        assert D(str(orden.total)).quantize(D('0.01')) == libro.total(oid), \
            f'orden {oid}: total {orden.total}, debía ser {libro.total(oid)}'
    for oid in (o6, o11):
        assert db.session.get(Orden, oid).estado == OrdenEstado.CANCELADA
    # (Sale no guarda la orden: que las cancelaciones no generen venta lo prueba el
    #  conteo de abajo, una venta por cuenta pagada)

    # Cambio entregado en cada cobro en efectivo
    for escenario, esperado, dado in cambios:
        assert esperado == dado, f'{escenario}: el cambio debió ser ${esperado}, se dio ${dado}'

    # Ventas = pagos verificados aplicados a la cuenta
    ventas = Sale.query.all()
    assert len(ventas) == len(pagadas), 'hay órdenes pagadas sin venta (o ventas de más)'
    assert sum(D(str(v.total)) for v in ventas) == venta_esperada
    pagos_ok = Pago.query.filter_by(verificado=True).all()
    assert sum(D(str(p.monto)) for p in pagos_ok) == venta_esperada, 'pagos y ventas no cuadran'

    # La venta es del mesero que atendió, no de la dueña que confirmó
    por_mesero = {}
    for oid, o in pagadas.items():
        por_mesero[o['mesero']] = por_mesero.get(o['mesero'], D('0')) + libro.total(oid)

    # Dashboard y reportes del domingo
    duena = d.duena
    assert D(str(duena.json('/admin/api/dashboard/ventas_hoy')['ventasHoy'])) == venta_esperada
    assert D(str(duena.json('/admin/api/dashboard/propinas_hoy')['propinas'])) == propinas_esperadas
    assert duena.json('/admin/api/dashboard/ordenes_hoy')['ordenesHoy'] == len(pagadas)

    rango = f'?fecha_inicio={DOMINGO}&fecha_fin={DOMINGO}'
    rep = duena.json('/admin/reportes/api/ventas' + rango)
    assert rep['por_dia']['labels'] == [str(DOMINGO)], \
        f'las ventas se repartieron en {rep["por_dia"]["labels"]}: la cena se fue al lunes'
    assert D(str(rep['por_dia']['totales'][0])) == venta_esperada
    assert '20:00' in rep['por_hora']['labels'], 'la cena no aparece en ventas por hora'

    pagos_rep = duena.json('/admin/reportes/api/pagos' + rango)
    por_metodo = dict(zip(pagos_rep['labels'], pagos_rep['totales']))
    esperado_metodo = {}
    for o in pagadas.values():
        for p in o['pagos']:
            if p['verificado']:
                esperado_metodo[p['metodo']] = esperado_metodo.get(p['metodo'], D('0')) + p['aplicado']
    for metodo, monto in esperado_metodo.items():
        assert D(str(por_metodo.get(metodo.capitalize(), 0))).quantize(D('0.01')) == monto, \
            f'reporte de pagos, {metodo}: {por_metodo.get(metodo.capitalize())} vs {monto}'

    meseros_rep = duena.json('/admin/reportes/api/meseros' + rango)
    reporte_mesero = dict(zip(meseros_rep['labels'], meseros_rep['totales']))
    for nombre, monto in por_mesero.items():
        assert D(str(reporte_mesero.get(nombre, 0))).quantize(D('0.01')) == monto, \
            f'ventas de {nombre}: reporte {reporte_mesero.get(nombre)} vs {monto}'
    assert 'Doña Chela' not in reporte_mesero, 'a la dueña se le acreditaron ventas'

    top = duena.json('/admin/reportes/api/productos' + rango)['top_productos']
    vendidos = {}
    for o in pagadas.values():
        for prod, q in o['items'].items():
            vendidos[prod] = vendidos.get(prod, 0) + q
    for prod, q in zip(top['labels'], top['cantidades']):
        assert vendidos.get(prod) == q, f'top productos, {prod}: {q} vs {vendidos.get(prod)}'

    # Corte de caja contando el cajón exacto
    duena.ok(duena.c.post('/admin/corte-caja', data={'efectivo_contado': str(libro.efectivo_caja)}))
    corte = CorteCaja.query.order_by(CorteCaja.id.desc()).first()
    assert D(str(corte.efectivo_esperado)).quantize(D('0.01')) == libro.efectivo_caja, \
        f'el corte esperaba ${corte.efectivo_esperado} en el cajón, hay ${libro.efectivo_caja}'
    assert D(str(corte.diferencia)) == 0
    assert D(str(corte.transferencia_total)).quantize(D('0.01')) == esperado_metodo['transferencia']
    pantalla_corte = duena.c.get('/admin/corte-caja').get_data(as_text=True)
    assert 'por verificar' in pantalla_corte.lower() or 'por confirmar' in pantalla_corte.lower(), \
        'el corte no avisa de la transferencia de la mesa 10'

    # Mesas: sólo la 10 (su transferencia no se ha confirmado)
    ocupadas = {m.numero for m in Mesa.query.filter(Mesa.estado != 'disponible')}
    assert ocupadas == {'10'}, f'mesas que no se liberaron: {ocupadas}'

    # El borrador abandonado no dejó nada: ni mesa ocupada ni folio quemado
    folios = sorted(o.folio for o in Orden.query.filter(Orden.folio.isnot(None)))
    assert folios == list(range(1, len(folios) + 1)), f'folios con huecos: {folios}'
    assert db.session.get(Orden, borrador) is None or \
        db.session.get(Orden, borrador).folio is None

    # Cada cancelación dice por qué; el descuento dice quién lo autorizó
    motivos = [a.descripcion for a in AuditLog.query.filter_by(accion='cancelar')]
    assert len(motivos) == 2 and all('Motivo:' in m for m in motivos), motivos
    assert db.session.get(Orden, o7).descuento_autorizado_por is not None

    # ═════════ 00:10 · YA ES LUNES ═════════
    d.reloj.a(0, 10, dia=LUNES)
    assert D(str(duena.json('/admin/api/dashboard/ventas_hoy')['ventasHoy'])) == 0, \
        'el lunes arrancó con ventas del domingo'
    rep = duena.json('/admin/reportes/api/ventas' + rango)
    assert D(str(rep['por_dia']['totales'][0])) == venta_esperada, 'el domingo cambió al día siguiente'

    # Para revisar el domingo en el navegador:
    #   KAIREST_DOMINGO_DB=/ruta/domingo.db pytest tests/test_domingo.py
    # y levantar el server con DATABASE_URL=sqlite:////ruta/domingo.db
    destino = os.getenv('KAIREST_DOMINGO_DB')
    if destino:
        db.session.commit()
        crudo = db.engine.raw_connection()
        copia = sqlite3.connect(destino)
        crudo.driver_connection.backup(copia)
        copia.close()
        crudo.close()
