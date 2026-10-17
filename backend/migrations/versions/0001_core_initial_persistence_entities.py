"""Initial persistence entities. Frozen DDL; never import mutable ORM metadata."""
from alembic import op
import sqlalchemy as sa


revision = '0001_core'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('audit_event',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('entity_type', sa.String(length=100), nullable=False),
    sa.Column('entity_id', sa.String(length=100), nullable=False),
    sa.Column('action', sa.String(length=100), nullable=False),
    sa.Column('actor_id', sa.String(length=100), nullable=True),
    sa.Column('actor_label', sa.Text(), nullable=False),
    sa.Column('occurred_at', sa.DateTime(), nullable=False),
    sa.Column('before_hash', sa.String(length=64), nullable=True),
    sa.Column('after_hash', sa.String(length=64), nullable=True),
    sa.Column('request_id', sa.String(length=100), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_audit_event'))
    )
    with op.batch_alter_table('audit_event', schema=None) as batch_op:
        batch_op.create_index('ix_audit_entity_time', ['entity_type', 'entity_id', 'occurred_at'], unique=False)

    op.create_table('carrier',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('code', sa.String(length=32), nullable=False),
    sa.Column('name_en', sa.Text(), nullable=True),
    sa.Column('name_zh', sa.Text(), nullable=True),
    sa.Column('active', sa.Boolean(), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_carrier')),
    sa.UniqueConstraint('code', name=op.f('uq_carrier_code'))
    )
    op.create_table('country_region',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('internal_code', sa.String(length=100), nullable=False),
    sa.Column('iso_country_code', sa.String(length=2), nullable=True),
    sa.Column('name_en', sa.Text(), nullable=False),
    sa.Column('name_zh', sa.Text(), nullable=False),
    sa.Column('parent_country_id', sa.String(length=36), nullable=True),
    sa.Column('active', sa.Boolean(), nullable=False),
    sa.ForeignKeyConstraint(['parent_country_id'], ['country_region.id'], name=op.f('fk_country_region_parent_country_id_country_region'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_country_region')),
    sa.UniqueConstraint('internal_code', name=op.f('uq_country_region_internal_code'))
    )
    op.create_table('model_config',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('provider', sa.String(length=100), nullable=False),
    sa.Column('model_identifier', sa.String(length=200), nullable=False),
    sa.Column('prompt_version', sa.String(length=100), nullable=False),
    sa.Column('schema_version', sa.String(length=100), nullable=False),
    sa.Column('secret_ref', sa.String(length=200), nullable=True),
    sa.Column('enabled', sa.Boolean(), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_model_config'))
    )
    op.create_table('origin_port',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('display_en', sa.Text(), nullable=False),
    sa.Column('display_zh', sa.Text(), nullable=False),
    sa.Column('standard_code', sa.String(length=5), nullable=True),
    sa.Column('active', sa.Boolean(), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_origin_port'))
    )
    op.create_table('quotation',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('origin_port_id', sa.String(length=36), nullable=False),
    sa.Column('destination_id', sa.String(length=36), nullable=False),
    sa.Column('carrier_id', sa.String(length=36), nullable=True),
    sa.Column('source_id', sa.String(length=36), nullable=True),
    sa.Column('current_revision_id', sa.String(length=36), nullable=False),
    sa.Column('related_quotation_id', sa.String(length=36), nullable=True),
    sa.Column('lifecycle_state', sa.String(length=40), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('created_by', sa.String(length=100), nullable=True),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.CheckConstraint('version >= 1', name=op.f('ck_quotation_version_positive')),
    sa.ForeignKeyConstraint(['carrier_id'], ['carrier.id'], name=op.f('fk_quotation_carrier_id_carrier'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['current_revision_id', 'id'], ['quotation_revision.id', 'quotation_revision.quotation_id'], name=op.f('fk_quotation_current_revision_id_quotation_revision'), initially='DEFERRED', deferrable=True),
    sa.ForeignKeyConstraint(['destination_id'], ['destination.id'], name=op.f('fk_quotation_destination_id_destination'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['origin_port_id'], ['origin_port.id'], name=op.f('fk_quotation_origin_port_id_origin_port'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['related_quotation_id'], ['quotation.id'], name=op.f('fk_quotation_related_quotation_id_quotation'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['source_id'], ['source.id'], name=op.f('fk_quotation_source_id_source'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_quotation')),
    sa.CheckConstraint("lifecycle_state IN ('ACTIVE','ARCHIVED')", name=op.f('ck_quotation_lifecycle_state_values'))
    )
    with op.batch_alter_table('quotation', schema=None) as batch_op:
        batch_op.create_index('ix_quotation_carrier_source', ['carrier_id', 'source_id'], unique=False)
        batch_op.create_index('ix_quotation_origin_destination_state', ['origin_port_id', 'destination_id', 'lifecycle_state'], unique=False)

    op.create_table('quotation_revision',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('quotation_id', sa.String(length=36), nullable=False),
    sa.Column('revision_no', sa.Integer(), nullable=False),
    sa.Column('price_20gp', sa.BigInteger(), nullable=True),
    sa.Column('price_40gp', sa.BigInteger(), nullable=True),
    sa.Column('price_40hq', sa.BigInteger(), nullable=True),
    sa.Column('currency', sa.String(length=3), nullable=True),
    sa.Column('sailing_weekdays', sa.JSON(none_as_null=True), nullable=False),
    sa.Column('sailing_text', sa.Text(), nullable=True),
    sa.Column('transit', sa.JSON(none_as_null=True), nullable=False),
    sa.Column('routing', sa.JSON(none_as_null=True), nullable=False),
    sa.Column('valid_from', sa.Date(), nullable=True),
    sa.Column('valid_to', sa.Date(), nullable=True),
    sa.Column('validity_basis', sa.String(length=40), nullable=False),
    sa.Column('remarks', sa.Text(), nullable=True),
    sa.Column('price_scope_summary', sa.Text(), nullable=True),
    sa.Column('conditions', sa.JSON(none_as_null=True), nullable=False),
    sa.Column('quality_flags', sa.JSON(none_as_null=True), nullable=False),
    sa.Column('service', sa.Text(), nullable=True),
    sa.Column('price_profile', sa.String(length=100), nullable=True),
    sa.Column('candidate_id', sa.String(length=36), nullable=True),
    sa.Column('application_id', sa.String(length=36), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('created_by', sa.String(length=100), nullable=True),
    sa.Column('canonical_payload_hash', sa.String(length=64), nullable=False),
    sa.Column('identity_snapshot', sa.JSON(none_as_null=True), nullable=False),
    sa.CheckConstraint("currency IS NULL OR (length(currency) = 3 AND currency NOT GLOB '*[^A-Z]*')", name=op.f('ck_quotation_revision_currency_shape')),
    sa.CheckConstraint("price_20gp IS NULL OR (typeof(price_20gp) = 'integer' AND price_20gp BETWEEN 0 AND 999999999999999999)", name=op.f('ck_quotation_revision_price_20gp_exact')),
    sa.CheckConstraint("price_40gp IS NULL OR (typeof(price_40gp) = 'integer' AND price_40gp BETWEEN 0 AND 999999999999999999)", name=op.f('ck_quotation_revision_price_40gp_exact')),
    sa.CheckConstraint("price_40hq IS NULL OR (typeof(price_40hq) = 'integer' AND price_40hq BETWEEN 0 AND 999999999999999999)", name=op.f('ck_quotation_revision_price_40hq_exact')),
    sa.CheckConstraint('price_20gp IS NOT NULL OR price_40gp IS NOT NULL OR price_40hq IS NOT NULL', name=op.f('ck_quotation_revision_at_least_one_price')),
    sa.CheckConstraint('valid_from IS NULL OR valid_to IS NULL OR valid_to >= valid_from', name=op.f('ck_quotation_revision_validity_order')),
    sa.ForeignKeyConstraint(['application_id'], ['application.id'], name=op.f('fk_quotation_revision_application_id_application'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['candidate_id'], ['extraction_candidate.id'], name=op.f('fk_quotation_revision_candidate_id_extraction_candidate'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['quotation_id'], ['quotation.id'], name=op.f('fk_quotation_revision_quotation_id_quotation'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_quotation_revision')),
    sa.UniqueConstraint('id', 'quotation_id', name='uq_revision_owner'),
    sa.UniqueConstraint('quotation_id', 'revision_no', name='uq_revision_number'),
    sa.CheckConstraint("valid_from IS NULL OR (length(valid_from) = 10 AND valid_from GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]' AND date(valid_from, '+0 days') IS NOT NULL AND date(valid_from, '+0 days') = valid_from)", name=op.f('ck_quotation_revision_valid_from_calendar')),
    sa.CheckConstraint("valid_to IS NULL OR (length(valid_to) = 10 AND valid_to GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]' AND date(valid_to, '+0 days') IS NOT NULL AND date(valid_to, '+0 days') = valid_to)", name=op.f('ck_quotation_revision_valid_to_calendar')),
    sa.CheckConstraint('revision_no >= 1', name=op.f('ck_quotation_revision_revision_positive')),
    sa.CheckConstraint("validity_basis IN ('UNSPECIFIED','ETD','BOOKING_DATE','GATE_IN_DATE','QUOTATION_DATE','OTHER')", name=op.f('ck_quotation_revision_validity_basis_values'))
    )
    with op.batch_alter_table('quotation_revision', schema=None) as batch_op:
        batch_op.create_index('ix_revision_validity_currency', ['valid_from', 'valid_to', 'currency'], unique=False)

    op.create_table('region',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('code', sa.String(length=100), nullable=False),
    sa.Column('sheet_name', sa.String(length=31), nullable=False),
    sa.Column('sort_order', sa.Integer(), nullable=False),
    sa.Column('active', sa.Boolean(), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_region')),
    sa.UniqueConstraint('code', name=op.f('uq_region_code')),
    sa.UniqueConstraint('sheet_name', name=op.f('uq_region_sheet_name'))
    )
    op.create_table('source',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('name', sa.Text(), nullable=False),
    sa.Column('kind', sa.String(length=40), nullable=False),
    sa.Column('public_code', sa.String(length=100), nullable=True),
    sa.Column('active', sa.Boolean(), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_source')),
    sa.UniqueConstraint('public_code', name=op.f('uq_source_public_code')),
    sa.CheckConstraint("kind IN ('CARRIER','AGENT','OTHER','UNKNOWN')", name=op.f('ck_source_kind_values'))
    )
    op.create_table('template_config',
    sa.Column('version', sa.String(length=100), nullable=False),
    sa.Column('schema_version', sa.String(length=100), nullable=False),
    sa.Column('layout_json', sa.JSON(none_as_null=True), nullable=False),
    sa.Column('checksum', sa.String(length=64), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('version', name=op.f('pk_template_config'))
    )
    op.create_table('carrier_alias',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('carrier_id', sa.String(length=36), nullable=False),
    sa.Column('alias_raw', sa.Text(), nullable=False),
    sa.Column('alias_normalized', sa.Text(), nullable=False),
    sa.ForeignKeyConstraint(['carrier_id'], ['carrier.id'], name=op.f('fk_carrier_alias_carrier_id_carrier'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_carrier_alias'))
    )
    with op.batch_alter_table('carrier_alias', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_carrier_alias_alias_normalized'), ['alias_normalized'], unique=False)

    op.create_table('change_plan',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('origin_port_id', sa.String(length=36), nullable=False),
    sa.Column('base_dataset_version', sa.Integer(), nullable=False),
    sa.Column('selected_candidate_versions', sa.JSON(none_as_null=True), nullable=False),
    sa.Column('items', sa.JSON(none_as_null=True), nullable=False),
    sa.Column('content_hash', sa.String(length=64), nullable=False),
    sa.Column('state', sa.String(length=40), nullable=False),
    sa.Column('expires_at', sa.DateTime(), nullable=True),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.CheckConstraint('version >= 1', name=op.f('ck_change_plan_version_positive')),
    sa.ForeignKeyConstraint(['origin_port_id'], ['origin_port.id'], name=op.f('fk_change_plan_origin_port_id_origin_port'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_change_plan')),
    sa.UniqueConstraint('id', 'origin_port_id', name='uq_plan_id_origin'),
    sa.CheckConstraint("state IN ('DRAFT','READY','APPLIED','STALE','CANCELLED')", name=op.f('ck_change_plan_state_values'))
    )
    op.create_table('dataset_snapshot',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('origin_port_id', sa.String(length=36), nullable=False),
    sa.Column('dataset_version', sa.Integer(), nullable=False),
    sa.Column('payload_json', sa.JSON(none_as_null=True), nullable=False),
    sa.Column('payload_storage_key', sa.Text(), nullable=True),
    sa.Column('payload_sha256', sa.String(length=64), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['origin_port_id'], ['origin_port.id'], name=op.f('fk_dataset_snapshot_origin_port_id_origin_port'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_dataset_snapshot')),
    sa.UniqueConstraint('id', 'origin_port_id', 'dataset_version', name='uq_snapshot_identity'),
    sa.UniqueConstraint('origin_port_id', 'dataset_version', name='uq_snapshot_origin_version'),
    sa.CheckConstraint('dataset_version >= 1', name=op.f('ck_dataset_snapshot_dataset_positive'))
    )
    op.create_table('dataset_version',
    sa.Column('origin_port_id', sa.String(length=36), nullable=False),
    sa.Column('dataset_version', sa.Integer(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.CheckConstraint('version >= 1', name=op.f('ck_dataset_version_version_positive')),
    sa.ForeignKeyConstraint(['origin_port_id'], ['origin_port.id'], name=op.f('fk_dataset_version_origin_port_id_origin_port'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('origin_port_id', name=op.f('pk_dataset_version')),
    sa.CheckConstraint('dataset_version >= 1', name=op.f('ck_dataset_version_dataset_positive'))
    )
    op.create_table('import_batch',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('origin_port_id', sa.String(length=36), nullable=False),
    sa.Column('title', sa.Text(), nullable=False),
    sa.Column('source_id', sa.String(length=36), nullable=True),
    sa.Column('created_by', sa.String(length=100), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.CheckConstraint('version >= 1', name=op.f('ck_import_batch_version_positive')),
    sa.ForeignKeyConstraint(['origin_port_id'], ['origin_port.id'], name=op.f('fk_import_batch_origin_port_id_origin_port'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['source_id'], ['source.id'], name=op.f('fk_import_batch_source_id_source'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_import_batch'))
    )
    op.create_table('route_group',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('region_id', sa.String(length=36), nullable=False),
    sa.Column('code', sa.String(length=100), nullable=False),
    sa.Column('name', sa.Text(), nullable=False),
    sa.Column('sort_order', sa.Integer(), nullable=False),
    sa.Column('active', sa.Boolean(), nullable=False),
    sa.ForeignKeyConstraint(['region_id'], ['region.id'], name=op.f('fk_route_group_region_id_region'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_route_group')),
    sa.UniqueConstraint('code', name=op.f('uq_route_group_code'))
    )
    op.create_table('application',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('origin_port_id', sa.String(length=36), nullable=False),
    sa.Column('plan_id', sa.String(length=36), nullable=False),
    sa.Column('idempotency_key', sa.String(length=200), nullable=False),
    sa.Column('request_hash', sa.String(length=64), nullable=False),
    sa.Column('before_version', sa.Integer(), nullable=False),
    sa.Column('after_version', sa.Integer(), nullable=False),
    sa.Column('actor_id', sa.String(length=100), nullable=True),
    sa.Column('applied_at', sa.DateTime(), nullable=False),
    sa.Column('status', sa.String(length=40), nullable=False),
    sa.CheckConstraint('before_version >= 1 AND after_version = before_version + 1', name=op.f('ck_application_version_step')),
    sa.ForeignKeyConstraint(['origin_port_id', 'after_version'], ['dataset_snapshot.origin_port_id', 'dataset_snapshot.dataset_version'], name=op.f('fk_application_origin_port_id_dataset_snapshot'), initially='DEFERRED', deferrable=True),
    sa.ForeignKeyConstraint(['origin_port_id'], ['origin_port.id'], name=op.f('fk_application_origin_port_id_origin_port'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['plan_id', 'origin_port_id'], ['change_plan.id', 'change_plan.origin_port_id'], name=op.f('fk_application_plan_id_change_plan'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_application')),
    sa.UniqueConstraint('origin_port_id', 'idempotency_key', name='uq_application_origin_key'),
    sa.CheckConstraint("status IN ('APPLIED')", name=op.f('ck_application_status_values')),
    sa.UniqueConstraint('origin_port_id', 'after_version', name='uq_application_origin_version')
    )
    op.create_table('destination',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('country_region_id', sa.String(length=36), nullable=False),
    sa.Column('kind', sa.String(length=40), nullable=False),
    sa.Column('parent_destination_id', sa.String(length=36), nullable=True),
    sa.Column('terminal_key', sa.String(length=160), nullable=True),
    sa.Column('canonical_key', sa.String(length=200), nullable=False),
    sa.Column('display_name_en', sa.Text(), nullable=False),
    sa.Column('display_name_zh', sa.Text(), nullable=False),
    sa.Column('unlocode', sa.String(length=5), nullable=True),
    sa.Column('route_group_id', sa.String(length=36), nullable=False),
    sa.Column('sort_order', sa.Integer(), nullable=False),
    sa.Column('active', sa.Boolean(), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.CheckConstraint("kind != 'TERMINAL' OR (parent_destination_id IS NOT NULL AND terminal_key IS NOT NULL AND length(trim(terminal_key)) > 0)", name=op.f('ck_destination_terminal_identity')),
    sa.CheckConstraint('parent_destination_id IS NULL OR parent_destination_id != id', name=op.f('ck_destination_not_self_parent')),
    sa.CheckConstraint('version >= 1', name=op.f('ck_destination_version_positive')),
    sa.ForeignKeyConstraint(['country_region_id'], ['country_region.id'], name=op.f('fk_destination_country_region_id_country_region'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['parent_destination_id'], ['destination.id'], name=op.f('fk_destination_parent_destination_id_destination'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['route_group_id'], ['route_group.id'], name=op.f('fk_destination_route_group_id_route_group'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_destination')),
    sa.UniqueConstraint('canonical_key', name=op.f('uq_destination_canonical_key')),
    sa.UniqueConstraint('parent_destination_id', 'terminal_key', name='uq_destination_parent_terminal'),
    sa.CheckConstraint("kind IN ('SEAPORT','TERMINAL','ICD','INLAND_POINT','CITY_SCOPE','UNKNOWN')", name=op.f('ck_destination_kind_values'))
    )
    with op.batch_alter_table('destination', schema=None) as batch_op:
        batch_op.create_index('ix_destination_route_active_sort', ['route_group_id', 'active', 'sort_order'], unique=False)

    op.create_table('export_artifact',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('origin_port_id', sa.String(length=36), nullable=False),
    sa.Column('snapshot_id', sa.String(length=36), nullable=False),
    sa.Column('dataset_version', sa.Integer(), nullable=False),
    sa.Column('baseline_version', sa.Integer(), nullable=True),
    sa.Column('export_mode', sa.String(length=40), nullable=False),
    sa.Column('filter_payload', sa.JSON(none_as_null=True), nullable=False),
    sa.Column('template_version', sa.String(length=100), nullable=False),
    sa.Column('file_sha256', sa.String(length=64), nullable=True),
    sa.Column('file_storage_key', sa.Text(), nullable=True),
    sa.Column('state', sa.String(length=40), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('error', sa.JSON(none_as_null=True), nullable=True),
    sa.ForeignKeyConstraint(['origin_port_id'], ['origin_port.id'], name=op.f('fk_export_artifact_origin_port_id_origin_port'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['snapshot_id', 'origin_port_id', 'dataset_version'], ['dataset_snapshot.id', 'dataset_snapshot.origin_port_id', 'dataset_snapshot.dataset_version'], name=op.f('fk_export_artifact_snapshot_id_dataset_snapshot'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['template_version'], ['template_config.version'], name=op.f('fk_export_artifact_template_version_template_config'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_export_artifact')),
    sa.CheckConstraint("export_mode IN ('FULL','FILTERED')", name=op.f('ck_export_artifact_export_mode_values')),
    sa.CheckConstraint("state IN ('QUEUED','RUNNING','SUCCEEDED','PARTIAL_FAILED','FAILED','CANCELLED','INTERRUPTED')", name=op.f('ck_export_artifact_state_values'))
    )
    with op.batch_alter_table('export_artifact', schema=None) as batch_op:
        batch_op.create_index('ix_export_cache', ['origin_port_id', 'dataset_version', 'template_version', 'export_mode', 'baseline_version'], unique=False)

    op.create_table('extraction_run',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('batch_id', sa.String(length=36), nullable=False),
    sa.Column('state', sa.String(length=40), nullable=False),
    sa.Column('provider_config_id', sa.String(length=36), nullable=True),
    sa.Column('model_name', sa.String(length=200), nullable=True),
    sa.Column('prompt_version', sa.String(length=100), nullable=False),
    sa.Column('parser_version', sa.String(length=100), nullable=False),
    sa.Column('started_at', sa.DateTime(), nullable=True),
    sa.Column('finished_at', sa.DateTime(), nullable=True),
    sa.Column('error', sa.JSON(none_as_null=True), nullable=True),
    sa.ForeignKeyConstraint(['batch_id'], ['import_batch.id'], name=op.f('fk_extraction_run_batch_id_import_batch'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['provider_config_id'], ['model_config.id'], name=op.f('fk_extraction_run_provider_config_id_model_config'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_extraction_run')),
    sa.CheckConstraint("state IN ('QUEUED','RUNNING','SUCCEEDED','PARTIAL_FAILED','FAILED','CANCELLED','INTERRUPTED')", name=op.f('ck_extraction_run_state_values'))
    )
    with op.batch_alter_table('extraction_run', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_extraction_run_batch_id'), ['batch_id'], unique=False)

    op.create_table('job',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('kind', sa.String(length=100), nullable=False),
    sa.Column('state', sa.String(length=40), nullable=False),
    sa.Column('stage', sa.String(length=100), nullable=True),
    sa.Column('batch_id', sa.String(length=36), nullable=True),
    sa.Column('lease_owner', sa.String(length=100), nullable=True),
    sa.Column('lease_expires_at', sa.DateTime(), nullable=True),
    sa.Column('heartbeat_at', sa.DateTime(), nullable=True),
    sa.Column('attempts', sa.Integer(), nullable=False),
    sa.Column('max_attempts', sa.Integer(), nullable=False),
    sa.Column('cancel_requested', sa.Boolean(), nullable=False),
    sa.Column('payload', sa.JSON(none_as_null=True), nullable=False),
    sa.Column('result_ref', sa.JSON(none_as_null=True), nullable=True),
    sa.Column('error', sa.JSON(none_as_null=True), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.CheckConstraint('attempts >= 0 AND max_attempts >= 1', name=op.f('ck_job_attempt_limits')),
    sa.CheckConstraint('version >= 1', name=op.f('ck_job_version_positive')),
    sa.ForeignKeyConstraint(['batch_id'], ['import_batch.id'], name=op.f('fk_job_batch_id_import_batch'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_job')),
    sa.CheckConstraint("state IN ('QUEUED','RUNNING','SUCCEEDED','PARTIAL_FAILED','FAILED','CANCELLED','INTERRUPTED')", name=op.f('ck_job_state_values'))
    )
    with op.batch_alter_table('job', schema=None) as batch_op:
        batch_op.create_index('ix_job_claim', ['state', 'lease_expires_at', 'created_at'], unique=False)

    op.create_table('source_file',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('batch_id', sa.String(length=36), nullable=False),
    sa.Column('original_name', sa.Text(), nullable=False),
    sa.Column('storage_key', sa.Text(), nullable=False),
    sa.Column('mime_type', sa.String(length=150), nullable=False),
    sa.Column('byte_size', sa.Integer(), nullable=False),
    sa.Column('sha256', sa.String(length=64), nullable=False),
    sa.Column('uploaded_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['batch_id'], ['import_batch.id'], name=op.f('fk_source_file_batch_id_import_batch'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_source_file')),
    sa.CheckConstraint('byte_size >= 0', name=op.f('ck_source_file_size_nonnegative'))
    )
    with op.batch_alter_table('source_file', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_source_file_batch_id'), ['batch_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_source_file_sha256'), ['sha256'], unique=False)

    op.create_table('source_group',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('batch_id', sa.String(length=36), nullable=False),
    sa.Column('source_id', sa.String(length=36), nullable=True),
    sa.Column('carrier_id', sa.String(length=36), nullable=True),
    sa.Column('context_defaults', sa.JSON(none_as_null=True), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.CheckConstraint('version >= 1', name=op.f('ck_source_group_version_positive')),
    sa.ForeignKeyConstraint(['batch_id'], ['import_batch.id'], name=op.f('fk_source_group_batch_id_import_batch'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['carrier_id'], ['carrier.id'], name=op.f('fk_source_group_carrier_id_carrier'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['source_id'], ['source.id'], name=op.f('fk_source_group_source_id_source'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_source_group'))
    )
    with op.batch_alter_table('source_group', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_source_group_batch_id'), ['batch_id'], unique=False)

    op.create_table('charge_rule',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('quotation_revision_id', sa.String(length=36), nullable=True),
    sa.Column('source_group_id', sa.String(length=36), nullable=True),
    sa.Column('type', sa.String(length=100), nullable=False),
    sa.Column('raw_text', sa.Text(), nullable=False),
    sa.Column('normalized_payload', sa.JSON(none_as_null=True), nullable=False),
    sa.Column('scope', sa.JSON(none_as_null=True), nullable=False),
    sa.Column('review_state', sa.String(length=40), nullable=False),
    sa.Column('evidence_ids', sa.JSON(none_as_null=True), nullable=False),
    sa.CheckConstraint('quotation_revision_id IS NOT NULL OR source_group_id IS NOT NULL', name=op.f('ck_charge_rule_has_owner')),
    sa.ForeignKeyConstraint(['quotation_revision_id'], ['quotation_revision.id'], name=op.f('fk_charge_rule_quotation_revision_id_quotation_revision'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['source_group_id'], ['source_group.id'], name=op.f('fk_charge_rule_source_group_id_source_group'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_charge_rule')),
    sa.CheckConstraint("review_state IN ('PENDING_REVIEW','APPROVED','NEEDS_INFO','REJECTED')", name=op.f('ck_charge_rule_review_state_values'))
    )
    op.create_table('destination_alias',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('destination_id', sa.String(length=36), nullable=False),
    sa.Column('alias_raw', sa.Text(), nullable=False),
    sa.Column('alias_normalized', sa.Text(), nullable=False),
    sa.Column('alias_kind', sa.String(length=50), nullable=False),
    sa.Column('source_scope_id', sa.String(length=36), nullable=True),
    sa.Column('country_scope_id', sa.String(length=36), nullable=True),
    sa.Column('verified_at', sa.DateTime(), nullable=True),
    sa.Column('verified_by', sa.String(length=100), nullable=True),
    sa.ForeignKeyConstraint(['country_scope_id'], ['country_region.id'], name=op.f('fk_destination_alias_country_scope_id_country_region'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['destination_id'], ['destination.id'], name=op.f('fk_destination_alias_destination_id_destination'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['source_scope_id'], ['source.id'], name=op.f('fk_destination_alias_source_scope_id_source'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_destination_alias'))
    )
    with op.batch_alter_table('destination_alias', schema=None) as batch_op:
        batch_op.create_index('ix_alias_scoped_lookup', ['alias_normalized', 'source_scope_id', 'country_scope_id'], unique=False)

    op.create_table('extraction_candidate',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('batch_id', sa.String(length=36), nullable=False),
    sa.Column('source_group_id', sa.String(length=36), nullable=True),
    sa.Column('run_id', sa.String(length=36), nullable=False),
    sa.Column('raw_payload', sa.JSON(none_as_null=True), nullable=False),
    sa.Column('normalized_payload', sa.JSON(none_as_null=True), nullable=False),
    sa.Column('field_provenance', sa.JSON(none_as_null=True), nullable=False),
    sa.Column('issues', sa.JSON(none_as_null=True), nullable=False),
    sa.Column('review_state', sa.String(length=40), nullable=False),
    sa.Column('review_version', sa.Integer(), nullable=False),
    sa.Column('match_state', sa.String(length=40), nullable=False),
    sa.Column('application_state', sa.String(length=40), nullable=False),
    sa.Column('disposition', sa.String(length=40), nullable=False),
    sa.Column('reviewed_by', sa.String(length=100), nullable=True),
    sa.Column('reviewed_at', sa.DateTime(), nullable=True),
    sa.Column('reviewed_payload_hash', sa.String(length=64), nullable=True),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.CheckConstraint("review_state != 'APPROVED' OR (reviewed_payload_hash IS NOT NULL AND reviewed_at IS NOT NULL AND reviewed_by IS NOT NULL)", name=op.f('ck_extraction_candidate_approval_snapshot')),
    sa.CheckConstraint('review_version >= 1', name=op.f('ck_extraction_candidate_review_version_positive')),
    sa.CheckConstraint('version >= 1', name=op.f('ck_extraction_candidate_version_positive')),
    sa.ForeignKeyConstraint(['batch_id'], ['import_batch.id'], name=op.f('fk_extraction_candidate_batch_id_import_batch'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['run_id'], ['extraction_run.id'], name=op.f('fk_extraction_candidate_run_id_extraction_run'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['source_group_id'], ['source_group.id'], name=op.f('fk_extraction_candidate_source_group_id_source_group'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_extraction_candidate')),
    sa.CheckConstraint("application_state IN ('NOT_APPLIED','APPLIED','NO_CHANGE','EXCLUDED')", name=op.f('ck_extraction_candidate_application_state_values')),
    sa.CheckConstraint("disposition IN ('INCLUDE','DEFER','EXCLUDE')", name=op.f('ck_extraction_candidate_disposition_values')),
    sa.CheckConstraint("match_state IN ('UNMATCHED','SUGGESTED','CONFIRMED','OUT_OF_SCOPE')", name=op.f('ck_extraction_candidate_match_state_values')),
    sa.CheckConstraint("review_state IN ('PENDING_REVIEW','APPROVED','NEEDS_INFO','REJECTED')", name=op.f('ck_extraction_candidate_review_state_values'))
    )
    with op.batch_alter_table('extraction_candidate', schema=None) as batch_op:
        batch_op.create_index('ix_candidate_batch_review', ['batch_id', 'review_state'], unique=False)
        batch_op.create_index(batch_op.f('ix_extraction_candidate_run_id'), ['run_id'], unique=False)

    op.create_table('location_code_mapping',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('namespace', sa.String(length=100), nullable=False),
    sa.Column('issuer_id', sa.String(length=36), nullable=True),
    sa.Column('code_raw', sa.Text(), nullable=False),
    sa.Column('code_normalized', sa.Text(), nullable=False),
    sa.Column('destination_id', sa.String(length=36), nullable=True),
    sa.Column('origin_port_id', sa.String(length=36), nullable=True),
    sa.Column('review_state', sa.String(length=40), nullable=False),
    sa.Column('valid_from', sa.Date(), nullable=True),
    sa.Column('valid_to', sa.Date(), nullable=True),
    sa.Column('evidence_ids', sa.JSON(none_as_null=True), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.CheckConstraint('(destination_id IS NOT NULL) != (origin_port_id IS NOT NULL)', name=op.f('ck_location_code_mapping_one_location')),
    sa.CheckConstraint('valid_from IS NULL OR valid_to IS NULL OR valid_to >= valid_from', name=op.f('ck_location_code_mapping_validity_order')),
    sa.CheckConstraint('version >= 1', name=op.f('ck_location_code_mapping_version_positive')),
    sa.ForeignKeyConstraint(['destination_id'], ['destination.id'], name=op.f('fk_location_code_mapping_destination_id_destination'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['issuer_id'], ['source.id'], name=op.f('fk_location_code_mapping_issuer_id_source'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['origin_port_id'], ['origin_port.id'], name=op.f('fk_location_code_mapping_origin_port_id_origin_port'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_location_code_mapping')),
    sa.CheckConstraint("valid_from IS NULL OR (length(valid_from) = 10 AND valid_from GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]' AND date(valid_from, '+0 days') IS NOT NULL AND date(valid_from, '+0 days') = valid_from)", name=op.f('ck_location_code_mapping_valid_from_calendar')),
    sa.CheckConstraint("valid_to IS NULL OR (length(valid_to) = 10 AND valid_to GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]' AND date(valid_to, '+0 days') IS NOT NULL AND date(valid_to, '+0 days') = valid_to)", name=op.f('ck_location_code_mapping_valid_to_calendar')),
    sa.CheckConstraint("review_state IN ('PENDING_REVIEW','APPROVED','NEEDS_INFO','REJECTED')", name=op.f('ck_location_code_mapping_review_state_values'))
    )
    with op.batch_alter_table('location_code_mapping', schema=None) as batch_op:
        batch_op.create_index('ix_mapping_scope', ['namespace', 'issuer_id', 'code_normalized', 'review_state'], unique=False)

    op.create_table('source_group_file',
    sa.Column('source_group_id', sa.String(length=36), nullable=False),
    sa.Column('source_file_id', sa.String(length=36), nullable=False),
    sa.ForeignKeyConstraint(['source_file_id'], ['source_file.id'], name=op.f('fk_source_group_file_source_file_id_source_file'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['source_group_id'], ['source_group.id'], name=op.f('fk_source_group_file_source_group_id_source_group'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('source_group_id', 'source_file_id', name=op.f('pk_source_group_file'))
    )
    op.create_table('application_item',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('application_id', sa.String(length=36), nullable=False),
    sa.Column('action', sa.String(length=40), nullable=False),
    sa.Column('candidate_id', sa.String(length=36), nullable=True),
    sa.Column('quotation_id', sa.String(length=36), nullable=True),
    sa.Column('before_revision_id', sa.String(length=36), nullable=True),
    sa.Column('after_revision_id', sa.String(length=36), nullable=True),
    sa.Column('field_diff', sa.JSON(none_as_null=True), nullable=False),
    sa.ForeignKeyConstraint(['after_revision_id'], ['quotation_revision.id'], name=op.f('fk_application_item_after_revision_id_quotation_revision'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['application_id'], ['application.id'], name=op.f('fk_application_item_application_id_application'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['before_revision_id'], ['quotation_revision.id'], name=op.f('fk_application_item_before_revision_id_quotation_revision'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['candidate_id'], ['extraction_candidate.id'], name=op.f('fk_application_item_candidate_id_extraction_candidate'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['quotation_id'], ['quotation.id'], name=op.f('fk_application_item_quotation_id_quotation'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_application_item')),
    sa.CheckConstraint("action IN ('CREATE_QUOTE','UPDATE_QUOTE','LINK_EVIDENCE','ARCHIVE_QUOTE','NO_CHANGE','EXCLUDE')", name=op.f('ck_application_item_action_values'))
    )
    with op.batch_alter_table('application_item', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_application_item_application_id'), ['application_id'], unique=False)

    op.create_table('evidence',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('candidate_id', sa.String(length=36), nullable=False),
    sa.Column('field_path', sa.Text(), nullable=True),
    sa.Column('file_id', sa.String(length=36), nullable=False),
    sa.Column('sheet_name', sa.Text(), nullable=True),
    sa.Column('cell_range', sa.String(length=100), nullable=True),
    sa.Column('page_no', sa.Integer(), nullable=True),
    sa.Column('bbox', sa.JSON(none_as_null=True), nullable=True),
    sa.Column('original_text', sa.Text(), nullable=False),
    sa.Column('evidence_type', sa.String(length=50), nullable=False),
    sa.ForeignKeyConstraint(['candidate_id'], ['extraction_candidate.id'], name=op.f('fk_evidence_candidate_id_extraction_candidate'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['file_id'], ['source_file.id'], name=op.f('fk_evidence_file_id_source_file'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_evidence')),
    sa.CheckConstraint('page_no IS NULL OR page_no >= 1', name=op.f('ck_evidence_page_positive'))
    )
    with op.batch_alter_table('evidence', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_evidence_candidate_id'), ['candidate_id'], unique=False)

    op.create_table('issue',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('candidate_id', sa.String(length=36), nullable=True),
    sa.Column('charge_rule_id', sa.String(length=36), nullable=True),
    sa.Column('code', sa.String(length=100), nullable=False),
    sa.Column('field_paths', sa.JSON(none_as_null=True), nullable=False),
    sa.Column('affected_actions', sa.JSON(none_as_null=True), nullable=False),
    sa.Column('severity', sa.String(length=32), nullable=False),
    sa.Column('message', sa.Text(), nullable=False),
    sa.Column('resolution', sa.JSON(none_as_null=True), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.CheckConstraint('candidate_id IS NOT NULL OR charge_rule_id IS NOT NULL', name=op.f('ck_issue_has_owner')),
    sa.CheckConstraint('version >= 1', name=op.f('ck_issue_version_positive')),
    sa.ForeignKeyConstraint(['candidate_id'], ['extraction_candidate.id'], name=op.f('fk_issue_candidate_id_extraction_candidate'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['charge_rule_id'], ['charge_rule.id'], name=op.f('fk_issue_charge_rule_id_charge_rule'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_issue'))
    )


def downgrade():
    raise RuntimeError("Use a verified backup to recover; destructive downgrade is disabled")
