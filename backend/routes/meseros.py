import logging
import json
from decimal import Decimal
from flask import Blueprint, render_template, session, redirect, url_for, flash, request, jsonify, g, current_app, abort
from backend.models.models import (
    Mesa, Orden, Producto, OrdenDetalle, Usuario, Pago, IVA_RATE,
    Cliente, MovimientoInventario, OrdenEstado,
)
from backend.extensions import db, socketio
from backend.services.tiempo import hoy_local, rango_utc, a_local
from backend.services.cobro import cerrar_orden_pagada
from backend.services.pagos import metodos_pago_detalle, metodos_pago_habilitados
from backend.utils import (login_required, verificar_propiedad_orden, filtrar_por_sucursal,
                           verificar_stock_disponible, actualizar_estado_mesa,
                           no_es_borrador, limpiar_borradores)
from backend.services.sanitizer import sanitizar_texto
from collections import defaultdict
from sqlalchemy.orm import joinedload
from sqlalchemy import func
from datetime import datetime, date, timezone

logger = logging.getLogger(__name__)

meseros_bp = Blueprint('meseros', __name__, url_prefix='/meseros')

from backend.models.models import ESTADOS_MODIFICABLES  # noqa: E402  (re-export)


def _revertir_inventario_orden(orden, usuario_id):
    """Reverse inventory deductions for a cancelled order that already had inventory deducted.

    Bloquea cada fila de Ingrediente (FOR UPDATE) antes de sumar, en el mismo
    orden ascendente por id que descontar_inventario_por_orden, para evitar
    lost-updates y deadlocks concurrentes.
    """
    from backend.models.models import Ingrediente, _cantidades_por_ingrediente
    requerido = _cantidades_por_ingrediente(orden)
    for ingrediente_id in sorted(requerido):
        cantidad_total = requerido[ingrediente_id]
        ingrediente = db.session.get(Ingrediente, ingrediente_id, with_for_update=True)
        ingrediente.stock_actual += cantidad_total
        mov = MovimientoInventario(
            ingrediente_id=ingrediente_id,
            tipo='ajuste',
            cantidad=cantidad_total,
            orden_id=orden.id,
            usuario_id=usuario_id,
            motivo=f'Reversión cancelación orden #{orden.id}',
        )
        db.session.add(mov)


# =====================================================================
# Dashboard
# =====================================================================
@meseros_bp.route('/')
@login_required(roles=['mesero', 'admin', 'superadmin'])
def view_meseros():
    is_admin = session.get('rol') in ('admin', 'superadmin')
    user_id = session.get('user_id')
    # Barrido de borradores abandonados (ver utils.limpiar_borradores)
    if not is_admin:
        limpiar_borradores(user_id)
    query = Orden.query.options(
        joinedload(Orden.mesa),
        joinedload(Orden.detalles).joinedload(OrdenDetalle.producto),
        joinedload(Orden.mesero),
    ).filter(
        Orden.estado.notin_([OrdenEstado.PAGADA, OrdenEstado.FINALIZADA, OrdenEstado.CANCELADA]),
        no_es_borrador(),
    )
    if not is_admin:
        query = query.filter(Orden.mesero_id == user_id)
    query = filtrar_por_sucursal(query, Orden)
    ordenes_mesero = query.order_by(Orden.tiempo_registro.desc()).all()

    # Ensure totals are calculated for all orders (fixes $0.00 display)
    dirty = False
    for o in ordenes_mesero:
        if o.total is None and o.detalles:
            o.calcular_totales()
            dirty = True
    if dirty:
        db.session.commit()

    # Load paid orders from today for the "Pagadas" pill
    hoy = hoy_local()
    desde, hasta = rango_utc(hoy)
    q_pagadas = Orden.query.options(
        joinedload(Orden.mesa),
        joinedload(Orden.detalles).joinedload(OrdenDetalle.producto),
        joinedload(Orden.mesero),
    ).filter(
        Orden.estado.in_([OrdenEstado.PAGADA, OrdenEstado.FINALIZADA]),
        db.or_(
            db.and_(Orden.fecha_pago >= desde, Orden.fecha_pago < hasta),
            db.and_(Orden.tiempo_registro >= desde, Orden.tiempo_registro < hasta),
        ),
    )
    if not is_admin:
        q_pagadas = q_pagadas.filter(Orden.mesero_id == user_id)
    q_pagadas = filtrar_por_sucursal(q_pagadas, Orden)
    ordenes_pagadas = q_pagadas.order_by(Orden.fecha_pago.desc()).all()

    template = 'admin/ordenes_activas.html' if is_admin else 'meseros.html'
    return render_template(template, ordenes_mesero=ordenes_mesero,
                           ordenes_pagadas=ordenes_pagadas, now_utc=datetime.now(timezone.utc).replace(tzinfo=None))


# =====================================================================
# Mapa visual de mesas (Sprint 4 — 5.1)
# =====================================================================
@meseros_bp.route('/mapa')
@login_required(roles=['mesero', 'admin', 'superadmin'])
def mapa_mesas():
    mesas = filtrar_por_sucursal(Mesa.query, Mesa).all()
    zonas = sorted(set(m.zona for m in mesas if m.zona))
    is_admin = session.get('rol') in ('admin', 'superadmin')
    template = 'admin/mapa_mesas.html' if is_admin else 'meseros/mapa_mesas.html'
    return render_template(template, zonas=zonas, is_admin=is_admin)


