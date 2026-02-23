# backend/services/seeder.py
"""
Reusable seeding functions for the onboarding wizard and CLI scripts.
Extracted from seed_products.py / seed_users.py / seed_tables.py.
"""
import logging
from backend.extensions import db
from backend.models.models import Categoria, Producto, Estacion, Mesa, Usuario

logger = logging.getLogger(__name__)


def seed_menu_default():
    """Seed the default barbacoa/carnitas/comal menu.
    Idempotent — skips products that already exist.
    Returns the number of products created.
    """
    # ── Categorías ──
    categorias_data = [
        "Tacos de Barbacoa", "Tacos de Carnitas", "Tacos de Pollo",
        "Quesadillas", "Tlacoyos", "Porciones de Barbacoa",
        "Porciones de Carnitas", "Mixiote", "Antojitos",
        "Consomé", "Paquetes", "Bebidas",
    ]
    for nombre in categorias_data:
        if not Categoria.query.filter_by(nombre=nombre).first():
            db.session.add(Categoria(nombre=nombre))
    db.session.commit()

    categorias = {c.nombre: c for c in Categoria.query.all()}

    # ── Estaciones ──
    estaciones_data = ["taquero", "comal", "bebidas"]
    for nombre in estaciones_data:
        if not Estacion.query.filter_by(nombre=nombre).first():
            db.session.add(Estacion(nombre=nombre))
    db.session.commit()

    estaciones = {e.nombre: e for e in Estacion.query.all()}

    # ── Productos ──
    products_data = [
        # Tacos de Barbacoa
        {"nombre": "Espaldilla", "precio": 35.0, "categoria": "Tacos de Barbacoa", "estacion": "taquero", "unidad": "pieza"},
        {"nombre": "Falda", "precio": 35.0, "categoria": "Tacos de Barbacoa", "estacion": "taquero", "unidad": "pieza"},
        {"nombre": "Costilla", "precio": 35.0, "categoria": "Tacos de Barbacoa", "estacion": "taquero", "unidad": "pieza"},
        {"nombre": "Maciza", "precio": 35.0, "categoria": "Tacos de Barbacoa", "estacion": "taquero", "unidad": "pieza"},
        {"nombre": "Panza", "precio": 35.0, "categoria": "Tacos de Barbacoa", "estacion": "taquero", "unidad": "pieza"},
        {"nombre": "Cabeza", "precio": 35.0, "categoria": "Tacos de Barbacoa", "estacion": "taquero", "unidad": "pieza"},
        {"nombre": "Ojo", "precio": 35.0, "categoria": "Tacos de Barbacoa", "estacion": "taquero", "unidad": "pieza"},
        {"nombre": "Lengua", "precio": 35.0, "categoria": "Tacos de Barbacoa", "estacion": "taquero", "unidad": "pieza"},
        {"nombre": "Cachete", "precio": 35.0, "categoria": "Tacos de Barbacoa", "estacion": "taquero", "unidad": "pieza"},
        {"nombre": "Pezcueso", "precio": 35.0, "categoria": "Tacos de Barbacoa", "estacion": "taquero", "unidad": "pieza"},
        {"nombre": "Espinazo (surtida)", "precio": 35.0, "categoria": "Tacos de Barbacoa", "estacion": "taquero", "unidad": "pieza"},
        {"nombre": "Campechano maciza con panza", "precio": 38.0, "categoria": "Tacos de Barbacoa", "estacion": "taquero", "unidad": "pieza"},
        {"nombre": "Campechano espaldilla con panza", "precio": 38.0, "categoria": "Tacos de Barbacoa", "estacion": "taquero", "unidad": "pieza"},
        {"nombre": "Campechano falda con panza", "precio": 38.0, "categoria": "Tacos de Barbacoa", "estacion": "taquero", "unidad": "pieza"},
        {"nombre": "Campechano costilla con panza", "precio": 38.0, "categoria": "Tacos de Barbacoa", "estacion": "taquero", "unidad": "pieza"},
        # Tacos de Carnitas
        {"nombre": "Maciza (carnitas)", "precio": 35.0, "categoria": "Tacos de Carnitas", "estacion": "taquero", "unidad": "pieza"},
        {"nombre": "Costilla (carnitas)", "precio": 35.0, "categoria": "Tacos de Carnitas", "estacion": "taquero", "unidad": "pieza"},
        {"nombre": "Tripa", "precio": 35.0, "categoria": "Tacos de Carnitas", "estacion": "taquero", "unidad": "pieza"},
        {"nombre": "Cuerito", "precio": 35.0, "categoria": "Tacos de Carnitas", "estacion": "taquero", "unidad": "pieza"},
        # Tacos de Pollo
        {"nombre": "Taco de pollo", "precio": 35.0, "categoria": "Tacos de Pollo", "estacion": "taquero", "unidad": "pieza"},
        # Quesadillas
        {"nombre": "Chicharrón prensado", "precio": 33.0, "categoria": "Quesadillas", "estacion": "comal", "unidad": "pieza"},
        {"nombre": "Champiñón", "precio": 33.0, "categoria": "Quesadillas", "estacion": "comal", "unidad": "pieza"},
        {"nombre": "Queso", "precio": 33.0, "categoria": "Quesadillas", "estacion": "comal", "unidad": "pieza"},
        {"nombre": "Huitlacoche", "precio": 33.0, "categoria": "Quesadillas", "estacion": "comal", "unidad": "pieza"},
        {"nombre": "Mole verde", "precio": 33.0, "categoria": "Quesadillas", "estacion": "comal", "unidad": "pieza"},
        {"nombre": "Jamón con queso", "precio": 33.0, "categoria": "Quesadillas", "estacion": "comal", "unidad": "pieza"},
        {"nombre": "Flor de calabaza", "precio": 33.0, "categoria": "Quesadillas", "estacion": "comal", "unidad": "pieza"},
        {"nombre": "Tinga", "precio": 33.0, "categoria": "Quesadillas", "estacion": "comal", "unidad": "pieza"},
        {"nombre": "Quesadilla de Barbacoa", "precio": 65.0, "categoria": "Quesadillas", "estacion": "comal", "unidad": "pieza"},
        {"nombre": "Quesadilla de Carnitas", "precio": 40.0, "categoria": "Quesadillas", "estacion": "comal", "unidad": "pieza"},
        # Tlacoyos
        {"nombre": "Tlacoyo de Frijol", "precio": 33.0, "categoria": "Tlacoyos", "estacion": "comal", "unidad": "pieza"},
        {"nombre": "Tlacoyo de Requesón", "precio": 33.0, "categoria": "Tlacoyos", "estacion": "comal", "unidad": "pieza"},
        {"nombre": "Tlacoyo de Alberjón", "precio": 33.0, "categoria": "Tlacoyos", "estacion": "comal", "unidad": "pieza"},
        {"nombre": "Tlacoyo de Chicharrón", "precio": 33.0, "categoria": "Tlacoyos", "estacion": "comal", "unidad": "pieza"},
        {"nombre": "Tlacoyo de Barbacoa", "precio": 33.0, "categoria": "Tlacoyos", "estacion": "comal", "unidad": "pieza"},
        {"nombre": "Tlacoyo de Carnitas", "precio": 33.0, "categoria": "Tlacoyos", "estacion": "comal", "unidad": "pieza"},
        # Porciones de Barbacoa
        {"nombre": "1 kg Barbacoa", "precio": 550.0, "categoria": "Porciones de Barbacoa", "estacion": "taquero", "unidad": "kg"},
        {"nombre": "3/4 kg Barbacoa", "precio": 415.0, "categoria": "Porciones de Barbacoa", "estacion": "taquero", "unidad": "kg"},
        {"nombre": "1/2 kg Barbacoa", "precio": 280.0, "categoria": "Porciones de Barbacoa", "estacion": "taquero", "unidad": "kg"},
        {"nombre": "1/4 kg Barbacoa", "precio": 140.0, "categoria": "Porciones de Barbacoa", "estacion": "taquero", "unidad": "kg"},
        # Porciones de Carnitas
        {"nombre": "1 kg Carnitas", "precio": 300.0, "categoria": "Porciones de Carnitas", "estacion": "taquero", "unidad": "kg"},
        {"nombre": "3/4 kg Carnitas", "precio": 225.0, "categoria": "Porciones de Carnitas", "estacion": "taquero", "unidad": "kg"},
        {"nombre": "1/2 kg Carnitas", "precio": 150.0, "categoria": "Porciones de Carnitas", "estacion": "taquero", "unidad": "kg"},
        {"nombre": "1/4 kg Carnitas", "precio": 80.0, "categoria": "Porciones de Carnitas", "estacion": "taquero", "unidad": "kg"},
        # Mixiote
        {"nombre": "Mixiote de Pollo (llevar)", "precio": 80.0, "categoria": "Mixiote", "estacion": "taquero", "unidad": "pieza"},
        {"nombre": "Mixiote de Pollo (aquí)", "precio": 90.0, "categoria": "Mixiote", "estacion": "taquero", "unidad": "pieza"},
        # Antojitos
        {"nombre": "Orden de tacos dorados (3 flautas)", "precio": 90.0, "categoria": "Antojitos", "estacion": "comal", "unidad": "orden"},
        {"nombre": "1 flauta individual", "precio": 33.0, "categoria": "Antojitos", "estacion": "comal", "unidad": "pieza"},
        {"nombre": "1 kg Tortillas", "precio": 30.0, "categoria": "Antojitos", "estacion": "comal", "unidad": "pieza"},
        # Consomé
        {"nombre": "Plato de consomé", "precio": 35.0, "categoria": "Consomé", "estacion": "taquero", "unidad": "plato"},
        {"nombre": "1 litro de consomé", "precio": 60.0, "categoria": "Consomé", "estacion": "taquero", "unidad": "litro"},
        {"nombre": "1/2 litro de consomé", "precio": 35.0, "categoria": "Consomé", "estacion": "taquero", "unidad": "litro"},
        # Paquetes
        {"nombre": "1/4 kg barbacoa + 1 plato consomé", "precio": 175.0, "categoria": "Paquetes", "estacion": "taquero", "unidad": "paquete"},
        {"nombre": "1/2 kg barbacoa + 1 lt consomé", "precio": 340.0, "categoria": "Paquetes", "estacion": "taquero", "unidad": "paquete"},
        {"nombre": "3/4 kg barbacoa + 1 1/2 lt consomé", "precio": 500.0, "categoria": "Paquetes", "estacion": "taquero", "unidad": "paquete"},
        {"nombre": "1 kg barbacoa + 2 lt consomé", "precio": 670.0, "categoria": "Paquetes", "estacion": "taquero", "unidad": "paquete"},
        # Bebidas
        {"nombre": "Coca-Cola", "precio": 25.0, "categoria": "Bebidas", "estacion": "bebidas", "unidad": "pieza"},
        {"nombre": "Boing", "precio": 25.0, "categoria": "Bebidas", "estacion": "bebidas", "unidad": "pieza"},
        {"nombre": "Agua Jamaica", "precio": 40.0, "categoria": "Bebidas", "estacion": "bebidas", "unidad": "pieza"},
        {"nombre": "Agua sabor", "precio": 45.0, "categoria": "Bebidas", "estacion": "bebidas", "unidad": "pieza"},
        {"nombre": "Café", "precio": 25.0, "categoria": "Bebidas", "estacion": "bebidas", "unidad": "pieza"},
    ]

    created = 0
    for prod in products_data:
        if not Producto.query.filter_by(nombre=prod["nombre"]).first():
            estacion = estaciones.get(prod.get("estacion"))
            producto = Producto(
                nombre=prod["nombre"],
                precio=prod["precio"],
                categoria_id=categorias[prod["categoria"]].id,
                estacion_id=estacion.id if estacion else None,
                unidad=prod.get("unidad"),
                descripcion="",
            )
            db.session.add(producto)
            created += 1

    db.session.commit()
    logger.info('Menú default sembrado: %d productos nuevos.', created)
    return created


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
