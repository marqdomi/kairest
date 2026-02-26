"""Fase 3 — Item 16: Reportes por rango de fechas con export CSV.
   Sprint 4 — 6.1: JSON API endpoints para gráficas Chart.js.
   Sprint 6 — 6.2: Rentabilidad por producto.
   Sprint 6 — 6.3: Reporte delivery por canal."""
import io
import csv
import logging
from datetime import date, datetime, timedelta
from decimal import Decimal
from flask import Blueprint, render_template, request, jsonify, Response, g
from backend.utils import login_required, filtrar_por_sucursal
from backend.extensions import db
from backend.models.models import (
    Sale, SaleItem, Producto, Pago, Orden, Usuario, Ingrediente,
    MovimientoInventario, Categoria, RecetaDetalle, DeliveryOrden,
)
from sqlalchemy import func, extract, case
from sqlalchemy.orm import joinedload

logger = logging.getLogger(__name__)

reportes_bp = Blueprint('reportes', __name__, url_prefix='/admin/reportes')


def _parse_rango(args):
    """Extrae fecha_inicio y fecha_fin de los query params.

    Falls back to first-of-month / today when values are missing or malformed.
    """
    hoy = date.today()
    default_inicio = hoy.replace(day=1)

    fi_raw = args.get('fecha_inicio', '') or default_inicio.isoformat()
    ff_raw = args.get('fecha_fin', '') or hoy.isoformat()

    try:
        fi = date.fromisoformat(fi_raw)
    except (ValueError, TypeError):
        fi = default_inicio
    try:
        ff = date.fromisoformat(ff_raw)
    except (ValueError, TypeError):
        ff = hoy

    # Ensure inicio <= fin
    if fi > ff:
        fi, ff = ff, fi

    return fi, ff


# =====================================================================
# Dashboard de reportes
# =====================================================================
@reportes_bp.route('/')
@login_required(roles=['admin', 'superadmin'])
def dashboard_reportes():
    fi, ff = _parse_rango(request.args)
    return render_template('admin/reportes/dashboard.html', fecha_inicio=fi, fecha_fin=ff)


# =====================================================================
# Reporte de ventas
# =====================================================================
@reportes_bp.route('/ventas')
@login_required(roles=['admin', 'superadmin'])
def reporte_ventas():
    fi, ff = _parse_rango(request.args)

    ventas = filtrar_por_sucursal(
        Sale.query.filter(
            func.date(Sale.fecha_hora) >= fi,
            func.date(Sale.fecha_hora) <= ff,
        ), Sale,
    ).order_by(Sale.fecha_hora.desc()).all()

    total_ventas = sum(float(v.total) for v in ventas)
    num_ventas = len(ventas)
    ticket_promedio = (total_ventas / num_ventas) if num_ventas else 0

    # Ventas por día
    ventas_dia_q = db.session.query(
        func.date(Sale.fecha_hora).label('dia'),
        func.sum(Sale.total).label('total'),
        func.count(Sale.id).label('cantidad'),
    ).filter(
        func.date(Sale.fecha_hora) >= fi,
        func.date(Sale.fecha_hora) <= ff,
    )
    suc_id = getattr(g, 'sucursal_id', None)
    if suc_id is not None:
        ventas_dia_q = ventas_dia_q.filter(Sale.sucursal_id == suc_id)
    ventas_por_dia = ventas_dia_q.group_by(func.date(Sale.fecha_hora)).order_by(func.date(Sale.fecha_hora)).all()

    return render_template('admin/reportes/ventas.html',
                           fecha_inicio=fi, fecha_fin=ff,
                           total_ventas=total_ventas, num_ventas=num_ventas,
                           ticket_promedio=ticket_promedio,
                           ventas_por_dia=ventas_por_dia)


