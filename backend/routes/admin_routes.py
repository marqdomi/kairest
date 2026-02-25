import logging
from decimal import Decimal
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, current_app, g
from backend.utils import login_required, filtrar_por_sucursal
from backend.extensions import db
from backend.services.sanitizer import sanitizar_texto, sanitizar_email
from backend.models.models import Sale, SaleItem, Producto, Mesa, CorteCaja, Usuario, Categoria, Estacion, Pago, Orden, Ingrediente, OrdenDetalle
from backend.services.password_policy import validar_password
from sqlalchemy.orm import joinedload
from sqlalchemy import func
from werkzeug.security import generate_password_hash
from datetime import date, datetime, timedelta
from flask_login import current_user

logger = logging.getLogger(__name__)

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')


def _period_range():
    """Return (start_date, end_date) tuple from ?period= query param.
    Supports: today (default), yesterday, week, month.
    """
    period = request.args.get('period', 'today')
    hoy = date.today()
    if period == 'yesterday':
        return hoy - timedelta(days=1), hoy - timedelta(days=1)
    elif period == 'week':
        return hoy - timedelta(days=6), hoy
    elif period == 'month':
        return hoy - timedelta(days=29), hoy
    return hoy, hoy  # today


@admin_bp.route('/dashboard', methods=['GET'])
@login_required(roles=['admin','superadmin'])
def dashboard():
    """Admin dashboard landing page."""
    return render_template('admin/dashboard.html')

@admin_bp.route('/crear_usuario', methods=['GET', 'POST'])
@login_required(roles=['admin','superadmin'])
def crear_usuario():
    """Legacy redirect — use /usuarios/nuevo instead."""
    return redirect(url_for('admin.usuario_nuevo'))

@admin_bp.route('/api/dashboard/ventas_hoy')
@login_required(roles=['admin','superadmin'])
def api_ventas_hoy():
    inicio, fin = _period_range()
    q = filtrar_por_sucursal(
        db.session.query(db.func.sum(Sale.total))
        .filter(db.func.date(Sale.fecha_hora) >= inicio)
        .filter(db.func.date(Sale.fecha_hora) <= fin), Sale,
    )
    total = q.scalar() or 0
    return jsonify({'ventasHoy': float(total)})

@admin_bp.route('/api/dashboard/ordenes_hoy')
@login_required(roles=['admin','superadmin'])
def api_ordenes_hoy():
    inicio, fin = _period_range()
    count = filtrar_por_sucursal(
        Sale.query.filter(db.func.date(Sale.fecha_hora) >= inicio)
        .filter(db.func.date(Sale.fecha_hora) <= fin), Sale,
    ).count()
    return jsonify({'ordenesHoy': count})

@admin_bp.route('/api/dashboard/ticket_promedio')
@login_required(roles=['admin','superadmin'])
def api_ticket_promedio():
    inicio, fin = _period_range()
    ventas = filtrar_por_sucursal(
        Sale.query.filter(db.func.date(Sale.fecha_hora) >= inicio)
        .filter(db.func.date(Sale.fecha_hora) <= fin), Sale,
    ).all()
    if not ventas:
        return jsonify({'ticketPromedio': 0})
    promedio = sum(v.total for v in ventas) / len(ventas)
    return jsonify({'ticketPromedio': float(promedio)})

@admin_bp.route('/api/dashboard/top_productos')
@login_required(roles=['admin','superadmin'])
def api_top_productos():
    inicio, fin = _period_range()
    results = db.session.query(
        Producto.nombre,
        db.func.sum(SaleItem.cantidad).label('cantidad')
    ).join(SaleItem, SaleItem.producto_id == Producto.id) \
     .join(Sale, SaleItem.sale_id == Sale.id) \
     .filter(db.func.date(Sale.fecha_hora) >= inicio) \
     .filter(db.func.date(Sale.fecha_hora) <= fin) \
     .filter(Sale.sucursal_id == g.sucursal_id if getattr(g, 'sucursal_id', None) else True) \
     .group_by(Producto.id) \
     .order_by(db.desc('cantidad')) \
     .limit(5) \
     .all()
    return jsonify({
        'labels': [r[0] for r in results],
        'data':   [int(r[1]) for r in results]
    })


