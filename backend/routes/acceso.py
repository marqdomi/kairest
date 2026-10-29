"""Acceso rápido: PIN en dispositivos autorizados + vinculación con código.

Va en su propio blueprint para tener su propio límite de peticiones: el de `auth`
(10/min por IP) castigaría a todas las tablets del puesto juntas, que con Docker
Desktop llegan con la misma IP. El PIN se limita por dispositivo y el bloqueo real
es por persona (services/acceso.py).
"""
import logging

from flask import Blueprint, flash, jsonify, make_response, redirect, render_template, request, session, url_for

from backend.extensions import db
from backend.models.models import DispositivoAutorizado, Usuario, utc_now
from backend.services import acceso
from backend.services.audit import registrar_auditoria
from backend.services.sanitizer import sanitizar_texto
from backend.services.sesion import destino, iniciar_sesion
from backend.utils import login_required

logger = logging.getLogger(__name__)

acceso_bp = Blueprint('acceso', __name__)


def clave_dispositivo():
    """Llave del rate limit del PIN: el dispositivo, no la IP."""
    from flask_limiter.util import get_remote_address
    return request.cookies.get(acceso.COOKIE_DISPOSITIVO) or get_remote_address()


# ── PIN ──

@acceso_bp.route('/acceso/pin', methods=['POST'])
def entrar_con_pin():
    dispositivo = acceso.dispositivo_actual()
    if not dispositivo:
        return jsonify({'error': 'Este aparato no está autorizado para entrar con PIN.'}), 403

    data = request.get_json(silent=True) or {}
    from backend.services.validacion import leer_entero
    usuario_id = leer_entero(data.get('usuario_id'), 1, 2**31 - 1)  # texto → 500 antes
    usuario = db.session.get(Usuario, usuario_id) if usuario_id else None
    if not usuario or not usuario.usa_pin or not usuario.pin_hash:
        return jsonify({'error': 'Usuario no disponible.'}), 404

    ok, motivo = acceso.verificar_pin(usuario, str(data.get('pin') or ''))
    if not ok:
        db.session.commit()  # guarda el conteo de fallos / el bloqueo
        if motivo == 'bloqueado':
            return jsonify({'error': 'Demasiados intentos. Espera 5 minutos o pide a la dueña que te desbloquee.',
                            'bloqueado': True}), 423
        restantes = acceso.intentos_restantes(usuario)
        return jsonify({'error': 'PIN incorrecto.', 'restantes': restantes}), 401

    dispositivo.ultimo_uso = utc_now().replace(tzinfo=None)
    iniciar_sesion(usuario, metodo='pin')
    registrar_auditoria('login', 'Usuario', usuario.id,
                        f'Login con PIN: {usuario.identificador} en "{dispositivo.nombre}"', usuario.id)
    db.session.commit()
    logger.info('Login PIN: usuario_id=%s dispositivo=%s', usuario.id, dispositivo.id)
    return jsonify({'ok': True, 'redirect': destino(usuario)})


# ── Vincular este aparato con el código de la dueña ──

@acceso_bp.route('/vincular', methods=['GET', 'POST'])
def vincular():
    if request.method == 'POST':
        codigo = request.form.get('codigo', '')
        nombre = sanitizar_texto(request.form.get('nombre', ''), 60) or 'Dispositivo'
        ok, autorizador_id, mensaje = acceso.canjear_codigo(codigo)
        if not ok:
            db.session.commit()  # guarda el conteo de intentos del código
            flash(mensaje, 'danger')
            return render_template('vincular.html', nombre=nombre), 400
        autorizador = db.session.get(Usuario, autorizador_id) if autorizador_id else None
        disp, token = acceso.autorizar(nombre, usuario_id=autorizador_id,
                                       sucursal_id=autorizador.sucursal_id if autorizador else None)
        db.session.flush()
        registrar_auditoria('autorizar', 'Dispositivo', disp.id,
                            f'Dispositivo vinculado con código: "{disp.nombre}"', autorizador_id)
        db.session.commit()
        flash(f'Listo: "{disp.nombre}" ya puede entrar con PIN.', 'success')
        return acceso.poner_cookie(make_response(redirect(url_for('auth.login'))), token)
    return render_template('vincular.html', nombre='')


# ── Administración (dueña / admin) ──

@acceso_bp.route('/admin/dispositivos')
@login_required(roles=['admin', 'superadmin'])
def lista_dispositivos():
    dispositivos = DispositivoAutorizado.query.order_by(
        DispositivoAutorizado.activo.desc(), DispositivoAutorizado.creado.desc()).all()
    actual = acceso.dispositivo_actual()
    return render_template('admin/dispositivos.html', dispositivos=dispositivos,
                           actual_id=actual.id if actual else None,
                           codigo=session.pop('codigo_enlace', None),
                           segundos=acceso.codigo_vigente())


@acceso_bp.route('/admin/dispositivos/codigo', methods=['POST'])
@login_required(roles=['admin', 'superadmin'])
def generar_codigo():
    codigo = acceso.crear_codigo(session.get('user_id'))
    registrar_auditoria('codigo_enlace', 'Dispositivo', None, 'Código de vinculación generado')
    db.session.commit()
    # Se muestra una sola vez (no queda en la URL ni en el historial)
    session['codigo_enlace'] = codigo
    return redirect(url_for('acceso.lista_dispositivos'))


@acceso_bp.route('/admin/dispositivos/este', methods=['POST'])
@login_required(roles=['admin', 'superadmin'])
def autorizar_este():
    """La dueña ya está aquí con su contraseña: autoriza este mismo aparato sin código."""
    nombre = sanitizar_texto(request.form.get('nombre', ''), 60) or 'Dispositivo'
    usuario = db.session.get(Usuario, session.get('user_id'))
    disp, token = acceso.autorizar(nombre, usuario_id=usuario.id, sucursal_id=usuario.sucursal_id)
    db.session.flush()
    registrar_auditoria('autorizar', 'Dispositivo', disp.id, f'Dispositivo autorizado: "{disp.nombre}"')
    db.session.commit()
    flash(f'"{disp.nombre}" quedó autorizado para entrar con PIN.', 'success')
    return acceso.poner_cookie(make_response(redirect(url_for('acceso.lista_dispositivos'))), token)


@acceso_bp.route('/admin/dispositivos/<int:id>/desautorizar', methods=['POST'])
@login_required(roles=['admin', 'superadmin'])
def desautorizar(id):
    disp = db.get_or_404(DispositivoAutorizado, id)
    disp.activo = False
    registrar_auditoria('desautorizar', 'Dispositivo', disp.id, f'Dispositivo desautorizado: "{disp.nombre}"')
    db.session.commit()
    flash(f'"{disp.nombre}" ya no puede entrar con PIN.', 'info')
    return redirect(url_for('acceso.lista_dispositivos'))
