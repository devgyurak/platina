"""Spike 0004: a throwaway entity registry and its conversion to SQLAlchemy `MetaData`.

Mimics section 4.2 with ADR-0003/0004 syntax (`Entity` base, `Col[...]`, `path(...)`). Written
from scratch for this spike; nothing here is the real registry. Assumptions A1-A7 of the write-up
are encoded here: `renamed_from` syntax, index/unique syntax, naming rules, type mapping, the
`version` trigger body.
"""

import annotationlib
import hashlib
import operator
import types
from collections.abc import Callable
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Union, get_args, get_origin

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.types import UserDefinedType


# --------------------------------------------------------------------------- type markers
class Col[T]:
    """Annotation marker only (the real `Col[T]` is a descriptor, ADR-0004)."""


class Id[T]:
    """Annotation marker: a primary-key reference to entity T."""


class Xid8:
    """Annotation marker for PostgreSQL `xid8` (outbox log, checkpoints)."""


class Json:
    """Annotation marker for `jsonb`."""


class XID8(UserDefinedType[Any]):
    cache_ok = True

    def get_col_spec(self, **kw: Any) -> str:
        return "xid8"


# --------------------------------------------------------------------------- expressions
def _wrap(value: Any) -> Expr:
    return value if isinstance(value, Expr) else Lit(value)


class Expr:
    """A tiny expression tree built by the lambdas of `Check`, `Index` and `where=`."""

    __hash__ = object.__hash__

    def _bin(self, op: str, other: Any) -> BinOp:
        return BinOp(op, self, _wrap(other))

    def __ge__(self, other: Any) -> BinOp:
        return self._bin(">=", other)

    def __gt__(self, other: Any) -> BinOp:
        return self._bin(">", other)

    def __le__(self, other: Any) -> BinOp:
        return self._bin("<=", other)

    def __lt__(self, other: Any) -> BinOp:
        return self._bin("<", other)

    def __eq__(self, other: object) -> BinOp:  # type: ignore[override]
        return self._bin("=", other)

    def __ne__(self, other: object) -> BinOp:  # type: ignore[override]
        return self._bin("<>", other)

    def desc(self) -> Desc:
        return Desc(self)

    def key(self) -> str:
        raise NotImplementedError

    def columns(self) -> list[str]:
        raise NotImplementedError

    def to_sa(self, table: sa.Table) -> Any:
        raise NotImplementedError


_SA_OPS: dict[str, Callable[[Any, Any], Any]] = {
    ">=": operator.ge,
    ">": operator.gt,
    "<=": operator.le,
    "<": operator.lt,
    "=": operator.eq,
    "<>": operator.ne,
}


class BinOp(Expr):
    def __init__(self, op: str, left: Expr, right: Expr) -> None:
        self.op, self.left, self.right = op, left, right

    def key(self) -> str:
        return f"({self.left.key()} {self.op} {self.right.key()})"

    def columns(self) -> list[str]:
        return [*self.left.columns(), *self.right.columns()]

    def to_sa(self, table: sa.Table) -> Any:
        return _SA_OPS[self.op](self.left.to_sa(table), self.right.to_sa(table))


class Lit(Expr):
    def __init__(self, value: Any) -> None:
        self.value = value.value if isinstance(value, Enum) else value

    def key(self) -> str:
        return repr(self.value)

    def columns(self) -> list[str]:
        return []

    def to_sa(self, table: sa.Table) -> Any:
        return sa.literal(self.value)


class Desc(Expr):
    def __init__(self, inner: Expr) -> None:
        self.inner = inner

    def key(self) -> str:
        return f"{self.inner.key()} DESC"

    def columns(self) -> list[str]:
        return self.inner.columns()

    def to_sa(self, table: sa.Table) -> Any:
        return self.inner.to_sa(table).desc()


