"""Spike 0004 reproduction: H7/H8/H9 against the installed Alembic, and trigger drift (H3)."""

import repro_harness as h
import sqlalchemy as sa
from alembic.autogenerate import renderers
from alembic.ddl.impl import DefaultImpl
from alembic.ddl.postgresql import PostgresqlImpl
from alembic.operations import ops
from repro_states import ITEMS

# H7: who implements compare_check_constraint?
print(
    "H7 PostgresqlImpl overrides compare_check_constraint:",
    "compare_check_constraint" in vars(PostgresqlImpl),
)
print(
    "H7 DefaultImpl.compare_check_constraint(x, y):",
    DefaultImpl.compare_check_constraint(None, None, None),
)  # type: ignore[arg-type]

# H8: which dialect options does the PostgreSQL index comparison look at?
where = sa.Index("ix", sa.Column("a", sa.Integer()), postgresql_where=sa.text("a > 0"))
print("H8 _dialect_options(index with WHERE):", PostgresqlImpl._dialect_options(None, where))  # type: ignore[arg-type]

# H9: stock reverse of a column rename and of a table rename
alter = ops.AlterColumnOp("t", "old", modify_name="new", existing_type=sa.Integer())
rev = alter.reverse()
print(
    "H9 AlterColumnOp(old -> new).reverse():",
    {"column_name": rev.column_name, "modify_name": rev.modify_name},
)
try:
    ops.RenameTableOp("a", "b").reverse()
except NotImplementedError as e:
    print("H9 RenameTableOp.reverse():", type(e).__name__, e)
try:
    renderers.dispatch(ops.RenameTableOp("a", "b"))
    print("H9 renderer for stock RenameTableOp: present")
except ValueError as e:
    print("H9 renderer for stock RenameTableOp:", type(e).__name__, e)

# H3 drift: the trigger plugin under baseline, with the trigger or body changed by hand
sc = ITEMS["3"][0]
md = sc.states[0].md
h.reset("public")
eng = sa.create_engine(h.SA_URL)
with eng.begin() as c:
    md("columns").create_all(c)
    for s in __import__("registry").version_ddl(md("columns")):
        c.exec_driver_sql(s.replace("%", "%%"))
eng.dispose()
print("H3 drift, in sync:", h.compare_now("baseline", md("columns")))
h.sql(
    "DROP TRIGGER platina_version_orders ON orders; CREATE TRIGGER platina_version_orders "
    "AFTER INSERT ON orders FOR EACH ROW EXECUTE FUNCTION platina_bump_version()"
)
print("H3 drift, same trigger name but AFTER INSERT:", h.compare_now("baseline", md("columns")))
h.sql(
    "CREATE OR REPLACE FUNCTION platina_bump_version() RETURNS trigger LANGUAGE plpgsql "
    "AS $$BEGIN RETURN NEW; END;$$"
)
print("H3 drift, body edited by hand:", h.compare_now("baseline", md("columns")))
print("H3 stock, trigger and function present:", h.compare_now("stock", md("columns")))
h.reset("public")
