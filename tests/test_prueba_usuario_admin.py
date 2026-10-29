"""Prueba como usuario real, rol admin (v6.8): datos equivocados en cada formulario.

Cada test corresponde a algo que en el recorrido se aceptaba en silencio, se guardaba
mal o tronaba con un 500. Ver docs/PRUEBA_USUARIO_REAL.md.
"""
import io
from datetime import timedelta
from decimal import Decimal

import pytest

from tests.conftest import login
from tests.test_transferencias import orden_por_cobrar, _setup_onboarding  # noqa: F401


@pytest.fixture
def dueno(client, db, superadmin_user):
    _setup_onboarding(db)
    login(client, superadmin_user.email, 'Test1234!')
    return superadmin_user


def _avisos(resp):
    return resp.get_data(as_text=True)


# ── Texto: "&" no debe salir como "&amp;" ──────────────────────────────────────

class TestSanitizador:

    def test_conserva_ampersand_y_comillas(self):
        from backend.services.sanitizer import sanitizar_texto
        assert sanitizar_texto('Tacos & Más "El Güero"') == 'Tacos & Más "El Güero"'

    def test_sigue_quitando_html_incluso_disfrazado(self):
        from backend.services.sanitizer import sanitizar_texto
        assert sanitizar_texto('<script>alert(1)</script>Hnos') == 'alert(1)Hnos'
        assert '<img' not in sanitizar_texto('&lt;img src=x onerror=alert(1)&gt;')


# ── Correos ────────────────────────────────────────────────────────────────────

class TestCorreos:

    def test_wizard_rechaza_correo_invalido(self, client, db):
        from backend.models.models import Usuario
        client.post('/setup/paso/1', data={'nombre_negocio': 'Prueba'})
        resp = client.post('/setup/paso/2', data={
            'nombre': 'Ana', 'usuario': 'ana', 'email': 'no-es-correo',
            'password': 'Clave2026x', 'password2': 'Clave2026x'})
        assert 'no es un correo válido' in _avisos(resp)
        assert Usuario.query.filter_by(rol='superadmin').first() is None

    def test_alta_de_usuario_rechaza_correo_invalido(self, client, db, dueno):
        from backend.models.models import Usuario
        resp = client.post('/admin/usuarios/nuevo', data={
            'nombre': 'Jefe', 'usuario': 'jefe', 'rol': 'admin',
            'password': 'Jefe2026xx', 'email': 'jefe@'})
        assert 'no es un correo válido' in _avisos(resp)
        assert Usuario.query.filter_by(username='jefe').first() is None


# ── Precios y productos ────────────────────────────────────────────────────────

class TestProductos:

    def _form(self, db, **extra):
        from backend.models.models import Categoria, Estacion
        cat = Categoria.query.first() or Categoria(nombre='General')
        est = Estacion.query.first() or Estacion(nombre='Cocina')
        db.session.add_all([cat, est])
        db.session.commit()
        datos = {'nombre': 'Taco', 'precio': '30', 'unidad': '', 'descripcion': '',
                 'categoria_id': cat.id, 'estacion_id': est.id}
        datos.update(extra)
        return datos

    def test_precio_que_no_cabe_en_la_columna(self, client, db, dueno):
        from backend.models.models import Producto
        resp = client.post('/admin/productos/nuevo', data=self._form(db, precio='99999999999'))
        assert 'demasiado alto' in _avisos(resp)
        assert Producto.query.count() == 0

    def test_nombre_repetido_sin_importar_mayusculas(self, client, db, dueno):
        from backend.models.models import Producto
        client.post('/admin/productos/nuevo', data=self._form(db, nombre='1 kg Barbacoa'))
        resp = client.post('/admin/productos/nuevo', data=self._form(db, nombre='1 KG barbacoa'))
        assert 'Ya existe un producto' in _avisos(resp)
        assert Producto.query.count() == 1

    def test_wizard_manual_rechaza_precio_negativo_o_texto(self, client, db, superadmin_user):
        from backend.models.models import Producto
        with client.session_transaction() as s:
            s['setup_sucursal_id'] = None
        for precio in ('-20', 'abc'):
            resp = client.post('/setup/paso/3', data={
                'opcion_menu': 'manual', 'prod_nombre[]': 'Taco', 'prod_precio[]': precio,
                'prod_categoria[]': 'Tacos', 'prod_estacion[]': 'Taquero'},
                follow_redirects=True)
            assert 'el precio debe ser un número' in _avisos(resp)
        assert Producto.query.count() == 0


# ── Orden: cantidades y personas ───────────────────────────────────────────────

