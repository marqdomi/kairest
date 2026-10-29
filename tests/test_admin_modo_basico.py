"""Auditoría del panel admin en MODO BÁSICO (dashboard, operaciones, catálogo, ventas).

Fija los hallazgos de la auditoría del MVP. Tres grupos:

1. Dialecto SQL — `dia_local`/`hora_local_sql` generaban SQL de SQLite contra
   PostgreSQL y tumbaban los 5 reportes, el dashboard, el corte y el KDS con 500.
   La suite no lo detectó porque corre en SQLite, que es justo el dialecto al que
   caía por error. El test compila la expresión contra el dialecto real de la
   sesión, así que vale en cualquiera de los dos motores.
2. Zona horaria — la columna se guarda en UTC; formatearla en crudo mandaba las
   ventas de la tarde al día siguiente (el caso de negocio: una taquería que
   cierra a las 23:00 en UTC-6).
3. Validación de formularios — precio negativo, casts sin proteger y borrados
   destructivos en el catálogo.
"""
import csv
import io

import pytest

from tests.conftest import login


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _onboarding_listo(db):
    from backend.models.models import ConfiguracionSistema
    if not ConfiguracionSistema.query.filter_by(clave='onboarding_completado').first():
        db.session.add(ConfiguracionSistema(clave='onboarding_completado', valor='true'))
        db.session.commit()


def _entrar(client, db, email='super_test@test.com'):
    _onboarding_listo(db)
    login(client, email, 'Test1234!')


@pytest.fixture
def estacion(db):
    from backend.models.models import Estacion
    e = Estacion(nombre='Parrilla')
    db.session.add(e)
    db.session.commit()
    return e


@pytest.fixture
def producto_en_estacion(db, sample_categoria, estacion):
    from backend.models.models import Producto
    p = Producto(nombre='Taco al Pastor', precio=25,
                 categoria_id=sample_categoria.id, estacion_id=estacion.id)
    db.session.add(p)
    db.session.commit()
    return p


# ===========================================================================
# 1. Dialecto SQL
# ===========================================================================
class TestDialectoSQL:
    """`db.session.bind` es None en Flask-SQLAlchemy: el bind real se resuelve
    con `get_bind()`. Usar `.bind` hacía que el sistema se creyera SQLite siempre.
    """

    def test_session_bind_es_none_pero_get_bind_resuelve(self, app, db):
        """Documenta la trampa: si algún día `.bind` deja de ser None, este test
        avisa de que la premisa cambió."""
        assert db.session.bind is None
        assert db.session.get_bind() is not None

    def test_dia_local_genera_sql_del_dialecto_real(self, app, db):
        from backend.models.models import Sale
        from backend.services.tiempo import dia_local

        bind = db.session.get_bind()
        sql = str(dia_local(Sale.fecha_hora).compile(bind=bind)).lower()

        if bind.dialect.name == 'postgresql':
            # PostgreSQL no tiene la función datetime(); usa AT TIME ZONE.
            assert 'timezone' in sql
            assert 'datetime(' not in sql
        else:
            assert 'datetime(' in sql

    @pytest.mark.parametrize('expresion', ['dia_local', 'hora_local_sql'])
    def test_detecta_postgres_aunque_la_suite_corra_en_sqlite(self, app, db, monkeypatch,
                                                             expresion):
        """El guard de verdad contra la regresión.

        Corriendo en SQLite, leer `.bind` (None → se asume SQLite) da por
        casualidad el resultado correcto, así que un test que sólo mire el
        dialecto real nunca detectaría el bug. Aquí se finge un bind PostgreSQL:
        si el código vuelve a `.bind`, seguirá emitiendo `datetime(...)` y el
        test falla — que es exactamente lo que tumbaba los reportes en producción.
        """
        from sqlalchemy import create_engine
        from backend.models.models import Sale
        import backend.services.tiempo as tiempo

        pg = create_engine('postgresql+psycopg2://u:p@localhost/x')  # no conecta
        monkeypatch.setattr(db.session, 'get_bind', lambda *a, **k: pg)

        sql = str(getattr(tiempo, expresion)(Sale.fecha_hora).compile(bind=pg)).lower()
        assert 'datetime(' not in sql, 'se generó SQL de SQLite contra PostgreSQL'
        assert 'time zone' in sql or 'timezone' in sql

    def test_reportes_y_dashboard_no_truenan(self, client, superadmin_user, db):
        """Las 12 pantallas que dependen de dia_local/hora_local_sql."""
        _entrar(client, db)
        rutas = [
            '/admin/reportes/', '/admin/reportes/ventas', '/admin/reportes/productos',
            '/admin/reportes/meseros', '/admin/reportes/pagos', '/admin/reportes/inventario',
            '/admin/dashboard', '/admin/corte-caja',
            '/admin/api/dashboard/ventas_hoy', '/admin/api/dashboard/ventas_7dias',
            '/admin/reportes/api/ventas', '/cocina/api/estaciones',
        ]
        for ruta in rutas:
            resp = client.get(ruta)
            assert resp.status_code == 200, f'{ruta} devolvió {resp.status_code}'


