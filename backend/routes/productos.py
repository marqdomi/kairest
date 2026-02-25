from flask import Blueprint, render_template, redirect, url_for, flash, request
from backend.models.models import Producto, Estacion
from backend.extensions import db
from backend.forms.producto_form import ProductoForm
from backend.utils import login_required

productos_bp = Blueprint('productos', __name__, url_prefix='/admin/productos')

@productos_bp.route('/', methods=['GET'])
@login_required(roles=['admin','superadmin'])
def listar_productos():
    productos = Producto.query.order_by(Producto.nombre).all()
    return render_template('productos/list.html', productos=productos)

@productos_bp.route('/crear', methods=['GET','POST'])
@login_required(roles=['admin','superadmin'])
def crear_producto():
    form = ProductoForm()
    form.estacion.choices = [(e.nombre, e.nombre.title()) for e in Estacion.query.order_by(Estacion.nombre).all()]
    if form.validate_on_submit():
        p = Producto(
            nombre=form.nombre.data,
            precio_unitario=form.precio_unitario.data,
            categoria=form.categoria.data,
            estacion=form.estacion.data
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
    form.estacion.choices = [(e.nombre, e.nombre.title()) for e in Estacion.query.order_by(Estacion.nombre).all()]
    if form.validate_on_submit():
        form.populate_obj(p)
        db.session.commit()
        flash('Producto actualizado', 'success')
        return redirect(url_for('productos.listar_productos'))
    return render_template('productos/form.html', form=form, titulo='Editar Producto')

@productos_bp.route('/<int:id>/eliminar', methods=['POST'])
@login_required(roles=['superadmin'])  # quizá solo superadmin puede borrar
def eliminar_producto(id):
    p = Producto.query.get_or_404(id)
    db.session.delete(p); db.session.commit()
    flash('Producto eliminado', 'warning')
    return redirect(url_for('productos.listar_productos'))