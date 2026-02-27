"""Sprint 3 — Items 7.1, 7.2, 7.4: Rutas de facturación CFDI completas."""
import logging
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, Response
from backend.utils import login_required
from backend.extensions import db
from backend.models.models import Factura, Orden, Cliente, NotaCredito
from backend.services.cfdi import (
    crear_factura_cfdi, cancelar_factura_cfdi,
    descargar_xml, descargar_pdf, reenviar_email, crear_nota_credito,
    crear_complemento_pago,
)
from backend.services.rfc_validator import (
    validar_rfc, normalizar_rfc, obtener_regimenes, obtener_usos_cfdi, CATALOGOS_SAT,
)
from sqlalchemy.orm import joinedload

logger = logging.getLogger(__name__)

facturacion_bp = Blueprint('facturacion', __name__, url_prefix='/admin/facturacion')


@facturacion_bp.route('/')
@login_required(roles=['admin', 'superadmin'])
def lista_facturas():
    facturas = Factura.query.options(
        joinedload(Factura.orden),
        joinedload(Factura.cliente),
    ).order_by(Factura.fecha_creacion.desc()).all()
    return render_template('admin/facturacion/lista.html', facturas=facturas)


@facturacion_bp.route('/crear/<int:orden_id>', methods=['GET', 'POST'])
@login_required(roles=['admin', 'superadmin'])
def crear_factura(orden_id):
    from backend.models.models import OrdenDetalle
    orden = db.get_or_404(Orden, orden_id, options=[
        joinedload(Orden.detalles).joinedload(OrdenDetalle.producto),
    ])

    if request.method == 'POST':
        cliente_id = request.form.get('cliente_id')

        # Validar RFC del receptor
        rfc_raw = normalizar_rfc(request.form.get('rfc', ''))
        if rfc_raw:
            rfc_valido, rfc_error = validar_rfc(rfc_raw)
            if not rfc_valido:
                flash(f'RFC inválido: {rfc_error}', 'danger')
                clientes = Cliente.query.order_by(Cliente.nombre).all()
                return render_template('admin/facturacion/crear.html',
                                       orden=orden, clientes=clientes,
                                       regimenes=CATALOGOS_SAT.get('regimenes_fiscales', {}),
                                       usos_cfdi=CATALOGOS_SAT.get('usos_cfdi', {}))

        if not cliente_id:
            # Crear cliente nuevo inline
            cliente = Cliente(
                nombre=request.form['razon_social'],
                rfc=rfc_raw or 'XAXX010101000',
                razon_social=request.form['razon_social'],
                uso_cfdi=request.form.get('uso_cfdi', 'G03'),
                regimen_fiscal=request.form.get('regimen_fiscal', '616'),
                domicilio_fiscal=request.form.get('domicilio_fiscal', ''),
            )
            db.session.add(cliente)
            db.session.flush()
        else:
            cliente = db.get_or_404(Cliente, int(cliente_id))

        factura = crear_factura_cfdi(orden, cliente, db.session,
                                    metodo_pago=request.form.get('metodo_pago', 'PUE'))
        # Auditoría (Sprint 6 — 3.5)
        from backend.services.audit import registrar_auditoria
        registrar_auditoria('crear', 'Factura', factura.id,
                            f'Factura creada para orden #{orden.id}, estado={factura.estado}')
        db.session.commit()
        if factura.estado == 'timbrada':
            flash(f'Factura timbrada exitosamente. UUID: {factura.uuid_cfdi}', 'success')
        elif factura.estado == 'error':
            flash(f'Error al timbrar: {factura.pac_response}', 'danger')
        else:
            flash('Factura registrada como pendiente (PAC no configurado).', 'info')
        return redirect(url_for('facturacion.lista_facturas'))

    clientes = Cliente.query.order_by(Cliente.nombre).all()
    return render_template('admin/facturacion/crear.html',
                           orden=orden, clientes=clientes,
                           regimenes=CATALOGOS_SAT.get('regimenes_fiscales', {}),
                           usos_cfdi=CATALOGOS_SAT.get('usos_cfdi', {}))


