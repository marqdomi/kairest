from flask import Blueprint, request, jsonify
from backend.models.models import Orden, OrdenEstado
from backend.utils import obtener_ordenes_por_estacion, login_required

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
        # El query param es el nombre de la estación; obtener_ordenes_por_estacion
        # espera el objeto Estacion (usa .id) — resolver antes.
        from backend.models.models import Estacion
        est_obj = Estacion.query.filter(Estacion.nombre.ilike(estacion)).first()
        if not est_obj:
            return jsonify({'error': f'Estación "{estacion}" no encontrada'}), 404
        ordenes = obtener_ordenes_por_estacion(est_obj)
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

# NOTA: `POST /ordenes/<id>/detalle/<detalle_id>/listo` fue eliminado.
# Duplicaba el marcado del KDS pero sin ninguno de sus guards: cualquier usuario
# con sesión (mesero ajeno incluido) podía marcar listo un item de otra orden, y
# ni siquiera comprobaba que el detalle perteneciera a la orden indicada — se
# podía disparar el cambio de estado y las notificaciones sobre una orden que no
# era. Además `api_bp` está exento de CSRF. Ningún frontend la llamaba.
# El flujo vivo es `/cocina/<slug>/marcar/<orden_id>/<detalle_id>`, con alcance
# por estación y orden, y 409 en órdenes cerradas o canceladas.


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
    """Mesas compartidas: retorna TODAS las cuentas activas de una mesa.

    `orden_id` (primera cuenta) se conserva por compatibilidad con clientes
    viejos; `ordenes` trae la lista completa para el selector de cuentas.
    """
    ordenes = Orden.query.filter(
        Orden.mesa_id == mesa_id,
        Orden.estado.notin_([OrdenEstado.PAGADA, OrdenEstado.FINALIZADA, OrdenEstado.CANCELADA]),
    ).order_by(Orden.tiempo_registro).all()
    return jsonify(
        orden_id=ordenes[0].id if ordenes else None,
        ordenes=[{
            'orden_id': o.id,
            'estado': o.estado,
            'alias': o.alias,
            'num_personas': o.num_personas,
            'mesero_id': o.mesero_id,
        } for o in ordenes],
    )
