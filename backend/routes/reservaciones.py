"""Fase 3 — Item 19: Reservaciones y estados de mesa avanzados."""
import logging
from datetime import datetime, date, timedelta
from backend.models.models import utc_now
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, session
from backend.utils import login_required, filtrar_por_sucursal
from backend.extensions import db
from backend.services.sanitizer import sanitizar_texto, sanitizar_telefono
from backend.models.models import Reservacion, Mesa, Cliente
from sqlalchemy.orm import joinedload

RESERVACION_DURACION_HORAS = 2  # assumed duration window for overlap detection

logger = logging.getLogger(__name__)

reservaciones_bp = Blueprint('reservaciones', __name__, url_prefix='/admin/reservaciones')


@reservaciones_bp.route('/')
@login_required(roles=['admin', 'superadmin', 'mesero'])
def lista_reservaciones():
    hoy = date.today()
    filtro = request.args.get('fecha', hoy.isoformat())
    fecha_filtro = date.fromisoformat(filtro)

    reservaciones = Reservacion.query.options(
        joinedload(Reservacion.mesa),
    ).filter(
        db.func.date(Reservacion.fecha_hora) == fecha_filtro,
    ).order_by(Reservacion.fecha_hora).all()

    return render_template('admin/reservaciones/lista.html',
                           reservaciones=reservaciones, fecha_filtro=fecha_filtro)


@reservaciones_bp.route('/nueva', methods=['GET', 'POST'])
@login_required(roles=['admin', 'superadmin', 'mesero'])
def nueva_reservacion():
    if request.method == 'POST':
        fecha_hora_str = request.form['fecha_hora']
        try:
            fecha_hora = datetime.fromisoformat(fecha_hora_str)
        except ValueError:
            flash('Fecha/hora inválida.', 'danger')
            return redirect(url_for('reservaciones.nueva_reservacion'))

        mesa_id = request.form.get('mesa_id') or None
        cliente_id = request.form.get('cliente_id') or None

        # Overlap detection: check for existing non-cancelled reservations on same mesa
        if mesa_id:
            ventana = timedelta(hours=RESERVACION_DURACION_HORAS)
            conflicto = Reservacion.query.filter(
                Reservacion.mesa_id == int(mesa_id),
                Reservacion.estado.in_(['confirmada']),
                Reservacion.fecha_hora.between(fecha_hora - ventana, fecha_hora + ventana),
            ).first()
            if conflicto:
                flash(f'La mesa ya tiene reservación a las {conflicto.fecha_hora.strftime("%H:%M")} '
                      f'({conflicto.nombre_contacto}). Elige otra mesa u horario.', 'danger')
                return redirect(url_for('reservaciones.nueva_reservacion'))

        r = Reservacion(
            mesa_id=int(mesa_id) if mesa_id else None,
            cliente_id=int(cliente_id) if cliente_id else None,
            nombre_contacto=sanitizar_texto(request.form['nombre_contacto'], 100),
            telefono=sanitizar_telefono(request.form.get('telefono', '')),
            fecha_hora=fecha_hora,
            num_personas=int(request.form.get('num_personas', 2)),
            estado='confirmada',
            notas=sanitizar_texto(request.form.get('notas', ''), 500),
            creada_por=session.get('user_id'),
        )
        db.session.add(r)

        # Only mark mesa as 'reservada' if the reservation is within the next 2 hours (same-day)
        if mesa_id:
            mesa = db.session.get(Mesa, int(mesa_id))
            if mesa and mesa.estado == 'disponible':
                now = utc_now()
                if fecha_hora <= now + timedelta(hours=RESERVACION_DURACION_HORAS):
                    mesa.estado = 'reservada'

        db.session.commit()
        flash('Reservación creada.', 'success')
        return redirect(url_for('reservaciones.lista_reservaciones'))

    mesas = filtrar_por_sucursal(Mesa.query, Mesa).order_by(Mesa.numero).all()
    clientes = Cliente.query.order_by(Cliente.nombre).all()
    return render_template('admin/reservaciones/form.html', mesas=mesas, clientes=clientes)


@reservaciones_bp.route('/<int:id>/cancelar', methods=['POST'])
@login_required(roles=['admin', 'superadmin'])
def cancelar_reservacion(id):
    r = db.get_or_404(Reservacion, id)
    r.estado = 'cancelada'
    # Liberar mesa
    if r.mesa_id:
        mesa = db.session.get(Mesa, r.mesa_id)
        if mesa and mesa.estado == 'reservada':
            mesa.estado = 'disponible'
    db.session.commit()
    flash('Reservación cancelada.', 'info')
    return redirect(url_for('reservaciones.lista_reservaciones'))


@reservaciones_bp.route('/<int:id>/completar', methods=['POST'])
@login_required(roles=['admin', 'superadmin', 'mesero'])
def completar_reservacion(id):
    r = db.get_or_404(Reservacion, id)
    r.estado = 'completada'
    if r.mesa_id:
        mesa = db.session.get(Mesa, r.mesa_id)
        if mesa:
            mesa.estado = 'ocupada'
    db.session.commit()
    flash('Reservación completada. Mesa ocupada.', 'success')
    return redirect(url_for('reservaciones.lista_reservaciones'))


# =====================================================================
# Mapa visual de mesas (API JSON)
# =====================================================================
@reservaciones_bp.route('/api/mesas')
@login_required(roles=['admin', 'superadmin', 'mesero'])
def api_mesas_estado():
    mesas = filtrar_por_sucursal(Mesa.query, Mesa).order_by(Mesa.numero).all()
    return jsonify([{
        'id': m.id,
        'numero': m.numero,
        'capacidad': m.capacidad,
        'estado': m.estado,
        'zona': m.zona,
        'pos_x': m.pos_x,
        'pos_y': m.pos_y,
    } for m in mesas])


@reservaciones_bp.route('/api/mesas/<int:id>/estado', methods=['POST'])
@login_required(roles=['admin', 'superadmin', 'mesero'])
def api_cambiar_estado_mesa(id):
    mesa = db.get_or_404(Mesa, id)
    data = request.get_json()
    nuevo_estado = data.get('estado')
    if nuevo_estado not in ('disponible', 'ocupada', 'reservada', 'mantenimiento'):
        return jsonify(success=False, message='Estado inválido.'), 400
    mesa.estado = nuevo_estado
    db.session.commit()
    return jsonify(success=True, estado=mesa.estado)
