"""
Sprint 3 — Item 7.1: CFDI / Facturación Electrónica completa.

Integración con Facturapi (https://facturapi.io).
Configura FACTURAPI_KEY en .env para activar el timbrado real.
Usa FACTURAPI_URL para sandbox (https://www.facturapi.io/v2) o producción.

Funcionalidades:
- Crear factura (ingreso tipo "I")
- Cancelar factura con motivo SAT
- Descargar XML / PDF
- Reenviar factura por email
- Crear nota de crédito (egreso tipo "E")
"""
import os
import logging
from datetime import datetime
from decimal import Decimal

from backend.models.models import utc_now

logger = logging.getLogger(__name__)

FACTURAPI_KEY = os.getenv('FACTURAPI_KEY', '')
FACTURAPI_URL = os.getenv('FACTURAPI_URL', 'https://www.facturapi.io/v2')

# Mapeo método de pago POS → clave SAT forma_pago
FORMA_PAGO_MAP = {
    'efectivo': '01',
    'tarjeta': '04',
    'transferencia': '03',
}


def _facturapi_disponible():
    return bool(FACTURAPI_KEY)


def _headers():
    return {
        'Authorization': f'Bearer {FACTURAPI_KEY}',
        'Content-Type': 'application/json',
    }


def crear_factura_cfdi(orden, cliente, db_session, metodo_pago='PUE'):
    """Crea una factura CFDI tipo ingreso.

    Args:
        metodo_pago: 'PUE' (pago en una exhibición) o 'PPD' (parcialidades/diferido).
    """
    from backend.models.models import Factura, IVA_RATE
    from backend.services.rfc_validator import validar_rfc, normalizar_rfc

    orden.calcular_totales()

    # Validar RFC antes de timbrar
    rfc = normalizar_rfc(cliente.rfc or 'XAXX010101000')
    rfc_valido, rfc_error = validar_rfc(rfc)
    if not rfc_valido:
        logger.warning('RFC inválido para factura orden=%s: %s', orden.id, rfc_error)

    # Determinar forma de pago predominante
    forma_pago = '01'  # Efectivo default
    if orden.pagos:
        metodo_principal = max(orden.pagos, key=lambda p: p.monto)
        forma_pago = FORMA_PAGO_MAP.get(metodo_principal.metodo, '01')

    # Para PPD: forma de pago '99' (Por definir) y método 'PPD'
    if metodo_pago == 'PPD':
        forma_pago = '99'

    factura = Factura(
        orden_id=orden.id,
        cliente_id=cliente.id,
        rfc_receptor=rfc,
        razon_social=cliente.razon_social or cliente.nombre,
        uso_cfdi=cliente.uso_cfdi or 'G03',
        regimen_fiscal=cliente.regimen_fiscal or '616',
        domicilio_fiscal=cliente.domicilio_fiscal or '',
        subtotal=orden.subtotal,
        iva=orden.iva,
        total=orden.total,
        estado='pendiente',
        forma_pago=forma_pago,
        metodo_pago_cfdi=metodo_pago,
    )
    db_session.add(factura)
    db_session.flush()

    if _facturapi_disponible():
        try:
            resultado = _timbrar_facturapi(factura, orden, cliente)
            factura.uuid_cfdi = resultado.get('uuid')
            factura.serie = resultado.get('serie')
            factura.folio = resultado.get('folio_number')
            factura.facturapi_id = resultado.get('id')
            factura.xml_url = resultado.get('xml_url', '')
            factura.pdf_url = resultado.get('pdf_url', '')
            factura.pac_response = str(resultado)
            factura.fecha_timbrado = utc_now()
            factura.estado = 'timbrada'
            logger.info('CFDI timbrado: factura=%s uuid=%s', factura.id, factura.uuid_cfdi)
        except Exception as e:
            factura.estado = 'error'
            factura.pac_response = str(e)
            logger.exception('Error al timbrar CFDI factura=%s', factura.id)
    else:
        logger.info('CFDI sin PAC: factura=%s registrada como pendiente', factura.id)

    db_session.commit()
    return factura


def _timbrar_facturapi(factura, orden, cliente):
    """Llama al API de Facturapi para timbrar factura tipo ingreso."""
    import requests

    items = []
    for d in orden.detalles:
        precio = float(d.precio_unitario or d.producto.precio)
        items.append({
            'quantity': d.cantidad,
            'product': {
                'description': d.producto.nombre,
                'product_key': '90101500',  # Código SAT genérico para alimentos
                'unit_key': 'E48',  # Unidad de servicio
                'unit_name': 'Servicio',
                'price': precio,
                'tax_included': False,
                'taxes': [{
                    'type': 'IVA',
                    'rate': 0.16,
                }],
            },
        })

    payload = {
        'customer': {
            'legal_name': factura.razon_social,
            'tax_id': factura.rfc_receptor,
            'tax_system': factura.regimen_fiscal or '616',
            'address': {
                'zip': factura.domicilio_fiscal or '00000',
            },
        },
        'items': items,
        'use': factura.uso_cfdi,
        'payment_form': factura.forma_pago or '01',
        'payment_method': factura.metodo_pago_cfdi or 'PUE',
    }

    # Si hay email del cliente, incluirlo
    if cliente.email:
        payload['customer']['email'] = cliente.email

    resp = requests.post(f'{FACTURAPI_URL}/invoices', json=payload,
                         headers=_headers(), timeout=30)
    resp.raise_for_status()
    data = resp.json()

    return {
        'id': data.get('id'),
        'uuid': data.get('uuid'),
        'serie': data.get('series'),
        'folio_number': str(data.get('folio_number', '')),
        'xml_url': f"{FACTURAPI_URL}/invoices/{data.get('id')}/xml",
        'pdf_url': f"{FACTURAPI_URL}/invoices/{data.get('id')}/pdf",
    }


