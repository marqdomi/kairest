"""Fase 3 — Item 15: Módulo de inventario con receta estándar."""
import logging
from decimal import Decimal
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, session, g
from backend.utils import login_required, filtrar_por_sucursal
from backend.extensions import db
from backend.models.models import (
    Ingrediente, RecetaDetalle, MovimientoInventario, Producto,
)
from backend.services.sanitizer import sanitizar_texto
from sqlalchemy.orm import joinedload

logger = logging.getLogger(__name__)

inventario_bp = Blueprint('inventario', __name__, url_prefix='/admin/inventario')


# =====================================================================
# Ingredientes CRUD
# =====================================================================
@inventario_bp.route('/')
@login_required(roles=['admin', 'superadmin'])
def lista_ingredientes():
    query = filtrar_por_sucursal(
        Ingrediente.query.filter_by(activo=True), Ingrediente,
    )
    ingredientes = query.order_by(Ingrediente.nombre).all()
    alertas = [i for i in ingredientes if i.stock_actual <= i.stock_minimo]
    return render_template('admin/inventario/ingredientes.html',
                           ingredientes=ingredientes, alertas=alertas)


@inventario_bp.route('/ingrediente/nuevo', methods=['GET', 'POST'])
@login_required(roles=['admin', 'superadmin'])
def ingrediente_nuevo():
    if request.method == 'POST':
        i = Ingrediente(
            nombre=sanitizar_texto(request.form['nombre'], 100),
            unidad=sanitizar_texto(request.form['unidad'], 20),
            stock_actual=Decimal(request.form.get('stock_actual', '0')),
            stock_minimo=Decimal(request.form.get('stock_minimo', '0')),
            costo_unitario=Decimal(request.form.get('costo_unitario', '0')),
            sucursal_id=getattr(g, 'sucursal_id', None),
        )
        db.session.add(i)
        db.session.commit()
        flash('Ingrediente creado.', 'success')
        return redirect(url_for('inventario.lista_ingredientes'))
    return render_template('admin/inventario/ingrediente_form.html')


@inventario_bp.route('/ingrediente/<int:id>/editar', methods=['GET', 'POST'])
@login_required(roles=['admin', 'superadmin'])
def ingrediente_editar(id):
    i = db.get_or_404(Ingrediente, id)
    if request.method == 'POST':
        i.nombre = sanitizar_texto(request.form['nombre'], 100)
        i.unidad = sanitizar_texto(request.form['unidad'], 20)
        i.stock_minimo = Decimal(request.form.get('stock_minimo', '0'))
        i.costo_unitario = Decimal(request.form.get('costo_unitario', '0'))
        db.session.commit()
        flash('Ingrediente actualizado.', 'success')
        return redirect(url_for('inventario.lista_ingredientes'))
    return render_template('admin/inventario/ingrediente_form.html', ingrediente=i)


# =====================================================================
# Entradas de stock
# =====================================================================
@inventario_bp.route('/entrada', methods=['GET', 'POST'])
@login_required(roles=['admin', 'superadmin'])
def entrada_stock():
    if request.method == 'POST':
        ing = db.get_or_404(Ingrediente, int(request.form['ingrediente_id']))
        cantidad = Decimal(request.form['cantidad'])
        costo = Decimal(request.form.get('costo', '0'))

        ing.stock_actual += cantidad
        if costo > 0:
            ing.costo_unitario = costo

        mov = MovimientoInventario(
            ingrediente_id=ing.id, tipo='entrada', cantidad=cantidad,
            costo=costo, motivo=sanitizar_texto(request.form.get('motivo', 'Compra'), 200),
            usuario_id=session.get('user_id'),
        )
        db.session.add(mov)
        db.session.commit()
        flash(f'{cantidad} {ing.unidad} de {ing.nombre} registrados.', 'success')
        return redirect(url_for('inventario.lista_ingredientes'))

    ingredientes = filtrar_por_sucursal(
        Ingrediente.query.filter_by(activo=True), Ingrediente,
    ).order_by(Ingrediente.nombre).all()
    return render_template('admin/inventario/entrada_stock.html', ingredientes=ingredientes)


