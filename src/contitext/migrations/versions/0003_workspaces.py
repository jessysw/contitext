"""Workspace membership and UUID project identities.

Revision ID: 0003_workspaces
Revises: 0002_credentials
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0003_workspaces"
down_revision = "0002_credentials"
branch_labels = None
depends_on = None

LEGACY_WORKSPACE_ID = "00000000-0000-4000-8000-000000000001"
REFERENCES = ("project_acl", "scope_bindings", "context_events", "projection_offsets")


def upgrade() -> None:
    # PostgreSQL transactional DDL keeps the mapping and every FK atomic. Writers
    # must be fenced before an operational upgrade; no old binary may run after it.
    op.create_table(
        "workspaces",
        sa.Column("id", postgresql.UUID(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("slug", sa.Text(), nullable=False, unique=True),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("slug ~ '^[A-Za-z0-9][A-Za-z0-9._-]*$' AND length(slug) <= 128", name="ck_workspaces_slug"),
    )
    op.create_table(
        "workspace_members",
        sa.Column("workspace_id", postgresql.UUID(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("principal_id", postgresql.UUID(), sa.ForeignKey("principals.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("role", sa.Text(), nullable=False),
        sa.CheckConstraint("role IN ('member', 'owner')", name="ck_workspace_members_role"),
    )
    op.execute(sa.text("INSERT INTO workspaces (id, slug, display_name) VALUES "
                       "('00000000-0000-4000-8000-000000000001', 'legacy', 'Legacy workspace')"))
    op.execute(sa.text("INSERT INTO workspace_members (workspace_id, principal_id, role) "
                       "SELECT '00000000-0000-4000-8000-000000000001', principal_id, 'member' "
                       "FROM project_acl GROUP BY principal_id"))
    op.add_column("projects", sa.Column("slug", sa.Text()))
    op.add_column("projects", sa.Column("workspace_id", postgresql.UUID()))
    op.add_column("projects", sa.Column("project_uuid", postgresql.UUID(), nullable=False, server_default=sa.text("gen_random_uuid()")))
    op.execute("UPDATE projects SET slug = id, workspace_id = '00000000-0000-4000-8000-000000000001'")
    for table in REFERENCES:
        op.drop_constraint(f"{table}_project_id_fkey", table, type_="foreignkey")
        op.execute(f"UPDATE {table} r SET project_id = p.project_uuid::text FROM projects p WHERE r.project_id = p.id")
        op.alter_column(table, "project_id", type_=postgresql.UUID(), postgresql_using="project_id::uuid")
    op.alter_column("projects", "id", type_=postgresql.UUID(), postgresql_using="project_uuid")
    op.alter_column("projects", "id", server_default=sa.text("gen_random_uuid()"))
    op.drop_column("projects", "project_uuid")
    op.alter_column("projects", "slug", nullable=False)
    op.alter_column("projects", "workspace_id", nullable=False)
    op.create_foreign_key("projects_workspace_id_fkey", "projects", "workspaces", ["workspace_id"], ["id"], ondelete="RESTRICT")
    op.create_unique_constraint("uq_projects_workspace_slug", "projects", ["workspace_id", "slug"])
    op.create_check_constraint("ck_projects_slug", "projects", "slug ~ '^[A-Za-z0-9][A-Za-z0-9._-]*$' AND length(slug) <= 128")
    for table in REFERENCES:
        op.create_foreign_key(f"{table}_project_id_fkey", table, "projects", ["project_id"], ["id"], ondelete="CASCADE")


def downgrade() -> None:
    connection = op.get_bind()
    populated = connection.execute(sa.text(
        "SELECT EXISTS(SELECT 1 FROM projects) OR EXISTS(SELECT 1 FROM workspace_members) "
        "OR EXISTS(SELECT 1 FROM workspaces WHERE id <> '00000000-0000-4000-8000-000000000001')"
    )).scalar_one()
    if populated:
        raise RuntimeError("workspace data exists; restore a verified pre-upgrade backup instead of flattening namespaces")
    for table in REFERENCES:
        op.drop_constraint(f"{table}_project_id_fkey", table, type_="foreignkey")
        op.alter_column(table, "project_id", type_=sa.Text(), postgresql_using="project_id::text")
    op.drop_constraint("uq_projects_workspace_slug", "projects", type_="unique")
    op.drop_constraint("ck_projects_slug", "projects", type_="check")
    op.drop_constraint("projects_workspace_id_fkey", "projects", type_="foreignkey")
    op.alter_column("projects", "id", server_default=None)
    op.alter_column("projects", "id", type_=sa.Text(), postgresql_using="id::text")
    op.drop_column("projects", "slug")
    op.drop_column("projects", "workspace_id")
    for table in REFERENCES:
        op.create_foreign_key(f"{table}_project_id_fkey", table, "projects", ["project_id"], ["id"], ondelete="CASCADE")
    op.drop_table("workspace_members")
    op.drop_table("workspaces")
