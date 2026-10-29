# Evaluación visual — KaiRest (2026-10-29)

Recorrido completo desde una base en blanco: wizard (5 pasos) → login → dashboard admin →
mesero en celular (375×812) → orden → KDS en tablet (768×1024) → cobro. Tema claro y oscuro.

**Veredicto corto:** la base de diseño es sólida (tokens, temas, accesibilidad, KDS muy bien
resuelto). Lo más débil es la **identidad**: el producto tiene tres logos, dos nombres y tres
números de versión, y nada lo conectaba con KAINET. Eso es lo que más se nota en una demo.

---

## 1. Identidad y marca

### Tres logos para el mismo producto
| Archivo | Qué es | Dónde aparece | Problema |
|---|---|---|---|
| `img/kainetResto.png` | Mascota con sombrero, texto "KaiResto · Punto de venta" | Login (160px), topbar de operaciones (28px), navbar legacy, logo por defecto del sidebar admin | **1.5 MB** (PNG 1024×1024). A 28–32px es una mancha ilegible: sombrero + texto no escalan |
| `img/kairest-logo.svg` | "K" blanca en círculo rojo | Wizard paso 1, default en Personalización | Es el único vectorial, pero sólo sale en el wizard |
| `img/logoCasaLeones.svg` | Logo del **cliente** (Barbacoa Casa Leones) | Modal de ticket en `meseros.js:552`, hardcodeado | **Fuga de white-label**: cualquier otro negocio vería el logo de Casa Leones en su ticket. Pesa 344 KB (JPEG embebido en SVG). Ese modal además muestra `data.orden_id` en vez del folio |

El wizard enseña la K roja y en el siguiente paso (login) aparece la mascota: el cliente ve dos
marcas distintas en los primeros 2 minutos.

### Dos nombres
- **KaiRest**: títulos de pestaña, instalador (`~/kairest`), imagen Docker, PDF, apple-mobile-web-app-title
- **KaiResto**: la mascota y los `alt` de las imágenes

Recomendación: **KaiRest** (ya está en la infraestructura) y retirar "KaiResto".

### Tres versiones
- Sidebar admin: `v7.0 · Admin` (hardcodeado en `_layout_admin.html`)
- `config.VERSION = '5.5.0'` — y es el `?v=` del cache-busting de **todos** los CSS, así que el
  número no ha cambiado desde hace varias versiones: una tablet con caché puede seguir con CSS viejo
  después de `update.sh`
- CLAUDE.md va en v6.7

Recomendación: una sola fuente (`config.VERSION`), subirla en cada release y mostrarla en el sidebar.

### Paleta KaiRest vs KAINET
- KaiRest: rojo `#C41E3A` / `#A6192E`, grises fríos
- KAINET (kainet.mx): terracota `#C4704A`, salvia `#6B8F5E`, café `#0D1F18`, beige `#F5EDE0`,
  Hanken Grotesk

**No recomiendo repintar la app con la paleta de KAINET.** El rojo ya está auditado para
contraste (v6.5), es reconocible en operación y un POS necesita colores funcionales, no de marca
corporativa. El modelo que funciona es el de **marca respaldada** ("Instagram from Meta"): el
producto conserva su identidad y la familia se nota en la firma.

### Lo que ya quedó hecho: firma "hecho por kainet."
- `templates/components/_kainet.html` → macro `firma_kainet()`, logo **inline** (no `<img>` ni
  hotlink): el sistema opera offline y el CSP sólo permite recursos propios. Las piezas oscuras
  del logo usan `currentColor`, así que funciona en claro, oscuro y sobre el degradado del wizard
  sin dos versiones del archivo
- Liga a `https://kainet.mx` en pestaña nueva
- Aparece en: wizard (todos los pasos), login, páginas de error, pie del sidebar admin, pie de los
  PDF ("Generado con KaiRest · hecho por kainet. · kainet.mx")
- **No** aparece en mesero ni KDS: ahí la marca es la del negocio y cualquier logo extra es ruido
- Logos originales copiados en `static/img/kainet/` como referencia
- De paso: el pie del PDF decía "Generado automáticamente por *Barbacoa X* POS" (usaba el nombre
  del negocio como si fuera el sistema), y el login decía "© 2025" fijo (la variable `now` no
  existe en ese contexto)

