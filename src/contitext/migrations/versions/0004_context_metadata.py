"""Add explicit task and lifecycle metadata without reinterpreting old payloads."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0004_context_metadata'
down_revision = '0003_workspaces'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('context_events', sa.Column('event_metadata', postgresql.JSONB(none_as_null=True), nullable=True))
    for key in ('task_id', 'supersedes', 'resolves'):
        op.create_index('ix_context_events_meta_' + key, 'context_events', ['project_id', sa.text("(event_metadata->>'" + key + "')")])


def downgrade():
    if op.get_bind().execute(sa.text('SELECT EXISTS (SELECT 1 FROM context_events WHERE event_metadata IS NOT NULL)')).scalar_one():
        raise RuntimeError('context metadata exists; restore a verified pre-upgrade backup instead of discarding lifecycle history')
    for key in ('task_id', 'supersedes', 'resolves'):
        op.drop_index('ix_context_events_meta_' + key, table_name='context_events')
    op.drop_column('context_events', 'event_metadata')
