"""Protect immutable history and scoped, approved code mappings."""
from alembic import op

revision = "0002_history_guards"
down_revision = "0001_core"
branch_labels = None
depends_on = None


def upgrade():
    for table in ("quotation_revision", "dataset_snapshot", "audit_event", "template_config", "application", "application_item"):
        for action in ("UPDATE", "DELETE"):
            op.execute(f"""CREATE TRIGGER {table}_immutable_{action.lower()}
                BEFORE {action} ON {table} BEGIN
                SELECT RAISE(ABORT, 'immutable history'); END""")

    for action in ("INSERT", "UPDATE"):
        # NULL issuer means the standard namespace, not an SQL uniqueness loophole.
        # Approved mappings may have separate, non-overlapping date intervals.
        op.execute(f"""CREATE TRIGGER mapping_no_overlap_{action.lower()}
            BEFORE {action} ON location_code_mapping
            WHEN NEW.review_state = 'APPROVED' AND EXISTS (
                SELECT 1 FROM location_code_mapping old
                WHERE old.id != NEW.id AND old.review_state = 'APPROVED'
                AND old.namespace = NEW.namespace
                AND old.issuer_id IS NEW.issuer_id
                AND old.code_normalized = NEW.code_normalized
                AND coalesce(old.valid_from, '0001-01-01') <= coalesce(NEW.valid_to, '9999-12-31')
                AND coalesce(NEW.valid_from, '0001-01-01') <= coalesce(old.valid_to, '9999-12-31')
            ) BEGIN SELECT RAISE(ABORT, 'overlapping approved code mapping'); END""")

    op.execute("""CREATE TRIGGER revision_origin_insert
        BEFORE INSERT ON quotation_revision WHEN
        (SELECT origin_port_id FROM quotation WHERE id=NEW.quotation_id) !=
        (SELECT origin_port_id FROM application WHERE id=NEW.application_id)
        BEGIN SELECT RAISE(ABORT, 'cross-origin quotation application'); END""")

    # Parent-child references alone do not ensure a common source batch.
    checks = {
        "source_group_file": "(SELECT batch_id FROM source_group WHERE id=NEW.source_group_id) != (SELECT batch_id FROM source_file WHERE id=NEW.source_file_id)",
        "extraction_candidate": "NEW.batch_id != (SELECT batch_id FROM extraction_run WHERE id=NEW.run_id) OR (NEW.source_group_id IS NOT NULL AND NEW.batch_id != (SELECT batch_id FROM source_group WHERE id=NEW.source_group_id))",
        "evidence": "(SELECT batch_id FROM extraction_candidate WHERE id=NEW.candidate_id) != (SELECT batch_id FROM source_file WHERE id=NEW.file_id)",
    }
    for table, condition in checks.items():
        for action in ("INSERT", "UPDATE"):
            op.execute(f"""CREATE TRIGGER {table}_batch_{action.lower()}
                BEFORE {action} ON {table} WHEN {condition}
                BEGIN SELECT RAISE(ABORT, 'cross-batch evidence reference'); END""")


def downgrade():
    raise RuntimeError("Use a verified backup to recover; destructive downgrade is disabled")
