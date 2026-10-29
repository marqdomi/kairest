"""Acceso rápido del personal: usuario corto, PIN y dispositivos autorizados.

Reglas (docs/PLAN_ACCESO_PIN.md):
- Meseros y cocina entran con PIN de 4 dígitos, SÓLO en dispositivos que la dueña
  vinculó con un código de 6 dígitos. La dueña y los admin, con usuario + contraseña.
- 5 PIN fallidos seguidos bloquean a esa persona 5 minutos.
"""
import hashlib
import json
import logging
import re
import secrets
import time
import unicodedata
from datetime import timedelta

from flask import current_app, request

from backend.extensions import db
from backend.models.models import ConfiguracionSistema, DispositivoAutorizado, Usuario, utc_now

logger = logging.getLogger(__name__)

COOKIE_DISPOSITIVO = 'kr_dispositivo'
DURACION_DISPOSITIVO = timedelta(days=365)
PIN_LONGITUD = 4
PIN_MAX_FALLIDOS = 5
PIN_BLOQUEO = timedelta(minutes=5)
CODIGO_VIGENCIA_SEG = 10 * 60
CODIGO_MAX_INTENTOS = 5
_CLAVE_CODIGO = 'codigo_enlace_dispositivo'

# Los que cualquiera prueba primero
_PINES_OBVIOS = {'1234', '4321', '1212', '2580', '0852', '1122', '6969', '1004', '2000', '1010'}


# ── Usuario corto ──

def normalizar_username(texto):
    base = unicodedata.normalize('NFKD', texto or '').encode('ascii', 'ignore').decode()
    return re.sub(r'[^a-z0-9._-]', '', base.lower())[:40]


def sugerir_username(nombre, excluir_id=None):
    """"Pepe Mesero" → "pepe"; si ya existe, "pepe2", "pepe3"…"""
    base = normalizar_username((nombre or '').split()[0] if (nombre or '').split() else '') or 'usuario'
    base = base[:30]
    candidato, n = base, 2
    while True:
        q = Usuario.query.filter_by(username=candidato)
        if excluir_id:
            q = q.filter(Usuario.id != excluir_id)
        if not q.first():
            return candidato
        candidato, n = f'{base}{n}', n + 1


def buscar_para_login(identificador):
    """Acepta usuario o correo (las cuentas creadas antes de esto entran con correo)."""
    ident = (identificador or '').strip()
    if not ident:
        return None
    if '@' in ident:
        return Usuario.query.filter(db.func.lower(Usuario.email) == ident.lower()).first()
    return Usuario.query.filter_by(username=normalizar_username(ident)).first()


# ── PIN ──

def validar_pin(pin):
    """Devuelve (ok, mensaje)."""
    pin = pin or ''
    if not re.fullmatch(rf'\d{{{PIN_LONGITUD}}}', pin):
        return False, f'El PIN debe tener {PIN_LONGITUD} números.'
    if len(set(pin)) == 1 or pin in _PINES_OBVIOS or pin in '0123456789' or pin in '9876543210':
        return False, 'Ese PIN es muy fácil de adivinar. Elige otro.'
    return True, ''


def generar_pin():
    while True:
        pin = f'{secrets.randbelow(10 ** PIN_LONGITUD):0{PIN_LONGITUD}d}'
        if validar_pin(pin)[0]:
            return pin


def _ahora():
    return utc_now().replace(tzinfo=None)  # columnas DateTime naive (convención del repo)


def bloqueado(usuario):
    return usuario.pin_bloqueado


def verificar_pin(usuario, pin):
    """Devuelve (ok, motivo). motivo: 'bloqueado' | 'incorrecto' | ''.

    El conteo de fallos es por persona (no por IP): con Docker Desktop todas las
    tablets del puesto llegan con la misma IP y un límite por IP las castigaría juntas.
    """
    if bloqueado(usuario):
        return False, 'bloqueado'
    if usuario.check_pin(pin):
        usuario.pin_fallidos = 0
        usuario.pin_bloqueado_hasta = None
        return True, ''
    usuario.pin_fallidos = (usuario.pin_fallidos or 0) + 1
    if usuario.pin_fallidos >= PIN_MAX_FALLIDOS:
        usuario.pin_fallidos = 0
        usuario.pin_bloqueado_hasta = _ahora() + PIN_BLOQUEO
        from backend.services.audit import registrar_auditoria
        registrar_auditoria('pin_bloqueado', 'Usuario', usuario.id,
                            f'PIN bloqueado 5 min por {PIN_MAX_FALLIDOS} intentos fallidos: {usuario.identificador}',
                            usuario.id)
        return False, 'bloqueado'
    return False, 'incorrecto'


