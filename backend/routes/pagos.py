"""Verificación de transferencias.

El efectivo se cuenta y ya. Una transferencia sólo es dinero cuando aparece en el
estado de cuenta, así que aquí quien administra confirma —contra su app del banco—
que el depósito llegó. Hasta entonces la cuenta del cliente sigue abierta.
"""
import logging
from decimal import Decimal

from flask import Blueprint, jsonify, render_template, request
from sqlalchemy.orm import joinedload

from backend.extensions import db, socketio
from backend.models.models import Orden, Pago, utc_now
from backend.services.audit import registrar_auditoria
from backend.services.cobro import cerrar_orden_pagada
from backend.services.tiempo import hoy_local, rango_utc
from backend.utils import actualizar_estado_mesa, filtrar_por_sucursal, login_required

logger = logging.getLogger(__name__)

pagos_bp = Blueprint('pagos', __name__, url_prefix='/admin/pagos')

# Quién puede dar por buena una transferencia.
ROLES_VERIFICAN = ['admin', 'superadmin']


def _pendientes_query():
    q = Pago.query.options(
        joinedload(Pago.usuario),
        joinedload(Pago.orden).joinedload(Orden.mesa),
    ).join(Orden, Pago.orden_id == Orden.id).filter(Pago.verificado.is_(False))
    return filtrar_por_sucursal(q, Orden)


@pagos_bp.route('/verificar')
@login_required(roles=ROLES_VERIFICAN)
def lista_por_verificar():
    """Bandeja de transferencias esperando confirmación."""
    pendientes = _pendientes_query().order_by(Pago.fecha.asc()).all()

    desde, hasta = rango_utc(hoy_local())
    verificados_hoy = filtrar_por_sucursal(
        Pago.query.options(joinedload(Pago.verificador))
        .join(Orden, Pago.orden_id == Orden.id)
        .filter(Pago.verificado.is_(True),
                Pago.metodo == 'transferencia',
                Pago.fecha_verificacion >= desde,
                Pago.fecha_verificacion < hasta),
        Orden,
    ).order_by(Pago.fecha_verificacion.desc()).all()

    total_pendiente = sum((p.monto for p in pendientes), Decimal('0'))
    return render_template('admin/pagos/verificar.html',
                           pendientes=pendientes,
                           verificados_hoy=verificados_hoy,
                           total_pendiente=total_pendiente)


@pagos_bp.route('/api/pendientes')
@login_required(roles=ROLES_VERIFICAN)
def api_pendientes():
    """Contador para el badge del menú."""
    pendientes = _pendientes_query().all()
    return jsonify({
        'cantidad': len(pendientes),
        'total': float(sum((p.monto for p in pendientes), Decimal('0'))),
    })


@pagos_bp.route('/<int:pago_id>/verificar', methods=['POST'])
@login_required(roles=ROLES_VERIFICAN)
def verificar_pago(pago_id):
    """Confirma que el dinero llegó. Si con esto se cubre la cuenta, la cierra."""
    from flask import session

    pago = db.session.get(Pago, pago_id, with_for_update=True)
    if not pago:
        return jsonify(success=False, message='Pago no encontrado.'), 404
    if pago.verificado:
        return jsonify(success=False, message='Este pago ya estaba verificado.'), 409

    # Lockear la orden antes de tocar saldos (mismo patrón que el cobro): primero el
    # lock, después las relaciones — PostgreSQL rechaza FOR UPDATE con outer join.
    orden = db.session.get(Orden, pago.orden_id, with_for_update=True)
    if not orden:
        return jsonify(success=False, message='Orden no encontrada.'), 404
    db.session.refresh(orden)
    orden.detalles
    orden.pagos

    # La cuenta ya se cubrió por otro lado (el cliente dijo que transfería, no llegó y
    # pagó en efectivo). Confirmar esta transferencia contaba el dinero dos veces: una
    # cuenta de $630 quedaba con $1,160 cobrados y el corte sumaba lo que no es venta.
    # Si de verdad llegó, es una devolución, no un ingreso: que se rechace aquí.
    if orden.estado == 'pagada' or orden.saldo_pendiente() <= 0:
        return jsonify(success=False,
                       message='Esa cuenta ya está pagada por otro medio. Si el depósito sí '
                               'llegó, hay que devolverlo; recházala aquí para que no se '
                               'cuente dos veces.'), 409

    pago.verificado = True
    pago.verificado_por = session.get('user_id')
    pago.fecha_verificacion = utc_now()
    db.session.flush()

    orden.calcular_totales()
    cerrada = False
    if orden.saldo_pendiente() <= 0 and orden.estado not in ('pagada', 'cancelada'):
        cerrar_orden_pagada(orden, orden.mesero_id or session.get('user_id'))
        cerrada = True

    registrar_auditoria('verificar_pago', 'Pago', pago.id,
                        f'Transferencia ${float(pago.monto):.2f} confirmada '
                        f'(ref: {pago.referencia or "sin referencia"}), orden #{orden.id}')
    db.session.commit()

    if cerrada:
        actualizar_estado_mesa(orden.mesa_id)
        db.session.commit()

    socketio.emit('pago_verificado', {
        'pago_id': pago.id, 'orden_id': orden.id,
        'orden_cerrada': cerrada,
        'mensaje': f'Transferencia de la orden #{orden.numero} confirmada.',
    })
    logger.info('Pago %s verificado por usuario %s (orden %s, cerrada=%s)',
                pago.id, session.get('user_id'), orden.id, cerrada)

    return jsonify(success=True, orden_cerrada=cerrada,
                   message='Transferencia confirmada.' +
                           (' Cuenta liberada.' if cerrada else ''))


@pagos_bp.route('/<int:pago_id>/rechazar', methods=['POST'])
@login_required(roles=ROLES_VERIFICAN)
def rechazar_pago(pago_id):
    """El depósito nunca llegó: se elimina el pago y la cuenta vuelve a quedar por cobrar."""
    from flask import session

    pago = db.session.get(Pago, pago_id, with_for_update=True)
    if not pago:
        return jsonify(success=False, message='Pago no encontrado.'), 404
    if pago.verificado:
        return jsonify(success=False,
                       message='No se puede rechazar un pago ya verificado.'), 409

    orden_id, monto, referencia = pago.orden_id, pago.monto, pago.referencia
    motivo = (request.get_json(silent=True) or {}).get('motivo', '')

    db.session.delete(pago)
    registrar_auditoria('rechazar_pago', 'Orden', orden_id,
                        f'Transferencia ${float(monto):.2f} rechazada '
                        f'(ref: {referencia or "sin referencia"}). {motivo}'.strip())
    db.session.commit()

    socketio.emit('pago_rechazado', {
        'orden_id': orden_id, 'monto': float(monto),
        'mensaje': f'La transferencia de la orden #{orden_id} no se pudo confirmar.',
    })
    logger.info('Pago %s rechazado por usuario %s (orden %s)',
                pago_id, session.get('user_id'), orden_id)

    return jsonify(success=True, message='Transferencia rechazada. La cuenta sigue por cobrar.')