# ===========================================================================
# 2. Zona horaria en lo que ve la gente
# ===========================================================================
class TestZonaHorariaVisible:
    """Una venta de las 21:00 locales se guarda como 03:00 UTC del día siguiente.
    Formatear la columna en crudo la muestra 6 h corrida y con la fecha equivocada.
    """

    @staticmethod
    def _utc_de_la_cena():
        """UTC de las 21:05 locales de HOY.

        Se calcula desde la fecha local en vez de fijarla: con una fecha escrita
        a mano el caso deja de caer en "hoy" al día siguiente y el historial
        (que filtra por el día contable) devuelve vacío.
        """
        from datetime import datetime, time, timezone
        from backend.services.tiempo import hoy_local, zona

        local = datetime.combine(hoy_local(), time(21, 5), tzinfo=zona())
        return local.astimezone(timezone.utc).replace(tzinfo=None)

    @classmethod
    def _orden_de_la_noche(cls, db, mesa, mesero, producto):
        """Orden de las 21:05 locales — en UTC cae en la madrugada del día siguiente."""
        from backend.models.models import Orden, OrdenDetalle, OrdenEstado

        utc = cls._utc_de_la_cena()
        o = Orden(mesa_id=mesa.id, mesero_id=mesero.id, estado=OrdenEstado.PAGADA,
                  tiempo_registro=utc, fecha_pago=utc, folio=1, total=75)
        db.session.add(o)
        db.session.flush()
        db.session.add(OrdenDetalle(orden_id=o.id, producto_id=producto.id, cantidad=3,
                                    precio_unitario=25, estado=OrdenEstado.LISTO))
        db.session.commit()
        return o, utc

    def test_feed_de_actividad_usa_hora_local(self, client, superadmin_user, db,
                                              sample_mesa, mesero_user, producto_en_estacion):
        from backend.services.tiempo import a_local

        _o, utc = self._orden_de_la_noche(db, sample_mesa, mesero_user, producto_en_estacion)
        esperada = a_local(utc).strftime('%H:%M')
        assert esperada != utc.strftime('%H:%M'), 'el test sólo vale si la zona desplaza'

        _entrar(client, db)
        items = client.get('/admin/api/dashboard/actividad_reciente').get_json()['items']
        horas = [i['hora'] for i in items]
        assert esperada in horas
        assert utc.strftime('%H:%M') not in horas

    def test_feed_de_actividad_muestra_folio_no_id_interno(self, client, superadmin_user, db,
                                                           sample_mesa, mesero_user,
                                                           producto_en_estacion):
        o, _utc = self._orden_de_la_noche(db, sample_mesa, mesero_user, producto_en_estacion)
        o.folio = 7          # folio del día distinto del id interno
        db.session.commit()

        _entrar(client, db)
        items = client.get('/admin/api/dashboard/actividad_reciente').get_json()['items']
        assert items[0]['id'] == 7

    def test_historial_csv_usa_hora_local_y_folio(self, client, superadmin_user, db,
                                                  sample_mesa, mesero_user, producto_en_estacion):
        from backend.services.tiempo import a_local

        o, utc = self._orden_de_la_noche(db, sample_mesa, mesero_user, producto_en_estacion)
        o.folio = 7
        db.session.commit()

        _entrar(client, db)
        resp = client.get('/meseros/historial/csv')
        assert resp.status_code == 200
        filas = list(csv.reader(io.StringIO(resp.data.decode())))
        cuerpo = [f for f in filas[1:] if f]
        assert cuerpo, 'el CSV salió vacío'
        assert cuerpo[0][0] == '#7', 'el CSV debe traer el folio, no el id interno'
        assert cuerpo[0][1] == a_local(utc).strftime('%H:%M')

    def test_ventas_csv_usa_el_dia_contable_local(self, client, superadmin_user, db,
                                                  sample_mesa, mesero_user):
        """El peor caso: sin convertir, la venta se exporta con la fecha del día
        siguiente y el CSV no cuadra contra el corte de caja."""
        from backend.models.models import Sale
        from backend.services.tiempo import a_local, hoy_local

        utc = self._utc_de_la_cena()
        db.session.add(Sale(usuario_id=mesero_user.id, mesa_id=sample_mesa.id,
                            total=75, estado='cerrada', fecha_hora=utc))
        db.session.commit()

        _entrar(client, db)
        resp = client.get('/admin/reportes/ventas/csv')
        assert resp.status_code == 200
        filas = list(csv.reader(io.StringIO(resp.data.decode())))
        cuerpo = [f for f in filas[1:] if f]
        assert cuerpo, 'el CSV salió vacío'
        assert cuerpo[0][1] == a_local(utc).strftime('%Y-%m-%d %H:%M')
        # Sin convertir, la cena se exportaría con la fecha del día siguiente.
        assert cuerpo[0][1].startswith(hoy_local().isoformat()), \
            'la venta se fue al día siguiente'
        assert not cuerpo[0][1].startswith(utc.strftime('%Y-%m-%d')), \
            'el test sólo vale si la fecha UTC y la local difieren'

    def test_ticket_impreso_usa_hora_local_y_folio(self, db, sample_mesa, mesero_user,
                                                   producto_en_estacion):
        """PRINTER_TYPE=none cae al texto de respaldo, que es justo lo que se
        manda a `window.print()`.

        El ticket estampa la hora de impresión: el contenedor corre en UTC, así
        que `datetime.now()` imprimía 6 h adelantado.
        """
        from datetime import datetime
        from backend.services.printer import generar_texto_ticket
        from backend.services.tiempo import ahora_local

        o, _utc = self._orden_de_la_noche(db, sample_mesa, mesero_user, producto_en_estacion)
        o.folio = 7
        db.session.commit()

        texto = generar_texto_ticket(o, 'Puesto')
        assert 'Orden #7' in texto, 'el ticket debe traer el folio, no el id interno'

        fecha = next(l.split('Fecha:', 1)[1].strip()
                     for l in texto.splitlines() if 'Fecha:' in l)
        # Hasta la hora: el minuto puede correr entre generar y comparar.
        assert fecha.startswith(ahora_local().strftime('%Y-%m-%d %H'))
        if ahora_local().utcoffset().total_seconds() != 0:
            assert not fecha.startswith(datetime.now().strftime('%Y-%m-%d %H')), \
                'el ticket sigue imprimiendo la hora UTC del contenedor'