@reportes_bp.route('/ventas/csv')
@login_required(roles=['admin', 'superadmin'])
def export_ventas_csv():
    fi, ff = _parse_rango(request.args)
    ventas = filtrar_por_sucursal(
        Sale.query.options(
            joinedload(Sale.usuario),
        ).filter(
            func.date(Sale.fecha_hora) >= fi,
            func.date(Sale.fecha_hora) <= ff,
        ), Sale,
    ).order_by(Sale.fecha_hora).all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['ID', 'Fecha', 'Mesa', 'Mesero', 'Total', 'Estado'])
    for v in ventas:
        writer.writerow([v.id, v.fecha_hora.strftime('%Y-%m-%d %H:%M'),
                         v.mesa_id or 'Llevar', v.usuario.nombre if v.usuario else '',
                         float(v.total), v.estado])

    return Response(
        output.getvalue(),
        mimetype='text/csv',
        headers={'Content-Disposition': f'attachment;filename=ventas_{fi}_{ff}.csv'},
    )


@reportes_bp.route('/ventas/pdf')
@login_required(roles=['admin', 'superadmin'])
def export_ventas_pdf():
    """Exporta reporte de ventas a PDF."""
    from datetime import datetime
    from backend.services.pdf_generator import generar_pdf

    fi, ff = _parse_rango(request.args)
    ventas_dia_q = db.session.query(
        func.date(Sale.fecha_hora).label('dia'),
        func.sum(Sale.total).label('total'),
        func.count(Sale.id).label('cantidad'),
    ).filter(
        func.date(Sale.fecha_hora) >= fi,
        func.date(Sale.fecha_hora) <= ff,
    )
    suc_id = getattr(g, 'sucursal_id', None)
    if suc_id is not None:
        ventas_dia_q = ventas_dia_q.filter(Sale.sucursal_id == suc_id)
    ventas_por_dia = ventas_dia_q.group_by(func.date(Sale.fecha_hora)).order_by(func.date(Sale.fecha_hora)).all()

    total_ventas = sum(float(r.total) for r in ventas_por_dia)
    num_ventas = sum(r.cantidad for r in ventas_por_dia)
    ticket_promedio = (total_ventas / num_ventas) if num_ventas else 0

    pdf = generar_pdf('pdf/ventas.html',
                      fecha_inicio=fi, fecha_fin=ff,
                      total_ventas=total_ventas, num_ventas=num_ventas,
                      ticket_promedio=ticket_promedio,
                      ventas_por_dia=ventas_por_dia,
                      now=datetime.now())
    if pdf:
        return Response(pdf, mimetype='application/pdf',
                        headers={'Content-Disposition': f'attachment;filename=ventas_{fi}_{ff}.pdf'})
    flash('Error al generar PDF. Verifique la instalación de WeasyPrint.', 'danger')
    return redirect(url_for('reportes.reporte_ventas', fecha_inicio=fi, fecha_fin=ff))


@reportes_bp.route('/productos/pdf')
@login_required(roles=['admin', 'superadmin'])
def export_productos_pdf():
    """Exporta reporte de productos a PDF."""
    from datetime import datetime
    from backend.services.pdf_generator import generar_pdf

    fi, ff = _parse_rango(request.args)
    top = db.session.query(
        Producto.nombre.label('nombre'),
        func.sum(SaleItem.cantidad).label('cantidad'),
        func.sum(SaleItem.subtotal).label('total'),
    ).join(SaleItem, SaleItem.producto_id == Producto.id
    ).join(Sale, Sale.id == SaleItem.sale_id
    ).filter(func.date(Sale.fecha_hora) >= fi, func.date(Sale.fecha_hora) <= ff)
    suc_id = getattr(g, 'sucursal_id', None)
    if suc_id is not None:
        top = top.filter(Sale.sucursal_id == suc_id)
    productos = top.group_by(Producto.nombre).order_by(func.sum(SaleItem.subtotal).desc()).all()

    pdf = generar_pdf('pdf/productos.html',
                      fecha_inicio=fi, fecha_fin=ff,
                      productos=productos, now=datetime.now())
    if pdf:
        return Response(pdf, mimetype='application/pdf',
                        headers={'Content-Disposition': f'attachment;filename=productos_{fi}_{ff}.pdf'})
    flash('Error al generar PDF.', 'danger')
    return redirect(url_for('reportes.reporte_productos', fecha_inicio=fi, fecha_fin=ff))