### Siguiente paso de marca (decisión tuya)
1. **Redibujar la K de KaiRest con la geometría de la K de kainet** (las 4 piezas), en rojo
   KaiRest. Así el ícono de la app, el favicon y el logo del wizard son visiblemente "de la familia"
   aunque no lleven la firma. Reemplazaría a la mascota y a la K en círculo
2. Si quieres conservar la mascota, que sea **ilustración** (login, wizard, materiales de venta) y
   no logo: nunca a menos de ~96px
3. Una página `kainet.mx/kairest` para que la liga de la firma aterrice en el producto y no en la
   home (hoy no existe ninguna ruta de producto en kainet-final)

---

## 2. Wizard (primera impresión)

- Sin bienvenida: la primera pantalla es directamente "Tu Negocio". Un subtítulo tipo
  *"Bienvenido a KaiRest — configura tu punto de venta en 5 pasos"* ubica al cliente
- Sólo el paso 1 tiene logo; los pasos 2–5 no tenían marca (ahora llevan la firma abajo)
- **Acentos faltantes** (paso 3): "Tu Menu", "Taqueria", "Cafeteria", "Puedes agregar mas despues",
  "Atras" (el paso 2 sí dice "Atrás")
- Paso 3: el texto *"decide abajo a cuál de tus estaciones…"* está **debajo** de los selects que
  explica; la etiqueta "¿Cuántas estaciones de cocina vas a operar?" se parte en 2 líneas sobre un
  input de media anchura; la tarjeta pega con el borde superior en pantallas bajas
- Paso 5: 4 campos en una fila de 560px — el placeholder "Min. 8 caracteres" se corta
- Los avisos (`flash`) del wizard reusan `.cl-toast`, que entra deslizándose desde la derecha y
  mide máximo 360px: dentro de la tarjeta se ve como una caja corrida, no como un aviso a lo ancho
- Salto de estilo wizard → login: el wizard es degradado rojo oscuro fijo (ignora el tema), el
  login es claro con cuadrícula. Son dos productos visualmente

## 3. Login

