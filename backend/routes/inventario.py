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


def _cantidad(campo, *, positivo=False, obligatorio=True):
    """Lee un número del formulario. Devuelve (Decimal | None, error | None).

    Antes eran `Decimal(request.form[...])` directos: un campo vacío o con texto daba
    un 500, y los negativos pasaban (stock −10, entradas de −30, mermas negativas que
    SUBÍAN el inventario).
    """
    from backend.services.validacion import leer_monto
    crudo = (request.form.get(campo) or '').strip()
    if not crudo:
        return (None, None) if not obligatorio else (None, 'falta')
    valor = leer_monto(crudo, minimo=Decimal('0'))
    if valor is None or (positivo and valor <= 0):
        return None, 'invalido'
    return valor, None


def _ingrediente_del_form(actual=None):
    """Valida nombre y números del ingrediente. Devuelve (datos, errores)."""
    errores = []
    nombre = sanitizar_texto(request.form.get('nombre', ''), 100)
    if not nombre:
        errores.append('Escribe el nombre del ingrediente.')
    else:
        otro = Ingrediente.query.filter(db.func.lower(Ingrediente.nombre) == nombre.lower()).first()
        if otro and (actual is None or otro.id != actual.id):
            errores.append(f'Ya existe un ingrediente llamado "{nombre}".')
    datos = {'nombre': nombre, 'unidad': sanitizar_texto(request.form.get('unidad', ''), 20) or 'pieza'}
    etiquetas = {'stock_actual': 'El stock', 'stock_minimo': 'El stock mínimo',
                 'costo_unitario': 'El costo'}
    for campo, etiqueta in etiquetas.items():
        if actual is not None and campo == 'stock_actual':
            continue  # el stock se mueve con entradas y mermas, no editando
        valor, error = _cantidad(campo, obligatorio=False)
        if error:
            errores.append(f'{etiqueta} debe ser un número de 0 en adelante.')
        datos[campo] = valor if valor is not None else Decimal('0')
    return datos, errores


@inventario_bp.route('/ingrediente/nuevo', methods=['GET', 'POST'])
@login_required(roles=['admin', 'superadmin'])
def ingrediente_nuevo():
    if request.method == 'POST':
        datos, errores = _ingrediente_del_form()
        if errores:
            for err in errores:
                flash(err, 'danger')
            return render_template('admin/inventario/ingrediente_form.html')
        i = Ingrediente(sucursal_id=getattr(g, 'sucursal_id', None), **datos)
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
        datos, errores = _ingrediente_del_form(actual=i)
        if errores:
            for err in errores:
                flash(err, 'danger')
            return render_template('admin/inventario/ingrediente_form.html', ingrediente=i)
        for campo, valor in datos.items():
            setattr(i, campo, valor)
        db.session.commit()
        flash('Ingrediente actualizado.', 'success')
        return redirect(url_for('inventario.lista_ingredientes'))
    return render_template('admin/inventario/ingrediente_form.html', ingrediente=i)


def _ingrediente_elegido():
    """El ingrediente del select, o None si falta / no existe (antes: 500 o 404)."""
    try:
        ing_id = int(request.form.get('ingrediente_id', ''))
    except ValueError:
        return None
    return db.session.get(Ingrediente, ing_id)


# =====================================================================
# Entradas de stock
# =====================================================================
@inventario_bp.route('/entrada', methods=['GET', 'POST'])
@login_required(roles=['admin', 'superadmin'])
def entrada_stock():
    if request.method == 'POST':
        ing = _ingrediente_elegido()
        if ing is None:
            flash('Elige un ingrediente.', 'danger')
            return redirect(url_for('inventario.entrada_stock'))
        cantidad, err_cant = _cantidad('cantidad', positivo=True)
        costo, err_costo = _cantidad('costo', obligatorio=False)
        if err_cant or err_costo:
            flash('La cantidad debe ser mayor a 0 y el costo un número de 0 en adelante.', 'danger')
            return redirect(url_for('inventario.entrada_stock'))
        costo = costo or Decimal('0')

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
        ing = _ingrediente_elegido()
        if ing is None:
            flash('Elige un ingrediente.', 'danger')
            return redirect(url_for('inventario.registrar_merma'))
        cantidad, err_cant = _cantidad('cantidad', positivo=True)
        if err_cant:
            flash('La cantidad de merma debe ser mayor a 0.', 'danger')
            return redirect(url_for('inventario.registrar_merma'))
        # Una merma mayor a lo que hay se recortaba a 0 sin avisar: casi siempre es
        # un error de captura (kg vs g) y borraba el inventario
        if cantidad > (ing.stock_actual or 0):
            flash(f'Sólo hay {float(ing.stock_actual or 0):g} {ing.unidad} de {ing.nombre}: '
                  'revisa la cantidad de merma.', 'danger')
            return redirect(url_for('inventario.registrar_merma'))
        motivo = sanitizar_texto(request.form.get('motivo', 'Merma'), 200)

        ing.stock_actual = ing.stock_actual - cantidad
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
