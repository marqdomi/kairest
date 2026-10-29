"""El estado de una orden mientras se sirve, cuando parte de ella la despacha el mesero.

En Casa Leones no hay quien atienda una pantalla de Bebidas: el mesero toma los
refrescos del refri y los lleva. Una estación marcada `la_sirve_mesero` funciona así:

- Lo suyo queda **listo en cuanto la orden sale** (o en cuanto se agrega, si ya había
  salido) y el mesero sólo lo marca "entregado" desde su tarjeta.
- No aparece en ningún KDS ni detiene la orden: antes los refrescos se quedaban
  "pendientes" para siempre y la mesa no se podía cobrar.
- Pedir otro refresco a media comida no regresa la orden a cocina.

`sincronizar_estado()` es el único lugar que decide en qué estado queda una orden ya
enviada después de agregarle o quitarle cosas, para que los tres caminos (carrito del
mesero, pantalla de agregar productos y borrar un renglón) se comporten igual.
"""
from backend.extensions import db, socketio
from backend.models.models import OrdenEstado, utc_now

# Lo que ya no le toca a nadie de la cocina
HECHO = (OrdenEstado.LISTO, 'entregado')

# Órdenes en las que ya no se mueve nada
_CERRADAS = (OrdenEstado.PENDIENTE, OrdenEstado.PAGADA, OrdenEstado.CANCELADA,
             OrdenEstado.FINALIZADA)


def lo_sirve_mesero(producto):
    estacion = getattr(producto, 'estacion', None)
    return bool(estacion and estacion.la_sirve_mesero)


def servir_lo_del_mesero(orden):
    """Pasa a listo lo pendiente que despacha el mesero. Sólo en órdenes ya enviadas:
    un borrador todavía no le pide nada a nadie. Devuelve los renglones que cambió."""
    if orden.estado in _CERRADAS:
        return []
    cambiados = []
    for d in orden.detalles:
        if d.estado == OrdenEstado.PENDIENTE and lo_sirve_mesero(d.producto):
            d.estado = OrdenEstado.LISTO
            d.fecha_listo = utc_now()
            cambiados.append(d)
    return cambiados


def sincronizar_estado(orden):
    """Deja la orden en el estado que corresponde a sus renglones.

    - Algo le falta a la cocina → vuelve a preparación si ya estaba lista o completada
      (sin esto, un taco agregado al final no le llegaba a ningún KDS)
    - Todo entregado → completada (se puede cobrar)
    - Todo listo o entregado → lista para entregar, y se avisa al mesero
      (antes sólo contaba "listo": si el mesero ya había llevado los refrescos, el
      aviso de que la comida estaba lista nunca llegaba)
    """
    if orden.estado in _CERRADAS or not orden.detalles:
        return orden.estado
    detalles = orden.detalles
    if any(d.estado not in HECHO for d in detalles):
        if orden.estado in (OrdenEstado.LISTA_PARA_ENTREGAR, OrdenEstado.COMPLETADA):
            orden.estado = OrdenEstado.EN_PREPARACION
    elif all(d.estado == 'entregado' for d in detalles):
        orden.estado = OrdenEstado.COMPLETADA
    elif orden.estado != OrdenEstado.LISTA_PARA_ENTREGAR:
        orden.estado = OrdenEstado.LISTA_PARA_ENTREGAR
        socketio.emit('orden_completa_lista', {
            'orden_id': orden.id,
            'mesa_nombre': orden.mesa.numero if orden.mesa else 'Para Llevar',
            'mensaje': f'¡Toda la orden {orden.numero} está lista para entregar!',
        })
    return orden.estado


def tras_cambiar_renglones(orden):
    """Después de agregar o quitar productos: lo del mesero queda listo y la orden en
    su estado. No hace commit."""
    servir_lo_del_mesero(orden)
    db.session.flush()
    return sincronizar_estado(orden)
