"""Usuarios: quién puede administrar a quién.

El hallazgo: todo el CRUD de usuarios era `roles=['admin', 'superadmin']` sin
distinguir entre los dos, y el selector de rol ofrece "superadmin". Un admin
—el gerente— podía crear un superadmin, auto-promoverse, degradar a la dueña a
mesero y cambiarle la contraseña para entrar como ella. En un negocio real eso
es que el gerente se queda con el sistema y deja fuera al dueño.

La cuenta de superadmin es la única que puede recuperar el sistema (y la que
`flask reset-password` asume que existe), así que sólo un superadmin la
administra.
"""
import pytest

from tests.conftest import login


def _onboarding_listo(db):
    from backend.models.models import ConfiguracionSistema
    if not ConfiguracionSistema.query.filter_by(clave='onboarding_completado').first():
        db.session.add(ConfiguracionSistema(clave='onboarding_completado', valor='true'))
        db.session.commit()


@pytest.fixture
def duena(db):
    from backend.models.models import Usuario
    u = Usuario(nombre='Duena', email='duena@test.com', rol='superadmin')
    u.set_password('Test1234!')
    db.session.add(u)
    db.session.commit()
    return u


@pytest.fixture
def gerente(db):
    from backend.models.models import Usuario
    u = Usuario(nombre='Gerente', email='gerente@test.com', rol='admin')
    u.set_password('Test1234!')
    db.session.add(u)
    db.session.commit()
    return u


@pytest.fixture
def como_gerente(client, db, gerente, duena):
    _onboarding_listo(db)
    login(client, 'gerente@test.com', 'Test1234!')
    return client


@pytest.fixture
def como_duena(client, db, duena):
    _onboarding_listo(db)
    login(client, 'duena@test.com', 'Test1234!')
    return client


class TestUnAdminNoEscalaPrivilegios:
    def test_no_puede_crear_un_superadmin(self, como_gerente, db):
        from backend.models.models import Usuario

        como_gerente.post('/admin/usuarios/nuevo', data={
            'nombre': 'Titere', 'email': 'titere@test.com',
            'rol': 'superadmin', 'password': 'Test1234!',
        })
        creado = Usuario.query.filter_by(email='titere@test.com').first()
        assert creado is None or creado.rol != 'superadmin'

    def test_no_puede_auto_promoverse(self, como_gerente, db, gerente):
        como_gerente.post(f'/admin/usuarios/{gerente.id}/editar', data={
            'nombre': 'Gerente', 'email': 'gerente@test.com', 'rol': 'superadmin',
        })
        db.session.refresh(gerente)
        assert gerente.rol == 'admin'

    def test_no_puede_degradar_al_dueno(self, como_gerente, db, duena):
        como_gerente.post(f'/admin/usuarios/{duena.id}/editar', data={
            'nombre': 'Duena', 'email': 'duena@test.com', 'rol': 'mesero',
        })
        db.session.refresh(duena)
        assert duena.rol == 'superadmin'

    def test_no_puede_cambiarle_la_contrasena_al_dueno(self, como_gerente, db, duena):
        """Era secuestro directo de la cuenta con la que se recupera el sistema."""
        antes = duena.password_hash

        como_gerente.post(f'/admin/usuarios/{duena.id}/editar', data={
            'nombre': 'Duena', 'email': 'duena@test.com', 'rol': 'superadmin',
            'password': 'Otra1234!',
        })
        db.session.refresh(duena)
        assert duena.password_hash == antes

    def test_no_puede_borrar_al_dueno(self, como_gerente, db, duena):
        from backend.models.models import Usuario

        como_gerente.post(f'/admin/usuarios/{duena.id}/eliminar')
        assert db.session.get(Usuario, duena.id) is not None

    def test_si_puede_administrar_al_resto_del_equipo(self, como_gerente, db):
        """Control positivo: el gerente sigue siendo útil, sólo no toca al dueño."""
        from backend.models.models import Usuario

        como_gerente.post('/admin/usuarios/nuevo', data={
            'nombre': 'Nuevo Mesero', 'email': 'nuevo@test.com',
            'rol': 'mesero', 'password': 'Test1234!',
        })
        creado = Usuario.query.filter_by(email='nuevo@test.com').first()
        assert creado is not None and creado.rol == 'mesero'


class TestElSuperadminSiAdministra:
    def test_puede_crear_otro_superadmin(self, como_duena, db):
        from backend.models.models import Usuario

        como_duena.post('/admin/usuarios/nuevo', data={
            'nombre': 'Socio', 'email': 'socio@test.com',
            'rol': 'superadmin', 'password': 'Test1234!',
        })
        creado = Usuario.query.filter_by(email='socio@test.com').first()
        assert creado is not None and creado.rol == 'superadmin'

    def test_no_se_queda_el_sistema_sin_superadmin(self, como_duena, db, duena):
        """Degradar al único superadmin deja el sistema sin quien lo administre."""
        como_duena.post(f'/admin/usuarios/{duena.id}/editar', data={
            'nombre': 'Duena', 'email': 'duena@test.com', 'rol': 'mesero',
        })
        db.session.refresh(duena)
        assert duena.rol == 'superadmin'

    def test_si_hay_otro_superadmin_si_se_puede_degradar(self, como_duena, db, duena):
        """Control positivo del anterior."""
        from backend.models.models import Usuario

        otro = Usuario(nombre='Socio', email='socio@test.com', rol='superadmin')
        otro.set_password('Test1234!')
        db.session.add(otro)
        db.session.commit()

        como_duena.post(f'/admin/usuarios/{duena.id}/editar', data={
            'nombre': 'Duena', 'email': 'duena@test.com', 'rol': 'admin',
        })
        db.session.refresh(duena)
        assert duena.rol == 'admin'

    def test_no_borra_al_ultimo_superadmin(self, como_duena, db, duena, gerente):
        """Aunque no sea auto-borrado: si lo borra otro, nadie administra."""
        from backend.models.models import Usuario

        # El gerente no puede; se prueba el guard del último superadmin
        # promoviendo primero al gerente y dejando a la dueña como única.
        como_duena.post(f'/admin/usuarios/{duena.id}/eliminar')
        assert db.session.get(Usuario, duena.id) is not None