# --- Sprint 5: Dashboard mejorado APIs (5.4) ---

@admin_bp.route('/api/dashboard/mesas_activas')
@login_required(roles=['admin','superadmin'])
def api_mesas_activas():
    """Mesas ocupadas vs total."""
    q = filtrar_por_sucursal(Mesa.query, Mesa)
    total = q.count()
    ocupadas = q.filter(Mesa.estado == 'ocupada').count()
    reservadas = q.filter(Mesa.estado == 'reservada').count()
    return jsonify({'total': total, 'ocupadas': ocupadas, 'reservadas': reservadas})


@admin_bp.route('/api/dashboard/ordenes_cocina')
@login_required(roles=['admin','superadmin'])
def api_ordenes_cocina():
    """Órdenes con items pendientes en cocina."""
    pendientes = filtrar_por_sucursal(
        Orden.query.filter(Orden.estado.in_(['pendiente', 'en_preparacion'])), Orden
    ).count()
    # Timer promedio de órdenes activas
    ahora = datetime.utcnow()
    ordenes_activas = filtrar_por_sucursal(
        Orden.query.filter(Orden.estado.in_(['pendiente', 'en_preparacion'])), Orden
    ).all()
    if ordenes_activas:
        tiempos = [(ahora - o.tiempo_registro).total_seconds() / 60 for o in ordenes_activas]
        timer_prom = round(sum(tiempos) / len(tiempos), 1)
    else:
        timer_prom = 0
    return jsonify({'pendientes': pendientes, 'timer_promedio_min': timer_prom})


@admin_bp.route('/api/dashboard/alertas_stock')
@login_required(roles=['admin','superadmin'])
def api_alertas_stock():
    """Ingredientes con stock bajo (stock_actual <= stock_minimo)."""
    q = Ingrediente.query.filter(
        Ingrediente.activo == True,
        Ingrediente.stock_actual <= Ingrediente.stock_minimo
    )
    suc_id = getattr(g, 'sucursal_id', None)
    if suc_id is not None:
        q = q.filter(Ingrediente.sucursal_id == suc_id)
    alertas = q.order_by(Ingrediente.stock_actual.asc()).limit(10).all()
    return jsonify({
        'count': len(alertas),
        'items': [
            {'nombre': a.nombre, 'stock': float(a.stock_actual), 'minimo': float(a.stock_minimo), 'unidad': a.unidad}
            for a in alertas
        ]
    })


@admin_bp.route('/api/dashboard/propinas_hoy')
@login_required(roles=['admin','superadmin'])
def api_propinas_hoy():
    """Total de propinas del período."""
    inicio, fin = _period_range()
    q = filtrar_por_sucursal(
        db.session.query(func.sum(Orden.propina)).filter(
            func.date(Orden.fecha_pago) >= inicio,
            func.date(Orden.fecha_pago) <= fin,
            Orden.propina > 0
        ), Orden
    )
    total = q.scalar() or 0
    return jsonify({'propinas': float(total)})


@admin_bp.route('/api/dashboard/ultimo_corte')
@login_required(roles=['admin','superadmin'])
def api_ultimo_corte():
    """Último corte de caja."""
    q = CorteCaja.query.options(joinedload(CorteCaja.usuario))
    suc_id = getattr(g, 'sucursal_id', None)
    if suc_id is not None:
        q = q.filter(CorteCaja.sucursal_id == suc_id)
    corte = q.order_by(CorteCaja.fecha.desc()).first()
    if not corte:
        return jsonify({'exists': False})
    return jsonify({
        'exists': True,
        'fecha': corte.fecha.isoformat(),
        'total_ingresos': float(corte.total_ingresos),
        'diferencia': float(corte.diferencia),
        'usuario': corte.usuario.nombre if corte.usuario else '—'
    })