# =====================================================================
# Top productos
# =====================================================================
@reportes_bp.route('/productos')
@login_required(roles=['admin', 'superadmin'])
def reporte_productos():
    fi, ff = _parse_rango(request.args)

    top = db.session.query(
        Producto.nombre,
        func.sum(SaleItem.cantidad).label('cantidad'),
        func.sum(SaleItem.subtotal).label('ingreso'),
    ).join(SaleItem, SaleItem.producto_id == Producto.id
    ).join(Sale, SaleItem.sale_id == Sale.id
    ).filter(
        func.date(Sale.fecha_hora) >= fi,
        func.date(Sale.fecha_hora) <= ff,
    )
    suc_id = getattr(g, 'sucursal_id', None)
    if suc_id is not None:
        top = top.filter(Sale.sucursal_id == suc_id)
    top = top.group_by(Producto.id).order_by(func.sum(SaleItem.cantidad).desc()).all()

    return render_template('admin/reportes/productos.html',
                           fecha_inicio=fi, fecha_fin=ff, top_productos=top)


@reportes_bp.route('/productos/csv')
@login_required(roles=['admin', 'superadmin'])
def export_productos_csv():
    fi, ff = _parse_rango(request.args)
    top = db.session.query(
        Producto.nombre,
        func.sum(SaleItem.cantidad).label('cantidad'),
        func.sum(SaleItem.subtotal).label('ingreso'),
    ).join(SaleItem, SaleItem.producto_id == Producto.id
    ).join(Sale, SaleItem.sale_id == Sale.id
    ).filter(
        func.date(Sale.fecha_hora) >= fi,
        func.date(Sale.fecha_hora) <= ff,
    )
    suc_id = getattr(g, 'sucursal_id', None)
    if suc_id is not None:
        top = top.filter(Sale.sucursal_id == suc_id)
    top = top.group_by(Producto.id).order_by(func.sum(SaleItem.cantidad).desc()).all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Producto', 'Cantidad Vendida', 'Ingreso Total'])
    for row in top:
        writer.writerow([row.nombre, int(row.cantidad), float(row.ingreso)])

    return Response(
        output.getvalue(), mimetype='text/csv',
        headers={'Content-Disposition': f'attachment;filename=productos_{fi}_{ff}.csv'},
    )


# =====================================================================
# Reporte por mesero
# =====================================================================
@reportes_bp.route('/meseros')
@login_required(roles=['admin', 'superadmin'])
def reporte_meseros():
    fi, ff = _parse_rango(request.args)

    datos = db.session.query(
        Usuario.nombre,
        func.count(Sale.id).label('num_ventas'),
        func.sum(Sale.total).label('total_ventas'),
    ).join(Sale, Sale.usuario_id == Usuario.id
    ).filter(
        func.date(Sale.fecha_hora) >= fi,
        func.date(Sale.fecha_hora) <= ff,
    )
    suc_id = getattr(g, 'sucursal_id', None)
    if suc_id is not None:
        datos = datos.filter(Sale.sucursal_id == suc_id)
    datos = datos.group_by(Usuario.id).order_by(func.sum(Sale.total).desc()).all()

    # Propinas por mesero (Sprint 6 — 3.6)
    propinas_q = db.session.query(
        Usuario.nombre,
        func.sum(Orden.propina).label('total_propinas'),
    ).join(Orden, Orden.mesero_id == Usuario.id
    ).filter(
        Orden.estado == 'pagada',
        func.date(Orden.fecha_pago) >= fi,
        func.date(Orden.fecha_pago) <= ff,
    )
    if suc_id is not None:
        propinas_q = propinas_q.filter(Orden.sucursal_id == suc_id)
    propinas_map = {r.nombre: float(r.total_propinas or 0) for r in propinas_q.group_by(Usuario.id).all()}

    return render_template('admin/reportes/meseros.html',
                           fecha_inicio=fi, fecha_fin=ff, datos_meseros=datos,
                           propinas_map=propinas_map)


# =====================================================================
# Reporte de métodos de pago
# =====================================================================
@reportes_bp.route('/pagos')
@login_required(roles=['admin', 'superadmin'])
def reporte_pagos():
    fi, ff = _parse_rango(request.args)

    datos = db.session.query(
        Pago.metodo,
        func.count(Pago.id).label('cantidad'),
        func.sum(Pago.monto).label('total'),
    ).filter(
        func.date(Pago.fecha) >= fi,
        func.date(Pago.fecha) <= ff,
    )
    suc_id = getattr(g, 'sucursal_id', None)
    if suc_id is not None:
        datos = datos.join(Orden, Pago.orden_id == Orden.id).filter(Orden.sucursal_id == suc_id)
    datos = datos.group_by(Pago.metodo).all()

    return render_template('admin/reportes/pagos.html',
                           fecha_inicio=fi, fecha_fin=ff, datos_pagos=datos)


