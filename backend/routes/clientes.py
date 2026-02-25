"""Fase 3 — Item 20: CRM básico (clientes frecuentes)."""
import logging
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from backend.utils import login_required
from backend.extensions import db
from backend.models.models import Cliente, Orden, Sale
from backend.services.sanitizer import sanitizar_texto, sanitizar_rfc, sanitizar_email, sanitizar_telefono
from backend.services.rfc_validator import validar_rfc, normalizar_rfc, obtener_regimenes, obtener_usos_cfdi, CATALOGOS_SAT
from sqlalchemy.orm import joinedload
from sqlalchemy import func

logger = logging.getLogger(__name__)

clientes_bp = Blueprint('clientes', __name__, url_prefix='/admin/clientes')


@clientes_bp.route('/')
@login_required(roles=['admin', 'superadmin'])
def lista_clientes():
    clientes = Cliente.query.order_by(Cliente.nombre).all()
    return render_template('admin/clientes/lista.html', clientes=clientes)


@clientes_bp.route('/nuevo', methods=['GET', 'POST'])
@login_required(roles=['admin', 'superadmin'])
def cliente_nuevo():
    if request.method == 'POST':
        rfc_raw = request.form.get('rfc', '').strip()
        # Validar RFC si se proporcionó
        if rfc_raw:
            rfc_normalizado = normalizar_rfc(rfc_raw)
            rfc_valido, rfc_error = validar_rfc(rfc_normalizado)
            if not rfc_valido:
                flash(f'RFC inválido: {rfc_error}', 'danger')
                return render_template('admin/clientes/form.html',
                                       regimenes=CATALOGOS_SAT.get('regimenes_fiscales', {}),
                                       usos_cfdi=CATALOGOS_SAT.get('usos_cfdi', {}))
        else:
            rfc_normalizado = ''

        regimen = request.form.get('regimen_fiscal', '')
        c = Cliente(
            nombre=sanitizar_texto(request.form['nombre'], 100),
            telefono=sanitizar_telefono(request.form.get('telefono', '')),
            email=sanitizar_email(request.form.get('email', '')),
            rfc=sanitizar_rfc(rfc_normalizado),
            razon_social=sanitizar_texto(request.form.get('razon_social', ''), 200),
            uso_cfdi=request.form.get('uso_cfdi', 'G03'),
            regimen_fiscal=regimen,
            domicilio_fiscal=sanitizar_texto(request.form.get('domicilio_fiscal', ''), 300),
            notas=sanitizar_texto(request.form.get('notas', ''), 500),
        )
        db.session.add(c)
        db.session.commit()
        flash('Cliente creado.', 'success')
        return redirect(url_for('clientes.lista_clientes'))
    return render_template('admin/clientes/form.html',
                           regimenes=CATALOGOS_SAT.get('regimenes_fiscales', {}),
                           usos_cfdi=CATALOGOS_SAT.get('usos_cfdi', {}))


@clientes_bp.route('/<int:id>/editar', methods=['GET', 'POST'])
@login_required(roles=['admin', 'superadmin'])
def cliente_editar(id):
    c = Cliente.query.get_or_404(id)
    if request.method == 'POST':
        rfc_raw = request.form.get('rfc', '').strip()
        if rfc_raw:
            rfc_normalizado = normalizar_rfc(rfc_raw)
            rfc_valido, rfc_error = validar_rfc(rfc_normalizado)
            if not rfc_valido:
                flash(f'RFC inválido: {rfc_error}', 'danger')
                return render_template('admin/clientes/form.html', cliente=c,
                                       regimenes=CATALOGOS_SAT.get('regimenes_fiscales', {}),
                                       usos_cfdi=CATALOGOS_SAT.get('usos_cfdi', {}))
        else:
            rfc_normalizado = ''

        c.nombre = sanitizar_texto(request.form['nombre'], 100)
        c.telefono = sanitizar_telefono(request.form.get('telefono', ''))
        c.email = sanitizar_email(request.form.get('email', ''))
        c.rfc = sanitizar_rfc(rfc_normalizado)
        c.razon_social = sanitizar_texto(request.form.get('razon_social', ''), 200)
        c.uso_cfdi = request.form.get('uso_cfdi', 'G03')
        c.regimen_fiscal = request.form.get('regimen_fiscal', '')
        c.domicilio_fiscal = sanitizar_texto(request.form.get('domicilio_fiscal', ''), 300)
        c.notas = sanitizar_texto(request.form.get('notas', ''), 500)
        db.session.commit()
        flash('Cliente actualizado.', 'success')
        return redirect(url_for('clientes.lista_clientes'))
    return render_template('admin/clientes/form.html', cliente=c,
                           regimenes=CATALOGOS_SAT.get('regimenes_fiscales', {}),
                           usos_cfdi=CATALOGOS_SAT.get('usos_cfdi', {}))


@clientes_bp.route('/<int:id>/perfil')
@login_required(roles=['admin', 'superadmin'])
def perfil_cliente(id):
    c = Cliente.query.get_or_404(id)
    ordenes = Orden.query.filter_by(cliente_id=id).order_by(Orden.tiempo_registro.desc()).limit(20).all()
    return render_template('admin/clientes/perfil.html', cliente=c, ordenes=ordenes)


@clientes_bp.route('/api/buscar')
@login_required(roles=['mesero', 'admin', 'superadmin'])
def buscar_cliente():
    """API para buscar clientes por nombre/teléfono (autocompletado en meseros)."""
    q = sanitizar_texto(request.args.get('q', ''), 100)
    if len(q) < 2:
        return jsonify([])
    # Escape LIKE wildcards to prevent pattern injection
    q_escaped = q.replace('%', '\\%').replace('_', '\\_')
    clientes = Cliente.query.filter(
        db.or_(
            Cliente.nombre.ilike(f'%{q_escaped}%'),
            Cliente.telefono.ilike(f'%{q_escaped}%'),
        )
    ).limit(10).all()
    return jsonify([{
        'id': c.id, 'nombre': c.nombre, 'telefono': c.telefono,
        'visitas': c.visitas, 'total_gastado': float(c.total_gastado or 0),
    } for c in clientes])


@clientes_bp.route('/api/validar_rfc')
@login_required(roles=['mesero', 'admin', 'superadmin'])
def api_validar_rfc():
    """API para validar un RFC en el servidor."""
    rfc = normalizar_rfc(request.args.get('rfc', ''))
    if not rfc:
        return jsonify({'valid': False, 'error': 'RFC es requerido.'})
    valido, error = validar_rfc(rfc)
    return jsonify({'valid': valido, 'error': error, 'rfc': rfc})


@clientes_bp.route('/api/catalogos_sat')
@login_required(roles=['mesero', 'admin', 'superadmin'])
def api_catalogos_sat():
    """API para obtener catálogos SAT filtrados por tipo de RFC."""
    rfc = normalizar_rfc(request.args.get('rfc', ''))
    return jsonify({
        'regimenes': obtener_regimenes(rfc),
        'usos_cfdi': obtener_usos_cfdi(rfc),
    })