@admin_bp.route('/api/dashboard/ventas_7dias')
@login_required(roles=['admin','superadmin'])
def api_ventas_7dias():
    """Ventas diarias de los últimos 7 días."""
    hoy = date.today()
    inicio = hoy - timedelta(days=6)
    results = filtrar_por_sucursal(
        db.session.query(
            func.date(Sale.fecha_hora).label('dia'),
            func.sum(Sale.total).label('total')
        ).filter(func.date(Sale.fecha_hora) >= inicio)
        .group_by(func.date(Sale.fecha_hora))
        .order_by(func.date(Sale.fecha_hora)), Sale
    ).all()

    # Fill missing days with 0
    ventas_map = {str(r.dia): float(r.total) for r in results}
    labels = []
    data = []
    for i in range(7):
        d = inicio + timedelta(days=i)
        labels.append(d.strftime('%d/%m'))
        data.append(ventas_map.get(str(d), 0))

    return jsonify({'labels': labels, 'data': data})


@admin_bp.route('/api/dashboard/actividad_reciente')
@login_required(roles=['admin','superadmin'])
def api_actividad_reciente():
    """Últimas 8 órdenes/ventas para feed de actividad."""
    recientes = filtrar_por_sucursal(
        Orden.query.options(
            joinedload(Orden.mesero),
            joinedload(Orden.mesa)
        ).order_by(Orden.tiempo_registro.desc()).limit(8), Orden
    ).all()
    items = []
    for o in recientes:
        items.append({
            'id': o.id,
            'estado': o.estado,
            'mesa': o.mesa.numero if o.mesa else 'P/LL',
            'mesero': o.mesero.nombre if o.mesero else '—',
            'total': float(o.total) if o.total else 0,
            'hora': o.tiempo_registro.strftime('%H:%M'),
        })
    return jsonify({'items': items})

# --- Usuarios CRUD ---
@admin_bp.route('/usuarios')
@login_required(roles=['admin', 'superadmin'])
def lista_usuarios():
    usuarios = Usuario.query.order_by(Usuario.rol, Usuario.nombre).all()
    return render_template('admin/usuarios.html', usuarios=usuarios)

@admin_bp.route('/usuarios/nuevo', methods=['GET', 'POST'])
@login_required(roles=['admin', 'superadmin'])
def usuario_nuevo():
    if request.method == 'POST':
        nombre = sanitizar_texto(request.form['nombre'], 100)
        email = sanitizar_email(request.form['email']) or request.form['email'].strip()
        rol_raw = request.form['rol']
        password = request.form['password']
        if Usuario.query.filter_by(email=email).first():
            flash('Email ya existe', 'danger')
            return redirect(url_for('admin.usuario_nuevo'))
        # Validar política de contraseñas
        pw_valida, pw_errores = validar_password(password, nombre=nombre, email=email)
        if not pw_valida:
            for err in pw_errores:
                flash(err, 'danger')
            return redirect(url_for('admin.usuario_nuevo'))
        # Parse cocina:station_name → rol='cocina' + estacion_id
        estacion_id = None
        if rol_raw.startswith('cocina:'):
            station_name = rol_raw.split(':', 1)[1].strip()
            est = Estacion.query.filter(db.func.lower(Estacion.nombre) == station_name.lower()).first()
            if est:
                estacion_id = est.id
            rol = 'cocina'
        else:
            rol = rol_raw
        u = Usuario(nombre=nombre, email=email, rol=rol, estacion_id=estacion_id)
        u.set_password(password)
        db.session.add(u)
        db.session.commit()
        flash('Usuario creado', 'success')
        return redirect(url_for('admin.lista_usuarios'))
    estaciones = Estacion.query.order_by(Estacion.nombre).all()
    return render_template('admin/usuario_form.html', estaciones=estaciones)