# =====================================================================
# Reporte de inventario / mermas
# =====================================================================
@reportes_bp.route('/inventario')
@login_required(roles=['admin', 'superadmin'])
def reporte_inventario():
    fi, ff = _parse_rango(request.args)

    mermas = db.session.query(
        Ingrediente.nombre,
        Ingrediente.unidad,
        func.sum(MovimientoInventario.cantidad).label('total_merma'),
    ).join(MovimientoInventario, MovimientoInventario.ingrediente_id == Ingrediente.id
    ).filter(
        MovimientoInventario.tipo == 'merma',
        func.date(MovimientoInventario.fecha) >= fi,
        func.date(MovimientoInventario.fecha) <= ff,
    )
    suc_id = getattr(g, 'sucursal_id', None)
    if suc_id is not None:
        mermas = mermas.filter(Ingrediente.sucursal_id == suc_id)
    mermas = mermas.group_by(Ingrediente.id).order_by(func.sum(MovimientoInventario.cantidad).desc()).all()

    return render_template('admin/reportes/inventario.html',
                           fecha_inicio=fi, fecha_fin=ff, mermas=mermas)


# =====================================================================
# JSON API endpoints for Chart.js (Sprint 4 — 6.1)
# =====================================================================

@reportes_bp.route('/api/ventas')
@login_required(roles=['admin', 'superadmin'])
def api_ventas_chart():
    """Ventas por día + ventas por hora para Chart.js."""
    fi, ff = _parse_rango(request.args)
    suc_id = getattr(g, 'sucursal_id', None)

    # Ventas por día
    q_dia = db.session.query(
        func.date(Sale.fecha_hora).label('dia'),
        func.sum(Sale.total).label('total'),
        func.count(Sale.id).label('cantidad'),
    ).filter(
        func.date(Sale.fecha_hora) >= fi,
        func.date(Sale.fecha_hora) <= ff,
    )
    if suc_id is not None:
        q_dia = q_dia.filter(Sale.sucursal_id == suc_id)
    por_dia = q_dia.group_by(func.date(Sale.fecha_hora)).order_by(func.date(Sale.fecha_hora)).all()

    # Ventas por hora del día
    q_hora = db.session.query(
        extract('hour', Sale.fecha_hora).label('hora'),
        func.sum(Sale.total).label('total'),
        func.count(Sale.id).label('cantidad'),
    ).filter(
        func.date(Sale.fecha_hora) >= fi,
        func.date(Sale.fecha_hora) <= ff,
    )
    if suc_id is not None:
        q_hora = q_hora.filter(Sale.sucursal_id == suc_id)
    por_hora = q_hora.group_by(extract('hour', Sale.fecha_hora)).order_by(
        extract('hour', Sale.fecha_hora)).all()

    return jsonify({
        'por_dia': {
            'labels': [str(r.dia) for r in por_dia],
            'totales': [float(r.total) for r in por_dia],
            'cantidades': [int(r.cantidad) for r in por_dia],
        },
        'por_hora': {
            'labels': [f'{int(r.hora):02d}:00' for r in por_hora],
            'totales': [float(r.total) for r in por_hora],
            'cantidades': [int(r.cantidad) for r in por_hora],
        },
    })


