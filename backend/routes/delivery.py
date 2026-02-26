"""Fase 4 — Item 21: Webhooks y admin de delivery."""
import logging
from datetime import datetime
from flask import Blueprint, render_template, request, jsonify
from backend.utils import login_required
from backend.extensions import db, socketio
from backend.models.models import DeliveryOrden, Orden, utc_now
from backend.services.delivery import procesar_orden_delivery
from backend.services.webhook_auth import verificar_webhook_signature
from sqlalchemy.orm import joinedload

logger = logging.getLogger(__name__)

delivery_bp = Blueprint('delivery', __name__, url_prefix='/delivery')


# =====================================================================
# Webhooks — reciben órdenes de plataformas externas
# =====================================================================
@delivery_bp.route('/webhook/<plataforma>', methods=['POST'])
@verificar_webhook_signature
def webhook_recibir(plataforma):
    """Endpoint genérico para webhooks de delivery."""
    if plataforma not in ('uber_eats', 'rappi', 'didi_food'):
        return jsonify(error='Plataforma no soportada'), 400

    payload = request.get_json(silent=True) or {}
    try:
        delivery = procesar_orden_delivery(plataforma, payload, db.session, socketio)
        return jsonify(success=True, delivery_id=delivery.id, orden_id=delivery.orden_id), 200
    except Exception as e:
        logger.exception('Error procesando webhook %s', plataforma)
        return jsonify(error=str(e)), 500


# =====================================================================
# Admin — panel de órdenes de delivery
# =====================================================================
@delivery_bp.route('/admin')
@login_required(roles=['admin', 'superadmin'])
def admin_delivery():
    ordenes = DeliveryOrden.query.options(
        joinedload(DeliveryOrden.orden),
    ).order_by(DeliveryOrden.fecha_recibido.desc()).limit(100).all()
    return render_template('admin/delivery/lista.html', ordenes=ordenes)


@delivery_bp.route('/admin/<int:id>/aceptar', methods=['POST'])
@login_required(roles=['admin', 'superadmin'])
def aceptar_delivery(id):
    d = DeliveryOrden.query.get_or_404(id)
    d.estado_plataforma = 'aceptada'
    d.fecha_aceptado = utc_now()
    db.session.commit()
    return jsonify(success=True)


@delivery_bp.route('/admin/<int:id>/listo', methods=['POST'])
@login_required(roles=['admin', 'superadmin'])
def marcar_listo_delivery(id):
    d = DeliveryOrden.query.get_or_404(id)
    d.estado_plataforma = 'lista_para_recoger'
    d.fecha_listo = utc_now()
    db.session.commit()
    return jsonify(success=True)


# =====================================================================
# API status
# =====================================================================
@delivery_bp.route('/api/status')
@login_required(roles=['admin', 'superadmin'])
def api_delivery_status():
    """Resumen de órdenes delivery del día."""
    from datetime import date
    from sqlalchemy import func
    hoy = date.today()
    stats = db.session.query(
        DeliveryOrden.plataforma,
        func.count(DeliveryOrden.id).label('total'),
    ).filter(
        func.date(DeliveryOrden.fecha_recibido) == hoy,
    ).group_by(DeliveryOrden.plataforma).all()
    return jsonify([{'plataforma': s.plataforma, 'total': s.total} for s in stats])