@admin_bp.route('/usuarios/<int:id>/editar', methods=['GET', 'POST'])
@login_required(roles=['admin', 'superadmin'])
def usuario_editar(id):
    u = Usuario.query.get_or_404(id)
    if request.method == 'POST':
        u.nombre = sanitizar_texto(request.form['nombre'], 100)
        u.email = sanitizar_email(request.form['email']) or request.form['email'].strip()
        rol_raw = request.form['rol']
        # Parse cocina:station_name → rol='cocina' + estacion_id
        if rol_raw.startswith('cocina:'):
            station_name = rol_raw.split(':', 1)[1].strip()
            est = Estacion.query.filter(db.func.lower(Estacion.nombre) == station_name.lower()).first()
            u.rol = 'cocina'
            u.estacion_id = est.id if est else None
        else:
            u.rol = rol_raw
            u.estacion_id = None
        db.session.commit()
        flash('Usuario actualizado', 'success')
        return redirect(url_for('admin.lista_usuarios'))
    estaciones = Estacion.query.order_by(Estacion.nombre).all()
    return render_template('admin/usuario_form.html', usuario=u, estaciones=estaciones)

@admin_bp.route('/usuarios/<int:id>/eliminar', methods=['POST'])
@login_required(roles=['admin', 'superadmin'])
def usuario_eliminar(id):
    u = Usuario.query.get_or_404(id)
    db.session.delete(u)
    db.session.commit()
    flash('Usuario eliminado', 'success')
    return redirect(url_for('admin.lista_usuarios'))


# --- Productos CRUD ---
@admin_bp.route('/productos')
@login_required(roles=['superadmin'])
def lista_productos():
    productos = Producto.query.options(
        joinedload(Producto.categoria),
        joinedload(Producto.estacion)
    ).order_by(Producto.nombre).all()
    return render_template('admin/productos.html', productos=productos)

@admin_bp.route('/productos/nuevo', methods=['GET', 'POST'])
@login_required(roles=['superadmin'])
def producto_nuevo():
    if request.method == 'POST':
        p = Producto(
            nombre=sanitizar_texto(request.form['nombre'], 100),
            precio=float(request.form['precio']),
            unidad=sanitizar_texto(request.form.get('unidad'), 30) if request.form.get('unidad') else None,
            descripcion=sanitizar_texto(request.form.get('descripcion'), 500) if request.form.get('descripcion') else None,
            categoria_id=int(request.form['categoria_id']),
            estacion_id=int(request.form['estacion_id'])
        )
        db.session.add(p)
        db.session.commit()
        flash('Producto creado', 'success')
        return redirect(url_for('admin.lista_productos'))
    categorias = Categoria.query.order_by(Categoria.nombre).all()
    estaciones = Estacion.query.order_by(Estacion.nombre).all()
    return render_template(
        'admin/producto_form.html',
        categorias=categorias,
        estaciones=estaciones
    )

@admin_bp.route('/productos/<int:id>/editar', methods=['GET', 'POST'])
@login_required(roles=['superadmin'])
def producto_editar(id):
    p = Producto.query.get_or_404(id)
    if request.method == 'POST':
        p.nombre = sanitizar_texto(request.form['nombre'], 100)
        p.precio = float(request.form['precio'])
        p.unidad = sanitizar_texto(request.form.get('unidad'), 30) if request.form.get('unidad') else None
        p.descripcion = sanitizar_texto(request.form.get('descripcion'), 500) if request.form.get('descripcion') else None
        p.categoria_id = int(request.form['categoria_id'])
        p.estacion_id = int(request.form['estacion_id'])
        db.session.commit()
        flash('Producto actualizado', 'success')
        return redirect(url_for('admin.lista_productos'))
    categorias = Categoria.query.order_by(Categoria.nombre).all()
    estaciones = Estacion.query.order_by(Estacion.nombre).all()
    return render_template(
        'admin/producto_form.html',
        producto=p,
        categorias=categorias,
        estaciones=estaciones
    )

@admin_bp.route('/productos/<int:id>/eliminar', methods=['POST'])
@login_required(roles=['superadmin'])
def producto_eliminar(id):
    p = Producto.query.get_or_404(id)
    db.session.delete(p)
    db.session.commit()
    flash('Producto eliminado', 'success')
    return redirect(url_for('admin.lista_productos'))