@reportes_bp.route('/api/productos')
@login_required(roles=['admin', 'superadmin'])
def api_productos_chart():
    """Top 20 productos + ingresos por categoría para Chart.js."""
    fi, ff = _parse_rango(request.args)
    suc_id = getattr(g, 'sucursal_id', None)

    q = db.session.query(
        Producto.nombre,
        Categoria.nombre.label('cat_nombre'),
        func.sum(SaleItem.cantidad).label('cantidad'),
        func.sum(SaleItem.subtotal).label('ingreso'),
    ).join(SaleItem, SaleItem.producto_id == Producto.id
    ).join(Sale, SaleItem.sale_id == Sale.id
    ).outerjoin(Categoria, Producto.categoria_id == Categoria.id
    ).filter(
        func.date(Sale.fecha_hora) >= fi,
        func.date(Sale.fecha_hora) <= ff,
    )
    if suc_id is not None:
        q = q.filter(Sale.sucursal_id == suc_id)
    top = q.group_by(Producto.id, Categoria.nombre).order_by(func.sum(SaleItem.cantidad).desc()).limit(20).all()

    # Categorías
    q_cat = db.session.query(
        Categoria.nombre.label('cat_nombre'),
        func.sum(SaleItem.subtotal).label('ingreso'),
    ).join(Producto, Producto.categoria_id == Categoria.id
    ).join(SaleItem, SaleItem.producto_id == Producto.id
    ).join(Sale, SaleItem.sale_id == Sale.id
    ).filter(
        func.date(Sale.fecha_hora) >= fi,
        func.date(Sale.fecha_hora) <= ff,
    )
    if suc_id is not None:
        q_cat = q_cat.filter(Sale.sucursal_id == suc_id)
    cats = q_cat.group_by(Categoria.nombre).order_by(func.sum(SaleItem.subtotal).desc()).all()

    return jsonify({
        'top_productos': {
            'labels': [r.nombre for r in top],
            'cantidades': [int(r.cantidad) for r in top],
            'ingresos': [float(r.ingreso) for r in top],
        },
        'categorias': {
            'labels': [r.cat_nombre or 'Sin categoría' for r in cats],
            'ingresos': [float(r.ingreso) for r in cats],
        },
    })


@reportes_bp.route('/api/meseros')
@login_required(roles=['admin', 'superadmin'])
def api_meseros_chart():
    """Rendimiento por mesero para Chart.js."""
    fi, ff = _parse_rango(request.args)
    suc_id = getattr(g, 'sucursal_id', None)

    q = db.session.query(
        Usuario.nombre,
        func.count(Sale.id).label('num_ventas'),
        func.sum(Sale.total).label('total_ventas'),
    ).join(Sale, Sale.usuario_id == Usuario.id
    ).filter(
        func.date(Sale.fecha_hora) >= fi,
        func.date(Sale.fecha_hora) <= ff,
    )
    if suc_id is not None:
        q = q.filter(Sale.sucursal_id == suc_id)
    datos = q.group_by(Usuario.id).order_by(func.sum(Sale.total).desc()).all()

    return jsonify({
        'labels': [r.nombre for r in datos],
        'num_ventas': [int(r.num_ventas) for r in datos],
        'totales': [float(r.total_ventas) for r in datos],
    })


@reportes_bp.route('/api/pagos')
@login_required(roles=['admin', 'superadmin'])
def api_pagos_chart():
    """Desglose de métodos de pago para Chart.js."""
    fi, ff = _parse_rango(request.args)
    suc_id = getattr(g, 'sucursal_id', None)

    q = db.session.query(
        Pago.metodo,
        func.count(Pago.id).label('cantidad'),
        func.sum(Pago.monto).label('total'),
    ).filter(
        func.date(Pago.fecha) >= fi,
        func.date(Pago.fecha) <= ff,
    )
    if suc_id is not None:
        q = q.join(Orden, Pago.orden_id == Orden.id).filter(Orden.sucursal_id == suc_id)
    datos = q.group_by(Pago.metodo).all()

    return jsonify({
        'labels': [r.metodo.capitalize() for r in datos],
        'totales': [float(r.total) for r in datos],
        'cantidades': [int(r.cantidad) for r in datos],
    })


@reportes_bp.route('/api/inventario')
@login_required(roles=['admin', 'superadmin'])
def api_inventario_chart():
    """Mermas de inventario para Chart.js."""
    fi, ff = _parse_rango(request.args)
    suc_id = getattr(g, 'sucursal_id', None)

    q = db.session.query(
        Ingrediente.nombre,
        Ingrediente.unidad,
        func.sum(MovimientoInventario.cantidad).label('total_merma'),
    ).join(MovimientoInventario, MovimientoInventario.ingrediente_id == Ingrediente.id
    ).filter(
        MovimientoInventario.tipo == 'merma',
        func.date(MovimientoInventario.fecha) >= fi,
        func.date(MovimientoInventario.fecha) <= ff,
    )
    if suc_id is not None:
        q = q.filter(Ingrediente.sucursal_id == suc_id)
    mermas = q.group_by(Ingrediente.id).order_by(func.sum(MovimientoInventario.cantidad).desc()).limit(20).all()

    return jsonify({
        'labels': [f'{r.nombre} ({r.unidad})' for r in mermas],
        'totales': [float(r.total_merma) for r in mermas],
    })


