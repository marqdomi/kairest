"""Auditoría del KDS de cocina.

El hallazgo: `batch-listo` movía la orden de "enviado" a "en preparación" antes
de comprobar si algún item calificaba, así que un batch que no marcaba nada
(ids de otra estación, o ya listos) igual sacaba la orden de la cola y le
avisaba al mesero por Socket.IO que ya la estaban preparando.

El resto (aislamiento entre estaciones, ventana de undo, 409 en órdenes
cerradas) ya funcionaba; queda cubierto para que no se rompa.
"""
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
def estaciones(db):
    from backend.models.models import Estacion
    parrilla = Estacion(nombre='Parrilla')
    bebidas = Estacion(nombre='Bebidas')
    db.session.add_all([parrilla, bebidas])
    db.session.commit()
    return {'parrilla': parrilla, 'bebidas': bebidas}


@pytest.fixture
def productos(db, sample_categoria, estaciones):
    from backend.models.models import Producto
    taco = Producto(nombre='Taco', precio=25, categoria_id=sample_categoria.id,
                    estacion_id=estaciones['parrilla'].id)
    agua = Producto(nombre='Agua', precio=20, categoria_id=sample_categoria.id,
                    estacion_id=estaciones['bebidas'].id)
    db.session.add_all([taco, agua])
    db.session.commit()
    return {'taco': taco, 'agua': agua}


@pytest.fixture
def cocinero_parrilla(db, estaciones):
    from backend.models.models import Usuario
    u = Usuario(nombre='CociP', email='cocip@test.com', rol='cocina',
                estacion_id=estaciones['parrilla'].id)
    u.set_password('Test1234!')
    db.session.add(u)
    db.session.commit()
    return u


@pytest.fixture
def orden_mixta(db, mesero_user, sample_mesa, productos):
    """Orden enviada a cocina con un item de Parrilla y otro de Bebidas."""
    from backend.models.models import Orden, OrdenDetalle, OrdenEstado
    o = Orden(mesa_id=sample_mesa.id, mesero_id=mesero_user.id, estado=OrdenEstado.ENVIADO)
    db.session.add(o)
    db.session.flush()
    d_taco = OrdenDetalle(orden_id=o.id, producto_id=productos['taco'].id, cantidad=1,
                          precio_unitario=25, estado=OrdenEstado.PENDIENTE)
    d_agua = OrdenDetalle(orden_id=o.id, producto_id=productos['agua'].id, cantidad=1,
                          precio_unitario=20, estado=OrdenEstado.PENDIENTE)
    db.session.add_all([d_taco, d_agua])
    db.session.commit()
    return {'orden': o, 'taco': d_taco, 'agua': d_agua}


class TestBatchListo:
    def test_batch_sin_items_validos_no_mueve_la_orden(self, client, superadmin_user, db,
                                                       orden_mixta):
        """El bug: la orden salía de "enviado" aunque no se marcara nada."""
        from backend.models.models import OrdenEstado

        orden = orden_mixta['orden']
        agua = orden_mixta['agua']          # es de Bebidas, no de Parrilla

        _entrar(client, db, 'super_test@test.com')
        resp = client.post('/cocina/parrilla/batch-listo',
                           json={'orden_id': orden.id, 'detalle_ids': [agua.id]})
        assert resp.status_code == 200

        db.session.refresh(orden)
        db.session.refresh(agua)
        assert agua.estado != OrdenEstado.LISTO
        assert orden.estado == OrdenEstado.ENVIADO, \
            'la orden se movió a en_preparacion sin que nadie la empezara'

    def test_batch_valido_si_mueve_la_orden(self, client, superadmin_user, db, orden_mixta):
        """Control positivo: si el batch nunca transicionara, el test de arriba
        pasaría por la razón equivocada."""
        from backend.models.models import OrdenEstado

        orden = orden_mixta['orden']
        taco = orden_mixta['taco']

        _entrar(client, db, 'super_test@test.com')
        resp = client.post('/cocina/parrilla/batch-listo',
                           json={'orden_id': orden.id, 'detalle_ids': [taco.id]})
        assert resp.status_code == 200

        db.session.refresh(orden)
        db.session.refresh(taco)
        assert taco.estado == OrdenEstado.LISTO
        assert orden.estado == OrdenEstado.EN_PREPARACION

    def test_batch_no_toca_ordenes_cerradas(self, client, superadmin_user, db, orden_mixta):
        from backend.models.models import OrdenEstado

        orden = orden_mixta['orden']
        orden.estado = OrdenEstado.CANCELADA
        db.session.commit()

        _entrar(client, db, 'super_test@test.com')
        resp = client.post('/cocina/parrilla/batch-listo',
                           json={'orden_id': orden.id,
                                 'detalle_ids': [orden_mixta['taco'].id]})
        assert resp.status_code == 409

        db.session.refresh(orden_mixta['taco'])
        assert orden_mixta['taco'].estado != OrdenEstado.LISTO

    def test_batch_sin_body_avisa(self, client, superadmin_user, db, estaciones):
        _entrar(client, db, 'super_test@test.com')
        assert client.post('/cocina/parrilla/batch-listo', json={}).status_code == 400


