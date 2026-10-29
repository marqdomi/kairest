"""Personas por mesa: control real de ocupación.

Una mesa de 12 con dos clientes no está llena, pero el mosaico la pintaba igual
que una llena: el mesero no tenía forma de ver cuántos lugares quedaban para
sentar a alguien más. `Orden.num_personas` ya existía en el modelo y el POST ya
lo leía, pero la pantalla de elegir mesa nunca lo pedía ni lo mostraba.
"""
import pytest

from tests.conftest import login


def _onboarding_listo(db):
    from backend.models.models import ConfiguracionSistema
    if not ConfiguracionSistema.query.filter_by(clave='onboarding_completado').first():
        db.session.add(ConfiguracionSistema(clave='onboarding_completado', valor='true'))
        db.session.commit()


def _entrar(client, db, email='mesero_test@test.com'):
    _onboarding_listo(db)
    return login(client, email, 'Test1234!')


@pytest.fixture
def mesa_grande(db):
    from backend.models.models import Mesa
    m = Mesa(numero='12', capacidad=12, zona='interior', estado='disponible')
    db.session.add(m)
    db.session.commit()
    return m


@pytest.fixture
def producto_con_estacion(db, sample_categoria):
    from backend.models.models import Estacion, Producto
    est = Estacion(nombre='Parrilla')
    db.session.add(est)
    db.session.flush()
    p = Producto(nombre='Taco', precio=25, categoria_id=sample_categoria.id,
                 estacion_id=est.id)
    db.session.add(p)
    db.session.commit()
    return p


def _abrir_mesa(client, mesa, personas=None, forzar=False):
    datos = {'mesa_id': mesa.id}
    if personas is not None:
        datos['num_personas'] = personas
    if forzar:
        datos['forzar_nueva'] = '1'
    resp = client.post('/meseros/seleccionar_mesa', data=datos, follow_redirects=False)
    destino = resp.headers.get('Location') or ''
    return int(destino.rstrip('/').split('/')[-2]) if '/ordenes/' in destino else None


class TestCapturaDePersonas:
    def test_guarda_cuantas_personas_son(self, client, mesero_user, db, mesa_grande):
        from backend.models.models import Orden

        _entrar(client, db)
        oid = _abrir_mesa(client, mesa_grande, personas='2')
        assert db.session.get(Orden, oid).num_personas == 2

    def test_se_puede_omitir(self, client, mesero_user, db, mesa_grande):
        """No debe frenar el servicio: capturarlo es opcional."""
        from backend.models.models import Orden

        _entrar(client, db)
        oid = _abrir_mesa(client, mesa_grande)
        assert oid is not None
        assert db.session.get(Orden, oid).num_personas is None

    @pytest.mark.parametrize('valor', ['muchos', '', '-3', '0'])
    def test_un_valor_invalido_no_rompe_la_pantalla(self, client, mesero_user, db,
                                                    mesa_grande, valor):
        _entrar(client, db)
        resp = client.post('/meseros/seleccionar_mesa',
                           data={'mesa_id': mesa_grande.id, 'num_personas': valor})
        assert resp.status_code < 500

    def test_la_pantalla_ofrece_capturarlo(self, client, mesero_user, db, mesa_grande):
        _entrar(client, db)
        html = client.get('/meseros/seleccionar_mesa').data.decode()
        assert 'modalPersonas' in html
        assert 'data-abrir-mesa' in html
        assert f'data-mesa-capacidad="{mesa_grande.capacidad}"' in html