# =====================================================================
# Reporte de rentabilidad por producto (Sprint 6 — 6.2)
# =====================================================================
@reportes_bp.route('/rentabilidad')
@login_required(roles=['admin', 'superadmin'])
def reporte_rentabilidad():
    fi, ff = _parse_rango(request.args)
    suc_id = getattr(g, 'sucursal_id', None)

    # Cantidad vendida por producto en el rango
    q_ventas = db.session.query(
        SaleItem.producto_id,
        func.sum(SaleItem.cantidad).label('cantidad_vendida'),
        func.sum(SaleItem.subtotal).label('ingreso_total'),
    ).join(Sale, SaleItem.sale_id == Sale.id
    ).filter(
        func.date(Sale.fecha_hora) >= fi,
        func.date(Sale.fecha_hora) <= ff,
    )
    if suc_id is not None:
        q_ventas = q_ventas.filter(Sale.sucursal_id == suc_id)
    ventas_map = {
        r.producto_id: {'cantidad': int(r.cantidad_vendida), 'ingreso': float(r.ingreso_total)}
        for r in q_ventas.group_by(SaleItem.producto_id).all()
    }

    # Todos los productos con su receta y costo
    productos = Producto.query.options(
        joinedload(Producto.receta_items).joinedload(RecetaDetalle.ingrediente),
    ).all()

    rows = []
    for p in productos:
        vendidos = ventas_map.get(p.id, {})
        cantidad = vendidos.get('cantidad', 0)
        ingreso = vendidos.get('ingreso', 0.0)
        precio_venta = float(p.precio)

        if p.receta_items:
            costo = sum(
                float(r.cantidad_por_unidad) * float(r.ingrediente.costo_unitario or 0)
                for r in p.receta_items
            )
        else:
            costo = None

        if costo is not None and precio_venta > 0:
            margen_pct = ((precio_venta - costo) / precio_venta) * 100
            margen_abs = precio_venta - costo
            utilidad_total = margen_abs * cantidad
        else:
            margen_pct = None
            margen_abs = None
            utilidad_total = None

        rows.append({
            'nombre': p.nombre,
            'precio_venta': precio_venta,
            'costo': costo,
            'margen_abs': margen_abs,
            'margen_pct': margen_pct,
            'cantidad': cantidad,
            'ingreso': ingreso,
            'utilidad_total': utilidad_total,
        })

    # Sort by utilidad_total desc (None at end)
    rows.sort(key=lambda r: r['utilidad_total'] if r['utilidad_total'] is not None else -1, reverse=True)

    return render_template('admin/reportes/rentabilidad.html',
                           fecha_inicio=fi, fecha_fin=ff, rows=rows)