# ===========================================================================
# 3. Catálogo: validación y borrados destructivos
# ===========================================================================
class TestValidacionProductos:
    def _alta(self, client, db, categoria, estacion, **cambios):
        datos = {'nombre': 'Producto Prueba', 'precio': '25',
                 'categoria_id': str(categoria.id), 'estacion_id': str(estacion.id)}
        datos.update(cambios)
        return client.post('/admin/productos/nuevo', data=datos)

    @pytest.mark.parametrize('precio', ['-50', 'abc', ''])
    def test_precio_invalido_no_se_guarda(self, client, superadmin_user, db,
                                          sample_categoria, estacion, precio):
        """Un precio negativo restaría del total de la cuenta y descuadraría el
        corte; el `min` del HTML no basta porque el POST se puede mandar directo."""
        from backend.models.models import Producto

        _entrar(client, db)
        resp = self._alta(client, db, sample_categoria, estacion, precio=precio)
        assert resp.status_code < 500
        assert Producto.query.filter_by(nombre='Producto Prueba').first() is None

    @pytest.mark.parametrize('campo,valor', [
        ('categoria_id', '99999'),
        ('estacion_id', '99999'),
        ('categoria_id', 'abc'),
        ('nombre', ''),
    ])
    def test_fk_o_nombre_invalidos_no_se_guardan(self, client, superadmin_user, db,
                                                 sample_categoria, estacion, campo, valor):
        from backend.models.models import Producto

        _entrar(client, db)
        resp = self._alta(client, db, sample_categoria, estacion, **{campo: valor})
        assert resp.status_code < 500
        assert Producto.query.filter_by(nombre='Producto Prueba').first() is None

    def test_editar_a_precio_negativo_no_se_aplica(self, client, superadmin_user, db,
                                                   sample_categoria, estacion,
                                                   producto_en_estacion):
        _entrar(client, db)
        resp = client.post(f'/admin/productos/{producto_en_estacion.id}/editar', data={
            'nombre': 'Taco al Pastor', 'precio': '-99',
            'categoria_id': str(sample_categoria.id), 'estacion_id': str(estacion.id),
        })
        assert resp.status_code < 500
        db.session.refresh(producto_en_estacion)
        assert float(producto_en_estacion.precio) >= 0

    def test_alta_valida_si_funciona(self, client, superadmin_user, db,
                                     sample_categoria, estacion):
        """Control positivo: si el formulario válido fallara, los tests de arriba
        pasarían por la razón equivocada."""
        from backend.models.models import Producto

        _entrar(client, db)
        self._alta(client, db, sample_categoria, estacion, nombre='Producto Prueba')
        creado = Producto.query.filter_by(nombre='Producto Prueba').first()
        assert creado is not None and float(creado.precio) == 25

    def test_precio_cero_si_se_permite(self, client, superadmin_user, db,
                                       sample_categoria, estacion):
        """Decisión de negocio: $0 es válido (promociones, cortesías, 2x1).
        Sólo se rechaza el negativo, que descuadraría el corte."""
        from backend.models.models import Producto

        _entrar(client, db)
        self._alta(client, db, sample_categoria, estacion, nombre='Producto Prueba', precio='0')
        creado = Producto.query.filter_by(nombre='Producto Prueba').first()
        assert creado is not None
        assert float(creado.precio) == 0