class TestAislamientoEntreEstaciones:
    def test_cocinero_no_abre_el_kds_de_otra_estacion(self, client, cocinero_parrilla, db):
        _entrar(client, db, 'cocip@test.com')
        assert client.get('/cocina/parrilla').status_code == 200
        assert client.get('/cocina/bebidas').status_code == 403

    def test_el_kds_solo_muestra_los_items_de_su_estacion(self, client, superadmin_user,
                                                          db, orden_mixta):
        _entrar(client, db, 'super_test@test.com')
        html = client.get('/cocina/parrilla').data.decode()
        assert 'Taco' in html
        assert 'Agua' not in html

    def test_no_marca_items_de_otra_estacion(self, client, superadmin_user, db, orden_mixta):
        from backend.models.models import OrdenEstado

        _entrar(client, db, 'super_test@test.com')
        resp = client.post(
            f"/cocina/parrilla/marcar/{orden_mixta['orden'].id}/{orden_mixta['agua'].id}")
        assert resp.status_code == 403

        db.session.refresh(orden_mixta['agua'])
        assert orden_mixta['agua'].estado != OrdenEstado.LISTO

    def test_rechaza_detalle_de_otra_orden(self, client, superadmin_user, db, orden_mixta,
                                           mesero_user, sample_mesa):
        from backend.models.models import Orden, OrdenEstado

        otra = Orden(mesa_id=sample_mesa.id, mesero_id=mesero_user.id,
                     estado=OrdenEstado.ENVIADO)
        db.session.add(otra)
        db.session.commit()

        _entrar(client, db, 'super_test@test.com')
        resp = client.post(f"/cocina/parrilla/marcar/{otra.id}/{orden_mixta['taco'].id}")
        assert resp.status_code == 400


class TestCicloDeVida:
    def test_primer_item_pasa_a_en_preparacion(self, client, superadmin_user, db, orden_mixta):
        from backend.models.models import OrdenEstado

        _entrar(client, db, 'super_test@test.com')
        client.post(f"/cocina/parrilla/marcar/{orden_mixta['orden'].id}/{orden_mixta['taco'].id}")

        db.session.refresh(orden_mixta['orden'])
        assert orden_mixta['orden'].estado == OrdenEstado.EN_PREPARACION

    def test_todos_los_items_pasan_a_lista_para_entregar(self, client, superadmin_user,
                                                         db, orden_mixta):
        from backend.models.models import OrdenEstado

        _entrar(client, db, 'super_test@test.com')
        oid = orden_mixta['orden'].id
        client.post(f"/cocina/parrilla/marcar/{oid}/{orden_mixta['taco'].id}")
        client.post(f"/cocina/bebidas/marcar/{oid}/{orden_mixta['agua'].id}")

        db.session.refresh(orden_mixta['orden'])
        assert orden_mixta['orden'].estado == OrdenEstado.LISTA_PARA_ENTREGAR

    def test_no_marca_en_orden_cancelada(self, client, superadmin_user, db, orden_mixta):
        from backend.models.models import OrdenEstado

        orden_mixta['orden'].estado = OrdenEstado.CANCELADA
        db.session.commit()

        _entrar(client, db, 'super_test@test.com')
        resp = client.post(
            f"/cocina/parrilla/marcar/{orden_mixta['orden'].id}/{orden_mixta['taco'].id}")
        assert resp.status_code == 409


