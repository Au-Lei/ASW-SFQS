"""Durable queue attempts, checkpoints and worker fencing. Additive upgrade."""
from alembic import op
import sqlalchemy as sa

revision = "0003_jobs"
down_revision = "0002_history_guards"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("job", sa.Column("progress_done", sa.Integer(), nullable=False, server_default=sa.text("0"),
        *[sa.CheckConstraint("progress_done >= 0", name=op.f("ck_job_progress_nonnegative"))]))
    op.add_column("job", sa.Column("progress_total", sa.Integer(),
        sa.CheckConstraint("progress_total IS NULL OR progress_total >= progress_done", name=op.f("ck_job_progress_order"))))
    op.add_column("job", sa.Column("available_at", sa.DateTime()))
    op.add_column("job", sa.Column("dedup_key", sa.String(64)))
    op.add_column("job", sa.Column("request_hash", sa.String(64)))
    # SQLite supports a nullable REFERENCES column with its default NULL.
    op.execute("ALTER TABLE job ADD COLUMN retry_parent_id VARCHAR(36) REFERENCES job(id)")
    op.execute("ALTER TABLE job ADD COLUMN execution_id VARCHAR(36) REFERENCES job(id)")
    op.execute("UPDATE job SET execution_id = id")
    op.create_index("uq_job_dedup_key", "job", ["dedup_key"], unique=True)
    op.create_index("uq_job_retry_parent_id", "job", ["retry_parent_id"], unique=True)
    op.create_index("ix_job_due", "job", ["state", "available_at", "created_at"])
    op.create_table("job_attempt",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("job_id", sa.String(36), sa.ForeignKey("job.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("attempt_no", sa.Integer(), nullable=False),
        sa.Column("worker_id", sa.String(36), nullable=False),
        sa.Column("state", sa.String(40), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime()), sa.Column("error", sa.JSON(none_as_null=True)),
        sa.CheckConstraint("state IN ('RUNNING','SUCCEEDED','PARTIAL_FAILED','FAILED','CANCELLED','INTERRUPTED')", name=op.f("ck_job_attempt_state_values")),
        sa.UniqueConstraint("job_id", "attempt_no", name="uq_attempt_number"))
    op.create_index("ix_job_attempt_job_id", "job_attempt", ["job_id"])
    op.create_table("job_checkpoint",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("execution_id", sa.String(36), sa.ForeignKey("job.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("attempt_id", sa.String(36), sa.ForeignKey("job_attempt.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("item_key", sa.String(100), nullable=False),
        sa.Column("result_ref", sa.JSON(none_as_null=True), nullable=False),
        sa.Column("payload_sha256", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("execution_id", "item_key", name="uq_checkpoint_item"))
    op.create_index("ix_job_checkpoint_execution_id", "job_checkpoint", ["execution_id"])
    op.create_table("worker_runtime",
        sa.Column("name", sa.String(50), primary_key=True),
        sa.Column("owner", sa.String(36), nullable=False),
        sa.Column("lease_expires_at", sa.DateTime(), nullable=False),
        sa.Column("heartbeat_at", sa.DateTime(), nullable=False))
    for action in ("UPDATE", "DELETE"):
        op.execute(f"CREATE TRIGGER checkpoint_immutable_{action.lower()} BEFORE {action} ON job_checkpoint BEGIN SELECT RAISE(ABORT, 'immutable checkpoint'); END")
    op.execute("CREATE TRIGGER attempt_terminal_immutable BEFORE UPDATE ON job_attempt WHEN OLD.state != 'RUNNING' BEGIN SELECT RAISE(ABORT, 'immutable attempt'); END")
    op.execute("CREATE TRIGGER attempt_delete_forbidden BEFORE DELETE ON job_attempt BEGIN SELECT RAISE(ABORT, 'immutable attempt'); END")
    op.execute("""CREATE TRIGGER checkpoint_execution_scope BEFORE INSERT ON job_checkpoint
        WHEN NEW.execution_id IS NOT (SELECT coalesce(j.execution_id,j.id) FROM job_attempt a JOIN job j ON j.id=a.job_id WHERE a.id=NEW.attempt_id)
        BEGIN SELECT RAISE(ABORT, 'cross-execution checkpoint'); END""")


def downgrade():
    raise RuntimeError("Use a verified backup to recover; destructive downgrade is disabled")
