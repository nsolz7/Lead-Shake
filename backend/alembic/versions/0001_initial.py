"""Initial evidence model.

Revision ID: 0001_initial
Revises:
"""
from alembic import op
from sqlalchemy import text

from app.database import Base
from app import models  # noqa: F401

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        bind.execute(text("CREATE EXTENSION IF NOT EXISTS postgis"))
        bind.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
    Base.metadata.create_all(bind=bind)
    if bind.dialect.name == "postgresql":
        bind.execute(text("CREATE INDEX IF NOT EXISTS ix_account_name_trgm ON account_groups USING gin (normalized_name gin_trgm_ops)"))
        bind.execute(text("CREATE INDEX IF NOT EXISTS ix_location_address_trgm ON locations USING gin (normalized_address gin_trgm_ops)"))
        bind.execute(text("""
            ALTER TABLE locations
            ADD COLUMN IF NOT EXISTS geom geometry(Point, 4326)
            GENERATED ALWAYS AS (
                CASE WHEN latitude IS NOT NULL AND longitude IS NOT NULL
                THEN ST_SetSRID(ST_MakePoint(longitude, latitude), 4326)
                ELSE NULL END
            ) STORED
        """))
        bind.execute(text("CREATE INDEX IF NOT EXISTS ix_location_geom ON locations USING gist (geom)"))


def downgrade() -> None:
    Base.metadata.drop_all(bind=op.get_bind())