# =====================================================================
# Historial del día (Sprint 9 — moved from cocina, accessible to meseros)
# =====================================================================
@meseros_bp.route('/historial')
@login_required(roles=['mesero', 'admin', 'superadmin'])
def historial_dia():
    hoy = hoy_local()
    desde, hasta = rango_utc(hoy)
    query = Orden.query.options(
        joinedload(Orden.mesa),
        joinedload(Orden.detalles).joinedload(OrdenDetalle.producto),
    ).filter(
        Orden.estado.in_([OrdenEstado.FINALIZADA, OrdenEstado.PAGADA]),
        db.or_(
            db.and_(Orden.fecha_pago >= desde, Orden.fecha_pago < hasta),
            db.and_(Orden.tiempo_registro >= desde, Orden.tiempo_registro < hasta),
        ),
    )
    query = filtrar_por_sucursal(query, Orden)
    ordenes = query.order_by(Orden.fecha_pago.desc().nullslast()).all()
    is_admin = session.get('rol') in ('admin', 'superadmin')
    template = 'admin/historial_dia.html' if is_admin else 'historial_dia.html'
    return render_template(template, ordenes=ordenes)


# =====================================================================
# Historial CSV export (Sprint 9 — 9.7)
# =====================================================================
@meseros_bp.route('/historial/csv')
@login_required(roles=['mesero', 'admin', 'superadmin'])
def historial_csv():
    import csv
    import io
    from flask import Response

    hoy = hoy_local()
    desde, hasta = rango_utc(hoy)
    query = Orden.query.options(
        joinedload(Orden.mesa),
        joinedload(Orden.detalles).joinedload(OrdenDetalle.producto),
    ).filter(
        Orden.estado.in_([OrdenEstado.FINALIZADA, OrdenEstado.PAGADA]),
        db.or_(
            db.and_(Orden.fecha_pago >= desde, Orden.fecha_pago < hasta),
            db.and_(Orden.tiempo_registro >= desde, Orden.tiempo_registro < hasta),
        ),
    )
    query = filtrar_por_sucursal(query, Orden)
    ordenes = query.order_by(Orden.fecha_pago.desc().nullslast()).all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Orden', 'Hora', 'Mesa', 'Estado', 'Productos', 'Total'])
    for o in ordenes:
        mesa = f'Mesa {o.mesa.numero}' if o.mesa else 'Para llevar'
        productos = '; '.join(f'{d.producto.nombre} x{d.cantidad}' for d in o.detalles)
        total = float(o.total or 0)
        # Folio del día (lo que ve el cliente), no el id interno; y la hora
        # convertida a la zona del negocio (la columna se guarda en UTC).
        writer.writerow([f'#{o.numero}', a_local(o.tiempo_registro).strftime('%H:%M'),
                         mesa, o.estado, productos, f'${total:.2f}'])

    output.seek(0)
    return Response(
        output.getvalue(),
        mimetype='text/csv',
        headers={'Content-Disposition': f'attachment; filename=historial_{hoy.isoformat()}.csv'},
    )


# =====================================================================
# Crear órdenes
# =====================================================================
@meseros_bp.route('/crear_orden_para_llevar', methods=['POST'])
@login_required(roles='mesero')
def crear_orden_para_llevar():
    """Crea (o reutiliza) la orden para llevar del mesero.

    POST y no GET: como enlace, bastaba con que el navegador precargara la liga para
    generar una orden fantasma sin que nadie la pidiera.
    """
    user_id = session.get('user_id')

    # Si ya dejó un borrador vacío para llevar, se reutiliza en vez de crear otro.
    borrador = Orden.query.filter(
        Orden.mesero_id == user_id,
        Orden.es_para_llevar.is_(True),
        Orden.estado == OrdenEstado.PENDIENTE,
        ~Orden.detalles.any(),
    ).order_by(Orden.id.desc()).first()
    if borrador:
        return redirect(url_for('meseros.detalle_orden', orden_id=borrador.id))

    nueva_orden = Orden(
        mesero_id=user_id, es_para_llevar=True, estado=OrdenEstado.PENDIENTE,
        sucursal_id=g.sucursal_id,
    )
    db.session.add(nueva_orden)
    db.session.commit()
    logger.info('Orden para llevar creada: id=%s', nueva_orden.id)
    return redirect(url_for('meseros.detalle_orden', orden_id=nueva_orden.id))


