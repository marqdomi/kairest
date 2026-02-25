import logging
from flask import Blueprint, render_template, session, flash, redirect, url_for, jsonify, abort, request
from backend.models.models import Orden, OrdenDetalle, Producto, Estacion, Usuario
from backend.utils import login_required, verificar_orden_completa
from backend.extensions import db, socketio
from flask_login import current_user
from datetime import date, datetime
from text_unidecode import unidecode
import re

logger = logging.getLogger(__name__)

cocina_bp = Blueprint('cocina', __name__, url_prefix='/cocina')


# ── Helpers ─────────────────────────────────────────────────────

# Color palette for dynamic station assignment
_STATION_COLORS = [
    'var(--cl-red-500)',           # red
    'var(--cl-amber-500, #f59e0b)',  # amber
    'var(--cl-blue-500, #3b82f6)',   # blue
    'var(--cl-green-500, #22c55e)',  # green
    'var(--cl-purple-500, #a855f7)', # purple
    'var(--cl-orange-500, #f97316)', # orange
    'var(--cl-teal-500, #14b8a6)',   # teal
    'var(--cl-pink-500, #ec4899)',   # pink
]


def _slugify(name):
    """Convert station name to URL-safe slug: 'Parrilla' -> 'parrilla'."""
    slug = unidecode(name).lower().strip()
    slug = re.sub(r'[^a-z0-9]+', '-', slug)
    return slug.strip('-')


def _get_estacion_or_404(slug):
    """Look up an Estacion by slug (slugified nombre). Abort 404 if not found."""
    estaciones = Estacion.query.all()
    for est in estaciones:
        if _slugify(est.nombre) == slug:
            return est
    abort(404)


def _get_station_color(estacion_id):
    """Assign a color to a station based on its ID."""
    return _STATION_COLORS[(estacion_id - 1) % len(_STATION_COLORS)]


def _build_cfg(estacion):
    """Build a KDS config dict for a station (replaces old STATION_CONFIG)."""
    slug = _slugify(estacion.nombre)
    return {
        'estacion_db': estacion.nombre,
        'slug': slug,
        'label': estacion.nombre.title(),
        'color': _get_station_color(estacion.id),
    }


def _user_can_access_station(estacion):
    """Check if the current user can access a given station's KDS view."""
    user_role = session.get('rol', '')
    if user_role in ('admin', 'superadmin'):
        return True
    if user_role == 'cocina':
        # User must be assigned to this station
        user_estacion_id = session.get('estacion_id')
        return user_estacion_id == estacion.id
    # Backward compatibility: legacy role matches station name
    if user_role == estacion.nombre.lower() or user_role == _slugify(estacion.nombre):
        return True
    # Mesero can access any station (for delivery/bebidas scenarios)
    if user_role == 'mesero':
        return True
    return False


def _require_station_access(estacion):
    """Abort 403 if user cannot access the station."""
    if not _user_can_access_station(estacion):
        flash('No tienes permiso para acceder a esta estación', 'danger')
        abort(403)


def _query_pending_detalles(estacion_nombre):
    """Return pending + listo OrdenDetalle items for a given station.
    Includes 'listo' items so the KDS can show per-item progress (check-circles).
    Only shows orders in enviado/en_preparacion — once all items are listo
    the order transitions to lista_para_entregar and leaves the KDS.
    """
    return OrdenDetalle.query \
        .join(Orden, OrdenDetalle.orden_id == Orden.id) \
        .join(Producto, OrdenDetalle.producto_id == Producto.id) \
        .join(Estacion, Producto.estacion_id == Estacion.id) \
        .filter(
            Estacion.nombre == estacion_nombre,
            OrdenDetalle.estado.in_(['pendiente', 'listo']),
            Orden.estado.in_(['enviado', 'en_preparacion'])
        ) \
        .order_by(Orden.tiempo_registro.asc(), OrdenDetalle.id.asc()).all()


def _group_by_orden(detalles):
    """Group a flat list of OrdenDetalle into {Orden: [detalles]} dict."""
    grouped = {}
    for d in detalles:
        grouped.setdefault(d.orden, []).append(d)
    return grouped


