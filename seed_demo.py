#!/usr/bin/env python3
"""
seed_demo.py — Comprehensive demo data seeder for CasaLeones POS.
Fills ALL tables with realistic example data so the system looks fully operational.

Usage:
  DATABASE_URL="postgresql://casaleones:casaleones_secret@localhost:5433/casaleones" \
  REDIS_URL="" python3 seed_demo.py

This script is IDEMPOTENT — safe to run multiple times.
It will RESET transactional data (orders, sales, payments, etc.) on each run.
"""
import os
import sys
import random
from datetime import datetime, timedelta
from decimal import Decimal

os.environ.setdefault('FLASK_ENV', 'development')
os.environ.setdefault('DATABASE_URL', 'postgresql://casaleones:casaleones_secret@localhost:5433/casaleones')
if not os.environ.get('REDIS_URL'):
    os.environ['REDIS_URL'] = ''

from backend.app import create_app
from backend.extensions import db
from backend.models.models import (
    ConfiguracionSistema, Sucursal, Usuario, Categoria, Estacion, Producto,
    Mesa, Cliente, Reservacion, Orden, OrdenDetalle, Pago, Ingrediente,
    RecetaDetalle, MovimientoInventario, AuditLog, Factura, NotaCredito,
    CorteCaja, Sale, SaleItem, DeliveryOrden, IVA_RATE,
)

random.seed(42)  # reproducible

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
NOW = datetime(2026, 2, 19, 14, 0, 0)  # "today" anchor


def rand_date(days_back=30):
    """Random datetime in the last N days."""
    delta = timedelta(
        days=random.randint(0, days_back),
        hours=random.randint(8, 21),
        minutes=random.randint(0, 59),
    )
    return NOW - delta


def rand_recent(hours_back=8):
    delta = timedelta(hours=random.randint(0, hours_back), minutes=random.randint(0, 59))
    return NOW - delta


# ---------------------------------------------------------------------------
# 1. CONFIGURACIÓN DEL SISTEMA
# ---------------------------------------------------------------------------
def seed_configuracion():
    print("  → Configuración del sistema...")
    defaults = {
        'onboarding_completado': 'true',
        'modo_sistema': 'avanzado',
        'nombre_negocio': 'Casa Leones Barbacoa & Carnitas',
        'moneda': 'MXN',
        'timezone': 'America/Mexico_City',
    }
    for clave, valor in defaults.items():
        ConfiguracionSistema.set(clave, valor)
    db.session.commit()


# ---------------------------------------------------------------------------
# 2. SUCURSALES
# ---------------------------------------------------------------------------
def seed_sucursales():
    print("  → Sucursales...")
    data = [
        {'nombre': 'Casa Leones Centro', 'direccion': 'Av. Insurgentes Sur 1234, Col. Del Valle, CDMX', 'telefono': '55-1234-5678'},
        {'nombre': 'Casa Leones Coyoacán', 'direccion': 'Calle Francisco Sosa 45, Coyoacán, CDMX', 'telefono': '55-8765-4321'},
    ]
    for d in data:
        if not Sucursal.query.filter_by(nombre=d['nombre']).first():
            db.session.add(Sucursal(**d))
    db.session.commit()
    return {s.nombre: s for s in Sucursal.query.all()}


# ---------------------------------------------------------------------------
# 3. USUARIOS
# ---------------------------------------------------------------------------
def seed_usuarios(sucursales):
    print("  → Usuarios...")
    centro = sucursales.get('Casa Leones Centro')
    coyoacan = sucursales.get('Casa Leones Coyoacán')

    data = [
        {'nombre': 'Marco Domínguez', 'email': 'marco@casaleones.mx', 'rol': 'superadmin', 'sucursal_id': None},
        {'nombre': 'Admin Centro', 'email': 'admin@casaleones.mx', 'rol': 'admin', 'sucursal_id': centro.id if centro else None},
        # Meseros Centro
        {'nombre': 'Carlos Hernández', 'email': 'carlos@casaleones.mx', 'rol': 'mesero', 'sucursal_id': centro.id if centro else None},
        {'nombre': 'María López', 'email': 'maria@casaleones.mx', 'rol': 'mesero', 'sucursal_id': centro.id if centro else None},
        {'nombre': 'José García', 'email': 'jose@casaleones.mx', 'rol': 'mesero', 'sucursal_id': centro.id if centro else None},
        {'nombre': 'Ana Martínez', 'email': 'ana@casaleones.mx', 'rol': 'mesero', 'sucursal_id': centro.id if centro else None},
        # Cocina Centro
        {'nombre': 'Don Roberto', 'email': 'roberto@casaleones.mx', 'rol': 'taquero', 'sucursal_id': centro.id if centro else None},
        {'nombre': 'Doña Lupe', 'email': 'lupe@casaleones.mx', 'rol': 'comal', 'sucursal_id': centro.id if centro else None},
        {'nombre': 'Paco Ríos', 'email': 'paco@casaleones.mx', 'rol': 'bebidas', 'sucursal_id': centro.id if centro else None},
        # Coyoacán
        {'nombre': 'Admin Coyoacán', 'email': 'admin.coyoacan@casaleones.mx', 'rol': 'admin', 'sucursal_id': coyoacan.id if coyoacan else None},
        {'nombre': 'Luis Ramírez', 'email': 'luis@casaleones.mx', 'rol': 'mesero', 'sucursal_id': coyoacan.id if coyoacan else None},
        {'nombre': 'Rosa Flores', 'email': 'rosa@casaleones.mx', 'rol': 'mesero', 'sucursal_id': coyoacan.id if coyoacan else None},
    ]

    for d in data:
        u = Usuario.query.filter_by(email=d['email']).first()
        if not u:
            u = Usuario(nombre=d['nombre'], email=d['email'], rol=d['rol'], sucursal_id=d['sucursal_id'])
            u.set_password('CasaLeones2026!')
            db.session.add(u)
        else:
            u.nombre = d['nombre']
            u.rol = d['rol']
            u.sucursal_id = d['sucursal_id']
    db.session.commit()
    return {u.email: u for u in Usuario.query.all()}