@meseros_bp.route('/seleccionar_mesa', methods=['GET', 'POST'])
@login_required(roles='mesero')
def seleccionar_mesa():
    if request.method == 'POST':
        mesa_id = request.form.get('mesa_id')
        if mesa_id:
            try:
                mesa_id_int = int(mesa_id)
            except (ValueError, TypeError):
                flash('Mesa inválida.', 'danger')
                return redirect(url_for('meseros.seleccionar_mesa'))
            # Lock the Mesa row so concurrent creates on the same table are
            # serialized — the second request blocks until the first commits.
            mesa = db.session.get(Mesa, mesa_id_int, with_for_update=True)
            if not mesa:
                db.session.rollback()
                flash('Mesa no encontrada.', 'danger')
                return redirect(url_for('meseros.seleccionar_mesa'))

            # Mesas compartidas: una mesa puede tener varias cuentas abiertas.
            # Si ya hay cuentas y el mesero no pidió explícitamente una nueva,
            # se le muestra el selector de cuentas de esa mesa.
            forzar_nueva = request.form.get('forzar_nueva') == '1'
            # Cuentas que el mesero debe ver antes de abrir otra. Se ignora sólo su
            # PROPIO borrador vacío (ese se reutiliza más abajo); el borrador de otro
            # mesero sí cuenta, para que no dos levanten la misma mesa sin enterarse.
            mi_borrador_vacio = db.and_(
                Orden.mesero_id == session.get('user_id'),
                Orden.estado == OrdenEstado.PENDIENTE,
                ~Orden.detalles.any(),
            )
            cuentas_activas = Orden.query.filter(
                Orden.mesa_id == mesa_id_int,
                Orden.estado.notin_([OrdenEstado.PAGADA, OrdenEstado.FINALIZADA, OrdenEstado.CANCELADA]),
                db.not_(mi_borrador_vacio),
            ).count()
            if cuentas_activas and not forzar_nueva:
                db.session.rollback()  # release lock, nothing created
                return redirect(url_for('meseros.cuentas_mesa', mesa_id=mesa_id_int))

            alias = sanitizar_texto(request.form.get('alias') or '', 50) or None
            try:
                num_personas = int(request.form.get('num_personas') or 0) or None
            except (ValueError, TypeError):
                num_personas = None
            # Es opcional: algo fuera de rango (−4, 0, 5000) se toma como "no se dijo"
            # en vez de guardarse y pintarse en el mapa de mesas
            if num_personas is not None and not 1 <= num_personas <= 99:
                num_personas = None

            # Si el mesero ya dejó un borrador vacío en esta mesa, se reutiliza en vez
            # de amontonar cuentas fantasma cada vez que entra y se regresa.
            nueva_orden = Orden.query.filter(
                Orden.mesa_id == mesa_id_int,
                Orden.mesero_id == session.get('user_id'),
                Orden.estado == OrdenEstado.PENDIENTE,
                ~Orden.detalles.any(),
            ).order_by(Orden.id.desc()).first()

            if nueva_orden:
                db.session.rollback()  # suelta el lock: no hay nada que crear
                if alias:
                    nueva_orden.alias = alias
                if num_personas:
                    nueva_orden.num_personas = num_personas
                db.session.commit()
            else:
                nueva_orden = Orden(
                    mesero_id=session.get('user_id'), mesa_id=mesa_id_int,
                    es_para_llevar=False, estado=OrdenEstado.PENDIENTE,
                    sucursal_id=g.sucursal_id,
                    alias=alias, num_personas=num_personas,
                )
                db.session.add(nueva_orden)
                db.session.commit()
            # La mesa se marca ocupada al agregar el primer producto, no antes: una
            # cuenta vacía no debe bloquear la mesa si el mesero se arrepiente.
            return redirect(url_for('meseros.detalle_orden', orden_id=nueva_orden.id))
        flash('Debes seleccionar una mesa.', 'warning')
        return redirect(url_for('meseros.seleccionar_mesa'))

    mesas = filtrar_por_sucursal(Mesa.query, Mesa).order_by(Mesa.numero).all()

    # Mesas compartidas: cada mesa puede tener VARIAS cuentas activas.
    # `no_es_borrador` excluye las cuentas vacías: una que el mesero abrió y
    # abandonó no debe pintar la mesa como ocupada (la mesa sólo se ocupa con el
    # primer producto, así que si no, el mosaico y el estado real no coinciden).
    active_orders = Orden.query.filter(
        Orden.estado.notin_([OrdenEstado.PAGADA, OrdenEstado.FINALIZADA, OrdenEstado.CANCELADA]),
        no_es_borrador(),
    ).order_by(Orden.tiempo_registro).all()
    mesa_order_map = {}
    for o in active_orders:
        if o.mesa_id:
            mesa_order_map.setdefault(o.mesa_id, []).append(o)

    # Cuánta gente hay sentada por mesa, sumando todas sus cuentas: una mesa de
    # 12 con dos clientes no está "llena", y el mesero necesita verlo para
    # sentar a alguien más ahí.
    mesa_personas = {
        mesa_id: sum(o.num_personas or 0 for o in ordenes)
        for mesa_id, ordenes in mesa_order_map.items()
    }

    zonas = sorted(set(m.zona for m in mesas if m.zona))
    return render_template('seleccionar_mesa.html', mesas=mesas,
                           mesa_personas=mesa_personas,
                           mesa_order_map=mesa_order_map, zonas=zonas)