# --- Mesas CRUD ---
@admin_bp.route('/mesas')
@login_required(roles=['superadmin'])
def lista_mesas():
    mesas = filtrar_por_sucursal(Mesa.query, Mesa).order_by(Mesa.numero).all()
    return render_template('admin/mesas.html', mesas=mesas)

@admin_bp.route('/mesas/nuevo', methods=['GET', 'POST'])
@login_required(roles=['superadmin'])
def mesa_nuevo():
    if request.method == 'POST':
        m = Mesa(
            numero=request.form['numero'],
            capacidad=int(request.form.get('capacidad', 4)),
            zona=request.form.get('zona', ''),
        )
        db.session.add(m)
        db.session.commit()
        flash('Mesa creada', 'success')
        return redirect(url_for('admin.lista_mesas'))
    return render_template('admin/mesa_form.html')

@admin_bp.route('/mesas/<int:id>/editar', methods=['GET', 'POST'])
@login_required(roles=['superadmin'])
def mesa_editar(id):
    m = Mesa.query.get_or_404(id)
    if request.method == 'POST':
        m.numero = request.form['numero']
        m.capacidad = int(request.form.get('capacidad', 4))
        m.zona = request.form.get('zona', '')
        db.session.commit()
        flash('Mesa actualizada', 'success')
        return redirect(url_for('admin.lista_mesas'))
    return render_template('admin/mesa_form.html', mesa=m)

@admin_bp.route('/mesas/<int:id>/eliminar', methods=['POST'])
@login_required(roles=['superadmin'])
def mesa_eliminar(id):
    m = Mesa.query.get_or_404(id)
    db.session.delete(m)
    db.session.commit()
    flash('Mesa eliminada', 'success')
    return redirect(url_for('admin.lista_mesas'))


@admin_bp.route('/mesas/<int:id>/posicion', methods=['POST'])
@login_required(roles=['admin', 'superadmin'])
def mesa_guardar_posicion(id):
    """Sprint 4 — 5.1: Guardar posición de mesa (drag-and-drop en mapa)."""
    m = Mesa.query.get_or_404(id)
    data = request.get_json()
    m.pos_x = int(data.get('pos_x', 0))
    m.pos_y = int(data.get('pos_y', 0))
    db.session.commit()
    return jsonify(success=True)