# ---------------------------------------------------------------------------
# 4. ESTACIONES + CATEGORÍAS + PRODUCTOS
# ---------------------------------------------------------------------------
def seed_catalogo():
    print("  → Catálogo (estaciones, categorías, productos)...")

    # Estaciones
    for nombre in ['taquero', 'comal', 'bebidas']:
        if not Estacion.query.filter_by(nombre=nombre).first():
            db.session.add(Estacion(nombre=nombre))
    db.session.commit()
    estaciones = {e.nombre: e for e in Estacion.query.all()}

    # Categorías
    cats_data = [
        'Tacos de Barbacoa', 'Tacos de Carnitas', 'Tacos de Pollo',
        'Quesadillas', 'Tlacoyos', 'Porciones de Barbacoa',
        'Porciones de Carnitas', 'Mixiote', 'Antojitos',
        'Consomé', 'Paquetes', 'Bebidas',
    ]
    for nombre in cats_data:
        if not Categoria.query.filter_by(nombre=nombre).first():
            db.session.add(Categoria(nombre=nombre))
    db.session.commit()
    cats = {c.nombre: c for c in Categoria.query.all()}

    # Productos
    products_data = [
        # Tacos de Barbacoa
        ('Espaldilla', 35, 'Tacos de Barbacoa', 'taquero', 'pieza'),
        ('Falda', 35, 'Tacos de Barbacoa', 'taquero', 'pieza'),
        ('Costilla', 35, 'Tacos de Barbacoa', 'taquero', 'pieza'),
        ('Maciza', 35, 'Tacos de Barbacoa', 'taquero', 'pieza'),
        ('Panza', 35, 'Tacos de Barbacoa', 'taquero', 'pieza'),
        ('Cabeza', 35, 'Tacos de Barbacoa', 'taquero', 'pieza'),
        ('Ojo', 35, 'Tacos de Barbacoa', 'taquero', 'pieza'),
        ('Lengua', 35, 'Tacos de Barbacoa', 'taquero', 'pieza'),
        ('Cachete', 35, 'Tacos de Barbacoa', 'taquero', 'pieza'),
        ('Pezcueso', 35, 'Tacos de Barbacoa', 'taquero', 'pieza'),
        ('Espinazo (surtida)', 35, 'Tacos de Barbacoa', 'taquero', 'pieza'),
        ('Campechano maciza con panza', 38, 'Tacos de Barbacoa', 'taquero', 'pieza'),
        ('Campechano espaldilla con panza', 38, 'Tacos de Barbacoa', 'taquero', 'pieza'),
        ('Campechano falda con panza', 38, 'Tacos de Barbacoa', 'taquero', 'pieza'),
        ('Campechano costilla con panza', 38, 'Tacos de Barbacoa', 'taquero', 'pieza'),
        # Tacos de Carnitas
        ('Maciza (carnitas)', 35, 'Tacos de Carnitas', 'taquero', 'pieza'),
        ('Costilla (carnitas)', 35, 'Tacos de Carnitas', 'taquero', 'pieza'),
        ('Tripa', 35, 'Tacos de Carnitas', 'taquero', 'pieza'),
        ('Cuerito', 35, 'Tacos de Carnitas', 'taquero', 'pieza'),
        # Tacos de Pollo
        ('Taco de pollo', 35, 'Tacos de Pollo', 'taquero', 'pieza'),
        # Quesadillas
        ('Quesadilla de Chicharrón prensado', 33, 'Quesadillas', 'comal', 'pieza'),
        ('Quesadilla de Champiñón', 33, 'Quesadillas', 'comal', 'pieza'),
        ('Quesadilla de Queso', 33, 'Quesadillas', 'comal', 'pieza'),
        ('Quesadilla de Huitlacoche', 33, 'Quesadillas', 'comal', 'pieza'),
        ('Quesadilla de Mole verde', 33, 'Quesadillas', 'comal', 'pieza'),
        ('Quesadilla de Jamón con queso', 33, 'Quesadillas', 'comal', 'pieza'),
        ('Quesadilla de Flor de calabaza', 33, 'Quesadillas', 'comal', 'pieza'),
        ('Quesadilla de Tinga', 33, 'Quesadillas', 'comal', 'pieza'),
        ('Quesadilla de Barbacoa', 65, 'Quesadillas', 'comal', 'pieza'),
        ('Quesadilla de Carnitas', 40, 'Quesadillas', 'comal', 'pieza'),
        # Tlacoyos
        ('Tlacoyo de Frijol', 33, 'Tlacoyos', 'comal', 'pieza'),
        ('Tlacoyo de Requesón', 33, 'Tlacoyos', 'comal', 'pieza'),
        ('Tlacoyo de Alberjón', 33, 'Tlacoyos', 'comal', 'pieza'),
        ('Tlacoyo de Chicharrón', 33, 'Tlacoyos', 'comal', 'pieza'),
        ('Tlacoyo de Barbacoa', 33, 'Tlacoyos', 'comal', 'pieza'),
        ('Tlacoyo de Carnitas', 33, 'Tlacoyos', 'comal', 'pieza'),
        # Porciones Barbacoa
        ('1 kg Barbacoa', 550, 'Porciones de Barbacoa', 'taquero', 'kg'),
        ('3/4 kg Barbacoa', 415, 'Porciones de Barbacoa', 'taquero', 'kg'),
        ('1/2 kg Barbacoa', 280, 'Porciones de Barbacoa', 'taquero', 'kg'),
        ('1/4 kg Barbacoa', 140, 'Porciones de Barbacoa', 'taquero', 'kg'),
        # Porciones Carnitas
        ('1 kg Carnitas', 300, 'Porciones de Carnitas', 'taquero', 'kg'),
        ('3/4 kg Carnitas', 225, 'Porciones de Carnitas', 'taquero', 'kg'),
        ('1/2 kg Carnitas', 150, 'Porciones de Carnitas', 'taquero', 'kg'),
        ('1/4 kg Carnitas', 80, 'Porciones de Carnitas', 'taquero', 'kg'),
        # Mixiote
        ('Mixiote de Pollo (llevar)', 80, 'Mixiote', 'taquero', 'pieza'),
        ('Mixiote de Pollo (aquí)', 90, 'Mixiote', 'taquero', 'pieza'),
        # Antojitos
        ('Orden de tacos dorados (3 flautas)', 90, 'Antojitos', 'comal', 'orden'),
        ('1 flauta individual', 33, 'Antojitos', 'comal', 'pieza'),
        ('1 kg Tortillas', 30, 'Antojitos', 'comal', 'pieza'),
        # Consomé
        ('Plato de consomé', 35, 'Consomé', 'taquero', 'plato'),
        ('1 litro de consomé', 60, 'Consomé', 'taquero', 'litro'),
        ('1/2 litro de consomé', 35, 'Consomé', 'taquero', 'litro'),
        # Paquetes
        ('Paq 1/4 kg barbacoa + consomé', 175, 'Paquetes', 'taquero', 'paquete'),
        ('Paq 1/2 kg barbacoa + 1lt consomé', 340, 'Paquetes', 'taquero', 'paquete'),
        ('Paq 3/4 kg barbacoa + 1½lt consomé', 500, 'Paquetes', 'taquero', 'paquete'),
        ('Paq 1 kg barbacoa + 2lt consomé', 670, 'Paquetes', 'taquero', 'paquete'),
        # Bebidas
        ('Coca-Cola', 25, 'Bebidas', 'bebidas', 'pieza'),
        ('Coca-Cola Zero', 25, 'Bebidas', 'bebidas', 'pieza'),
        ('Sprite', 25, 'Bebidas', 'bebidas', 'pieza'),
        ('Boing Mango', 25, 'Bebidas', 'bebidas', 'pieza'),
        ('Boing Guayaba', 25, 'Bebidas', 'bebidas', 'pieza'),
        ('Agua Jamaica', 40, 'Bebidas', 'bebidas', 'pieza'),
        ('Agua Horchata', 40, 'Bebidas', 'bebidas', 'pieza'),
        ('Agua Tamarindo', 40, 'Bebidas', 'bebidas', 'pieza'),
        ('Agua Natural 600ml', 20, 'Bebidas', 'bebidas', 'pieza'),
        ('Café de olla', 25, 'Bebidas', 'bebidas', 'pieza'),
        ('Cerveza Corona', 45, 'Bebidas', 'bebidas', 'pieza'),
        ('Cerveza Victoria', 45, 'Bebidas', 'bebidas', 'pieza'),
        ('Michelada', 65, 'Bebidas', 'bebidas', 'pieza'),
    ]

    for nombre, precio, cat_name, est_name, unidad in products_data:
        if not Producto.query.filter_by(nombre=nombre).first():
            db.session.add(Producto(
                nombre=nombre,
                precio=Decimal(str(precio)),
                categoria_id=cats[cat_name].id,
                estacion_id=estaciones[est_name].id,
                unidad=unidad,
                descripcion='',
            ))
    db.session.commit()
    return {p.nombre: p for p in Producto.query.all()}


