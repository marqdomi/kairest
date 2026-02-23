"""
Sprint 3 — Item 3.1: Impresión ESC/POS.

Servicio de impresión para:
- Comandas de cocina (al enviar a cocina)
- Tickets de cuenta (al pagar)
- Cortes de caja

Soporta impresoras USB, red y modo "none" (deshabilitado).
Configurable via env vars:
  PRINTER_TYPE=none|usb|network
  PRINTER_HOST=192.168.1.100  (para network)
  PRINTER_PORT=9100           (para network)
  PRINTER_VID=0x04b8          (para USB, vendor ID)
  PRINTER_PID=0x0202          (para USB, product ID)
  PRINTER_WIDTH=42            (caracteres por línea)
  AUTO_PRINT_COMANDA=false    (auto-imprimir al enviar a cocina)
"""
import os
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

PRINTER_TYPE = os.getenv('PRINTER_TYPE', 'none')  # none, usb, network
PRINTER_HOST = os.getenv('PRINTER_HOST', '192.168.1.100')
PRINTER_PORT = int(os.getenv('PRINTER_PORT', '9100'))
PRINTER_VID = os.getenv('PRINTER_VID', '')
PRINTER_PID = os.getenv('PRINTER_PID', '')
PRINTER_WIDTH = int(os.getenv('PRINTER_WIDTH', '42'))
AUTO_PRINT_COMANDA = os.getenv('AUTO_PRINT_COMANDA', 'false').lower() == 'true'


def _get_printer():
    """Obtiene instancia de impresora según configuración."""
    if PRINTER_TYPE == 'none':
        return None

    try:
        from escpos.printer import Usb, Network

        if PRINTER_TYPE == 'usb' and PRINTER_VID and PRINTER_PID:
            vid = int(PRINTER_VID, 16) if PRINTER_VID.startswith('0x') else int(PRINTER_VID)
            pid = int(PRINTER_PID, 16) if PRINTER_PID.startswith('0x') else int(PRINTER_PID)
            return Usb(vid, pid)
        elif PRINTER_TYPE == 'network':
            return Network(PRINTER_HOST, PRINTER_PORT)
        else:
            logger.warning('Tipo de impresora no válido o faltan configuraciones: %s', PRINTER_TYPE)
            return None
    except ImportError:
        logger.warning('python-escpos no instalado. Impresión deshabilitada.')
        return None
    except Exception as e:
        logger.error('Error conectando impresora: %s', e)
        return None


def _center(text, width=None):
    """Centra texto en el ancho de la impresora."""
    w = width or PRINTER_WIDTH
    return text.center(w)


def _separator(char='-', width=None):
    """Línea separadora."""
    w = width or PRINTER_WIDTH
    return char * w


def _format_line(left, right, width=None):
    """Formatea una línea con texto a la izquierda y derecha."""
    w = width or PRINTER_WIDTH
    space = w - len(left) - len(right)
    if space < 1:
        space = 1
    return left + ' ' * space + right


def imprimir_comanda(orden):
    """
    Imprime comanda de cocina para una orden.

    Agrupa productos por estación para facilitar la preparación.
    """
    printer = _get_printer()
    if not printer:
        logger.info('Impresora no disponible, comanda no impresa para orden=%s', orden.id)
        return False

    try:
        now = datetime.now().strftime('%Y-%m-%d %H:%M')

        printer.set(align='center', bold=True, width=2, height=2)
        printer.text('COMANDA\n')
        printer.set(align='center', bold=False, width=1, height=1)
        printer.text(f'Orden #{orden.id}\n')

        if orden.mesa:
            printer.set(align='center', bold=True, width=2, height=1)
            printer.text(f'Mesa {orden.mesa.numero}\n')

        printer.set(align='left', bold=False, width=1, height=1)
        printer.text(f'{_separator()}\n')
        printer.text(f'Mesero: {orden.mesero.nombre if orden.mesero else "N/A"}\n')
        printer.text(f'Fecha: {now}\n')

        if orden.es_para_llevar:
            printer.set(bold=True)
            printer.text('*** PARA LLEVAR ***\n')
            printer.set(bold=False)

        printer.text(f'{_separator()}\n')

        # Agrupar por estación
        por_estacion = {}
        for d in orden.detalles:
            estacion = d.producto.estacion.nombre if d.producto.estacion else 'General'
            if estacion not in por_estacion:
                por_estacion[estacion] = []
            por_estacion[estacion].append(d)

        for estacion, items in por_estacion.items():
            printer.set(align='center', bold=True)
            printer.text(f'[ {estacion.upper()} ]\n')
            printer.set(align='left', bold=False)
            for d in items:
                printer.text(f'{d.cantidad}x {d.producto.nombre}\n')
                if d.notas:
                    printer.text(f'   >> {d.notas}\n')

        printer.text(f'{_separator()}\n')
        printer.text(f'{_center(now)}\n')
        printer.cut()
        printer.close()
        logger.info('Comanda impresa: orden=%s', orden.id)
        return True
    except Exception as e:
        logger.error('Error imprimiendo comanda orden=%s: %s', orden.id, e)
        try:
            printer.close()
        except Exception:
            pass
        return False