# =====================================================================
# Mesas compartidas — selector de cuentas por mesa
# =====================================================================
@meseros_bp.route('/mesa/<int:mesa_id>/cuentas')
@login_required(roles=['mesero', 'admin', 'superadmin'])
def cuentas_mesa(mesa_id):
    """Lista las cuentas activas de una mesa y permite abrir una nueva.

    Una mesa grande puede compartirse entre varios grupos: cada grupo lleva su
    propia cuenta (Orden) que se pide, cobra y cancela por separado. La mesa se
    libera sola cuando la última cuenta se cierra (actualizar_estado_mesa).
    """
    mesa = db.get_or_404(Mesa, mesa_id)
    cuentas = Orden.query.options(
        joinedload(Orden.detalles).joinedload(OrdenDetalle.producto),
        joinedload(Orden.mesero),
    ).filter(
        Orden.mesa_id == mesa_id,
        Orden.estado.notin_([OrdenEstado.PAGADA, OrdenEstado.FINALIZADA, OrdenEstado.CANCELADA]),
    ).order_by(Orden.tiempo_registro).all()

    if not cuentas:
        # Sin cuentas activas — nada que elegir, directo al flujo normal
        return redirect(url_for('meseros.seleccionar_mesa'))

    user_id = session.get('user_id')
    is_admin = session.get('rol') in ('admin', 'superadmin')
    return render_template('cuentas_mesa.html', mesa=mesa, cuentas=cuentas,
                           user_id=user_id, is_admin=is_admin)


# =====================================================================
# Detalle / agregar productos
# =====================================================================
@meseros_bp.route('/ordenes/<int:orden_id>/detalle_orden', methods=['GET'])
@login_required(roles='mesero')
@verificar_propiedad_orden
def detalle_orden(orden_id):
    orden = db.get_or_404(Orden, orden_id, options=[
        joinedload(Orden.mesa),
        joinedload(Orden.detalles).joinedload(OrdenDetalle.producto),
    ])

    if orden.estado not in ESTADOS_MODIFICABLES:
        flash(f'Orden #{orden.numero} no puede modificarse ({orden.estado}).', 'warning')
        return redirect(url_for('meseros.view_meseros'))

    productos = Producto.query.options(
        joinedload(Producto.categoria),
    # Orden del menú (el de la plantilla o el de alta), no alfabético: "1/2 kg"
    # caía antes que "1/4" y "3/4" después de "1 kg".
    ).order_by(Producto.categoria_id, Producto.id).all()

    productos_por_categoria = defaultdict(list)
    for p in productos:
        productos_por_categoria[p.categoria.nombre].append(p.to_dict())

    # M9 — Popular products: top 8 most ordered products overall
    popular_ids = (
        db.session.query(OrdenDetalle.producto_id, func.sum(OrdenDetalle.cantidad).label('total'))
        .group_by(OrdenDetalle.producto_id)
        .order_by(func.sum(OrdenDetalle.cantidad).desc())
        .limit(8)
        .all()
    )
    popular_product_ids = [pid for pid, _ in popular_ids]

    return render_template('detalle_orden.html', orden=orden,
                           productos_por_categoria=productos_por_categoria,
                           popular_product_ids=popular_product_ids,
                           user_id=session.get('user_id', 0))


@meseros_bp.route('/ordenes/<int:orden_id>/agregar_productos', methods=['POST'])
@login_required(roles='mesero')
@verificar_propiedad_orden
def agregar_productos_a_orden(orden_id):
    orden = db.get_or_404(Orden, orden_id)
    if orden.estado not in ESTADOS_MODIFICABLES:
        flash(f'No se pueden agregar productos ({orden.estado}).', 'danger')
        return redirect(url_for('meseros.detalle_orden', orden_id=orden_id))

    data = request.form.get('productos_json')
    if not data:
        flash('No se recibieron productos.', 'warning')
        return redirect(url_for('meseros.detalle_orden', orden_id=orden_id))

    orden_ya_enviada = orden.estado != OrdenEstado.PENDIENTE
    try:
        productos_sel = json.loads(data)
        if not productos_sel:
            flash('No se seleccionaron productos.', 'info')
            return redirect(url_for('meseros.detalle_orden', orden_id=orden_id))

        nuevos = []
        stock_warnings = []
        for p_data in productos_sel:
            prod = db.session.get(Producto, p_data['id'])
            if not prod:
                continue
            from backend.routes.orders import CANTIDAD_MAXIMA
            from backend.services.validacion import leer_entero
            cantidad = leer_entero(p_data.get('cantidad', 1), 1, CANTIDAD_MAXIMA)
            if cantidad is None:
                flash(f'Cantidad inválida para {prod.nombre}: de 1 a {CANTIDAD_MAXIMA}.', 'danger')
                continue
            notas = sanitizar_texto(p_data.get('notas') or '', 300)

            # Validación de stock (Sprint 2 — 3.2)
            if current_app.config.get('INVENTARIO_VALIDAR_STOCK'):
                disponible, faltantes, warns = verificar_stock_disponible(prod.id, cantidad)
                if not disponible:
                    nombres = ', '.join(f['ingrediente'] for f in faltantes)
                    flash(f'Stock insuficiente para {prod.nombre}: faltan {nombres}', 'danger')
                    continue
                stock_warnings.extend(warns)

            # Merge: only merge with items that share the same notes
            existentes = OrdenDetalle.query.filter_by(
                orden_id=orden_id, producto_id=prod.id, estado=OrdenEstado.PENDIENTE,
            ).all()
            merged = False
            for existente in existentes:
                if (existente.notas or '').strip() == notas:
                    existente.cantidad += cantidad
                    merged = True
                    break
            if not merged:
                d = OrdenDetalle(
                    orden_id=orden_id, producto_id=prod.id,
                    cantidad=cantidad, notas=notas or None,
                    precio_unitario=prod.precio, estado=OrdenEstado.PENDIENTE,
                )
                db.session.add(d)
                nuevos.append(d)

        db.session.commit()

        # Si la orden ya había salido de la cocina (todo listo) y ahora tiene
        # items sin preparar, tiene que volver: el KDS sólo muestra órdenes en
        # enviado/en_preparacion, así que sin esto el producto nuevo no le
        # llegaba a nadie y la cuenta se podía cobrar con comida sin hacer.
        if orden.estado == OrdenEstado.LISTA_PARA_ENTREGAR and any(
                d.estado == OrdenEstado.PENDIENTE for d in orden.detalles):
            orden.estado = OrdenEstado.EN_PREPARACION
            db.session.commit()
            logger.info('Orden %s regresa a en_preparacion: se agregaron productos', orden_id)

        # Con el primer producto deja de ser borrador: folio del día y mesa ocupada
        from backend.services.folio import asignar_folio
        asignar_folio(orden)
        db.session.commit()
        if orden.mesa_id:
            actualizar_estado_mesa(orden.mesa_id)
            db.session.commit()
        if orden_ya_enviada and nuevos:
            socketio.emit('nueva_orden_cocina', {
                'orden_id': orden.id,
                'mensaje': f'Nuevos productos en orden #{orden.numero}.',
            })
        # Avisar warnings de stock bajo
        for w in stock_warnings:
            flash(f'⚠️ Stock bajo: {w["ingrediente"]} ({w["stock_actual"]} {w["unidad"]})', 'warning')
        flash('Productos agregados.', 'success')
    except Exception as e:
        db.session.rollback()
        logger.exception('Error agregar productos orden %s', orden_id)
        flash(f'Error: {e}', 'danger')

    return redirect(url_for('meseros.detalle_orden', orden_id=orden_id))


