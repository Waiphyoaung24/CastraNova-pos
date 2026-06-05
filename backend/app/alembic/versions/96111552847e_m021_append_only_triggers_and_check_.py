"""m021 append-only triggers and check constraints

Revision ID: 96111552847e
Revises: 1a8ceda3b098
Create Date: 2026-06-04 20:33:30.434286

"""
from alembic import op
import sqlalchemy as sa
import sqlmodel.sql.sqltypes


# revision identifiers, used by Alembic.
revision = '96111552847e'
down_revision = '1a8ceda3b098'
branch_labels = None
depends_on = None


# The five append-only ledger tables (SQLModel lowercases class names, no
# underscores). The app connects as a superuser/owner, so REVOKE is a no-op —
# a BEFORE UPDATE OR DELETE trigger is the only mechanism that fires for every
# role. TRUNCATE is intentionally NOT covered (the pytest db teardown relies on
# TRUNCATE ... CASCADE).
_LEDGER_TABLES = (
    "unitmovement",
    "partmovement",
    "costline",
    "pricechange",
    "notificationlog",
)


def upgrade():
    op.execute(
        """
CREATE OR REPLACE FUNCTION reject_ledger_mutation() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'append-only: % rows cannot be updated or deleted', TG_TABLE_NAME
        USING ERRCODE = 'restrict_violation';
END;
$$ LANGUAGE plpgsql;
"""
    )
    for table in _LEDGER_TABLES:
        op.execute(
            f"""
DROP TRIGGER IF EXISTS trg_{table}_append_only ON {table};
CREATE TRIGGER trg_{table}_append_only
BEFORE UPDATE OR DELETE ON {table}
FOR EACH ROW EXECUTE FUNCTION reject_ledger_mutation();
"""
        )

    # Scheduled CHECK constraints (deferred security hardening, now M021).
    op.create_check_constraint(
        "ck_unit_purchase_cost_nonneg", "unit", "purchase_cost_thb >= 0"
    )
    op.create_check_constraint(
        "ck_saleline_unit_cost_nonneg", "saleline", "unit_cost_thb >= 0"
    )
    op.create_check_constraint(
        "ck_saleline_unit_requires_unit_id",
        "saleline",
        "line_kind != 'UNIT' OR unit_id IS NOT NULL",
    )


def downgrade():
    op.drop_constraint(
        "ck_saleline_unit_requires_unit_id", "saleline", type_="check"
    )
    op.drop_constraint("ck_saleline_unit_cost_nonneg", "saleline", type_="check")
    op.drop_constraint("ck_unit_purchase_cost_nonneg", "unit", type_="check")

    for table in _LEDGER_TABLES:
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_append_only ON {table};")
    op.execute("DROP FUNCTION IF EXISTS reject_ledger_mutation();")