# ---------------------------------------------------------------------------
# 5. MESAS
# ---------------------------------------------------------------------------
def seed_mesas(sucursales):
    print("  → Mesas...")
    centro = sucursales.get('Casa Leones Centro')

    mesas_data = [
        # Interior
        ('1', 4, 'Interior', 100, 100),
        ('2', 4, 'Interior', 250, 100),
        ('3', 6, 'Interior', 400, 100),
        ('4', 4, 'Interior', 100, 250),
        ('5', 6, 'Interior', 250, 250),
        ('6', 8, 'Interior', 400, 250),
        # Terraza
        ('7', 4, 'Terraza', 100, 450),
        ('8', 4, 'Terraza', 250, 450),
        ('9', 6, 'Terraza', 400, 450),
        ('10', 8, 'Terraza', 550, 450),
        # Barra
        ('11', 2, 'Barra', 600, 100),
        ('12', 2, 'Barra', 600, 200),
    ]

    for numero, cap, zona, px, py in mesas_data:
        m = Mesa.query.filter_by(numero=numero).first()
        if not m:
            m = Mesa(numero=numero, capacidad=cap, zona=zona, pos_x=px, pos_y=py,
                     sucursal_id=centro.id if centro else None, estado='disponible')
            db.session.add(m)
        else:
            m.capacidad = cap
            m.zona = zona
            m.pos_x = px
            m.pos_y = py
            m.sucursal_id = centro.id if centro else None
    db.session.commit()
    return {m.numero: m for m in Mesa.query.all()}


# ---------------------------------------------------------------------------
# 6. INGREDIENTES + RECETAS
# ---------------------------------------------------------------------------
def seed_inventario(sucursales, productos):
    print("  → Ingredientes + Recetas...")
    centro = sucursales.get('Casa Leones Centro')
    sid = centro.id if centro else None

    ingredientes_data = [
        # Carnes
        ('Barbacoa (maciza)', 'kg', 50.0, 10.0, 280.0),
        ('Barbacoa (panza)', 'kg', 30.0, 8.0, 220.0),
        ('Barbacoa (costilla)', 'kg', 25.0, 5.0, 250.0),
        ('Barbacoa (cabeza)', 'kg', 20.0, 5.0, 200.0),
        ('Barbacoa (lengua)', 'kg', 15.0, 3.0, 350.0),
        ('Barbacoa (cachete)', 'kg', 15.0, 3.0, 300.0),
        ('Carnitas (maciza)', 'kg', 40.0, 10.0, 180.0),
        ('Carnitas (costilla)', 'kg', 25.0, 5.0, 200.0),
        ('Carnitas (tripa)', 'kg', 20.0, 5.0, 150.0),
        ('Carnitas (cuerito)', 'kg', 15.0, 5.0, 120.0),
        ('Pollo deshebrado', 'kg', 20.0, 5.0, 120.0),
        # Masas y Tortillas
        ('Tortilla de maíz', 'pieza', 500.0, 100.0, 1.50),
        ('Masa de maíz (tortillas)', 'kg', 30.0, 10.0, 18.0),
        ('Masa de maíz (tlacoyos)', 'kg', 20.0, 5.0, 20.0),
        # Rellenos de quesadillas
        ('Chicharrón prensado', 'kg', 10.0, 3.0, 160.0),
        ('Champiñones', 'kg', 8.0, 2.0, 90.0),
        ('Queso Oaxaca', 'kg', 12.0, 3.0, 180.0),
        ('Huitlacoche', 'kg', 5.0, 1.0, 250.0),
        ('Mole verde', 'litro', 8.0, 2.0, 80.0),
        ('Jamón', 'kg', 6.0, 2.0, 90.0),
        ('Flor de calabaza', 'kg', 4.0, 1.0, 120.0),
        ('Tinga de pollo', 'kg', 10.0, 3.0, 100.0),
        # Tlacoyos rellenos
        ('Frijol refrito', 'kg', 15.0, 3.0, 30.0),
        ('Requesón', 'kg', 8.0, 2.0, 60.0),
        ('Alberjón', 'kg', 5.0, 2.0, 40.0),
        # Mixiote
        ('Mixiote de pollo preparado', 'pieza', 30.0, 5.0, 45.0),
        # Consomé
        ('Consomé de barbacoa', 'litro', 40.0, 10.0, 25.0),
        # Bebidas
        ('Coca-Cola 355ml', 'pieza', 48.0, 12.0, 12.0),
        ('Coca-Cola Zero 355ml', 'pieza', 24.0, 6.0, 12.0),
        ('Sprite 355ml', 'pieza', 24.0, 6.0, 12.0),
        ('Boing Mango 500ml', 'pieza', 24.0, 6.0, 10.0),
        ('Boing Guayaba 500ml', 'pieza', 24.0, 6.0, 10.0),
        ('Jamaica concentrado', 'litro', 10.0, 3.0, 35.0),
        ('Horchata concentrado', 'litro', 10.0, 3.0, 30.0),
        ('Tamarindo concentrado', 'litro', 10.0, 3.0, 32.0),
        ('Agua embotellada 600ml', 'pieza', 36.0, 12.0, 6.0),
        ('Café de olla concentrado', 'litro', 8.0, 2.0, 40.0),
        ('Cerveza Corona 355ml', 'pieza', 24.0, 6.0, 22.0),
        ('Cerveza Victoria 355ml', 'pieza', 24.0, 6.0, 22.0),
        ('Mix michelada', 'litro', 5.0, 1.0, 45.0),
        # Otros
        ('Salsa verde', 'litro', 10.0, 2.0, 35.0),
        ('Salsa roja', 'litro', 10.0, 2.0, 35.0),
        ('Limones', 'kg', 5.0, 1.0, 40.0),
        ('Cilantro', 'manojo', 20.0, 5.0, 8.0),
        ('Cebolla', 'kg', 10.0, 2.0, 25.0),
        ('Aguacate', 'kg', 8.0, 2.0, 90.0),
        ('Servilletas', 'paquete', 10.0, 3.0, 25.0),
        ('Desechables (platos)', 'paquete', 5.0, 2.0, 60.0),
        ('Bolsas para llevar', 'paquete', 8.0, 2.0, 35.0),
    ]

    ings = {}
    for nombre, unidad, stock, stock_min, costo in ingredientes_data:
        ing = Ingrediente.query.filter_by(nombre=nombre).first()
        if not ing:
            ing = Ingrediente(
                nombre=nombre, unidad=unidad,
                stock_actual=Decimal(str(stock)),
                stock_minimo=Decimal(str(stock_min)),
                costo_unitario=Decimal(str(costo)),
                sucursal_id=sid, activo=True,
            )
            db.session.add(ing)
        else:
            ing.stock_actual = Decimal(str(stock))
            ing.costo_unitario = Decimal(str(costo))
        ings[nombre] = ing
    db.session.commit()
    ings = {i.nombre: i for i in Ingrediente.query.all()}

    # Recetas (producto → ingrediente, cantidad por unidad)
    recetas = [
        # Tacos de barbacoa — each taco uses ~0.08 kg meat + 2 tortillas
        ('Espaldilla', 'Barbacoa (maciza)', 0.08),
        ('Espaldilla', 'Tortilla de maíz', 2),
        ('Falda', 'Barbacoa (maciza)', 0.08),
        ('Falda', 'Tortilla de maíz', 2),
        ('Costilla', 'Barbacoa (costilla)', 0.08),
        ('Costilla', 'Tortilla de maíz', 2),
        ('Maciza', 'Barbacoa (maciza)', 0.08),
        ('Maciza', 'Tortilla de maíz', 2),
        ('Panza', 'Barbacoa (panza)', 0.08),
        ('Panza', 'Tortilla de maíz', 2),
        ('Cabeza', 'Barbacoa (cabeza)', 0.08),
        ('Cabeza', 'Tortilla de maíz', 2),
        ('Lengua', 'Barbacoa (lengua)', 0.08),
        ('Lengua', 'Tortilla de maíz', 2),
        ('Cachete', 'Barbacoa (cachete)', 0.08),
        ('Cachete', 'Tortilla de maíz', 2),
        # Tacos de carnitas
        ('Maciza (carnitas)', 'Carnitas (maciza)', 0.08),
        ('Maciza (carnitas)', 'Tortilla de maíz', 2),
        ('Costilla (carnitas)', 'Carnitas (costilla)', 0.08),
        ('Costilla (carnitas)', 'Tortilla de maíz', 2),
        ('Tripa', 'Carnitas (tripa)', 0.08),
        ('Tripa', 'Tortilla de maíz', 2),
        ('Cuerito', 'Carnitas (cuerito)', 0.08),
        ('Cuerito', 'Tortilla de maíz', 2),
        # Pollo
        ('Taco de pollo', 'Pollo deshebrado', 0.08),
        ('Taco de pollo', 'Tortilla de maíz', 2),
        # Quesadillas
        ('Quesadilla de Chicharrón prensado', 'Chicharrón prensado', 0.05),
        ('Quesadilla de Chicharrón prensado', 'Queso Oaxaca', 0.04),
        ('Quesadilla de Chicharrón prensado', 'Masa de maíz (tortillas)', 0.08),
        ('Quesadilla de Champiñón', 'Champiñones', 0.06),
        ('Quesadilla de Champiñón', 'Queso Oaxaca', 0.04),
        ('Quesadilla de Champiñón', 'Masa de maíz (tortillas)', 0.08),
        ('Quesadilla de Queso', 'Queso Oaxaca', 0.08),
        ('Quesadilla de Queso', 'Masa de maíz (tortillas)', 0.08),
        ('Quesadilla de Huitlacoche', 'Huitlacoche', 0.05),
        ('Quesadilla de Huitlacoche', 'Queso Oaxaca', 0.04),
        ('Quesadilla de Huitlacoche', 'Masa de maíz (tortillas)', 0.08),
        ('Quesadilla de Flor de calabaza', 'Flor de calabaza', 0.05),
        ('Quesadilla de Flor de calabaza', 'Queso Oaxaca', 0.04),
        ('Quesadilla de Flor de calabaza', 'Masa de maíz (tortillas)', 0.08),
        ('Quesadilla de Tinga', 'Tinga de pollo', 0.06),
        ('Quesadilla de Tinga', 'Queso Oaxaca', 0.04),
        ('Quesadilla de Tinga', 'Masa de maíz (tortillas)', 0.08),
        # Porciones
        ('1 kg Barbacoa', 'Barbacoa (maciza)', 1.0),
        ('3/4 kg Barbacoa', 'Barbacoa (maciza)', 0.75),
        ('1/2 kg Barbacoa', 'Barbacoa (maciza)', 0.5),
        ('1/4 kg Barbacoa', 'Barbacoa (maciza)', 0.25),
        ('1 kg Carnitas', 'Carnitas (maciza)', 1.0),
        ('3/4 kg Carnitas', 'Carnitas (maciza)', 0.75),
        ('1/2 kg Carnitas', 'Carnitas (maciza)', 0.5),
        ('1/4 kg Carnitas', 'Carnitas (maciza)', 0.25),
        # Consomé
        ('Plato de consomé', 'Consomé de barbacoa', 0.35),
        ('1 litro de consomé', 'Consomé de barbacoa', 1.0),
        ('1/2 litro de consomé', 'Consomé de barbacoa', 0.5),
        # Mixiote
        ('Mixiote de Pollo (llevar)', 'Mixiote de pollo preparado', 1),
        ('Mixiote de Pollo (aquí)', 'Mixiote de pollo preparado', 1),
        # Bebidas directas
        ('Coca-Cola', 'Coca-Cola 355ml', 1),
        ('Coca-Cola Zero', 'Coca-Cola Zero 355ml', 1),
        ('Sprite', 'Sprite 355ml', 1),
        ('Boing Mango', 'Boing Mango 500ml', 1),
        ('Boing Guayaba', 'Boing Guayaba 500ml', 1),
        ('Agua Jamaica', 'Jamaica concentrado', 0.15),
        ('Agua Horchata', 'Horchata concentrado', 0.15),
        ('Agua Tamarindo', 'Tamarindo concentrado', 0.15),
        ('Agua Natural 600ml', 'Agua embotellada 600ml', 1),
        ('Café de olla', 'Café de olla concentrado', 0.15),
        ('Cerveza Corona', 'Cerveza Corona 355ml', 1),
        ('Cerveza Victoria', 'Cerveza Victoria 355ml', 1),
        ('Michelada', 'Cerveza Victoria 355ml', 1),
        ('Michelada', 'Mix michelada', 0.1),
    ]

    for prod_name, ing_name, qty in recetas:
        p = productos.get(prod_name)
        i = ings.get(ing_name)
        if p and i:
            existing = RecetaDetalle.query.filter_by(producto_id=p.id, ingrediente_id=i.id).first()
            if not existing:
                db.session.add(RecetaDetalle(
                    producto_id=p.id,
                    ingrediente_id=i.id,
                    cantidad_por_unidad=Decimal(str(qty)),
                ))
    db.session.commit()
    return ings