# =====================================================================
# Pago — full-page payment view (Sprint 9 — 9.6)
# =====================================================================
@meseros_bp.route('/ordenes/<int:orden_id>/pago_view', methods=['GET'])
@login_required(roles='mesero')
@verificar_propiedad_orden
def pago_view(orden_id):
    orden = db.get_or_404(Orden, orden_id, options=[
        joinedload(Orden.mesa),
        joinedload(Orden.detalles).joinedload(OrdenDetalle.producto),
    ])
    from backend.services.banco import datos_bancarios
    return render_template('pago.html', orden=orden,
                           metodos_pago=metodos_pago_detalle(),
                           banco=datos_bancarios())


# =====================================================================
# Enviar / entregar / cancelar
# =====================================================================
@meseros_bp.route('/ordenes/<int:orden_id>/enviar_a_cocina', methods=['POST'])
@login_required(roles='mesero')
@verificar_propiedad_orden
def enviar_orden_a_cocina(orden_id):
    orden = db.get_or_404(Orden, orden_id)
    if not orden.detalles:
        flash('Orden vacía.', 'warning')
        return redirect(url_for('meseros.detalle_orden', orden_id=orden_id))
    if orden.estado != OrdenEstado.PENDIENTE:
        flash(f'Orden ya enviada ({orden.estado}).', 'warning')
    else:
        orden.estado = OrdenEstado.ENVIADO
        db.session.commit()
        socketio.emit('nueva_orden_cocina', {'orden_id': orden.id, 'mensaje': f'Orden #{orden.numero} para cocina.'})
        # Auto-imprimir comanda si está configurado (Sprint 3 — 3.1)
        from backend.services.printer import AUTO_PRINT_COMANDA, imprimir_comanda
        if AUTO_PRINT_COMANDA:
            imprimir_comanda(orden)
        flash('Orden enviada a cocina.', 'success')
    return redirect(url_for('meseros.view_meseros'))


@meseros_bp.route('/entregar_item/<int:orden_id>/<int:detalle_id>', methods=['POST'])
@login_required(roles=['mesero', 'admin', 'superadmin'])
@verificar_propiedad_orden
def entregar_item(orden_id, detalle_id):
    detalle = OrdenDetalle.query.filter_by(id=detalle_id, orden_id=orden_id).first_or_404()
    if detalle.estado == 'entregado':
        return jsonify(success=False, message="Ya entregado."), 400
    if detalle.estado != OrdenEstado.LISTO:
        return jsonify(success=False, message="No está listo."), 400

    detalle.estado = 'entregado'
    orden = db.get_or_404(Orden, orden_id, options=[joinedload(Orden.detalles)])

    if all(d.estado == 'entregado' for d in orden.detalles):
        if orden.estado not in [OrdenEstado.PAGADA, OrdenEstado.FINALIZADA, OrdenEstado.CANCELADA, OrdenEstado.COMPLETADA]:
            orden.estado = OrdenEstado.COMPLETADA
            socketio.emit('orden_actualizada_para_cobro', {
                'orden_id': orden.id, 'estado_orden': 'completada',
                'mensaje': f'Orden #{orden.numero} lista para cobro.',
            })
    db.session.commit()
    return jsonify(success=True, message="Entregado.")



# Los mismos valores que el <select> del modal de cancelación (detalle_orden.html)
MOTIVOS_CANCELACION = {
    'cliente_solicito': 'El cliente lo solicitó',
    'error_orden': 'Error al capturar la orden',
    'producto_agotado': 'Producto agotado',
    'tiempo_espera': 'Exceso de tiempo de espera',
    'otro': 'Otro',
}