def _marcar_listo(orden_id, detalle_id):
    """Mark a single OrdenDetalle as 'listo', set fecha_listo, handle en_preparacion transition."""
    detalle = OrdenDetalle.query.get_or_404(detalle_id)
    if detalle.estado == 'listo':
        return jsonify({'message': 'Ya estaba marcado como listo'}), 200
    detalle.estado = 'listo'
    detalle.fecha_listo = datetime.utcnow()
    orden = Orden.query.get(orden_id)

    # Transition to en_preparacion on first item marked listo
    if orden and orden.estado == 'enviado':
        orden.estado = 'en_preparacion'
        socketio.emit('orden_en_preparacion', {
            'orden_id': orden.id,
            'mesa_nombre': orden.mesa.numero if orden.mesa else 'Para Llevar',
        })
        logger.info('Orden %s → en_preparacion', orden_id)

    db.session.commit()
    verificar_orden_completa(orden_id)

    # Emit item-level notification
    socketio.emit('item_listo_notificacion', {
        'item_id': detalle.id,
        'orden_id': orden_id,
        'producto_id': detalle.producto_id,
        'producto_nombre': detalle.producto.nombre,
        'mesa_nombre': orden.mesa.numero if orden and orden.mesa else 'Para Llevar',
        'mensaje': f'¡{detalle.producto.nombre} de la orden {orden_id} está listo!'
    })

    # Emit progress update for meseros
    _emit_item_progreso(orden_id)

    return jsonify({'message': 'Producto marcado como listo'}), 200


def _emit_item_progreso(orden_id):
    """Emit item_progreso Socket.IO event with listo/total counts."""
    all_detalles = OrdenDetalle.query.filter_by(orden_id=orden_id).all()
    items_listos = sum(1 for d in all_detalles if d.estado == 'listo')
    items_total = len(all_detalles)
    orden = Orden.query.get(orden_id)
    socketio.emit('item_progreso', {
        'orden_id': orden_id,
        'items_listos': items_listos,
        'items_total': items_total,
        'mesa_nombre': orden.mesa.numero if orden and orden.mesa else 'Para Llevar',
    })


# ── API endpoint ────────────────────────────────────────────────
@cocina_bp.route('/api/orders')
@login_required(roles=['cocina', 'mesero', 'admin', 'superadmin'])
def api_orders():
    ordenes = Orden.query.filter(Orden.estado != 'pagado', Orden.estado != 'finalizada').all()
    return jsonify([{
        'id': o.id, 'estado': o.estado,
        'tiempo_registro': o.tiempo_registro.isoformat()
    } for o in ordenes]), 200


# ── Stats API: completadas hoy + avg time ──────────────────────
@cocina_bp.route('/<slug>/stats')
@login_required(roles=['cocina', 'mesero', 'admin', 'superadmin'])
def station_stats(slug):
    """Return today's stats for a KDS station: completed count + avg time."""
    estacion = _get_estacion_or_404(slug)
    _require_station_access(estacion)
    hoy = date.today()

    # Completed detalles today (items with fecha_listo set today)
    completados = OrdenDetalle.query \
        .join(Producto, OrdenDetalle.producto_id == Producto.id) \
        .join(Estacion, Producto.estacion_id == Estacion.id) \
        .join(Orden, OrdenDetalle.orden_id == Orden.id) \
        .filter(
            Estacion.nombre == estacion.nombre,
            OrdenDetalle.estado == 'listo',
            OrdenDetalle.fecha_listo.isnot(None),
            db.func.date(OrdenDetalle.fecha_listo) == hoy,
        ).all()

    # Count unique orders that contain at least one completed item
    ordenes_completadas = len(set(d.orden_id for d in completados))

    # Average time: from orden.tiempo_registro to detalle.fecha_listo
    tiempos = []
    for d in completados:
        if d.orden and d.orden.tiempo_registro and d.fecha_listo:
            diff = (d.fecha_listo - d.orden.tiempo_registro).total_seconds() / 60.0
            if 0 < diff < 240:  # ignore outliers > 4h
                tiempos.append(diff)

    avg_min = round(sum(tiempos) / len(tiempos), 1) if tiempos else 0

    # Previous shift (yesterday) avg time for comparison
    from datetime import timedelta
    ayer = hoy - timedelta(days=1)
    completados_ayer = OrdenDetalle.query \
        .join(Producto, OrdenDetalle.producto_id == Producto.id) \
        .join(Estacion, Producto.estacion_id == Estacion.id) \
        .join(Orden, OrdenDetalle.orden_id == Orden.id) \
        .filter(
            Estacion.nombre == estacion.nombre,
            OrdenDetalle.estado == 'listo',
            OrdenDetalle.fecha_listo.isnot(None),
            db.func.date(OrdenDetalle.fecha_listo) == ayer,
        ).all()

    tiempos_ayer = []
    for d in completados_ayer:
        if d.orden and d.orden.tiempo_registro and d.fecha_listo:
            diff = (d.fecha_listo - d.orden.tiempo_registro).total_seconds() / 60.0
            if 0 < diff < 240:
                tiempos_ayer.append(diff)

    avg_ayer = round(sum(tiempos_ayer) / len(tiempos_ayer), 1) if tiempos_ayer else 0

    return jsonify({
        'completadas': ordenes_completadas,
        'items_completados': len(completados),
        'avg_minutos': avg_min,
        'avg_turno_anterior': avg_ayer,
    }), 200