class Func(Expr):
    def __init__(self, name: str, args: tuple[Expr, ...]) -> None:
        self.name, self.args = name, args

    def key(self) -> str:
        return f"{self.name}({', '.join(a.key() for a in self.args)})"

    def columns(self) -> list[str]:
        return [c for a in self.args for c in a.columns()]

    def to_sa(self, table: sa.Table) -> Any:
        return getattr(sa.func, self.name)(*(a.to_sa(table) for a in self.args))


class _Fn:
    """`fn.lower(User.email)` - assumed syntax for function expressions (A4)."""

    def __getattr__(self, name: str) -> Callable[..., Func]:
        return lambda *args: Func(name, tuple(_wrap(a) for a in args))


fn = _Fn()


class ColRef(Expr):
    def __init__(self, name: str) -> None:
        self.name = name

    def key(self) -> str:
        return self.name

    def columns(self) -> list[str]:
        return [self.name]

    def to_sa(self, table: sa.Table) -> Any:
        return table.c[self.name]


# --------------------------------------------------------------------------- field specifiers
class ColumnSpec(Expr):
    def __init__(
        self,
        *,
        kind: str = "col",
        length: int | None = None,
        unique: bool = False,
        server_default: str | None = None,
        renamed_from: str | None = None,
        target: Callable[[], type] | None = None,
        primary_key: bool = False,
    ) -> None:
        self.kind = kind
        self.length = length
        self.unique = unique
        self.server_default = server_default
        self.renamed_from = renamed_from
        self.target = target
        self.primary_key = primary_key or kind == "pk"
        self.name = ""
        self.owner: type | None = None

    def __set_name__(self, owner: type, name: str) -> None:
        self.owner, self.name = owner, name

    def key(self) -> str:
        return self.name

    def columns(self) -> list[str]:
        return [self.name]

    def to_sa(self, table: sa.Table) -> Any:
        return table.c[self.name]


class EmbeddedSpec:
    def __init__(self, prefix: str) -> None:
        self.prefix = prefix
        self.name = ""

    def __set_name__(self, owner: type, name: str) -> None:
        self.name = name

    def path(self, field: ColumnSpec) -> ColRef:
        return ColRef(self.prefix + field.name)


def column(
    *,
    length: int | None = None,
    unique: bool = False,
    server_default: str | None = None,
    renamed_from: str | None = None,
    primary_key: bool = False,
) -> Any:
    return ColumnSpec(
        length=length,
        unique=unique,
        server_default=server_default,
        renamed_from=renamed_from,
        primary_key=primary_key,
    )


def pk(*, generated: str = "uuid7", renamed_from: str | None = None) -> Any:
    return ColumnSpec(kind="pk", renamed_from=renamed_from)


def fk(target: Callable[[], type], *, renamed_from: str | None = None) -> Any:
    return ColumnSpec(kind="fk", target=target, renamed_from=renamed_from)


def version_column() -> Any:
    return ColumnSpec(kind="version", server_default="1")


def embedded(*, prefix: str) -> Any:
    return EmbeddedSpec(prefix)


def server_now() -> str:
    return "now()"


def _fill_columns(cls: type) -> None:
    """Give every `Col[...]` field without a specifier a plain `ColumnSpec` (the real `Col`
    is a descriptor, so `Order.quantity` exists on the class whether or not it has a default)."""
    names = annotationlib.get_annotations(cls, format=annotationlib.Format.STRING)
    for attr, text in names.items():
        if text.startswith("Col[") and attr not in cls.__dict__:
            spec = ColumnSpec()
            setattr(cls, attr, spec)
            spec.__set_name__(cls, attr)


def value[C: type](cls: C) -> C:
    _fill_columns(cls)
    return cls


class Check:
    def __init__(self, expr: Callable[[], Expr], *, name: str | None = None) -> None:
        self.expr, self.name = expr, name


class Index:
    def __init__(
        self,
        exprs: Callable[[], tuple[Expr, ...]],
        *,
        where: Callable[[], Expr] | None = None,
        unique: bool = False,
        name: str | None = None,
    ) -> None:
        self.exprs, self.where, self.unique, self.name = exprs, where, unique, name


