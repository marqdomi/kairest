import logging
import json
from decimal import Decimal
from flask import Blueprint, render_template, session, redirect, url_for, flash, request, jsonify, g, current_app
from backend.models.models import (
    Mesa, Orden, Producto, OrdenDetalle, Sale, SaleItem, Usuario, Pago, IVA_RATE,
    descontar_inventario_por_orden, Cliente, MovimientoInventario,
)
from backend.extensions import db, socketio
from backend.utils import login_required, verificar_propiedad_orden, filtrar_por_sucursal, verificar_stock_disponible, actualizar_estado_mesa
from backend.services.sanitizer import sanitizar_texto
from collections import defaultdict
from sqlalchemy.orm import joinedload
from sqlalchemy import func
from datetime import datetime, date

logger = logging.getLogger(__name__)

meseros_bp = Blueprint('meseros', __name__, url_prefix='/meseros')

ESTADOS_MODIFICABLES = ['pendiente', 'enviado', 'en_preparacion', 'lista_para_entregar']


def _revertir_inventario_orden(orden, usuario_id):
    """Reverse inventory deductions for a cancelled order that already had inventory deducted."""
    for detalle in orden.detalles:
        if not detalle.producto or not detalle.producto.receta_items:
            continue
        for receta in detalle.producto.receta_items:
            cantidad_total = receta.cantidad_por_unidad * detalle.cantidad
            receta.ingrediente.stock_actual += cantidad_total
            mov = MovimientoInventario(
                ingrediente_id=receta.ingrediente_id,
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
    query = Orden.query.options(
        joinedload(Orden.mesa),
        joinedload(Orden.detalles).joinedload(OrdenDetalle.producto),
        joinedload(Orden.mesero),
    ).filter(
        Orden.estado.notin_(['pagada', 'finalizada', 'cancelada']),
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
    hoy = date.today()
    q_pagadas = Orden.query.options(
        joinedload(Orden.mesa),
        joinedload(Orden.detalles).joinedload(OrdenDetalle.producto),
        joinedload(Orden.mesero),
    ).filter(
        Orden.estado.in_(['pagada', 'finalizada']),
        db.or_(
            db.func.date(Orden.fecha_pago) == hoy,
            db.func.date(Orden.tiempo_registro) == hoy,
        ),
    )
    if not is_admin:
        q_pagadas = q_pagadas.filter(Orden.mesero_id == user_id)
    q_pagadas = filtrar_por_sucursal(q_pagadas, Orden)
    ordenes_pagadas = q_pagadas.order_by(Orden.fecha_pago.desc()).all()

    template = 'admin/ordenes_activas.html' if is_admin else 'meseros.html'
    return render_template(template, ordenes_mesero=ordenes_mesero,
                           ordenes_pagadas=ordenes_pagadas, now_utc=datetime.utcnow())


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
    hoy = date.today()
    query = Orden.query.options(
        joinedload(Orden.mesa),
        joinedload(Orden.detalles).joinedload(OrdenDetalle.producto),
    ).filter(
        Orden.estado.in_(['finalizada', 'pagada']),
        db.or_(
            db.func.date(Orden.fecha_pago) == hoy,
            db.func.date(Orden.tiempo_registro) == hoy,
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

    hoy = date.today()
    query = Orden.query.options(
        joinedload(Orden.mesa),
        joinedload(Orden.detalles).joinedload(OrdenDetalle.producto),
    ).filter(
        Orden.estado.in_(['finalizada', 'pagada']),
        db.or_(
            db.func.date(Orden.fecha_pago) == hoy,
            db.func.date(Orden.tiempo_registro) == hoy,
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
        writer.writerow([f'#{o.id}', o.tiempo_registro.strftime('%H:%M'), mesa, o.estado, productos, f'${total:.2f}'])

    output.seek(0)
    return Response(
        output.getvalue(),
        mimetype='text/csv',
        headers={'Content-Disposition': f'attachment; filename=historial_{hoy.isoformat()}.csv'},
    )


# =====================================================================
# Crear órdenes
# =====================================================================
@meseros_bp.route('/crear_orden_para_llevar')
@login_required(roles='mesero')
def crear_orden_para_llevar():
    nueva_orden = Orden(
        mesero_id=session.get('user_id'), es_para_llevar=True, estado='pendiente',
        sucursal_id=g.sucursal_id,
    )
    db.session.add(nueva_orden)
    db.session.commit()
    logger.info('Orden para llevar creada: id=%s', nueva_orden.id)
    flash('Nueva orden para llevar creada. Añade productos.', 'success')
    return redirect(url_for('meseros.detalle_orden', orden_id=nueva_orden.id))


@meseros_bp.route('/seleccionar_mesa', methods=['GET', 'POST'])
@login_required(roles='mesero')
def seleccionar_mesa():
    if request.method == 'POST':
        mesa_id = request.form.get('mesa_id')
        if mesa_id:
            orden_existente = Orden.query.filter(
                Orden.mesa_id == int(mesa_id),
                Orden.estado.notin_(['pagada', 'finalizada', 'cancelada']),
            ).first()
            if orden_existente:
                flash(f'Mesa ya tiene orden activa (ID: {orden_existente.id}).', 'warning')
                return redirect(url_for('meseros.detalle_orden', orden_id=orden_existente.id))

            nueva_orden = Orden(
                mesero_id=session.get('user_id'), mesa_id=int(mesa_id),
                es_para_llevar=False, estado='pendiente',
                sucursal_id=g.sucursal_id,
            )
            db.session.add(nueva_orden)
            db.session.commit()
            # Auto-ocupar mesa (Sprint 2 — 3.3)
            actualizar_estado_mesa(int(mesa_id), 'ocupada')
            db.session.commit()
            flash(f'Orden creada para Mesa {nueva_orden.mesa.numero}.', 'success')
            return redirect(url_for('meseros.detalle_orden', orden_id=nueva_orden.id))
        flash('Debes seleccionar una mesa.', 'warning')
        return redirect(url_for('meseros.seleccionar_mesa'))

    mesas = filtrar_por_sucursal(Mesa.query, Mesa).order_by(Mesa.numero).all()

    # Sprint 9 — 9.4: enrich mesas with active order info
    active_orders = Orden.query.filter(
        Orden.estado.notin_(['pagada', 'finalizada', 'cancelada']),
    ).all()
    mesa_order_map = {}
    for o in active_orders:
        if o.mesa_id:
            mesa_order_map[o.mesa_id] = o

    zonas = sorted(set(m.zona for m in mesas if m.zona))
    return render_template('seleccionar_mesa.html', mesas=mesas,
                           mesa_order_map=mesa_order_map, zonas=zonas)


# =====================================================================
# Detalle / agregar productos
# =====================================================================
@meseros_bp.route('/ordenes/<int:orden_id>/detalle_orden', methods=['GET'])
@login_required(roles='mesero')
@verificar_propiedad_orden
def detalle_orden(orden_id):
    orden = Orden.query.options(
        joinedload(Orden.mesa),
        joinedload(Orden.detalles).joinedload(OrdenDetalle.producto),
    ).get_or_404(orden_id)

    if orden.estado not in ESTADOS_MODIFICABLES:
        flash(f'Orden #{orden.id} no puede modificarse ({orden.estado}).', 'warning')
        return redirect(url_for('meseros.view_meseros'))

    productos = Producto.query.options(
        joinedload(Producto.categoria),
    ).order_by(Producto.categoria_id, Producto.nombre).all()

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
    orden = Orden.query.get_or_404(orden_id)
    if orden.estado not in ESTADOS_MODIFICABLES:
        flash(f'No se pueden agregar productos ({orden.estado}).', 'danger')
        return redirect(url_for('meseros.detalle_orden', orden_id=orden_id))

    data = request.form.get('productos_json')
    if not data:
        flash('No se recibieron productos.', 'warning')
        return redirect(url_for('meseros.detalle_orden', orden_id=orden_id))

    orden_ya_enviada = orden.estado != 'pendiente'
    try:
        productos_sel = json.loads(data)
        if not productos_sel:
            flash('No se seleccionaron productos.', 'info')
            return redirect(url_for('meseros.detalle_orden', orden_id=orden_id))

        nuevos = []
        stock_warnings = []
        for p_data in productos_sel:
            prod = Producto.query.get(p_data['id'])
            if not prod:
                continue
            cantidad = int(p_data['cantidad'])

            # Validación de stock (Sprint 2 — 3.2)
            if current_app.config.get('INVENTARIO_VALIDAR_STOCK'):
                disponible, faltantes, warns = verificar_stock_disponible(prod.id, cantidad)
                if not disponible:
                    nombres = ', '.join(f['ingrediente'] for f in faltantes)
                    flash(f'Stock insuficiente para {prod.nombre}: faltan {nombres}', 'danger')
                    continue
                stock_warnings.extend(warns)

            existente = OrdenDetalle.query.filter_by(
                orden_id=orden_id, producto_id=prod.id, estado='pendiente',
            ).first()
            if existente:
                existente.cantidad += cantidad
            else:
                d = OrdenDetalle(
                    orden_id=orden_id, producto_id=prod.id,
                    cantidad=cantidad, precio_unitario=prod.precio, estado='pendiente',
                )
                db.session.add(d)
                nuevos.append(d)

        db.session.commit()
        if orden_ya_enviada and nuevos:
            socketio.emit('nueva_orden_cocina', {
                'orden_id': orden.id,
                'mensaje': f'Nuevos productos en orden #{orden.id}.',
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
    orden = Orden.query.options(
        joinedload(Orden.mesa),
        joinedload(Orden.detalles).joinedload(OrdenDetalle.producto),
    ).get_or_404(orden_id)
    return render_template('pago.html', orden=orden)


# =====================================================================
# Enviar / entregar / cancelar
# =====================================================================
@meseros_bp.route('/ordenes/<int:orden_id>/enviar_a_cocina', methods=['POST'])
@login_required(roles='mesero')
@verificar_propiedad_orden
def enviar_orden_a_cocina(orden_id):
    orden = Orden.query.get_or_404(orden_id)
    if not orden.detalles:
        flash('Orden vacía.', 'warning')
        return redirect(url_for('meseros.detalle_orden', orden_id=orden_id))
    if orden.estado != 'pendiente':
        flash(f'Orden ya enviada ({orden.estado}).', 'warning')
    else:
        orden.estado = 'enviado'
        db.session.commit()
        socketio.emit('nueva_orden_cocina', {'orden_id': orden.id, 'mensaje': f'Orden #{orden.id} para cocina.'})
        # Auto-imprimir comanda si está configurado (Sprint 3 — 3.1)
        from backend.services.printer import AUTO_PRINT_COMANDA, imprimir_comanda
        if AUTO_PRINT_COMANDA:
            imprimir_comanda(orden)
        flash('Orden enviada a cocina.', 'success')
    return redirect(url_for('meseros.view_meseros'))


@meseros_bp.route('/entregar_item/<int:orden_id>/<int:detalle_id>', methods=['POST'])
@login_required(roles=['mesero', 'admin', 'superadmin'])
def entregar_item(orden_id, detalle_id):
    detalle = OrdenDetalle.query.filter_by(id=detalle_id, orden_id=orden_id).first_or_404()
    if detalle.estado == 'entregado':
        return jsonify(success=False, message="Ya entregado."), 400
    if detalle.estado != 'listo':
        return jsonify(success=False, message="No está listo."), 400

    detalle.estado = 'entregado'
    orden = Orden.query.options(joinedload(Orden.detalles)).get_or_404(orden_id)

    if all(d.estado == 'entregado' for d in orden.detalles):
        if orden.estado not in ['pagada', 'finalizada', 'cancelada', 'completada']:
            orden.estado = 'completada'
            socketio.emit('orden_actualizada_para_cobro', {
                'orden_id': orden.id, 'estado_orden': 'completada',
                'mensaje': f'Orden #{orden.id} lista para cobro.',
            })
    db.session.commit()
    return jsonify(success=True, message="Entregado.")


@meseros_bp.route('/ordenes/<int:orden_id>/cancelar', methods=['POST'])
@login_required(roles=['mesero', 'admin', 'superadmin'])
def cancelar_orden(orden_id):
    orden = Orden.query.options(
        joinedload(Orden.detalles).joinedload(OrdenDetalle.producto),
        joinedload(Orden.pagos),
    ).get_or_404(orden_id)
    if orden.estado in ['pagada', 'finalizada', 'cancelada']:
        flash('No se puede cancelar.', 'warning')
        return redirect(url_for('meseros.view_meseros'))

    # Reverse inventory if it was already deducted (order went through payment flow)
    if orden.estado == 'pagada' or orden.pagos:
        try:
            _revertir_inventario_orden(orden, session.get('user_id'))
        except Exception:
            logger.exception('Error revirtiendo inventario orden %s', orden_id)

    orden.estado = 'cancelada'
    db.session.commit()
    # Liberar mesa si no quedan órdenes activas (Sprint 2 — 3.3)
    actualizar_estado_mesa(orden.mesa_id)
    db.session.commit()
    logger.info('Orden %s cancelada por usuario %s', orden_id, session.get('user_id'))
    flash(f'Orden #{orden.id} cancelada.', 'info')
    return redirect(url_for('meseros.view_meseros'))


# =====================================================================
# ITEM 12: Descuento con autorización
# =====================================================================
@meseros_bp.route('/ordenes/<int:orden_id>/descuento', methods=['POST'])
@login_required(roles=['mesero', 'admin', 'superadmin'])
def aplicar_descuento(orden_id):
    """Aplica descuento; requiere credenciales de admin/superadmin para autorizar."""
    orden = Orden.query.get_or_404(orden_id)
    data = request.get_json()
    if not data:
        return jsonify(success=False, message="Datos faltantes."), 400

    # Validar autorización
    auth_email = data.get('auth_email')
    auth_password = data.get('auth_password')
    autorizador = Usuario.query.filter_by(email=auth_email).first()

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
    orden = Orden.query.options(
        joinedload(Orden.mesa),
        joinedload(Orden.detalles).joinedload(OrdenDetalle.producto),
        joinedload(Orden.pagos),
    ).get_or_404(orden_id)

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

    return jsonify({
        "orden_id": orden.id,
        "mesa_numero": orden.mesa.numero if orden.mesa else None,
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
    orden = db.session.query(Orden).with_for_update().get(orden_id)
    if not orden:
        return jsonify(success=False, message="Orden no encontrada."), 404
    # Eager-load relationships after locking
    db.session.refresh(orden)
    orden.detalles  # trigger lazy load
    orden.pagos     # trigger lazy load

    if orden.estado not in ('completada', 'lista_para_entregar'):
        return jsonify(success=False, message=f"Orden no lista para cobro ({orden.estado})."), 400

    data = request.get_json()
    metodo = data.get('metodo', 'efectivo')
    if metodo not in ('efectivo', 'tarjeta', 'transferencia'):
        return jsonify(success=False, message="Método inválido."), 400

    try:
        monto = Decimal(str(data.get('monto', 0)))
    except Exception:
        return jsonify(success=False, message="Monto inválido."), 400

    if monto <= 0:
        return jsonify(success=False, message="Monto debe ser mayor a 0."), 400

    referencia = data.get('referencia', '')

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

    pago = Pago(
        metodo=metodo, monto=monto,
        referencia=referencia, registrado_por=session.get('user_id'),
    )
    orden.pagos.append(pago)  # Use relationship so in-memory collection stays in sync
    db.session.flush()

    total_pagado = orden.total_pagado()
    saldo = orden.saldo_pendiente()

    # Si ya se cubrió el total, cerrar la orden
    if saldo <= 0:
        cambio = abs(saldo) if metodo == 'efectivo' else Decimal('0')
        orden.monto_recibido = total_pagado
        orden.cambio = cambio
        orden.fecha_pago = datetime.utcnow()
        orden.estado = 'pagada'

        # Crear Sale record
        venta = Sale(mesa_id=orden.mesa_id, usuario_id=session.get('user_id'),
                     total=orden.total, estado='cerrada',
                     sucursal_id=getattr(g, 'sucursal_id', None))
        db.session.add(venta)
        db.session.flush()
        for det in orden.detalles:
            precio = float(det.precio_unitario) if det.precio_unitario else float(det.producto.precio)
            db.session.add(SaleItem(
                sale_id=venta.id, producto_id=det.producto_id,
                cantidad=det.cantidad, precio_unitario=precio,
                subtotal=det.cantidad * precio,
            ))

        socketio.emit('orden_pagada_notificacion', {
            'orden_id': orden.id, 'mensaje': f'Orden #{orden.id} pagada.',
        })
        # Descontar inventario según receta estándar
        inventario_ok = True
        try:
            descontar_inventario_por_orden(orden, session.get('user_id'))
        except Exception:
            inventario_ok = False
            logger.exception('Error descontando inventario orden %s — requiere reconciliación', orden_id)
            # Flag for reconciliation via ConfiguracionSistema
            try:
                from backend.models.models import ConfiguracionSistema
                pending = ConfiguracionSistema.get('inventario_pendiente', '')
                ids = f"{pending},{orden_id}" if pending else str(orden_id)
                ConfiguracionSistema.set('inventario_pendiente', ids)
            except Exception:
                pass  # Don't block payment over flagging

        # Actualizar visitas/gasto del cliente
        if orden.cliente_id:
            cli = Cliente.query.get(orden.cliente_id)
            if cli:
                cli.visitas = (cli.visitas or 0) + 1
                cli.total_gastado = (cli.total_gastado or 0) + orden.total

        logger.info('Orden #%s pagada total=$%.2f', orden_id, float(orden.total))

    # Auditoría (Sprint 6 — 3.5)
    from backend.services.audit import registrar_auditoria
    registrar_auditoria('pago', 'Orden', orden_id,
                        f'Pago ${float(monto):.2f} ({metodo}). Propina: ${float(propina):.2f}')

    db.session.commit()

    # Liberar mesa si orden pagada (Sprint 2 — 3.3)
    if orden.estado == 'pagada':
        actualizar_estado_mesa(orden.mesa_id)
        db.session.commit()

    return jsonify(
        success=True,
        message="Pago registrado." + (" Orden pagada." if orden.estado == 'pagada' else ""),
        pago_id=pago.id,
        metodo=metodo,
        monto=float(monto),
        total_pagado=float(orden.total_pagado()),
        saldo_pendiente=float(max(orden.saldo_pendiente(), Decimal('0'))),
        cambio=float(orden.cambio or 0),
        orden_pagada=(orden.estado == 'pagada'),
    )


# =====================================================================
# Cobrar (legacy — redirige a nuevo flujo de pagos)
# =====================================================================
@meseros_bp.route('/ordenes/<int:orden_id>/cobrar', methods=['POST'])
@login_required(roles='mesero')
@verificar_propiedad_orden
def cobrar_orden_post(orden_id):
    """Compatibilidad: convierte pago único legacy al nuevo modelo multi-pago."""
    orden = Orden.query.options(
        joinedload(Orden.detalles).joinedload(OrdenDetalle.producto),
        joinedload(Orden.pagos),
    ).get_or_404(orden_id)

    if orden.estado not in ('completada', 'lista_para_entregar'):
        return jsonify(success=False, message=f"No lista para cobro ({orden.estado})."), 400

    data = request.get_json()
    if not data or 'monto_recibido' not in data:
        return jsonify(success=False, message="Falta monto_recibido."), 400

    try:
        monto_recibido = Decimal(str(data['monto_recibido']))
    except Exception:
        return jsonify(success=False, message="Monto inválido."), 400

    orden.calcular_totales()

    if monto_recibido < orden.total:
        return jsonify(success=False, message=f"Insuficiente (total=${orden.total}).",
                       total_orden=float(orden.total)), 400

    # Registrar como pago efectivo
    pago = Pago(
        orden_id=orden.id, metodo='efectivo', monto=monto_recibido,
        registrado_por=session.get('user_id'),
    )
    db.session.add(pago)

    orden.monto_recibido = monto_recibido
    orden.cambio = monto_recibido - orden.total
    orden.fecha_pago = datetime.utcnow()
    orden.estado = 'pagada'

    venta = Sale(mesa_id=orden.mesa_id, usuario_id=session.get('user_id'),
                 total=orden.total, estado='cerrada',
                 sucursal_id=getattr(g, 'sucursal_id', None))
    db.session.add(venta)
    db.session.flush()

    for det in orden.detalles:
        precio = float(det.precio_unitario) if det.precio_unitario else float(det.producto.precio)
        db.session.add(SaleItem(
            sale_id=venta.id, producto_id=det.producto_id,
            cantidad=det.cantidad, precio_unitario=precio,
            subtotal=det.cantidad * precio,
        ))

    db.session.commit()
    # Descontar inventario (Sprint 6)
    try:
        descontar_inventario_por_orden(orden, session.get('user_id'))
    except Exception:
        logger.exception('Error descontando inventario en cobrar_orden_post orden %s', orden_id)
    # Liberar mesa si no quedan órdenes activas (Sprint 2 — 3.3)
    actualizar_estado_mesa(orden.mesa_id)
    db.session.commit()
    logger.info('Orden #%s pagada (legacy). Total=$%.2f', orden_id, float(orden.total))

    socketio.emit('orden_pagada_notificacion', {
        'orden_id': orden.id, 'mensaje': f'Orden #{orden.id} pagada.',
    })

    return jsonify(
        success=True, message="Pago confirmado.",
        cambio=float(orden.cambio), orden_id=orden.id,
        subtotal=float(orden.subtotal), iva=float(orden.iva), total=float(orden.total),
    )


# =====================================================================
# Impresión ESC/POS (Sprint 3 — 3.1)
# =====================================================================
@meseros_bp.route('/ordenes/<int:orden_id>/imprimir/comanda', methods=['POST'])
@login_required(roles=['mesero', 'admin', 'superadmin'])
def imprimir_comanda_endpoint(orden_id):
    """Imprime comanda de cocina. Fallback: retorna texto para window.print()."""
    from backend.services.printer import imprimir_comanda, generar_texto_comanda, PRINTER_TYPE
    orden = Orden.query.options(
        joinedload(Orden.mesa),
        joinedload(Orden.mesero),
        joinedload(Orden.detalles).joinedload(OrdenDetalle.producto),
    ).get_or_404(orden_id)

    if PRINTER_TYPE != 'none':
        ok = imprimir_comanda(orden)
        if ok:
            return jsonify(success=True, message='Comanda impresa.')
        return jsonify(success=False, message='Error al imprimir.', texto=generar_texto_comanda(orden))

    # Modo none: retornar texto para impresión del navegador
    return jsonify(success=True, fallback=True, texto=generar_texto_comanda(orden))


@meseros_bp.route('/ordenes/<int:orden_id>/imprimir/ticket', methods=['POST'])
@login_required(roles=['mesero', 'admin', 'superadmin'])
def imprimir_ticket_endpoint(orden_id):
    """Imprime ticket de cuenta. Fallback: retorna texto para window.print()."""
    from backend.services.printer import imprimir_ticket_cuenta, generar_texto_ticket, PRINTER_TYPE
    orden = Orden.query.options(
        joinedload(Orden.mesa),
        joinedload(Orden.mesero),
        joinedload(Orden.detalles).joinedload(OrdenDetalle.producto),
        joinedload(Orden.pagos),
    ).get_or_404(orden_id)

    if PRINTER_TYPE != 'none':
        ok = imprimir_ticket_cuenta(orden)
        if ok:
            return jsonify(success=True, message='Ticket impreso.')
        return jsonify(success=False, message='Error al imprimir.', texto=generar_texto_ticket(orden))

    return jsonify(success=True, fallback=True, texto=generar_texto_ticket(orden))
