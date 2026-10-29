"""Estaciones que despacha el mesero (sin pantalla de cocina).

- estacion.la_sirve_mesero (bool, default false)

En Casa Leones no hay quien atienda una estación de Bebidas: los meseros las sirven
porque las tienen a la mano. Con la estación marcada, lo que pertenece a ella queda
listo en cuanto se envía la orden y el mesero sólo lo marca entregado; no va a ningún
KDS ni detiene la orden.

Idempotente: verifica con inspector antes de crear, para tolerar bases creadas por
create_all() con el modelo ya actualizado.

Revision ID: c015
Revises: c014
Create Date: 2026-10-29
"""
import sqlalchemy as sa
from alembic import op

revision = 'c015'
down_revision = 'c014'
branch_labels = None
depends_on = None


def upgrade():
    insp = sa.inspect(op.get_bind())
    cols = {c['name'] for c in insp.get_columns('estacion')}
    if 'la_sirve_mesero' not in cols:
        with op.batch_alter_table('estacion') as batch:
            batch.add_column(sa.Column('la_sirve_mesero', sa.Boolean(), nullable=False,
                                       server_default=sa.false()))


def downgrade():
    insp = sa.inspect(op.get_bind())
    cols = {c['name'] for c in insp.get_columns('estacion')}
    if 'la_sirve_mesero' in cols:
        with op.batch_alter_table('estacion') as batch:
            batch.drop_column('la_sirve_mesero')
