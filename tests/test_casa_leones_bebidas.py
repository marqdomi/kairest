"""Casa Leones: las bebidas las sirve el mesero (no hay quien atienda una pantalla).

En el puesto los refrescos están a la mano: el mesero los toma y los lleva. Con la
estación Bebidas marcada `la_sirve_mesero`:

- al enviar la orden, los refrescos quedan listos y el mesero los entrega de inmediato
- la cocina (Taquero, Comal) nunca los ve
- la orden se completa con lo que haga la cocina, aunque las bebidas ya se entregaron
- "¿me trae otro refresco?" a media comida no regresa la orden a cocina, y se puede
  pedir aunque ya se haya entregado todo; un taco extra sí regresa a cocina

Antes de esto, sin nadie en la pantalla de Bebidas, la mesa no se podía cobrar.
"""
from datetime import time
from decimal import Decimal
from types import SimpleNamespace

import pytest

from tests.test_domingo import (DOMINGO, _Cocina, _Duena, _Mesero, _Reloj,
                                _datetime_falso)

D = Decimal


@pytest.fixture
def casa_leones(app, db, monkeypatch):
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
    monkeypatch.setattr(acceso, 'dispositivo_actual',
                        lambda: SimpleNamespace(id=1, nombre='Tablet', ultimo_uso=None))

    db.session.add(Sucursal(nombre='Barbacoa Casa Leones'))
    ConfiguracionSistema.set('onboarding_completado', 'true')
    ConfiguracionSistema.set('metodos_pago', 'efectivo,transferencia')
    seed_from_template('casaleones')      # la plantilla ya marca Bebidas
    for n in range(1, 7):
        db.session.add(Mesa(numero=str(n), capacidad=6, estado='disponible'))
    est = {e.nombre: e for e in Estacion.query.all()}

    duena = Usuario(nombre='Doña Lety', email='lety@casaleones.mx', username='lety', rol='superadmin')
    duena.set_password('Lety2026xx')
    gente = {}
    for clave, nombre, pin in [('ana', 'Ana', '3691'), ('beto', 'Beto', '4826')]:
        u = Usuario(nombre=nombre, username=clave, rol='mesero')
        u.set_pin(pin)
        gente[clave] = (u, pin)
    for clave, nombre, pin, e in [('tono', 'Toño', '6148', 'Taquero'), ('lupe', 'Lupe', '7259', 'Comal')]:
        u = Usuario(nombre=nombre, username=clave, rol='cocina', estacion_id=est[e].id)
        u.set_pin(pin)
        gente[clave] = (u, pin, est[e])
    db.session.add(duena)
    db.session.add_all([v[0] for v in gente.values()])
    db.session.commit()

    menu = {p.nombre: p for p in Producto.query.all()}
    return SimpleNamespace(
        reloj=reloj, menu=menu, est=est, mesas={m.numero: m for m in Mesa.query.all()},
        duena=_Duena(app, duena, 'Lety2026xx'),
        ana=_Mesero(app, *gente['ana'], menu), beto=_Mesero(app, *gente['beto'], menu),
        tono=_Cocina(app, *gente['tono']), lupe=_Cocina(app, *gente['lupe']),
    )


def _renglones(oid):
    from backend.models.models import OrdenDetalle
    return {d.producto.nombre: d for d in OrdenDetalle.query.filter_by(orden_id=oid)}


def _estado(db, oid):
    from backend.models.models import Orden
    db.session.expire_all()
    return db.session.get(Orden, oid).estado


def _en_kds(cocina, oid):
    html = cocina.c.get(f'/cocina/{cocina.slug}/fragmento_ordenes').get_data(as_text=True)
    return f'kds-orden-{oid}' in html, html


def test_la_plantilla_de_casa_leones_marca_bebidas(casa_leones):
    est = casa_leones.est
    assert est['Bebidas'].la_sirve_mesero is True
    assert est['Taquero'].la_sirve_mesero is False and est['Comal'].la_sirve_mesero is False


