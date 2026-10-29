# Prueba como usuario real — Admin, mesero y cocina (2026-10-29)

Recorrido desde una base en blanco con datos equivocados a propósito en cada formulario:
wizard → login → las 17 pantallas del modo básico → las 45 del avanzado → altas, bajas,
cobro, transferencias, corte y reportes. Guardas en `tests/test_prueba_usuario_admin.py`
(43 tests; sin las correcciones fallan 40).

## Lo que ya se defendía bien
- Login: vacío, usuario inexistente, inyección SQL, mayúsculas/espacios (desde el trabajo del PIN)
- Wizard: nombre vacío, contraseñas débiles o distintas, mesas fuera de rango, PIN inválidos u obvios
- Productos: precio negativo/texto/vacío, categoría o estación inexistente
- Mesas, estaciones y usuarios: duplicados, vacíos, borrados peligrosos (a sí misma, estación con productos)
- Cobro: orden no lista, montos 0/negativos/texto, método apagado, transferencia sin referencia o de más
- Reportes: 40 combinaciones de fechas absurdas sin error

## Corregido
| # | Dónde | Qué pasaba |
|---|---|---|
| 1 | Todo el texto | "Tacos & Más" se guardaba como "Tacos &amp;amp; Más" y así se veía (login, títulos, productos) |
| 2 | Wizard paso 2, Usuarios, Clientes | Cualquier texto servía de correo ("no-es-correo", "jefe@") |
| 3 | Wizard paso 3 (manual) | Productos a −$20 o con precio "abc" (guardado como $0) |
| 4 | Productos | Precio de $99,999,999,999 (en PostgreSQL: error 500) y productos con nombre repetido |
| 5 | **API de la orden** | **Cantidad 0 o negativa** ("−2 kg Barbacoa" restaba de la cuenta); "dos" daba 500 |
| 6 | Abrir mesa | Se guardaba "−4 personas" |
| 7 | **Transferencias** | **Confirmar una transferencia de una cuenta ya pagada en efectivo contaba el dinero dos veces** ($630 → $1,160 cobrados). Ahora 409 + aviso en la bandeja |
| 8 | **Corte de caja** | "1,160.00", vacío o texto se guardaban como **$0 contados** (faltante falso); negativos aceptados; notas con HTML |
| 9 | Personalización | Nombre vacío borraba el nombre del negocio; RFC/CLABE inválidos se descartaban diciendo "guardada exitosamente"; un texto renombrado a .png o un SVG con script se aceptaban como logo |
| 10 | Inventario | Vacío/texto/duplicado → error 500; stock y costos negativos; entradas negativas; mermas mayores al stock o negativas (subían el inventario) |
| 11 | Reservaciones | En el pasado, para 0/−5 personas, sin nombre, en una mesa que no existe |
| 12 | Clientes, Sucursales | Se creaban sin nombre |

Helpers nuevos en `backend/services/validacion.py`: `leer_monto` (acepta "1,160.50" y "$200"),
`leer_entero`, `leer_correo`. Úsalos en vez de `float()`/`int()` sobre `request.form`.

## No es bug del producto
- Los PDF tumbaron el servidor local (segfault): esta Mac no tiene `pango`. En Docker sí está.
- Datos viejos con "&amp;" se corrigen solos al volver a guardarlos.

---

# Mesero (Pedro, celular) y cocina (Taquero, Comal, Bebidas en tablet)

Guardas en `tests/test_prueba_usuario_roles.py` (6; sin el fix fallan los 6).

## Lo que ya se defendía bien
- PIN: equivocado, vacío, de un admin, de alguien que no existe; bloqueo tras 5 fallos
  (y la dueña puede desbloquear poniendo un PIN nuevo)
- Mesero: no puede ver, agregar ni cobrar órdenes de otro; no entra a ninguna pantalla
  del admin; descuento exige autorización; no se reenvía a cocina; no se agrega a una
  orden cancelada; no se entrega algo que cocina no terminó; notas con HTML se limpian
  y se recortan a 300
- Cocina: cada quien sólo ve su estación (403 en las demás); no marca items de otra
  estación ni de órdenes canceladas; marcar dos veces no duplica; deshacer funciona;
  no puede cobrar ni entrar al admin o a meseros
- Flujo completo entre estaciones: cuando Taquero, Comal y Bebidas terminan lo suyo, la
  orden pasa sola a "lista para entregar"

## Corregido
| Dónde | Qué pasaba |
|---|---|
| **Cancelar orden** | **El diálogo pedía el motivo pero el servidor lo ignoraba**: la auditoría sólo decía "cancelada". Ahora es obligatorio (si es "Otro", hay que escribirlo) y queda en la auditoría |
| **KDS** | **Una nota larga sacaba de la tarjeta el botón de marcar listo** (el renglón crecía a 1,724 px) |
| Entrar con PIN | `usuario_id` con texto → error 500 |
| Peticiones mal formadas | 400/415 salían en inglés ("Bad Request") |
| Sesiones sin Redis | Al pasar de 500 sesiones se borraban al azar: la dueña quedó fuera a media prueba. En Docker se usa Redis y no aplica, pero el preview de demo usa archivos |
