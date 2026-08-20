"""счётчик попыток кода и повторные уведомления о статусе

Revision ID: 0002
Revises: 0001
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0002"
down_revision: Union[str, Sequence[str], None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


CONSTRAINT_NAME = "uq_ticket_status_notification"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # Счётчик неудачных попыток ввода кода: без него шестизначный код перебирается.
    existing_columns = {column["name"] for column in inspector.get_columns("email_verifications")}
    if "attempts" not in existing_columns:
        with op.batch_alter_table("email_verifications", schema=None) as batch_op:
            batch_op.add_column(
                sa.Column("attempts", sa.Integer(), server_default="0", nullable=False)
            )

    # Уникальность (ticket_id, new_status) запрещала повторное уведомление, когда
    # заявку переоткрыли и снова закрыли. В SQLite ограничение могло быть создано
    # без имени, поэтому удаляем только то, что действительно существует.
    existing_constraints = {
        constraint["name"]
        for constraint in inspector.get_unique_constraints("ticket_status_notifications")
    }
    if CONSTRAINT_NAME in existing_constraints:
        with op.batch_alter_table("ticket_status_notifications", schema=None) as batch_op:
            batch_op.drop_constraint(CONSTRAINT_NAME, type_="unique")


def downgrade() -> None:
    with op.batch_alter_table("ticket_status_notifications", schema=None) as batch_op:
        batch_op.create_unique_constraint(
            "uq_ticket_status_notification", ["ticket_id", "new_status"]
        )

    with op.batch_alter_table("email_verifications", schema=None) as batch_op:
        batch_op.drop_column("attempts")
