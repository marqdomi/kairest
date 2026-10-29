"""Comandos de consola para operación del sistema.

Sirven para lo que no se puede hacer desde la interfaz porque justamente no se
puede entrar: recuperar el acceso cuando se olvidó la contraseña del admin.

Uso en la instalación con Docker:

    docker compose exec web flask usuarios
    docker compose exec web flask reset-password maria            (o el correo)
    docker compose exec web flask reset-pin pepe
"""
import logging

import click
from flask.cli import with_appcontext

from backend.extensions import db
from backend.models.models import Usuario
from backend.services.audit import registrar_auditoria
from backend.services.password_policy import validar_password

logger = logging.getLogger(__name__)


@click.command('usuarios')
@with_appcontext
def listar_usuarios():
    """Lista los usuarios registrados (para saber con qué correo entrar)."""
    usuarios = Usuario.query.order_by(Usuario.rol, Usuario.nombre).all()
    if not usuarios:
        click.echo('No hay usuarios registrados. ¿Falta completar el asistente inicial?')
        return

    click.echo('')
    click.echo(f"{'USUARIO':<16} {'CORREO':<30} {'NOMBRE':<22} {'ROL':<10} {'ENTRA CON':<11} SUCURSAL")
    click.echo('-' * 105)
    for u in usuarios:
        sucursal = u.sucursal.nombre if u.sucursal_id and u.sucursal else '—'
        entra = ('PIN' if u.pin_hash else 'sin PIN') if u.usa_pin else 'contraseña'
        if u.pin_bloqueado:
            entra += ' 🔒'
        click.echo(f'{u.username or "—":<16} {u.email or "—":<30} {u.nombre:<22} {u.rol:<10} {entra:<11} {sucursal}')
    click.echo('')


def _buscar(identificador):
    from backend.services.acceso import buscar_para_login
    usuario = buscar_para_login(identificador)
    if not usuario:
        raise click.ClickException(
            f'No existe ningún usuario "{identificador}". '
            'Usa "flask usuarios" para ver los registrados.'
        )
    return usuario


@click.command('reset-password')
@click.argument('email')
@click.option('--password', help='Contraseña nueva. Si se omite, se pide sin mostrarla en pantalla.')
@with_appcontext
def reset_password(email, password):
    """Cambia la contraseña del usuario (por usuario o por correo)."""
    usuario = _buscar(email)

    if not password:
        password = click.prompt('Contraseña nueva', hide_input=True, confirmation_prompt=True)

    valida, errores = validar_password(password, nombre=usuario.nombre, email=usuario.email or '')
    if not valida:
        for error in errores:
            click.echo(f'  • {error}', err=True)
        raise click.ClickException('La contraseña no cumple los requisitos.')

    usuario.set_password(password)
    registrar_auditoria(
        'editar', 'Usuario', usuario.id,
        f'Contraseña restablecida por consola: {usuario.identificador}',
        usuario_id=usuario.id,
    )
    db.session.commit()

    click.echo(f'✅ Contraseña actualizada para {usuario.nombre} ({usuario.identificador}).')


@click.command('reset-pin')
@click.argument('usuario')
@click.option('--pin', help='PIN nuevo de 4 números. Si se omite, se genera uno.')
@with_appcontext
def reset_pin(usuario, pin):
    """Pone un PIN nuevo a un mesero o cocinero y lo desbloquea."""
    from backend.services.acceso import generar_pin, validar_pin
    u = _buscar(usuario)
    if not u.usa_pin:
        raise click.ClickException(f'{u.nombre} es {u.rol}: entra con contraseña (usa reset-password).')
    pin = pin or generar_pin()
    ok, msg = validar_pin(pin)
    if not ok:
        raise click.ClickException(msg)
    u.set_pin(pin)
    registrar_auditoria('editar', 'Usuario', u.id, f'PIN restablecido por consola: {u.identificador}',
                        usuario_id=u.id)
    db.session.commit()
    click.echo(f'✅ PIN de {u.nombre} ({u.username}): {pin}')


def registrar_comandos(app):
    """Engancha los comandos al `flask` de esta app."""
    app.cli.add_command(listar_usuarios)
    app.cli.add_command(reset_password)
    app.cli.add_command(reset_pin)
