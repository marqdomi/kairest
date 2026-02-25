from datetime import datetime
from decimal import Decimal
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import UserMixin

from backend.extensions import db

# -------------------- CONSTANTES FISCALES --------------------
IVA_RATE = Decimal('0.16')  # 16% IVA México


# -------------------- CONFIGURACIÓN DEL SISTEMA (Fase 7 - Onboarding) --------------------

class ConfiguracionSistema(db.Model):
    """Key-value store for system-wide configuration.
    Used for onboarding state, system mode, and business settings."""
    __tablename__ = 'configuracion_sistema'
    id = db.Column(db.Integer, primary_key=True)
    clave = db.Column(db.String(100), unique=True, nullable=False, index=True)
    valor = db.Column(db.Text, nullable=True)

    @staticmethod
    def get(clave, default=None):
        """Get a config value by key."""
        row = ConfiguracionSistema.query.filter_by(clave=clave).first()
        return row.valor if row else default

    @staticmethod
    def set(clave, valor):
        """Set a config value (upsert)."""
        row = ConfiguracionSistema.query.filter_by(clave=clave).first()
        if row:
            row.valor = str(valor)
        else:
            row = ConfiguracionSistema(clave=clave, valor=str(valor))
            db.session.add(row)
        db.session.flush()
        return row

    @staticmethod
    def get_bool(clave, default=False):
        """Get a config value as boolean."""
        val = ConfiguracionSistema.get(clave)
        if val is None:
            return default
        return val.lower() in ('true', '1', 'yes', 'si')

    def __repr__(self):
        return f"<Config {self.clave}={self.valor}>"


# -------------------- MULTI-SUCURSAL (Fase 4 - Item 23) --------------------

class Sucursal(db.Model):
    __tablename__ = 'sucursales'
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100), nullable=False, unique=True)
    direccion = db.Column(db.String(300), nullable=True)
    telefono = db.Column(db.String(20), nullable=True)
    activa = db.Column(db.Boolean, default=True)
    fecha_creacion = db.Column(db.DateTime, default=datetime.utcnow)

    # White-label customization (Fase 9)
    logo_url = db.Column(db.String(500), nullable=True)       # Path to uploaded logo
    color_primario = db.Column(db.String(7), default='#C41E3A')  # Hex color
    slogan = db.Column(db.String(200), nullable=True)
    rfc = db.Column(db.String(13), nullable=True)              # For tickets/facturas

    usuarios = db.relationship('Usuario', backref='sucursal', lazy=True)
    mesas = db.relationship('Mesa', backref='sucursal', lazy=True)


# -------------------- MODELOS --------------------

class Usuario(UserMixin, db.Model):
    # Roles estáticos: superadmin, admin, mesero, cocina
    # Los usuarios con rol='cocina' se asocian a una estación vía estacion_id
    ROLES_ESTATICOS = ['superadmin', 'admin', 'mesero', 'cocina']

    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100), nullable=False)
    rol = db.Column(db.String(50), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256))
    sucursal_id = db.Column(db.Integer, db.ForeignKey('sucursales.id'), nullable=True)
    estacion_id = db.Column(db.Integer, db.ForeignKey('estacion.id'), nullable=True)
    estacion = db.relationship('Estacion', backref='usuarios', lazy=True)

    @property
    def es_cocina(self):
        """True si el usuario es un trabajador de cocina (rol='cocina' o rol legacy de estación)."""
        if self.rol == 'cocina':
            return True
        # Backward compatibility: roles legacy (taquero, comal, bebidas, etc.)
        return self.rol not in self.ROLES_ESTATICOS and self.rol != ''

    @property
    def estacion_nombre(self):
        """Nombre de la estación asignada (vía FK o rol legacy)."""
        if self.estacion_id and self.estacion:
            return self.estacion.nombre
        # Backward compatibility: el rol es el nombre de la estación
        if self.es_cocina and self.rol != 'cocina':
            return self.rol
        return None

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def __repr__(self):
        return f"<Usuario id={self.id} email={self.email}>"


class Categoria(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(50), unique=True, nullable=False)


class Estacion(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(50), unique=True, nullable=False)
    productos = db.relationship('Producto', backref='estacion', lazy=True)