@reportes_bp.route('/rentabilidad/csv')
@login_required(roles=['admin', 'superadmin'])
def export_rentabilidad_csv():
    fi, ff = _parse_rango(request.args)
    suc_id = getattr(g, 'sucursal_id', None)

    q_ventas = db.session.query(
        SaleItem.producto_id,
        func.sum(SaleItem.cantidad).label('cantidad_vendida'),
        func.sum(SaleItem.subtotal).label('ingreso_total'),
    ).join(Sale, SaleItem.sale_id == Sale.id
    ).filter(
        func.date(Sale.fecha_hora) >= fi,
        func.date(Sale.fecha_hora) <= ff,
    )
    if suc_id is not None:
        q_ventas = q_ventas.filter(Sale.sucursal_id == suc_id)
    ventas_map = {
        r.producto_id: {'cantidad': int(r.cantidad_vendida), 'ingreso': float(r.ingreso_total)}
        for r in q_ventas.group_by(SaleItem.producto_id).all()
    }

    productos = Producto.query.options(
        joinedload(Producto.receta_items).joinedload(RecetaDetalle.ingrediente),
    ).all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Producto', 'Precio Venta', 'Costo', 'Margen $', 'Margen %',
                      'Cantidad Vendida', 'Ingreso Total', 'Utilidad Total'])
    for p in productos:
        vendidos = ventas_map.get(p.id, {})
        cantidad = vendidos.get('cantidad', 0)
        ingreso = vendidos.get('ingreso', 0.0)
        precio_venta = float(p.precio)

        if p.receta_items:
            costo = sum(float(r.cantidad_por_unidad) * float(r.ingrediente.costo_unitario or 0)
                        for r in p.receta_items)
            margen_abs = precio_venta - costo
            margen_pct = ((precio_venta - costo) / precio_venta * 100) if precio_venta > 0 else 0
            utilidad_total = margen_abs * cantidad
        else:
            costo = 'N/A'
            margen_abs = 'N/A'
            margen_pct = 'N/A'
            utilidad_total = 'N/A'

        writer.writerow([p.nombre, f'{precio_venta:.2f}',
                         f'{costo:.2f}' if isinstance(costo, float) else costo,
                         f'{margen_abs:.2f}' if isinstance(margen_abs, float) else margen_abs,
                         f'{margen_pct:.1f}' if isinstance(margen_pct, float) else margen_pct,
                         cantidad, f'{ingreso:.2f}',
                         f'{utilidad_total:.2f}' if isinstance(utilidad_total, float) else utilidad_total])

    return Response(
        output.getvalue(), mimetype='text/csv',
        headers={'Content-Disposition': f'attachment;filename=rentabilidad_{fi}_{ff}.csv'},
    )


@reportes_bp.route('/api/rentabilidad')
@login_required(roles=['admin', 'superadmin'])
def api_rentabilidad_chart():
    """Bar/Line: Ingreso Total vs Margen % para Chart.js."""
    fi, ff = _parse_rango(request.args)
    suc_id = getattr(g, 'sucursal_id', None)

    # Cantidad vendida por producto en el rango
    q_ventas = db.session.query(
        SaleItem.producto_id,
        func.sum(SaleItem.cantidad).label('cantidad_vendida'),
        func.sum(SaleItem.subtotal).label('ingreso_total'),
    ).join(Sale, SaleItem.sale_id == Sale.id
    ).filter(
        func.date(Sale.fecha_hora) >= fi,
        func.date(Sale.fecha_hora) <= ff,
    )
    if suc_id is not None:
        q_ventas = q_ventas.filter(Sale.sucursal_id == suc_id)
    ventas_map = {
        r.producto_id: {'cantidad': int(r.cantidad_vendida), 'ingreso': float(r.ingreso_total)}
        for r in q_ventas.group_by(SaleItem.producto_id).all()
    }

    productos = Producto.query.options(
        joinedload(Producto.receta_items).joinedload(RecetaDetalle.ingrediente),
    ).all()

    points = []
    for p in productos:
        if not p.receta_items:
            continue
        vendidos = ventas_map.get(p.id, {})
        ingreso = vendidos.get('ingreso', 0.0)
        if ingreso == 0:
            continue # Solo mostrar productos con ventas en el periodo

        precio = float(p.precio)
        costo = sum(float(r.cantidad_por_unidad) * float(r.ingrediente.costo_unitario or 0)
                     for r in p.receta_items)
        margen = ((precio - costo) / precio * 100) if precio > 0 else 0
        points.append({
            'nombre': p.nombre, 
            'ingreso': ingreso, 
            'margen': round(margen, 1)
        })

    # Sort by ingreso desc
    points.sort(key=lambda x: x['ingreso'], reverse=True)
    # Take top 20 to avoid clutter
    points = points[:20]

    return jsonify({'productos': points})