# --- Corte de Caja con Conciliación (Fase 2 - Item 14) ---
@admin_bp.route('/corte-caja', methods=['GET', 'POST'])
@login_required(roles=['superadmin'])
def corte_caja():
    hoy = date.today()

    # Totales de venta del día (filtrado por sucursal)
    sale_q = filtrar_por_sucursal(
        db.session.query(func.sum(Sale.total)).filter(
            func.date(Sale.fecha_hora) == hoy
        ), Sale,
    )
    total = sale_q.scalar() or Decimal('0')
    count = filtrar_por_sucursal(
        Sale.query.filter(func.date(Sale.fecha_hora) == hoy), Sale,
    ).count()
    promedio = (float(total) / count) if count else 0

    # Totales por método de pago del día
    pago_q = db.session.query(
        Pago.metodo,
        func.sum(Pago.monto).label('total'),
    ).filter(func.date(Pago.fecha) == hoy)
    # Filtrar pagos por sucursal via Sale
    suc_id = getattr(g, 'sucursal_id', None)
    if suc_id is not None:
        pago_q = pago_q.join(Orden, Pago.orden_id == Orden.id).filter(Orden.sucursal_id == suc_id)
    pagos_hoy = pago_q.group_by(Pago.metodo).all()

    efectivo_esperado = Decimal('0')
    tarjeta_total = Decimal('0')
    transferencia_total = Decimal('0')
    for metodo, monto in pagos_hoy:
        if metodo == 'efectivo':
            efectivo_esperado = monto or Decimal('0')
        elif metodo == 'tarjeta':
            tarjeta_total = monto or Decimal('0')
        elif metodo == 'transferencia':
            transferencia_total = monto or Decimal('0')

    resumen = {
        'fecha': hoy,
        'total_ingresos': float(total),
        'num_ordenes': count,
        'ticket_promedio': float(promedio),
        'efectivo_esperado': float(efectivo_esperado),
        'tarjeta_total': float(tarjeta_total),
        'transferencia_total': float(transferencia_total),
    }

    # Propinas del día (Sprint 6 — 3.6)
    propinas_q = db.session.query(func.sum(Orden.propina)).filter(
        Orden.estado == 'pagada',
        func.date(Orden.fecha_pago) == hoy,
    )
    if suc_id is not None:
        propinas_q = propinas_q.filter(Orden.sucursal_id == suc_id)
    resumen['propinas_total'] = float(propinas_q.scalar() or 0)

    if request.method == 'POST':
        efectivo_contado = request.form.get('efectivo_contado', type=float) or 0.0
        notas = request.form.get('notas', '')
        diferencia = efectivo_contado - float(efectivo_esperado)

        corte = CorteCaja(
            fecha=hoy,
            sucursal_id=getattr(g, 'sucursal_id', None),
            total_ingresos=total,
            num_ordenes=count,
            efectivo_esperado=efectivo_esperado,
            efectivo_contado=Decimal(str(efectivo_contado)),
            diferencia=Decimal(str(round(diferencia, 2))),
            tarjeta_total=tarjeta_total,
            transferencia_total=transferencia_total,
            notas=notas,
            usuario_id=session.get('user_id'),
        )
        db.session.add(corte)
        db.session.commit()
        logger.info('Corte de caja generado por usuario_id=%s diferencia=$%.2f',
                     session.get('user_id'), diferencia)
        flash('Corte de caja generado.', 'success')
        return redirect(url_for('admin.corte_caja'))

    page = request.args.get('page', 1, type=int)
    per_page = 15
    cortes_q = CorteCaja.query.options(
        joinedload(CorteCaja.usuario),
    ).order_by(CorteCaja.fecha.desc())
    if suc_id is not None:
        cortes_q = cortes_q.filter(CorteCaja.sucursal_id == suc_id)
    pagination = cortes_q.paginate(page=page, per_page=per_page, error_out=False)
    return render_template('admin/corte_caja.html', resumen=resumen,
                           cortes=pagination.items, pagination=pagination)


@admin_bp.route('/corte-caja/<int:corte_id>/imprimir', methods=['POST'])
@login_required(roles=['superadmin'])
def imprimir_corte(corte_id):
    """Imprime corte de caja. Fallback: retorna JSON para window.print()."""
    from backend.services.printer import imprimir_corte_caja, PRINTER_TYPE
    corte = CorteCaja.query.options(joinedload(CorteCaja.usuario)).get_or_404(corte_id)

    if PRINTER_TYPE != 'none':
        ok = imprimir_corte_caja(corte)
        if ok:
            return jsonify(success=True, message='Corte impreso.')
        return jsonify(success=False, message='Error al imprimir.')

    return jsonify(success=True, fallback=True, message='Impresora no configurada.')