@facturacion_bp.route('/<int:factura_id>')
@login_required(roles=['admin', 'superadmin'])
def detalle_factura(factura_id):
    """Detalle de una factura con sus notas de crédito."""
    factura = db.get_or_404(Factura, factura_id, options=[
        joinedload(Factura.orden),
        joinedload(Factura.cliente),
        joinedload(Factura.notas_credito),
    ])
    return render_template('admin/facturacion/detalle.html', factura=factura)


@facturacion_bp.route('/<int:factura_id>/cancelar', methods=['POST'])
@login_required(roles=['superadmin'])
def cancelar(factura_id):
    factura = db.get_or_404(Factura, factura_id)
    motivo = request.form.get('motivo_cancelacion', '02')
    ok = cancelar_factura_cfdi(factura, db.session, motivo=motivo)
    # Auditoría (Sprint 6 — 3.5)
    from backend.services.audit import registrar_auditoria
    registrar_auditoria('cancelar', 'Factura', factura_id,
                        f'Cancelación factura UUID={factura.uuid_cfdi}, motivo={motivo}')
    db.session.commit()
    if ok:
        flash('Factura cancelada.', 'info')
    else:
        flash(f'Error al cancelar factura: {factura.pac_response}', 'danger')
    return redirect(url_for('facturacion.lista_facturas'))


@facturacion_bp.route('/<int:factura_id>/xml')
@login_required(roles=['admin', 'superadmin'])
def download_xml(factura_id):
    """Descarga el XML de la factura."""
    factura = db.get_or_404(Factura, factura_id)
    xml_data = descargar_xml(factura)
    if xml_data:
        return Response(
            xml_data,
            mimetype='application/xml',
            headers={'Content-Disposition': f'attachment; filename=factura_{factura.uuid_cfdi or factura.id}.xml'},
        )
    flash('No se pudo descargar el XML. Verifica la configuración del PAC.', 'warning')
    return redirect(url_for('facturacion.lista_facturas'))


@facturacion_bp.route('/<int:factura_id>/pdf')
@login_required(roles=['admin', 'superadmin'])
def download_pdf(factura_id):
    """Descarga el PDF de la factura."""
    factura = db.get_or_404(Factura, factura_id)
    pdf_data = descargar_pdf(factura)
    if pdf_data:
        return Response(
            pdf_data,
            mimetype='application/pdf',
            headers={'Content-Disposition': f'attachment; filename=factura_{factura.uuid_cfdi or factura.id}.pdf'},
        )
    flash('No se pudo descargar el PDF. Verifica la configuración del PAC.', 'warning')
    return redirect(url_for('facturacion.lista_facturas'))


@facturacion_bp.route('/<int:factura_id>/reenviar', methods=['POST'])
@login_required(roles=['admin', 'superadmin'])
def reenviar(factura_id):
    """Reenvía la factura por email."""
    factura = db.get_or_404(Factura, factura_id, options=[joinedload(Factura.cliente)])
    email = request.form.get('email', '') or (factura.cliente.email if factura.cliente else '')
    if not email:
        flash('No hay email para enviar la factura.', 'warning')
        return redirect(url_for('facturacion.lista_facturas'))

    ok = reenviar_email(factura, email)
    if ok:
        flash(f'Factura reenviada a {email}.', 'success')
    else:
        flash('Error al reenviar la factura.', 'danger')
    return redirect(url_for('facturacion.lista_facturas'))


# -------------------- NOTAS DE CRÉDITO (7.2) --------------------

