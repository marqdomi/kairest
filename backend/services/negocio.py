"""Identidad del negocio para lo que ve el cliente (tickets, comandas, cortes).

El nombre y el logo se capturan en el wizard de instalación (paso 1) y se
editan luego en Personalización, pero el ticket los traía escritos a mano:
salía "CASA LEONES" (el cliente demo) en cualquier instalación, y el ticket
ESC/POS decía "Mi Restaurante" porque nadie le pasaba el nombre.

Todo lo que se imprime o se le entrega al cliente debe pasar por aquí.
"""
_FALLBACK_NOMBRE = 'KaiRest'


def _sucursal_actual():
    """La sucursal del negocio. En instalación de una sola sucursal es la única.

    Se usa `g.sucursal_id` cuando existe para que un despliegue multi-sucursal
    imprima los datos de la sucursal en la que se está cobrando.
    """
    from flask import g
    from backend.models.models import Sucursal

    suc_id = getattr(g, 'sucursal_id', None)
    if suc_id:
        suc = Sucursal.query.get(suc_id)
        if suc:
            return suc
    return Sucursal.query.order_by(Sucursal.id).first()


EXTENSIONES_LOGO = {'png', 'jpg', 'jpeg', 'svg', 'webp'}


def guardar_logo(sucursal, archivo):
    """Guarda el logo del negocio y lo deja en `sucursal.logo_url`.

    Devuelve (guardado, error). No hace commit: lo hace quien llama, junto con
    el resto del formulario.

    Se usa desde el wizard de instalación y desde Personalización, para que el
    negocio pueda poner su marca desde el primer día y no quede con la del
    producto en el ticket que se lleva el cliente.
    """
    import os
    from flask import current_app, url_for
    from werkzeug.utils import secure_filename

    if not archivo or not archivo.filename:
        return False, None

    ext = archivo.filename.rsplit('.', 1)[-1].lower() if '.' in archivo.filename else ''
    if ext not in EXTENSIONES_LOGO:
        return False, 'Formato de imagen no soportado. Usa PNG, JPG, SVG o WebP.'

    destino = os.path.join(current_app.static_folder, 'uploads', 'logos')
    os.makedirs(destino, exist_ok=True)
    nombre = secure_filename(f'logo_{sucursal.id}.{ext}')
    archivo.save(os.path.join(destino, nombre))
    sucursal.logo_url = url_for('static', filename=f'uploads/logos/{nombre}')
    return True, None


def nombre_negocio():
    """Nombre para encabezar tickets y comandas."""
    try:
        suc = _sucursal_actual()
        if suc and (suc.nombre or '').strip():
            return suc.nombre.strip()
    except Exception:
        pass
    return _FALLBACK_NOMBRE


def datos_negocio():
    """Identidad completa para el ticket: nombre, logo y datos de contacto.

    Devuelve siempre las mismas llaves (con cadena vacía si no hay dato) para
    que la plantilla del ticket no tenga que defenderse de ausencias.
    """
    datos = {
        'nombre': _FALLBACK_NOMBRE,
        'logo_url': '',
        'direccion': '',
        'telefono': '',
        'rfc': '',
        'slogan': '',
    }
    try:
        suc = _sucursal_actual()
        if not suc:
            return datos
        datos['nombre'] = (suc.nombre or '').strip() or _FALLBACK_NOMBRE
        datos['direccion'] = (suc.direccion or '').strip()
        datos['telefono'] = (suc.telefono or '').strip()
        datos['rfc'] = (suc.rfc or '').strip()
        datos['slogan'] = (suc.slogan or '').strip()

        logo = (getattr(suc, 'logo_url', '') or '').strip()
        if logo:
            datos['logo_url'] = logo
        else:
            # Sin logo propio no se pone ninguno: el del demo en el ticket de
            # otro negocio es peor que no tener logo.
            datos['logo_url'] = ''
    except Exception:
        pass
    return datos