class TestDeshacer:
    def _marcar(self, client, orden_mixta):
        return client.post(
            f"/cocina/parrilla/marcar/{orden_mixta['orden'].id}/{orden_mixta['taco'].id}")

    def test_undo_regresa_el_item_y_la_orden(self, client, superadmin_user, db, orden_mixta):
        """Si la orden ya había salido del KDS, debe reaparecer para que el
        mesero no entregue de más."""
        from backend.models.models import OrdenEstado

        _entrar(client, db, 'super_test@test.com')
        oid = orden_mixta['orden'].id
        self._marcar(client, orden_mixta)
        client.post(f"/cocina/bebidas/marcar/{oid}/{orden_mixta['agua'].id}")
        db.session.refresh(orden_mixta['orden'])
        assert orden_mixta['orden'].estado == OrdenEstado.LISTA_PARA_ENTREGAR

        resp = client.post(f"/cocina/parrilla/desmarcar/{oid}/{orden_mixta['taco'].id}")
        assert resp.status_code == 200

        db.session.refresh(orden_mixta['taco'])
        db.session.refresh(orden_mixta['orden'])
        assert orden_mixta['taco'].estado == OrdenEstado.PENDIENTE
        assert orden_mixta['orden'].estado == OrdenEstado.EN_PREPARACION

    def test_undo_fuera_de_la_ventana_se_rechaza(self, client, superadmin_user, db,
                                                 orden_mixta):
        from datetime import timedelta
        from backend.models.models import utc_now
        from backend.routes.cocina import UNDO_LISTO_SEGUNDOS

        _entrar(client, db, 'super_test@test.com')
        self._marcar(client, orden_mixta)

        db.session.refresh(orden_mixta['taco'])
        orden_mixta['taco'].fecha_listo = (utc_now().replace(tzinfo=None)
                                           - timedelta(seconds=UNDO_LISTO_SEGUNDOS + 60))
        db.session.commit()

        resp = client.post(
            f"/cocina/parrilla/desmarcar/{orden_mixta['orden'].id}/{orden_mixta['taco'].id}")
        assert resp.status_code == 409

    def test_undo_de_item_de_otra_estacion_se_rechaza(self, client, superadmin_user, db,
                                                      orden_mixta):
        _entrar(client, db, 'super_test@test.com')
        oid = orden_mixta['orden'].id
        client.post(f"/cocina/bebidas/marcar/{oid}/{orden_mixta['agua'].id}")

        resp = client.post(f"/cocina/parrilla/desmarcar/{oid}/{orden_mixta['agua'].id}")
        assert resp.status_code == 403


class TestSlugDeEstacion:
    """El KDS se resuelve por slug: dos nombres que normalizan igual comparten
    dirección y sólo se alcanza uno. Los items del otro no se pueden marcar
    listos y su orden queda incobrable.
    """

    @pytest.mark.parametrize('primero,segundo', [
        ('Plancha Fria', 'Plancha Fría'),   # acento
        ('Bar', 'Bar!'),                    # puntuación
        ('Sushi Bar', 'Sushi-Bar'),         # separador
    ])
    def test_no_admite_dos_estaciones_con_el_mismo_slug(self, client, superadmin_user, db,
                                                        primero, segundo):
        from backend.models.models import Estacion

        _entrar(client, db, 'super_test@test.com')
        client.post('/admin/estaciones/nueva', data={'nombre': primero})
        client.post('/admin/estaciones/nueva', data={'nombre': segundo})

        assert Estacion.query.count() == 1, \
            f'"{primero}" y "{segundo}" coexisten y comparten URL de KDS'

    def test_nombres_realmente_distintos_si_conviven(self, client, superadmin_user, db):
        """Control positivo: la validación no debe bloquear nombres legítimos."""
        from backend.models.models import Estacion

        _entrar(client, db, 'super_test@test.com')
        client.post('/admin/estaciones/nueva', data={'nombre': 'Parrilla'})
        client.post('/admin/estaciones/nueva', data={'nombre': 'Plancha'})
        assert Estacion.query.count() == 2

    def test_tampoco_al_renombrar(self, client, superadmin_user, db):
        from backend.models.models import Estacion

        _entrar(client, db, 'super_test@test.com')
        client.post('/admin/estaciones/nueva', data={'nombre': 'Plancha Fria'})
        client.post('/admin/estaciones/nueva', data={'nombre': 'Parrilla'})
        parrilla = Estacion.query.filter_by(nombre='Parrilla').first()

        client.post(f'/admin/estaciones/{parrilla.id}/editar',
                    data={'nombre': 'Plancha Fría'})

        db.session.refresh(parrilla)
        assert parrilla.nombre == 'Parrilla'

    def test_renombrar_mueve_el_kds_al_slug_nuevo(self, client, superadmin_user, db,
                                                  estaciones):
        _entrar(client, db, 'super_test@test.com')
        client.post(f"/admin/estaciones/{estaciones['parrilla'].id}/editar",
                    data={'nombre': 'Parrilla Norte'})

        assert client.get('/cocina/parrilla').status_code == 404
        assert client.get('/cocina/parrilla-norte').status_code == 200


