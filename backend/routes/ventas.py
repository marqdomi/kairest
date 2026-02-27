from flask import Blueprint, request, jsonify, g, session
from backend.utils import login_required
from backend.extensions import db
from backend.models.models import Sale, SaleItem, Producto, Mesa

ventas_bp = Blueprint('ventas', __name__, url_prefix='/ventas')

@ventas_bp.route('/abrir', methods=['POST'])
@login_required(roles=['admin', 'superadmin', 'mesero'])
def abrir_venta():
    data = request.get_json()
    if not data:
        return jsonify({'error': 'Body JSON requerido.'}), 400
    mesa_id = data.get('mesa_id')
    sale = Sale(
        usuario_id=session.get('user_id'),
        mesa_id=mesa_id,
        sucursal_id=getattr(g, 'sucursal_id', None),
    )
    db.session.add(sale)
    db.session.commit()
    return jsonify({'sale_id': sale.id}), 201

@ventas_bp.route('/<int:sale_id>/items', methods=['POST'])
@login_required(roles=['admin', 'superadmin', 'mesero'])
def agregar_item(sale_id):
    data = request.get_json()
    if not data or 'producto_id' not in data:
        return jsonify({'error': 'Body JSON con producto_id requerido.'}), 400
    sale = db.get_or_404(Sale, sale_id)
    # Ownership check (admin/superadmin bypass)
    if session.get('rol') not in ('admin', 'superadmin') and sale.usuario_id != session.get('user_id'):
        return jsonify({'error': 'No tienes permiso para modificar esta venta.'}), 403
    if sale.estado == 'cerrada':
        return jsonify({'error': 'La venta ya está cerrada.'}), 400
    producto = db.get_or_404(Producto, data['producto_id'])
    cantidad = data.get('cantidad', 1)
    if not isinstance(cantidad, (int, float)) or cantidad < 1:
        return jsonify({'error': 'Cantidad debe ser >= 1.'}), 400
    precio = producto.precio
    item = SaleItem(
        sale_id=sale_id,
        producto_id=producto.id,
        cantidad=cantidad,
        precio_unitario=precio,
        subtotal=precio * cantidad
    )
    sale.total += item.subtotal
    db.session.add(item)
    db.session.commit()
    return jsonify({'item_id': item.id, 'nuevo_total': float(sale.total)}), 201

@ventas_bp.route('/<int:sale_id>/cerrar', methods=['POST'])
@login_required(roles=['admin', 'superadmin', 'mesero'])
def cerrar_venta(sale_id):
    sale = db.get_or_404(Sale, sale_id)
    # Ownership check
    if session.get('rol') not in ('admin', 'superadmin') and sale.usuario_id != session.get('user_id'):
        return jsonify({'error': 'No tienes permiso para cerrar esta venta.'}), 403
    if sale.estado == 'cerrada':
        return jsonify({'error': 'La venta ya está cerrada.'}), 400
    sale.estado = 'cerrada'
    db.session.commit()
    return jsonify({'estado': sale.estado, 'total': float(sale.total)})
