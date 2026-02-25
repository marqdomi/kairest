# backend/routes/setup.py
"""
First-run onboarding wizard.
5-step setup: Negocio → Admin → Menú → Mesas → Equipo → Completar
No authentication required (creates the first admin user).
"""
import logging
from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from backend.extensions import db
from backend.models.models import ConfiguracionSistema, Sucursal, Usuario, Mesa, Categoria, Estacion, Producto
from backend.services.seeder import seed_from_template, get_template_list, seed_mesas
from backend.services.password_policy import validar_password
from backend.services.sanitizer import sanitizar_texto, sanitizar_email

logger = logging.getLogger(__name__)

setup_bp = Blueprint('setup', __name__, url_prefix='/setup')


def _onboarding_done():
    """Check if onboarding has been completed."""
    try:
        return ConfiguracionSistema.get_bool('onboarding_completado', False)
    except Exception:
        return False  # Table may not exist yet (fresh install)


def _ensure_tables():
    """Create tables if they don't exist (safety net for fresh installs)."""
    try:
        # Quick check: try to count configuracion_sistema
        ConfiguracionSistema.query.limit(1).all()
    except Exception:
        db.session.rollback()
        try:
            from backend.models.database import init_db
            init_db()
            logger.info('Tablas creadas desde setup blueprint (fresh install).')
        except Exception:
            logger.exception('Error creando tablas desde setup.')


@setup_bp.before_request
def _setup_ensure_db():
    """Ensure DB tables exist before any setup route runs."""
    _ensure_tables()


@setup_bp.route('/')
def index():
    """Entry point — redirect to step 1 or login if already done."""
    if _onboarding_done():
        return redirect(url_for('auth.login'))
    return redirect(url_for('setup.paso1'))


# ── Paso 1: Tu Negocio ──

@setup_bp.route('/paso/1', methods=['GET', 'POST'])
def paso1():
    if _onboarding_done():
        return redirect(url_for('auth.login'))

    if request.method == 'POST':
        nombre = sanitizar_texto(request.form.get('nombre_negocio', ''), 100)
        if not nombre:
            flash('Ingresa el nombre de tu negocio.', 'danger')
            return redirect(url_for('setup.paso1'))

        # Create or update the first sucursal
        sucursal = Sucursal.query.first()
        if sucursal:
            sucursal.nombre = nombre
        else:
            sucursal = Sucursal(nombre=nombre, activa=True)
            db.session.add(sucursal)

        ConfiguracionSistema.set('nombre_negocio', nombre)
        db.session.commit()

        # Store in wizard session
        session['setup_sucursal_id'] = sucursal.id
        return redirect(url_for('setup.paso2'))

    nombre_actual = ConfiguracionSistema.get('nombre_negocio', '')
    return render_template('setup/paso1.html', nombre_actual=nombre_actual, paso=1)


# ── Paso 2: Administrador ──

@setup_bp.route('/paso/2', methods=['GET', 'POST'])
def paso2():
    if _onboarding_done():
        return redirect(url_for('auth.login'))
    # Guard: must complete step 1 first
    if not ConfiguracionSistema.get('nombre_negocio'):
        flash('Primero completa el paso 1.', 'warning')
        return redirect(url_for('setup.paso1'))

    if request.method == 'POST':
        nombre = sanitizar_texto(request.form.get('nombre', ''), 100)
        email = sanitizar_email(request.form.get('email', '')) or request.form.get('email', '').strip()
        password = request.form.get('password', '')
        password2 = request.form.get('password2', '')

        errors = []
        if not nombre:
            errors.append('Ingresa tu nombre.')
        if not email:
            errors.append('Ingresa tu email.')
        if not password:
            errors.append('Ingresa una contraseña.')
        if password != password2:
            errors.append('Las contraseñas no coinciden.')

        if not errors:
            pw_valida, pw_errores = validar_password(password, nombre=nombre, email=email)
            if not pw_valida:
                errors.extend(pw_errores)

        if errors:
            for err in errors:
                flash(err, 'danger')
            return render_template('setup/paso2.html', paso=2, nombre=nombre, email=email)

        # Check if a superadmin already exists (re-running wizard)
        admin = Usuario.query.filter_by(rol='superadmin').first()
        if admin:
            admin.nombre = nombre
            admin.email = email
            admin.set_password(password)
        else:
            admin = Usuario(nombre=nombre, email=email, rol='superadmin')
            admin.set_password(password)
            sucursal_id = session.get('setup_sucursal_id')
            if sucursal_id:
                admin.sucursal_id = sucursal_id
            db.session.add(admin)

        db.session.commit()
        session['setup_admin_id'] = admin.id
        return redirect(url_for('setup.paso3'))

    return render_template('setup/paso2.html', paso=2, nombre='', email='')