class TestProductoSinEstacion:
    """Un producto sin estación no aparece en ningún KDS: nadie lo prepara, la
    orden nunca pasa a lista_para_entregar y no se puede cobrar.
    """

    @pytest.fixture
    def orden_con_huerfano(self, db, mesero_user, sample_mesa, sample_categoria, productos):
        from backend.models.models import Orden, OrdenDetalle, OrdenEstado, Producto

        huerfano = Producto(nombre='Huerfano', precio=30,
                            categoria_id=sample_categoria.id, estacion_id=None)
        db.session.add(huerfano)
        db.session.flush()

        o = Orden(mesa_id=sample_mesa.id, mesero_id=mesero_user.id,
                  estado=OrdenEstado.ENVIADO)
        db.session.add(o)
        db.session.flush()
        d_taco = OrdenDetalle(orden_id=o.id, producto_id=productos['taco'].id,
                              cantidad=1, precio_unitario=25, estado=OrdenEstado.PENDIENTE)
        d_h = OrdenDetalle(orden_id=o.id, producto_id=huerfano.id, cantidad=1,
                           precio_unitario=30, estado=OrdenEstado.PENDIENTE)
        db.session.add_all([d_taco, d_h])
        db.session.commit()
        return {'orden': o, 'taco': d_taco, 'huerfano_detalle': d_h, 'producto': huerfano}

    def test_la_alta_por_la_ui_no_deja_crear_huerfanos(self, client, superadmin_user, db,
                                                       sample_categoria, estaciones):
        from backend.models.models import Producto

        _entrar(client, db, 'super_test@test.com')
        client.post('/admin/productos/nuevo', data={
            'nombre': 'Sin Estacion', 'precio': '30',
            'categoria_id': str(sample_categoria.id),
        })
        assert Producto.query.filter_by(nombre='Sin Estacion').first() is None

    def test_la_orden_con_huerfano_queda_atorada(self, client, superadmin_user, db,
                                                 orden_con_huerfano):
        """Documenta la consecuencia que justifica el aviso y la recuperación."""
        from backend.models.models import OrdenEstado

        _entrar(client, db, 'super_test@test.com')
        oid = orden_con_huerfano['orden'].id
        client.post(f"/cocina/parrilla/marcar/{oid}/{orden_con_huerfano['taco'].id}")

        db.session.refresh(orden_con_huerfano['orden'])
        assert orden_con_huerfano['orden'].estado == OrdenEstado.EN_PREPARACION

    def test_estaciones_avisa_de_los_huerfanos(self, client, superadmin_user, db,
                                               orden_con_huerfano, estaciones):
        _entrar(client, db, 'super_test@test.com')
        html = client.get('/admin/estaciones').data.decode()
        assert 'sin estación' in html
        assert 'Huerfano' in html

    def test_asignar_estacion_destraba_la_orden_abierta(self, client, superadmin_user, db,
                                                        orden_con_huerfano, estaciones,
                                                        sample_categoria):
        """La salida del problema: el KDS resuelve la estación al consultar, así
        que la orden ya abierta se corrige sola."""
        from backend.models.models import OrdenEstado

        _entrar(client, db, 'super_test@test.com')
        oid = orden_con_huerfano['orden'].id
        client.post(f"/cocina/parrilla/marcar/{oid}/{orden_con_huerfano['taco'].id}")

        client.post(f"/admin/productos/{orden_con_huerfano['producto'].id}/editar", data={
            'nombre': 'Huerfano', 'precio': '30',
            'categoria_id': str(sample_categoria.id),
            'estacion_id': str(estaciones['parrilla'].id),
        })

        html = client.get('/cocina/parrilla').data.decode()
        assert 'Huerfano' in html, 'el item atorado sigue invisible en el KDS'

        resp = client.post(
            f"/cocina/parrilla/marcar/{oid}/{orden_con_huerfano['huerfano_detalle'].id}")
        assert resp.status_code == 200

        db.session.refresh(orden_con_huerfano['orden'])
        assert orden_con_huerfano['orden'].estado == OrdenEstado.LISTA_PARA_ENTREGAR


