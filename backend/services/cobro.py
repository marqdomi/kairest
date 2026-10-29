"""Cierre de cuenta: lo que pasa cuando una orden queda totalmente pagada.

Vive aparte porque ocurre desde dos lados: el cobro normal del mesero (efectivo, que
se verifica solo) y la confirmación de una transferencia por parte de la dueña, que
puede llegar minutos después. Ambos caminos tienen que dejar exactamente el mismo
rastro contable: venta registrada, inventario descontado y mesa liberada.
"""
import logging
from decimal import Decimal

from flask import g

from backend.extensions import db, socketio
from backend.models.models import (Cliente, OrdenEstado, Sale, SaleItem,
                                   descontar_inventario_por_orden, utc_now)

logger = logging.getLogger(__name__)


def cerrar_orden_pagada(orden, vendedor_id, cambio=Decimal('0'), propina_efectivo=Decimal('0')):
    """Marca la orden como pagada y genera la venta. Devuelve si el inventario cuadró.

    `vendedor_id` es a quién se le atribuye la venta en los reportes: siempre el mesero
    de la orden, no quien aprieta el botón (la dueña al verificar una transferencia).
    """
    total_pagado = orden.total_pagado()
    orden.monto_recibido = total_pagado + cambio + propina_efectivo
    orden.cambio = cambio
    orden.fecha_pago = utc_now()
    orden.estado = OrdenEstado.PAGADA

    venta = Sale(mesa_id=orden.mesa_id, usuario_id=vendedor_id,
                 total=orden.total, estado='cerrada',
                 sucursal_id=orden.sucursal_id or getattr(g, 'sucursal_id', None))
    db.session.add(venta)
    db.session.flush()
    for det in orden.detalles:
        precio = float(det.precio_unitario) if det.precio_unitario else float(det.producto.precio)
        db.session.add(SaleItem(
            sale_id=venta.id, producto_id=det.producto_id,
            cantidad=det.cantidad, precio_unitario=precio,
            subtotal=det.cantidad * precio,
        ))

    socketio.emit('orden_pagada_notificacion', {
        'orden_id': orden.id, 'mensaje': f'Orden #{orden.numero} pagada.',
    })

    # Descontar inventario según receta estándar (savepoint: que un tropiezo aquí no
    # tire el cobro, pero quede marcado para reconciliar)
    inventario_ok = True
    try:
        db.session.begin_nested()
        descontar_inventario_por_orden(orden, vendedor_id)
        db.session.commit()  # release savepoint
    except Exception:
        db.session.rollback()  # rollback savepoint only
        inventario_ok = False
        logger.exception('Error descontando inventario orden %s — requiere reconciliación', orden.id)
        try:
            from backend.models.models import ConfiguracionSistema
            pending = ConfiguracionSistema.get('inventario_pendiente', '')
            ids = f"{pending},{orden.id}" if pending else str(orden.id)
            ConfiguracionSistema.set('inventario_pendiente', ids)
        except Exception:
            pass  # Don't block payment over flagging

    if orden.cliente_id:
        cli = db.session.get(Cliente, orden.cliente_id)
        if cli:
            cli.visitas = (cli.visitas or 0) + 1
            cli.total_gastado = (cli.total_gastado or 0) + orden.total

    logger.info('Orden #%s pagada total=$%.2f', orden.id, float(orden.total or 0))
    return inventario_ok