@meseros_bp.route('/ordenes/<int:orden_id>/cancelar', methods=['POST'])
@login_required(roles=['mesero', 'admin', 'superadmin'])
@verificar_propiedad_orden
def cancelar_orden(orden_id):
    # Lock the order row so a concurrent payment (registrar_pago,
    # which also lock via with_for_update) can't be silently overwritten by this
    # cancellation — whoever gets the lock first wins, and we re-check state
    # against the just-locked row instead of a stale pre-lock read.
    # NOTE: no joinedload here — FOR UPDATE + OUTER JOIN is rejected by
    # PostgreSQL ("FOR UPDATE cannot be applied to the nullable side of an
    # outer join"); relationships are lazy-loaded after the lock instead.
    orden = db.session.get(Orden, orden_id, with_for_update=True)
    if not orden:
        abort(404)
    orden.detalles  # trigger lazy load (post-lock, consistent snapshot)
    orden.pagos

    if orden.estado in [OrdenEstado.PAGADA, OrdenEstado.FINALIZADA, OrdenEstado.CANCELADA]:
        db.session.rollback()  # release lock, no changes made
        flash('No se puede cancelar.', 'warning')
        return redirect(url_for('meseros.view_meseros'))

    # El modal pedía el motivo pero aquí no se leía: la auditoría sólo decía "cancelada"
    # y la dueña no podía revisar por qué se cancelan cuentas (cancelar después de
    # cobrar en efectivo es justo lo que conviene poder rastrear)
    motivo = MOTIVOS_CANCELACION.get(request.form.get('motivo_cancelacion', ''))
    if motivo == 'Otro':
        detalle = sanitizar_texto(request.form.get('motivo_otro', ''), 200)
        motivo = f'Otro: {detalle}' if detalle else None
    if not motivo:
        db.session.rollback()
        flash('Elige el motivo de la cancelación (si es "Otro", escríbelo).', 'warning')
        return redirect(url_for('meseros.detalle_orden', orden_id=orden_id))

    # Reverse inventory only if it was actually deducted. Inventory is deducted
    # exclusively when the order closes fully paid (saldo <= 0), so a partial
    # payment alone means nothing to reverse — checking for the salida_venta
    # movement is the ground truth and avoids inflating stock with phantom stock.
    hubo_descuento = MovimientoInventario.query.filter_by(
        orden_id=orden.id, tipo='salida_venta',
    ).count() > 0
    if hubo_descuento:
        try:
            _revertir_inventario_orden(orden, session.get('user_id'))
        except Exception:
            logger.exception('Error revirtiendo inventario orden %s', orden_id)

    orden.estado = OrdenEstado.CANCELADA
    from backend.services.audit import registrar_auditoria
    registrar_auditoria('cancelar', 'Orden', orden_id,
                        f'Orden #{orden.numero} cancelada. Motivo: {motivo}')
    db.session.commit()
    # Liberar mesa si no quedan órdenes activas (Sprint 2 — 3.3)
    actualizar_estado_mesa(orden.mesa_id)
    db.session.commit()
    logger.info('Orden %s cancelada por usuario %s', orden_id, session.get('user_id'))
    flash(f'Orden #{orden.numero} cancelada.', 'info')
    return redirect(url_for('meseros.view_meseros'))


# =====================================================================
# ITEM 12: Descuento con autorización
# =====================================================================
@meseros_bp.route('/ordenes/<int:orden_id>/descuento', methods=['POST'])
@login_required(roles=['mesero', 'admin', 'superadmin'])
@verificar_propiedad_orden
def aplicar_descuento(orden_id):
    """Aplica descuento; requiere credenciales de admin/superadmin para autorizar."""
    orden = db.get_or_404(Orden, orden_id)
    data = request.get_json()
    if not data:
        return jsonify(success=False, message="Datos faltantes."), 400

    # Validar autorización
    auth_email = data.get('auth_email')
    auth_password = data.get('auth_password')
    from backend.services.acceso import buscar_para_login
    autorizador = buscar_para_login(auth_email)  # usuario corto o correo

    if not autorizador or not autorizador.check_password(auth_password):
        return jsonify(success=False, message="Credenciales de autorización inválidas."), 403
    if autorizador.rol not in ('admin', 'superadmin'):
        return jsonify(success=False, message="Solo admin/superadmin puede autorizar descuentos."), 403

    tipo = data.get('tipo', 'porcentaje')  # porcentaje | monto
    valor = Decimal(str(data.get('valor', 0)))
    motivo = sanitizar_texto(data.get('motivo', ''), 200)

    if tipo == 'porcentaje':
        if valor < 0 or valor > 100:
            return jsonify(success=False, message="Porcentaje debe ser 0-100."), 400
        orden.descuento_pct = valor
        orden.descuento_monto = Decimal('0')
    else:
        if valor < 0:
            return jsonify(success=False, message="Monto inválido."), 400
        orden.descuento_monto = valor
        orden.descuento_pct = Decimal('0')

    orden.descuento_motivo = motivo
    orden.descuento_autorizado_por = autorizador.id
    orden.calcular_totales()

    from backend.services.audit import registrar_auditoria
    registrar_auditoria('descuento', 'Orden', orden_id,
                        f'Descuento {tipo}={float(valor)} autorizado por={autorizador.id}. Motivo: {motivo}')
    db.session.commit()

    logger.info('Descuento aplicado orden=%s tipo=%s valor=%s por=%s',
                orden_id, tipo, valor, autorizador.id)
    return jsonify(success=True, message="Descuento aplicado.",
                   subtotal=float(orden.subtotal), iva=float(orden.iva), total=float(orden.total))