def imprimir_ticket_cuenta(orden, nombre_negocio='Mi Restaurante'):
    """
    Imprime ticket de cuenta / recibo para el cliente.

    Incluye: datos del negocio, detalle de productos, subtotal, IVA,
    descuentos, total, métodos de pago y cambio.
    """
    printer = _get_printer()
    if not printer:
        logger.info('Impresora no disponible, ticket no impreso para orden=%s', orden.id)
        return False

    try:
        now = datetime.now().strftime('%Y-%m-%d %H:%M')

        # Encabezado
        printer.set(align='center', bold=True, width=2, height=2)
        printer.text(f'{nombre_negocio}\n')
        printer.set(align='center', bold=False, width=1, height=1)
        printer.text(f'{_separator()}\n')
        printer.text(f'Orden #{orden.id}\n')
        if orden.mesa:
            printer.text(f'Mesa {orden.mesa.numero}\n')
        printer.text(f'Mesero: {orden.mesero.nombre if orden.mesero else "N/A"}\n')
        printer.text(f'Fecha: {now}\n')
        printer.text(f'{_separator()}\n')

        # Detalle de productos
        printer.set(align='left')
        for d in orden.detalles:
            precio = float(d.precio_unitario or d.producto.precio)
            total_item = d.cantidad * precio
            nombre = d.producto.nombre[:25]
            printer.text(f'{d.cantidad}x {nombre}\n')
            printer.text(f'{_format_line("", f"${total_item:.2f}")}\n')

        printer.text(f'{_separator()}\n')

        # Totales
        subtotal = float(orden.subtotal or 0)
        iva = float(orden.iva or 0)
        total = float(orden.total or 0)

        printer.text(f'{_format_line("Subtotal:", f"${subtotal:.2f}")}\n')

        if orden.descuento_pct and orden.descuento_pct > 0:
            printer.text(f'{_format_line(f"Descuento ({orden.descuento_pct}%):", f"-${float(orden.descuento_monto or 0):.2f}")}\n')
        elif orden.descuento_monto and orden.descuento_monto > 0:
            printer.text(f'{_format_line("Descuento:", f"-${float(orden.descuento_monto):.2f}")}\n')

        printer.text(f'{_format_line("IVA 16%:", f"${iva:.2f}")}\n')

        printer.set(bold=True)
        printer.text(f'{_format_line("TOTAL:", f"${total:.2f}")}\n')
        printer.set(bold=False)

        # Métodos de pago
        if orden.pagos:
            printer.text(f'{_separator()}\n')
            for pago in orden.pagos:
                metodo = pago.metodo.capitalize()
                printer.text(f'{_format_line(metodo + ":", f"${float(pago.monto):.2f}")}\n')

            if orden.cambio and orden.cambio > 0:
                printer.text(f'{_format_line("Cambio:", f"${float(orden.cambio):.2f}")}\n')

        # Propina
        if orden.propina and orden.propina > 0:
            printer.text(f'{_format_line("Propina:", f"${float(orden.propina):.2f}")}\n')

        # Pie
        printer.text(f'{_separator()}\n')
        printer.set(align='center')
        printer.text('Gracias por su visita\n')
        printer.text(f'{nombre_negocio}\n')
        printer.text('\n\n')
        printer.cut()
        printer.close()
        logger.info('Ticket impreso: orden=%s', orden.id)
        return True
    except Exception as e:
        logger.error('Error imprimiendo ticket orden=%s: %s', orden.id, e)
        try:
            printer.close()
        except Exception:
            pass
        return False