class Producto(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(150), nullable=False)
    precio = db.Column(db.Numeric(10, 2), nullable=False)
    unidad = db.Column(db.String(50))
    descripcion = db.Column(db.Text)

    categoria_id = db.Column(db.Integer, db.ForeignKey('categoria.id'), nullable=False)
    categoria = db.relationship('Categoria', backref='productos')

    estacion_id = db.Column(db.Integer, db.ForeignKey('estacion.id'), nullable=True)

    # Fase 3: relación con receta
    receta_items = db.relationship('RecetaDetalle', backref='producto', lazy=True)

    def to_dict(self):
        return {
            'id': self.id,
            'nombre': self.nombre,
            'precio': float(self.precio),
            'unidad': self.unidad,
            'descripcion': self.descripcion,
            'categoria': self.categoria.nombre if self.categoria else None,
            'estacion': self.estacion.nombre if self.estacion else None,
        }


class Mesa(db.Model):
    __table_args__ = (
        db.UniqueConstraint('numero', 'sucursal_id', name='uq_mesa_numero_sucursal'),
    )
    id = db.Column(db.Integer, primary_key=True)
    numero = db.Column(db.String(10), nullable=False)
    capacidad = db.Column(db.Integer, default=4)
    estado = db.Column(db.String(20), default='disponible')
    zona = db.Column(db.String(50), nullable=True)
    pos_x = db.Column(db.Integer, nullable=True)
    pos_y = db.Column(db.Integer, nullable=True)
    sucursal_id = db.Column(db.Integer, db.ForeignKey('sucursales.id'), nullable=True)

    ordenes = db.relationship('Orden', backref='mesa', lazy=True)
    reservaciones = db.relationship('Reservacion', backref='mesa', lazy=True)


# -------------------- CLIENTES / CRM (Fase 3 - Item 20) --------------------

class Cliente(db.Model):
    __tablename__ = 'clientes'
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(150), nullable=False)
    telefono = db.Column(db.String(20), nullable=True)
    email = db.Column(db.String(120), nullable=True)
    rfc = db.Column(db.String(13), nullable=True)
    razon_social = db.Column(db.String(200), nullable=True)
    uso_cfdi = db.Column(db.String(10), nullable=True)  # G03, P01, etc.
    regimen_fiscal = db.Column(db.String(5), nullable=True)  # 601, 612, 616, etc.
    domicilio_fiscal = db.Column(db.String(10), nullable=True)  # CP
    notas = db.Column(db.Text, nullable=True)
    fecha_registro = db.Column(db.DateTime, default=datetime.utcnow)
    visitas = db.Column(db.Integer, default=0)
    total_gastado = db.Column(db.Numeric(12, 2), default=0)

    ordenes = db.relationship('Orden', backref='cliente', lazy=True)
    facturas = db.relationship('Factura', backref='cliente', lazy=True)


# -------------------- RESERVACIONES (Fase 3 - Item 19) --------------------

class Reservacion(db.Model):
    __tablename__ = 'reservaciones'
    id = db.Column(db.Integer, primary_key=True)
    mesa_id = db.Column(db.Integer, db.ForeignKey('mesa.id'), nullable=True)
    cliente_id = db.Column(db.Integer, db.ForeignKey('clientes.id'), nullable=True)
    nombre_contacto = db.Column(db.String(150), nullable=False)
    telefono = db.Column(db.String(20), nullable=True)
    fecha_hora = db.Column(db.DateTime, nullable=False)
    num_personas = db.Column(db.Integer, default=2)
    estado = db.Column(db.String(20), default='confirmada')  # confirmada, cancelada, completada, no_show
    notas = db.Column(db.Text, nullable=True)
    creada_por = db.Column(db.Integer, db.ForeignKey('usuario.id'), nullable=True)
    fecha_creacion = db.Column(db.DateTime, default=datetime.utcnow)

    cliente_rel = db.relationship('Cliente', overlaps='reservaciones')
    usuario = db.relationship('Usuario')


# -------------------- ÓRDENES --------------------