# ── Paso 3: Tu Menú ──

@setup_bp.route('/paso/3', methods=['GET', 'POST'])
def paso3():
    if _onboarding_done():
        return redirect(url_for('auth.login'))
    # Guard: must have admin user from step 2
    if not Usuario.query.filter_by(rol='superadmin').first():
        flash('Primero crea tu cuenta de administrador.', 'warning')
        return redirect(url_for('setup.paso2'))

    if request.method == 'POST':
        opcion = request.form.get('opcion_menu', 'taqueria')

        if opcion == 'manual':
            # Process manually-added products
            nombres = request.form.getlist('prod_nombre[]')
            precios = request.form.getlist('prod_precio[]')
            categorias_form = request.form.getlist('prod_categoria[]')
            # Ensure stations exist
            estaciones_form = request.form.getlist('prod_estacion[]')

            # Build station map — create new stations on-the-fly
            estaciones_map = {e.nombre.lower(): e for e in Estacion.query.all()}
            for est_raw in estaciones_form:
                est_name = sanitizar_texto(est_raw, 50)
                if est_name and est_name.lower() not in estaciones_map:
                    new_est = Estacion(nombre=est_name)
                    db.session.add(new_est)
                    db.session.flush()
                    estaciones_map[est_name.lower()] = new_est

            created = 0
            for i, nombre in enumerate(nombres):
                nombre = sanitizar_texto(nombre, 150)
                if not nombre:
                    continue
                try:
                    precio = float(precios[i]) if i < len(precios) else 0
                except (ValueError, IndexError):
                    precio = 0

                cat_nombre = categorias_form[i] if i < len(categorias_form) else 'General'
                est_nombre = estaciones_form[i] if i < len(estaciones_form) else ''

                # Get or create category
                cat = Categoria.query.filter_by(nombre=cat_nombre).first()
                if not cat:
                    cat = Categoria(nombre=cat_nombre)
                    db.session.add(cat)
                    db.session.flush()

                estacion = estaciones_map.get(est_nombre.lower().strip()) if est_nombre else None

                if not Producto.query.filter_by(nombre=nombre).first():
                    prod = Producto(
                        nombre=nombre,
                        precio=precio,
                        categoria_id=cat.id,
                        estacion_id=estacion.id if estacion else None,
                        unidad='pieza',
                        descripcion='',
                    )
                    db.session.add(prod)
                    created += 1

            db.session.commit()
            flash(f'{created} productos agregados.', 'success')
        else:
            # Template-based seeding (taqueria, restaurante, cafeteria)
            created = seed_from_template(opcion)
            flash(f'Menu cargado: {created} productos agregados.', 'success')

        return redirect(url_for('setup.paso4'))

    # Get existing categories, stations, and available templates
    categorias = [c.nombre for c in Categoria.query.order_by(Categoria.nombre).all()]
    estaciones = [e.nombre for e in Estacion.query.order_by(Estacion.nombre).all()]
    templates = get_template_list()
    return render_template('setup/paso3.html', paso=3, categorias=categorias, estaciones=estaciones, templates=templates)


# ── Paso 4: Mesas ──

