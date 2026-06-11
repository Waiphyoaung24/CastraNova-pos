"""m025 movement service_ticket fks

Revision ID: 311a921ce5e2
Revises: 0d75e85a30ef
Create Date: 2026-06-11 15:36:01.744667

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '311a921ce5e2'
down_revision = '0d75e85a30ef'
branch_labels = None
depends_on = None


# No ondelete on either FK: serviceticket rows are never deleted (no delete
# endpoint; append-only domain).
def upgrade():
    # Orphan pre-check: the FK must not be created over dangling references.
    conn = op.get_bind()
    for table in ("partmovement", "unitmovement"):
        orphans = conn.execute(
            sa.text(
                f"SELECT COUNT(*) FROM {table} m WHERE m.service_ticket_id IS NOT NULL "
                "AND NOT EXISTS (SELECT 1 FROM serviceticket t WHERE t.id = m.service_ticket_id)"
            )
        ).scalar()
        if orphans:
            raise RuntimeError(
                f"{table} has {orphans} orphaned service_ticket_id rows; resolve before migrating"
            )
    op.create_foreign_key(
        "fk_partmovement_service_ticket_id",
        "partmovement", "serviceticket", ["service_ticket_id"], ["id"],
    )
    op.create_foreign_key(
        "fk_unitmovement_service_ticket_id",
        "unitmovement", "serviceticket", ["service_ticket_id"], ["id"],
    )
    op.create_index(
        "ix_unitmovement_service_ticket_id",
        "unitmovement", ["service_ticket_id"],
        postgresql_where=sa.text("service_ticket_id IS NOT NULL"),
    )


def downgrade():
    op.drop_index(
        "ix_unitmovement_service_ticket_id",
        table_name="unitmovement",
        postgresql_where=sa.text("service_ticket_id IS NOT NULL"),
    )
    op.drop_constraint(
        "fk_unitmovement_service_ticket_id", "unitmovement", type_="foreignkey"
    )
    op.drop_constraint(
        "fk_partmovement_service_ticket_id", "partmovement", type_="foreignkey"
    )