class Orden(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    mesa_id = db.Column(db.Integer, db.ForeignKey('mesa.id'))
    mesero_id = db.Column(db.Integer, db.ForeignKey('usuario.id'))
    cliente_id = db.Column(db.Integer, db.ForeignKey('clientes.id'), nullable=True)
    sucursal_id = db.Column(db.Integer, db.ForeignKey('sucursales.id'), nullable=True)
    estado = db.Column(db.String(50), default='pendiente')
    es_para_llevar = db.Column(db.Boolean, default=False)
    canal = db.Column(db.String(30), default='local')  # local, uber_eats, rappi, didi_food
    tiempo_registro = db.Column(db.DateTime, default=datetime.utcnow)
    fecha_pago = db.Column(db.DateTime, nullable=True)
    monto_recibido = db.Column(db.Numeric(10, 2), nullable=True)
    cambio = db.Column(db.Numeric(10, 2), nullable=True)

    # Fase 2: IVA y descuentos
    subtotal = db.Column(db.Numeric(10, 2), nullable=True)
    descuento_pct = db.Column(db.Numeric(5, 2), default=0)
    descuento_monto = db.Column(db.Numeric(10, 2), default=0)
    descuento_motivo = db.Column(db.String(200), nullable=True)
    descuento_autorizado_por = db.Column(db.Integer, db.ForeignKey('usuario.id'), nullable=True)
    iva = db.Column(db.Numeric(10, 2), nullable=True)
    total = db.Column(db.Numeric(10, 2), nullable=True)
    propina = db.Column(db.Numeric(10, 2), default=0)

    mesero = db.relationship('Usuario', foreign_keys=[mesero_id], backref='ordenes')
    autorizador_descuento = db.relationship('Usuario', foreign_keys=[descuento_autorizado_por])
    detalles = db.relationship('OrdenDetalle', backref='orden', lazy=True)
    pagos = db.relationship('Pago', backref='orden', lazy=True, cascade='all, delete-orphan')
    productos = db.relationship('Producto', secondary='orden_detalle', viewonly=True, backref='ordenes')

    def calcular_totales(self):
        """Calcula subtotal, descuento, IVA y total.
        Respects precios_incluyen_iva config from ConfiguracionSistema.
        If True (default): menu prices already include IVA, so we extract IVA from the total.
        If False: IVA is added on top of the menu prices."""
        precios_con_iva = ConfiguracionSistema.get_bool('precios_incluyen_iva', default=True)

        bruto = sum(
            d.cantidad * Decimal(str(d.precio_unitario if d.precio_unitario is not None else d.producto.precio))
            for d in self.detalles
        )

        desc = Decimal('0')
        if self.descuento_pct and self.descuento_pct > 0:
            desc = bruto * (self.descuento_pct / Decimal('100'))
        if self.descuento_monto and self.descuento_monto > 0:
            desc += self.descuento_monto
        desc = min(desc, bruto)

        base_con_descuento = bruto - desc

        if precios_con_iva:
            # Prices already include IVA — extract IVA from total
            self.total = base_con_descuento.quantize(Decimal('0.01'))
            self.iva = (self.total - self.total / (1 + IVA_RATE)).quantize(Decimal('0.01'))
            self.subtotal = (self.total - self.iva).quantize(Decimal('0.01'))
        else:
            # Prices do NOT include IVA — add IVA on top
            self.subtotal = base_con_descuento.quantize(Decimal('0.01'))
            self.iva = (self.subtotal * IVA_RATE).quantize(Decimal('0.01'))
            self.total = (self.subtotal + self.iva).quantize(Decimal('0.01'))

        return self.total

    def total_pagado(self):
        return sum((p.monto for p in self.pagos), Decimal('0'))

    def saldo_pendiente(self):
        t = self.total or Decimal('0')
        return t - self.total_pagado()

    def to_dict(self):
        return {
            'id': self.id,
            'mesa_id': self.mesa_id,
            'mesero_id': self.mesero_id,
            'estado': self.estado,
            'es_para_llevar': self.es_para_llevar,
            'canal': self.canal,
            'tiempo_registro': self.tiempo_registro.isoformat(),
            'fecha_pago': self.fecha_pago.isoformat() if self.fecha_pago else None,
            'subtotal': float(self.subtotal or 0),
            'descuento_pct': float(self.descuento_pct or 0),
            'descuento_monto': float(self.descuento_monto or 0),
            'iva': float(self.iva or 0),
            'total': float(self.total or 0),
            'propina': float(self.propina or 0),
            'cambio': float(self.cambio or 0),
            'detalles': [detalle.to_dict() for detalle in self.detalles],
            'pagos': [{'id': p.id, 'metodo': p.metodo, 'monto': float(p.monto),
                       'fecha': p.fecha.isoformat() if p.fecha else None} for p in self.pagos],
        }


class OrdenDetalle(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    orden_id = db.Column(db.Integer, db.ForeignKey('orden.id'))
    producto_id = db.Column(db.Integer, db.ForeignKey('producto.id'))
    cantidad = db.Column(db.Integer, default=1)
    notas = db.Column(db.String(200))
    estado = db.Column(db.String(20), nullable=False, default='pendiente')
    entregado = db.Column(db.Boolean, default=False)
    precio_unitario = db.Column(db.Numeric(10, 2), nullable=True)
    fecha_listo = db.Column(db.DateTime, nullable=True)

    producto = db.relationship('Producto', backref='orden_detalles')

    def to_dict(self):
        precio = float(self.precio_unitario) if self.precio_unitario is not None else float(self.producto.precio)
        return {
            'id': self.id,
            'orden_id': self.orden_id,
            'producto_id': self.producto_id,
            'cantidad': self.cantidad,
            'notas': self.notas,
            'precio_unitario': precio,
            'producto': self.producto.to_dict(),
            'entregado': self.entregado,
        }


# -------------------- PAGOS (Fase 2) --------------------

class Pago(db.Model):
    __tablename__ = 'pagos'
    id = db.Column(db.Integer, primary_key=True)
    orden_id = db.Column(db.Integer, db.ForeignKey('orden.id'), nullable=False)
    metodo = db.Column(db.String(30), nullable=False)
    monto = db.Column(db.Numeric(10, 2), nullable=False)
    referencia = db.Column(db.String(100), nullable=True)
    fecha = db.Column(db.DateTime, default=datetime.utcnow)
    registrado_por = db.Column(db.Integer, db.ForeignKey('usuario.id'), nullable=False)

    usuario = db.relationship('Usuario')


# -------------------- INVENTARIO (Fase 3 - Item 15) --------------------

class Ingrediente(db.Model):
    __tablename__ = 'ingredientes'
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(150), nullable=False, unique=True)
    unidad = db.Column(db.String(30), nullable=False)  # kg, litro, pieza, gramo
    stock_actual = db.Column(db.Numeric(12, 4), default=0)
    stock_minimo = db.Column(db.Numeric(12, 4), default=0)
    costo_unitario = db.Column(db.Numeric(10, 2), default=0)
    activo = db.Column(db.Boolean, default=True)
    sucursal_id = db.Column(db.Integer, db.ForeignKey('sucursales.id'), nullable=True)

    sucursal = db.relationship('Sucursal', backref='ingredientes')
    movimientos = db.relationship('MovimientoInventario', backref='ingrediente', lazy=True)


class RecetaDetalle(db.Model):
    """Cuánto ingrediente se usa por unidad de producto."""
    __tablename__ = 'receta_detalle'
    id = db.Column(db.Integer, primary_key=True)
    producto_id = db.Column(db.Integer, db.ForeignKey('producto.id'), nullable=False)
    ingrediente_id = db.Column(db.Integer, db.ForeignKey('ingredientes.id'), nullable=False)
    cantidad_por_unidad = db.Column(db.Numeric(12, 4), nullable=False)

    ingrediente = db.relationship('Ingrediente', backref='recetas')

    __table_args__ = (
        db.UniqueConstraint('producto_id', 'ingrediente_id', name='uq_receta_prod_ing'),
    )


class MovimientoInventario(db.Model):
    """Registro de entradas, salidas, mermas y ajustes de stock."""
    __tablename__ = 'movimientos_inventario'
    id = db.Column(db.Integer, primary_key=True)
    ingrediente_id = db.Column(db.Integer, db.ForeignKey('ingredientes.id'), nullable=False)
    tipo = db.Column(db.String(20), nullable=False)  # entrada, salida_venta, merma, ajuste
    cantidad = db.Column(db.Numeric(12, 4), nullable=False)
    costo = db.Column(db.Numeric(10, 2), nullable=True)
    motivo = db.Column(db.String(200), nullable=True)
    orden_id = db.Column(db.Integer, db.ForeignKey('orden.id'), nullable=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey('usuario.id'), nullable=False)
    fecha = db.Column(db.DateTime, default=datetime.utcnow)

    usuario = db.relationship('Usuario')


# -------------------- AUDITORÍA (Sprint 6 - Item 3.5) --------------------

class AuditLog(db.Model):
    """Registro de auditoría para acciones del sistema."""
    __tablename__ = 'audit_log'
    id = db.Column(db.Integer, primary_key=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey('usuario.id'), nullable=True)
    accion = db.Column(db.String(50), nullable=False)  # login, logout, crear, editar, eliminar, pago, cancelar, etc.
    entidad = db.Column(db.String(50), nullable=True)  # Orden, Producto, Usuario, Factura, etc.
    entidad_id = db.Column(db.Integer, nullable=True)
    descripcion = db.Column(db.Text, nullable=True)
    ip_address = db.Column(db.String(45), nullable=True)
    user_agent = db.Column(db.String(300), nullable=True)
    fecha = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    usuario = db.relationship('Usuario', backref='audit_logs')


# -------------------- FACTURACIÓN CFDI (Fase 3 - Item 17) --------------------

class Factura(db.Model):
    __tablename__ = 'facturas'
    id = db.Column(db.Integer, primary_key=True)
    orden_id = db.Column(db.Integer, db.ForeignKey('orden.id'), nullable=False)
    cliente_id = db.Column(db.Integer, db.ForeignKey('clientes.id'), nullable=False)
    uuid_cfdi = db.Column(db.String(40), nullable=True, unique=True)
    serie = db.Column(db.String(10), nullable=True)
    folio = db.Column(db.String(20), nullable=True)
    rfc_receptor = db.Column(db.String(13), nullable=False)
    razon_social = db.Column(db.String(200), nullable=False)
    uso_cfdi = db.Column(db.String(10), default='G03')
    regimen_fiscal = db.Column(db.String(5), nullable=True)
    domicilio_fiscal = db.Column(db.String(10), nullable=True)  # CP
    subtotal = db.Column(db.Numeric(10, 2), nullable=False)
    iva = db.Column(db.Numeric(10, 2), nullable=False)
    total = db.Column(db.Numeric(10, 2), nullable=False)
    estado = db.Column(db.String(20), default='pendiente')  # pendiente, timbrada, cancelada, error
    forma_pago = db.Column(db.String(5), nullable=True)  # 01=Efectivo, 03=Transferencia, 04=Tarjeta
    metodo_pago_cfdi = db.Column(db.String(5), default='PUE')  # PUE=Pago en una sola exhibición, PPD=Parcialidades o diferido
    facturapi_id = db.Column(db.String(50), nullable=True)  # ID interno Facturapi
    xml_url = db.Column(db.String(500), nullable=True)
    pdf_url = db.Column(db.String(500), nullable=True)
    pac_response = db.Column(db.Text, nullable=True)
    fecha_timbrado = db.Column(db.DateTime, nullable=True)
    fecha_creacion = db.Column(db.DateTime, default=datetime.utcnow)

    orden = db.relationship('Orden', backref='facturas')
    notas_credito = db.relationship('NotaCredito', backref='factura_origen', lazy=True)


# -------------------- NOTAS DE CRÉDITO (Sprint 3 - Item 7.2) --------------------

class NotaCredito(db.Model):
    """Nota de crédito CFDI tipo egreso (E) relacionada a una factura."""
    __tablename__ = 'notas_credito'
    id = db.Column(db.Integer, primary_key=True)
    factura_origen_id = db.Column(db.Integer, db.ForeignKey('facturas.id'), nullable=False)
    uuid_cfdi = db.Column(db.String(40), nullable=True, unique=True)
    facturapi_id = db.Column(db.String(50), nullable=True)
    motivo = db.Column(db.String(200), nullable=False)
    subtotal = db.Column(db.Numeric(10, 2), nullable=False)
    iva = db.Column(db.Numeric(10, 2), nullable=False)
    monto = db.Column(db.Numeric(10, 2), nullable=False)  # Total de la NC
    estado = db.Column(db.String(20), default='pendiente')  # pendiente, timbrada, error
    xml_url = db.Column(db.String(500), nullable=True)
    pdf_url = db.Column(db.String(500), nullable=True)
    pac_response = db.Column(db.Text, nullable=True)
    fecha_creacion = db.Column(db.DateTime, default=datetime.utcnow)


# -------------------- VENTAS --------------------

class CorteCaja(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    fecha = db.Column(db.Date, nullable=False)
    sucursal_id = db.Column(db.Integer, db.ForeignKey('sucursales.id'), nullable=True)
    total_ingresos = db.Column(db.Numeric(10, 2), nullable=False)
    num_ordenes = db.Column(db.Integer, nullable=False)
    efectivo_esperado = db.Column(db.Numeric(10, 2), nullable=True)
    efectivo_contado = db.Column(db.Numeric(10, 2), nullable=True)
    diferencia = db.Column(db.Numeric(10, 2), nullable=True)
    tarjeta_total = db.Column(db.Numeric(10, 2), nullable=True)
    transferencia_total = db.Column(db.Numeric(10, 2), nullable=True)
    notas = db.Column(db.Text, nullable=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey('usuario.id'), nullable=False)
    usuario = db.relationship('Usuario', backref='cortes_realizados')


class Sale(db.Model):
    __tablename__ = 'sales'
    id = db.Column(db.Integer, primary_key=True)
    fecha_hora = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    mesa_id = db.Column(db.Integer, db.ForeignKey('mesa.id'), nullable=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey('usuario.id'), nullable=False)
    sucursal_id = db.Column(db.Integer, db.ForeignKey('sucursales.id'), nullable=True)
    total = db.Column(db.Numeric(10, 2), default=0, nullable=False)
    estado = db.Column(db.String(20), default='abierta', nullable=False)
    usuario = db.relationship('Usuario', backref='ventas')
    sucursal = db.relationship('Sucursal', backref='ventas')
    items = db.relationship('SaleItem', backref='sale', cascade='all, delete-orphan')


class SaleItem(db.Model):
    __tablename__ = 'sale_items'
    id = db.Column(db.Integer, primary_key=True)
    sale_id = db.Column(db.Integer, db.ForeignKey('sales.id'), nullable=False)
    producto_id = db.Column(db.Integer, db.ForeignKey('producto.id'), nullable=False)
    cantidad = db.Column(db.Integer, nullable=False)
    precio_unitario = db.Column(db.Numeric(10, 2), nullable=False)
    subtotal = db.Column(db.Numeric(10, 2), nullable=False)
    producto = db.relationship('Producto')


# -------------------- DELIVERY (Fase 4 - Item 21) --------------------

class DeliveryOrden(db.Model):
    """Órdenes recibidas de plataformas externas de delivery."""
    __tablename__ = 'delivery_ordenes'
    id = db.Column(db.Integer, primary_key=True)
    plataforma = db.Column(db.String(30), nullable=False)  # uber_eats, rappi, didi_food
    external_id = db.Column(db.String(100), nullable=False)  # ID en la plataforma
    orden_id = db.Column(db.Integer, db.ForeignKey('orden.id'), nullable=True)
    estado_plataforma = db.Column(db.String(50), nullable=True)
    payload_raw = db.Column(db.Text, nullable=True)  # JSON crudo del webhook
    cliente_nombre = db.Column(db.String(150), nullable=True)
    cliente_telefono = db.Column(db.String(20), nullable=True)
    direccion_entrega = db.Column(db.Text, nullable=True)
    total_plataforma = db.Column(db.Numeric(10, 2), nullable=True)
    comision = db.Column(db.Numeric(10, 2), nullable=True)
    fecha_recibido = db.Column(db.DateTime, default=datetime.utcnow)
    fecha_aceptado = db.Column(db.DateTime, nullable=True)
    fecha_listo = db.Column(db.DateTime, nullable=True)

    orden = db.relationship('Orden', backref='delivery_info')

    __table_args__ = (
        db.UniqueConstraint('plataforma', 'external_id', name='uq_delivery_plat_ext'),
    )


# -------------------- HELPER: descontar inventario al pagar --------------------

def descontar_inventario_por_orden(orden, usuario_id):
    """Descuenta stock de ingredientes según receta estándar de cada producto vendido."""
    for detalle in orden.detalles:
        for receta in detalle.producto.receta_items:
            cantidad_total = receta.cantidad_por_unidad * detalle.cantidad
            receta.ingrediente.stock_actual -= cantidad_total
            mov = MovimientoInventario(
                ingrediente_id=receta.ingrediente_id,
                tipo='salida_venta',
                cantidad=cantidad_total,
                orden_id=orden.id,
                usuario_id=usuario_id,
                motivo=f'Venta orden #{orden.id}',
            )
            db.session.add(mov)
