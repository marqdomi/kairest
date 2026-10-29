"""Datos bancarios del negocio, para cobrar por transferencia.

El mesero no debería dictar la CLABE de memoria: son 18 dígitos y un error manda el
dinero a otra cuenta. Se capturan una vez en Personalización y se muestran en la
pantalla de cobro cuando el cliente elige transferencia.
"""
import re

from backend.models.models import ConfiguracionSistema

# Claves en ConfiguracionSistema
CAMPOS = ('banco_nombre', 'banco_titular', 'banco_clabe', 'banco_referencia_extra')

_PESOS_CLABE = (3, 7, 1)


def solo_digitos(valor):
    return re.sub(r'\D', '', valor or '')


def digito_verificador_clabe(primeros_17):
    """Dígito de control de una CLABE (ponderación 3-7-1, módulo 10)."""
    suma = sum((int(d) * _PESOS_CLABE[i % 3]) % 10 for i, d in enumerate(primeros_17))
    return (10 - (suma % 10)) % 10


def validar_clabe(clabe):
    """(válida, mensaje). Una CLABE mal capturada manda el dinero a otra cuenta,
    así que se valida el dígito verificador, no sólo la longitud."""
    digitos = solo_digitos(clabe)
    if not digitos:
        return True, ''  # opcional: no capturarla no es un error
    if len(digitos) != 18:
        return False, f'La CLABE debe tener 18 dígitos (capturaste {len(digitos)}).'
    if digito_verificador_clabe(digitos[:17]) != int(digitos[17]):
        return False, 'La CLABE no es válida — revisa que no falte o sobre un dígito.'
    return True, ''


def formatear_clabe(clabe):
    """Agrupada de 4 en 4 para poder leerla en voz alta sin equivocarse."""
    digitos = solo_digitos(clabe)
    return ' '.join(digitos[i:i + 4] for i in range(0, len(digitos), 4))


def datos_bancarios():
    """Lo capturado en Personalización. `configurado` dice si hay algo que mostrar."""
    datos = {campo: (ConfiguracionSistema.get(campo, '') or '') for campo in CAMPOS}
    datos['clabe_formateada'] = formatear_clabe(datos['banco_clabe'])
    datos['configurado'] = bool(datos['banco_clabe'] or datos['banco_nombre'])
    return datos


def guardar_datos_bancarios(form):
    """Guarda los datos del formulario. Devuelve la lista de errores encontrados."""
    from backend.services.sanitizer import sanitizar_texto

    errores = []
    clabe_raw = form.get('banco_clabe', '') or ''
    clabe = solo_digitos(clabe_raw)
    # Letras en la CLABE: solo_digitos las tiraba y quedaba vacía, que es válido
    # ("sin CLABE"), así que se BORRABA la CLABE guardada sin decir nada
    if any(ch.isalpha() for ch in clabe_raw):
        errores.append('La CLABE son 18 números, sin letras. No se cambió la que tenías.')
        clabe = None
    valida, mensaje = validar_clabe(clabe) if clabe is not None else (False, None)
    if not valida:
        if mensaje:
            errores.append(mensaje)
    else:
        ConfiguracionSistema.set('banco_clabe', clabe)

    ConfiguracionSistema.set('banco_nombre', sanitizar_texto(form.get('banco_nombre', ''), 60))
    ConfiguracionSistema.set('banco_titular', sanitizar_texto(form.get('banco_titular', ''), 120))
    ConfiguracionSistema.set('banco_referencia_extra',
                             sanitizar_texto(form.get('banco_referencia_extra', ''), 120))
    return errores