# ---------------------------------------------------------------------------
# 7. CLIENTES
# ---------------------------------------------------------------------------
def seed_clientes():
    print("  → Clientes...")
    data = [
        {'nombre': 'Público en General', 'telefono': '', 'email': '', 'rfc': 'XAXX010101000',
         'razon_social': 'PUBLICO EN GENERAL', 'uso_cfdi': 'S01', 'regimen_fiscal': '616',
         'domicilio_fiscal': '06600', 'notas': 'Cliente genérico para venta mostrador', 'visitas': 245, 'total_gastado': 38500},
        {'nombre': 'Juan Pérez Martínez', 'telefono': '55-1234-0001', 'email': 'juan.perez@gmail.com', 'rfc': 'PEMJ850315AB1',
         'razon_social': 'JUAN PÉREZ MARTÍNEZ', 'uso_cfdi': 'G03', 'regimen_fiscal': '612',
         'domicilio_fiscal': '03100', 'notas': 'Cliente frecuente — siempre pide barbacoa', 'visitas': 32, 'total_gastado': 8750},
        {'nombre': 'Restaurante Los Compadres SA', 'telefono': '55-9876-5432', 'email': 'compras@loscompadres.mx', 'rfc': 'RLC200101KJ8',
         'razon_social': 'RESTAURANTE LOS COMPADRES SA DE CV', 'uso_cfdi': 'G03', 'regimen_fiscal': '601',
         'domicilio_fiscal': '06700', 'notas': 'Compra por mayoreo cada semana', 'visitas': 18, 'total_gastado': 24300},
        {'nombre': 'María Fernanda García', 'telefono': '55-5555-1234', 'email': 'mfgarcia@outlook.com', 'rfc': 'GAFM900722PQ3',
         'razon_social': 'MARÍA FERNANDA GARCÍA LÓPEZ', 'uso_cfdi': 'G03', 'regimen_fiscal': '612',
         'domicilio_fiscal': '04100', 'notas': '', 'visitas': 15, 'total_gastado': 4200},
        {'nombre': 'Corporativo TechMex', 'telefono': '55-2233-4455', 'email': 'admin@techmex.mx', 'rfc': 'CTE180501HN7',
         'razon_social': 'CORPORATIVO TECHMEX SA DE CV', 'uso_cfdi': 'G03', 'regimen_fiscal': '601',
         'domicilio_fiscal': '11520', 'notas': 'Pedidos para eventos corporativos', 'visitas': 8, 'total_gastado': 15600},
        {'nombre': 'Pedro Sánchez', 'telefono': '55-7788-9900', 'email': 'pedro.s@yahoo.com', 'rfc': '',
         'razon_social': '', 'uso_cfdi': '', 'regimen_fiscal': '',
         'domicilio_fiscal': '', 'notas': 'Solo paga en efectivo', 'visitas': 45, 'total_gastado': 6200},
        {'nombre': 'Laura Jiménez', 'telefono': '55-4411-2233', 'email': 'laura.j@gmail.com', 'rfc': 'JILL880430RR5',
         'razon_social': 'LAURA JIMÉNEZ LUNA', 'uso_cfdi': 'G03', 'regimen_fiscal': '612',
         'domicilio_fiscal': '03810', 'notas': 'Siempre pide para llevar', 'visitas': 22, 'total_gastado': 5400},
        {'nombre': 'Familia Rodríguez', 'telefono': '55-6677-8899', 'email': '', 'rfc': '',
         'razon_social': '', 'uso_cfdi': '', 'regimen_fiscal': '',
         'domicilio_fiscal': '', 'notas': 'Vienen domingos con niños, mesa grande', 'visitas': 12, 'total_gastado': 9800},
        {'nombre': 'Lic. Roberto Mendoza', 'telefono': '55-3344-5566', 'email': 'rmendoza@bufete.mx', 'rfc': 'MEMR750612AB2',
         'razon_social': 'ROBERTO MENDOZA RÍOS', 'uso_cfdi': 'G03', 'regimen_fiscal': '612',
         'domicilio_fiscal': '06600', 'notas': 'Siempre requiere factura', 'visitas': 28, 'total_gastado': 11200},
        {'nombre': 'Escuela Primaria Benito Juárez', 'telefono': '55-1122-3344', 'email': 'direccion@primariabj.mx', 'rfc': 'EPB000101AA0',
         'razon_social': 'ESCUELA PRIMARIA BENITO JUÁREZ', 'uso_cfdi': 'G03', 'regimen_fiscal': '603',
         'domicilio_fiscal': '04000', 'notas': 'Pedido especial para eventos', 'visitas': 3, 'total_gastado': 4500},
    ]

    for d in data:
        c = Cliente.query.filter_by(nombre=d['nombre']).first()
        if not c:
            c = Cliente(**d)
            db.session.add(c)
        else:
            for k, v in d.items():
                setattr(c, k, v)
    db.session.commit()
    return {c.nombre: c for c in Cliente.query.all()}