class TestOcupacionVisible:
    def test_muestra_ocupacion_y_lugares_libres(self, client, mesero_user, db,
                                                mesa_grande, producto_con_estacion):
        _entrar(client, db)
        oid = _abrir_mesa(client, mesa_grande, personas='2')
        client.post(f'/api/ordenes/{oid}/detalle',
                    json={'producto_id': producto_con_estacion.id, 'cantidad': 1})

        html = client.get('/meseros/seleccionar_mesa').data.decode()
        assert '2/12' in html, 'no se ve la ocupación real de la mesa'
        assert '10 lugares libres' in html

    def test_suma_las_personas_de_todas_las_cuentas(self, client, mesero_user, db,
                                                    mesa_grande, producto_con_estacion,
                                                    otro_mesero):
        """Mesas compartidas: la ocupación es la suma de sus cuentas activas."""
        _entrar(client, db)
        oid = _abrir_mesa(client, mesa_grande, personas='2')
        client.post(f'/api/ordenes/{oid}/detalle',
                    json={'producto_id': producto_con_estacion.id, 'cantidad': 1})

        _entrar(client, db, 'beto_test@test.com')
        oid2 = _abrir_mesa(client, mesa_grande, personas='3', forzar=True)
        client.post(f'/api/ordenes/{oid2}/detalle',
                    json={'producto_id': producto_con_estacion.id, 'cantidad': 1})

        html = client.get('/meseros/seleccionar_mesa').data.decode()
        assert '5/12' in html, 'no suma las cuentas de la misma mesa'
        assert '7 lugares libres' in html

    def test_al_cobrar_se_liberan_los_lugares(self, client, mesero_user, db, mesa_grande,
                                              producto_con_estacion):
        from backend.models.models import Orden, OrdenEstado

        _entrar(client, db)
        oid = _abrir_mesa(client, mesa_grande, personas='4')
        client.post(f'/api/ordenes/{oid}/detalle',
                    json={'producto_id': producto_con_estacion.id, 'cantidad': 1})

        html = client.get('/meseros/seleccionar_mesa').data.decode()
        assert '4/12' in html

        orden = db.session.get(Orden, oid)
        orden.estado = OrdenEstado.LISTA_PARA_ENTREGAR
        for d in orden.detalles:
            d.estado = OrdenEstado.LISTO
        db.session.commit()
        client.post(f'/meseros/ordenes/{oid}/pago',
                    json={'metodo': 'efectivo', 'monto': 25})

        html = client.get('/meseros/seleccionar_mesa').data.decode()
        assert '4/12' not in html, 'la mesa sigue contando gente que ya se fue'


class TestBorradoresEnElMosaico:
    def test_una_cuenta_vacia_no_ocupa_la_mesa(self, client, mesero_user, db, mesa_grande):
        """La mesa sólo se ocupa con el primer producto; el mosaico usaba otra
        regla y la pintaba ocupada desde que se abría la cuenta."""
        _entrar(client, db)
        _abrir_mesa(client, mesa_grande, personas='2')

        db.session.refresh(mesa_grande)
        assert mesa_grande.estado == 'disponible'

        html = client.get('/meseros/seleccionar_mesa').data.decode()
        assert 'data-abrir-mesa' in html
        assert f'data-mesa-numero="{mesa_grande.numero}"' in html, \
            'la mesa con sólo un borrador se pinta como ocupada'

    def test_con_producto_si_ocupa(self, client, mesero_user, db, mesa_grande,
                                   producto_con_estacion):
        """Control positivo del anterior."""
        _entrar(client, db)
        oid = _abrir_mesa(client, mesa_grande, personas='2')
        client.post(f'/api/ordenes/{oid}/detalle',
                    json={'producto_id': producto_con_estacion.id, 'cantidad': 1})

        db.session.refresh(mesa_grande)
        assert mesa_grande.estado == 'ocupada'

        html = client.get('/meseros/seleccionar_mesa').data.decode()
        assert f'data-mesa-numero="{mesa_grande.numero}"' not in html


@pytest.fixture
def otro_mesero(db):
    from backend.models.models import Usuario
    u = Usuario(nombre='Beto', email='beto_test@test.com', rol='mesero')
    u.set_password('Test1234!')
    db.session.add(u)
    db.session.commit()
    return u
