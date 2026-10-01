"""``CREATE TABLE`` aus dem Modell rekonstruieren.

Gemeinsam genutzt von der HTML-Seite (DDL-Abschnitt) und der KI-Ausgabe
(``schema.sql``).
"""

from __future__ import annotations

from .graph import Graph
from .model import Catalog, DbObject


# DacFx-Eigenschaftswerte -> T-SQL
_FK_ACTION = {"Cascade": "CASCADE", "SetNull": "SET NULL",
              "SetDefault": "SET DEFAULT", "NoAction": "NO ACTION"}


def _oneline(text: str) -> str:
    return " ".join(text.split())


def create_table(obj: DbObject, catalog: Catalog, graph: Graph,
                 comments: bool = False) -> str:
    """DDL einer Tabelle. Mit ``comments`` steht die Beschreibung jeder
    Spalte als ``-- …`` hinter ihrer Zeile."""
    parts: list[tuple[str, str]] = []   # (Zeile, Kommentar)
    for col in obj.columns:
        if col.computed and col.default:   # der Ausdruck steht im Modell als default
            parts.append((f"    [{col.name}] AS {col.default}",
                          _oneline(col.description or "") if comments else ""))
            continue
        piece = f"    [{col.name}] {col.type or ''}".rstrip()
        if col.collation:
            piece += f" COLLATE {col.collation}"
        if col.identity:
            piece += f" IDENTITY({col.identity})"
        if col.default:
            piece += f" DEFAULT {col.default}"
        piece += "" if col.nullable else " NOT NULL"
        parts.append((piece, _oneline(col.description or "") if comments else ""))
    for index in obj.indexes:
        if index.kind not in ("primarykey", "unique"):
            continue
        name = f"CONSTRAINT [{index.name}] " if index.name else ""
        cols = ", ".join(f"[{c}]" for c in index.columns)
        if index.kind == "primarykey":
            clustered = " CLUSTERED" if index.clustered else ""
            parts.append((f"    {name}PRIMARY KEY{clustered} ({cols})", ""))
        else:
            parts.append((f"    {name}UNIQUE ({cols})", ""))
    for fk in graph.fk_out.get(obj.id, []):
        cols = ", ".join(f"[{c}]" for c in fk.columns)
        ref_cols = ", ".join(f"[{c}]" for c in fk.ref_columns)
        ref_obj = catalog.objects.get(fk.ref_table)
        if ref_obj:
            ref = ref_obj.qualified
        else:   # Ziel in einer nicht geladenen Datenbank
            bare = fk.ref_table.split("|", 1)[-1].replace("[", "").replace("]", "")
            ref = f"{fk.ref_external_db}.{bare}" if fk.ref_external_db else bare
        piece = (f"    CONSTRAINT [{fk.name}] FOREIGN KEY ({cols}) "
                 f"REFERENCES {ref} ({ref_cols})")
        for action, value in (("DELETE", fk.on_delete), ("UPDATE", fk.on_update)):
            if value and value != "NoAction":
                piece += f" ON {action} {_FK_ACTION.get(value, value)}"
        parts.append((piece, ""))
    for check in obj.checks:
        name = f"CONSTRAINT [{check.name}] " if check.name else ""
        parts.append((f"    {name}CHECK ({check.expression})", ""))

    lines = [f"CREATE TABLE {obj.display} ("]
    for i, (piece, comment) in enumerate(parts):
        line = piece + ("," if i < len(parts) - 1 else "")
        lines.append(f"{line}  -- {comment}" if comment else line)
    lines.append(");")
    for index in obj.indexes:
        if index.kind != "index":
            continue
        unique = "UNIQUE " if index.unique else ""
        clustered = "CLUSTERED " if index.clustered else ""
        cols = ", ".join(f"[{c}]" for c in index.columns)
        stmt = (f"\nCREATE {unique}{clustered}INDEX [{index.name}] "
                f"ON {obj.display} ({cols})")
        if index.included:
            stmt += " INCLUDE (" + ", ".join(f"[{c}]" for c in index.included) + ")"
        lines.append(stmt + ";")
    return "\n".join(lines)
