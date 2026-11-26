"""Spike 0004: Alembic environment. Everything comes from `Config.attributes` (see run.py)."""

import sys
from pathlib import Path

import sqlalchemy as sa
from alembic import context

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import ext

attrs = context.config.attributes
config = attrs["config"]  # "stock" | "baseline" | "ckplugin"

plugins = ext.plugins_for(config)
attrs["rename_rewrite"] = config != "stock"

engine = sa.create_engine(attrs["url"])
with engine.connect() as connection:
    context.configure(
        connection=connection,
        target_metadata=attrs["metadata"],
        autogenerate_plugins=plugins,
        process_revision_directives=ext.directives_hook(attrs),
        compare_type=True,
        render_item=ext.render_item,
    )
    with context.begin_transaction():
        context.run_migrations()
engine.dispose()