class TestValidacionMesas:
    def test_capacidad_no_numerica_no_truena(self, client, superadmin_user, db):
        from backend.models.models import Mesa

        _entrar(client, db)
        resp = client.post('/admin/mesas/nuevo', data={'numero': '77', 'capacidad': 'abc'})
        assert resp.status_code < 500
        assert Mesa.query.filter_by(numero='77').first() is None

    def test_capacidad_negativa_no_se_guarda(self, client, superadmin_user, db):
        from backend.models.models import Mesa

        _entrar(client, db)
        client.post('/admin/mesas/nuevo', data={'numero': '78', 'capacidad': '-5'})
        assert Mesa.query.filter_by(numero='78').first() is None

    def test_numero_duplicado_al_editar_no_se_aplica(self, client, superadmin_user, db,
                                                     sample_mesa):
        """Dos "Mesa 1" en el piso dejan al mesero sin saber cuál levantó."""
        from backend.models.models import Mesa

        otra = Mesa(numero='9', capacidad=4, estado='disponible')
        db.session.add(otra)
        db.session.commit()

        _entrar(client, db)
        client.post(f'/admin/mesas/{otra.id}/editar',
                    data={'numero': sample_mesa.numero, 'capacidad': '4'})
        db.session.refresh(otra)
        assert otra.numero != sample_mesa.numero