class Unique:
    def __init__(self, cols: Callable[[], tuple[Expr, ...]], *, name: str | None = None) -> None:
        self.cols, self.name = cols, name


class Entity:
    __platina_table__: str
    __platina_renamed_from__: str | None
    __platina_partition_by__: str | None

    def __init_subclass__(
        cls,
        *,
        table: str,
        renamed_from: str | None = None,
        aggregate_root: bool = False,
        partition_by: str | None = None,
    ) -> None:
        cls.__platina_table__ = table
        cls.__platina_renamed_from__ = renamed_from
        cls.__platina_partition_by__ = partition_by
        _fill_columns(cls)


# --------------------------------------------------------------------------- conversion
VERSION_FUNCTION = "platina_bump_version"
VERSION_BODY_V1 = """
BEGIN
  IF NEW.version IS NOT DISTINCT FROM OLD.version THEN
    NEW.version := OLD.version + 1;
  END IF;
  RETURN NEW;
END;
"""
# A changed body (as a Platina upgrade could ship): also refuses a version going backwards.
VERSION_BODY_V2 = """
BEGIN
  IF NEW.version IS NOT DISTINCT FROM OLD.version THEN
    NEW.version := OLD.version + 1;
  ELSIF NEW.version < OLD.version THEN
    RAISE EXCEPTION 'version went backwards on %', TG_TABLE_NAME;
  END IF;
  RETURN NEW;
END;
"""

NAMING_CONVENTION = {
    "pk": "pk_%(table_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
}


def _name(prefix: str, table: str, expr_key: str, cols: list[str], naming: str) -> str:
    if naming == "hash":
        return f"{prefix}_{table}_{hashlib.sha1(expr_key.encode()).hexdigest()[:8]}"
    seen = list(dict.fromkeys(cols))
    return f"{prefix}_{table}_{'_'.join(seen)}"


def _unwrap(annotation: Any) -> tuple[Any, bool]:
    """Col[X] -> (X without None, nullable)."""
    inner = get_args(annotation)[0]
    origin = get_origin(inner)
    if origin in (Union, types.UnionType):
        args = [a for a in get_args(inner) if a is not type(None)]
        return args[0], True
    return inner, False


def _sa_type(py: Any, spec: ColumnSpec) -> sa.types.TypeEngine[Any]:
    if get_origin(py) is Id or spec.kind in ("pk", "fk"):
        return sa.UUID()
    if py is str:
        return sa.String(spec.length) if spec.length else sa.Text()
    if py is Decimal:
        return sa.Numeric(12, 2)
    if py is int:
        return sa.Integer()
    if py is datetime:
        return sa.DateTime(timezone=True)
    if py is Xid8:
        return XID8()
    if py is Json:
        return postgresql.JSONB()
    if isinstance(py, type) and issubclass(py, Enum):
        return sa.Text()
    raise TypeError(f"no mapping for {py!r}")


def _table_columns(cls: type) -> list[sa.Column[Any]]:
    annotations = annotationlib.get_annotations(cls, format=annotationlib.Format.VALUE)
    cols: list[sa.Column[Any]] = []
    for attr, annotation in annotations.items():
        if get_origin(annotation) is not Col:
            continue
        spec = cls.__dict__.get(attr)
        py, nullable = _unwrap(annotation)
        if isinstance(spec, EmbeddedSpec):
            value_annotations = annotationlib.get_annotations(py, format=annotationlib.Format.VALUE)
            for field in value_annotations:
                field_spec = py.__dict__.get(field)
                field_py, field_nullable = _unwrap(value_annotations[field])
                field_spec = field_spec if isinstance(field_spec, ColumnSpec) else ColumnSpec()
                cols.append(
                    sa.Column(
                        spec.prefix + field,
                        _sa_type(field_py, field_spec),
                        nullable=nullable or field_nullable,
                    )
                )
            continue
        spec = spec if isinstance(spec, ColumnSpec) else ColumnSpec()
        args: list[Any] = []
        if spec.kind == "fk" and spec.target is not None:
            target = spec.target()
            args.append(sa.ForeignKey(f"{target.__platina_table__}.id"))
        info = {"renamed_from": spec.renamed_from} if spec.renamed_from else {}
        cols.append(
            sa.Column(
                attr,
                _sa_type(py, spec),
                *args,
                primary_key=spec.primary_key,
                nullable=False if spec.primary_key else nullable,
                unique=spec.unique or None,
                server_default=sa.text(spec.server_default) if spec.server_default else None,
                info=info,
            )
        )
    return cols