# ---------------------------------------------------------------------------
# 8. RESERVACIONES
# ---------------------------------------------------------------------------
def seed_reservaciones(clientes, mesas, usuarios):
    print("  → Reservaciones...")
    admin = next((u for u in usuarios.values() if u.rol == 'admin'), None)

    data = [
        {'nombre_contacto': 'Juan Pérez', 'telefono': '55-1234-0001', 'mesa_num': '6',
         'fecha_hora': NOW + timedelta(hours=2), 'num_personas': 6, 'estado': 'confirmada',
         'notas': 'Cumpleaños, necesita pastel'},
        {'nombre_contacto': 'Familia Rodríguez', 'telefono': '55-6677-8899', 'mesa_num': '10',
         'fecha_hora': NOW + timedelta(days=1, hours=3), 'num_personas': 8, 'estado': 'confirmada',
         'notas': 'Domingo familiar'},
        {'nombre_contacto': 'Lic. Mendoza', 'telefono': '55-3344-5566', 'mesa_num': '3',
         'fecha_hora': NOW + timedelta(days=2, hours=1), 'num_personas': 4, 'estado': 'confirmada',
         'notas': 'Comida de negocios'},
        {'nombre_contacto': 'Laura Jiménez', 'telefono': '55-4411-2233', 'mesa_num': '5',
         'fecha_hora': NOW - timedelta(days=1, hours=2), 'num_personas': 3, 'estado': 'completada',
         'notas': ''},
        {'nombre_contacto': 'Pedro Sánchez', 'telefono': '55-7788-9900', 'mesa_num': '7',
         'fecha_hora': NOW - timedelta(days=2), 'num_personas': 2, 'estado': 'no_show',
         'notas': 'No se presentó'},
        {'nombre_contacto': 'TechMex — evento', 'telefono': '55-2233-4455', 'mesa_num': '9',
         'fecha_hora': NOW + timedelta(days=5, hours=1), 'num_personas': 6, 'estado': 'confirmada',
         'notas': 'Evento corporativo, requiere factura'},
    ]

    # Clear existing
    Reservacion.query.delete()
    for d in data:
        mesa = mesas.get(d['mesa_num'])
        db.session.add(Reservacion(
            mesa_id=mesa.id if mesa else None,
            nombre_contacto=d['nombre_contacto'],
            telefono=d['telefono'],
            fecha_hora=d['fecha_hora'],
            num_personas=d['num_personas'],
            estado=d['estado'],
            notas=d['notas'],
            creada_por=admin.id if admin else None,
        ))
    db.session.commit()


