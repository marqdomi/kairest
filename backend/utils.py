import logging
from functools import wraps
from decimal import Decimal
from flask import session, redirect, url_for, flash, request, jsonify, g, current_app
from backend.models.models import Orden, OrdenDetalle, Producto, RecetaDetalle, Mesa, OrdenEstado
from backend.extensions import db, socketio

logger = logging.getLogger(__name__)


# =====================================================================
# Órdenes borrador
# =====================================================================

def no_es_borrador():
    """Condición SQL: la orden ya es real (no un borrador vacío).

    Al tocar "Nueva orden" se crea la fila antes de agregar nada, porque el carrito
    se guarda producto por producto (así no se pierde la orden si el celular se
    bloquea a media captura). Mientras esté vacía no debe existir para nadie: ni en
    la lista, ni en los contadores, ni ocupando la mesa.
    """
    return db.or_(Orden.estado != OrdenEstado.PENDIENTE, Orden.detalles.any())


def limpiar_borradores(mesero_id, minutos=10):
    """Borra los borradores vacíos que el mesero abandonó hace rato.

    Se llama al abrir la lista de órdenes: barre solo, sin depender de que el mesero
    use el botón "Regresar" (puede salir con el gesto del teléfono o cerrar la app).
    """
    from datetime import timedelta
    from backend.models.models import utc_now

    limite = utc_now().replace(tzinfo=None) - timedelta(minutes=minutos)
    viejos = Orden.query.filter(
        Orden.mesero_id == mesero_id,
        Orden.estado == OrdenEstado.PENDIENTE,
        Orden.tiempo_registro < limite,
        ~Orden.detalles.any(),
    ).all()
    if not viejos:
        return 0
    mesas = {o.mesa_id for o in viejos if o.mesa_id}
    for o in viejos:
        db.session.delete(o)
    db.session.commit()
    for mesa_id in mesas:
        actualizar_estado_mesa(mesa_id)
    db.session.commit()
    logger.info('Borradores vacíos eliminados: %s (mesero=%s)', len(viejos), mesero_id)
    return len(viejos)


# =====================================================================
# Multi-sucursal: filtrado de queries (Sprint 2 — 2.2)
# =====================================================================

def filtrar_por_sucursal(query, modelo):
    """Agrega filtro `.filter(modelo.sucursal_id == g.sucursal_id)` si hay
    sucursal activa en sesión. Superadmin con sucursal_id=None ve todo."""
    sucursal_id = getattr(g, 'sucursal_id', None)
    if sucursal_id is None:
        return query  # superadmin "Todas" — sin filtro
    if not hasattr(modelo, 'sucursal_id'):
        return query  # modelo sin FK sucursal
    return query.filter(modelo.sucursal_id == sucursal_id)


# =====================================================================
# Validación de stock (Sprint 2 — 3.2)
# =====================================================================

def verificar_stock_disponible(producto_id, cantidad):
    """Verifica si hay stock suficiente para un producto según su receta.

    Returns:
        (disponible: bool, faltantes: list[dict], warnings: list[dict])
        - disponible=True si stock >= requerido (o no tiene receta)
        - faltantes: ingredientes con stock 0 o negativo
        - warnings: ingredientes con stock bajo (<= stock_minimo)
    """
    receta = RecetaDetalle.query.filter_by(producto_id=producto_id).all()
    if not receta:
        return True, [], []  # Sin receta, no se valida

    faltantes = []
    warnings = []
    for item in receta:
        ing = item.ingrediente
        requerido = item.cantidad_por_unidad * cantidad
        if ing.stock_actual <= 0:
            faltantes.append({
                'ingrediente': ing.nombre,
                'unidad': ing.unidad,
                'stock_actual': float(ing.stock_actual),
                'requerido': float(requerido),
            })
        elif ing.stock_actual < requerido:
            faltantes.append({
                'ingrediente': ing.nombre,
                'unidad': ing.unidad,
                'stock_actual': float(ing.stock_actual),
                'requerido': float(requerido),
            })
        elif ing.stock_actual <= ing.stock_minimo:
            warnings.append({
                'ingrediente': ing.nombre,
                'unidad': ing.unidad,
                'stock_actual': float(ing.stock_actual),
                'stock_minimo': float(ing.stock_minimo),
            })

    disponible = len(faltantes) == 0
    return disponible, faltantes, warnings


# =====================================================================
# Flujo de mesa automático (Sprint 2 — 3.3)
# =====================================================================