def intentos_restantes(usuario):
    return max(0, PIN_MAX_FALLIDOS - (usuario.pin_fallidos or 0))


# ── Dispositivos ──

def _hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def dispositivo_actual():
    """El DispositivoAutorizado de este navegador, o None."""
    token = request.cookies.get(COOKIE_DISPOSITIVO)
    if not token:
        return None
    disp = DispositivoAutorizado.query.filter_by(token_hash=_hash(token), activo=True).first()
    return disp


def autorizar(nombre, usuario_id=None, sucursal_id=None):
    """Crea el dispositivo y devuelve (dispositivo, token). El token va a la cookie."""
    token = secrets.token_urlsafe(32)
    disp = DispositivoAutorizado(nombre=(nombre or 'Dispositivo')[:60], token_hash=_hash(token),
                                 autorizado_por=usuario_id, sucursal_id=sucursal_id)
    db.session.add(disp)
    return disp, token


def poner_cookie(respuesta, token):
    respuesta.set_cookie(
        COOKIE_DISPOSITIVO, token,
        max_age=int(DURACION_DISPOSITIVO.total_seconds()),
        httponly=True, samesite='Lax',
        secure=bool(current_app.config.get('SESSION_COOKIE_SECURE')),
    )
    return respuesta


# ── Código de enlace (6 dígitos, 10 min, un solo uso) ──

def crear_codigo(usuario_id):
    codigo = f'{secrets.randbelow(10 ** 6):06d}'
    ConfiguracionSistema.set(_CLAVE_CODIGO, json.dumps({
        'hash': _hash(codigo), 'vence': int(time.time()) + CODIGO_VIGENCIA_SEG,
        'por': usuario_id, 'intentos': 0,
    }))
    return codigo


def canjear_codigo(codigo):
    """Devuelve (ok, usuario_id_que_lo_generó, mensaje). El código muere al usarse,
    al vencer o tras 5 intentos fallidos (6 dígitos no aguantan fuerza bruta abierta)."""
    crudo = ConfiguracionSistema.get(_CLAVE_CODIGO)
    datos = json.loads(crudo) if crudo else None
    if not datos or datos.get('vence', 0) < time.time():
        return False, None, 'El código no es válido o ya venció. Pide uno nuevo.'
    if secrets.compare_digest(datos['hash'], _hash((codigo or '').strip())):
        ConfiguracionSistema.set(_CLAVE_CODIGO, '')
        return True, datos.get('por'), ''
    datos['intentos'] = datos.get('intentos', 0) + 1
    if datos['intentos'] >= CODIGO_MAX_INTENTOS:
        ConfiguracionSistema.set(_CLAVE_CODIGO, '')
        return False, None, 'Demasiados intentos: el código se anuló. Pide uno nuevo.'
    ConfiguracionSistema.set(_CLAVE_CODIGO, json.dumps(datos))
    return False, None, 'Código incorrecto.'


def codigo_vigente():
    """Segundos que le quedan al código activo (0 si no hay)."""
    crudo = ConfiguracionSistema.get(_CLAVE_CODIGO)
    datos = json.loads(crudo) if crudo else None
    if not datos:
        return 0
    return max(0, int(datos.get('vence', 0) - time.time()))


def personal_con_pin(dispositivo):
    q = Usuario.query.filter(Usuario.pin_hash.isnot(None))
    if dispositivo and dispositivo.sucursal_id:
        q = q.filter(db.or_(Usuario.sucursal_id == dispositivo.sucursal_id, Usuario.sucursal_id.is_(None)))
    return [u for u in q.order_by(Usuario.nombre).all() if u.usa_pin]