def to_metadata(
    *entities: type,
    naming: str = "columns",
    version_body: str = VERSION_BODY_V1,
) -> sa.MetaData:
    """Seal: evaluate every lambda and build the `MetaData` Alembic compares (A7)."""
    md = sa.MetaData(naming_convention=NAMING_CONVENTION)
    triggers: dict[str, str] = {}
    for cls in entities:
        tname = cls.__platina_table__  # type: ignore[attr-defined]
        kwargs: dict[str, Any] = {}
        if cls.__platina_partition_by__:  # type: ignore[attr-defined]
            kwargs["postgresql_partition_by"] = cls.__platina_partition_by__  # type: ignore[attr-defined]
        info = (
            {"renamed_from": cls.__platina_renamed_from__}  # type: ignore[attr-defined]
            if cls.__platina_renamed_from__  # type: ignore[attr-defined]
            else {}
        )
        table = sa.Table(tname, md, *_table_columns(cls), info=info, **kwargs)
        if any(isinstance(s, ColumnSpec) and s.kind == "version" for s in vars(cls).values()):
            triggers[tname] = f"platina_version_{tname}"
        meta = cls.__dict__.get("Meta")
        for check in getattr(meta, "checks", ()):
            expr = check.expr()
            name = check.name or _name("ck", tname, expr.key(), expr.columns(), naming)
            table.append_constraint(sa.CheckConstraint(expr.to_sa(table), name=name))
        for uq in getattr(meta, "uniques", ()):
            exprs = uq.cols()
            key = ",".join(e.key() for e in exprs)
            cols = [c for e in exprs for c in e.columns()]
            name = uq.name or _name("uq", tname, key, cols, naming)
            table.append_constraint(
                sa.UniqueConstraint(*(e.to_sa(table) for e in exprs), name=name)
            )
        for ix in getattr(meta, "indexes", ()):
            exprs = ix.exprs()
            where = ix.where() if ix.where else None
            key = ",".join(e.key() for e in exprs) + (f" WHERE {where.key()}" if where else "")
            cols = [c for e in exprs for c in e.columns()]
            name = ix.name or _name("ix", tname, key, cols, naming)
            ix_kwargs: dict[str, Any] = {}
            if where is not None:
                ix_kwargs["postgresql_where"] = where.to_sa(table)
            sa.Index(name, *(e.to_sa(table) for e in exprs), unique=ix.unique, **ix_kwargs)
            table.indexes  # noqa: B018 - the Index attached itself to the table
    md.info["platina_version_triggers"] = triggers
    md.info["platina_version_body"] = version_body if triggers else None
    return md


def version_ddl(md: sa.MetaData) -> list[str]:
    """The DDL the registry intends for `version` triggers (used for the reference schema)."""
    body = md.info["platina_version_body"]
    if body is None:
        return []
    stmts = [
        f"CREATE FUNCTION {VERSION_FUNCTION}() RETURNS trigger LANGUAGE plpgsql "
        f"AS $platina${body}$platina$"
    ]
    for table, trigger in sorted(md.info["platina_version_triggers"].items()):
        stmts.append(
            f"CREATE TRIGGER {trigger} BEFORE UPDATE ON {table} "
            f"FOR EACH ROW EXECUTE FUNCTION {VERSION_FUNCTION}()"
        )
    return stmts
