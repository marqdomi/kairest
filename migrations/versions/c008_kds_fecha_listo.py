"""Add fecha_listo to orden_detalle for individual item marking.

Revision ID: c008
Revises: c007
Create Date: 2026-02-24
"""
from alembic import op
import sqlalchemy as sa

revision = 'c008'
down_revision = 'c007'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('orden_detalle',
                  sa.Column('fecha_listo', sa.DateTime(), nullable=True))


def downgrade():
    op.drop_column('orden_detalle', 'fecha_listo')
