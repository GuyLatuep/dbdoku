"""``model.xml`` -> :class:`~dbdoku.model.Database`."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET

from .dacpac import (
    NS,
    DacpacReader,
    annotation,
    flag,
    prop,
    rel_elements,
    rel_references,
)
from .model import (
    Check,
    Column,
    Database,
    DbObject,
    ForeignKey,
    Index,
    Parameter,
    Ref,
    split_name,
)

# Elementtyp -> (Objektart, Routinenunterart)
ROUTINES = {
    "SqlProcedure": ("procedure", "procedure"),
    "SqlScalarFunction": ("function", "scalar"),
    "SqlInlineTableValuedFunction": ("function", "inline_tvf"),
    "SqlMultiStatementTableValuedFunction": ("function", "mstvf"),
    "SqlDmlTrigger": ("trigger", "trigger"),
}

# Typen mit Laengenangabe bzw. mit Genauigkeit/Nachkommastellen.
_SIZED = {
    "binary", "char", "nchar", "nvarchar", "varbinary", "varchar",
}
_PRECISE = {
    "decimal", "numeric", "float", "datetime2", "datetimeoffset", "time",
}

_DYNAMIC_SQL = re.compile(
    r"\b(?:sp_executesql|exec(?:ute)?\s*\(|exec(?:ute)?\s+@)", re.IGNORECASE
)

_TRIGGER_EVENTS = [("IsInsertTrigger", "INSERT"),
                   ("IsUpdateTrigger", "UPDATE"),
                   ("IsDeleteTrigger", "DELETE")]


def qualify(parts: list[str]) -> str:
    """``['dbo', 'Person']`` -> ``'[dbo].[Person]'``."""
    return ".".join("[" + p.replace("]", "]]") + "]" for p in parts)


def parse_ref(ref: ET.Element) -> Ref | None:
    """Ein ``<References>``-Element normalisieren.

    Liefert ``None`` fuer eingebaute Typen und Systembezeichner, die im
    Abhaengigkeitsgraph nur Rauschen waeren.
    """
    name = ref.get("Name")
    if not name:
        return None
    source = ref.get("ExternalSource")
    if source == "BuiltIns":
        return None

    external_db = None
    if "|" in name:
        # Fremddatenbank: '[Fremd-DB]|[dbo].[Kunde].[Spalte]'
        db_part, name = name.split("|", 1)
        db_parts = split_name(db_part)
        external_db = db_parts[0] if db_parts else db_part
    elif source:
        external_db = source[:-7] if source.endswith(".dacpac") else source

    parts = split_name(name)
    if len(parts) < 2:
        return None
    return Ref(
        target=qualify(parts[:2]),
        column=parts[2] if len(parts) > 2 else None,
        external_db=external_db,
        source=source,
    )


def parse_refs(el: ET.Element, *names: str) -> list[Ref]:
    out: list[Ref] = []
    for name in names:
        for ref in rel_references(el, name):
            if (parsed := parse_ref(ref)) is not None:
                out.append(parsed)
    return out


def type_of(owner: ET.Element) -> str:
    """Datentyp aus der ``TypeSpecifier``- bzw. ``Type``-Relationship."""
    specs = rel_elements(owner, "TypeSpecifier") or rel_elements(owner, "Type")
    if not specs:
        # Parameter mit benutzerdefiniertem Tabellentyp referenzieren direkt.
        for ref in rel_references(owner, "Type"):
            parts = split_name(ref.get("Name") or "")
            if parts:
                return ".".join(parts)
        return ""
    spec = specs[0]

    base = ""
    for ref in rel_references(spec, "Type"):
        parts = split_name(ref.get("Name") or "")
        base = ".".join(parts) if len(parts) > 1 else (parts[0] if parts else "")
        break
    if not base:
        return ""

    bare = base.split(".")[-1].lower()
    if flag(spec, "IsMax"):
        return f"{base}(max)"
    length = prop(spec, "Length")
    if length and bare in _SIZED:
        return f"{base}({length})"
    precision, scale = prop(spec, "Precision"), prop(spec, "Scale")
    if precision and bare in _PRECISE:
        return f"{base}({precision},{scale})" if scale else f"{base}({precision})"
    if scale and not precision and bare in _PRECISE:
        return f"{base}({scale})"
    if length:
        return f"{base}({length})"
    return base


def column_of(el: ET.Element) -> Column:
    parts = split_name(el.get("Name") or "")
    computed = el.get("Type") == "SqlComputedColumn"
    col = Column(
        name=parts[-1] if parts else "",
        type=type_of(el),
        nullable=(prop(el, "IsNullable") or "True").lower() == "true",
        collation=prop(el, "Collation"),
        computed=computed,
        rowguid=flag(el, "IsRowGuidColumn"),
        refs=parse_refs(el, "ExpressionDependencies"),
    )
    if flag(el, "IsIdentity"):
        seed = prop(el, "IdentitySeed") or "1"
        inc = prop(el, "IdentityIncrement") or "1"
        col.identity = f"{seed},{inc}"
    if computed and (expr := prop(el, "ExpressionScript")):
        col.type = col.type or "berechnet"
        col.default = expr
    return col


def indexed_columns(el: ET.Element) -> list[str]:
    """Spaltennamen aus ``ColumnSpecifications`` bzw. ``Columns``."""
    out: list[str] = []
    for spec in rel_elements(el, "ColumnSpecifications"):
        for ref in rel_references(spec, "Column"):
            parts = split_name(ref.get("Name") or "")
            if parts:
                out.append(parts[-1])
    if not out:
        for ref in rel_references(el, "Columns"):
            parts = split_name(ref.get("Name") or "")
            if parts:
                out.append(parts[-1])
    return out


def _target(el: ET.Element, *names: str) -> str | None:
    """Objekt-Id aus der ersten passenden Relationship."""
    for name in names:
        for ref in rel_references(el, name):
            parsed = parse_ref(ref)
            if parsed is not None:
                return parsed.target
    return None


def source_of(el: ET.Element) -> tuple[str, str]:
    """Kopftext und Rumpf eines Objekts als ``(header, body)``.

    Prozeduren, Sichten und Trigger tragen ihren Rumpf direkt; bei Funktionen
    steckt er eine Ebene tiefer in der ``FunctionBody``-Relationship. Der Kopf
    (``CREATE FUNCTION … AS`` samt vorangehender Kommentare) steht in beiden
    Faellen in der ``SysCommentsObjectAnnotation`` des rumpftragenden Elements,
    nicht in einer Property.
    """
    impls = rel_elements(el, "FunctionBody")
    src = impls[0] if impls else el
    body = prop(src, "BodyScript") or prop(src, "QueryScript") or ""
    ann = annotation(src, "SysCommentsObjectAnnotation")
    header = prop(ann, "HeaderContents") if ann is not None else None
    if header is None:  # aeltere Modelle schreiben den Kopf als Property
        header = prop(src, "HeaderContents") or ""
    return header, body


class Extractor:
    def __init__(self) -> None:
        self.db = Database()
        # Nachgelagert zu verdrahten: Constraints koennen vor ihrer Tabelle stehen.
        self._indexes: list[tuple[str, Index]] = []
        self._checks: list[tuple[str, Check]] = []
        self._defaults: list[tuple[str, str, str]] = []       # tabelle, spalte, ausdruck
        self._descriptions: list[tuple[str, str | None, str]] = []  # ziel, spalte, text

    # -- Einstiegspunkt ----------------------------------------------------

    def run(self, path: str) -> Database:
        with DacpacReader(path) as reader:
            meta = reader.metadata()
            self.db.name = meta.get("Name", "")
            self.db.version = meta.get("Version", "")
            self.db.created = meta.get("Created", "")
            self._read_header(reader)
            for el in reader.iter_elements():
                self._element(el)
            self.sanitized_refs = reader.sanitized_refs
        self._wire()
        return self.db

    def _read_header(self, reader: DacpacReader) -> None:
        header = reader.model_header()
        if header is None:
            return
        for data in header.findall(f"{NS}CustomData"):
            if data.get("Category") == "CompatibilityMode":
                for m in data.findall(f"{NS}Metadata"):
                    if m.get("Name") == "CompatibilityMode":
                        self.db.compatibility = m.get("Value") or ""

    # -- ein Top-Level-Element --------------------------------------------

    def _element(self, el: ET.Element) -> None:
        kind = el.get("Type") or ""
        handler = getattr(self, f"_on_{kind}", None)
        if handler is not None:
            handler(el)

    def _new(self, el: ET.Element, kind: str) -> DbObject:
        qname = el.get("Name") or ""
        parts = split_name(qname)
        # Tabellentypen leben in SQL Server in einem eigenen Namensraum und duerfen
        # heissen wie eine Tabelle. Sie bekommen deshalb einen eigenen Schluessel;
        # unqualifizierte Referenzen zeigen weiterhin auf die Relation.
        oid = f"{qname}#type" if kind == "tabletype" else qname
        obj = DbObject(
            id=oid,
            kind=kind,
            schema=parts[0] if len(parts) > 1 else "",
            name=parts[-1] if parts else qname,
        )
        self.db.objects[oid] = obj
        if obj.schema:
            self.db.schemas.add(obj.schema)
        return obj

    # -- Tabellen und Sichten ---------------------------------------------

    def _on_SqlTable(self, el: ET.Element) -> None:
        obj = self._new(el, "table")
        obj.columns = [column_of(c) for c in rel_elements(el, "Columns")]

    def _on_SqlView(self, el: ET.Element) -> None:
        obj = self._new(el, "view")
        obj.columns = [column_of(c) for c in rel_elements(el, "Columns")]
        obj.header, obj.body = source_of(el)
        obj.refs = parse_refs(el, "QueryDependencies", "BodyDependencies")
        for col in obj.columns:
            obj.refs.extend(col.refs)

    def _on_SqlTableType(self, el: ET.Element) -> None:
        obj = self._new(el, "tabletype")
        obj.columns = [column_of(c) for c in rel_elements(el, "Columns")]

    # -- Routinen ----------------------------------------------------------

    def _routine(self, el: ET.Element, kind: str, subtype: str) -> None:
        obj = self._new(el, kind)
        obj.routine_type = subtype
        obj.header, obj.body = source_of(el)
        obj.refs = parse_refs(el, "BodyDependencies", "ExpressionDependencies",
                              "QueryDependencies", "DynamicObjects")
        obj.dynamic_sql = bool(_DYNAMIC_SQL.search(obj.body))

        for p in rel_elements(el, "Parameters"):
            parts = split_name(p.get("Name") or "")
            obj.parameters.append(Parameter(
                name=parts[-1] if parts else "",
                type=type_of(p),
                output=flag(p, "IsOutput"),
                readonly=flag(p, "IsReadOnly"),
                default=prop(p, "DefaultExpressionScript"),
            ))

        if kind == "function":
            obj.returns = type_of(el) or None
            if subtype in ("inline_tvf", "mstvf"):
                obj.columns = [column_of(c) for c in rel_elements(el, "Columns")]
                var = prop(el, "ReturnTableVariable")
                obj.returns = f"TABLE {var}" if var else "TABLE"
            impls = rel_elements(el, "FunctionBody")
            if impls and impls[0].get("Type") == "SqlClrFunctionImplementation":
                obj.clr = True
        if kind == "trigger":
            obj.trigger_on = _target(el, "Parent")
            obj.trigger_events = [label for key, label in _TRIGGER_EVENTS if flag(el, key)]

        # CLR-Routinen haben keinen T-SQL-Body, sondern eine Assembly-Bindung.
        impls = rel_elements(el, "FunctionBody")
        binding = impls[0] if impls else el
        if not obj.body and (cls := prop(binding, "ClassName")):
            method = prop(binding, "MethodName") or ""
            obj.body = f"-- CLR: {cls}.{method}"
            obj.clr = True

    def _on_SqlProcedure(self, el: ET.Element) -> None:
        self._routine(el, *ROUTINES["SqlProcedure"])

    def _on_SqlScalarFunction(self, el: ET.Element) -> None:
        self._routine(el, *ROUTINES["SqlScalarFunction"])

    def _on_SqlInlineTableValuedFunction(self, el: ET.Element) -> None:
        self._routine(el, *ROUTINES["SqlInlineTableValuedFunction"])

    def _on_SqlMultiStatementTableValuedFunction(self, el: ET.Element) -> None:
        self._routine(el, *ROUTINES["SqlMultiStatementTableValuedFunction"])

    def _on_SqlDmlTrigger(self, el: ET.Element) -> None:
        self._routine(el, *ROUTINES["SqlDmlTrigger"])

    # -- Constraints und Indizes ------------------------------------------

    def _key(self, el: ET.Element, kind: str) -> None:
        table = _target(el, "DefiningTable", "IndexedObject")
        if not table:
            return
        parts = split_name(el.get("Name") or "")
        self._indexes.append((table, Index(
            name=parts[-1] if len(parts) > 1 else None,
            columns=indexed_columns(el),
            unique=kind != "index" or flag(el, "IsUnique"),
            clustered=flag(el, "IsClustered"),
            kind=kind,
        )))

    def _on_SqlPrimaryKeyConstraint(self, el: ET.Element) -> None:
        self._key(el, "primarykey")

    def _on_SqlUniqueConstraint(self, el: ET.Element) -> None:
        self._key(el, "unique")

    def _on_SqlIndex(self, el: ET.Element) -> None:
        table = _target(el, "IndexedObject", "DefiningTable")
        if not table:
            return
        parts = split_name(el.get("Name") or "")
        included = []
        for ref in rel_references(el, "IncludedColumns"):
            cols = split_name(ref.get("Name") or "")
            if cols:
                included.append(cols[-1])
        self._indexes.append((table, Index(
            name=parts[-1] if parts else None,
            columns=indexed_columns(el),
            included=included,
            unique=flag(el, "IsUnique"),
            clustered=flag(el, "IsClustered"),
            kind="index",
        )))

    def _on_SqlForeignKeyConstraint(self, el: ET.Element) -> None:
        table = _target(el, "DefiningTable")
        if not table:
            return
        ref_table, ref_db = None, None
        for ref in rel_references(el, "ForeignTable"):
            if (parsed := parse_ref(ref)) is not None:
                ref_table, ref_db = parsed.target, parsed.external_db
                break
        if not ref_table:
            return

        def cols(rel: str) -> list[str]:
            out = []
            for r in rel_references(el, rel):
                parts = split_name((r.get("Name") or "").split("|")[-1])
                if parts:
                    out.append(parts[-1])
            return out

        parts = split_name(el.get("Name") or "")
        self.db.foreign_keys.append(ForeignKey(
            name=parts[-1] if parts else "(unbenannt)",
            table=table,
            columns=cols("Columns"),
            ref_table=ref_table,
            ref_columns=cols("ForeignColumns"),
            on_delete=prop(el, "OnDeleteAction"),
            on_update=prop(el, "OnUpdateAction"),
            ref_external_db=ref_db,
        ))

    def _on_SqlCheckConstraint(self, el: ET.Element) -> None:
        table = _target(el, "DefiningTable")
        if not table:
            return
        parts = split_name(el.get("Name") or "")
        self._checks.append((table, Check(
            name=parts[-1] if len(parts) > 1 else None,
            expression=prop(el, "CheckExpressionScript") or "",
        )))

    def _on_SqlDefaultConstraint(self, el: ET.Element) -> None:
        expr = prop(el, "DefaultExpressionScript")
        if not expr:
            return
        for ref in rel_references(el, "ForColumn"):
            parts = split_name(ref.get("Name") or "")
            if len(parts) >= 3:
                self._defaults.append((qualify(parts[:2]), parts[-1], expr))

    # -- Beschreibungen und Sonstiges -------------------------------------

    def _on_SqlExtendedProperty(self, el: ET.Element) -> None:
        parts = split_name(el.get("Name") or "")
        if not parts or parts[-1] != "MS_Description":
            return
        value = (prop(el, "Value") or "").strip()
        # Der Wert ist ein T-SQL-Literal: N'…' bzw. '…'
        if value.startswith(("N'", "n'")):
            value = value[1:]
        if len(value) >= 2 and value[0] == "'" and value[-1] == "'":
            value = value[1:-1].replace("''", "'")
        if not value:
            return
        for ref in rel_references(el, "Host"):
            host = split_name(ref.get("Name") or "")
            if len(host) >= 3:
                self._descriptions.append((qualify(host[:2]), host[2], value))
            elif len(host) == 2:
                self._descriptions.append((qualify(host), None, value))
            break

    def _on_SqlSchema(self, el: ET.Element) -> None:
        parts = split_name(el.get("Name") or "")
        if parts:
            self.db.schemas.add(parts[0])

    def _on_SqlAssembly(self, el: ET.Element) -> None:
        parts = split_name(el.get("Name") or "")
        if parts:
            self.db.assemblies.append(parts[-1])

    def _on_SqlDatabaseOptions(self, el: ET.Element) -> None:
        self.db.collation = prop(el, "Collation") or ""

    # -- Nachbearbeitung ---------------------------------------------------

    def _wire(self) -> None:
        objects = self.db.objects

        for table, index in self._indexes:
            if (obj := objects.get(table)) is not None:
                obj.indexes.append(index)
        for table, check in self._checks:
            if (obj := objects.get(table)) is not None:
                obj.checks.append(check)

        by_column = {
            (oid, col.name): col
            for oid, obj in objects.items()
            for col in obj.columns
        }
        for table, column, expr in self._defaults:
            if (col := by_column.get((table, column))) is not None:
                col.default = expr
        for target, column, text in self._descriptions:
            if column is None:
                if (obj := objects.get(target)) is not None:
                    obj.description = text
            elif (col := by_column.get((target, column))) is not None:
                col.description = text
            elif (obj := objects.get(target)) is not None and column.startswith("@"):
                for param in obj.parameters:
                    if param.name == column:
                        break

        # Fremddatenbanken einsammeln.
        for obj in objects.values():
            for ref in obj.refs:
                if ref.external_db:
                    self.db.external_dbs.setdefault(ref.external_db, ref.source or "")
        for fk in self.db.foreign_keys:
            if fk.ref_external_db:
                self.db.external_dbs.setdefault(fk.ref_external_db, "")

        # Indizes stabil sortieren: Primaerschluessel, Unique, dann Rest.
        order = {"primarykey": 0, "unique": 1, "index": 2}
        for obj in objects.values():
            obj.indexes.sort(key=lambda i: (order.get(i.kind, 3), (i.name or "").lower()))
        self.db.foreign_keys.sort(key=lambda f: f.name.lower())


def extract(path: str) -> Database:
    return Extractor().run(path)
