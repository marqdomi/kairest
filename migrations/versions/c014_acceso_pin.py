"""Acceso rápido: usuario corto, PIN y dispositivos autorizados.

- usuario.username (único) — se llena para los usuarios existentes a partir del
  nombre ("Pepe Mesero" → "pepe"; si choca, "pepe2")
- usuario.email pasa a opcional (el personal ya no necesita correo)
- usuario.pin_hash / pin_fallidos / pin_bloqueado_hasta
- tabla dispositivos_autorizados

Idempotente: verifica con inspector antes de crear, para tolerar bases creadas por
create_all() con el modelo ya actualizado (flujo stamp head de update.sh).

Revision ID: c014
Revises: c013
Create Date: 2026-10-29
"""
import re
import unicodedata

import sqlalchemy as sa
from alembic import op

revision = 'c014'
down_revision = 'c013'
branch_labels = None
depends_on = None


def _slug(nombre):
    base = unicodedata.normalize('NFKD', nombre or '').encode('ascii', 'ignore').decode()
    base = re.sub(r'[^a-z0-9]', '', (base.split() or [''])[0].lower())
    return base[:30] or 'usuario'


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    cols = {c['name'] for c in insp.get_columns('usuario')}

    with op.batch_alter_table('usuario') as batch:
        if 'username' not in cols:
            batch.add_column(sa.Column('username', sa.String(40), nullable=True))
        if 'pin_hash' not in cols:
            batch.add_column(sa.Column('pin_hash', sa.String(256), nullable=True))
        if 'pin_fallidos' not in cols:
            batch.add_column(sa.Column('pin_fallidos', sa.Integer(), nullable=False, server_default='0'))
        if 'pin_bloqueado_hasta' not in cols:
            batch.add_column(sa.Column('pin_bloqueado_hasta', sa.DateTime(), nullable=True))
        batch.alter_column('email', existing_type=sa.String(120), nullable=True)

    # Llenar username a los usuarios que no lo tienen
    usados = {r[0] for r in bind.execute(sa.text(
        'SELECT username FROM usuario WHERE username IS NOT NULL'))}
    pendientes = bind.execute(sa.text(
        'SELECT id, nombre FROM usuario WHERE username IS NULL ORDER BY id')).fetchall()
    for uid, nombre in pendientes:
        base = _slug(nombre)
        candidato, n = base, 2
        while candidato in usados:
            candidato, n = f'{base}{n}', n + 1
        usados.add(candidato)
        bind.execute(sa.text('UPDATE usuario SET username = :u WHERE id = :i'),
                     {'u': candidato, 'i': uid})

    indices = {i['name'] for i in insp.get_indexes('usuario')}
    if 'ix_usuario_username' not in indices:
        op.create_index('ix_usuario_username', 'usuario', ['username'], unique=True)

    if 'dispositivos_autorizados' not in insp.get_table_names():
        op.create_table(
            'dispositivos_autorizados',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('nombre', sa.String(60), nullable=False),
            sa.Column('token_hash', sa.String(64), nullable=False),
            sa.Column('sucursal_id', sa.Integer(), sa.ForeignKey('sucursales.id'), nullable=True),
            sa.Column('autorizado_por', sa.Integer(), sa.ForeignKey('usuario.id'), nullable=True),
            sa.Column('creado', sa.DateTime(), nullable=True),
            sa.Column('ultimo_uso', sa.DateTime(), nullable=True),
            sa.Column('activo', sa.Boolean(), nullable=False, server_default=sa.true()),
        )
        op.create_index('ix_dispositivos_autorizados_token_hash', 'dispositivos_autorizados',
                        ['token_hash'], unique=True)


def downgrade():
    insp = sa.inspect(op.get_bind())
    if 'dispositivos_autorizados' in insp.get_table_names():
        op.drop_table('dispositivos_autorizados')
    cols = {c['name'] for c in insp.get_columns('usuario')}
    indices = {i['name'] for i in insp.get_indexes('usuario')}
    if 'ix_usuario_username' in indices:
        op.drop_index('ix_usuario_username', table_name='usuario')
    with op.batch_alter_table('usuario') as batch:
        for c in ('pin_bloqueado_hasta', 'pin_fallidos', 'pin_hash', 'username'):
            if c in cols:
                batch.drop_column(c)
