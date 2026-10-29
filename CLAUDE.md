# CasaLeones POS

Flask + PostgreSQL + Socket.IO + Redis + Gunicorn. Backend: `backend/`, Frontend: Jinja2 (único).

## Comandos
- `docker-compose up --build` — Levanta todo (web con gunicorn, db, redis, backup)
- `DATABASE_URL=sqlite:///dev_local.db REDIS_URL= ./.venv/bin/python -m backend.app` — Flask+Socket.IO local puerto 5005 sin Docker (también via `.claude/launch.json` → `flask-local-sqlite`)
- `npm run start:backend` — legacy: flask run puerto 5000, sin Socket.IO real ni deps garantizadas; preferir el comando anterior

## Stack
- Backend: Flask 3.1, SQLAlchemy, Flask-SocketIO, Flask-WTF (CSRF), Flask-Limiter, Flask-Session, Flask-Caching
- WSGI: Gunicorn (2 workers, 4 threads, Docker)
- DB: PostgreSQL 16 (Docker), connection pooling (pool_size=5, max_overflow=10, pool_pre_ping)
- Redis: sesiones (db1), rate limiting (db0), caché (db2)
- Migraciones: Flask-Migrate (Alembic) — c001, c002, c003, c004, c005, c006, c009
- Docker: Multi-stage build (python:3.12-slim), healthcheck, non-root user
- Backups: pg_dump cada hora via Docker, retención 7 días

## Estructura
- `backend/routes/` — auth, meseros, cocina, admin, api, orders, ventas, productos, inventario, reportes, facturacion, clientes, reservaciones, delivery, sucursales, auditoria, setup
- `backend/models/models.py` — Sucursal, Usuario, Producto, Orden, OrdenDetalle, Pago, Sale, Ingrediente, RecetaDetalle, MovimientoInventario, Cliente, Reservacion, Factura, DeliveryOrden, CorteCaja, NotaCredito, AuditLog, ConfiguracionSistema
- `backend/services/cfdi.py` — Integración Facturapi completa (timbrado, cancelación, notas de crédito, complemento de pago, descarga XML/PDF)
- `backend/services/audit.py` — Registro de auditoría (login, logout, pagos, facturación)
- `backend/services/pdf_generator.py` — Generación de PDF con WeasyPrint
- `backend/services/rfc_validator.py` — Validación RFC con dígito verificador SAT (módulo 11)
- `backend/services/printer.py` — Impresión ESC/POS (comandas, tickets, cortes de caja)
- `backend/services/seeder.py` — Seed idempotente (menú default, mesas, datos demo)
- `backend/data/catalogos_sat.json` — Catálogos SAT (regímenes fiscales, usos CFDI, formas de pago)
- `backend/services/delivery.py` — Integración delivery (Uber Eats, Rappi, DiDi Food)
- `backend/services/webhook_auth.py` — Verificación HMAC de webhooks delivery (Uber Eats, Rappi, DiDi Food)
- `backend/services/password_policy.py` — Validación de fuerza de contraseñas
- `backend/services/sanitizer.py` — Sanitización de inputs (texto, RFC, email, teléfono)
- `backend/templates/admin/` — inventario/, reportes/, facturacion/, clientes/, reservaciones/, delivery/, sucursales/
- `backend/templates/setup/` — _layout_setup.html, paso1-5.html (onboarding wizard)

## Fiscal / Pagos (Fase 2)
- IVA 16% automático (`Orden.calcular_totales()`, constante `IVA_RATE`)
- Multi-pago: efectivo, tarjeta, transferencia (modelo `Pago`)
- Split de cuenta, descuentos con auth admin
- Ticket imprimible desde modal de cobro

## Inventario (Fase 3 + Sprint 2)
- Ingrediente → RecetaDetalle → Producto (receta estándar)
- MovimientoInventario: entrada, salida_venta, merma, ajuste
- `descontar_inventario_por_orden()` auto al pagar
- Alertas de stock bajo
- `verificar_stock_disponible()` bloquea pedidos si `INVENTARIO_VALIDAR_STOCK=true`
- Validación al agregar productos (meseros + API orders)