# =====================================================================
# Cobro info — ahora con IVA (ITEM 8)
# =====================================================================
@meseros_bp.route('/ordenes/<int:orden_id>/cobrar_info', methods=['GET'])
@login_required(roles='mesero')
@verificar_propiedad_orden
def get_cobrar_orden_info(orden_id):
    orden = db.get_or_404(Orden, orden_id, options=[
        joinedload(Orden.mesa),
        joinedload(Orden.detalles).joinedload(OrdenDetalle.producto),
        joinedload(Orden.pagos),
    ])

    # Recalcular siempre al pedir info
    orden.calcular_totales()
    db.session.commit()

    detalles_data = []
    for d in orden.detalles:
        precio = float(d.precio_unitario) if d.precio_unitario is not None else float(d.producto.precio)
        detalles_data.append({
            "id": d.id, "nombre": d.producto.nombre, "cantidad": d.cantidad,
            "precio": precio, "subtotal": precio * d.cantidad, "estado": d.estado,
        })

    pagos_data = [{
        'id': p.id, 'metodo': p.metodo, 'monto': float(p.monto),
        'referencia': p.referencia,
    } for p in orden.pagos]

    from backend.services.negocio import datos_negocio

    return jsonify({
        "orden_id": orden.id,
        # Lo que se le dice al cliente es el folio del día, no el id interno.
        "orden_numero": orden.numero,
        # El ticket traía "CASA LEONES" escrito a mano: sale del negocio real.
        "negocio": datos_negocio(),
        "mesa_numero": orden.mesa.numero if orden.mesa else None,
        "alias": orden.alias,
        "es_para_llevar": orden.es_para_llevar,
        "estado_orden": orden.estado,
        "detalles": detalles_data,
        "subtotal": float(orden.subtotal or 0),
        "descuento_pct": float(orden.descuento_pct or 0),
        "descuento_monto": float(orden.descuento_monto or 0),
        "iva_rate": float(IVA_RATE * 100),
        "iva": float(orden.iva or 0),
        "total": float(orden.total or 0),
        "pagos": pagos_data,
        "total_pagado": float(orden.total_pagado()),
        "saldo_pendiente": float(max(orden.saldo_pendiente(), Decimal('0'))),
        "cambio": float(orden.cambio or 0),
    })


