# backend/models/database.py

import logging
from sqlalchemy import text
from backend.extensions import db

logger = logging.getLogger(__name__)


def init_db():
    """Create all tables if they don't exist."""
    import backend.models.models  # noqa: F401

    engine = db.engine

    if engine.dialect.name == 'postgresql':
        lock_id = 72410931
        with engine.connect() as conn:
            try:
                conn.execute(text('SELECT pg_advisory_lock(:lock_id)'), {'lock_id': lock_id})
                db.metadata.create_all(bind=conn, checkfirst=True)
                conn.commit()
            finally:
                try:
                    conn.execute(text('SELECT pg_advisory_unlock(:lock_id)'), {'lock_id': lock_id})
                    conn.commit()
                except Exception:
                    logger.exception('No se pudo liberar pg_advisory_unlock durante init_db.')
    else:
        db.create_all()

    logger.info('Base de datos inicializada correctamente.')