## Reportes (Fase 3 + Sprint 4)
- Dashboard con filtro por rango de fechas
- Ventas, Top Productos, Meseros, Métodos de Pago, Mermas
- Export CSV en ventas y productos
- Gráficas interactivas Chart.js 4.x en los 5 reportes
- API JSON: `/admin/reportes/api/{ventas,productos,meseros,pagos,inventario}`
- Toggle tabla ↔ gráfica, export PNG por gráfica
- Ventas: línea (tendencia día), barras (por hora)
- Productos: barras horizontales (top 20), donut (categorías)
- Meseros: barras doble eje (ventas $ + # ventas)
- Pagos: donut (desglose métodos)
- Inventario: barras horizontales (mermas por ingrediente)

## CFDI (v5.2 — Sprint 3 completado)
- Facturapi integración completa: timbrado, cancelación con motivo SAT, descarga XML/PDF, reenvío email
- Validación RFC con algoritmo módulo 11 del SAT (dígito verificador)
- Catálogos SAT: 19 regímenes fiscales, 24 usos CFDI, formas y métodos de pago
- Notas de crédito (CFDI tipo E): parciales o totales, con timbrado independiente
- Modelo NotaCredito con factura_origen_id, uuid, facturapi_id, motivo, monto, estado
- Cliente con `regimen_fiscal` para cumplimiento CFDI 4.0
- Validación RFC client-side (`rfc-validator.js`) y server-side
- Sin key: facturas quedan en estado "pendiente"
- Configura `FACTURAPI_KEY` y `FACTURAPI_URL` en .env

## CRM (Fase 3 + Sprint 3)
- Modelo Cliente con RFC, razón social, régimen fiscal, datos fiscales
- Visitas y total gastado actualizados al pagar
- API búsqueda autocompletado `/admin/clientes/api/buscar`
- Inputs sanitizados: nombre, RFC, email, teléfono, notas

## Reservaciones (Fase 3 + Sprint 2)
- Mesa con capacidad, zona, estado (disponible/ocupada/reservada/mantenimiento)
- Reservacion con estado (confirmada/cancelada/completada/no_show)
- Mapa visual de mesas via API JSON
- Inputs sanitizados: nombre_contacto, teléfono, notas
- Flujo automático de mesa: ocupada al crear orden, disponible al pagar/cancelar
- `actualizar_estado_mesa()` con eventos Socket.IO `mesa_estado_actualizado`

## Delivery (Fase 4)
- Webhooks: `POST /delivery/webhook/{uber_eats,rappi,didi_food}`
- Verificación de firma HMAC por plataforma (`webhook_auth.py`)
- DeliveryOrden con external_id, payload, comisión
- Panel admin de órdenes delivery. Orden.canal = local/uber_eats/rappi/didi_food
- Secrets en .env: `UBER_EATS_WEBHOOK_SECRET`, `RAPPI_WEBHOOK_KEY`, `DIDI_WEBHOOK_SECRET`

## Multi-sucursal (Fase 4 + Sprint 2)
- Modelo Sucursal. FK en Usuario, Mesa, Orden, Sale, CorteCaja, Ingrediente
- CRUD admin `/admin/sucursales/`, selección en sesión
- `filtrar_por_sucursal(query, modelo)` — filtro automático por `g.sucursal_id`
- Filtrado aplicado a: meseros, órdenes, ventas, reportes, inventario, reservaciones, dashboard, corte de caja
- Superadmin con sucursal=None ve todas las sucursales

## PWA (Fase 4)
- `manifest.json`, `sw.js` (network-first + cache fallback)
- Offline page, push notifications scaffolding
- Instalable en dispositivos móviles

## Seguridad (v5.0 — Sprint 1 completado)
- CSRF: CSRFProtect activo. APIs JSON exentas.
- Auth: Flask-Login + sesiones Redis. Roles: superadmin, admin, mesero, taquero, comal, bebidas.
- CSP: Content-Security-Policy con nonces por request (`csp_nonce` en templates)
- CORS: Restrictivo por dominio (configurable via `CORS_ORIGINS` en .env)
- Contraseñas: Política enforced (min 8 chars, mayúscula, minúscula, número, no comunes)
- Anti-enumeración: Login con timing constante y mensaje genérico
- IDOR: `@verificar_propiedad_orden` en endpoints de mesero (admin bypass)
- Sanitización: `bleach` en todos los inputs de texto libre (clientes, inventario, reservaciones, descuentos, productos, usuarios)
- Logging: `logging` estándar, sin print() de debug.
- Rate limiting: Flask-Limiter con Redis persistente (auth: 10/min, delivery: 30/min, default: 200/min)
- Security headers: CSP, X-Content-Type-Options, X-Frame-Options, X-XSS-Protection, HSTS, Referrer-Policy
- Monitoreo: Sentry (configura `SENTRY_DSN` en .env), `/health` endpoint con pool stats

## Arquitectura (v5.1 — Sprint 2 completado)
- Config: `Config`, `DevelopmentConfig`, `ProductionConfig` con `config_by_name`
- Connection pooling: `SQLALCHEMY_ENGINE_OPTIONS` (pool_pre_ping, pool_recycle)
- WSGI: Gunicorn en Docker (workers, threads configurable via env)
- Docker: Multi-stage build, python:3.12-slim, non-root user, healthcheck
- Frontend React eliminado. Solo Jinja2.

## Impresión ESC/POS (v5.2 — Sprint 3 completado)
- `python-escpos>=3.0` para impresoras térmicas (USB o red)
- Comanda cocina: agrupada por estación, para llevar marcado
- Ticket cuenta: productos, descuentos, IVA, métodos de pago, cambio, propina
- Corte de caja: resumen ventas, métodos de pago, desglose
- Fallback texto para `window.print()` si no hay impresora
- Config: `PRINTER_TYPE` (none/usb/network), `AUTO_PRINT_COMANDA`

## Mapa Interactivo de Mesas (v5.3 — Sprint 4 completado)
- Mapa visual con posicionamiento drag-and-drop (admin)
- Color por estado: verde (disponible), rojo (ocupada), amarillo (reservada), gris (mantenimiento)
- Click: disponible → crear orden, ocupada → ir a orden activa
- Socket.IO en tiempo real (`mesa_estado_actualizado`)
- Filtro por zona, auto-refresh 30s, vista lista en móvil
- API: `/admin/mesas/<id>/posicion` (POST), `/api/ordenes/mesa/<id>` (GET)
- Archivos: `mapa_mesas.css`, `mapa_mesas.js`, `meseros/mapa_mesas.html`

## Optimización Tablets (v5.3 — Sprint 4 completado)
- Touch targets ≥48px en botones, nav, forms (media query 768-1024px)
- Grid productos 3 columnas en tablet
- Cocina: fuentes grandes legibles a 1.5m, layout landscape/portrait
- Header sticky en detalle de orden
- PWA: `display-mode: standalone`, `safe-area-inset`, `orientation: any`
- Ripple touch feedback en botones y tarjetas
- No scroll horizontal enforced
- `manifest.json` con `theme_color: #A6192E`, `orientation: any`
- Archivo: `tablet.css` (185 líneas)

## Gráficas Chart.js (v5.3 — Sprint 4 completado)
- Chart.js 4.x CDN cargado solo en páginas de reportes
- 5 reportes con gráficas interactivas + toggle tabla/gráfica + export PNG
- API JSON en `reportes.py` para datos de cada reporte
- Paleta consistente con tema CasaLeones
- Archivo: `reportes-charts.js` (280 líneas)

## Feedback Visual (v5.4 — Sprint 5 completado)
- Animaciones CSS: bounceIn, badgePop, checkMark, shimmer skeleton, slideInRight toasts, confettiPulse
- Toast helper mejorado: iconos (✅❌⚠️ℹ️🎉), role="alert", aria-atomic, auto-dismiss 3s
- Modal cancelación con motivo (5 opciones + texto libre)
- Bounce en product cards, badge pop en carrito

## Notas por Item (v5.4 — Sprint 5 completado)
- Modal de notas con 15 notas rápidas predefinidas (`notas_rapidas.json`)
- Toggle buttons + texto libre + cantidad
- Cocina: notas destacadas con alert-warning y badge bg-warning
- Carrito muestra notas con 📝
- API ya soporta `notas` en OrdenDetalle

## Dashboard Admin Mejorado (v5.4 — Sprint 5 completado)
- 8 KPI cards con skeleton loading: ventas, órdenes, ticket promedio, propinas, mesas, cocina, stock, corte
- 7 APIs nuevas: mesas_activas, ordenes_cocina, alertas_stock, propinas_hoy, ultimo_corte, ventas_7dias, actividad_reciente
- Gráfica ventas 7 días (línea) + Top 5 productos (barras horizontales)
- Lista alertas stock con barras de progreso
- Feed actividad reciente con badges de estado
- Auto-refresh 30s con indicador visual
- Archivo: `admin-dashboard.js` (~200 líneas)

## Modo Oscuro + Accesibilidad (v5.4 — Sprint 5 completado)
- `dark-mode.css`: CSS variables invertidas con [data-theme="dark"]
- Toggle 🌙/☀️ en navbar con localStorage persistente
- Auto-detect `prefers-color-scheme: dark`
- Cocina (taqueros, comal, bebidas): dark mode por defecto
- Skip-to-content link accesible
- `aria-label` en botones de icono, `role="region"` en toast container
- `focus-visible` outline 3px en todos los interactivos
- Mapa mesas: tabindex + role="button" + keyboard Enter/Space
- Scrollbar estilizado en dark mode

## Rentabilidad por Producto (v5.5 — Sprint 6 completado)
- Reporte `/admin/reportes/rentabilidad` — costo, margen, utilidad por producto
- Cálculo de costo via RecetaDetalle → Ingrediente.costo_unitario
- Badges de margen: rojo (<30%), amarillo (<50%), verde (≥50%)
- Gráfica scatter Chart.js (precio vs margen) con línea umbral 30%
- Export CSV + PDF

## Reporte Delivery (v5.5 — Sprint 6 completado)
- Reporte `/admin/reportes/delivery` — ventas por canal + comisiones
- KPI cards por canal (local, uber_eats, rappi, didi_food)
- Gráfica barras por canal, tabla comisiones delivery
- Export CSV

## Gestión Propinas (v5.5 — Sprint 6 completado)
- UI en cobro: botones 0%, 10%, 15%, 20% + monto personalizado
- `meseros.js` — `mostrarCobro()` con sección propina, `registrarPago()` envía propina en JSON
- Backend: `orden.propina` acumulado al registrar pago
- Corte de caja: KPI propinas_total
- Reporte meseros: columna Propinas por mesero

## Historial Auditoría (v5.5 — Sprint 6 completado)
- Modelo `AuditLog`: usuario_id, accion, entidad, entidad_id, descripcion, ip_address, user_agent, fecha
- Service: `backend/services/audit.py` — `registrar_auditoria()` helper
- Blueprint: `/admin/auditoria/` — lista paginada con filtros (fecha, acción, entidad)
- Auditoría en: login, logout, pago, crear factura, cancelar factura, complemento pago

## Complemento de Pago CFDI (v5.5 — Sprint 6 completado)
- `crear_complemento_pago()` en cfdi.py — CFDI tipo "P" para facturas PPD
- Factura.metodo_pago_cfdi: 'PUE' (exhibición) o 'PPD' (parcialidades/diferido)
- Selector PUE/PPD en formulario de facturación
- Ruta `/admin/facturacion/<id>/complemento-pago` GET/POST
- Botón "Complemento de Pago" visible solo en facturas PPD
- Template: `complemento_pago.html`

## Export PDF (v5.5 — Sprint 6 completado)
- WeasyPrint ≥60.0 para generación de PDF
- Service: `backend/services/pdf_generator.py` — `generar_pdf()` con templates HTML
- Templates PDF: `pdf/base_pdf.html`, `pdf/ventas.html`, `pdf/productos.html`, `pdf/corte_caja.html`
- Endpoints: `/ventas/pdf`, `/productos/pdf`, `/corte-caja/pdf`
- Botón "Exportar PDF" en ventas, productos, corte de caja
- Diseño profesional: header CasaLeones, KPIs, tablas, paginación, footer

## Pytest Suite (v5.5 — Sprint 6 completado)
- `pytest>=8.0`, `pytest-cov` en requirements.txt
- `tests/conftest.py`: fixtures (app, db SQLite in-memory, client, users, producto, mesa)
- `tests/test_auth.py`: login, logout, rutas protegidas
- `tests/test_orders.py`: creación de orden, cálculo IVA, pagos
- `tests/test_inventario.py`: ingredientes, recetas, movimientos, alertas stock
- `tests/test_reportes.py`: acceso reportes, CSV export, AuditLog
- `tests/test_models.py`: todos los modelos, health endpoint, Factura PUE/PPD

## PRD v5 — Progreso
- **Sprint 1 ✅** Seguridad + Base (8/8 items: CSP, webhooks, CORS, passwords, anti-enum, IDOR, sanitización, Redis)
- **Sprint 2 ✅** Arquitectura + Operación (6/6 items: filtrado sucursal, eliminar React, connection pooling, Docker, stock, flujo mesa)
- **Sprint 3 ✅** Fiscal + Operación (4/4 items: CFDI Facturapi completo, RFC validation SAT, notas de crédito, impresión ESC/POS)
- **Sprint 4 ✅** UX + Analytics (3/3 items: mapa mesas interactivo, optimización tablets, gráficas Chart.js)
- **Sprint 5 ✅** Refinamiento (4/4 items: feedback visual, notas por item, dashboard admin, modo oscuro + accesibilidad)
- **Sprint 6 ✅** Final + Calidad (7/7 items: rentabilidad, delivery report, PDF export, complemento pago, auditoría, propinas, pytest)

## PRD v6 UI Redesign — Progreso
- **Sprint 7 ✅** Foundation (tokens.css, 4 layouts, 8 component macros, base.html + login)
- **Sprint 8 ✅** Core CRUD (data_table, form_group, sidebar admin, migrate Users/Products/Mesas/etc CRUD)
- **Sprint 9 ✅** Operations Redesign (7/7 items: split-panel detalle_orden, product tiles + search, cart panel sticky, mesa grid color-coded, meseros cards + urgency, pago full-page multi-payment, historial CSV)
- **Sprint 10 ✅** KDS, Polish & Dark Mode (8/8 items: KDS conveyor+urgency+sound, dashboard period selector, dark mode data-bs-theme nativo, reportes 9/9 migrados, facturación 6/6 migrada, corte de caja paginación)
- **Sprint 11 ✅** Accessibility, Animation & QA (8/8 items: WCAG audit, focus management, aria-live, keyboard nav, prefers-reduced-motion, print CSS, performance audit, cross-browser/tablet)

## Instalador Multi-OS (Deployment)
- **macOS/Linux (Bash):**
  - `install.sh` — Installer script: detecta macOS/Ubuntu, verifica Docker + Git, clona repo a `~/kairest`, genera `.env` con secretos aleatorios, ejecuta `docker compose up -d --build`, health check loop
  - `uninstall.sh` — Limpieza completa: para containers, opción de borrar volúmenes (base de datos)
  - `update.sh` — Actualización: backup DB, `git pull`, rebuild containers, health check con versión
- **Windows (PowerShell):**
  - `install.ps1` — Installer PowerShell: verifica Docker Desktop + Git, clona repo a `%USERPROFILE%\kairest`, genera `.env` con `RNGCryptoServiceProvider`, `docker compose up -d --build`, health check, abre navegador automáticamente
  - `uninstall.ps1` — Detiene containers, opción de borrar volúmenes (base de datos)
  - `update.ps1` — Backup DB, `git pull`, rebuild containers, health check con versión
- `.env` auto-generado con: `SECRET_KEY`, `POSTGRES_PASSWORD`, `APP_PORT`, `CORS_ORIGINS`

## Onboarding Wizard (Setup)
- Blueprint: `backend/routes/setup.py` — 5 pasos, sin auth requerido
- Middleware: `_check_onboarding` en `app.py` redirige a `/setup/` si onboarding no completado
- Paso 1: Nombre del negocio → crea Sucursal
- Paso 2: Admin principal → crea Usuario superadmin con validación de contraseña
- Paso 3: Menú → plantilla default (seed_menu_default) o entrada manual de productos
- Paso 4: Mesas → selector ± (1-30), crea mesas numeradas
- Paso 5: Equipo → usuarios adicionales opcionales (mesero/taquero/comal/bebidas)
- Completar: marca `onboarding_completado=true`, `modo_sistema=basico`
- Templates: `backend/templates/setup/_layout_setup.html`, `paso1-5.html`
- Modelo: `ConfiguracionSistema` — almacén key-value para config persistente
- Service: `backend/services/seeder.py` — seed idempotente (menú, mesas)

## Modo Sistema (Básico/Avanzado)
- Constantes en `config.py`: `MODULOS_BASICOS` (dashboard, operaciones, catalogo, ventas), `MODULOS_AVANZADOS` (todos)
- Sidebar admin: filtrado dinámico con `{% if modo_sistema == 'avanzado' or group.key in modulos_basicos %}`
- Navbar base: Inventario, CRM, Fiscal, Delivery, Sucursales ocultos en modo básico
- Toggle: widget superadmin en sidebar, ruta POST `/admin/toggle-modo`
- Context processor: `_inject_modo_sistema` inyecta `modo_sistema` a todos los templates
- ConfiguracionSistema.get('modo_sistema', 'basico') como default

## Pytest Setup Tests (Deployment)
- `tests/test_setup.py`: 26 tests (ConfiguracionSistema 6, SetupWizard 13, ModoSistema 2, Seeder 4)
- Conftest: SQLite in-memory, Redis deshabilitado (`REDIS_URL=''`), filesystem sessions, memory limiter
- Test infrastructure: `_get_app()` guard para TESTING env, pool options condicionales para SQLite

## Bug Fixes & Hardening (Post-Sprint 11)
Auditoría completa del backend: 37 issues identificados, 17 corregidos (6 P0, 5 P1, 6 P2).

### P0 — Data Corruption / Crash
- `producto_form.py` + `productos.py`: Form↔Model mismatch corregido (precio_unitario→precio, categoria→categoria_id, estacion→estacion_id como SelectField coerce=int)
- `cocina.py` línea 169: Estados incorrectos 'pagado'→'pagada', 'finalizada'→'cancelada' (leak de órdenes cerradas)
- `meseros.py` cobrar_orden_post: Agregado `with_for_update()`, `begin_nested()` savepoint, inventario antes de commit, flag reconciliación
- `meseros.py` registrar_pago: Savepoint `begin_nested()` alrededor de `descontar_inventario_por_orden()`
- `meseros.py` agregar_productos: Merge ahora compara notas antes de fusionar items (consistente con orders.py)
- `app.py`: Removido `csrf.exempt(ventas_bp)` — fetch ya auto-inyecta CSRF token

### P1 — Security / Functional
- `app.py` format_money: Retorna `Markup()` para evitar double-escaping en Jinja2
- `auth.py` logout: Cambiado GET→POST, auditoría null-safe (verifica user_id antes de registrar)
- Templates (base.html, _layout_operations.html, _layout_admin.html): Links logout→POST forms con csrf_token
- `admin_routes.py` usuario_editar: Agregado update opcional de contraseña con `validar_password()`
- `ventas.py`: Null-body checks, ownership check (sale.usuario_id), re-close guard, validación cantidad

### P2 — Robustness
- `admin_routes.py` usuario_eliminar: Guard self-delete + check órdenes activas FK
- `admin_routes.py` producto_eliminar: Guard OrdenDetalle FK count
- `productos.py` eliminar_producto: Guard OrdenDetalle FK count
- `admin_routes.py` mesa_nuevo: Uniqueness check en número de mesa
- `admin_routes.py` mesa_eliminar: Check órdenes activas antes de borrar
- `orders.py`: Null-body checks en create_order, update_order_status, add_product_to_order, update_order_detail + validación FK mesa_id

## Bug Fixes & Hardening — Ronda 2 (Post-Sprint 11)
Segunda auditoría: 30 issues identificados.

### Grupo 1 — CSRF Hardening
- `app.py`: Removido `csrf.exempt(orders_bp)` y `csrf.exempt(setup_bp)` — solo queda `csrf.exempt(api_bp)` para JSON puro
- Setup templates (paso1-5.html) ya tenían `csrf_token()` en hidden fields
- Frontend CSRF ya cubierto: fetch override + jQuery `$.ajaxSetup` en base.html auto-inyectan `X-CSRFToken`

### Grupo 2 — Reportes Date Crash
- `reportes.py` `_parse_rango()`: try/except alrededor de `date.fromisoformat()`, fallback a primer-día-del-mes / hoy, guard `fi > ff` swap

### Grupo 3 — Ventas Query Memory
- `reportes.py` `reporte_ventas()`: Eliminado `.all()` que cargaba todos los Sale a memoria; KPIs ahora calculados desde `ventas_por_dia` aggregation (misma técnica que `export_ventas_pdf`)

### Grupo 4 — XSS Sanitización DOM
- `base.html`: Agregado `window.__escapeHtml()` helper global para sanitizar texto antes de inyectar en innerHTML
- `meseros.js` `moveCardToPagadas()`: Nombres y cantidades de producto escapados con `esc()`
- `detalle_orden.html`: `nombre`, `item.notas`, `_notasRapidas` escapados con `_esc()` antes de innerHTML
- `admin-dashboard.js`: `item.nombre` (stock alerts), `item.mesero`, `item.mesa` (activity feed) escapados

### Grupo 5 — DB Indexes + datetime.utcnow Deprecation
- `models.py`: `index=True` en 20+ columnas FK/filtro (Orden, OrdenDetalle, Pago, MovimientoInventario, Factura, Sale, SaleItem)
- `models.py`: Helper `utc_now()` → `datetime.now(timezone.utc)` reemplaza `datetime.utcnow` (deprecated Python 3.12)
- Todos los `default=datetime.utcnow` en columnas → `default=utc_now`
- Runtime calls `datetime.utcnow()` → `utc_now()` en: meseros.py, cocina.py, orders.py, api.py, admin_routes.py, delivery.py, reservaciones.py, cfdi.py

### Grupo 6 — OrdenEstado Constants
- `models.py`: Clase `OrdenEstado` con 11 constantes (PENDIENTE, ENVIADO, EN_PREPARACION, EN_COCINA, LISTA, LISTA_PARA_ENTREGAR, COMPLETADA, PAGADA, CANCELADA, FINALIZADA, LISTO)
- Magic strings reemplazados en: meseros.py, cocina.py, orders.py, api.py, admin_routes.py, reportes.py, utils.py, services/delivery.py
- Column defaults: `Orden.estado` y `OrdenDetalle.estado` usan `OrdenEstado.PENDIENTE`

## Launch Readiness Fixes (Post-Audit)
Auditoría de lanzamiento: 5 issues corregidos para demo con primeros clientes.

### Blocker 1 — Socket.IO Production Worker
- `docker-compose.prod.yml`: Cambiado gunicorn de `--workers N --threads N` a `--worker-class eventlet --workers 1`
- Sin eventlet worker, Socket.IO fallback a polling (sin WebSocket real-time)

### Blocker 2 — test_auth Logout
- `tests/test_auth.py`: `client.get('/logout')` → `client.post('/logout')` para coincidir con cambio POST-only en auth.py

### Important 3 — Favicon 404
- `backend/templates/base.html`: Referencia corregida de `img/favicon.ico` (no existe) a `img/kairest-logo.svg` (existe), type `image/svg+xml`

### Important 4 — Migration c009 Indexes
- `migrations/versions/c009_add_indexes_fk_filter_columns.py`: Migración Alembic para 24 índices FK/filtro (Grupo 5)
- Indexes en: configuracion_sistema, orden (5), orden_detalle (3), pago (2), movimientos_inventario (3), reservaciones, facturas (3), sales (3), sale_items (2)
- Usa `if_not_exists=True` para idempotencia

### Important 5 — Query.get() Deprecation (SQLAlchemy 2.0)
- 69 ocurrencias migradas en 15 archivos:
  - `Model.query.get(id)` → `db.session.get(Model, id)`
  - `Model.query.get_or_404(id)` → `db.get_or_404(Model, id)`
  - `Model.query.options(...).get_or_404(id)` → `db.get_or_404(Model, id, options=[...])`
  - `db.session.query(Model).with_for_update().get(id)` → `db.session.get(Model, id, with_for_update=True)`
- Archivos: app.py, utils.py, orders.py, api.py, clientes.py, productos.py, delivery.py, sucursales.py, ventas.py, cocina.py, reservaciones.py, inventario.py, facturacion.py, admin_routes.py, meseros.py

## Release Demo v6.1 (2026-07 — versión para primer cliente)
Versión auditada (3 rondas multi-agente) y validada con simulación E2E de 58 checks
(0 errores): wizard → orden mesa/para llevar → modificación post-envío → KDS por
estación → entrega → cobro efectivo → cancelación. Verificación de locks contra
PostgreSQL 16 real (no solo SQLite).

### Wizard flexible de estaciones (paso 3)
- `seed_from_template(key, custom_estaciones, origen_map)` — el negocio define cuántas
  estaciones opera y sus nombres; las estaciones de la plantilla se mapean a las reales
- Fallback server-side: ningún producto puede quedar con `estacion_id=None` (un producto
  sin estación jamás aparece en KDS y deja la orden incobrable) — aplica en plantilla y manual
- paso5: roles `cocina:<Estación>` dinámicos; login de cocina aterriza en su estación

### Concurrencia / integridad (flujo dinero)
- Locks `with_for_update`: Orden en pago Y cancelación (revalidación post-lock), Mesa en
  `seleccionar_mesa` (no doble orden activa), Ingrediente en descuento/reversión de
  inventario en orden determinista por id (anti lost-update y anti-deadlock)
- ⚠️ PostgreSQL rechaza `with_for_update` + `joinedload` (FOR UPDATE en outer join) —
  lockear primero, lazy-load después (patrón en registrar_pago/cancelar_orden)
- Reversión de inventario solo si existe MovimientoInventario `salida_venta` de la orden
- Cobro efectivo: `Pago.monto` = aplicado a la cuenta (corte cuadra), cambio = recibido −
  saldo − propina; tarjeta/transferencia rechazan monto > saldo
- IDOR cerrado: `@verificar_propiedad_orden` en cancelar/entregar/descuento/imprimir
- KDS: scope por orden+estación en marcar/batch-listo, 409 en órdenes cerradas/canceladas,
  `verificar_orden_completa` excluye CANCELADA
- Auditoría: cancelación, descuento, editar/eliminar usuario, toggle modo sistema

### Operación offline
- Vendors locales en `static/vendor/` (Bootstrap 5.3, jQuery 3.7.1, Socket.IO 4.7.5,
  Chart.js 4, chartjs-plugin-annotation, Lucide 0.460) — cero CDNs en runtime
- CSP endurecido a 'self' únicamente; sw.js v4 pre-cachea vendors

### Ciclo de vida
- `restore.sh` — restauración de backups con respaldo de seguridad previo y confirmación
- `update.sh` — aplica migraciones Alembic (stamp head inicial en bases create_all + upgrade);
  usa el mismo stack compose que install.sh (build local si hay .git)
- `install.ps1` — modo in-place: instala desde la carpeta del proyecto (ZIP/USB) sin Git
- `docs/GUIA_INSTALACION_WINDOWS.md` — guía cliente final (Docker Desktop, wizard, tablets)

### Repo
- Des-trackeados: `.venv/`, `flask_session/`, `instance/*.db`, `cookies.txt`,
  `pytest_results.txt`, `.DS_Store`, `__pycache__` (y agregados a .gitignore)
- Tests: 67 passed (`test_mesero_seguridad.py` nuevo: IDOR + race de mesa; 4 tests de
  estaciones flexibles en `test_setup.py`)
- Fuera de alcance de esta versión (pendiente para cliente que facture): guard de doble
  timbrado CFDI, NC acumuladas, complemento de pago vs monto cobrado

## Mesas Compartidas — Multi-cuenta (v6.2)
- Una mesa puede tener VARIAS cuentas (Orden) activas a la vez — mesas grandes
  compartidas por grupos distintos, típico de puestos pequeños/callejeros
- `Orden.alias` + `Orden.num_personas` (migración c010, idempotente con inspector)
- Selector de cuentas: `GET /meseros/mesa/<id>/cuentas` (`cuentas_mesa.html`) — lista
  cuentas activas (alias, mesero, items, total, hora) + form "nueva cuenta"
- `seleccionar_mesa` POST: sin `forzar_nueva=1` y con cuentas activas → redirect al
  selector; con `forzar_nueva=1` crea otra cuenta (lock de Mesa se mantiene)
- Mesa se libera SOLA al cerrar la última cuenta (actualizar_estado_mesa ya contaba
  órdenes activas — sin cambios); cancelar una cuenta no libera si hay otra abierta
- Grid mesas: badge "🧾 N cuentas"; mapa: click en ocupada → selector
- `/api/ordenes/mesa/<id>`: ahora devuelve `ordenes` (lista) + `orden_id` (compat)
- Alias visible en: cards de mesero, detalle de orden, KDS, pago, cobrar_info
- Ownership entre cuentas: mesero solo abre sus propias cuentas (verificar_propiedad_orden);
  las ajenas se muestran como informativas en el selector
- Tests: `tests/test_mesas_compartidas.py` (6) — suite total 73 passed

## UX Servicio — Alertas de mesero + Undo KDS (v6.2)
- meseros.js: `playNotif()` ahora también vibra (`navigator.vibrate`); eventos
  item_listo/orden_completa/cobro filtrados con `esMiOrden()` (card en DOM) — sin
  el guard, a cada mesero le sonaban las órdenes de todos
- KDS undo: `POST /cocina/<slug>/desmarcar/<orden_id>/<detalle_id>` — deshace un
  "listo" marcado por dedazo dentro de `UNDO_LISTO_SEGUNDOS` (120s); scope por
  estación + orden; si la orden ya estaba lista_para_entregar regresa a
  en_preparacion y reaparece en el KDS (emite nueva_orden_cocina + item_progreso)
- Check de item listo en KDS = botón deshacer (icono undo-2) durante la ventana;
  fuera de ventana el server responde 409 y el UI avisa
- Tests: `tests/test_kds_undo.py` (5). Suite total 79 passed.

## UX Servicio 2 — Badges, highlight y para-llevar (v6.2)
- `/cocina/api/estaciones` incluye `pendientes` (sum de cantidades de items
  pendientes en órdenes enviado/en_preparacion, por estación)
- Tabs de estación del layout de operaciones muestran badge con pendientes:
  polling 30s + evento `kds:actividad` (disparado por meseros.js en
  nueva_orden_cocina/item_listo) para refresh inmediato
- KDS: items agregados a una orden ya en pantalla se resaltan 8s
  (`.cl-kds-item--added`, resistente a refreshes vía `recentAddedItems` Map)
- KDS: toggle "Llevar 1º" en header — reordena tarjetas priorizando para-llevar
  (`data-para-llevar` en fragment), persistente en localStorage por estación,
  se reaplica tras cada refresh
- Test: conteo de pendientes por estación en test_kds_undo.py. Suite: 80 passed.

## Auditoría del Panel Admin (v6.2 — barrido de rutas + coherencia con v6.2)
Barrido HTTP de las ~70 rutas GET del admin como superadmin + pyflakes sobre
`backend/routes/`. 6 fallas reales corregidas:
- `api_ordenes_cocina` (KPI "En cocina") tronaba con 500: `utc_now()` es aware y
  `Orden.tiempo_registro` se guarda naive. Convención del repo: comparar contra
  `utc_now().replace(tzinfo=None)` (igual que el `now_utc` que se pasa a templates).
  Además contaba PENDIENTE en vez de ENVIADO — ahora usa los mismos estados que el KDS
- `admin_routes.py` no importaba `session` ni `Response`: **generar el corte de caja
  daba 500** (NameError) y el PDF del corte habría tronado apenas existiera pango
- `reportes.py` no importaba `flash`/`redirect`: la rama de error de los export PDF
  también tronaba
- `dockerfile` no instalaba pango/cairo → WeasyPrint fallaba en producción, no sólo en
  local. Agregadas libs del sistema; `generar_pdf` ahora captura el OSError del dlopen
  (no sólo ImportError) y degrada a flash
- Blueprint `productos` era un segundo CRUD bajo el mismo prefijo (`/admin/productos/`
  con slash ≠ `/admin/productos`) con templates que aún usaban `precio_unitario` → 500.
  Reducido a redirects al CRUD vigente de `admin_routes`; templates viejos eliminados
- Mesas compartidas invisibles para el admin: `admin/ordenes_activas.html` y
  `admin/historial_dia.html` son forks de las vistas de mesero que no recibieron el
  `alias` de v6.2. Agregado ahí y en el feed del dashboard (que además mostraba
  "Mesa P/LL" en órdenes para llevar)
- Tests: `tests/test_admin_panel.py` (5) — APIs del dashboard, corte de caja POST,
  alias en el feed, redirects legacy. Suite total 85 passed.
- Pendiente (no bloquea demo): el chip "N en cocina" de órdenes activas suma pendientes
  (aún no enviadas), así que no coincide con el KPI del dashboard ni con el KDS.

## Zona horaria del negocio — el día contable (v6.3)
**El hallazgo más caro de la auditoría financiera.** Las fechas se guardan en UTC
(`utc_now()`) pero los filtros usaban `func.date(columna) == date.today()`. En México
(UTC-6) eso manda al día siguiente **toda la venta posterior a las 18:00 local** — la
cena, que es el grueso de una taquería. Afectaba corte de caja, dashboard, reportes,
historial del día y métricas de cocina.

- `backend/services/tiempo.py` — `zona()`, `hoy_local()`, `rango_utc(fi, ff)`,
  `a_local()`, `iso_utc()`, `dia_local(col)`, `hora_local_sql(col)`
- Regla: filtrar por rango `col >= desde AND col < hasta` (además usa índice, a
  diferencia de `func.date()`), y agrupar por día con `dia_local(col)`
- `dia_local`/`hora_local_sql` resuelven por dialecto: PostgreSQL con `AT TIME ZONE`
  (respeta DST), SQLite con offset fijo (exacto para México, sin DST desde 2022)
- Configurable con `APP_TIMEZONE` en .env (default `America/Mexico_City`)
- Convertidos: admin_routes (corte, 11 APIs del dashboard, PDF), reportes.py (~50
  filtros + agrupaciones), meseros.py, cocina.py, delivery.py, auditoria.py
- `reservaciones.py` NO se convirtió: `Reservacion.fecha_hora` viene del form en hora
  local naive, ahí `date.today()` es correcto. Sí se corrigió comparar ese naive contra
  `utc_now()` aware al marcar mesa (TypeError al crear reservación con mesa)

### Horas visibles
- Filtros Jinja `hora_local`, `fecha_local`, `fechahora_local` (registrados en app.py);
  reemplazan `.strftime()` sobre columnas UTC en 16 templates. Un ticket de las 13:44
  se mostraba como 19:44
- Filtro `iso_utc` + `iso_utc()` en cocina.api_orders: sin la `Z`, `new Date()` lee el
  timestamp como hora local y el **cronómetro del KDS quedaba 6 h en el futuro** (00:00
  permanente). También la gráfica "ventas por hora" mostraba el pico de la comida a las 19:00

## Cuadre de caja — propina por método de pago (v6.3)
- `Pago.propina` (migración c011, idempotente): la propina sólo vivía en `Orden`, sin
  saber por qué método entró
- Corte: "Efectivo en caja" = venta en efectivo + propinas en efectivo, con el desglose
  visible. Antes decía sólo la venta, así que contar el cajón siempre daba un "sobrante"
  exactamente igual a las propinas. La `diferencia` del arqueo y el `efectivo_esperado`
  guardado en `CorteCaja` usan ya el monto que debe estar físicamente en la caja
- Pagos anteriores a c011 tienen `propina=0`; el KPI "Propinas" (lee `Orden.propina`)
  puede no coincidir con el desglose de efectivo para esos registros históricos

### Verificado end-to-end
Venta real contra el server (mesero → KDS → entrega → cobro): 3 × $25 = $75, cliente
paga $125 con $20 de propina → cambio $30, `Pago.monto` = $75 (no los $125). El mismo
$75 aparece en dashboard, reporte de ventas, top productos, reporte de pagos y corte.
- Tests: `tests/test_finanzas.py` (10) con control negativo verificado — al revertir las
  consultas al día UTC, el test del corte falla. Suite total 95 passed.

### Pendientes financieros (decisión de negocio, no bugs de código)
- Propina con tarjeta: `registrar_pago` rechaza cobrar más que el saldo, así que la
  propina se registra en la orden pero **nunca se le cobra al cliente**
- `cobrar_orden_post` (ruta legacy `/ordenes/<id>/cobrar`, sin uso en el frontend)
  guarda `Pago.monto = monto_recibido` incluyendo el cambio: inflaría el corte. El flujo
  vivo es `/ordenes/<id>/pago`, que sí aplica sólo el saldo

## Transferencias con verificación + métodos de pago configurables (v6.4)
El negocio piloto no acepta tarjeta pero sí transferencias, y una de las dueñas revisa
en su app del banco que el depósito haya llegado antes de dar la cuenta por pagada.
Antes el sistema sólo guardaba un `referencia` de texto libre, opcional, que **no se
mostraba en ninguna pantalla del admin**: un cobro marcado como transferencia cerraba
la cuenta aunque el dinero nunca llegara, y el corte se veía perfecto.

### Modelo
- `Pago.verificado` / `verificado_por` / `fecha_verificacion` (migración c012, idempotente)
- `Orden.total_pagado()` **sólo suma pagos verificados** — un depósito sin confirmar no
  cubre la cuenta ni la cierra. `total_por_verificar()` para mostrar lo que está en el aire
- El efectivo nace verificado (está en la mano); la transferencia nace pendiente

### Flujo
- Cobro con transferencia: referencia **obligatoria** (sin ella no se puede buscar en el
  estado de cuenta), la orden NO se cierra, se emite `transferencia_por_verificar`
- `/admin/pagos/verificar` (admin/superadmin) — bandeja con hora, cuenta, referencia,
  quién cobró y monto; botones "Llegó" y rechazar. Badge con contador en el sidebar
  (polling 30s + eventos Socket.IO)
- Confirmar → cierra la cuenta, genera la venta y libera la mesa. Rechazar → borra el
  pago, la cuenta vuelve a quedar por cobrar. Ambos quedan en auditoría
- Doble verificación devuelve 409 (no duplica la venta)

### `backend/services/cobro.py`
`cerrar_orden_pagada()` — extraído de `registrar_pago` porque ahora el cierre ocurre
desde dos lados (cobro en efectivo y confirmación posterior de la dueña) y ambos deben
dejar el mismo rastro: venta, inventario descontado, cliente actualizado, mesa liberada.
La venta se atribuye a `orden.mesero_id`, **no** a quien aprieta el botón — si no, el
reporte de meseros le acreditaría las ventas a la dueña.

### Métodos de pago configurables
- `backend/services/pagos.py` + `ConfiguracionSistema['metodos_pago']`
- Default `efectivo,transferencia` (tarjeta apagada: el negocio no tiene terminal). Se
  habilita desde Personalización con checkboxes
- `registrar_pago` valida contra los habilitados; la pantalla de cobro pinta sólo esos

### Corte de caja
- Los pagos sin verificar **no cuentan** como ingreso del día
- Aviso con monto y liga a la bandeja cuando hay transferencias pendientes

### Corregido de paso
`pago.html` leía `data.orden_cerrada` pero el backend responde `orden_pagada`: el overlay
de "orden pagada" nunca se mostraba y la pantalla se quedaba recargando el saldo.

- Tests: `tests/test_transferencias.py` (10). Suite total 105 passed.

## Datos bancarios configurables (v6.4)
- `backend/services/banco.py` + `ConfiguracionSistema`: `banco_nombre`, `banco_titular`,
  `banco_clabe`, `banco_referencia_extra`
- Se capturan en Personalización y aparecen en la pantalla de cobro al elegir
  transferencia, con la CLABE agrupada de 4 en 4 y botón "Copiar CLABE" (con fallback a
  `execCommand` porque las tablets abren el sistema por http, sin clipboard API)
- **Validación de CLABE con dígito verificador** (ponderación 3-7-1, módulo 10), igual
  que el validador de RFC: 18 dígitos con un número cambiado NO se guarda. Un dígito mal
  capturado manda el dinero a la cuenta de otra persona
- Tests: `tests/test_datos_bancarios.py` (12), incluye 3 CLABEs reales de bancos distintos

## CSP mataba todos los handlers inline (bug preexistente grave)
El CSP es `script-src 'self' 'nonce-…'` sin `'unsafe-inline'`, así que **los atributos
`onclick`/`oninput`/`onchange`/`onsubmit` del HTML nunca se ejecutaron**. Verificado en
el navegador: `element.onclick` queda en `null` y el handler no corre.

Había 24 repartidos por los templates. El peor caso: **13 en `pago.html`**, o sea que la
pantalla de cobro de página completa estaba inerte — no se podía elegir método, ni usar
los montos rápidos, ni poner propina, ni siquiera apretar "Confirmar Pago".

Otros afectados: cálculo de diferencia en vivo del arqueo, filtros de zona al elegir
mesa, preview del logo, cerrar toasts, y los `confirm()` antes de cancelar una factura
ante el SAT (se ejecutaban sin preguntar).

- Convertidos a `addEventListener` dentro de los `<script nonce>` existentes, usando
  `data-*` para los parámetros que iban en el atributo
- Dos patrones repetidos (`data-cerrar-toast`, `data-confirmar`) se enganchan una sola
  vez con delegación en `base.html`
- El estilo de foco que se hacía con `onfocus`/`onblur` pasó a CSS (`.cl-corte-campo:focus`)
- **Regla para adelante: nada de handlers en atributos HTML** — no funcionan en este
  sistema. Todo va en un `<script nonce="{{ csp_nonce }}">`

## Tema claro real + arranque por defecto (v6.5)
Auditoría de contraste (medida en el navegador, WCAG): el **tema claro no existía**.
Los tokens v7 (`--cl-canvas`, `--cl-surface-*`, bordes, sombras, velos) sólo tenían
valores oscuros y nunca se sobrescribían, así que en claro salía texto `#101828` sobre
fondo `#0A0B10` — **contraste 1.02:1, negro sobre negro**. Peor aún, el arranque sólo
*activaba* oscuro; una tablet en modo claro sin preferencia guardada caía en ese estado
roto (el default de fábrica de cualquier tablet).

### Modelo de tokens
- Los tokens de superficie ahora viven **claros en `:root`** y el bloque
  `[data-theme="dark"]` los devuelve a oscuro. Motivo: un puesto de calle con sol —
  con fondo oscuro la pantalla es un espejo. Claro es el default.
- `--cl-overlay-subtle/overlay/overlay-strong`: reemplazan los 84
  `rgba(255,255,255,α)` de baja opacidad (tintes/hover/bordes) que sólo aclaran sobre
  oscuro; ahora oscurecen en claro y aclaran en oscuro
- `--cl-*-text` (success/warning/error/info/danger/brand): los `-500` brillan sobre
  oscuro pero no contrastan como texto sobre blanco. Estos tokens usan el `-700`/`-600`
  en claro y el brillante en oscuro. Retarget mecánico: sólo los usos como `color:`
  (98 sitios), no los fondos de badge (que sí quieren el color brillante)
- `--cl-topbar-bg`: la topbar de operaciones tenía `rgba(13,14,20,.92)` fijo → texto
  claro sobre fondo claro. Ahora es un token que se invierte

### Arranque del tema (base.html)
- Default **claro**; respeta `localStorage.theme` si el usuario eligió. Ya no auto-sigue
  el modo del SO (era impredecible y el caso de uso pide claro)
- `force_theme` por template: el KDS lo fija en `'dark'` (tablero fijo, lectura a
  distancia, normalmente bajo techo). El resto usa el default

### Resultado (medido)
- Meseros en claro: de 17 fallos AA → 1 (un contador de 10px en 4.33). Admin: 0 fallos
- Oscuro sin regresión; KDS intacto (verde/ámbar brillantes sobre negro)
- Fuentes de cronómetro (11→12.5px) y contadores (10→11px) subidas: mejora en ambos temas

### Bugs latentes corregidos de paso
- `--cl-danger-500`, `--cl-success-600`, `--cl-primary-100/500/600/700` se usaban en
  templates pero **nunca se definieron** (caían a negro/heredado). Agregados como alias
- `v7-base.css` forzaba `--bs-body-bg`/`html`/`body` a oscuro hardcodeado, ignorando el
  tema. Ahora usan los tokens

### Regla
Nada de colores de superficie hardcodeados. Todo fondo/borde/texto va por token para
que herede el tema. Colores semánticos como texto → `--cl-*-text`, no `-500`.

## Auditoría móvil — celulares y tablets (v6.5)
Medición en 360×640 (gama baja), 390×844, 430×932 y tablet 768×1024, sobre las
pantallas del mesero, cobro, KDS, dashboard y transferencias.

### Lo que ya estaba bien
Cero scroll horizontal en todas las pantallas y tamaños. KDS en tablet impecable
(tipografía grande, LISTO enorme, oscuro forzado). Sin tablas desbordadas en el admin.

### Corregido
- **Los FAB tapaban el botón "Cobrar"** y las pestañas de estación, en TODOS los anchos
  de celular (el contenedor iba de 822 a 916 y la barra inferior arranca en 876).
  `.cl-fab-container--sobre-tabs` los sube por encima de la barra (56px + notch).
  Clase explícita en vez de `:has()`: los WebView viejos de gama baja no lo soportan
- La regla que reservaba espacio inferior apuntaba a `.cl-ops-main`, clase que el
  `<main>` **no tenía** — por eso el contenido quedaba debajo de la barra. Se conectó,
  y las pantallas con FAB reservan además su pila (`tiene_fab` → `--con-fab`)
- **La bandeja de transferencias era una tabla de 6 columnas**: 594px en un contenedor
  de 328, con el botón "Llegó" en x=468, fuera de la pantalla. Patrón nuevo
  `.cl-tabla-cards`: en <768px cada fila se apila como tarjeta con su `data-label` y el
  botón principal a todo lo ancho (thead se oculta accesible, no con display:none)
- **"Confirmar Pago" caía fuera de la vista** (y=883 en pantalla de 640): ahora es
  `position:sticky` al pie en celular
- **Zoom automático de iOS**: 5 campos bajo 16px. Regla global de 16px + alto 44px
- **Objetivos táctiles**: de 21 a 8 por pantalla, y los que quedan son 38–43px (antes
  había de 14×14 —cerrar sesión— y 18×25 —estrella de favorito—)
- **Letra bajo 12px**: de 46 a 1 en detalle de orden. El piso usa prefijo `html` para
  ganarle a los `<style>` de cada plantilla, que si no vencen por orden de cascada

### Compresión (lo que más pesa en gama baja)
Los estáticos viajaban **sin comprimir**: `lucide.min.js` son 356 KB en crudo.
- Flask-Compress con `COMPRESS_ALGORITHM` y **`COMPRESS_ALGORITHM_STREAMING`** — este
  segundo es clave: los estáticos van en streaming y usan su propia lista, que por
  defecto no incluye gzip, así que un navegador sin brotli se quedaba sin comprimir
- Medido con cabeceras de navegador viejo (`gzip, deflate`): **842 KB → 188 KB (−78%)**

### Pendiente
La librería de iconos son 348 KB para ~107 iconos usados; un subconjunto ahorraría otro
tanto, pero requiere paso de build (hoy todo es vendorizado a mano).

## Encabezado de órdenes: contadores dentro de los filtros (v6.5)
En 360×640 el chrome se comía **319 px de 640** antes de la primera orden: una fila de
chips ("5 activas / 5 en cocina / 5 urgentes"), otra con el botón Actualizar, y los
filtros partidos en **tres renglones**. Los chips y los filtros decían lo mismo.

- Los contadores viven ahora **dentro de los filtros** (`cl-pill-count`); la fila de
  chips se eliminó en `meseros.html` y `admin/ordenes_activas.html`
- `.cl-filter-row`: una sola fila que **se desliza de lado** en celular
  (`flex-wrap:nowrap` + `overflow-x:auto` + `scroll-snap`), y sigue envolviendo normal
  en ≥768px. La sangría negativa deja los filtros a ras del borde al deslizar
- Filtros de Urgentes y Llevar sólo aparecen si hay algo que filtrar
- El botón Actualizar queda sólo icono en celular (ahorraba una fila entera al envolver)
- `updateFilterCounters()` en meseros.js: se quitó el bloque que actualizaba los chips
  (código muerto; los ids ya no existen)

Medido: primera tarjeta de **319 px → 184 px**, filtros de **96 px en 3 filas → 48 px en
1**, y de 1 a **3 órdenes visibles** sin hacer scroll. En la vista de mesero el botón
"Cobrar" de la primera orden ya se ve sin desplazarse.

## Órdenes borrador: nada existe hasta que hay algo pedido (v6.6)
Tocar "Nueva orden" creaba la fila al instante: si el mesero se regresaba quedaba una
cuenta fantasma ocupando la mesa y contando como activa. En la base de la demo había
**4 de 6 órdenes vacías**.

### Por qué no se crea "hasta confirmar"
El carrito **no es local**: cada producto se guarda al tocarlo (`POST /api/ordenes/<id>/detalle`).
Mover el carrito al navegador significaría perder la orden completa si el celular se
bloquea a media captura — en gama baja el WebView mata pestañas en segundo plano. Además
la mesa se marca ocupada al crear, y el sistema permite agregar productos a una orden ya
enviada a cocina, así que habría que mantener dos flujos.

La solución conserva el guardado por toque, pero **mientras la orden esté vacía no existe
para nadie**:
- `utils.no_es_borrador()` — condición SQL (`estado != pendiente OR tiene detalles`).
  Aplicada a la lista de órdenes y al conteo de ocupación de mesa
- **Reutilización**: si el mesero ya tiene un borrador vacío de esa mesa (o para llevar),
  se reutiliza en vez de crear otro. Tocar 3 veces = 1 orden
- La mesa se ocupa **con el primer producto**, no al elegirla (en `orders.py` y en
  `agregar_productos_a_orden`)
- `utils.limpiar_borradores(mesero_id, minutos=10)` — barrido al abrir la lista; no
  depende de que el mesero use "Regresar" (puede salir con el gesto del teléfono)
- El selector de cuentas ignora **sólo el borrador propio**: el de otro mesero sí avisa,
  para que dos no levanten la misma mesa sin enterarse

### `crear_orden_para_llevar` pasó a POST
Era un enlace `GET` sin CSRF: bastaba con que el navegador precargara la liga para crear
una orden. Ahora responde 405 a GET. Los 6 enlaces usan `data-post-link`, manejado con
delegación en `base.html` (arma un form con CSRF y lo envía; bloquea el doble tap).

- Tests: `tests/test_ordenes_borrador.py` (10). Los de mesas compartidas se actualizaron
  para darle producto a la cuenta antes de exigir el selector — sin productos ya no es
  una cuenta. Suite total 128 passed.

## Salida homogénea desde los paneles de cocina (v6.6)
El KDS tenía una flecha pelona de 15px sin etiqueta, en un encabezado que **se desbordaba
de lado** (625 px en una pantalla de 360), así que competía con chips cortados.
- `.cl-kds-salir` — botón con etiqueta visible ("← Panel" para admin, "← Mis Órdenes"
  para mesero), siempre arriba a la izquierda
- El encabezado del KDS envuelve en celular en vez de desbordarse; en tablet sigue en
  una sola fila de 60px

## Folio diario por sucursal (v6.6)
El `id` de Orden es una secuencia global compartida por todas las sucursales, y además
salta cuando se descarta un borrador: al tercer día el cliente escucharía "orden 247".

- `FolioDiario(sucursal_id, fecha, ultimo)` con UNIQUE — contador por sucursal y día
  contable (`hoy_local()`, así que respeta la zona del negocio)
- `Orden.folio` + `Orden.folio_fecha` (migración c013, idempotente)
- `Orden.numero` — property: el folio, o el `id` si no tiene. Las órdenes anteriores a
  esta función siguen mostrándose sin romperse
- `services/folio.py::asignar_folio()` — idempotente (agregar un segundo producto no
  renumera). Bloquea el contador con `with_for_update()` para que dos meseros que
  registran su primer producto al mismo tiempo no se lleven el mismo número; la
  creación del contador va en savepoint y tolera la carrera por el UNIQUE
- **Se asigna con el primer producto**, cuando la orden deja de ser borrador: un
  borrador abandonado no quema número
- El `id` sigue siendo la llave para URLs y relaciones; sólo cambió lo que se muestra
  (20 lugares en templates + `data-orden-num` que usa meseros.js)

Verificado contra el servidor: 3 borradores abandonados → 0 folios usados; luego 3
órdenes reales con ids internos 5, 6, 7 → folios 1, 2, 3.

### El contador guarda 0, nunca NULL (bug encontrado en revisión)
`Orden.sucursal_id` viene **NULL** en la instalación de una sola sucursal (que es la del
cliente). El contador arrancó con esa columna nullable y `UNIQUE(sucursal_id, fecha)`:
en SQL **dos NULL nunca son iguales**, así que el UNIQUE no impedía filas duplicadas.
Probado contra PostgreSQL real con 12 órdenes simultáneas: se crearon **5 contadores** y
**3 órdenes recibieron el folio 1**, sin ningún error visible.

`FolioDiario.sucursal_id` es ahora `NOT NULL DEFAULT 0` (0 = sin sucursal, sin FK porque
0 no es una sucursal real) y el servicio normaliza con `sucursal_id or 0`. Revalidado:
60 órdenes simultáneas en 3 sucursales → 1..20 en cada una, cero duplicados, 3
contadores. **SQLite ignora `with_for_update`, así que la concurrencia sólo se puede
probar contra PostgreSQL** — los tests en SQLite fijan el invariante (el contador nunca
guarda NULL), no la serialización.

- Tests: `tests/test_folio_diario.py` (10, con control negativo verificado).
  Suite total 138 passed.

## Operación sin poder entrar: recuperar acceso y restaurar (v6.6)
Preparación para que el cliente lo use sin Marco enfrente. Los tres huecos no eran de
producto sino de **operación**: qué hace el negocio cuando algo sale mal y nadie del
equipo técnico está ahí.

### Contraseña olvidada
No había ningún camino de recuperación: olvidar la contraseña del admin dejaba el
sistema inservible salvo entrando a mano a la base. `backend/cli.py` agrega dos comandos
al `flask` de la app (registrados en `create_app`):
- `flask usuarios` — lista correo/nombre/rol/sucursal (el dueño no recuerda con qué
  correo se dio de alta)
- `flask reset-password <correo>` — pide la contraseña sin mostrarla (o `--password`),
  la valida con `validar_password()` y la deja en auditoría

Se pasa `usuario_id` explícito a `registrar_auditoria`: fuera de request, la línea
`session.get('user_id')` lanza `RuntimeError` **fuera del try** del servicio.

En Docker: `docker compose exec web flask reset-password correo@ejemplo.com`
(`FLASK_APP=backend.app` ya viene en el compose).

### `restore.ps1` — el backup que no se podía restaurar
Los respaldos corren cada hora y la guía del cliente es de Windows, pero `restore.sh`
sólo existía en bash. Portado con la misma secuencia: respaldo de seguridad previo →
parar `web` (no la db) → `pg_restore --clean --if-exists` → arrancar → health check.

**Los .dump binarios NO pueden pasar por la redirección de PowerShell**: `>` convierte
la salida a texto y corrompe el archivo, y `<` ni siquiera existe como operador. Ambos
`pg_dump`/`pg_restore` van por `cmd /c "... > archivo"`. Por esto los backups que
generaba `update.ps1` estaban **corruptos desde siempre** — no se habrían podido usar.

### `update.ps1` no aplicaba migraciones
El bug más caro del camino Windows: `update.sh` hace `flask db stamp head` (si la base
nació de `create_all`) + `flask db upgrade`, y la versión PowerShell **no tenía ese
paso**. Actualizar en Windows dejaba el código nuevo contra el schema viejo — sin la
columna `folio`, cada orden truena. Portado igual que el bash.

Además `update.ps1` elegía `docker-compose.prod.yml` en cuanto el archivo existiera,
pero `install.ps1` instala con `docker-compose.yml` (build local) y el clon de git trae
ambos: la primera actualización cambiaba al equipo a jalar `ghcr.io/marqdomi/kairest`,
una imagen distinta a la que tenía corriendo. Ahora usa la regla de `update.sh`: con
`.git` → build local; `prod.yml` sólo para despliegues sin git.

### Ruta legacy de cobro eliminada
`POST /meseros/ordenes/<id>/cobrar` guardaba `Pago.monto = monto_recibido`, **con el
cambio incluido**: cobrar $75 con un billete de $100 registraba $100 e inflaba el corte.
Ningún frontend la llamaba (el flujo vivo es `/ordenes/<id>/pago`) pero seguía expuesta.
Borrada junto con sus imports huérfanos.

- Tests: `tests/test_cli.py` (7, con control negativo verificado). Suite total 145 passed.
- **No verificado**: la instalación en frío en Windows real (Docker Desktop → `install.ps1`
  → wizard) y la sintaxis de los `.ps1` — no hay PowerShell en el Mac de desarrollo.

## Demo con el primer cliente — barbacoa (v6.7)
Recorrido completo desde base en blanco con cada rol (wizard → mesero celular → KDS
tablet × 3 estaciones → cobro efectivo y transferencia → verificación → corte). Guion,
usuarios de prueba y hallazgos en `docs/DEMO_PRIMER_CLIENTE.md`; preview
`flask-demo-cliente` (SQLite `demo_cliente.db`, `RATELIMIT_ENABLED=false` porque la sonda
del preview hace HEAD / 3 veces por segundo).

- Plantilla `barbacoa` (primera del wizard) generada de `menu_restaurante.csv`: 58
  productos, estaciones Taquero / Comal / Bebidas. Productos se listan en orden de menú
  (`Producto.id`), no alfabético
- **Toques rápidos duplicaban renglones**: `agregarDirecto` va en cola de promesas y
  `add_product_to_order` lockea la Orden (`with_for_update`) antes del merge
- "Cobrar" de las tarjetas del mesero lleva a `pago_view` (el modal `mostrarCobro` queda
  para ver ticket de pagadas y el panel admin). El modal ignoraba métodos habilitados y CLABE
- `--cl-gold-500/600` eran tokens inexistentes → botón Cobrar del carrito invisible
- Textos visibles (avisos Socket.IO, flash, impresora) usan `orden.numero`, no `orden.id`
- `/` redirige por rol si hay sesión; páginas de error 403/404/429/500 en español
  (`error.html`, JSON en `/api/`); `manifest.json` `start_url` = `/`
- `services/tiempo.fecha_larga()` — fecha en español sin depender del locale
- Tests: `tests/test_demo_cliente.py` (11). Suite total 156 passed.