# ---------------------------------------------------------------------------
# 9. ÓRDENES + DETALLES + PAGOS (the big one!)
# ---------------------------------------------------------------------------
def seed_ordenes(productos, mesas, usuarios, clientes, sucursales):
    print("  → Órdenes + Pagos (últimos 30 días)...")
    centro = sucursales.get('Casa Leones Centro')
    sid = centro.id if centro else None

    meseros = [u for u in usuarios.values() if u.rol == 'mesero' and (u.sucursal_id == sid or u.sucursal_id is None)]
    if not meseros:
        meseros = [u for u in usuarios.values() if u.rol == 'mesero']

    # Product pools by popularity
    popular_tacos = ['Espaldilla', 'Maciza', 'Costilla', 'Lengua', 'Cachete',
                     'Campechano maciza con panza', 'Panza', 'Falda']
    carnitas = ['Maciza (carnitas)', 'Costilla (carnitas)', 'Tripa', 'Cuerito']
    quesadillas = ['Quesadilla de Queso', 'Quesadilla de Chicharrón prensado',
                    'Quesadilla de Flor de calabaza', 'Quesadilla de Huitlacoche',
                    'Quesadilla de Tinga', 'Quesadilla de Champiñón']
    tlacoyos = ['Tlacoyo de Frijol', 'Tlacoyo de Requesón', 'Tlacoyo de Barbacoa']
    bebidas = ['Coca-Cola', 'Agua Jamaica', 'Agua Horchata', 'Cerveza Corona',
               'Cerveza Victoria', 'Michelada', 'Boing Mango', 'Café de olla',
               'Agua Natural 600ml', 'Sprite']
    porciones = ['1/4 kg Barbacoa', '1/2 kg Barbacoa', '1/4 kg Carnitas', '1/2 kg Carnitas']
    extras = ['Plato de consomé', '1/2 litro de consomé', 'Orden de tacos dorados (3 flautas)',
              'Mixiote de Pollo (aquí)']

    metodos_pago = ['efectivo', 'tarjeta', 'transferencia']
    canales = ['local'] * 8 + ['uber_eats', 'rappi', 'didi_food']  # 73% local

    mesa_list = list(mesas.values())
    cliente_list = list(clientes.values())

    # Clear transactional data
    print("    (limpiando datos transaccionales previos...)")
    OrdenDetalle.query.delete()
    Pago.query.delete()
    Orden.query.delete()
    db.session.commit()

    ordenes_creadas = []

    # Generate ~180 orders over the last 30 days
    for i in range(180):
        fecha = rand_date(30)
        canal = random.choice(canales)
        es_para_llevar = canal != 'local' or random.random() < 0.15
        mesero = random.choice(meseros)

        if canal == 'local':
            mesa = random.choice(mesa_list)
        else:
            mesa = None

        cliente = random.choice(cliente_list) if random.random() < 0.4 else None

        # Determine state: most are paid, some recent ones are pending/preparing
        if (NOW - fecha).total_seconds() < 3600 * 2:  # last 2 hours
            estado = random.choice(['pendiente', 'preparando', 'listo', 'pagado', 'pagado'])
        else:
            estado = random.choice(['pagado'] * 9 + ['cancelado'])

        orden = Orden(
            mesa_id=mesa.id if mesa else None,
            mesero_id=mesero.id,
            cliente_id=cliente.id if cliente else None,
            sucursal_id=sid,
            estado=estado,
            es_para_llevar=es_para_llevar,
            canal=canal,
            tiempo_registro=fecha,
        )
        db.session.add(orden)
        db.session.flush()

        # Add items
        num_items = random.randint(2, 8)
        order_items = []

        # Almost every order has tacos
        if random.random() < 0.85:
            for _ in range(random.randint(1, 4)):
                taco = random.choice(popular_tacos + carnitas)
                order_items.append((taco, random.randint(1, 4)))

        # Quesadillas ~40%
        if random.random() < 0.4:
            for _ in range(random.randint(1, 2)):
                q = random.choice(quesadillas)
                order_items.append((q, random.randint(1, 3)))

        # Tlacoyos ~20%
        if random.random() < 0.2:
            t = random.choice(tlacoyos)
            order_items.append((t, random.randint(1, 2)))

        # Bebidas — almost always
        if random.random() < 0.9:
            for _ in range(random.randint(1, 3)):
                b = random.choice(bebidas)
                order_items.append((b, 1))

        # Porciones ~15%
        if random.random() < 0.15:
            p = random.choice(porciones)
            order_items.append((p, 1))

        # Extras ~20%
        if random.random() < 0.2:
            e = random.choice(extras)
            order_items.append((e, 1))

        # Ensure at least 2 items
        if len(order_items) < 2:
            order_items.append((random.choice(popular_tacos), random.randint(2, 3)))
            order_items.append((random.choice(bebidas), 1))

        notas_opciones = [
            '', '', '', '', '',  # most without notes
            'Sin cebolla', 'Extra salsa', 'Bien dorado', 'Sin cilantro',
            'Tortilla extra', 'Con todo', 'Poco picante', 'Bien caliente',
        ]

        for prod_name, qty in order_items:
            prod = productos.get(prod_name)
            if prod:
                db.session.add(OrdenDetalle(
                    orden_id=orden.id,
                    producto_id=prod.id,
                    cantidad=qty,
                    precio_unitario=prod.precio,
                    notas=random.choice(notas_opciones),
                    estado='entregado' if estado == 'pagado' else 'pendiente',
                    entregado=estado == 'pagado',
                ))

        # Calculate totals
        orden.calcular_totales()

        # Discounts ~10% of orders
        if random.random() < 0.1 and estado == 'pagado':
            desc_pct = random.choice([5, 10, 15])
            orden.descuento_pct = Decimal(str(desc_pct))
            orden.descuento_motivo = random.choice([
                'Cliente frecuente', 'Promoción del día', 'Cortesía gerente',
                'Error en pedido', 'Cupón descuento',
            ])
            orden.calcular_totales()

        # Propina ~60% of paid meals
        if estado == 'pagado' and random.random() < 0.6:
            pct = random.choice([0.10, 0.15, 0.20])
            propina = float(orden.total or 0) * pct
            orden.propina = Decimal(str(round(propina, 2)))

        # Payment
        if estado == 'pagado':
            orden.fecha_pago = fecha + timedelta(minutes=random.randint(20, 90))
            metodo = random.choice(metodos_pago)
            monto = float(orden.total or 0)

            # Sometimes split payment
            if random.random() < 0.12 and monto > 200:
                split1 = round(monto * 0.6, 2)
                split2 = round(monto - split1, 2)
                db.session.add(Pago(
                    orden_id=orden.id, metodo='efectivo',
                    monto=Decimal(str(split1)), fecha=orden.fecha_pago,
                    registrado_por=mesero.id,
                ))
                db.session.add(Pago(
                    orden_id=orden.id, metodo='tarjeta',
                    monto=Decimal(str(split2)), fecha=orden.fecha_pago,
                    registrado_por=mesero.id,
                ))
            else:
                if metodo == 'efectivo':
                    recibido = round(monto / 50) * 50 + 50  # redondear arriba
                    orden.monto_recibido = Decimal(str(recibido))
                    orden.cambio = Decimal(str(round(recibido - monto, 2)))

                db.session.add(Pago(
                    orden_id=orden.id, metodo=metodo,
                    monto=Decimal(str(monto)), fecha=orden.fecha_pago,
                    registrado_por=mesero.id,
                    referencia=f'REF-{random.randint(10000,99999)}' if metodo != 'efectivo' else None,
                ))

        ordenes_creadas.append(orden)

    db.session.commit()
    print(f"    {len(ordenes_creadas)} órdenes creadas.")
    return ordenes_creadas


# ---------------------------------------------------------------------------
# 10. SALES + SALE_ITEMS (mirror of paid orders for reporting)
# ---------------------------------------------------------------------------
def seed_sales(ordenes, productos_dict, sucursales):
    print("  → Sales (registro de ventas)...")
    centro = sucursales.get('Casa Leones Centro')
    sid = centro.id if centro else None

    SaleItem.query.delete()
    Sale.query.delete()
    db.session.commit()

    count = 0
    for orden in ordenes:
        if orden.estado != 'pagado':
            continue

        sale = Sale(
            fecha_hora=orden.fecha_pago or orden.tiempo_registro,
            mesa_id=orden.mesa_id,
            usuario_id=orden.mesero_id,
            sucursal_id=sid,
            total=orden.total or Decimal('0'),
            estado='cerrada',
        )
        db.session.add(sale)
        db.session.flush()

        for det in orden.detalles:
            db.session.add(SaleItem(
                sale_id=sale.id,
                producto_id=det.producto_id,
                cantidad=det.cantidad,
                precio_unitario=det.precio_unitario or det.producto.precio,
                subtotal=(det.precio_unitario or det.producto.precio) * det.cantidad,
            ))
        count += 1

    db.session.commit()
    print(f"    {count} sales creadas.")


