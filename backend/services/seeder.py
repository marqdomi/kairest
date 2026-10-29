# backend/services/seeder.py
"""
Reusable seeding functions for the onboarding wizard and CLI scripts.
Extracted from seed_products.py / seed_users.py / seed_tables.py.
"""
import json
import logging
import os
from backend.extensions import db
from backend.models.models import Categoria, Producto, Estacion, Mesa, Usuario

logger = logging.getLogger(__name__)

# ── Path to templates JSON ──
_TEMPLATES_PATH = os.path.join(os.path.dirname(__file__), '..', 'data', 'restaurant_templates.json')


def _load_templates():
    """Load restaurant templates from JSON file."""
    with open(_TEMPLATES_PATH, 'r', encoding='utf-8') as f:
        return json.load(f)


def get_template_list():
    """Return a summary list of available templates for the UI.
    Each item: {key, nombre, descripcion, icon, productos_count, estaciones, categorias}
    """
    templates = _load_templates()
    result = []
    for key, tpl in templates.items():
        result.append({
            'key': key,
            'nombre': tpl['nombre'],
            'descripcion': tpl['descripcion'],
            'icon': tpl['icon'],
            'productos_count': len(tpl['productos']),
            'estaciones': tpl['estaciones'],
            # Estaciones que en ese tipo de negocio despacha el mesero (sin pantalla)
            'la_sirve_mesero': tpl.get('la_sirve_mesero', []),
            'categorias': tpl['categorias'],
        })
    return result


def seed_from_template(template_key, custom_estaciones=None, origen_map=None, sirve_mesero=None):
    """Seed categories, stations, and products from a named template.
    Idempotent — skips existing records.

    A template defines a fixed set of "estaciones" (e.g. Parrilla/Comal/Barra)
    and assigns each product to one of them. A small kitchen may run fewer
    real stations than the template's default granularity, so this accepts:

        custom_estaciones: list of station names to actually create, replacing
            tpl['estaciones']. If None, the template's own list is used
            unchanged (identical to the pre-existing behavior).
        origen_map: dict {template_estacion_name: custom_estacion_name} routing
            each template station to one of `custom_estaciones`. If None but
            custom_estaciones is given, each template station maps to
            custom_estaciones[min(i, len(custom_estaciones) - 1)] in order —
            i.e. extra template stations collapse into the last custom one.
        sirve_mesero: nombres de estaciones finales que despacha el mesero (sin
            pantalla de cocina). None = lo que diga la plantilla (`la_sirve_mesero`),
            traducido por el mismo mapeo.

    Returns the number of products created.
    """
    templates = _load_templates()
    tpl = templates.get(template_key)
    if not tpl:
        logger.warning('Template "%s" no encontrado.', template_key)
        return 0

    # ── Categorías ──
    for cat_nombre in tpl['categorias']:
        if not Categoria.query.filter_by(nombre=cat_nombre).first():
            db.session.add(Categoria(nombre=cat_nombre))
    db.session.commit()
    categorias = {c.nombre: c for c in Categoria.query.all()}

    # ── Estaciones: las del template, o las que el negocio realmente va a operar ──
    estaciones_finales = custom_estaciones or tpl['estaciones']
    for est_nombre in estaciones_finales:
        if not Estacion.query.filter_by(nombre=est_nombre).first():
            db.session.add(Estacion(nombre=est_nombre))
    db.session.commit()
    estaciones = {e.nombre.lower(): e for e in Estacion.query.all()}

    # ── Mapeo: estación-del-template → estación-real-del-negocio ──
    if origen_map:
        mapa = {k.lower(): v for k, v in origen_map.items()}
    elif custom_estaciones:
        mapa = {
            orig.lower(): custom_estaciones[min(i, len(custom_estaciones) - 1)]
            for i, orig in enumerate(tpl['estaciones'])
        }
    else:
        mapa = {orig.lower(): orig for orig in tpl['estaciones']}

    # ── Las que sirve el mesero (Casa Leones: Bebidas, que están a la mano) ──
    if sirve_mesero is None:
        sirve_mesero = [mapa.get(n.lower(), n) for n in tpl.get('la_sirve_mesero', [])]
    marcadas = {n.lower() for n in sirve_mesero}
    for nombre_lower, est in estaciones.items():
        if nombre_lower in {e.lower() for e in estaciones_finales}:
            est.la_sirve_mesero = nombre_lower in marcadas
    db.session.commit()

    # ── Productos ──
    # Un producto sin estación jamás aparece en ningún KDS y deja su orden
    # incobrable (verificar_orden_completa exige todos los detalles listos),
    # así que ante cualquier mapeo fallido caemos a la primera estación real.
    est_fallback = estaciones.get(estaciones_finales[0].lower()) if estaciones_finales else None
    created = 0
    for prod in tpl['productos']:
        if not Producto.query.filter_by(nombre=prod['nombre']).first():
            cat = categorias.get(prod['categoria'])
            orig_est = (prod.get('estacion') or '').lower()
            est_nombre_final = mapa.get(orig_est, prod.get('estacion'))
            est = estaciones.get((est_nombre_final or '').lower()) or est_fallback
            producto = Producto(
                nombre=prod['nombre'],
                precio=prod['precio'],
                categoria_id=cat.id if cat else None,
                estacion_id=est.id if est else None,
                unidad=prod.get('unidad', 'pieza'),
                descripcion='',
            )
            db.session.add(producto)
            created += 1

    db.session.commit()
    logger.info('Template "%s" sembrado: %d productos nuevos.', template_key, created)
    return created


def seed_menu_default():
    """Backward-compatible alias — seeds the taqueria template."""
    return seed_from_template('taqueria')


def seed_mesas(cantidad=8):
    """Create numbered mesas (1..cantidad). Idempotent — skips existing.
    Returns the number of mesas created.
    """
    created = 0
    for numero in range(1, cantidad + 1):
        num_str = str(numero)
        if not Mesa.query.filter_by(numero=num_str).first():
            db.session.add(Mesa(numero=num_str, capacidad=4))
            created += 1
    db.session.commit()
    logger.info('Mesas sembradas: %d nuevas.', created)
    return created


def seed_estaciones():
    """Ensure the three default kitchen stations exist."""
    for nombre in ["taquero", "comal", "bebidas"]:
        if not Estacion.query.filter_by(nombre=nombre).first():
            db.session.add(Estacion(nombre=nombre))
    db.session.commit()