def cancelar_factura_cfdi(factura, db_session, motivo='02'):
    """
    Cancela una factura CFDI ante el SAT via PAC.

    Motivos SAT:
    - 01: Comprobante emitido con errores con relación
    - 02: Comprobante emitido con errores sin relación
    - 03: No se llevó a cabo la operación
    - 04: Operación nominativa relacionada en una factura global
    """
    if not _facturapi_disponible():
        factura.estado = 'cancelada'
        db_session.commit()
        return True

    try:
        import requests
        payload = {'motive': motivo}
        resp = requests.delete(
            f'{FACTURAPI_URL}/invoices/{factura.facturapi_id or factura.uuid_cfdi}',
            json=payload, headers=_headers(), timeout=30,
        )
        resp.raise_for_status()
        factura.estado = 'cancelada'
        db_session.commit()
        logger.info('CFDI cancelado: uuid=%s motivo=%s', factura.uuid_cfdi, motivo)
        return True
    except Exception as e:
        logger.exception('Error cancelando CFDI uuid=%s', factura.uuid_cfdi)
        factura.pac_response = f'Error cancelación: {e}'
        db_session.commit()
        return False


def descargar_xml(factura):
    """Descarga el XML de una factura timbrada."""
    if not _facturapi_disponible() or not factura.facturapi_id:
        return None
    try:
        import requests
        resp = requests.get(
            f'{FACTURAPI_URL}/invoices/{factura.facturapi_id}/xml',
            headers={'Authorization': f'Bearer {FACTURAPI_KEY}'},
            timeout=30,
        )
        resp.raise_for_status()
        return resp.content
    except Exception as e:
        logger.exception('Error descargando XML factura=%s', factura.id)
        return None


def descargar_pdf(factura):
    """Descarga el PDF de una factura timbrada."""
    if not _facturapi_disponible() or not factura.facturapi_id:
        return None
    try:
        import requests
        resp = requests.get(
            f'{FACTURAPI_URL}/invoices/{factura.facturapi_id}/pdf',
            headers={'Authorization': f'Bearer {FACTURAPI_KEY}'},
            timeout=30,
        )
        resp.raise_for_status()
        return resp.content
    except Exception as e:
        logger.exception('Error descargando PDF factura=%s', factura.id)
        return None


def reenviar_email(factura, email=None):
    """Reenvía la factura por email via Facturapi."""
    if not _facturapi_disponible() or not factura.facturapi_id:
        return False
    try:
        import requests
        payload = {}
        if email:
            payload['email'] = email
        resp = requests.post(
            f'{FACTURAPI_URL}/invoices/{factura.facturapi_id}/email',
            json=payload, headers=_headers(), timeout=30,
        )
        resp.raise_for_status()
        logger.info('Factura reenviada por email: factura=%s email=%s', factura.id, email)
        return True
    except Exception as e:
        logger.exception('Error reenviando factura=%s por email', factura.id)
        return False


def crear_nota_credito(factura_origen, monto, motivo, db_session):
    """
    Crea una nota de crédito (CFDI tipo egreso "E") relacionada a una factura.

    Args:
        factura_origen: Factura original a la que se aplica la NC
        monto: Monto de la nota de crédito (parcial o total)
        motivo: Motivo de la nota de crédito
        db_session: Sesión de base de datos

    Returns:
        NotaCredito creada
    """
    from backend.models.models import NotaCredito, IVA_RATE

    monto_decimal = Decimal(str(monto))
    iva_nc = (monto_decimal * IVA_RATE / (1 + IVA_RATE)).quantize(Decimal('0.01'))
    subtotal_nc = monto_decimal - iva_nc

    nc = NotaCredito(
        factura_origen_id=factura_origen.id,
        motivo=motivo,
        monto=monto_decimal,
        subtotal=subtotal_nc,
        iva=iva_nc,
        estado='pendiente',
    )
    db_session.add(nc)
    db_session.flush()

    if _facturapi_disponible() and factura_origen.facturapi_id:
        try:
            resultado = _timbrar_nota_credito(nc, factura_origen)
            nc.uuid_cfdi = resultado.get('uuid')
            nc.facturapi_id = resultado.get('id')
            nc.xml_url = resultado.get('xml_url', '')
            nc.pdf_url = resultado.get('pdf_url', '')
            nc.estado = 'timbrada'
            logger.info('Nota de crédito timbrada: nc=%s uuid=%s', nc.id, nc.uuid_cfdi)
        except Exception as e:
            nc.estado = 'error'
            nc.pac_response = str(e)
            logger.exception('Error timbrar nota de crédito nc=%s', nc.id)
    else:
        logger.info('Nota de crédito sin PAC: nc=%s registrada como pendiente', nc.id)

    db_session.commit()
    return nc