def test_un_servicio_en_casa_leones(casa_leones, db):
    from backend.models.models import AuditLog, Mesa, Orden, Pago, Sale
    from backend.services.printer import generar_texto_comanda

    c = casa_leones
    M = c.mesas
    esperado = {}

    # 13:00 · Mesa 1, familia: tacos, quesadillas y cuatro refrescos
    c.reloj.ahora = c.reloj.ahora.replace(hour=13)
    o1 = c.ana.abrir_mesa(M['1'], personas=4)
    pedido = [('Taco de maciza', 4), ('Quesadilla de queso', 2), ('Refresco Coca-Cola', 4)]
    for prod, q in pedido:
        c.ana.pedir(o1, prod, q)
    c.ana.a_cocina(o1)

    r = _renglones(o1)
    assert r['Refresco Coca-Cola'].estado == 'listo', \
        'los refrescos deben quedar listos al enviar: nadie atiende una pantalla de Bebidas'
    assert r['Taco de maciza'].estado == 'pendiente'

    # La cocina sólo ve lo suyo; Bebidas no aparece en ninguna pantalla
    visible, html = _en_kds(c.tono, o1)
    assert visible and 'Refresco' not in html, 'el taquero ve los refrescos'
    estaciones = c.ana.c.get('/cocina/api/estaciones').get_json()
    nombres = [e['nombre'] for e in (estaciones if isinstance(estaciones, list) else estaciones['estaciones'])]
    assert 'Bebidas' not in nombres, 'Bebidas sigue apareciendo como pantalla de cocina'
    assert 'Refresco' not in generar_texto_comanda(db.session.get(Orden, o1)), \
        'la comanda de cocina trae los refrescos'

    # El mesero lleva los refrescos de inmediato, antes que la comida
    c.ana.ok(c.ana.c.post(f'/meseros/entregar_item/{o1}/{r["Refresco Coca-Cola"].id}'))
    c.tono.terminar(o1)
    c.lupe.terminar(o1)
    assert _estado(db, o1) == 'lista_para_entregar', \
        'con los refrescos ya entregados, la comida lista no marcó la orden como lista'
    c.ana.entregar(o1)
    assert _estado(db, o1) == 'completada'
    esperado[o1] = D('4') * 35 + 2 * 33 + 4 * 25            # 306
    c.ana.cobrar(o1, 'efectivo', 350, propina=20)

    # 13:20 · Mesa 2: "¿me trae otro refresco?" con la comida ya lista, y otra vez
    # cuando ya se entregó todo
    o2 = c.beto.abrir_mesa(M['2'], personas=2)
    c.beto.pedir(o2, '1/2 kg Barbacoa')
    c.beto.pedir(o2, 'Jugo Boing (mango)', 2)
    c.beto.a_cocina(o2)
    c.tono.terminar(o2)
    assert _estado(db, o2) == 'lista_para_entregar'
    c.beto.pedir(o2, 'Refresco Coca-Cola')
    assert _estado(db, o2) == 'lista_para_entregar', \
        'un refresco extra regresó la orden a cocina'
    assert not _en_kds(c.tono, o2)[0], 'la orden reapareció en el KDS por un refresco'
    c.beto.entregar(o2)
    assert _estado(db, o2) == 'completada'
    c.beto.pedir(o2, 'Café')        # antes: 409, no se podía agregar a una cuenta entregada
    assert _estado(db, o2) == 'lista_para_entregar'
    c.beto.entregar(o2)
    assert _estado(db, o2) == 'completada'
    esperado[o2] = D('280') + 2 * 25 + 25 + 25                # 380

    # Y un taco extra al final sí regresa a la cocina
    c.beto.pedir(o2, 'Taco de cabeza', 2)
    assert _estado(db, o2) == 'en_preparacion', 'el taco extra no regresó la orden a cocina'
    assert _en_kds(c.tono, o2)[0], 'el taco extra no le llegó al taquero'
    c.tono.terminar(o2)
    c.beto.entregar(o2)
    esperado[o2] += 2 * 35                                    # 450
    c.beto.cobrar(o2, 'transferencia', esperado[o2], referencia='SPEI 2020')
    c.duena.confirmar(o2)

    # 13:40 · Para llevar de puras bebidas: no pasa por ninguna cocina
    o3 = c.ana.para_llevar()
    c.ana.pedir(o3, 'Jugo Boing (guayaba)', 2)
    c.ana.pedir(o3, 'Agua fresca (Jamaica)', 1)
    c.ana.a_cocina(o3)
    assert _estado(db, o3) == 'lista_para_entregar', 'unas bebidas para llevar se quedaron esperando'
    c.ana.entregar(o3)
    esperado[o3] = D('2') * 25 + 40                          # 90
    c.ana.cobrar(o3, 'efectivo', 100)

    # 14:00 · Mesa 3: quitar un refresco ya entregado no se puede (ya se lo tomaron);
    # uno que todavía no se lleva, sí
    o4 = c.beto.abrir_mesa(M['3'], personas=2)
    c.beto.pedir(o4, 'Tlacoyo de frijol', 2)
    c.beto.pedir(o4, 'Refresco Coca-Cola', 1)
    c.beto.a_cocina(o4)
    c.beto.pedir(o4, 'Café', 1)
    r = _renglones(o4)
    c.beto.ok(c.beto.c.post(f'/meseros/entregar_item/{o4}/{r["Refresco Coca-Cola"].id}'))
    resp = c.beto.c.delete(f'/api/ordenes/{o4}/detalle/{r["Refresco Coca-Cola"].id}')
    assert resp.status_code == 409, 'se pudo quitar un refresco que ya se entregó'
    c.beto.quitar(o4, r['Café'].id)
    c.lupe.terminar(o4)
    assert _estado(db, o4) == 'lista_para_entregar'
    c.beto.entregar(o4)
    esperado[o4] = D('2') * 33 + 25                          # 91
    c.beto.cobrar(o4, 'efectivo', 91)

    # 14:20 · Mesa 4: se van después de tomarse los refrescos; se cancela con motivo
    o5 = c.ana.abrir_mesa(M['4'], personas=3)
    c.ana.pedir(o5, '1 kg Barbacoa')
    c.ana.pedir(o5, 'Refresco Coca-Cola', 3)
    c.ana.a_cocina(o5)
    c.ana.entregar(o5)
    c.ana.cancelar(o5, 'otro', 'se fueron; sólo se tomaron los refrescos')
    assert _estado(db, o5) == 'cancelada'

    # ═══ Cierre ═══
    db.session.expire_all()
    for oid, total in esperado.items():
        orden = db.session.get(Orden, oid)
        assert orden.estado == 'pagada', f'orden {oid} quedó {orden.estado}'
        assert D(str(orden.total)).quantize(D('0.01')) == total, f'orden {oid}: {orden.total} vs {total}'
    assert sum(D(str(s.total)) for s in Sale.query.all()) == sum(esperado.values())
    assert sum(D(str(p.monto)) for p in Pago.query.filter_by(verificado=True)) == sum(esperado.values())
    assert Mesa.query.filter(Mesa.estado != 'disponible').count() == 0
    cancelacion = AuditLog.query.filter_by(accion='cancelar').one()
    assert 'sólo se tomaron los refrescos' in cancelacion.descripcion