class TestAsignacionDeCocinerosAEstaciones:
    """Es la única vía para dar de alta cocina después de la instalación.

    El selector manda "cocina:<Estación>". Si esa estación no resolvía, el
    usuario se creaba con `estacion_id` nulo: al entrar, el KDS lo mandaba a la
    primera estación y le respondía 403. Se quedaba sin poder trabajar y sin
    ningún mensaje que lo explicara.
    """

    @staticmethod
    def _sesion_de(client, usuario):
        with client.session_transaction() as s:
            s['user_id'] = usuario.id
            s['rol'] = usuario.rol
            if usuario.estacion_id:
                s['estacion_id'] = usuario.estacion_id

    def test_alta_con_estacion_valida(self, client, superadmin_user, db, estaciones):
        from backend.models.models import Usuario

        _entrar(client, db, 'super_test@test.com')
        client.post('/admin/usuarios/nuevo', data={
            'nombre': 'Coci', 'email': 'nuevo_coci@test.com',
            'rol': 'cocina:Parrilla', 'password': 'Test1234!',
        })

        u = Usuario.query.filter_by(email='nuevo_coci@test.com').first()
        assert u is not None
        assert u.rol == 'cocina'
        assert u.estacion_id == estaciones['parrilla'].id

    def test_el_cocinero_aterriza_en_su_estacion(self, client, superadmin_user, db,
                                                 estaciones):
        from backend.models.models import Usuario

        _entrar(client, db, 'super_test@test.com')
        client.post('/admin/usuarios/nuevo', data={
            'nombre': 'Coci', 'email': 'nuevo_coci@test.com',
            'rol': 'cocina:Parrilla', 'password': 'Test1234!',
        })
        u = Usuario.query.filter_by(email='nuevo_coci@test.com').first()

        self._sesion_de(client, u)
        resp = client.get('/cocina/', follow_redirects=False)
        assert 'parrilla' in (resp.headers.get('Location') or '')
        assert client.get('/cocina/parrilla').status_code == 200
        assert client.get('/cocina/bebidas').status_code == 403

    def test_reasignar_a_otra_estacion(self, client, superadmin_user, db, estaciones):
        from backend.models.models import Usuario

        _entrar(client, db, 'super_test@test.com')
        client.post('/admin/usuarios/nuevo', data={
            'nombre': 'Coci', 'email': 'nuevo_coci@test.com',
            'rol': 'cocina:Parrilla', 'password': 'Test1234!',
        })
        u = Usuario.query.filter_by(email='nuevo_coci@test.com').first()

        client.post(f'/admin/usuarios/{u.id}/editar', data={
            'nombre': 'Coci', 'email': 'nuevo_coci@test.com', 'rol': 'cocina:Bebidas',
        })
        db.session.refresh(u)
        assert u.estacion_id == estaciones['bebidas'].id

        self._sesion_de(client, u)
        assert client.get('/cocina/bebidas').status_code == 200
        assert client.get('/cocina/parrilla').status_code == 403

    def test_no_crea_un_cocinero_sin_estacion_valida(self, client, superadmin_user, db,
                                                     estaciones):
        from backend.models.models import Usuario

        _entrar(client, db, 'super_test@test.com')
        client.post('/admin/usuarios/nuevo', data={
            'nombre': 'Fantasma', 'email': 'fantasma@test.com',
            'rol': 'cocina:Estacion Que No Existe', 'password': 'Test1234!',
        })
        assert Usuario.query.filter_by(email='fantasma@test.com').first() is None, \
            'se creó un usuario de cocina que al entrar recibe 403'

    def test_editar_a_una_estacion_inexistente_no_lo_deja_huerfano(self, client,
                                                                   superadmin_user, db,
                                                                   estaciones):
        from backend.models.models import Usuario

        _entrar(client, db, 'super_test@test.com')
        client.post('/admin/usuarios/nuevo', data={
            'nombre': 'Coci', 'email': 'nuevo_coci@test.com',
            'rol': 'cocina:Parrilla', 'password': 'Test1234!',
        })
        u = Usuario.query.filter_by(email='nuevo_coci@test.com').first()

        client.post(f'/admin/usuarios/{u.id}/editar', data={
            'nombre': 'Coci', 'email': 'nuevo_coci@test.com', 'rol': 'cocina:No Existe',
        })
        db.session.refresh(u)
        assert u.estacion_id == estaciones['parrilla'].id, \
            'se quedó sin estación y no puede abrir ningún KDS'

    @pytest.fixture
    def wizard_listo(self, db, superadmin_user, sample_mesa, estaciones):
        """Paso 5 exige pasos previos: superadmin y mesas."""
        from backend.models.models import ConfiguracionSistema, Sucursal

        db.session.add(Sucursal(nombre='Puesto'))
        ConfiguracionSistema.set('nombre_negocio', 'Puesto')
        db.session.commit()

    def test_el_wizard_da_de_alta_cocina_con_estacion_valida(self, client, db, wizard_listo,
                                                             estaciones):
        """Control positivo: sin esto, el test de abajo pasaría aunque el paso 5
        ni siquiera se ejecutara."""
        from backend.models.models import Usuario

        client.post('/setup/paso/5', data={
            'user_nombre[]': ['Coci Wizard'],
            'user_email[]': ['coci_wizard@test.com'],
            'user_password[]': ['Test1234!'],
            'user_rol[]': ['cocina:Parrilla'],
        })
        u = Usuario.query.filter_by(email='coci_wizard@test.com').first()
        assert u is not None, 'el paso 5 no dio de alta al equipo'
        assert u.rol == 'cocina'
        assert u.estacion_id == estaciones['parrilla'].id

    def test_el_wizard_no_da_de_alta_cocina_sin_estacion(self, client, db, wizard_listo):
        """Paso 5 del wizard: mismo riesgo al capturar el equipo inicial."""
        from backend.models.models import Usuario

        client.post('/setup/paso/5', data={
            'user_nombre[]': ['Fantasma'],
            'user_email[]': ['fantasma@test.com'],
            'user_password[]': ['Test1234!'],
            'user_rol[]': ['cocina:No Existe'],
        })
        assert Usuario.query.filter_by(email='fantasma@test.com').first() is None


