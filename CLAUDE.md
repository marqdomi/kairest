# CasaLeones POS

Flask + PostgreSQL + Socket.IO + Redis + Gunicorn. Backend: `backend/`, Frontend: Jinja2 (único).

## Comandos
- `docker-compose up --build` — Levanta todo (web con gunicorn, db, redis, backup)
- `npm run start:backend` — Flask local puerto 5005

## Stack
- Backend: Flask 3.1, SQLAlchemy, Flask-SocketIO, Flask-WTF (CSRF), Flask-Limiter, Flask-Session, Flask-Caching
- WSGI: Gunicorn (2 workers, 4 threads, Docker)
- DB: PostgreSQL 16 (Docker), connection pooling (pool_size=5, max_overflow=10, pool_pre_ping)
- Redis: sesiones (db1), rate limiting (db0), caché (db2)
- Migraciones: Flask-Migrate (Alembic) — c001, c002, c003, c004, c005, c006
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
