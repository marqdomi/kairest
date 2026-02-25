"""
Fase 4 — Item 21: Integración con plataformas de delivery.

Scaffolding para Uber Eats, Rappi y DiDi Food.
Cada plataforma envía webhooks con órdenes nuevas. Este servicio:
1. Parsea el payload de cada plataforma
2. Crea una Orden interna + DeliveryOrden
3. Emite socket para notificar a cocina

Configurar en .env:
  UBER_EATS_CLIENT_ID / UBER_EATS_CLIENT_SECRET
  RAPPI_API_KEY
  DIDI_FOOD_API_KEY
"""
import os
import json
import logging
from datetime import datetime
from decimal import Decimal

logger = logging.getLogger(__name__)

UBER_EATS_SECRET = os.getenv('UBER_EATS_WEBHOOK_SECRET', '')
RAPPI_API_KEY = os.getenv('RAPPI_API_KEY', '')
DIDI_FOOD_API_KEY = os.getenv('DIDI_FOOD_API_KEY', '')


def procesar_orden_delivery(plataforma, payload, db_session, socketio=None):
    """Procesa un webhook de delivery y crea la orden interna."""
    from backend.models.models import Orden, OrdenDetalle, DeliveryOrden, Producto

    parser = PARSERS.get(plataforma)
    if not parser:
        raise ValueError(f'Plataforma no soportada: {plataforma}')

    data = parser(payload)

    # Verificar que no sea duplicado
    existente = DeliveryOrden.query.filter_by(
        plataforma=plataforma, external_id=data['external_id'],
    ).first()
    if existente:
        logger.warning('Orden delivery duplicada: %s %s', plataforma, data['external_id'])
        return existente

    # Crear orden interna
    # Use a system user for delivery orders (first superadmin as fallback)
    from backend.models.models import Usuario
    sistema_user = Usuario.query.filter_by(rol='superadmin').first()
    sistema_user_id = sistema_user.id if sistema_user else None

    orden = Orden(
        es_para_llevar=True,
        estado='enviado',
        canal=plataforma,
        mesero_id=sistema_user_id,
    )
    db_session.add(orden)
    db_session.flush()

    # Mapear items — intenta vincular con productos internos por nombre
    for item in data.get('items', []):
        # Escape LIKE wildcards to prevent pattern injection
        nombre_buscar = item['nombre'].replace('%', '\\%').replace('_', '\\_')
        producto = Producto.query.filter(
            Producto.nombre.ilike(f'%{nombre_buscar}%')
        ).first()
        if not producto:
            logger.warning('Producto delivery no encontrado: %s (plataforma=%s)', item['nombre'], plataforma)

        detalle = OrdenDetalle(
            orden_id=orden.id,
            producto_id=producto.id if producto else None,
            cantidad=item.get('cantidad', 1),
            precio_unitario=Decimal(str(item.get('precio', 0))),
            notas=item.get('notas', ''),
            estado='pendiente',
        )
        db_session.add(detalle)

    # Crear registro de delivery
    delivery = DeliveryOrden(
        plataforma=plataforma,
        external_id=data['external_id'],
        orden_id=orden.id,
        estado_plataforma=data.get('estado', 'nueva'),
        payload_raw=json.dumps(payload) if isinstance(payload, dict) else str(payload),
        cliente_nombre=data.get('cliente_nombre', ''),
        cliente_telefono=data.get('cliente_telefono', ''),
        direccion_entrega=data.get('direccion', ''),
        total_plataforma=Decimal(str(data.get('total', 0))),
        comision=Decimal(str(data.get('comision', 0))),
    )
    db_session.add(delivery)
    db_session.commit()

    # Notificar cocina
    if socketio:
        socketio.emit('nueva_orden_cocina', {
            'orden_id': orden.id,
            'mensaje': f'Nueva orden de {plataforma} #{data["external_id"]}',
        })

    logger.info('Orden delivery procesada: plataforma=%s ext_id=%s orden=%s',
                plataforma, data['external_id'], orden.id)
    return delivery


# =====================================================================
# Parsers por plataforma
# =====================================================================

def _parse_uber_eats(payload):
    """Parser para webhook de Uber Eats."""
    return {
        'external_id': payload.get('id', payload.get('order_id', '')),
        'estado': payload.get('current_state', 'nueva'),
        'cliente_nombre': payload.get('eater', {}).get('first_name', ''),
        'cliente_telefono': '',
        'direccion': payload.get('delivery_address', {}).get('formatted_address', ''),
        'total': payload.get('total', {}).get('amount', 0),
        'comision': payload.get('charges', {}).get('service_fee', 0),
        'items': [
            {
                'nombre': item.get('title', ''),
                'cantidad': item.get('quantity', 1),
                'precio': item.get('price', {}).get('amount', 0),
                'notas': item.get('special_instructions', ''),
            }
            for item in payload.get('items', [])
        ],
    }


def _parse_rappi(payload):
    """Parser para webhook de Rappi."""
    return {
        'external_id': str(payload.get('order_id', '')),
        'estado': payload.get('status', 'nueva'),
        'cliente_nombre': payload.get('client', {}).get('name', ''),
        'cliente_telefono': payload.get('client', {}).get('phone', ''),
        'direccion': payload.get('delivery', {}).get('address', ''),
        'total': payload.get('total_price', 0),
        'comision': payload.get('commission', 0),
        'items': [
            {
                'nombre': item.get('name', ''),
                'cantidad': item.get('quantity', 1),
                'precio': item.get('price', 0),
                'notas': item.get('comments', ''),
            }
            for item in payload.get('products', [])
        ],
    }


def _parse_didi_food(payload):
    """Parser para webhook de DiDi Food."""
    return {
        'external_id': str(payload.get('orderId', '')),
        'estado': payload.get('orderStatus', 'nueva'),
        'cliente_nombre': payload.get('customerInfo', {}).get('name', ''),
        'cliente_telefono': payload.get('customerInfo', {}).get('phone', ''),
        'direccion': payload.get('deliveryAddress', {}).get('address', ''),
        'total': payload.get('orderAmount', 0),
        'comision': payload.get('platformFee', 0),
        'items': [
            {
                'nombre': item.get('itemName', ''),
                'cantidad': item.get('quantity', 1),
                'precio': item.get('itemPrice', 0),
                'notas': item.get('remark', ''),
            }
            for item in payload.get('itemList', [])
        ],
    }


PARSERS = {
    'uber_eats': _parse_uber_eats,
    'rappi': _parse_rappi,
    'didi_food': _parse_didi_food,
}