def test_la_duena_lo_activa_con_ordenes_abiertas(app, db, casa_leones):
    """Casa Leones ya instalado antes de esta función: Bebidas era una pantalla más.
    Al marcarla, los refrescos que estaban esperando quedan listos al momento."""
    from backend.models.models import Estacion
    c = casa_leones
    bebidas = c.est['Bebidas']
    bebidas.la_sirve_mesero = False
    db.session.commit()

    o = c.ana.abrir_mesa(c.mesas['5'], personas=2)
    c.ana.pedir(o, 'Taco de maciza', 2)
    c.ana.pedir(o, 'Refresco Coca-Cola', 2)
    c.ana.a_cocina(o)
    c.tono.terminar(o)
    assert _estado(db, o) == 'en_preparacion', 'sin la casilla, la orden espera a Bebidas'

    c.duena.ok(c.duena.c.post(f'/admin/estaciones/{bebidas.id}/editar',
                              data={'nombre': 'Bebidas', 'la_sirve_mesero': '1'}))
    db.session.expire_all()
    assert db.session.get(Estacion, bebidas.id).la_sirve_mesero is True
    assert _estado(db, o) == 'lista_para_entregar', 'los refrescos que esperaban no se liberaron'


def test_pantalla_de_bebidas_y_roles(casa_leones, db):
    c = casa_leones
    resp = c.duena.c.get('/cocina/bebidas')
    assert resp.status_code == 200 and 'no tiene pantalla' in resp.get_data(as_text=True)
    form = c.duena.c.get('/admin/usuarios/nuevo').get_data(as_text=True)
    assert 'cocina:Bebidas' not in form, 'se puede dar de alta a alguien en una estación sin pantalla'
    assert 'cocina:Taquero' in form
    tabs = c.ana.c.get('/meseros/').get_data(as_text=True)
    assert '/cocina/bebidas' not in tabs, 'la barra del mesero sigue mostrando la pestaña Bebidas'


def test_wizard_respeta_la_casilla(client, db, superadmin_user):
    """En el paso 3 la casilla viene marcada para Bebidas; si se desmarca, Bebidas
    queda como pantalla normal."""
    from backend.models.models import Estacion
    client.post('/setup/paso/3', data={
        'opcion_menu': 'casaleones',
        'estacion_nombre[]': ['Taquero', 'Comal', 'Bebidas'],
        'estacion_destino[]': ['0', '1', '2'],
        'estacion_mesero[]': ['1'],      # el dueño decide que el Comal lo sirve el mesero
    })
    est = {e.nombre: e for e in Estacion.query.all()}
    assert est['Comal'].la_sirve_mesero is True
    assert est['Bebidas'].la_sirve_mesero is False
    assert est['Taquero'].la_sirve_mesero is False
