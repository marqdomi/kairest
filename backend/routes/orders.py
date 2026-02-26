from flask import Blueprint, request, jsonify, session, g, current_app
from backend.utils import login_required, verificar_orden_completa, verificar_stock_disponible, verificar_propiedad_orden
from backend.models.models import Orden, OrdenDetalle, Producto, Mesa, OrdenEstado
from backend.extensions import db, socketio

orders_bp = Blueprint('orders', __name__, url_prefix='/api')

@orders_bp.route('/ordenes', methods=['POST'])
@login_required()
def create_order():
    data = request.get_json()
    if not data:
        return jsonify({'error': 'Body JSON requerido.'}), 400
    es_para_llevar = data.get('es_para_llevar', False)
    mesa_id = data.get('mesa_id') if not es_para_llevar else None
    # Validate mesa_id FK if provided
    if mesa_id is not None:
        mesa = Mesa.query.get(mesa_id)
        if not mesa:
            return jsonify({'error': f'Mesa {mesa_id} no existe.'}), 404
    mesero_id = session.get('user_id')
    nueva_orden = Orden(mesa_id=mesa_id, mesero_id=mesero_id,
                        es_para_llevar=es_para_llevar,
                        sucursal_id=getattr(g, 'sucursal_id', None))
    db.session.add(nueva_orden)
    db.session.commit()
    socketio.emit('order_created', {
        'orden_id': nueva_orden.id,
        'estado': nueva_orden.estado,
        'es_para_llevar': nueva_orden.es_para_llevar,
        'tiempo_registro': nueva_orden.tiempo_registro.isoformat()
    })
    return jsonify({'message': 'Orden creada exitosamente.', 'orden_id': nueva_orden.id}), 201

@orders_bp.route('/ordenes/<int:orden_id>/estado', methods=['PUT'])
@login_required()
@verificar_propiedad_orden
def update_order_status(orden_id):
    data = request.get_json()
    if not data:
        return jsonify({'error': 'Body JSON requerido.'}), 400
    nuevo_estado = data.get('estado')
    ESTADOS_VALIDOS = [OrdenEstado.PENDIENTE, OrdenEstado.ENVIADO, OrdenEstado.EN_PREPARACION,
                        OrdenEstado.LISTA_PARA_ENTREGAR, OrdenEstado.COMPLETADA,
                        OrdenEstado.PAGADA, OrdenEstado.CANCELADA]
    if nuevo_estado not in ESTADOS_VALIDOS:
        return jsonify({'error': f'Estado no válido. Debe ser uno de: {", ".join(ESTADOS_VALIDOS)}.'}), 400
    orden = Orden.query.get_or_404(orden_id)
    orden.estado = nuevo_estado
    db.session.commit()
    socketio.emit('order_updated', {
        'orden_id': orden.id,
        'nuevo_estado': orden.estado
    })
    return jsonify({'message': 'Estado actualizado.', 'orden_id': orden.id}), 200

@orders_bp.route('/ordenes/<int:orden_id>/detalle', methods=['POST'])
@login_required()
@verificar_propiedad_orden
def add_product_to_order(orden_id):
    data = request.get_json()
    if not data or 'producto_id' not in data:
        return jsonify({'error': 'Body JSON con producto_id requerido.'}), 400
    producto_id = data.get('producto_id')
    cantidad = data.get('cantidad', 1)
    notas = data.get('notas', '').strip()
    producto = Producto.query.get_or_404(producto_id)
    orden = Orden.query.get_or_404(orden_id)

    # Validación de stock (Sprint 2 — 3.2)
    if current_app.config.get('INVENTARIO_VALIDAR_STOCK'):
        disponible, faltantes, warns = verificar_stock_disponible(producto_id, cantidad)
        if not disponible:
            return jsonify({
                'error': 'Stock insuficiente',
                'faltantes': faltantes,
            }), 409

    # Merge: only merge with items that are still 'pendiente' (not listo/entregado)
    existing = OrdenDetalle.query.filter_by(
        orden_id=orden.id, producto_id=producto.id, estado=OrdenEstado.PENDIENTE
    ).all()
    merged = False
    for d in existing:
        existing_notas = (d.notas or '').strip()
        if existing_notas == notas:
            d.cantidad += cantidad
            detalle = d
            merged = True
            break

    if not merged:
        detalle = OrdenDetalle(
            orden_id=orden.id,
            producto_id=producto.id,
            cantidad=cantidad,
            notas=notas,
            precio_unitario=producto.precio,
            estado=OrdenEstado.PENDIENTE,
        )
        db.session.add(detalle)

    db.session.commit()

    # Emit real-time update
    socketio.emit('order_detail_added', {
        'orden_id': orden.id,
        'detalle': {
            'id': detalle.id,
            'producto_id': producto.id,
            'producto_nombre': producto.nombre,
            'cantidad': detalle.cantidad,
            'notas': detalle.notas or ''
        }
    })

    # If the order is already sent to kitchen, notify KDS about new items
    if orden.estado not in ('pendiente',):
        socketio.emit('nueva_orden_cocina', {
            'orden_id': orden.id,
            'mensaje': f'Nuevos productos en orden #{orden.id}.',
        })

    verificar_orden_completa(orden.id)
    return jsonify({
        'message': 'Producto agregado a la orden.',
        'detalle_id': detalle.id
    }), 201

