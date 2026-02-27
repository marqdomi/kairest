from flask import Blueprint, request, jsonify
from backend.models.models import Orden, OrdenDetalle, Producto, utc_now, OrdenEstado
from backend.extensions import db, socketio
from backend.utils import obtener_ordenes_por_estacion, verificar_orden_completa, login_required

api_bp = Blueprint('api', __name__, url_prefix='/api')

@api_bp.route('/ordenes', methods=['GET'])
@login_required()
def listar_ordenes():
    """
    Lista órdenes según estación o estado.
    """
    estacion = request.args.get('estacion')
    estado = request.args.get('estado')
    if estacion:
        ordenes = obtener_ordenes_por_estacion(estacion)
        result = []
        for oid, detalles in ordenes.items():
            result.append({
                'id': oid,
                'detalles': [
                    {
                        'id': d.id,
                        'producto_id': d.producto.id,
                        'producto_nombre': d.producto.nombre,
                        'cantidad': d.cantidad,
                        'notas': d.notas,
                        'estado': d.estado
                    } for d in detalles
                ]
            })
        return jsonify(result), 200
    elif estado:
        ordenes = Orden.query.filter_by(estado=estado).all()
        result = []
        for orden in ordenes:
            detalles = [
                {
                    'id': d.id,
                    'producto': {'nombre': d.producto.nombre}
                }
                for d in orden.detalles
            ]
            result.append({'id': orden.id, 'detalles': detalles})
        return jsonify(result), 200
    else:
        return jsonify({'error': 'se requiere parámetro estacion o estado'}), 400

@api_bp.route('/ordenes/<int:orden_id>/detalle/<int:detalle_id>/listo', methods=['POST'])
@login_required()
def marcar_detalle_listo(orden_id, detalle_id):
    detalle = db.get_or_404(OrdenDetalle, detalle_id)
    if detalle.estado == OrdenEstado.LISTO:
        return jsonify({'message': 'Ya estaba marcado como listo'}), 200
    detalle.estado = OrdenEstado.LISTO
    detalle.fecha_listo = utc_now()
    orden = db.session.get(Orden, orden_id)
    # Transition to en_preparacion on first item marked listo
    if orden and orden.estado == OrdenEstado.ENVIADO:
        orden.estado = OrdenEstado.EN_PREPARACION
        socketio.emit('orden_en_preparacion', {
            'orden_id': orden.id,
            'mesa_nombre': orden.mesa.numero if orden.mesa else 'Para Llevar',
        })
    db.session.commit()
    verificar_orden_completa(orden_id)
    socketio.emit('item_listo_notificacion', {
        'item_id': detalle.id,
        'orden_id': orden_id,
        'producto_id': detalle.producto_id,
        'producto_nombre': detalle.producto.nombre,
        'mesa_nombre': orden.mesa.numero if orden and orden.mesa else 'Para Llevar',
        'mensaje': f'¡{detalle.producto.nombre} de la orden {orden_id} está listo!'
    })
    # Emit progress
    all_detalles = OrdenDetalle.query.filter_by(orden_id=orden_id).all()
    items_listos = sum(1 for d in all_detalles if d.estado == OrdenEstado.LISTO)
    socketio.emit('item_progreso', {
        'orden_id': orden_id,
        'items_listos': items_listos,
        'items_total': len(all_detalles),
        'mesa_nombre': orden.mesa.numero if orden and orden.mesa else 'Para Llevar',
    })
    return jsonify({'message': 'Item marcado como listo.'}), 200

@api_bp.route('/ordenes/<int:orden_id>/pagar', methods=['POST'])
@login_required()
def pagar_orden(orden_id):
    """DEPRECATED — Use /meseros/ordenes/<id>/pago (registrar_pago) instead.
    This endpoint was broken (wrong state, no Sale, no inventory, no audit).
    Kept for backwards compatibility but returns error directing to proper flow."""
    return jsonify({
        'error': 'Endpoint deprecado. Usa el flujo de pagos en /meseros/ordenes/<id>/pago.',
        'message': 'Use the proper payment flow via registrar_pago.',
    }), 410


# NOTE: GET/POST for /ordenes/<id>/detalle is now handled by orders_bp
# (add_product_to_order, get_order_details) with IDOR protection.
# PATCH/DELETE also in orders_bp.


@api_bp.route('/ordenes/mesa/<int:mesa_id>')
@login_required()
def orden_activa_mesa(mesa_id):
    """Sprint 4 — 5.1: Retorna la orden activa de una mesa (para mapa de mesas)."""
    orden = Orden.query.filter(
        Orden.mesa_id == mesa_id,
        Orden.estado.notin_(['pagada', 'finalizada', 'cancelada']),
    ).first()
    if orden:
        return jsonify(orden_id=orden.id, estado=orden.estado)
    return jsonify(orden_id=None)