@setup_bp.route('/paso/4', methods=['GET', 'POST'])
def paso4():
    if _onboarding_done():
        return redirect(url_for('auth.login'))
    # Guard: must have completed previous steps (superadmin + products)
    if not Usuario.query.filter_by(rol='superadmin').first():
        flash('Primero completa los pasos anteriores.', 'warning')
        return redirect(url_for('setup.paso2'))
    if Producto.query.count() == 0:
        flash('Primero agrega productos en el paso 3.', 'warning')
        return redirect(url_for('setup.paso3'))

    if request.method == 'POST':
        try:
            cantidad = int(request.form.get('cantidad_mesas', '8'))
            cantidad = max(1, min(30, cantidad))  # clamp 1-30
        except (ValueError, TypeError):
            cantidad = 8

        created = seed_mesas(cantidad)
        flash(f'{created} mesas creadas.', 'success')
        return redirect(url_for('setup.paso5'))

    mesas_existentes = Mesa.query.count()
    return render_template('setup/paso4.html', paso=4, mesas_existentes=mesas_existentes)


# ── Paso 5: Tu Equipo ──

@setup_bp.route('/paso/5', methods=['GET', 'POST'])
def paso5():
    if _onboarding_done():
        return redirect(url_for('auth.login'))
    # Guard: must have completed step 4 (mesas)
    if Mesa.query.count() == 0 and not Usuario.query.filter_by(rol='superadmin').first():
        flash('Primero completa los pasos anteriores.', 'warning')
        return redirect(url_for('setup.paso1'))

    if request.method == 'POST':
        nombres = request.form.getlist('user_nombre[]')
        emails = request.form.getlist('user_email[]')
        passwords = request.form.getlist('user_password[]')
        roles = request.form.getlist('user_rol[]')

        created = 0
        sucursal_id = session.get('setup_sucursal_id')

        # Build station lookup for cocina roles
        estaciones_map = {e.nombre.lower(): e for e in Estacion.query.all()}

        for i, nombre in enumerate(nombres):
            nombre = sanitizar_texto(nombre, 100)
            if not nombre:
                continue
            email = sanitizar_email(emails[i]) if i < len(emails) else ''
            if not email:
                continue
            password = passwords[i] if i < len(passwords) else ''
            if not password:
                continue

            # Validate password strength (same policy as superadmin)
            pw_valida, pw_errores = validar_password(password, nombre=nombre, email=email)
            if not pw_valida:
                flash(f'Contraseña de {nombre} no cumple política: {"; ".join(pw_errores)}', 'danger')
                continue

            rol_raw = roles[i] if i < len(roles) else 'mesero'

            # Parse "cocina:station_name" format → rol='cocina' + estacion_id FK
            estacion_id = None
            if rol_raw.startswith('cocina:'):
                station_name = rol_raw.split(':', 1)[1].strip()
                estacion = estaciones_map.get(station_name.lower())
                if estacion:
                    estacion_id = estacion.id
                rol = 'cocina'
            else:
                rol = rol_raw

            if Usuario.query.filter_by(email=email).first():
                flash(f'El email {email} ya existe, se omitió.', 'warning')
                continue

            user = Usuario(nombre=nombre, email=email, rol=rol, estacion_id=estacion_id)
            user.set_password(password)
            if sucursal_id:
                user.sucursal_id = sucursal_id
            db.session.add(user)
            created += 1

        db.session.commit()
        if created:
            flash(f'{created} usuarios creados.', 'success')

        # Complete onboarding
        ConfiguracionSistema.set('onboarding_completado', 'true')
        ConfiguracionSistema.set('modo_sistema', 'basico')
        db.session.commit()
        logger.info('Onboarding completado desde paso 5.')
        flash('¡Configuración completada! Inicia sesión para comenzar.', 'success')
        return redirect(url_for('auth.login'))

    estaciones = Estacion.query.order_by(Estacion.nombre).all()
    return render_template('setup/paso5.html', paso=5, estaciones=estaciones)


# ── Completar ──

@setup_bp.route('/completar', methods=['POST'])
def completar():
    if _onboarding_done():
        return redirect(url_for('auth.login'))
    # Guard: must have a superadmin to complete
    if not Usuario.query.filter_by(rol='superadmin').first():
        flash('Primero completa el setup.', 'warning')
        return redirect(url_for('setup.paso1'))

    ConfiguracionSistema.set('onboarding_completado', 'true')
    ConfiguracionSistema.set('modo_sistema', 'basico')
    db.session.commit()
    logger.info('Onboarding completado.')
    flash('¡Configuración completada! Inicia sesión para comenzar.', 'success')
    return redirect(url_for('auth.login'))
