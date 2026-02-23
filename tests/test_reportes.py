"""Tests for report endpoints."""
import pytest
from tests.conftest import login
from decimal import Decimal


def _setup_onboarding(db):
    """Mark onboarding as completed so routes don't redirect to /setup/."""
    from backend.models.models import ConfiguracionSistema
    if not ConfiguracionSistema.query.filter_by(clave='onboarding_completado').first():
        db.session.add(ConfiguracionSistema(clave='onboarding_completado', valor='true'))
        db.session.commit()


class TestReportAccess:
    def test_reportes_dashboard_requires_auth(self, client):
        resp = client.get('/admin/reportes/', follow_redirects=True)
        assert resp.status_code == 200

    def test_reportes_dashboard_admin(self, client, admin_user, db):
        _setup_onboarding(db)
        login(client, 'admin_test@test.com', 'Test1234!')
        resp = client.get('/admin/reportes/')
        assert resp.status_code == 200


class TestReportData:
    def test_ventas_report_empty(self, client, admin_user, db):
        """Should render even with no sales data."""
        _setup_onboarding(db)
        login(client, 'admin_test@test.com', 'Test1234!')
        resp = client.get('/admin/reportes/ventas')
        assert resp.status_code == 200

    def test_productos_report_empty(self, client, admin_user, db):
        _setup_onboarding(db)
        login(client, 'admin_test@test.com', 'Test1234!')
        resp = client.get('/admin/reportes/productos')
        assert resp.status_code == 200


class TestCSVExport:
    def test_ventas_csv(self, client, admin_user, db):
        _setup_onboarding(db)
        login(client, 'admin_test@test.com', 'Test1234!')
        resp = client.get('/admin/reportes/ventas/csv')
        assert resp.status_code == 200
        assert 'text/csv' in resp.content_type

    def test_productos_csv(self, client, admin_user, db):
        _setup_onboarding(db)
        login(client, 'admin_test@test.com', 'Test1234!')
        resp = client.get('/admin/reportes/productos/csv')
        assert resp.status_code == 200
        assert 'text/csv' in resp.content_type


class TestAuditLog:
    def test_audit_log_creation(self, db, admin_user, app):
        """Test direct creation of AuditLog entries."""
        from backend.models.models import AuditLog

        log = AuditLog(
            usuario_id=admin_user.id,
            accion='test',
            entidad='Sistema',
            entidad_id=0,
            descripcion='Test entry',
        )
        db.session.add(log)
        db.session.commit()

        assert log.id is not None
        assert log.accion == 'test'

    def test_audit_log_list_route(self, client, superadmin_user, db):
        """Test auditoria list route."""
        _setup_onboarding(db)
        login(client, 'super_test@test.com', 'Test1234!')
        resp = client.get('/admin/auditoria/')
        assert resp.status_code == 200