# ── API: list all stations (for navbar, selectors, etc.) ───────
@cocina_bp.route('/api/estaciones')
@login_required(roles=['mesero', 'cocina', 'admin', 'superadmin'])
def api_estaciones():
    """Return all stations with their slugs and colors."""
    estaciones = Estacion.query.order_by(Estacion.nombre).all()
    return jsonify([{
        'id': e.id,
        'nombre': e.nombre,
        'slug': _slugify(e.nombre),
        'color': _get_station_color(e.id),
        'label': e.nombre.title(),
    } for e in estaciones]), 200


# ── Station index: redirect to user's assigned station ─────────
@cocina_bp.route('/')
@login_required(roles=['cocina', 'mesero', 'admin', 'superadmin'])
def index():
    """Redirect cocina users to their assigned station, or show station list."""
    user_role = session.get('rol', '')
    user_estacion_id = session.get('estacion_id')

    # If user has an assigned station, go directly there
    if user_estacion_id:
        est = Estacion.query.get(user_estacion_id)
        if est:
            return redirect(url_for('cocina.station_view', slug=_slugify(est.nombre)))

    # Legacy: role matches a station name
    if user_role not in ('admin', 'superadmin', 'mesero', 'cocina'):
        estaciones = Estacion.query.all()
        for est in estaciones:
            if user_role == est.nombre.lower() or user_role == _slugify(est.nombre):
                return redirect(url_for('cocina.station_view', slug=_slugify(est.nombre)))

    # Admin/superadmin: show first station or station list
    first = Estacion.query.order_by(Estacion.id).first()
    if first:
        return redirect(url_for('cocina.station_view', slug=_slugify(first.nombre)))
    flash('No hay estaciones configuradas.', 'warning')
    return redirect(url_for('auth.login'))


# ── Dynamic station view ───────────────────────────────────────
@cocina_bp.route('/<slug>')
@login_required(roles=['cocina', 'mesero', 'admin', 'superadmin'])
def station_view(slug):
    """Unified KDS view for any station, resolved by slug."""
    estacion = _get_estacion_or_404(slug)
    _require_station_access(estacion)
    cfg = _build_cfg(estacion)
    detalles = _query_pending_detalles(estacion.nombre)
    ordenes_data = _group_by_orden(detalles)
    return render_template('kds_station.html',
                           ordenes_data=ordenes_data, now_utc=datetime.utcnow(),
                           station=cfg['slug'], station_slug=cfg['slug'], cfg=cfg)


# ── Dynamic fragment endpoint (AJAX refresh) ───────────────────
@cocina_bp.route('/<slug>/fragmento_ordenes')
@login_required(roles=['cocina', 'mesero', 'admin', 'superadmin'])
def station_fragment(slug):
    """Return JSON with rendered HTML fragment + count for a station."""
    estacion = _get_estacion_or_404(slug)
    _require_station_access(estacion)
    detalles = _query_pending_detalles(estacion.nombre)
    ordenes_data = _group_by_orden(detalles)
    total = sum(d.cantidad for d in detalles)
    html = render_template('cocina/_kds_cards_fragment.html',
                           ordenes_data=ordenes_data, now_utc=datetime.utcnow())
    return jsonify({'html': html, 'conteo_productos': total})


