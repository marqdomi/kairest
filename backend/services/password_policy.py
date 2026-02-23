"""Fase 5 — Sprint 1 (4.4): Política de contraseñas."""
import re

# Top 100 contraseñas comunes (subset representativo)
_COMMON_PASSWORDS = frozenset([
    '123456', 'password', '12345678', 'qwerty', '123456789',
    '12345', '1234', '111111', '1234567', 'dragon',
    '123123', 'baseball', 'abc123', 'football', 'monkey',
    'letmein', '696969', 'shadow', 'master', '666666',
    'qwertyuiop', '123321', 'mustang', '1234567890', 'michael',
    'password1', 'password123', 'admin', 'admin123', 'root',
    'toor', 'pass', 'test', 'guest', 'welcome',
    'login', 'changeme', 'abc123456', 'p@ssw0rd', 'qwer1234',
    'kairest', 'restaurante', 'mesero', 'cocina', 'tacos',
])

# Requisitos mínimos
MIN_LENGTH = 8


def validar_password(password: str, nombre: str = '', email: str = '') -> tuple[bool, list[str]]:
    """Valida una contraseña contra la política de seguridad.

    Returns:
        (es_valida, lista_de_errores)
    """
    errores = []

    if not password:
        return False, ['La contraseña es requerida.']

    if len(password) < MIN_LENGTH:
        errores.append(f'Debe tener al menos {MIN_LENGTH} caracteres.')

    if not re.search(r'[A-Z]', password):
        errores.append('Debe contener al menos una letra mayúscula.')

    if not re.search(r'[a-z]', password):
        errores.append('Debe contener al menos una letra minúscula.')

    if not re.search(r'\d', password):
        errores.append('Debe contener al menos un número.')

    if password.lower() in _COMMON_PASSWORDS:
        errores.append('Contraseña demasiado común. Elige una más segura.')

    # No puede ser igual al nombre o email
    if nombre and password.lower() == nombre.lower():
        errores.append('La contraseña no puede ser igual al nombre.')
    if email and password.lower() == email.lower().split('@')[0]:
        errores.append('La contraseña no puede ser igual al email.')

    return (len(errores) == 0, errores)
