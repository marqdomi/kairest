"""Tests for the onboarding wizard (setup), seeder, and modo sistema."""
import pytest
from backend.models.models import ConfiguracionSistema, Sucursal, Usuario, Producto, Mesa, Categoria


class TestConfiguracionSistema:
    """Tests for the key-value configuration model."""

    def test_set_and_get(self, app, db):
        with app.app_context():
            ConfiguracionSistema.set('test_key', 'test_value')
            db.session.commit()
            assert ConfiguracionSistema.get('test_key') == 'test_value'

    def test_get_default(self, app, db):
        with app.app_context():
            assert ConfiguracionSistema.get('nonexistent', 'fallback') == 'fallback'

    def test_get_bool_true(self, app, db):
        with app.app_context():
            ConfiguracionSistema.set('flag', 'true')
            db.session.commit()
            assert ConfiguracionSistema.get_bool('flag') is True

    def test_get_bool_false(self, app, db):
        with app.app_context():
            ConfiguracionSistema.set('flag', 'false')
            db.session.commit()
            assert ConfiguracionSistema.get_bool('flag') is False

    def test_get_bool_default(self, app, db):
        with app.app_context():
            assert ConfiguracionSistema.get_bool('missing', True) is True

    def test_upsert(self, app, db):
        with app.app_context():
            ConfiguracionSistema.set('key1', 'first')
            db.session.commit()
            ConfiguracionSistema.set('key1', 'second')
            db.session.commit()
            assert ConfiguracionSistema.get('key1') == 'second'
            # Only one row should exist
            count = ConfiguracionSistema.query.filter_by(clave='key1').count()
            assert count == 1


class TestSetupWizard:
    """Tests for the 5-step onboarding wizard."""

    def test_redirect_to_setup_when_not_done(self, client, app, db):
        """Unauthenticated requests should redirect to /setup when onboarding is not completed."""
        with app.app_context():
            response = client.get('/', follow_redirects=False)
            # Should eventually reach /setup/paso/1
            assert response.status_code in (302, 308)

    def test_setup_index_redirects_to_step1(self, client, app, db):
        with app.app_context():
            response = client.get('/setup/', follow_redirects=False)
            assert response.status_code == 302
            assert '/setup/paso/1' in response.headers['Location']

    def test_paso1_renders(self, client, app, db):
        with app.app_context():
            response = client.get('/setup/paso/1')
            assert response.status_code == 200
            assert 'Tu Negocio' in response.data.decode()

    def test_paso1_creates_sucursal(self, client, app, db):
        with app.app_context():
            response = client.post('/setup/paso/1', data={
                'nombre_negocio': 'Test Barbacoa',
            }, follow_redirects=False)
            assert response.status_code == 302
            sucursal = Sucursal.query.first()
            assert sucursal is not None
            assert sucursal.nombre == 'Test Barbacoa'
            assert ConfiguracionSistema.get('nombre_negocio') == 'Test Barbacoa'

    def test_paso2_renders(self, client, app, db):
        with app.app_context():
            response = client.get('/setup/paso/2')
            assert response.status_code == 200
            assert 'Administrador' in response.data.decode()

    def test_paso2_creates_admin(self, client, app, db):
        with app.app_context():
            # First create sucursal
            client.post('/setup/paso/1', data={'nombre_negocio': 'Test'})

            response = client.post('/setup/paso/2', data={
                'nombre': 'Test Admin',
                'email': 'admin@test.com',
                'password': 'TestPass123!',
                'password2': 'TestPass123!',
            }, follow_redirects=False)
            assert response.status_code == 302
            admin = Usuario.query.filter_by(rol='superadmin').first()
            assert admin is not None
            assert admin.nombre == 'Test Admin'
            assert admin.email == 'admin@test.com'
            assert admin.check_password('TestPass123!')

    def test_paso2_password_mismatch(self, client, app, db):
        with app.app_context():
            response = client.post('/setup/paso/2', data={
                'nombre': 'Test',
                'email': 'admin@test.com',
                'password': 'TestPass123!',
                'password2': 'Different123!',
            })
            assert response.status_code == 200
            assert 'no coinciden' in response.data.decode()

    def test_paso3_renders(self, client, app, db):
        with app.app_context():
            response = client.get('/setup/paso/3')
            assert response.status_code == 200
            assert 'Tu Menú' in response.data.decode()

    def test_paso3_default_menu(self, client, app, db):
        with app.app_context():
            response = client.post('/setup/paso/3', data={
                'opcion_menu': 'default',
            }, follow_redirects=False)
            assert response.status_code == 302
            # Should have created products
            count = Producto.query.count()
            assert count > 0

    def test_paso4_renders(self, client, app, db):
        with app.app_context():
            response = client.get('/setup/paso/4')
            assert response.status_code == 200
            assert 'Mesas' in response.data.decode()

    def test_paso4_creates_mesas(self, client, app, db):
        with app.app_context():
            response = client.post('/setup/paso/4', data={
                'cantidad_mesas': '5',
            }, follow_redirects=False)
            assert response.status_code == 302
            assert Mesa.query.count() == 5

    def test_paso5_renders(self, client, app, db):
        with app.app_context():
            response = client.get('/setup/paso/5')
            assert response.status_code == 200
            assert 'Tu Equipo' in response.data.decode()

    def test_completar_marks_onboarding_done(self, client, app, db):
        with app.app_context():
            response = client.get('/setup/completar', follow_redirects=False)
            assert response.status_code == 302
            assert ConfiguracionSistema.get_bool('onboarding_completado') is True
            assert ConfiguracionSistema.get('modo_sistema') == 'basico'

    def test_steps_redirect_after_onboarding(self, client, app, db):
        """Once onboarding is done, all setup steps should redirect to login."""
        with app.app_context():
            ConfiguracionSistema.set('onboarding_completado', 'true')
            db.session.commit()

            for step in ['/setup/', '/setup/paso/1', '/setup/paso/2',
                         '/setup/paso/3', '/setup/paso/4', '/setup/paso/5']:
                response = client.get(step, follow_redirects=False)
                assert response.status_code == 302, f'{step} should redirect'


