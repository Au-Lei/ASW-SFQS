"""Migration connections are supplied by the checked local migration command."""
from alembic import context
from backend.app.repositories.models import Base

connection = context.config.attributes.get("connection")
if connection is None:
    raise RuntimeError("Use python -m backend.app.repositories.cli upgrade/check")

context.configure(connection=connection, target_metadata=Base.metadata,
                  compare_type=True, render_as_batch=True)
with context.begin_transaction():
    context.run_migrations()
