import logging
from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from werkzeug.security import generate_password_hash, check_password_hash

logger = logging.getLogger(__name__)

auth_bp = Blueprint('auth', __name__)

# Dummy hash — se usa para mantener timing constante cuando el usuario no existe
_DUMMY_HASH = generate_password_hash('dummy_constant_time_password')


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    from backend.services import acceso
    from backend.services.sesion import iniciar_sesion, destino

    if request.method == 'POST':
        # El campo se llama `email` por compatibilidad (formularios y tests viejos),
        # pero acepta usuario corto o correo.
        identificador = (request.form.get('usuario') or request.form.get('email') or '').strip()
        password = request.form.get('password', '')

        usuario = acceso.buscar_para_login(identificador)

        # Siempre ejecuta check_password para evitar timing attacks
        if usuario and usuario.password_hash:
            valid = usuario.check_password(password)
        else:
            # Consume el mismo tiempo que un check real
            check_password_hash(_DUMMY_HASH, password)
            valid = False

        if valid:
            iniciar_sesion(usuario, metodo='contrasena')
            logger.info('Login exitoso: usuario_id=%s rol=%s', usuario.id, usuario.rol)
            from backend.services.audit import registrar_auditoria
            registrar_auditoria('login', 'Usuario', usuario.id,
                                f'Login con contraseña: {usuario.identificador}', usuario.id)
            from backend.extensions import db
            db.session.commit()
            return redirect(destino(usuario))
        # Mensaje genérico — no revela si el usuario existe o no
        logger.warning('Login fallido: ip=%s', request.remote_addr)
        flash('Usuario o contraseña incorrectos', 'danger')
        return render_template('login.html', identificador=identificador)

    # En un aparato autorizado el personal entra tocando su nombre + PIN. La dueña
    # (o quien no tenga PIN) usa "Entrar con contraseña" → ?modo=contrasena
    dispositivo = acceso.dispositivo_actual()
    if dispositivo and request.args.get('modo') != 'contrasena':
        from backend.models.models import ConfiguracionSistema
        return render_template(
            'login_pin.html',
            dispositivo=dispositivo,
            personal=acceso.personal_con_pin(dispositivo),
            nombre_negocio=ConfiguracionSistema.get('nombre_negocio', ''),
        )
    return render_template('login.html', identificador='', dispositivo=dispositivo)


@auth_bp.route('/logout', methods=['POST'])
def logout():
    user_id = session.get('user_id')
    # Auditoría antes de limpiar sesión (null-safe)
    if user_id:
        from backend.services.audit import registrar_auditoria
        registrar_auditoria('logout', 'Usuario', user_id, 'Cierre de sesión', user_id)
        from backend.extensions import db
        db.session.commit()
    from backend.services.sesion import cerrar_sesion
    cerrar_sesion()
    logger.info('Logout: usuario_id=%s', user_id)
    flash('Sesión cerrada', 'info')
    return redirect(url_for('auth.login'))