def actualizar_estado_mesa(mesa_id, nuevo_estado=None):
    """Actualiza el estado de una mesa y emite evento Socket.IO.

    Si nuevo_estado=None, calcula automáticamente:
    - 'ocupada' si hay órdenes activas
    - 'disponible' si no hay órdenes activas (y no tiene reservación próxima)

    Returns: nuevo estado de la mesa o None si no se cambió
    """
    if not mesa_id:
        return None

    mesa = db.session.get(Mesa, mesa_id)
    if not mesa:
        return None

    if nuevo_estado is None:
        # Calcular: ¿hay órdenes activas en esta mesa?
        # Un borrador vacío no ocupa la mesa: si el mesero se arrepiente y regresa,
        # la mesa debe seguir libre para quien sea.
        ordenes_activas = Orden.query.filter(
            Orden.mesa_id == mesa_id,
            Orden.estado.notin_([OrdenEstado.PAGADA, OrdenEstado.FINALIZADA, OrdenEstado.CANCELADA]),
            no_es_borrador(),
        ).count()
        nuevo_estado = 'ocupada' if ordenes_activas > 0 else 'disponible'

    estado_anterior = mesa.estado
    if estado_anterior == nuevo_estado:
        return None  # Sin cambio

    # No revertir 'reservada' o 'mantenimiento' automáticamente
    if estado_anterior in ('reservada', 'mantenimiento') and nuevo_estado == 'disponible':
        return None

    mesa.estado = nuevo_estado
    db.session.flush()

    socketio.emit('mesa_estado_actualizado', {
        'mesa_id': mesa.id,
        'numero': mesa.numero,
        'estado_anterior': estado_anterior,
        'estado': nuevo_estado,
    })
    logger.info('Mesa %s: %s → %s', mesa.numero, estado_anterior, nuevo_estado)
    return nuevo_estado


def verificar_orden_completa(orden_id):
    """
    Marca la orden como 'lista_para_entregar' si todos sus detalles están en estado 'listo'.
    """
    detalles = OrdenDetalle.query.filter_by(orden_id=orden_id).all()
    try:
        # Listo o ya entregado: si el mesero llevó los refrescos antes que la comida,
        # contar sólo "listo" dejaba la orden en preparación y nunca avisaba
        if detalles and all(d.estado in (OrdenEstado.LISTO, 'entregado') for d in detalles):
            orden = db.session.get(Orden, orden_id)
            # CANCELADA incluida: un KDS con pantalla stale que marca el último
            # item no debe resucitar una orden ya cancelada.
            if orden.estado not in [OrdenEstado.FINALIZADA, OrdenEstado.PAGADA, OrdenEstado.LISTA_PARA_ENTREGAR, OrdenEstado.CANCELADA]:
                orden.estado = OrdenEstado.LISTA_PARA_ENTREGAR
                db.session.commit()
                socketio.emit('orden_completa_lista', {
                    'orden_id': orden.id,
                    'mesa_nombre': orden.mesa.numero if orden.mesa else 'Para Llevar',
                    'mensaje': f'¡Toda la orden {orden.id} está lista para entregar!'
                })
                logger.info('Orden %s marcada como lista_para_entregar', orden_id)
            return True
    except AttributeError:
        return False
    return False


def login_required(roles=None):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            if 'user_id' not in session:
                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return jsonify({'error': 'Debes iniciar sesión'}), 401
                flash('Debes iniciar sesión', 'warning')
                return redirect(url_for('auth.login'))

            if roles:
                allowed = roles if isinstance(roles, (list, tuple)) else [roles]
                user_role = session.get('rol')

                acceso_denegado = (user_role != 'superadmin' and user_role not in allowed)

                if acceso_denegado:
                    logger.warning(
                        'Acceso denegado: usuario_id=%s rol=%s ruta=%s roles_requeridos=%s',
                        session.get('user_id'), user_role, request.path, allowed,
                    )
                    flash('No tienes permiso para acceder a esta página', 'danger')
                    if user_role == 'mesero':
                        return redirect(url_for('meseros.view_meseros'))
                    elif user_role == 'cocina' or session.get('estacion_id'):
                        return redirect(url_for('cocina.index'))
                    elif user_role in ('admin', 'superadmin'):
                        return redirect(url_for('admin.dashboard'))
                    return redirect(url_for('auth.login'))

            return func(*args, **kwargs)
        return wrapper
    return decorator


def verificar_propiedad_orden(f):
    """Decorator que verifica que el mesero actual es dueño de la orden.

    Admin y superadmin pueden acceder a cualquier orden.
    Si el mesero no es dueño, retorna 403.
    """
    @wraps(f)
    def wrapper(orden_id, *args, **kwargs):
        user_id = session.get('user_id')
        user_rol = session.get('rol')

        # Admin y superadmin pueden ver todas las órdenes
        if user_rol in ('admin', 'superadmin'):
            return f(orden_id, *args, **kwargs)

        orden = db.session.get(Orden, orden_id)
        if not orden:
            return jsonify(error='Orden no encontrada'), 404

        if orden.mesero_id != user_id:
            logger.warning(
                'IDOR bloqueado: usuario_id=%s intentó acceder a orden_id=%s (dueño=%s) ip=%s',
                user_id, orden_id, orden.mesero_id, request.remote_addr,
            )
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or \
               request.content_type == 'application/json':
                return jsonify(error='No tienes permiso para acceder a esta orden'), 403
            flash('No tienes permiso para acceder a esta orden', 'danger')
            return redirect(url_for('meseros.view_meseros'))

        return f(orden_id, *args, **kwargs)
    return wrapper


def obtener_ordenes_por_estacion(estacion):
    """
    Devuelve un diccionario que mapea cada orden_id a la lista de
    OrdenDetalle pendientes para la estación indicada.
    """
    from backend.models.models import Producto
    detalles = (
        OrdenDetalle.query
        .filter(
            OrdenDetalle.estado != OrdenEstado.LISTO,
            OrdenDetalle.producto.has(Producto.estacion_id == estacion.id)
        )
        .all()
    )
    ordenes_por_estacion = {}
    for d in detalles:
        ordenes_por_estacion.setdefault(d.orden_id, []).append(d)
    return ordenes_por_estacion
