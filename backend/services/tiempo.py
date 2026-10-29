"""Zona horaria del negocio.

Todas las fechas se guardan en UTC (`utc_now()`), pero el día contable es el día
local del negocio: si la barbacoa cierra a las 23:00 de México (UTC-6), esas ventas
son de HOY, no de mañana. Filtrar con `func.date(columna) == date.today()` mandaba
toda la venta posterior a las 18:00 local al día siguiente.

Regla: filtrar por rango `col >= inicio_utc AND col < fin_utc` (además usa índice),
y agrupar por día con `dia_local(col)`.

Se configura con `APP_TIMEZONE` en .env (default America/Mexico_City).
"""
import os
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import func

_DEFAULT_TZ = 'America/Mexico_City'


def zona():
    """ZoneInfo del negocio. Cae a UTC si el nombre configurado no existe."""
    nombre = os.getenv('APP_TIMEZONE', _DEFAULT_TZ)
    try:
        return ZoneInfo(nombre)
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo('UTC')


def ahora_local():
    """Datetime actual en la zona del negocio (aware)."""
    return datetime.now(zona())


def hoy_local():
    """El día contable de hoy según el reloj del negocio."""
    return ahora_local().date()


_DIAS = ('lunes', 'martes', 'miércoles', 'jueves', 'viernes', 'sábado', 'domingo')
_MESES = ('enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio', 'julio', 'agosto',
          'septiembre', 'octubre', 'noviembre', 'diciembre')


def fecha_larga(d=None):
    """'jueves 29 de octubre de 2026' — sin depender del locale del servidor
    (en Docker es C/en_US y strftime('%A') daría 'Thursday')."""
    d = d or hoy_local()
    return f'{_DIAS[d.weekday()]} {d.day} de {_MESES[d.month - 1]} de {d.year}'


def a_local(dt):
    """Convierte un datetime guardado (UTC, naive o aware) a la zona del negocio."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(zona())


def rango_utc(fecha_inicio, fecha_fin=None):
    """Convierte un rango de días locales a límites UTC naive [inicio, fin).

    `fecha_fin` es inclusiva como día: rango_utc(hoy, hoy) cubre la jornada completa
    de hoy. El límite superior que devuelve es exclusivo, por eso se compara con `<`.
    """
    if fecha_fin is None:
        fecha_fin = fecha_inicio
    tz = zona()
    inicio = datetime.combine(fecha_inicio, time.min, tzinfo=tz)
    fin = datetime.combine(fecha_fin + timedelta(days=1), time.min, tzinfo=tz)
    return (inicio.astimezone(timezone.utc).replace(tzinfo=None),
            fin.astimezone(timezone.utc).replace(tzinfo=None))


def iso_utc(dt):
    """ISO-8601 con sufijo Z, para timestamps que consume JavaScript.

    Sin el sufijo, `new Date('2026-07-21T15:44:00')` se interpreta como hora local
    del navegador y los cronómetros del KDS salen desfasados por el offset.
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')


def _col_local(col):
    """La columna UTC expresada en hora local, en SQL.

    PostgreSQL sabe de zonas horarias (respeta horario de verano); SQLite sólo permite
    desplazar por un offset fijo, que es exacto para México (sin DST desde 2022).
    """
    from backend.extensions import db

    bind = db.session.bind
    dialect = bind.dialect.name if bind is not None else 'sqlite'
    if dialect == 'postgresql':
        return func.timezone(os.getenv('APP_TIMEZONE', _DEFAULT_TZ), func.timezone('UTC', col))
    offset_horas = ahora_local().utcoffset().total_seconds() / 3600
    return func.datetime(col, f'{offset_horas:+.0f} hours')


def dia_local(col):
    """Expresión SQL con el día local de una columna UTC, para GROUP BY / labels."""
    return func.date(_col_local(col))


def hora_local_sql(col):
    """Expresión SQL con la hora (0-23) local de una columna UTC.

    Sin esto, la gráfica de "ventas por hora" muestra el pico de la comida a las 19:00.
    """
    from sqlalchemy import extract
    return extract('hour', _col_local(col))
