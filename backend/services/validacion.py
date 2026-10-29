"""Lectura tolerante y validada de lo que la gente teclea en los formularios.

Los formularios recibían números y correos "como vinieran": `float('1,160.00')`
tronaba y el código caía a 0 en silencio (un corte de caja guardado con $0 contados),
`int('-4')` se guardaba tal cual (mesa con −4 personas) y un correo sin dominio se
aceptaba porque `sanitizar_email(x) or x` devolvía el texto original. Estas funciones
devuelven el valor limpio o None, y quien llama decide el mensaje.
"""
import re
from decimal import Decimal, InvalidOperation

from backend.services.sanitizer import sanitizar_email

# Lo que cabe en las columnas Numeric(10, 2) de precios y montos
MONTO_MAXIMO = Decimal('99999999.99')


def leer_monto(valor, minimo=Decimal('0'), maximo=MONTO_MAXIMO):
    """"1,160.50", "$1160", " 1 160 " → Decimal('1160.50'). Inválido o fuera de rango → None.

    La coma se toma como separador de miles (así se escribe en México); se redondea a
    centavos para que lo guardado sea lo mismo en SQLite que en PostgreSQL.
    """
    if valor is None:
        return None
    if isinstance(valor, (int, float, Decimal)):
        texto = str(valor)
    else:
        texto = re.sub(r'[\s$,]', '', str(valor))
    if not texto:
        return None
    try:
        monto = Decimal(texto).quantize(Decimal('0.01'))
    except (InvalidOperation, ValueError):
        return None
    if not monto.is_finite() or monto < minimo or monto > maximo:
        return None
    return monto


def leer_entero(valor, minimo, maximo):
    """Entero dentro de [minimo, maximo]; cualquier otra cosa → None."""
    if isinstance(valor, bool):
        return None
    try:
        if isinstance(valor, float) and not valor.is_integer():
            return None
        n = int(str(valor).strip()) if not isinstance(valor, (int, float)) else int(valor)
    except (TypeError, ValueError):
        return None
    return n if minimo <= n <= maximo else None


def leer_correo(valor):
    """(correo_normalizado_o_None, error_o_None). Vacío no es error: el correo es opcional."""
    crudo = (valor or '').strip()
    if not crudo:
        return None, None
    correo = sanitizar_email(crudo)
    if not correo:
        return None, f'"{crudo[:60]}" no es un correo válido (ejemplo: nombre@gmail.com).'
    return correo, None