# =====================================================================
# ITEM 9 + 13: Registrar pago (multi-método / split)
# =====================================================================
@meseros_bp.route('/ordenes/<int:orden_id>/pago', methods=['POST'])
@login_required(roles='mesero')
@verificar_propiedad_orden
def registrar_pago(orden_id):
    """Registra un pago parcial o total. Se pueden hacer múltiples."""
    # Lock the order row to prevent concurrent double-payment race condition
    orden = db.session.get(Orden, orden_id, with_for_update=True)
    if not orden:
        return jsonify(success=False, message="Orden no encontrada."), 404
    # Eager-load relationships after locking
    db.session.refresh(orden)
    orden.detalles  # trigger lazy load
    orden.pagos     # trigger lazy load

    if orden.estado not in ('completada', 'lista_para_entregar'):
        return jsonify(success=False, message=f"Orden no lista para cobro ({orden.estado})."), 400

    data = request.get_json(silent=True)
    if not data:
        return jsonify(success=False, message="Datos faltantes."), 400
    metodo = data.get('metodo', 'efectivo')
    if metodo not in metodos_pago_habilitados():
        return jsonify(success=False, message="Método de pago no habilitado."), 400

    try:
        monto = Decimal(str(data.get('monto', 0)))
    except Exception:
        return jsonify(success=False, message="Monto inválido."), 400

    if monto <= 0:
        return jsonify(success=False, message="Monto debe ser mayor a 0."), 400

    referencia = sanitizar_texto(data.get('referencia', '') or '', 100)
    # Una transferencia sin referencia no se puede buscar en el estado de cuenta,
    # así que no habría forma de confirmar que el dinero llegó.
    if metodo == 'transferencia' and not referencia:
        return jsonify(success=False,
                       message="Captura la referencia de la transferencia "
                               "(folio o nombre de quien transfiere)."), 400

    # Propina (Sprint 6 — 3.6)
    try:
        propina = Decimal(str(data.get('propina', 0)))
    except Exception:
        propina = Decimal('0')
    if propina < 0:
        propina = Decimal('0')
    orden.propina = (orden.propina or Decimal('0')) + propina

    # Recalcular totales
    orden.calcular_totales()
    saldo_antes = orden.saldo_pendiente()

    # Tarjeta/transferencia: no existe "cambio" — un cargo mayor al saldo sería
    # un sobre-cobro real al cliente, se rechaza en vez de perderse en silencio.
    if metodo != 'efectivo' and monto > saldo_antes:
        return jsonify(success=False,
                       message=f"Monto excede el saldo pendiente (${float(saldo_antes):.2f}).",
                       saldo_pendiente=float(saldo_antes)), 400

    # Efectivo: `monto` es lo que entregó el cliente. A la cuenta solo se aplica
    # hasta el saldo (Pago.monto alimenta el corte de caja y debe cuadrar con la
    # venta); el excedente es cambio, descontando la propina que se queda.
    monto_aplicado = min(monto, saldo_antes) if metodo == 'efectivo' else monto
    cambio_pago = max(monto - saldo_antes - propina, Decimal('0')) if metodo == 'efectivo' else Decimal('0')

    # El efectivo se da por verificado (está en la mano); la transferencia queda
    # pendiente hasta que alguien la confirme en el banco.
    requiere_verificacion = metodo == 'transferencia'

    pago = Pago(
        metodo=metodo, monto=monto_aplicado, propina=propina,
        referencia=referencia, registrado_por=session.get('user_id'),
        verificado=not requiere_verificacion,
    )
    orden.pagos.append(pago)  # Use relationship so in-memory collection stays in sync
    db.session.flush()

    saldo = orden.saldo_pendiente()

    # Si ya se cubrió el total con pagos verificados, cerrar la orden
    if saldo <= 0:
        cerrar_orden_pagada(
            orden, orden.mesero_id or session.get('user_id'),
            cambio=cambio_pago,
            propina_efectivo=(propina if metodo == 'efectivo' else Decimal('0')),
        )

    # Auditoría (Sprint 6 — 3.5)
    from backend.services.audit import registrar_auditoria
    registrar_auditoria('pago', 'Orden', orden_id,
                        f'Pago ${float(monto):.2f} ({metodo}). Propina: ${float(propina):.2f}'
                        + (' — pendiente de verificar' if requiere_verificacion else ''))

    db.session.commit()

    if requiere_verificacion:
        # Avisar a quien verifica que hay una transferencia esperando
        socketio.emit('transferencia_por_verificar', {
            'pago_id': pago.id, 'orden_id': orden.id,
            'monto': float(monto_aplicado), 'referencia': referencia,
            'mensaje': f'Transferencia de ${float(monto_aplicado):.2f} por verificar (orden #{orden.numero}).',
        })

    # Liberar mesa si orden pagada (Sprint 2 — 3.3)
    if orden.estado == OrdenEstado.PAGADA:
        actualizar_estado_mesa(orden.mesa_id)
        db.session.commit()

    if requiere_verificacion:
        mensaje = ('Transferencia registrada. La cuenta se libera cuando se '
                   'confirme que el dinero llegó.')
    elif orden.estado == OrdenEstado.PAGADA:
        mensaje = 'Pago registrado. Orden pagada.'
    else:
        mensaje = 'Pago registrado.'

    return jsonify(
        success=True,
        message=mensaje,
        pago_id=pago.id,
        metodo=metodo,
        monto=float(monto),
        requiere_verificacion=requiere_verificacion,
        por_verificar=float(orden.total_por_verificar()),
        total_pagado=float(orden.total_pagado()),
        saldo_pendiente=float(max(orden.saldo_pendiente(), Decimal('0'))),
        cambio=float(orden.cambio or 0),
        orden_pagada=(orden.estado == OrdenEstado.PAGADA),
    )


# =====================================================================
# Impresión ESC/POS (Sprint 3 — 3.1)
# =====================================================================
@meseros_bp.route('/ordenes/<int:orden_id>/imprimir/comanda', methods=['POST'])
@login_required(roles=['mesero', 'admin', 'superadmin'])
@verificar_propiedad_orden
def imprimir_comanda_endpoint(orden_id):
    """Imprime comanda de cocina. Fallback: retorna texto para window.print()."""
    from backend.services.printer import imprimir_comanda, generar_texto_comanda, PRINTER_TYPE
    orden = db.get_or_404(Orden, orden_id, options=[
        joinedload(Orden.mesa),
        joinedload(Orden.mesero),
        joinedload(Orden.detalles).joinedload(OrdenDetalle.producto),
    ])

    if PRINTER_TYPE != 'none':
        ok = imprimir_comanda(orden)
        if ok:
            return jsonify(success=True, message='Comanda impresa.')
        return jsonify(success=False, message='Error al imprimir.', texto=generar_texto_comanda(orden))

    # Modo none: retornar texto para impresión del navegador
    return jsonify(success=True, fallback=True, texto=generar_texto_comanda(orden))


@meseros_bp.route('/ordenes/<int:orden_id>/imprimir/ticket', methods=['POST'])
@login_required(roles=['mesero', 'admin', 'superadmin'])
@verificar_propiedad_orden
def imprimir_ticket_endpoint(orden_id):
    """Imprime ticket de cuenta. Fallback: retorna texto para window.print()."""
    from backend.services.printer import imprimir_ticket_cuenta, generar_texto_ticket, PRINTER_TYPE
    orden = db.get_or_404(Orden, orden_id, options=[
        joinedload(Orden.mesa),
        joinedload(Orden.mesero),
        joinedload(Orden.detalles).joinedload(OrdenDetalle.producto),
        joinedload(Orden.pagos),
    ])

    if PRINTER_TYPE != 'none':
        ok = imprimir_ticket_cuenta(orden)
        if ok:
            return jsonify(success=True, message='Ticket impreso.')
        return jsonify(success=False, message='Error al imprimir.', texto=generar_texto_ticket(orden))

    return jsonify(success=True, fallback=True, texto=generar_texto_ticket(orden))
