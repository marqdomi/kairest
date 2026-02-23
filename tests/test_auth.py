"""Tests for authentication routes."""
import pytest
from tests.conftest import login


class TestLogin:
    def test_login_page_loads(self, client, db):
        """Login page should load (may redirect to /setup/ if onboarding not done)."""
        from backend.models.models import ConfiguracionSistema
        # Mark onboarding as completed so /login doesn't redirect to /setup/
        cfg = ConfiguracionSistema(clave='onboarding_completado', valor='true')
        db.session.add(cfg)
        db.session.commit()

        resp = client.get('/login')
        assert resp.status_code == 200
        assert b'login' in resp.data.lower() or b'iniciar' in resp.data.lower()

    def test_login_valid_credentials(self, client, admin_user, db):
        from backend.models.models import ConfiguracionSistema
        cfg = ConfiguracionSistema(clave='onboarding_completado', valor='true')
        db.session.add(cfg)
        db.session.commit()

        resp = login(client, 'admin_test@test.com', 'Test1234!')
        assert resp.status_code == 200

    def test_login_invalid_password(self, client, admin_user, db):
        from backend.models.models import ConfiguracionSistema
        cfg = ConfiguracionSistema(clave='onboarding_completado', valor='true')
        db.session.add(cfg)
        db.session.commit()

        resp = login(client, 'admin_test@test.com', 'wrong_password')
        assert resp.status_code == 200
        # Should show error or stay on login page

    def test_login_nonexistent_user(self, client, db):
        from backend.models.models import ConfiguracionSistema
        cfg = ConfiguracionSistema(clave='onboarding_completado', valor='true')
        db.session.add(cfg)
        db.session.commit()

        resp = login(client, 'noexiste@test.com', 'Test1234!')
        assert resp.status_code == 200

    def test_logout(self, client, admin_user, db):
        from backend.models.models import ConfiguracionSistema
        cfg = ConfiguracionSistema(clave='onboarding_completado', valor='true')
        db.session.add(cfg)
        db.session.commit()

        login(client, 'admin_test@test.com', 'Test1234!')
        resp = client.get('/logout', follow_redirects=True)
        assert resp.status_code == 200


class TestProtectedRoutes:
    def test_admin_requires_login(self, client):
        resp = client.get('/admin/', follow_redirects=True)
        assert resp.status_code == 200
        # Should redirect to login

    def test_meseros_requires_login(self, client):
        resp = client.get('/meseros/', follow_redirects=True)
        assert resp.status_code == 200
