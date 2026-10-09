"""очередь ответов оператора для доставки в MAX

Revision ID: 0003
Revises: 0002
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0003"
down_revision: Union[str, Sequence[str], None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TABLE = "ticket_reply_notifications"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if TABLE in inspector.get_table_names():
        return

    op.create_table(
        TABLE,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("ticket_id", sa.Integer(), sa.ForeignKey("tickets.id"), nullable=False),
        sa.Column("signature", sa.String(length=64), nullable=False),
        sa.Column("author", sa.String(length=255), server_default="", nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("entry_created_at", sa.String(length=64), server_default="", nullable=False),
        sa.Column("notified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("ticket_id", "signature", name="uq_ticket_reply_signature"),
    )
    op.create_index("ix_ticket_reply_notifications_ticket_id", TABLE, ["ticket_id"])
    op.create_index("ix_ticket_reply_notifications_signature", TABLE, ["signature"])


def downgrade() -> None:
    op.drop_table(TABLE)