def _timbrar_nota_credito(nota_credito, factura_origen):
    """Timbra nota de crédito via Facturapi (tipo E - egreso)."""
    import requests

    payload = {
        'type': 'E',  # Egreso
        'customer': {
            'legal_name': factura_origen.razon_social,
            'tax_id': factura_origen.rfc_receptor,
            'tax_system': factura_origen.regimen_fiscal or '616',
            'address': {
                'zip': factura_origen.domicilio_fiscal or '00000',
            },
        },
        'items': [{
            'quantity': 1,
            'product': {
                'description': nota_credito.motivo or 'Nota de crédito',
                'product_key': '84111506',
                'unit_key': 'ACT',
                'unit_name': 'Actividad',
                'price': float(nota_credito.subtotal),
                'tax_included': False,
                'taxes': [{
                    'type': 'IVA',
                    'rate': 0.16,
                }],
            },
        }],
        'use': factura_origen.uso_cfdi or 'G02',  # G02 = Devoluciones
        'payment_form': factura_origen.forma_pago or '01',
        'payment_method': 'PUE',
        'related_documents': [{
            'relationship': '01',  # Nota de crédito de los documentos relacionados
            'uuid': factura_origen.uuid_cfdi,
        }],
    }

    resp = requests.post(f'{FACTURAPI_URL}/invoices', json=payload,
                         headers=_headers(), timeout=30)
    resp.raise_for_status()
    data = resp.json()

    return {
        'id': data.get('id'),
        'uuid': data.get('uuid'),
        'xml_url': f"{FACTURAPI_URL}/invoices/{data.get('id')}/xml",
        'pdf_url': f"{FACTURAPI_URL}/invoices/{data.get('id')}/pdf",
    }


# -------------------- COMPLEMENTO DE PAGO (Sprint 6 — 7.3) --------------------

def crear_complemento_pago(factura, monto_pago, forma_pago_real, db_session):
    """Crea un complemento de pago CFDI tipo "P" para facturas PPD.

    Args:
        factura: Factura original emitida como PPD.
        monto_pago: Monto del pago recibido.
        forma_pago_real: Clave SAT de forma de pago real (01, 03, 04).
        db_session: Sesión de SQLAlchemy.

    Returns:
        dict con resultado del complemento {success, message, uuid, ...}
    """
    from decimal import Decimal

    if factura.metodo_pago_cfdi != 'PPD':
        return {'success': False, 'message': 'Solo facturas PPD requieren complemento de pago.'}

    if not factura.uuid_cfdi:
        return {'success': False, 'message': 'La factura no tiene UUID (no timbrada).'}

    resultado = {
        'success': False,
        'message': '',
        'uuid': None,
        'facturapi_id': None,
    }

    if not _facturapi_disponible():
        resultado['message'] = 'Complemento registrado (PAC no configurado).'
        logger.info('Complemento de pago sin PAC para factura=%s', factura.id)
        return resultado

    try:
        import requests
        from datetime import datetime

        payload = {
            'type': 'P',  # Pago
            'customer': {
                'legal_name': factura.razon_social,
                'tax_id': factura.rfc_receptor,
                'tax_system': factura.regimen_fiscal or '616',
                'address': {
                    'zip': factura.domicilio_fiscal or '00000',
                },
            },
            'complements': [{
                'type': 'pago',
                'data': [{
                    'payment_form': forma_pago_real,
                    'date': utc_now().strftime('%Y-%m-%dT%H:%M:%S'),
                    'amount': float(monto_pago),
                    'related_documents': [{
                        'uuid': factura.uuid_cfdi,
                        'installment': 1,
                        'last_balance': float(factura.total),
                        'amount': float(monto_pago),
                    }],
                }],
            }],
        }

        resp = requests.post(f'{FACTURAPI_URL}/invoices', json=payload,
                             headers=_headers(), timeout=30)
        resp.raise_for_status()
        data = resp.json()

        resultado['success'] = True
        resultado['uuid'] = data.get('uuid')
        resultado['facturapi_id'] = data.get('id')
        resultado['message'] = f'Complemento timbrado. UUID: {data.get("uuid")}'
        logger.info('Complemento de pago timbrado para factura=%s uuid=%s', factura.id, data.get('uuid'))

    except Exception as e:
        resultado['message'] = f'Error al timbrar complemento: {str(e)}'
        logger.exception('Error complemento de pago factura=%s', factura.id)

    return resultado