class TestCantidades:

    @pytest.mark.parametrize('cantidad', [0, -3, 'dos', 1000, 2.5])
    def test_api_rechaza_cantidades_invalidas(self, client, db, mesero_user,
                                              sample_producto, sample_mesa, cantidad):
        from backend.models.models import Orden, OrdenDetalle
        _setup_onboarding(db)
        orden = Orden(mesa_id=sample_mesa.id, mesero_id=mesero_user.id)
        db.session.add(orden)
        db.session.commit()
        login(client, mesero_user.email, 'Test1234!')
        resp = client.post(f'/api/ordenes/{orden.id}/detalle',
                           json={'producto_id': sample_producto.id, 'cantidad': cantidad})
        assert resp.status_code == 400
        assert OrdenDetalle.query.count() == 0

    def test_patch_con_texto_no_truena(self, client, db, mesero_user, sample_producto, sample_mesa):
        from backend.models.models import Orden, OrdenDetalle
        _setup_onboarding(db)
        orden = Orden(mesa_id=sample_mesa.id, mesero_id=mesero_user.id)
        db.session.add(orden)
        db.session.flush()
        d = OrdenDetalle(orden_id=orden.id, producto_id=sample_producto.id, cantidad=1,
                         precio_unitario=Decimal('45'))
        db.session.add(d)
        db.session.commit()
        login(client, mesero_user.email, 'Test1234!')
        resp = client.patch(f'/api/ordenes/{orden.id}/detalle/{d.id}', json={'cantidad': 'dos'})
        assert resp.status_code == 400

    def test_personas_fuera_de_rango_no_se_guardan(self, client, db, mesero_user, sample_mesa):
        from backend.models.models import Orden
        _setup_onboarding(db)
        login(client, mesero_user.email, 'Test1234!')
        client.post('/meseros/seleccionar_mesa', data={'mesa_id': sample_mesa.id, 'num_personas': '-4'})
        assert Orden.query.one().num_personas is None


# ── Dinero ─────────────────────────────────────────────────────────────────────

class TestDinero:

    def test_no_se_confirma_una_transferencia_de_una_cuenta_ya_pagada(
            self, client, db, mesero_user, admin_user, orden_por_cobrar):
        """Transfiere → no llega → paga en efectivo → la dueña confirma la vieja: antes
        una cuenta de $100 quedaba con $200 cobrados."""
        from backend.models.models import Pago
        _setup_onboarding(db)
        login(client, mesero_user.email, 'Test1234!')
        client.post(f'/meseros/ordenes/{orden_por_cobrar.id}/pago',
                    json={'metodo': 'transferencia', 'monto': 100, 'referencia': 'SPEI 1'})
        client.post(f'/meseros/ordenes/{orden_por_cobrar.id}/pago',
                    json={'metodo': 'efectivo', 'monto': 100})
        transferencia = Pago.query.filter_by(metodo='transferencia').one()

        login(client, admin_user.email, 'Test1234!')
        resp = client.post(f'/admin/pagos/{transferencia.id}/verificar')
        assert resp.status_code == 409
        db.session.expire_all()
        assert db.session.get(Pago, transferencia.id).verificado is False

    @pytest.mark.parametrize('contado, esperado', [('1,160.50', Decimal('1160.50')),
                                                   ('$ 200', Decimal('200.00')),
                                                   ('0', Decimal('0.00'))])
    def test_corte_entiende_como_se_escribe_el_dinero(self, client, db, dueno, contado, esperado):
        from backend.models.models import CorteCaja
        client.post('/admin/corte-caja', data={'efectivo_contado': contado, 'notas': ''})
        assert CorteCaja.query.one().efectivo_contado == esperado

    @pytest.mark.parametrize('contado', ['', 'mucho', '-500'])
    def test_corte_rechaza_en_vez_de_guardar_cero(self, client, db, dueno, contado):
        from backend.models.models import CorteCaja
        resp = client.post('/admin/corte-caja', data={'efectivo_contado': contado},
                           follow_redirects=True)
        assert 'Escribe el efectivo que contaste' in _avisos(resp)
        assert CorteCaja.query.count() == 0

    def test_notas_del_corte_sin_html(self, client, db, dueno):
        from backend.models.models import CorteCaja
        client.post('/admin/corte-caja', data={'efectivo_contado': '0',
                                               'notas': '<script>x</script>faltó cambio'})
        assert CorteCaja.query.one().notas == 'xfaltó cambio'


# ── Personalización ────────────────────────────────────────────────────────────

