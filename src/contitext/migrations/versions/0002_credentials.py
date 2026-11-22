"""Add hash-only credentials without changing existing project data or config auth."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0002_credentials"
down_revision = "0001_foundation"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "credentials",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("principal_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("principals.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("token_hash", sa.Text(), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("clock_timestamp()"), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("token_hash ~ '^[0-9a-f]{64}$'", name="ck_credentials_hash"),
    )
    op.create_index("ix_credentials_principal_id", "credentials", ["principal_id"])
    op.create_table(
        "credential_audit",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("credential_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("credentials.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("related_credential_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("credentials.id", ondelete="RESTRICT")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("clock_timestamp()"), nullable=False),
        sa.CheckConstraint("action IN ('issued', 'imported', 'rotated', 'revoked')", name="ck_credential_audit_action"),
    )
    op.create_index("ix_credential_audit_credential_id", "credential_audit", ["credential_id"])


def downgrade():
    # An empty migration rehearsal can roll back. Real credential history must
    # never disappear silently or restore access via an old configuration mode.
    if op.get_bind().execute(sa.text("SELECT EXISTS (SELECT 1 FROM credentials)")).scalar_one():
        raise RuntimeError("credential history exists; restore a verified pre-upgrade backup instead of downgrading")
    op.drop_table("credential_audit")
    op.drop_table("credentials")