# ── Dynamic mark-done endpoint ─────────────────────────────────
@cocina_bp.route('/<slug>/marcar/<int:orden_id>/<int:detalle_id>',
                  methods=['POST'])
@login_required(roles=['cocina', 'mesero', 'admin', 'superadmin'])
def station_marcar(slug, orden_id, detalle_id):
    """Mark a single item as done in any station."""
    estacion = _get_estacion_or_404(slug)
    _require_station_access(estacion)
    return _marcar_listo(orden_id, detalle_id)


# ── Batch mark-done endpoint ────────────────────────────────────
@cocina_bp.route('/<slug>/batch-listo', methods=['POST'])
@login_required(roles=['cocina', 'mesero', 'admin', 'superadmin'])
def station_batch_listo(slug):
    """Mark multiple items as done in a single request."""
    estacion = _get_estacion_or_404(slug)
    _require_station_access(estacion)
    data = request.get_json(silent=True) or {}
    detalle_ids = data.get('detalle_ids', [])
    orden_id = data.get('orden_id')
    if not detalle_ids or not orden_id:
        return jsonify({'error': 'Se requiere orden_id y detalle_ids'}), 400

    orden = Orden.query.get_or_404(orden_id)
    # Transition to en_preparacion on first item if still enviado
    if orden.estado == 'enviado':
        orden.estado = 'en_preparacion'
        socketio.emit('orden_en_preparacion', {
            'orden_id': orden.id,
            'mesa_nombre': orden.mesa.numero if orden.mesa else 'Para Llevar',
        })
        logger.info('Orden %s → en_preparacion (batch)', orden_id)

    marked = []
    now = datetime.utcnow()
    for did in detalle_ids:
        detalle = OrdenDetalle.query.get(did)
        if detalle and detalle.estado != 'listo':
            detalle.estado = 'listo'
            detalle.fecha_listo = now
            marked.append(detalle)

    db.session.commit()
    verificar_orden_completa(orden_id)

    # Single Socket.IO emission for the batch
    if marked:
        socketio.emit('item_listo_notificacion', {
            'item_id': marked[-1].id,
            'orden_id': orden_id,
            'producto_id': marked[-1].producto_id,
            'producto_nombre': f'{len(marked)} items',
            'mesa_nombre': orden.mesa.numero if orden.mesa else 'Para Llevar',
            'mensaje': f'¡{len(marked)} items de la orden {orden_id} están listos!'
        })
        _emit_item_progreso(orden_id)

    return jsonify({'message': f'{len(marked)} items marcados como listos'}), 200


# ── Backward-compatible aliases for old endpoints ──────────────
# These keep url_for('cocina.dashboard_taqueros_view') etc. working
# in templates that still reference them. They redirect to the new
# dynamic routes. The endpoint names are preserved for url_for().

@cocina_bp.route('/legacy/taqueros', endpoint='dashboard_taqueros_view')
@login_required(roles=['cocina', 'mesero', 'admin', 'superadmin'])
def _compat_taqueros():
    return redirect(url_for('cocina.station_view', slug='taquero'))

@cocina_bp.route('/legacy/comal', endpoint='dashboard_comal_view')
@login_required(roles=['cocina', 'mesero', 'admin', 'superadmin'])
def _compat_comal():
    return redirect(url_for('cocina.station_view', slug='comal'))

@cocina_bp.route('/legacy/bebidas', endpoint='dashboard_bebidas_view')
@login_required(roles=['cocina', 'mesero', 'admin', 'superadmin'])
def _compat_bebidas():
    return redirect(url_for('cocina.station_view', slug='bebidas'))