# =====================================================================
# Registrar merma
# =====================================================================
@inventario_bp.route('/merma', methods=['GET', 'POST'])
@login_required(roles=['admin', 'superadmin'])
def registrar_merma():
    if request.method == 'POST':
        ing = db.get_or_404(Ingrediente, int(request.form['ingrediente_id']))
        cantidad = Decimal(request.form['cantidad'])
        motivo = sanitizar_texto(request.form.get('motivo', 'Merma'), 200)

        ing.stock_actual = max(ing.stock_actual - cantidad, Decimal('0'))
        mov = MovimientoInventario(
            ingrediente_id=ing.id, tipo='merma', cantidad=cantidad,
            motivo=motivo, usuario_id=session.get('user_id'),
        )
        db.session.add(mov)
        db.session.commit()
        flash(f'Merma de {cantidad} {ing.unidad} de {ing.nombre} registrada.', 'warning')
        return redirect(url_for('inventario.lista_ingredientes'))

    ingredientes = filtrar_por_sucursal(
        Ingrediente.query.filter_by(activo=True), Ingrediente,
    ).order_by(Ingrediente.nombre).all()
    return render_template('admin/inventario/merma.html', ingredientes=ingredientes)


# =====================================================================
# Recetas: asignar ingredientes a productos
# =====================================================================
@inventario_bp.route('/recetas')
@login_required(roles=['admin', 'superadmin'])
def lista_recetas():
    productos = Producto.query.options(
        joinedload(Producto.receta_items).joinedload(RecetaDetalle.ingrediente),
    ).order_by(Producto.nombre).all()
    return render_template('admin/inventario/recetas.html', productos=productos)


@inventario_bp.route('/recetas/<int:producto_id>', methods=['GET', 'POST'])
@login_required(roles=['admin', 'superadmin'])
def editar_receta(producto_id):
    producto = db.get_or_404(Producto, producto_id, options=[
        joinedload(Producto.receta_items).joinedload(RecetaDetalle.ingrediente),
    ])

    if request.method == 'POST':
        # Recibir JSON con items [{ingrediente_id, cantidad_por_unidad}]
        items = request.get_json()
        if items is None:
            return jsonify(success=False, message='Datos inválidos.'), 400

        # Borrar receta actual y recrear
        RecetaDetalle.query.filter_by(producto_id=producto_id).delete()
        for item in items:
            rd = RecetaDetalle(
                producto_id=producto_id,
                ingrediente_id=int(item['ingrediente_id']),
                cantidad_por_unidad=Decimal(str(item['cantidad_por_unidad'])),
            )
            db.session.add(rd)
        db.session.commit()
        logger.info('Receta actualizada: producto=%s items=%d', producto_id, len(items))
        return jsonify(success=True, message='Receta guardada.')

    ingredientes = filtrar_por_sucursal(
        Ingrediente.query.filter_by(activo=True), Ingrediente,
    ).order_by(Ingrediente.nombre).all()
    return render_template('admin/inventario/receta_form.html',
                           producto=producto, ingredientes=ingredientes)


# =====================================================================
# Movimientos (historial)
# =====================================================================
@inventario_bp.route('/movimientos')
@login_required(roles=['admin', 'superadmin'])
def historial_movimientos():
    page = request.args.get('page', 1, type=int)
    movimientos = MovimientoInventario.query.options(
        joinedload(MovimientoInventario.ingrediente),
        joinedload(MovimientoInventario.usuario),
    ).order_by(MovimientoInventario.fecha.desc()).paginate(page=page, per_page=50)
    return render_template('admin/inventario/movimientos.html', movimientos=movimientos)


# =====================================================================
# API: alertas de stock bajo (para dashboard)
# =====================================================================
@inventario_bp.route('/api/alertas')
@login_required(roles=['admin', 'superadmin'])
def api_alertas_stock():
    alertas = filtrar_por_sucursal(
        Ingrediente.query.filter(
            Ingrediente.activo == True,
            Ingrediente.stock_actual <= Ingrediente.stock_minimo,
        ), Ingrediente,
    ).all()
    return jsonify([{
        'id': a.id, 'nombre': a.nombre, 'unidad': a.unidad,
        'stock_actual': float(a.stock_actual), 'stock_minimo': float(a.stock_minimo),
    } for a in alertas])
