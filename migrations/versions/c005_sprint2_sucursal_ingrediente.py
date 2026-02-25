"""Sprint 2: add sucursal_id FK to ingredientes, sales, corte_caja.

Revision ID: c005
Revises: c004_fase4_multisucursal_delivery
Create Date: 2026-02-15
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = 'c005'
down_revision = 'c004_fase4'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('ingredientes',
                  sa.Column('sucursal_id', sa.Integer(),
                            sa.ForeignKey('sucursales.id'), nullable=True))
    op.add_column('sales',
                  sa.Column('sucursal_id', sa.Integer(),
                            sa.ForeignKey('sucursales.id'), nullable=True))
    op.add_column('corte_caja',
                  sa.Column('sucursal_id', sa.Integer(),
                            sa.ForeignKey('sucursales.id'), nullable=True))
    # CorteCaja: drop unique on fecha (now unique per sucursal+fecha)
    op.drop_constraint('corte_caja_fecha_key', 'corte_caja', type_='unique')
    op.create_unique_constraint('uq_corte_sucursal_fecha', 'corte_caja',
                                ['sucursal_id', 'fecha'])


def downgrade():
    op.drop_constraint('uq_corte_sucursal_fecha', 'corte_caja', type_='unique')
    op.create_unique_constraint('corte_caja_fecha_key', 'corte_caja', ['fecha'])
    op.drop_column('corte_caja', 'sucursal_id')
    op.drop_column('sales', 'sucursal_id')
    op.drop_column('ingredientes', 'sucursal_id')