def imprimir_corte_caja(corte, nombre_negocio='Mi Restaurante'):
    """
    Imprime reporte de corte de caja.

    Incluye: fecha, totales por método de pago, diferencia, notas.
    """
    printer = _get_printer()
    if not printer:
        logger.info('Impresora no disponible, corte no impreso id=%s', corte.id)
        return False

    try:
        now = datetime.now().strftime('%Y-%m-%d %H:%M')

        printer.set(align='center', bold=True, width=2, height=2)
        printer.text('CORTE DE CAJA\n')
        printer.set(align='center', bold=False, width=1, height=1)
        printer.text(f'{nombre_negocio}\n')
        printer.text(f'{_separator()}\n')
        printer.text(f'Fecha: {corte.fecha}\n')
        printer.text(f'Generado: {now}\n')
        printer.text(f'Usuario: {corte.usuario.nombre if corte.usuario else "N/A"}\n')
        printer.text(f'{_separator()}\n')

        printer.set(align='left')
        printer.text(f'{_format_line("No. Órdenes:", str(corte.num_ordenes))}\n')

        total = float(corte.total_ingresos or 0)
        printer.set(bold=True)
        printer.text(f'{_format_line("Total Ingresos:", f"${total:.2f}")}\n')
        printer.set(bold=False)

        printer.text(f'{_separator()}\n')

        # Desglose por método de pago
        if corte.efectivo_esperado is not None:
            printer.text(f'{_format_line("Efectivo esperado:", f"${float(corte.efectivo_esperado):.2f}")}\n')
        if corte.efectivo_contado is not None:
            printer.text(f'{_format_line("Efectivo contado:", f"${float(corte.efectivo_contado):.2f}")}\n')
        if corte.diferencia is not None:
            diff = float(corte.diferencia)
            label = 'Diferencia:'
            if diff > 0:
                label = 'Sobrante:'
            elif diff < 0:
                label = 'Faltante:'
            printer.set(bold=True)
            printer.text(f'{_format_line(label, f"${diff:.2f}")}\n')
            printer.set(bold=False)

        if corte.tarjeta_total is not None:
            printer.text(f'{_format_line("Tarjeta:", f"${float(corte.tarjeta_total):.2f}")}\n')
        if corte.transferencia_total is not None:
            printer.text(f'{_format_line("Transferencia:", f"${float(corte.transferencia_total):.2f}")}\n')

        if corte.notas:
            printer.text(f'{_separator()}\n')
            printer.text(f'Notas: {corte.notas}\n')

        printer.text(f'{_separator()}\n')
        printer.text('\n')
        printer.cut()
        printer.close()
        logger.info('Corte de caja impreso: id=%s', corte.id)
        return True
    except Exception as e:
        logger.error('Error imprimiendo corte id=%s: %s', corte.id, e)
        try:
            printer.close()
        except Exception:
            pass
        return False


def generar_texto_comanda(orden):
    """
    Genera el texto de comanda como string (para fallback window.print).
    Útil cuando no hay impresora ESC/POS conectada.
    """
    lines = []
    now = datetime.now().strftime('%Y-%m-%d %H:%M')

    lines.append(_center('COMANDA'))
    lines.append(_center(f'Orden #{orden.id}'))
    if orden.mesa:
        lines.append(_center(f'Mesa {orden.mesa.numero}'))
    lines.append(_separator())
    lines.append(f'Mesero: {orden.mesero.nombre if orden.mesero else "N/A"}')
    lines.append(f'Fecha: {now}')
    if orden.es_para_llevar:
        lines.append('*** PARA LLEVAR ***')
    lines.append(_separator())

    for d in orden.detalles:
        lines.append(f'{d.cantidad}x {d.producto.nombre}')
        if d.notas:
            lines.append(f'   >> {d.notas}')

    lines.append(_separator())
    return '\n'.join(lines)


def generar_texto_ticket(orden, nombre_negocio='Mi Restaurante'):
    """
    Genera el texto de ticket como string (para fallback window.print).
    """
    lines = []
    now = datetime.now().strftime('%Y-%m-%d %H:%M')

    lines.append(_center(nombre_negocio))
    lines.append(_separator())
    lines.append(f'Orden #{orden.id}')
    if orden.mesa:
        lines.append(f'Mesa {orden.mesa.numero}')
    lines.append(f'Mesero: {orden.mesero.nombre if orden.mesero else "N/A"}')
    lines.append(f'Fecha: {now}')
    lines.append(_separator())

    for d in orden.detalles:
        precio = float(d.precio_unitario or d.producto.precio)
        total_item = d.cantidad * precio
        lines.append(f'{d.cantidad}x {d.producto.nombre[:25]}')
        lines.append(_format_line('', f'${total_item:.2f}'))

    lines.append(_separator())
    lines.append(_format_line('Subtotal:', f'${float(orden.subtotal or 0):.2f}'))
    lines.append(_format_line('IVA 16%:', f'${float(orden.iva or 0):.2f}'))
    lines.append(_format_line('TOTAL:', f'${float(orden.total or 0):.2f}'))

    if orden.pagos:
        lines.append(_separator())
        for pago in orden.pagos:
            lines.append(_format_line(f'{pago.metodo.capitalize()}:', f'${float(pago.monto):.2f}'))
        if orden.cambio and orden.cambio > 0:
            lines.append(_format_line('Cambio:', f'${float(orden.cambio):.2f}'))

    lines.append(_separator())
    lines.append(_center('Gracias por su visita'))
    return '\n'.join(lines)