@orders_bp.route('/ordenes/<int:orden_id>/detalle', methods=['GET'])
@login_required()
@verificar_propiedad_orden
def get_order_details(orden_id):
    detalles = OrdenDetalle.query.filter_by(orden_id=orden_id).all()
    detalles_data = []
    for d in detalles:
        # Fallback: if precio_unitario is null (old data), use current product price
        precio = d.precio_unitario if d.precio_unitario is not None else d.producto.precio
        detalles_data.append({
            'id': d.id,
            'producto_id': d.producto_id,
            'producto_nombre': d.producto.nombre,
            'cantidad': d.cantidad,
            'notas': d.notas or '',
            'precio_unitario': float(precio),
            'estado': d.estado,
        })
    return jsonify(detalles_data), 200


@orders_bp.route('/ordenes/<int:orden_id>/detalle/<int:detalle_id>', methods=['PATCH'])
@login_required()
@verificar_propiedad_orden
def update_order_detail(orden_id, detalle_id):
    """Update quantity or notes of an order detail item."""
    detalle = OrdenDetalle.query.filter_by(id=detalle_id, orden_id=orden_id).first_or_404()
    data = request.get_json()
    if not data:
        return jsonify({'error': 'Body JSON requerido.'}), 400
    if 'cantidad' in data:
        nueva_cantidad = int(data['cantidad'])
        if nueva_cantidad < 1:
            return jsonify({'error': 'Cantidad mínima es 1.'}), 400
        if current_app.config.get('INVENTARIO_VALIDAR_STOCK'):
            diff = nueva_cantidad - detalle.cantidad
            if diff > 0:
                disponible, faltantes, _ = verificar_stock_disponible(detalle.producto_id, diff)
                if not disponible:
                    return jsonify({'error': 'Stock insuficiente', 'faltantes': faltantes}), 409
        detalle.cantidad = nueva_cantidad
    if 'notas' in data:
        detalle.notas = data['notas']
    db.session.commit()
    socketio.emit('order_detail_updated', {
        'orden_id': orden_id,
        'detalle_id': detalle_id,
        'cantidad': detalle.cantidad,
    })
    return jsonify({'message': 'Detalle actualizado.', 'cantidad': detalle.cantidad}), 200


@orders_bp.route('/ordenes/<int:orden_id>/detalle/<int:detalle_id>', methods=['DELETE'])
@login_required()
@verificar_propiedad_orden
def delete_order_detail(orden_id, detalle_id):
    """Remove a product from the order."""
    detalle = OrdenDetalle.query.filter_by(id=detalle_id, orden_id=orden_id).first_or_404()
    db.session.delete(detalle)
    db.session.commit()
    socketio.emit('order_detail_removed', {
        'orden_id': orden_id,
        'detalle_id': detalle_id,
    })
    verificar_orden_completa(orden_id)
    return jsonify({'message': 'Producto eliminado de la orden.'}), 200


@orders_bp.route('/ordenes/<int:orden_id>/notificar-cocina', methods=['POST'])
@login_required()
@verificar_propiedad_orden
def notificar_cocina(orden_id):
    """Manually re-notify kitchen about pending items in an already-sent order."""
    orden = Orden.query.get_or_404(orden_id)
    if orden.estado == OrdenEstado.PENDIENTE:
        return jsonify({'error': 'Usa "Enviar a Cocina" para órdenes pendientes.'}), 400
    pendientes = OrdenDetalle.query.filter_by(orden_id=orden_id, estado=OrdenEstado.PENDIENTE).count()
    if pendientes == 0:
        return jsonify({'error': 'No hay productos nuevos pendientes.'}), 400
    socketio.emit('nueva_orden_cocina', {
        'orden_id': orden.id,
        'mensaje': f'Nuevos productos ({pendientes}) en orden #{orden.id}.',
    })
    return jsonify({'message': f'Cocina notificada — {pendientes} producto(s) nuevo(s).'}), 200