@facturacion_bp.route('/<int:factura_id>/nota-credito', methods=['GET', 'POST'])
@login_required(roles=['admin', 'superadmin'])
def crear_nota_credito_view(factura_id):
    """Crea una nota de crédito (parcial o total) de una factura."""
    factura = db.get_or_404(Factura, factura_id, options=[
        joinedload(Factura.orden),
        joinedload(Factura.cliente),
    ])

    if factura.estado != 'timbrada':
        flash('Solo se pueden crear notas de crédito de facturas timbradas.', 'warning')
        return redirect(url_for('facturacion.lista_facturas'))

    if request.method == 'POST':
        monto = request.form.get('monto', 0, type=float)
        motivo = request.form.get('motivo', 'Devolución')

        if monto <= 0 or monto > float(factura.total):
            flash('El monto debe ser mayor a 0 y no exceder el total de la factura.', 'danger')
            return render_template('admin/facturacion/nota_credito.html', factura=factura)

        nc = crear_nota_credito(factura, monto, motivo, db.session)
        if nc.estado == 'timbrada':
            flash(f'Nota de crédito timbrada. UUID: {nc.uuid_cfdi}', 'success')
        elif nc.estado == 'error':
            flash(f'Error al timbrar nota de crédito: {nc.pac_response}', 'danger')
        else:
            flash('Nota de crédito registrada como pendiente.', 'info')
        return redirect(url_for('facturacion.detalle_factura', factura_id=factura.id))

    return render_template('admin/facturacion/nota_credito.html', factura=factura)


@facturacion_bp.route('/notas-credito')
@login_required(roles=['admin', 'superadmin'])
def lista_notas_credito():
    """Lista todas las notas de crédito."""
    notas = NotaCredito.query.options(
        joinedload(NotaCredito.factura_origen),
    ).order_by(NotaCredito.fecha_creacion.desc()).all()
    return render_template('admin/facturacion/notas_credito.html', notas=notas)


# -------------------- COMPLEMENTO DE PAGO (Sprint 6 — 7.3) --------------------

@facturacion_bp.route('/<int:factura_id>/complemento-pago', methods=['GET', 'POST'])
@login_required(roles=['admin', 'superadmin'])
def complemento_pago(factura_id):
    """Registra un complemento de pago CFDI tipo P para facturas PPD."""
    factura = db.get_or_404(Factura, factura_id, options=[
        joinedload(Factura.orden),
        joinedload(Factura.cliente),
    ])

    if factura.metodo_pago_cfdi != 'PPD':
        flash('Solo facturas con método de pago PPD requieren complemento.', 'warning')
        return redirect(url_for('facturacion.detalle_factura', factura_id=factura.id))

    formas_pago = CATALOGOS_SAT.get('formas_pago', {
        '01': 'Efectivo', '03': 'Transferencia electrónica', '04': 'Tarjeta de crédito',
        '28': 'Tarjeta de débito', '06': 'Dinero electrónico',
    })

    if request.method == 'POST':
        monto_pago = request.form.get('monto', 0, type=float)
        forma_pago_real = request.form.get('forma_pago', '01')

        if monto_pago <= 0 or monto_pago > float(factura.total):
            flash('El monto debe ser mayor a 0 y no exceder el total de la factura.', 'danger')
            return render_template('admin/facturacion/complemento_pago.html',
                                   factura=factura, formas_pago=formas_pago)

        resultado = crear_complemento_pago(factura, monto_pago, forma_pago_real, db.session)

        # Auditoría
        from backend.services.audit import registrar_auditoria
        registrar_auditoria('complemento_pago', 'Factura', factura.id,
                            f'Complemento de pago ${monto_pago:.2f}, forma={forma_pago_real}')
        db.session.commit()

        if resultado.get('success'):
            flash(resultado['message'], 'success')
        else:
            flash(resultado['message'], 'danger' if 'Error' in resultado['message'] else 'info')

        return redirect(url_for('facturacion.detalle_factura', factura_id=factura.id))

    return render_template('admin/facturacion/complemento_pago.html',
                           factura=factura, formas_pago=formas_pago)
