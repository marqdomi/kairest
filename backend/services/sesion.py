"""Inicio de sesión y vigencia por rol.

Toda la autorización del sistema lee `session['user_id']`, `session['rol']` y
`session['estacion_id']` (unos 40 lugares), no sólo Flask-Login. Por eso los dos
caminos de entrada — contraseña y PIN — pasan por `iniciar_sesion()`: si uno de los
dos llenara las llaves distinto, ese usuario vería pantallas a medias.

Vigencia: la sesión vence tras N horas SIN USO (se renueva con cada petición), con N
según el rol. Antes la cookie no tenía fecha de expiración y moría al cerrar el
navegador: en celulares de gama baja, que matan la app en segundo plano, el mesero
volvía a teclear todo a media jornada.
"""
import time
from datetime import timedelta

from flask import session
from flask_login import login_user, logout_user

# Horas sin uso antes de pedir de nuevo el acceso
VIGENCIA_POR_ROL = {
    'cocina': 30 * 24,      # tablet fija del KDS
    'mesero': 16,           # un turno; al día siguiente, PIN
    'admin': 7 * 24,
    'superadmin': 7 * 24,
}
VIGENCIA_DEFAULT = 16
# Tope de la cookie / registro en Redis: la mayor de las vigencias
VIGENCIA_MAXIMA = timedelta(hours=max(VIGENCIA_POR_ROL.values()))


def _horas(rol):
    return VIGENCIA_POR_ROL.get(rol, VIGENCIA_DEFAULT)


def iniciar_sesion(usuario, metodo='contrasena'):
    """Abre la sesión del usuario con las mismas llaves en ambos caminos de entrada."""
    # Sin esto una sesión vieja (otro usuario en la misma tablet) heredaría llaves
    # como `estacion_id` o la sucursal elegida.
    session.clear()
    login_user(usuario)
    session.permanent = True
    session['user_id'] = usuario.id
    session['rol'] = usuario.rol
    if usuario.estacion_id:
        session['estacion_id'] = usuario.estacion_id
    session['metodo_acceso'] = metodo
    renovar()


def renovar():
    """Corre en cada petición con sesión: empuja el vencimiento.

    Sólo reescribe si pasó más de un minuto: el KDS consulta cada pocos segundos y no
    hace falta guardar la sesión en Redis en cada consulta.
    """
    nuevo = int(time.time()) + _horas(session.get('rol')) * 3600
    if nuevo - session.get('vence', 0) > 60:
        session['vence'] = nuevo


def vencida():
    vence = session.get('vence')
    return vence is not None and vence < time.time()


def destino(usuario):
    """Pantalla de cada rol al entrar."""
    from flask import url_for
    if usuario.rol in ('superadmin', 'admin'):
        return url_for('admin.dashboard')
    if usuario.rol == 'mesero':
        return url_for('meseros.view_meseros')
    if usuario.es_cocina:
        return url_for('cocina.index')
    return url_for('auth.login')


def cerrar_sesion():
    logout_user()
    session.clear()