class TestContadorPorEstacion:
    """Los badges de las pestañas de estación."""

    def test_cuenta_los_pendientes_de_cada_estacion(self, client, superadmin_user, db,
                                                    orden_mixta):
        _entrar(client, db, 'super_test@test.com')
        datos = {e['nombre']: e for e in client.get('/cocina/api/estaciones').get_json()}
        assert datos['Parrilla']['pendientes'] == 1
        assert datos['Bebidas']['pendientes'] == 1

    def test_baja_al_marcar_listo(self, client, superadmin_user, db, orden_mixta):
        _entrar(client, db, 'super_test@test.com')
        client.post(
            f"/cocina/parrilla/marcar/{orden_mixta['orden'].id}/{orden_mixta['taco'].id}")

        datos = {e['nombre']: e for e in client.get('/cocina/api/estaciones').get_json()}
        assert datos['Parrilla']['pendientes'] == 0
        assert datos['Bebidas']['pendientes'] == 1, \
            'marcar en una estación afectó el contador de la otra'


class TestPantallasKds:
    @pytest.mark.parametrize('ruta', ['/cocina/api/estaciones', '/cocina/api/orders',
                                      '/cocina/parrilla', '/cocina/parrilla/stats',
                                      '/cocina/parrilla/fragmento_ordenes'])
    def test_responden(self, client, superadmin_user, db, estaciones, ruta):
        _entrar(client, db, 'super_test@test.com')
        assert client.get(ruta).status_code == 200

    def test_estacion_con_acento_y_espacio_resuelve(self, client, superadmin_user, db):
        from backend.models.models import Estacion

        db.session.add(Estacion(nombre='Plancha Fría'))
        db.session.commit()

        _entrar(client, db, 'super_test@test.com')
        assert client.get('/cocina/plancha-fria').status_code == 200

    def test_estacion_inexistente_da_404(self, client, superadmin_user, db, estaciones):
        _entrar(client, db, 'super_test@test.com')
        assert client.get('/cocina/no-existe').status_code == 404

    def test_historial_es_solo_de_admin(self, client, cocinero_parrilla, db):
        _entrar(client, db, 'cocip@test.com')
        assert client.get('/cocina/historial').status_code in (302, 403)

    def test_timestamps_llevan_sufijo_z(self, client, superadmin_user, db, orden_mixta):
        """Sin la Z, `new Date()` los lee como hora local y el cronómetro del KDS
        sale corrido por el offset."""
        _entrar(client, db, 'super_test@test.com')
        datos = client.get('/cocina/api/orders').get_json()
        texto = str(datos)
        assert 'T' in texto and 'Z' in texto