class TestModoSistema:
    """Tests for the modo básico/avanzado toggle."""

    def _complete_onboarding(self, db):
        ConfiguracionSistema.set('onboarding_completado', 'true')
        ConfiguracionSistema.set('modo_sistema', 'basico')
        db.session.commit()

    def _login_superadmin(self, client, db):
        """Create superadmin and log in."""
        user = Usuario(nombre='Super', email='super@test.com', rol='superadmin')
        user.set_password('TestPass123!')
        db.session.add(user)
        db.session.commit()
        client.post('/login', data={'email': 'super@test.com', 'password': 'TestPass123!'}, follow_redirects=True)
        return user

    def test_toggle_basico_to_avanzado(self, client, app, db):
        with app.app_context():
            self._complete_onboarding(db)
            self._login_superadmin(client, db)

            response = client.post('/admin/toggle-modo', follow_redirects=False)
            assert response.status_code == 302
            assert ConfiguracionSistema.get('modo_sistema') == 'avanzado'

    def test_toggle_avanzado_to_basico(self, client, app, db):
        with app.app_context():
            self._complete_onboarding(db)
            ConfiguracionSistema.set('modo_sistema', 'avanzado')
            db.session.commit()
            self._login_superadmin(client, db)

            response = client.post('/admin/toggle-modo', follow_redirects=False)
            assert response.status_code == 302
            assert ConfiguracionSistema.get('modo_sistema') == 'basico'


class TestSeeder:
    """Tests for the seeder service functions."""

    def test_seed_menu_default(self, app, db):
        with app.app_context():
            from backend.services.seeder import seed_menu_default
            created = seed_menu_default()
            assert created > 0
            assert Categoria.query.count() > 0
            assert Producto.query.count() > 0

    def test_seed_menu_default_idempotent(self, app, db):
        with app.app_context():
            from backend.services.seeder import seed_menu_default
            first = seed_menu_default()
            second = seed_menu_default()
            assert second == 0  # No new products on second run

    def test_seed_mesas(self, app, db):
        with app.app_context():
            from backend.services.seeder import seed_mesas
            created = seed_mesas(5)
            assert created == 5
            assert Mesa.query.count() == 5

    def test_seed_mesas_idempotent(self, app, db):
        with app.app_context():
            from backend.services.seeder import seed_mesas
            seed_mesas(3)
            created = seed_mesas(5)
            assert created == 2  # Only 2 new (4, 5)
            assert Mesa.query.count() == 5
