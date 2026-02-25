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
            'categorias': tpl['categorias'],
        })
    return result


def seed_from_template(template_key):
    """Seed categories, stations, and products from a named template.
    Idempotent — skips existing records.
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

    # ── Estaciones ──
    for est_nombre in tpl['estaciones']:
        if not Estacion.query.filter_by(nombre=est_nombre).first():
            db.session.add(Estacion(nombre=est_nombre))
    db.session.commit()
    estaciones = {e.nombre: e for e in Estacion.query.all()}

    # ── Productos ──
    created = 0
    for prod in tpl['productos']:
        if not Producto.query.filter_by(nombre=prod['nombre']).first():
            cat = categorias.get(prod['categoria'])
            est = estaciones.get(prod.get('estacion'))
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