# =====================================================================
# Reporte de delivery por canal (Sprint 6 — 6.3)
# =====================================================================
@reportes_bp.route('/delivery')
@login_required(roles=['admin', 'superadmin'])
def reporte_delivery():
    fi, ff = _parse_rango(request.args)
    suc_id = getattr(g, 'sucursal_id', None)

    # Ventas por canal
    q = db.session.query(
        Orden.canal,
        func.count(Orden.id).label('num_ordenes'),
        func.sum(Orden.total).label('total_ventas'),
    ).filter(
        Orden.estado == 'pagada',
        func.date(Orden.fecha_pago) >= fi,
        func.date(Orden.fecha_pago) <= ff,
    )
    if suc_id is not None:
        q = q.filter(Orden.sucursal_id == suc_id)
    por_canal = q.group_by(Orden.canal).all()

    canal_data = []
    total_general = Decimal('0')
    for canal, num, total in por_canal:
        total_general += (total or Decimal('0'))

    for canal, num, total in por_canal:
        total_val = float(total or 0)
        ticket_prom = total_val / num if num else 0
        pct = (float(total or 0) / float(total_general) * 100) if total_general > 0 else 0
        canal_data.append({
            'canal': canal or 'local',
            'num_ordenes': num,
            'total_ventas': total_val,
            'ticket_promedio': ticket_prom,
            'porcentaje': round(pct, 1),
        })

    # Comisiones por plataforma delivery
    q_com = db.session.query(
        DeliveryOrden.plataforma,
        func.count(DeliveryOrden.id).label('cantidad'),
        func.sum(DeliveryOrden.total_plataforma).label('total_plat'),
        func.sum(DeliveryOrden.comision).label('total_comision'),
    ).filter(
        func.date(DeliveryOrden.fecha_recibido) >= fi,
        func.date(DeliveryOrden.fecha_recibido) <= ff,
    )
    comisiones = q_com.group_by(DeliveryOrden.plataforma).all()

    comision_data = []
    for plat, cant, total_p, com in comisiones:
        comision_data.append({
            'plataforma': plat,
            'cantidad': cant,
            'total_plataforma': float(total_p or 0),
            'comision': float(com or 0),
            'neto': float((total_p or 0) - (com or 0)),
        })

    return render_template('admin/reportes/delivery.html',
                           fecha_inicio=fi, fecha_fin=ff,
                           canal_data=canal_data, comision_data=comision_data,
                           total_general=float(total_general))


@reportes_bp.route('/delivery/csv')
@login_required(roles=['admin', 'superadmin'])
def export_delivery_csv():
    fi, ff = _parse_rango(request.args)
    suc_id = getattr(g, 'sucursal_id', None)

    q = db.session.query(
        Orden.canal,
        func.count(Orden.id).label('num_ordenes'),
        func.sum(Orden.total).label('total_ventas'),
    ).filter(
        Orden.estado == 'pagada',
        func.date(Orden.fecha_pago) >= fi,
        func.date(Orden.fecha_pago) <= ff,
    )
    if suc_id is not None:
        q = q.filter(Orden.sucursal_id == suc_id)
    por_canal = q.group_by(Orden.canal).all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Canal', 'Órdenes', 'Ventas Total', 'Ticket Promedio'])
    for canal, num, total in por_canal:
        total_val = float(total or 0)
        ticket = total_val / num if num else 0
        writer.writerow([canal or 'local', num, f'{total_val:.2f}', f'{ticket:.2f}'])

    return Response(
        output.getvalue(), mimetype='text/csv',
        headers={'Content-Disposition': f'attachment;filename=delivery_{fi}_{ff}.csv'},
    )


@reportes_bp.route('/api/delivery')
@login_required(roles=['admin', 'superadmin'])
def api_delivery_chart():
    """Ventas por canal para Chart.js (stacked bar)."""
    fi, ff = _parse_rango(request.args)
    suc_id = getattr(g, 'sucursal_id', None)

    q = db.session.query(
        Orden.canal,
        func.count(Orden.id).label('num_ordenes'),
        func.sum(Orden.total).label('total'),
    ).filter(
        Orden.estado == 'pagada',
        func.date(Orden.fecha_pago) >= fi,
        func.date(Orden.fecha_pago) <= ff,
    )
    if suc_id is not None:
        q = q.filter(Orden.sucursal_id == suc_id)
    data = q.group_by(Orden.canal).all()

    return jsonify({
        'labels': [r.canal or 'local' for r in data],
        'totales': [float(r.total or 0) for r in data],
        'ordenes': [int(r.num_ordenes) for r in data],
    })
