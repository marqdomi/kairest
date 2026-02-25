import logging
from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from flask_login import login_user, logout_user
from werkzeug.security import generate_password_hash, check_password_hash
from backend.models.models import Usuario

logger = logging.getLogger(__name__)

auth_bp = Blueprint('auth', __name__)

# Dummy hash — se usa para mantener timing constante cuando el usuario no existe
_DUMMY_HASH = generate_password_hash('dummy_constant_time_password')


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '')

        usuario = Usuario.query.filter_by(email=email).first()

        # Siempre ejecuta check_password para evitar timing attacks
        if usuario:
            valid = usuario.check_password(password)
        else:
            # Consume el mismo tiempo que un check real
            check_password_hash(_DUMMY_HASH, password)
            valid = False

        if valid:
            login_user(usuario)
            session['user_id'] = usuario.id
            session['rol'] = usuario.rol
            logger.info('Login exitoso: usuario_id=%s rol=%s', usuario.id, usuario.rol)
            # Auditoría
            from backend.services.audit import registrar_auditoria
            registrar_auditoria('login', 'Usuario', usuario.id,
                                f'Login exitoso: {usuario.email}', usuario.id)
            flash('Inicio de sesión exitoso', 'success')

            # Store estacion_id in session for cocina users
            if usuario.estacion_id:
                session['estacion_id'] = usuario.estacion_id

            if usuario.rol in ('superadmin', 'admin'):
                return redirect(url_for('admin.crear_usuario'))
            elif usuario.rol == 'mesero':
                return redirect(url_for('meseros.view_meseros'))
            elif usuario.rol == 'cocina' or usuario.es_cocina:
                return redirect(url_for('cocina.index'))
            return redirect(url_for('auth.login'))
        else:
            # Mensaje genérico — no revela si el email existe o no
            logger.warning('Login fallido: ip=%s', request.remote_addr)
            flash('Credenciales inválidas', 'danger')

    return render_template('login.html')


@auth_bp.route('/logout')
def logout():
    user_id = session.get('user_id')
    # Auditoría antes de limpiar sesión
    from backend.services.audit import registrar_auditoria
    registrar_auditoria('logout', 'Usuario', user_id, 'Cierre de sesión', user_id)
    from backend.extensions import db
    db.session.commit()
    logout_user()  # Clean Flask-Login state + remember cookie
    session.clear()
    logger.info('Logout: usuario_id=%s', user_id)
    flash('Sesión cerrada', 'info')
    return redirect(url_for('auth.login'))
