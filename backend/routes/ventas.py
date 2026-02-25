from flask import Blueprint, request, jsonify, g, session
from backend.utils import login_required
from backend.extensions import db
from backend.models.models import Sale, SaleItem, Producto, Mesa

ventas_bp = Blueprint('ventas', __name__, url_prefix='/ventas')

@ventas_bp.route('/abrir', methods=['POST'])
@login_required(roles=['admin', 'superadmin', 'mesero'])
def abrir_venta():
    mesa_id = request.json.get('mesa_id')
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
    data = request.json
    producto = Producto.query.get_or_404(data['producto_id'])
    cantidad = data['cantidad']
    precio = producto.precio
    item = SaleItem(
        sale_id=sale_id,
        producto_id=producto.id,
        cantidad=cantidad,
        precio_unitario=precio,
        subtotal=precio * cantidad
    )
    sale = Sale.query.get_or_404(sale_id)
    sale.total += item.subtotal
    db.session.add(item)
    db.session.commit()
    return jsonify({'item_id': item.id, 'nuevo_total': float(sale.total)}), 201

@ventas_bp.route('/<int:sale_id>/cerrar', methods=['POST'])
@login_required(roles=['admin', 'superadmin', 'mesero'])
def cerrar_venta(sale_id):
    sale = Sale.query.get_or_404(sale_id)
    sale.estado = 'cerrada'
    db.session.commit()
    return jsonify({'estado': sale.estado, 'total': float(sale.total)})