- La mascota a 160px domina la tarjeta; "Bienvenido / Inicia sesión para continuar" es genérico.
  Ya existe `brand_name`: la tablet del negocio podría saludar con **su** nombre ("Barbacoa Casa
  Leones") y dejar KaiRest en la firma
- (corregido) "© 2025" fijo

## 4. Operación — mesero en celular

- **Estado vacío duplica las acciones**: "Nueva Orden" y "Para Llevar" en el centro **y** en los
  FAB a la vez (4 botones para 2 acciones). El ícono del estado vacío es una taza de café
- **Los toasts de "producto agregado" se apilan encima de "Enviar a Cocina" y "Cobrar"** en el
  carrito, ~3 s por producto. Agregando rápido, los botones quedan tapados justo cuando se necesitan
- Tres colores de acción en la misma barra: verde (Enviar), dorado (Cobrar), rojo (marca). Y
  "Cobrar" usa ícono de **tarjeta** en un negocio que no acepta tarjeta (`banknote`/`wallet`)
- Tile de producto: la categoría truncada ("BARBACOA PO…") repite lo que ya dice el filtro activo y
  le roba una línea al nombre
- El buscador dice "Buscar producto… ( / )": el atajo de teclado no significa nada en un celular
- Cobro: montos rápidos fijos $100/$200/$500/$1,000 para una cuenta de $700 — sólo uno sirve.
  Mejor generar denominaciones ≥ saldo (exacto, siguiente billete de 100, de 500, $1,000)
- Tarjeta de orden: la hora aparece dos veces (arriba a la derecha y en el pie)
- Barra inferior: estaciones en orden alfabético (Bebidas, Comal, Taquero), no en el que se
  definieron en el wizard
- La dueña (superadmin) ve "Órdenes activas" con el chrome del admin (hamburguesa + breadcrumb que
  se parte en 2 líneas a 375px) y al entrar a una orden cambia al chrome de operaciones (logo +
  avatar). Mismo flujo, dos encabezados

## 5. KDS — lo mejor de la app

Legible a distancia, oscuro forzado, LISTO enorme, cronómetro claro. Detalles menores: en tablet
vertical una sola orden usa 1/3 del ancho; el indicador "Desconectado" en rojo en el pie apareció en
el servidor local (verificar en Docker con eventlet antes de la demo).

## 6. Panel admin

- (corregido) **Columna en blanco de 240px entre 769 y 991px de ancho** — iPads en vertical (810,
  820, 834). `tokens.css` escondía el sidebar bajo 992px pero `v7-sidebar.css` quitaba el margen
  del contenido sólo bajo 768px. Ahora ambos cortan en 992, igual que el botón hamburguesa
- Tarjetas KPI de ~200px de alto para un número: mucho aire, poca información por pantalla
- El botón de cerrar de los avisos es un `×` nativo del navegador, sin estilo

## 7. Técnico-visual

- **La tipografía diseñada nunca carga.** `tokens.css` y `v7-base.css` hacen `@import` de Inter y
  JetBrains Mono desde Google Fonts; el CSP (`style-src 'self'`) lo bloquea y además el sistema
  opera offline. Resultado: Segoe UI/Consolas en Windows, Roboto en Android, SF en iPad — la app se
  ve distinta en cada equipo, y cada página genera 2 errores de consola. Opciones: vendorizar Inter
  (woff2 subset latino, ~100 KB) o declarar el system stack como intencional y quitar los `@import`
- **Peso de imágenes**: `kainetResto.png` 1.5 MB (se carga en cada pantalla de operación para
  pintarse a 28px), `icon-512.png` 1.1 MB (favicon + apple-touch), `logo.svg` y
  `logoCasaLeones.svg` 344 KB cada uno. Los PNG no se benefician de gzip/brotli: en gama baja es
  más que todo el JS junto
- **Errores 400/405 crudos en inglés**: `error.html` cubre 403/404/429/500, pero un CSRF caducado
  muestra "Bad Request — The CSRF session token is missing." en Times New Roman. Falta registrar
  `CSRFError` y 405 en el mismo handler

## 8. Bug funcional encontrado en el recorrido (no visual) — ✅ corregido

**El KDS marca items como listos aunque el servidor los rechace.** El token CSRF de Flask-WTF
caduca a los 60 minutos (`WTF_CSRF_TIME_LIMIT` no está configurado; verificado: a los 61 min
`validate_csrf` responde "The CSRF token has expired"). El KDS nunca recarga la página completa —
sólo fragmentos por `fetch` — así que su token es el de la hora en que se abrió. Después de una hora:

- `marcarItemListo` (`kds_station.html:372`) **no revisa `resp.ok`**: la palomita se pone, el
  servidor respondió 400, nada se guardó, el mesero nunca se entera, y en el siguiente refresco
  (30 s) el item vuelve a aparecer pendiente
- "LISTO" (batch) sí revisa y falla con error
- Lo mismo aplica a cualquier POST desde una pantalla abierta más de una hora (celular del mesero)

Arreglo propuesto: `WTF_CSRF_TIME_LIMIT = None` (el token queda atado a la sesión, que ya expira
por su cuenta) + revisar `resp.ok` en `marcarItemListo` y revertir la palomita si falla.

---

## Prioridad sugerida

| # | Qué | Esfuerzo | Por qué primero |
|---|---|---|---|
| ~~1~~ | ~~Bug CSRF del KDS (§8)~~ ✅ | — | Corregido con `tests/test_csrf_turno.py` |
| 2 | Logo del cliente hardcodeado en el ticket (§1) | 10 min | Fuga de white-label al segundo cliente |
| ~~3~~ | ~~Página de error para CSRF/405 (§7)~~ ✅ | — | Corregido junto con el §8 |
| 4 | Un solo logo + un solo nombre + una versión (§1) | 1–2 h + decisión de diseño | Lo que más se nota en la demo |
| 5 | Acentos y orden del paso 3 del wizard (§2) | 20 min | Primera impresión |
| 6 | Toasts sobre los botones del carrito, CTAs duplicados (§4) | 30 min | Fricción diaria del mesero |
| 7 | Tipografía y peso de imágenes (§7) | 1 h | Consistencia entre equipos y carga en gama baja |
