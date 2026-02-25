from flask import Blueprint, render_template, redirect, url_for, flash, request
from backend.models.models import Producto, Estacion, Categoria
from backend.extensions import db
from backend.forms.producto_form import ProductoForm
from backend.utils import login_required
from backend.services.sanitizer import sanitizar_texto

productos_bp = Blueprint('productos', __name__, url_prefix='/admin/productos')


def _populate_form_choices(form):
    """Fill categoria_id and estacion_id choices from the database."""
    form.categoria_id.choices = [
        (c.id, c.nombre) for c in Categoria.query.order_by(Categoria.nombre).all()
    ]
    form.estacion_id.choices = [
        (e.id, e.nombre.title()) for e in Estacion.query.order_by(Estacion.nombre).all()
    ]


@productos_bp.route('/', methods=['GET'])
@login_required(roles=['admin','superadmin'])
def listar_productos():
    productos = Producto.query.order_by(Producto.nombre).all()
    return render_template('productos/list.html', productos=productos)

@productos_bp.route('/crear', methods=['GET','POST'])
@login_required(roles=['admin','superadmin'])
def crear_producto():
    form = ProductoForm()
    _populate_form_choices(form)
    if form.validate_on_submit():
        p = Producto(
            nombre=sanitizar_texto(form.nombre.data, 100),
            precio=form.precio.data,
            categoria_id=form.categoria_id.data,
            estacion_id=form.estacion_id.data,
            unidad=sanitizar_texto(form.unidad.data, 30) if form.unidad.data else None,
            descripcion=sanitizar_texto(form.descripcion.data, 500) if form.descripcion.data else None,
        )
        db.session.add(p); db.session.commit()
        flash('Producto creado con éxito', 'success')
        return redirect(url_for('productos.listar_productos'))
    return render_template('productos/form.html', form=form, titulo='Crear Producto')

@productos_bp.route('/<int:id>/editar', methods=['GET','POST'])
@login_required(roles=['admin','superadmin'])
def editar_producto(id):
    p = Producto.query.get_or_404(id)
    form = ProductoForm(obj=p)
    _populate_form_choices(form)
    if form.validate_on_submit():
        p.nombre = sanitizar_texto(form.nombre.data, 100)
        p.precio = form.precio.data
        p.categoria_id = form.categoria_id.data
        p.estacion_id = form.estacion_id.data
        p.unidad = sanitizar_texto(form.unidad.data, 30) if form.unidad.data else None
        p.descripcion = sanitizar_texto(form.descripcion.data, 500) if form.descripcion.data else None
        db.session.commit()
        flash('Producto actualizado', 'success')
        return redirect(url_for('productos.listar_productos'))
    return render_template('productos/form.html', form=form, titulo='Editar Producto')

@productos_bp.route('/<int:id>/eliminar', methods=['POST'])
@login_required(roles=['superadmin'])
def eliminar_producto(id):
    from backend.models.models import OrdenDetalle
    p = Producto.query.get_or_404(id)
    refs = OrdenDetalle.query.filter_by(producto_id=p.id).count()
    if refs:
        flash(f'No se puede eliminar: tiene {refs} detalle(s) de orden asociados.', 'danger')
        return redirect(url_for('productos.listar_productos'))
    db.session.delete(p); db.session.commit()
    flash('Producto eliminado', 'warning')
    return redirect(url_for('productos.listar_productos'))