# ---------------------------------------------------------------------------
# 11. MOVIMIENTOS DE INVENTARIO
# ---------------------------------------------------------------------------
def seed_movimientos(ordenes, usuarios, ingredientes):
    print("  → Movimientos de inventario...")
    MovimientoInventario.query.delete()
    db.session.commit()

    admin = next((u for u in usuarios.values() if u.rol in ('admin', 'superadmin')), None)
    admin_id = admin.id if admin else 1

    # Initial entries — big restock 30 days ago
    for ing in ingredientes.values():
        db.session.add(MovimientoInventario(
            ingrediente_id=ing.id,
            tipo='entrada',
            cantidad=ing.stock_actual * 3,  # started with 3x current stock
            costo=ing.costo_unitario * ing.stock_actual * 3,
            motivo='Reabastecimiento semanal',
            usuario_id=admin_id,
            fecha=NOW - timedelta(days=30),
        ))

    # Some mermas (wastage)
    merma_items = random.sample(list(ingredientes.values()), min(8, len(ingredientes)))
    for ing in merma_items:
        qty = float(ing.stock_actual) * random.uniform(0.02, 0.08)
        db.session.add(MovimientoInventario(
            ingrediente_id=ing.id,
            tipo='merma',
            cantidad=Decimal(str(round(qty, 4))),
            motivo=random.choice([
                'Producto caducado', 'Se echó a perder', 'Derrame accidental',
                'Error de preparación', 'Merma natural',
            ]),
            usuario_id=admin_id,
            fecha=rand_date(15),
        ))

    # Additional weekly restock
    for week in range(1, 4):
        for ing in random.sample(list(ingredientes.values()), min(15, len(ingredientes))):
            qty = float(ing.stock_actual) * random.uniform(0.5, 1.5)
            db.session.add(MovimientoInventario(
                ingrediente_id=ing.id,
                tipo='entrada',
                cantidad=Decimal(str(round(qty, 4))),
                costo=Decimal(str(round(float(ing.costo_unitario) * qty, 2))),
                motivo='Reabastecimiento semanal',
                usuario_id=admin_id,
                fecha=NOW - timedelta(days=7 * week),
            ))

    db.session.commit()


# ---------------------------------------------------------------------------
# 12. CORTE DE CAJA
# ---------------------------------------------------------------------------
def seed_cortes(ordenes, usuarios, sucursales):
    print("  → Cortes de caja...")
    CorteCaja.query.delete()
    db.session.commit()

    centro = sucursales.get('Casa Leones Centro')
    sid = centro.id if centro else None
    admin = next((u for u in usuarios.values() if u.rol in ('admin', 'superadmin')), None)

    # Group paid orders by date
    from collections import defaultdict
    by_date = defaultdict(list)
    for o in ordenes:
        if o.estado == 'pagado' and o.fecha_pago:
            by_date[o.fecha_pago.date()].append(o)

    for fecha, ords in sorted(by_date.items()):
        total = sum(float(o.total or 0) for o in ords)
        efectivo = sum(float(p.monto) for o in ords for p in o.pagos if p.metodo == 'efectivo')
        tarjeta = sum(float(p.monto) for o in ords for p in o.pagos if p.metodo == 'tarjeta')
        transf = sum(float(p.monto) for o in ords for p in o.pagos if p.metodo == 'transferencia')

        # Simulate a small counting difference
        diff = round(random.uniform(-20, 20), 2)

        db.session.add(CorteCaja(
            fecha=fecha,
            sucursal_id=sid,
            total_ingresos=Decimal(str(round(total, 2))),
            num_ordenes=len(ords),
            efectivo_esperado=Decimal(str(round(efectivo, 2))),
            efectivo_contado=Decimal(str(round(efectivo + diff, 2))),
            diferencia=Decimal(str(round(diff, 2))),
            tarjeta_total=Decimal(str(round(tarjeta, 2))),
            transferencia_total=Decimal(str(round(transf, 2))),
            notas='Corte automático' if abs(diff) < 10 else 'Diferencia revisada por gerente',
            usuario_id=admin.id if admin else 1,
        ))

    db.session.commit()
    print(f"    {len(by_date)} cortes de caja creados.")


# ---------------------------------------------------------------------------
# 13. FACTURAS
# ---------------------------------------------------------------------------
def seed_facturas(ordenes, clientes):
    print("  → Facturas...")
    NotaCredito.query.delete()
    Factura.query.delete()
    db.session.commit()

    # Pick ~25 paid orders that have clients with RFC
    facturables = [o for o in ordenes if o.estado == 'pagado' and o.cliente_id]
    random.shuffle(facturables)
    facturables = facturables[:25]

    facturas = []
    formas_pago = {'efectivo': '01', 'tarjeta': '04', 'transferencia': '03'}

    for o in facturables:
        cliente = Cliente.query.get(o.cliente_id)
        if not cliente or not cliente.rfc:
            continue

        metodo_pago = o.pagos[0].metodo if o.pagos else 'efectivo'
        fpago = formas_pago.get(metodo_pago, '01')
        es_ppd = random.random() < 0.15  # 15% PPD

        f = Factura(
            orden_id=o.id,
            cliente_id=cliente.id,
            rfc_receptor=cliente.rfc,
            razon_social=cliente.razon_social or cliente.nombre.upper(),
            uso_cfdi=cliente.uso_cfdi or 'G03',
            regimen_fiscal=cliente.regimen_fiscal or '612',
            domicilio_fiscal=cliente.domicilio_fiscal or '06600',
            subtotal=o.subtotal or Decimal('0'),
            iva=o.iva or Decimal('0'),
            total=o.total or Decimal('0'),
            estado='timbrada',
            forma_pago=fpago,
            metodo_pago_cfdi='PPD' if es_ppd else 'PUE',
            uuid_cfdi=f'{random.randint(10000000,99999999):08x}-{random.randint(1000,9999):04x}-{random.randint(1000,9999):04x}-{random.randint(1000,9999):04x}-{random.randint(100000000000,999999999999):012x}',
            serie='A',
            folio=str(len(facturas) + 1001),
            fecha_timbrado=o.fecha_pago,
            fecha_creacion=o.fecha_pago,
        )
        db.session.add(f)
        facturas.append(f)

    db.session.commit()

    # Create 2 notas de crédito
    if len(facturas) >= 3:
        for i, factura in enumerate(facturas[:2]):
            db.session.add(NotaCredito(
                factura_origen_id=factura.id,
                uuid_cfdi=f'NC-{random.randint(10000000,99999999):08x}-{random.randint(1000,9999):04x}-{random.randint(1000,9999):04x}-{random.randint(1000,9999):04x}-{random.randint(100000000000,999999999999):012x}',
                motivo=random.choice(['Error en datos fiscales', 'Devolución parcial']),
                subtotal=factura.subtotal,
                iva=factura.iva,
                monto=factura.total,
                estado='timbrada',
            ))
        db.session.commit()

    print(f"    {len(facturas)} facturas + 2 notas de crédito creadas.")


# ---------------------------------------------------------------------------
# 14. DELIVERY
# ---------------------------------------------------------------------------
def seed_delivery(ordenes):
    print("  → Delivery órdenes...")
    DeliveryOrden.query.delete()
    db.session.commit()

    delivery_orders = [o for o in ordenes if o.canal in ('uber_eats', 'rappi', 'didi_food')]
    comisiones = {'uber_eats': 0.30, 'rappi': 0.25, 'didi_food': 0.22}

    nombres = ['Ana García', 'Luis Martínez', 'Carmen Flores', 'Sergio Ruiz',
               'Patricia López', 'Eduardo Díaz', 'Verónica Cruz', 'Miguel Ángel Torres']
    direcciones = [
        'Av. Universidad 1500, Col. Del Valle, CDMX',
        'Calle Moras 235, Col. Del Valle, CDMX',
        'Insurgentes Sur 800, Col. Nápoles, CDMX',
        'Av. Coyoacán 1450, Col. Del Valle, CDMX',
        'Eje 8 Sur 200, Col. Portales, CDMX',
        'Calz. de Tlalpan 1800, Col. Country Club, CDMX',
    ]

    for o in delivery_orders:
        pct = comisiones.get(o.canal, 0.25)
        comision = round(float(o.total or 0) * pct, 2)

        db.session.add(DeliveryOrden(
            plataforma=o.canal,
            external_id=f'{o.canal.upper()}-{random.randint(100000,999999)}',
            orden_id=o.id,
            estado_plataforma='delivered' if o.estado == 'pagado' else 'in_progress',
            cliente_nombre=random.choice(nombres),
            cliente_telefono=f'55-{random.randint(1000,9999)}-{random.randint(1000,9999)}',
            direccion_entrega=random.choice(direcciones),
            total_plataforma=o.total,
            comision=Decimal(str(comision)),
            fecha_recibido=o.tiempo_registro,
            fecha_aceptado=o.tiempo_registro + timedelta(minutes=random.randint(1, 5)),
            fecha_listo=o.tiempo_registro + timedelta(minutes=random.randint(15, 40)) if o.estado == 'pagado' else None,
        ))

    db.session.commit()
    print(f"    {len(delivery_orders)} delivery órdenes creadas.")