class TestPersonalizacion:

    @pytest.fixture
    def negocio(self, db):
        from backend.models.models import Sucursal
        s = Sucursal(nombre='Tacos & Más')
        db.session.add(s)
        db.session.commit()
        return s

    def _form(self, **extra):
        datos = {'nombre': 'Tacos & Más', 'color_primario': '#A6192E',
                 'metodos_pago': ['efectivo'], 'banco_clabe': ''}
        datos.update(extra)
        return datos

    def test_nombre_vacio_no_borra_el_nombre(self, client, db, dueno, negocio):
        resp = client.post('/admin/personalizacion', data=self._form(nombre=''),
                           follow_redirects=True)
        assert 'no puede quedar vacío' in _avisos(resp)
        db.session.refresh(negocio)
        assert negocio.nombre == 'Tacos & Más'

    def test_rfc_invalido_avisa(self, client, db, dueno, negocio):
        resp = client.post('/admin/personalizacion', data=self._form(rfc='NOESRFC'),
                           follow_redirects=True)
        assert 'no es válido' in _avisos(resp)
        assert 'guardada exitosamente' not in _avisos(resp)

    def test_clabe_con_letras_no_borra_la_guardada(self, client, db, dueno, negocio):
        from backend.models.models import ConfiguracionSistema
        ConfiguracionSistema.set('banco_clabe', '002010077777777771')
        db.session.commit()
        resp = client.post('/admin/personalizacion',
                           data=self._form(banco_clabe='ABCDEFGHIJKLMNOPQR'), follow_redirects=True)
        assert 'sin letras' in _avisos(resp)
        assert ConfiguracionSistema.get('banco_clabe') == '002010077777777771'

    @pytest.mark.parametrize('nombre, contenido', [
        ('logo.png', b'hola no soy imagen'),
        ('logo.svg', b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'),
        ('logo.svg', b'<svg onload="alert(1)"></svg>'),
    ])
    def test_logo_que_no_es_imagen(self, client, db, dueno, negocio, nombre, contenido):
        data = self._form()
        data['logo'] = (io.BytesIO(contenido), nombre)
        resp = client.post('/admin/personalizacion', data=data,
                           content_type='multipart/form-data', follow_redirects=True)
        assert 'no es una imagen válida' in _avisos(resp)
        db.session.refresh(negocio)
        assert not negocio.logo_url

    def test_logo_png_real_si_se_acepta(self, client, db, dueno, negocio):
        data = self._form()
        data['logo'] = (io.BytesIO(b'\x89PNG\r\n\x1a\n' + b'\x00' * 32), 'logo.png')
        client.post('/admin/personalizacion', data=data, content_type='multipart/form-data')
        db.session.refresh(negocio)
        assert negocio.logo_url and negocio.logo_url.endswith('.png')


# ── Módulos avanzados ──────────────────────────────────────────────────────────

class TestModulosAvanzados:

    @pytest.mark.parametrize('form', [
        {'nombre': '', 'unidad': 'kg'},
        {'nombre': 'Pimienta', 'unidad': 'kg', 'stock_actual': 'mucho'},
        {'nombre': 'Sal', 'unidad': 'kg', 'stock_actual': '-10', 'costo_unitario': '-5'},
    ])
    def test_ingrediente_invalido_avisa_sin_500(self, client, db, dueno, form):
        from backend.models.models import Ingrediente
        resp = client.post('/admin/inventario/ingrediente/nuevo', data=form)
        assert resp.status_code == 200
        assert Ingrediente.query.count() == 0

    def test_ingrediente_repetido(self, client, db, dueno):
        from backend.models.models import Ingrediente
        for _ in range(2):
            resp = client.post('/admin/inventario/ingrediente/nuevo',
                               data={'nombre': 'Carne', 'unidad': 'kg', 'stock_actual': '1'})
        assert resp.status_code == 200
        assert Ingrediente.query.count() == 1

    @pytest.fixture
    def carne(self, db):
        from backend.models.models import Ingrediente
        i = Ingrediente(nombre='Carne', unidad='kg', stock_actual=Decimal('20'),
                        stock_minimo=Decimal('1'), costo_unitario=Decimal('250'))
        db.session.add(i)
        db.session.commit()
        return i

    @pytest.mark.parametrize('ruta, cantidad', [
        ('/admin/inventario/merma', '500'),    # más de lo que hay
        ('/admin/inventario/merma', '-5'),     # subía el inventario
        ('/admin/inventario/entrada', '-30'),
        ('/admin/inventario/entrada', '0'),
    ])
    def test_movimiento_invalido_no_mueve_el_stock(self, client, db, dueno, carne, ruta, cantidad):
        resp = client.post(ruta, data={'ingrediente_id': carne.id, 'cantidad': cantidad,
                                       'costo': '', 'motivo': 'x'})
        assert resp.status_code in (200, 302)
        db.session.refresh(carne)
        assert carne.stock_actual == Decimal('20')

    @pytest.mark.parametrize('extra', [
        {'fecha_hora': '2020-01-01T14:00', 'num_personas': '4'},
        {'num_personas': '0'},
        {'num_personas': '-5'},
        {'num_personas': '2', 'mesa_id': '999'},
        {'nombre_contacto': ''},
    ])
    def test_reservacion_invalida(self, client, db, dueno, extra):
        from backend.models.models import Reservacion
        from backend.services.tiempo import ahora_local
        manana = (ahora_local() + timedelta(days=1)).strftime('%Y-%m-%dT14:00')
        data = {'nombre_contacto': 'Familia', 'fecha_hora': manana, 'num_personas': '2'}
        data.update(extra)
        client.post('/admin/reservaciones/nueva', data=data)
        assert Reservacion.query.count() == 0

    def test_cliente_y_sucursal_sin_nombre(self, client, db, dueno):
        from backend.models.models import Cliente, Sucursal
        client.post('/admin/clientes/nuevo', data={'nombre': '', 'uso_cfdi': 'G03'})
        client.post('/admin/clientes/nuevo', data={'nombre': 'Ana', 'email': 'x@', 'uso_cfdi': 'G03'})
        client.post('/admin/sucursales/nueva', data={'nombre': ''})
        assert Cliente.query.count() == 0
        assert Sucursal.query.count() == 0