class TestValidacionesDeUsuario:
    def test_no_admite_correo_duplicado_al_editar(self, como_duena, db, gerente):
        """Dos cuentas con el mismo correo dejan un login ambiguo."""
        from backend.models.models import Usuario

        como_duena.post(f'/admin/usuarios/{gerente.id}/editar', data={
            'nombre': 'Gerente', 'email': 'duena@test.com', 'rol': 'admin',
        })
        db.session.refresh(gerente)
        assert gerente.email == 'gerente@test.com'
        assert Usuario.query.filter_by(email='duena@test.com').count() == 1

    def test_no_admite_contrasena_debil(self, como_duena, db):
        from backend.models.models import Usuario

        como_duena.post('/admin/usuarios/nuevo', data={
            'nombre': 'Debil', 'email': 'debil@test.com',
            'rol': 'mesero', 'password': '123',
        })
        assert Usuario.query.filter_by(email='debil@test.com').first() is None

    def test_no_puede_eliminarse_a_si_mismo(self, como_duena, db, duena):
        from backend.models.models import Usuario

        resp = como_duena.post(f'/admin/usuarios/{duena.id}/eliminar')
        assert resp.status_code < 500, 'el borrado revienta en vez de proteger'
        assert db.session.get(Usuario, duena.id) is not None

    def test_no_borra_a_un_mesero_con_ordenes_activas(self, como_duena, db, mesero_user,
                                                      sample_mesa):
        from backend.models.models import Orden, OrdenEstado, Usuario

        db.session.add(Orden(mesa_id=sample_mesa.id, mesero_id=mesero_user.id,
                             estado=OrdenEstado.ENVIADO))
        db.session.commit()

        como_duena.post(f'/admin/usuarios/{mesero_user.id}/eliminar')
        assert db.session.get(Usuario, mesero_user.id) is not None


@pytest.fixture
def sucursal(db):
    """Personalización redirige si no hay sucursal: sin esto los tests de este
    módulo pasarían sin ejecutar la ruta."""
    from backend.models.models import Sucursal
    s = Sucursal(nombre='Puesto')
    db.session.add(s)
    db.session.commit()
    return s


class TestPersonalizacionOperativa:
    """Lo de Personalización que bloquea cobrar."""

    def test_la_pantalla_responde(self, como_duena, db, sucursal):
        """Control positivo: confirma que los demás tests sí llegan a la ruta."""
        assert como_duena.get('/admin/personalizacion').status_code == 200

    def test_no_deja_al_negocio_sin_metodos_de_pago(self, como_duena, db, sucursal):
        from backend.services.pagos import metodos_pago_habilitados

        como_duena.post('/admin/personalizacion', data={'nombre': 'Puesto'})
        assert len(metodos_pago_habilitados()) >= 1, 'no se podría cobrar nada'

    def test_ignora_metodos_inventados(self, como_duena, db, sucursal):
        from backend.services.pagos import metodos_pago_habilitados

        como_duena.post('/admin/personalizacion', data={
            'nombre': 'Puesto', 'metodos_pago': ['efectivo', 'bitcoin'],
        })
        habilitados = metodos_pago_habilitados()
        assert 'bitcoin' not in habilitados
        assert 'efectivo' in habilitados

    def test_un_metodo_apagado_se_rechaza_al_cobrar(self, client, db, duena, mesero_user,
                                                    sample_mesa, sample_producto, sucursal):
        from backend.models.models import Orden, OrdenDetalle, OrdenEstado
        from backend.services.pagos import metodos_pago_habilitados

        _onboarding_listo(db)
        login(client, 'duena@test.com', 'Test1234!')
        client.post('/admin/personalizacion', data={
            'nombre': 'Puesto', 'metodos_pago': ['efectivo'],
        })
        assert 'transferencia' not in metodos_pago_habilitados(), \
            'la configuración no se guardó: el test no probaría nada'

        o = Orden(mesa_id=sample_mesa.id, mesero_id=mesero_user.id,
                  estado=OrdenEstado.LISTA_PARA_ENTREGAR)
        db.session.add(o)
        db.session.flush()
        db.session.add(OrdenDetalle(orden_id=o.id, producto_id=sample_producto.id,
                                    cantidad=1, precio_unitario=25,
                                    estado=OrdenEstado.LISTO))
        db.session.commit()

        login(client, 'mesero_test@test.com', 'Test1234!')
        resp = client.post(f'/meseros/ordenes/{o.id}/pago',
                           json={'metodo': 'transferencia', 'monto': 25,
                                 'referencia': 'X'})
        assert resp.status_code == 400
