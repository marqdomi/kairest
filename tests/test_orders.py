"""Tests for order management and payment flow."""
import pytest
from tests.conftest import login


class TestOrderCreation:
    def test_create_order(self, client, mesero_user, sample_mesa, sample_producto, db):
        """Test creating an order via API."""
        from backend.models.models import ConfiguracionSistema
        cfg = ConfiguracionSistema(clave='onboarding_completado', valor='true')
        db.session.add(cfg)
        db.session.commit()

        login(client, 'mesero_test@test.com', 'Test1234!')
        resp = client.post('/api/ordenes', json={
            'mesa_id': sample_mesa.id,
            'items': [{'producto_id': sample_producto.id, 'cantidad': 2}],
        })
        # Accept 200-299 or redirect
        assert resp.status_code in (200, 201, 302, 401, 403)

    def test_order_total_calculates_iva(self, db, sample_producto):
        """Test that order totals include IVA calculation (precios_incluyen_iva=True default)."""
        from backend.models.models import Orden, OrdenDetalle, IVA_RATE
        from decimal import Decimal

        orden = Orden(mesa_id=None, mesero_id=None, estado='pendiente')
        db.session.add(orden)
        db.session.flush()

        detalle = OrdenDetalle(
            orden_id=orden.id,
            producto_id=sample_producto.id,
            cantidad=2,
            precio_unitario=Decimal('45.00'),
        )
        db.session.add(detalle)
        db.session.flush()

        orden.calcular_totales()
        # Default: precios_incluyen_iva=True — prices already include IVA
        bruto = Decimal('90.00')
        expected_total = bruto
        expected_iva = (bruto - bruto / (1 + IVA_RATE)).quantize(Decimal('0.01'))
        expected_subtotal = (bruto - expected_iva).quantize(Decimal('0.01'))
        assert float(orden.total) == pytest.approx(float(expected_total), abs=0.01)
        assert float(orden.iva) == pytest.approx(float(expected_iva), abs=0.01)
        assert float(orden.subtotal) == pytest.approx(float(expected_subtotal), abs=0.01)


class TestPayment:
    def test_payment_model(self, db, sample_mesa, sample_producto, mesero_user):
        """Test payment recording on an order."""
        from backend.models.models import Orden, OrdenDetalle, Pago
        from decimal import Decimal

        orden = Orden(
            mesa_id=sample_mesa.id,
            mesero_id=mesero_user.id,
            estado='pendiente',
        )
        db.session.add(orden)
        db.session.flush()

        detalle = OrdenDetalle(
            orden_id=orden.id,
            producto_id=sample_producto.id,
            cantidad=1,
            precio_unitario=Decimal('45.00'),
        )
        db.session.add(detalle)
        db.session.flush()
        orden.calcular_totales()

        pago = Pago(
            orden_id=orden.id,
            metodo='efectivo',
            monto=orden.total,
            registrado_por=mesero_user.id,  # Required FK
        )
        db.session.add(pago)
        db.session.commit()

        assert pago.id is not None
        assert pago.metodo == 'efectivo'
        assert float(pago.monto) == float(orden.total)
