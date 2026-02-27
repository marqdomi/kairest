"""Add indexes on FK and filter columns for query performance.

Revision ID: c009
Revises: c008
Create Date: 2026-02-26
"""
from alembic import op

revision = 'c009'
down_revision = 'c008'
branch_labels = None
depends_on = None

# (table, column) pairs that received index=True in models.py
_INDEXES = [
    ('configuracion_sistema', 'clave'),
    ('orden', 'mesa_id'),
    ('orden', 'mesero_id'),
    ('orden', 'sucursal_id'),
    ('orden', 'estado'),
    ('orden', 'fecha_pago'),
    ('orden_detalle', 'orden_id'),
    ('orden_detalle', 'producto_id'),
    ('orden_detalle', 'estado'),
    ('pago', 'orden_id'),
    ('pago', 'fecha'),
    ('movimientos_inventario', 'ingrediente_id'),
    ('movimientos_inventario', 'tipo'),
    ('movimientos_inventario', 'fecha'),
    ('reservaciones', 'fecha'),
    ('facturas', 'orden_id'),
    ('facturas', 'cliente_id'),
    ('facturas', 'estado'),
    ('sales', 'fecha_hora'),
    ('sales', 'usuario_id'),
    ('sales', 'sucursal_id'),
    ('sale_items', 'sale_id'),
    ('sale_items', 'producto_id'),
]


def _ix_name(table, column):
    return f'ix_{table}_{column}'


def upgrade():
    for table, column in _INDEXES:
        op.create_index(
            _ix_name(table, column),
            table,
            [column],
            unique=False,
            if_not_exists=True,
        )


def downgrade():
    for table, column in reversed(_INDEXES):
        op.drop_index(_ix_name(table, column), table_name=table)
