"""Add estacion_id FK to usuario + migrate legacy station roles to cocina+FK.

Revision ID: c007
Revises: c006
Create Date: 2026-02-23
"""
from alembic import op
import sqlalchemy as sa

revision = 'c007'
down_revision = 'c006'
branch_labels = None
depends_on = None


def upgrade():
    # 1. Add estacion_id column to usuario
    op.add_column('usuario', sa.Column('estacion_id', sa.Integer(), nullable=True))
    op.create_foreign_key(
        'fk_usuario_estacion_id', 'usuario', 'estacion',
        ['estacion_id'], ['id']
    )

    # 2. Migrate legacy roles: match usuario.rol to estacion.nombre,
    #    set estacion_id and change rol to 'cocina'
    conn = op.get_bind()
    estaciones = conn.execute(sa.text('SELECT id, nombre FROM estacion')).fetchall()
    for est_id, est_nombre in estaciones:
        # Match users whose rol equals the station name (case-insensitive)
        conn.execute(
            sa.text(
                "UPDATE usuario SET estacion_id = :est_id, rol = 'cocina' "
                "WHERE LOWER(rol) = LOWER(:est_nombre)"
            ),
            {'est_id': est_id, 'est_nombre': est_nombre}
        )


def downgrade():
    # Revert: set rol back to estacion.nombre for users with rol='cocina'
    conn = op.get_bind()
    conn.execute(
        sa.text(
            "UPDATE usuario SET rol = ("
            "  SELECT LOWER(e.nombre) FROM estacion e WHERE e.id = usuario.estacion_id"
            ") WHERE rol = 'cocina' AND estacion_id IS NOT NULL"
        )
    )
    op.drop_constraint('fk_usuario_estacion_id', 'usuario', type_='foreignkey')
    op.drop_column('usuario', 'estacion_id')