class TestEstacionesCRUD:
    """Sin esta pantalla el negocio no podía renombrar ni dar de alta estaciones
    después del wizard."""

    def test_alta_valida(self, client, superadmin_user, db):
        from backend.models.models import Estacion

        _entrar(client, db)
        client.post('/admin/estaciones/nueva', data={'nombre': 'Comal'})
        assert Estacion.query.filter_by(nombre='Comal').first() is not None

    @pytest.mark.parametrize('nombre', ['', '   '])
    def test_nombre_vacio_rechazado(self, client, superadmin_user, db, estacion, nombre):
        from backend.models.models import Estacion

        _entrar(client, db)
        client.post('/admin/estaciones/nueva', data={'nombre': nombre})
        assert Estacion.query.count() == 1

    @pytest.mark.parametrize('nombre', ['Parrilla', 'PARRILLA', 'parrilla'])
    def test_duplicado_rechazado_sin_importar_mayusculas(self, client, superadmin_user,
                                                         db, estacion, nombre):
        from backend.models.models import Estacion

        _entrar(client, db)
        client.post('/admin/estaciones/nueva', data={'nombre': nombre})
        assert Estacion.query.count() == 1

    def test_no_borra_estacion_con_productos(self, client, superadmin_user, db,
                                             estacion, producto_en_estacion):
        """Un producto sin estación nunca aparece en el KDS y deja la orden incobrable."""
        from backend.models.models import Estacion

        _entrar(client, db)
        client.post(f'/admin/estaciones/{estacion.id}/eliminar')
        assert db.session.get(Estacion, estacion.id) is not None

    def test_no_borra_estacion_con_usuarios(self, client, superadmin_user, db, estacion):
        from backend.models.models import Estacion, Usuario

        cocinero = Usuario(nombre='Coci', email='coci@test.com', rol='cocina',
                           estacion_id=estacion.id)
        cocinero.set_password('Test1234!')
        db.session.add(cocinero)
        db.session.commit()

        _entrar(client, db)
        client.post(f'/admin/estaciones/{estacion.id}/eliminar')
        assert db.session.get(Estacion, estacion.id) is not None

    def test_borra_estacion_libre(self, client, superadmin_user, db, estacion):
        from backend.models.models import Estacion

        _entrar(client, db)
        client.post(f'/admin/estaciones/{estacion.id}/eliminar')
        assert db.session.get(Estacion, estacion.id) is None

    def test_renombrar_cambia_el_slug_del_kds(self, client, superadmin_user, db, estacion):
        _entrar(client, db)
        client.post(f'/admin/estaciones/{estacion.id}/editar', data={'nombre': 'Plancha Norte'})
        assert client.get('/cocina/plancha-norte').status_code == 200
        assert client.get('/cocina/parrilla').status_code == 404

    def test_no_renombra_a_nombre_ya_usado(self, client, superadmin_user, db, estacion):
        from backend.models.models import Estacion

        otra = Estacion(nombre='Comal')
        db.session.add(otra)
        db.session.commit()

        _entrar(client, db)
        client.post(f'/admin/estaciones/{otra.id}/editar', data={'nombre': 'Parrilla'})
        db.session.refresh(otra)
        assert otra.nombre == 'Comal'

    def test_estacion_inexistente_da_404(self, client, superadmin_user, db):
        _entrar(client, db)
        assert client.get('/admin/estaciones/99999/editar').status_code == 404
        assert client.post('/admin/estaciones/99999/eliminar').status_code == 404