# ── KDS Historial + Analytics ──────────────────────────────────
@cocina_bp.route('/historial')
@login_required(roles=['admin', 'superadmin'])
def historial_dia():
    from datetime import timedelta
    from sqlalchemy.orm import joinedload

    # Filters from query params
    fecha_str = request.args.get('fecha', '')
    estacion_slug = request.args.get('estacion', '')

    try:
        fecha = date.fromisoformat(fecha_str) if fecha_str else date.today()
    except ValueError:
        fecha = date.today()

    # All stations for the dropdown
    estaciones = Estacion.query.order_by(Estacion.nombre).all()
    estacion_filter = None
    if estacion_slug:
        for est in estaciones:
            if _slugify(est.nombre) == estacion_slug:
                estacion_filter = est
                break

    # Query completed detalles for the date (with fecha_listo set)
    q = OrdenDetalle.query \
        .join(Producto, OrdenDetalle.producto_id == Producto.id) \
        .join(Estacion, Producto.estacion_id == Estacion.id) \
        .join(Orden, OrdenDetalle.orden_id == Orden.id) \
        .options(
            joinedload(OrdenDetalle.producto),
            joinedload(OrdenDetalle.orden).joinedload(Orden.mesa),
        ) \
        .filter(
            OrdenDetalle.estado == 'listo',
            OrdenDetalle.fecha_listo.isnot(None),
            db.func.date(OrdenDetalle.fecha_listo) == fecha,
        )

    if estacion_filter:
        q = q.filter(Estacion.nombre == estacion_filter.nombre)

    completados = q.order_by(OrdenDetalle.fecha_listo.desc()).all()

    # Compute per-item prep times
    tiempos = []
    for d in completados:
        if d.orden and d.orden.tiempo_registro and d.fecha_listo:
            diff = (d.fecha_listo - d.orden.tiempo_registro).total_seconds() / 60.0
            if 0 < diff < 240:
                tiempos.append(diff)

    # KPI metrics
    total_items = len(completados)
    ordenes_unicas = len(set(d.orden_id for d in completados))
    avg_min = round(sum(tiempos) / len(tiempos), 1) if tiempos else 0
    fastest = round(min(tiempos), 1) if tiempos else 0
    slowest = round(max(tiempos), 1) if tiempos else 0

    # Per-station breakdown
    station_stats = {}
    for d in completados:
        est_name = d.producto.estacion.nombre if d.producto.estacion else 'Sin estación'
        if est_name not in station_stats:
            station_stats[est_name] = {'items': 0, 'tiempos': []}
        station_stats[est_name]['items'] += 1
        if d.orden and d.orden.tiempo_registro and d.fecha_listo:
            diff = (d.fecha_listo - d.orden.tiempo_registro).total_seconds() / 60.0
            if 0 < diff < 240:
                station_stats[est_name]['tiempos'].append(diff)

    for name, stats in station_stats.items():
        stats['avg'] = round(sum(stats['tiempos']) / len(stats['tiempos']), 1) if stats['tiempos'] else 0

    # Group by order for the table
    ordenes_dict = {}
    for d in completados:
        if d.orden_id not in ordenes_dict:
            ordenes_dict[d.orden_id] = {
                'orden': d.orden,
                'detalles': [],
                'prep_min': None,
            }
        ordenes_dict[d.orden_id]['detalles'].append(d)

    # Calculate per-order max prep time (slowest item = order completion time)
    for oid, data in ordenes_dict.items():
        item_times = []
        for d in data['detalles']:
            if d.orden.tiempo_registro and d.fecha_listo:
                diff = (d.fecha_listo - d.orden.tiempo_registro).total_seconds() / 60.0
                if 0 < diff < 240:
                    item_times.append(diff)
        data['prep_min'] = round(max(item_times), 1) if item_times else None

    ordenes_list = sorted(ordenes_dict.values(), key=lambda x: x['orden'].tiempo_registro, reverse=True)

    return render_template('cocina/historial_kds.html',
                           fecha=fecha,
                           estacion_slug=estacion_slug,
                           estaciones=[{'nombre': e.nombre, 'slug': _slugify(e.nombre)} for e in estaciones],
                           completados=completados,
                           ordenes_list=ordenes_list,
                           station_stats=station_stats,
                           kpi={
                               'total_items': total_items,
                               'ordenes': ordenes_unicas,
                               'avg_min': avg_min,
                               'fastest': fastest,
                               'slowest': slowest,
                           })