# ---------------------------------------------------------------------------
# 15. AUDIT LOG
# ---------------------------------------------------------------------------
def seed_audit_log(usuarios, ordenes):
    print("  → Audit log...")
    AuditLog.query.delete()
    db.session.commit()

    admin = next((u for u in usuarios.values() if u.rol in ('admin', 'superadmin')), None)
    admin_id = admin.id if admin else 1
    meseros = [u for u in usuarios.values() if u.rol == 'mesero']

    logs = []

    # Login/logout events
    for _ in range(40):
        u = random.choice(list(usuarios.values()))
        fecha = rand_date(30)
        logs.append(AuditLog(
            usuario_id=u.id, accion='login', entidad='Usuario', entidad_id=u.id,
            descripcion=f'Inicio de sesión: {u.nombre}',
            ip_address='192.168.1.' + str(random.randint(10, 200)),
            user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)',
            fecha=fecha,
        ))
        logs.append(AuditLog(
            usuario_id=u.id, accion='logout', entidad='Usuario', entidad_id=u.id,
            descripcion=f'Cierre de sesión: {u.nombre}',
            ip_address='192.168.1.' + str(random.randint(10, 200)),
            user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)',
            fecha=fecha + timedelta(hours=random.randint(2, 8)),
        ))

    # Payment events
    paid = [o for o in ordenes if o.estado == 'pagado']
    for o in random.sample(paid, min(30, len(paid))):
        logs.append(AuditLog(
            usuario_id=o.mesero_id, accion='pago', entidad='Orden', entidad_id=o.id,
            descripcion=f'Pago registrado: Orden #{o.id} — ${float(o.total or 0):.2f}',
            ip_address='192.168.1.' + str(random.randint(10, 200)),
            fecha=o.fecha_pago or o.tiempo_registro,
        ))

    # Product changes
    for _ in range(5):
        logs.append(AuditLog(
            usuario_id=admin_id, accion='editar', entidad='Producto',
            entidad_id=random.randint(1, 50),
            descripcion='Precio actualizado',
            ip_address='192.168.1.10',
            fecha=rand_date(20),
        ))

    # Facturación
    for _ in range(8):
        logs.append(AuditLog(
            usuario_id=admin_id, accion='crear_factura', entidad='Factura',
            entidad_id=random.randint(1, 20),
            descripcion='Factura CFDI timbrada exitosamente',
            ip_address='192.168.1.10',
            fecha=rand_date(25),
        ))

    for log in logs:
        db.session.add(log)
    db.session.commit()
    print(f"    {len(logs)} registros de auditoría creados.")


# ---------------------------------------------------------------------------
# 16. SET SOME ACTIVE STATES (mesas occupadas, órdenes activas)
# ---------------------------------------------------------------------------
def seed_active_state(mesas, ordenes):
    print("  → Estado activo (mesas ocupadas, etc.)...")

    # Reset all mesas to available
    for m in mesas.values():
        m.estado = 'disponible'

    # Recent active orders → occupy their mesas
    active = [o for o in ordenes if o.estado in ('pendiente', 'preparando', 'listo') and o.mesa_id]
    for o in active:
        mesa = Mesa.query.get(o.mesa_id)
        if mesa:
            mesa.estado = 'ocupada'

    # One mesa in maintenance
    if '12' in mesas:
        mesas['12'].estado = 'mantenimiento'

    # One reserved
    if '6' in mesas:
        mesas['6'].estado = 'reservada'

    db.session.commit()


# ===========================================================================
# MAIN
# ===========================================================================
def main():
    print("\n🌮 CasaLeones — Seeder de datos demo")
    print("=" * 50)

    app = create_app()
    with app.app_context():
        # Ensure ALL tables exist (e.g. configuracion_sistema may be missing)
        db.create_all()

        # 1. Config
        seed_configuracion()

        # 2. Sucursales
        sucursales = seed_sucursales()

        # 3. Usuarios
        usuarios = seed_usuarios(sucursales)

        # 4. Catálogo
        productos = seed_catalogo()

        # 5. Mesas
        mesas = seed_mesas(sucursales)

        # 6. Inventario
        ingredientes = seed_inventario(sucursales, productos)

        # 7. Clientes
        clientes = seed_clientes()

        # 8. Reservaciones
        seed_reservaciones(clientes, mesas, usuarios)

        # 9. Órdenes + Pagos
        ordenes = seed_ordenes(productos, mesas, usuarios, clientes, sucursales)

        # 10. Sales
        seed_sales(ordenes, productos, sucursales)

        # 11. Movimientos inventario
        seed_movimientos(ordenes, usuarios, ingredientes)

        # 12. Cortes de caja
        seed_cortes(ordenes, usuarios, sucursales)

        # 13. Facturas
        seed_facturas(ordenes, clientes)

        # 14. Delivery
        seed_delivery(ordenes)

        # 15. Audit log
        seed_audit_log(usuarios, ordenes)

        # 16. Active state
        seed_active_state(mesas, ordenes)

        print("\n" + "=" * 50)
        print("✅ SEED COMPLETO — Resumen:")
        print(f"   Sucursales:    {Sucursal.query.count()}")
        print(f"   Usuarios:      {Usuario.query.count()}")
        print(f"   Categorías:    {len(set(p.categoria_id for p in Producto.query.all()))}")
        print(f"   Productos:     {Producto.query.count()}")
        print(f"   Mesas:         {Mesa.query.count()}")
        print(f"   Ingredientes:  {Ingrediente.query.count()}")
        print(f"   Recetas:       {RecetaDetalle.query.count()}")
        print(f"   Clientes:      {Cliente.query.count()}")
        print(f"   Reservaciones: {Reservacion.query.count()}")
        print(f"   Órdenes:       {Orden.query.count()}")
        print(f"   Pagos:         {Pago.query.count()}")
        print(f"   Sales:         {Sale.query.count()}")
        print(f"   SaleItems:     {SaleItem.query.count()}")
        print(f"   Facturas:      {Factura.query.count()}")
        print(f"   Notas Crédito: {NotaCredito.query.count()}")
        print(f"   Delivery:      {DeliveryOrden.query.count()}")
        print(f"   Cortes Caja:   {CorteCaja.query.count()}")
        print(f"   Mov Inventario:{MovimientoInventario.query.count()}")
        print(f"   Audit Logs:    {AuditLog.query.count()}")
        print()
        print("👤 Login: marco@casaleones.mx / CasaLeones2026!")
        print("👤 Admin: admin@casaleones.mx / CasaLeones2026!")
        print()


if __name__ == '__main__':
    main()