# ===========================================================================
# 4. Permisos del modo básico
# ===========================================================================
class TestPermisosModoBasico:
    RUTAS_SOLO_ADMIN = [
        '/admin/dashboard', '/admin/productos', '/admin/mesas', '/admin/estaciones',
        '/admin/corte-caja', '/admin/pagos/verificar', '/admin/reportes/',
        '/admin/reportes/ventas', '/admin/productos/nuevo', '/admin/estaciones/nueva',
    ]

    @pytest.mark.parametrize('ruta', RUTAS_SOLO_ADMIN)
    def test_mesero_no_entra_al_admin(self, client, mesero_user, db, ruta):
        _entrar(client, db, email='mesero_test@test.com')
        resp = client.get(ruta, follow_redirects=False)
        assert resp.status_code in (302, 403), f'{ruta} dejó entrar a un mesero'

    def test_mesero_no_puede_crear_ni_borrar_estaciones(self, client, mesero_user, db, estacion):
        from backend.models.models import Estacion

        _entrar(client, db, email='mesero_test@test.com')
        client.post('/admin/estaciones/nueva', data={'nombre': 'Pirata'})
        assert Estacion.query.filter_by(nombre='Pirata').first() is None

        client.post(f'/admin/estaciones/{estacion.id}/eliminar')
        assert db.session.get(Estacion, estacion.id) is not None


# ===========================================================================
# 5. Coherencia del modo básico: nada de Inventario a la vista
# ===========================================================================
class TestModoBasicoOcultaInventario:
    """En básico el módulo de Inventario está apagado. Dejar sus atajos a la
    vista lleva a pantallas vacías (Mermas) o engañosas (Rentabilidad da 100%
    de margen si nadie capturó costos de ingredientes).
    """

    @staticmethod
    def _modo(db, valor):
        from backend.models.models import ConfiguracionSistema
        ConfiguracionSistema.set('modo_sistema', valor)
        db.session.commit()

    def test_dashboard_sin_tarjetas_de_inventario_en_basico(self, client, superadmin_user, db):
        _entrar(client, db)
        self._modo(db, 'basico')
        html = client.get('/admin/dashboard').data.decode()
        assert 'Alertas Stock' not in html
        assert 'Alertas de Inventario' not in html

    def test_dashboard_con_inventario_en_avanzado(self, client, superadmin_user, db):
        """Control negativo del anterior: en avanzado sí deben aparecer."""
        _entrar(client, db)
        self._modo(db, 'avanzado')
        html = client.get('/admin/dashboard').data.decode()
        assert 'Alertas Stock' in html
        assert 'Alertas de Inventario' in html

    def test_reportes_sin_inventario_ni_rentabilidad_en_basico(self, client, superadmin_user, db):
        _entrar(client, db)
        self._modo(db, 'basico')
        html = client.get('/admin/reportes/').data.decode()
        assert 'Inventario / Mermas' not in html
        assert 'Rentabilidad' not in html
        # Los de venta pura sí siguen
        assert 'Top Productos' in html
        assert 'Métodos de Pago' in html

    def test_reportes_completos_en_avanzado(self, client, superadmin_user, db):
        _entrar(client, db)
        self._modo(db, 'avanzado')
        html = client.get('/admin/reportes/').data.decode()
        assert 'Inventario / Mermas' in html
        assert 'Rentabilidad' in html

    def test_sidebar_sin_subreporte_de_inventario_en_basico(self, client, superadmin_user, db):
        _entrar(client, db)
        self._modo(db, 'basico')
        html = client.get('/admin/dashboard').data.decode()
        assert '/admin/reportes/inventario' not in html

    def test_ultimo_corte_se_pinta_aunque_no_haya_inventario(self, client, superadmin_user, db):
        """La tarjeta de "Último corte" se renderiza después del bloque de stock
        en el JS; con un `return` temprano se quedaba cargando para siempre."""
        js = (client.get('/static/js/admin-dashboard.js').data.decode())
        stock = js.index("kpi-alertasStockCount")
        corte = js.index("kpi-ultimoCorte")
        entre = js[stock:corte]
        assert 'return;' not in entre, \
            'un return entre stock y corte deja el KPI de corte sin pintar en modo básico'
