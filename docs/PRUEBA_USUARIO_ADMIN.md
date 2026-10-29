# Prueba como usuario real — Admin (2026-10-29)

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
