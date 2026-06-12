"""m027 constraint hardening

Revision ID: 586bc2d1d79d
Revises: 5c22a636e00e
Create Date: 2026-06-12 05:10:00.000000

Defense-in-depth DB constraints (CodeRabbit remediation #5/#6/#7):
- saleline.quantity > 0
- product retail/repair price >= 0
- systemsetting.updated_by_user_id FK -> ON DELETE SET NULL
"""
from alembic import op

revision = "586bc2d1d79d"
down_revision = "5c22a636e00e"
branch_labels = None
depends_on = None

_SS_FK = "systemsetting_updated_by_user_id_fkey"


def upgrade() -> None:
    op.create_check_constraint(
        "ck_saleline_quantity_positive", "saleline", "quantity > 0",
        postgresql_not_valid=True,
    )
    op.create_check_constraint(
        "ck_product_retail_price_nonneg", "product", "retail_price_thb >= 0",
        postgresql_not_valid=True,
    )
    op.create_check_constraint(
        "ck_product_repair_price_nonneg", "product", "repair_price_thb >= 0",
        postgresql_not_valid=True,
    )
    op.execute("ALTER TABLE saleline VALIDATE CONSTRAINT ck_saleline_quantity_positive")
    op.execute("ALTER TABLE product VALIDATE CONSTRAINT ck_product_retail_price_nonneg")
    op.execute("ALTER TABLE product VALIDATE CONSTRAINT ck_product_repair_price_nonneg")
    op.drop_constraint(_SS_FK, "systemsetting", type_="foreignkey")
    op.create_foreign_key(_SS_FK, "systemsetting", "user", ["updated_by_user_id"], ["id"], ondelete="SET NULL")


def downgrade() -> None:
    op.drop_constraint(_SS_FK, "systemsetting", type_="foreignkey")
    op.create_foreign_key(_SS_FK, "systemsetting", "user", ["updated_by_user_id"], ["id"])
    op.drop_constraint("ck_product_repair_price_nonneg", "product", type_="check")
    op.drop_constraint("ck_product_retail_price_nonneg", "product", type_="check")
    op.drop_constraint("ck_saleline_quantity_positive", "saleline", type_="check")
