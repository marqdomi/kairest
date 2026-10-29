# Demo paso a paso — primer cliente (barbacoa / tacos)

Guion para recorrer el sistema con cada rol, desde una instalación en blanco, usando el
menú real (`menu_restaurante.csv`, ahora plantilla **Barbacoa y Carnitas** del wizard).

## Levantar una base limpia (local)

```bash
rm -f backend/instance/demo_cliente.db
DATABASE_URL=sqlite:///demo_cliente.db REDIS_URL= RATELIMIT_ENABLED=false ./.venv/bin/python -m backend.app
```

(o el preview `flask-demo-cliente` de `.claude/launch.json`). Abre `http://localhost:5005`.

## Usuarios de prueba (sólo para la base de demo local)

| Rol | Usuario | Entra con | Dispositivo sugerido |
|---|---|---|---|
| Dueña (superadmin) | `duena` | contraseña `Leones2026demo` | Celular |
| Mesero | `pepe` | PIN `4826` | Celular |
| Cocina — Taquero | `tito` | PIN `7391` | Tablet |
| Cocina — Comal | `cata` | PIN `5937` | Tablet |
| Cocina — Bebidas | `beto` | PIN `6148` | Tablet |

El PIN sólo funciona en aparatos autorizados: la dueña entra con contraseña →
Admin → Dispositivos → "Autorizar este" (o "Generar código" y en el otro aparato
"Vincular este aparato"). Las cuentas viejas siguen entrando también con su correo.

## Guion

1. **Wizard** — Negocio "Casa Leones" → dueña → plantilla *Barbacoa y Carnitas* (58
   productos, estaciones Taquero / Comal / Bebidas) → 6 mesas → los 4 usuarios de arriba.
2. **Mesero (celular)** — Nueva orden Mesa 1: 3 tacos de maciza (tocar rápido 3 veces),
   2 de cachete, 2 quesadillas de queso con nota "Sin cebolla", 2 refrescos → Enviar.
   Para llevar: 3 × ½ kg barbacoa + 1 L consomé → Enviar.
3. **Cocina (tablet)** — Taquero marca LISTO ambas; Comal marca la quesadilla (ve la nota);
   Bebidas marca los refrescos.
4. **Mesero** — Entregar todos → Cobrar. Para llevar en efectivo con $1,000 (cambio $100).
   Mesa 1 por transferencia con referencia.
5. **Dueña (celular)** — Transferencias → "Llegó". Dashboard: ventas $1,191. Corte de caja:
   efectivo $900 + transferencia $291, arqueo con $900 → diferencia $0.

## Corregido durante la demo (2026-10-29)

| Hallazgo | Impacto | Arreglo |
|---|---|---|
| El wizard no tenía el menú real | Había que capturar 58 productos a mano | Plantilla `barbacoa` (primera, por defecto) |
| Tocar rápido un producto creaba renglones duplicados ("maciza ×2" + "maciza ×1") | Comanda partida en cocina | Cola secuencial en el navegador + lock de la orden en el servidor |
| Botón **Cobrar** del carrito invisible (texto blanco sobre transparente) | `--cl-gold-500` no existía | Alias de tokens + `cl-btn--gold` |
| "Cobrar" de la tarjeta abría un modal viejo | Ofrecía Tarjeta apagada, sin CLABE, logo fijo | Lleva a la pantalla completa de cobro |
| "¡Pago exitoso!" al registrar una transferencia sin confirmar | La mesera cree que ya se cobró | "Transferencia por confirmar" en ámbar con reloj |
| Precio en verde claro sobre blanco (1.9:1) | Ilegible al sol | `--cl-success-text` |
| Categoría encimada con la estrella de favorito | Visual | Reserva de espacio + elipsis |
| Productos en orden alfabético (½ kg antes que ¼, tacos hasta abajo) | Lento de capturar | Orden del menú |
| La captura no decía qué mesa/folio | Errores de cuenta | Encabezado "Orden #N · Mesa X" en móvil/tablet |
| Barra inferior del mesero escondía la 3ª estación (Taquero) | Sin acceso rápido al KDS principal | Hasta 3 estaciones, pestañas flexibles; "Meseros" → "Órdenes" |
| Lista de órdenes con doble margen (tarjetas de 295 de 375 px) | Visual | `.cl-ops-page` |
| Avisos, comanda y ticket impresos con el `id` interno | "Orden #247" vs folio #3 en pantalla | Usan `orden.numero` |
| Notas rápidas de restaurante ("Término 3/4", "Sin gluten") | Irrelevantes | Notas de taquería ("Con todo", "Salsa aparte", "Doble tortilla"…) |
| 403/404/500 en inglés, sin estilo y sin salida | Usuario atorado | Página de error en español + "Regresar a mi pantalla" |
| `/` siempre mandaba al login aunque hubiera sesión | Ícono PWA y "regresar" rotos | Redirige por rol; `start_url` del manifest a `/` |
| Dashboard móvil: 1 KPI por pantalla (≈2,000 px de scroll) | La dueña no ve el día de un vistazo | 2 columnas compactas; periodos sin partirse |
| Fecha del dashboard vacía | Visual | `fecha_larga()` en español sin depender del locale |
| Corte: "Tarjeta $0" sin terminal, transferencia desbordada, `$1191.00` | Visual | Tarjeta sólo si está habilitada o tuvo cobros; grid flexible; separador de miles |

## Pendiente — requiere decisión

1. **Bebidas bloquea el cobro.** Un refresco espera a que alguien lo marque en el KDS de
   Bebidas, y la orden no se puede cobrar hasta entonces. En un puesto nadie atiende esa
   pantalla. Opciones: marca "sin preparación" por producto (nace listo) o asignar bebidas
   al mesero.
2. **Login de cocina con correo y contraseña fuerte.** Taqueros sin correo y con guantes:
   conviene un PIN de 4 dígitos por usuario en las tablets fijas.
3. **Datos bancarios fuera del wizard.** Hasta que la dueña capture la CLABE en
   Personalización, la pantalla de cobro no muestra a dónde transferir. Agregar al paso 1
   o un aviso en el dashboard.
4. **Marca inconsistente.** Login con logo KaiResto y "© 2025 KaiRest"; el wizard dice
   KaiRest; el modal de ticket usa `logoCasaLeones.svg` fijo. Definir si el login muestra el
   logo/nombre del negocio.
5. **Google Fonts bloqueadas por el CSP.** Inter nunca carga (errores en consola); se usa
   la fuente del sistema. Vendorizar Inter o quitar el `<link>`.
6. **Paso "Entregar" obligatorio antes de cobrar.** En para llevar son taps de más.
7. **Rate limit por IP.** Con Docker Desktop (Windows) todas las tablets pueden llegar con
   la misma IP y compartir el límite (10/min en login, 200/min global). Medir en el equipo
   real; si pasa, usar el usuario como llave.
8. **Copys sin acentos en el wizard** ("Tu Menu", "Taqueria", "Atras").
9. **Pantalla vacía del mesero** con CTA duplicados (botones + FAB encimados).
10. **"Monto a pagar"** en efectivo debería decir "Recibido" / "¿Con cuánto paga?".
