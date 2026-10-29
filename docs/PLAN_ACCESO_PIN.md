# Plan — Acceso rápido (usuario + PIN) y sesiones que no se caen

Implementado 2026-10-29 (las 6 fases; ver CLAUDE.md "Acceso rápido"). Decisiones de Marco:
- PIN **sólo en aparatos autorizados** (código de enlace de 6 dígitos)
- Sesión del mesero **16 h** (fin de turno); cocina 30 días; dueña 7 días
- La dueña entra **sólo con usuario + contraseña**
- PIN de **4 dígitos**

Objetivo: que entrar al sistema en el puesto tome **2 segundos y
cero teclado**, y que nadie tenga que volver a entrar a media jornada.

## Lo que pasa hoy (medido)

| Problema | Evidencia | Efecto en el puesto |
|---|---|---|
| Login con correo + contraseña fuerte (8+, mayúscula, número) | `auth.py`, `password_policy.py` | Un taquero con guantes escribiendo `tito@casaleones.mx` + `Leones2026x` en una tablet |
| La cookie de sesión **no tiene fecha de expiración** | `Set-Cookie: session=…; HttpOnly; Path=/` (`SESSION_PERMANENT = False`) | Muere al cerrar el navegador; en celulares de gama baja el sistema mata la app en segundo plano → el mesero vuelve a teclear todo |
| Redis sin persistencia en `deploy/gcp` | `--save ""` | Cada actualización o reinicio saca a todos |
| Correo obligatorio y único para todo usuario | `Usuario.email NOT NULL UNIQUE` | Hay que inventarle correo a quien no tiene |

## Propuesta

### 1. Sesiones persistentes (rápido, independiente, va primero)
- `SESSION_PERMANENT = True` → la cookie lleva fecha y sobrevive al cierre del navegador
- Duración **por rol**, guardada en la sesión y revisada en `before_request`:
  - Cocina (tablet fija del KDS): **30 días**
  - Mesero: **hasta fin de turno — 16 h** (al día siguiente, PIN de 4 dígitos)
  - Dueña/admin: **7 días**
- Redis con `appendonly yes` en `deploy/gcp` (las sesiones sobreviven reinicios)
- Se renueva con el uso (sliding): mientras trabajen, no vence

### 2. Usuario corto en vez de correo
- `Usuario.username` (único, minúsculas, p. ej. `pepe`, `tito`); se autollena del nombre
- `email` pasa a opcional (sólo la dueña lo necesita para recuperar acceso)
- El login de contraseña acepta **usuario o correo** (los usuarios actuales no se rompen)

### 3. PIN de 4 dígitos para personal (mesero y cocina)
- Pantalla **"¿Quién eres?"**: tarjetas grandes con el nombre de cada persona → tocas
  tu nombre → teclado numérico grande → al 4º dígito entra solo. Sin teclado del sistema
- PIN guardado con hash; se rechazan los obvios (`0000`, `1234`, `1111`…)
- **5 intentos fallidos → ese usuario se bloquea 5 min** (aviso a la dueña en auditoría)
- "Cambiar de usuario" de un toque en tablets compartidas
- La dueña sigue con contraseña (ve dinero, CLABE y reportes)

### 4. Dispositivos autorizados (lo que hace seguro al PIN en internet)
Al estar en la nube, el login queda expuesto a cualquiera. Un PIN de 4 dígitos solo
(10,000 combinaciones) no basta. Por eso el PIN **sólo funciona en dispositivos que la
dueña autorizó**, igual que en Square o Toast:
- Desde su panel, la dueña genera un **código de enlace de 6 dígitos** (válido 10 min)
- En la tablet o el celular nuevo: "Vincular dispositivo" → escribe el código → queda
  autorizado (cookie firmada de 1 año) y se le pone nombre ("Tablet comal")
- El dispositivo donde se hace el wizard queda autorizado solo
- Lista de dispositivos en el admin, con "Desautorizar" (celular perdido o mesero que se fue)
- En un dispositivo no autorizado sólo existe usuario + contraseña

### 5. Wizard, admin y recuperación
- Paso 2 (dueña): nombre, usuario, correo y contraseña
- Paso 5 (equipo): **nombre + rol + PIN** (botón "generar PIN"), sin correo ni contraseña
- Admin → Usuarios: cambiar o restablecer PIN y desbloquear
- CLI: `flask reset-pin <usuario>`

## Orden de trabajo

| Fase | Contenido | Se puede probar solo |
|---|---|---|
| 1 | Sesiones persistentes + Redis persistente | Sí: cerrar y abrir el navegador sin perder la sesión |
| 2 | Migración c014 (`username`, `pin_hash`, bloqueo, `email` opcional) + login por usuario | Sí |
| 3 | Dispositivos autorizados + código de enlace | Sí |
| 4 | Pantalla "¿Quién eres?" + teclado PIN + bloqueo | Requiere 2 y 3 |
| 5 | Wizard, admin de usuarios, CLI, guía | Requiere 2 |
| 6 | Tests + ensayo con 3–4 aparatos reales | Al final |

Todo en el stack actual (Flask + Jinja + JS sin build). Sin librerías nuevas.

## Riesgos

- **Toda la autorización vive en `session['user_id'|'rol'|'estacion_id']`** (40 usos). El
  login por PIN debe poblar exactamente las mismas llaves; se centraliza en una función
  `iniciar_sesion(usuario)` que usan los dos caminos
- Migración con `email` opcional: en PostgreSQL varios NULL no chocan con el UNIQUE
  (justo lo que queremos aquí, al revés que en el folio)
- Los tests usan `login(client, email, password)`: se mantiene compatible