@admin_bp.route('/corte-caja/pdf')
@login_required(roles=['superadmin'])
def export_corte_pdf():
    """Exporta corte de caja del día a PDF."""
    from datetime import datetime as dt
    from backend.services.pdf_generator import generar_pdf

    hoy = date.today()
    sale_q = filtrar_por_sucursal(
        db.session.query(func.sum(Sale.total)).filter(func.date(Sale.fecha_hora) == hoy), Sale)
    total = sale_q.scalar() or Decimal('0')
    count = filtrar_por_sucursal(Sale.query.filter(func.date(Sale.fecha_hora) == hoy), Sale).count()

    pago_q = db.session.query(Pago.metodo, func.sum(Pago.monto).label('total'),
                               func.count(Pago.id).label('cantidad')
                               ).filter(func.date(Pago.fecha) == hoy)
    suc_id = getattr(g, 'sucursal_id', None)
    if suc_id is not None:
        pago_q = pago_q.join(Orden, Pago.orden_id == Orden.id).filter(Orden.sucursal_id == suc_id)
    pagos_hoy = pago_q.group_by(Pago.metodo).all()

    propinas_q = db.session.query(func.sum(Orden.propina)).filter(
        Orden.estado == 'pagada', func.date(Orden.fecha_pago) == hoy)
    if suc_id is not None:
        propinas_q = propinas_q.filter(Orden.sucursal_id == suc_id)

    resumen = {
        'total_ventas': float(total),
        'num_ventas': count,
        'ticket_promedio': (float(total) / count) if count else 0,
        'propinas_total': float(propinas_q.scalar() or 0),
        'pagos_por_metodo': pagos_hoy,
    }

    pdf = generar_pdf('pdf/corte_caja.html', fecha=str(hoy), resumen=resumen, now=dt.now())
    if pdf:
        return Response(pdf, mimetype='application/pdf',
                        headers={'Content-Disposition': f'attachment;filename=corte_caja_{hoy}.pdf'})
    flash('Error al generar PDF.', 'danger')
    return redirect(url_for('admin.corte_caja'))


from backend.routes.meseros import meseros_bp
admin_bp.register_blueprint(meseros_bp, url_prefix="/meseros")


# ── Modo Sistema toggle (superadmin only) ──
@admin_bp.route('/toggle-modo', methods=['POST'])
@login_required(roles=['superadmin'])
def toggle_modo():
    """Toggle between modo básico and avanzado."""
    from backend.models.models import ConfiguracionSistema
    current = ConfiguracionSistema.get('modo_sistema', 'basico')
    nuevo = 'basico' if current == 'avanzado' else 'avanzado'
    ConfiguracionSistema.set('modo_sistema', nuevo)
    db.session.commit()
    flash(f'Modo cambiado a {nuevo}.', 'success')
    return redirect(request.referrer or url_for('admin.dashboard'))


# ── Personalización white-label (Fase 9) ──
@admin_bp.route('/personalizacion', methods=['GET', 'POST'])
@login_required(roles=['admin', 'superadmin'])
def personalizacion():
    """Admin panel for restaurant branding customization."""
    from backend.models.models import Sucursal
    import os
    from werkzeug.utils import secure_filename

    sucursal = Sucursal.query.first()
    if not sucursal:
        flash('No hay sucursal configurada. Completa el setup primero.', 'warning')
        return redirect(url_for('admin.dashboard'))

    if request.method == 'POST':
        sucursal.nombre = sanitizar_texto(request.form.get('nombre', '').strip(), 100)
        sucursal.slogan = sanitizar_texto(request.form.get('slogan', '').strip(), 200) or None
        sucursal.color_primario = request.form.get('color_primario', '#C41E3A').strip()
        sucursal.rfc = request.form.get('rfc', '').strip() or None
        sucursal.direccion = sanitizar_texto(request.form.get('direccion', '').strip(), 300) or None
        sucursal.telefono = request.form.get('telefono', '').strip() or None

        # Handle logo upload
        logo = request.files.get('logo')
        if logo and logo.filename:
            ALLOWED = {'png', 'jpg', 'jpeg', 'svg', 'webp'}
            ext = logo.filename.rsplit('.', 1)[-1].lower() if '.' in logo.filename else ''
            if ext in ALLOWED:
                upload_dir = os.path.join(current_app.static_folder, 'uploads', 'logos')
                os.makedirs(upload_dir, exist_ok=True)
                filename = secure_filename(f'logo_{sucursal.id}.{ext}')
                logo.save(os.path.join(upload_dir, filename))
                sucursal.logo_url = url_for('static', filename=f'uploads/logos/{filename}')
            else:
                flash('Formato de imagen no soportado. Usa PNG, JPG, SVG o WebP.', 'warning')

        db.session.commit()
        flash('Personalización guardada exitosamente.', 'success')
        return redirect(url_for('admin.personalizacion'))

    return render_template('admin/personalizacion.html', sucursal=sucursal)
