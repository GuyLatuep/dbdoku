"""Erzeugt eine kompakte Markdown-Fassung des Katalogs für KI-Assistenten.

Gleicher Inhalt wie die HTML-Seiten, aber ohne Markup, Navigation und
Diagramme — und mit englischen Beschriftungen, weil auch T-SQL englisch ist.
Der Ordner ist zum Durchsuchen mit Grep und zum Lesen Datei für Datei gedacht
(Claude Code), die Dateien ``schema.sql``, ``relations.md`` und ``index.md``
je Datenbank auch zum Hochladen in ein Projekt.

    llm/
      README.md, llms.txt
      <DB>/index.md, schema.sql, relations.md
      <DB>/tables|views|procedures|functions|triggers|types/<schema.name>.md
"""

from __future__ import annotations

from pathlib import Path

from . import ddl
from .graph import Graph
from .model import Catalog, Database, DbObject
from .render import NAV, assign_paths

# Objektart -> (Einzahl, Mehrzahl, Unterordner)
KINDS_EN = {
    "table": ("Table", "Tables", "tables"),
    "view": ("View", "Views", "views"),
    "procedure": ("Procedure", "Procedures", "procedures"),
    "function": ("Function", "Functions", "functions"),
    "trigger": ("Trigger", "Triggers", "triggers"),
    "tabletype": ("Table type", "Table types", "types"),
}

ROUTINE_TYPES = {"scalar": "scalar function", "inline_tvf": "inline table-valued function",
                 "mstvf": "multi-statement table-valued function"}

ACCESS_LEGEND = "S = select, I = insert, U = update, D = delete"


def oneline(text: str | None) -> str:
    return " ".join((text or "").split())


def cell(text: str | None) -> str:
    """Inhalt einer Markdown-Tabellenzelle: einzeilig, ``|`` maskiert."""
    return oneline(text).replace("|", "\\|")


def md_table(headers: list[str], rows: list[list[str]]) -> str:
    lines = ["| " + " | ".join(headers) + " |",
             "|" + "---|" * len(headers)]
    lines += ["| " + " | ".join(row) + " |" for row in rows]
    return "\n".join(lines)


def fenced(sql: str, lang: str = "sql") -> str:
    fence = "```"
    while fence in sql:
        fence += "`"
    return f"{fence}{lang}\n{sql.rstrip()}\n{fence}"


def _bare(ref_table: str) -> str:
    return ref_table.split("|", 1)[-1].replace("[", "").replace("]", "")


class LlmWriter:
    def __init__(self, catalog: Catalog, graph: Graph, outdir: Path,
                 title: str = "Database catalog") -> None:
        self.catalog = catalog
        self.graph = graph
        self.out = outdir
        self.title = title
        self.folders, self.paths = assign_paths(
            catalog, {k: KINDS_EN[k][2] for k in NAV}, ".md")
        self.home = ""   # Datenbank der gerade erzeugten Datei

    # -- Verweise ----------------------------------------------------------

    def label(self, oid: str) -> str:
        obj = self.catalog.objects.get(oid)
        if obj is None:
            return _bare(oid)
        return obj.display if oid.startswith(self.home + "|") else obj.qualified

    def link(self, oid: str, depth: int) -> str:
        """Relativer Markdown-Verweis; Objekte ohne eigene Datei als Code."""
        path = self.paths.get(oid)
        text = self.label(oid)
        if path is None:
            return f"`{text}`"
        own = self.folders.get(self.home, "") + "/"
        if path.startswith(own):   # gleiche Datenbank: kürzerer Pfad, spart Tokens
            return f"[{text}]({'../' * (depth - 1)}{path[len(own):]})"
        return f"[{text}]({'../' * depth}{path})"

    def kind_of(self, oid: str) -> str:
        obj = self.catalog.objects.get(oid)
        return KINDS_EN[obj.kind][0].lower() if obj else ""

    # -- Kopf --------------------------------------------------------------

    def _head(self, obj: DbObject, facts: list[str]) -> list[str]:
        lines = [f"# {KINDS_EN[obj.kind][0]} {obj.qualified}", "",
                 f"- database: {obj.db}", f"- schema: {obj.schema}"]
        if obj.description:
            lines.append(f"- description: {oneline(obj.description)}")
        lines += [f"- {fact}" for fact in facts]
        return lines

    @staticmethod
    def _section(title: str, body: str) -> list[str]:
        return ["", f"## {title}", "", body] if body else []

    # -- Spalten -----------------------------------------------------------

    def _columns(self, obj: DbObject, depth: int) -> str:
        if not obj.columns:
            return ""
        keys: dict[str, list[str]] = {}
        for index in obj.indexes:
            mark = {"primarykey": "PK", "unique": "UQ"}.get(index.kind, "IX")
            for col in index.columns:
                if mark not in keys.setdefault(col, []):
                    keys[col].append(mark)
        for fk in self.graph.fk_out.get(obj.id, []):
            for i, col in enumerate(fk.columns):
                target = fk.ref_columns[i] if i < len(fk.ref_columns) else ""
                if fk.ref_table in self.catalog.objects:
                    ref = f"{self.link(fk.ref_table, depth)}.{target}"
                else:
                    ref = f"`{fk.ref_external_db}.{_bare(fk.ref_table)}.{target}`"
                keys.setdefault(col, []).append(f"FK → {ref}")

        rows = []
        for col in obj.columns:
            extra = []
            if col.identity:
                extra.append(f"IDENTITY({col.identity})")
            if col.rowguid:
                extra.append("ROWGUIDCOL")
            rows.append([
                cell(col.name),
                "computed" if col.computed else (cell(col.type) or "—"),
                "" if col.nullable else "NOT NULL",
                (f"`AS {cell(col.default)}`" if col.computed else f"`{cell(col.default)}`")
                if col.default else "",
                ", ".join(keys.get(col.name, []) + extra),
                cell(col.description),
            ])
        return md_table(["Column", "Type", "Null", "Default", "Key", "Description"], rows)

    # -- Tabellen ----------------------------------------------------------

    def _indexes(self, obj: DbObject) -> str:
        lines = []
        for index in obj.indexes:
            kind = {"primarykey": "PRIMARY KEY", "unique": "UNIQUE"}.get(index.kind, "INDEX")
            if index.kind == "index" and index.unique:
                kind = "UNIQUE INDEX"
            if index.clustered:
                kind += " CLUSTERED"
            line = f"- {index.name or '(unnamed)'}: {kind} ({', '.join(index.columns)})"
            if index.included:
                line += f" INCLUDE ({', '.join(index.included)})"
            lines.append(line)
        return "\n".join(lines)

    def _fk_out(self, obj: DbObject, depth: int) -> str:
        lines = []
        for fk in self.graph.fk_out.get(obj.id, []):
            if fk.ref_table in self.catalog.objects:
                target = self.link(fk.ref_table, depth)
            else:
                target = f"`{fk.ref_external_db}.{_bare(fk.ref_table)}` (not loaded)"
            actions = "".join(f" ON {k} {v}" for k, v in
                              (("DELETE", fk.on_delete), ("UPDATE", fk.on_update)) if v)
            lines.append(f"- {fk.name}: ({', '.join(fk.columns)}) → {target} "
                         f"({', '.join(fk.ref_columns)}){actions}")
        return "\n".join(lines)

    def _fk_in(self, obj: DbObject, depth: int) -> str:
        return "\n".join(
            f"- {fk.name}: {self.link(fk.table, depth)} ({', '.join(fk.columns)}) "
            f"→ ({', '.join(fk.ref_columns)})"
            for fk in self.graph.fk_in.get(obj.id, []))

    def _access_list(self, items: list[tuple[str, str | None]], depth: int) -> str:
        """Objektliste, mit Zugriffsart davor, sofern ``letters`` nicht None ist."""
        lines = []
        for oid, letters in items:
            obj = self.catalog.objects.get(oid)
            desc = f" — {oneline(obj.description)}" if obj and obj.description else ""
            access = "" if letters is None else f"{letters or '-':<4} "
            lines.append(f"- {access}{self.link(oid, depth)} "
                         f"({self.kind_of(oid)}){desc}")
        return "\n".join(lines)

    def render_table(self, obj: DbObject) -> str:
        depth = 2
        users = self.graph.used_by.get(obj.id, [])
        lines = self._head(obj, [f"columns: {len(obj.columns)}",
                                 f"used by: {len(users)} objects"])
        lines += self._section("Columns", self._columns(obj, depth))
        lines += self._section("Keys and indexes", self._indexes(obj))
        lines += self._section("Check constraints", "\n".join(
            f"- {c.name or '(unnamed)'}: {oneline(c.expression)}" for c in obj.checks))
        lines += self._section("Foreign keys (outgoing)", self._fk_out(obj, depth))
        lines += self._section("Referenced by (incoming foreign keys)",
                               self._fk_in(obj, depth))
        if users:
            lines += self._section(f"Used by ({ACCESS_LEGEND})",
                                   self._access_list(users, depth))
        return "\n".join(lines) + "\n"

    # -- Sichten und Routinen ---------------------------------------------

    def _uses(self, obj: DbObject, depth: int) -> str:
        access = self.graph.access.get(obj.id, {})
        items = sorted(access.items(), key=lambda i: self.label(i[0]).lower())
        return self._access_list(items, depth)

    def _relation(self, ids: list[str], depth: int) -> str:
        return self._access_list([(oid, None) for oid in ids], depth)

    def _externals(self, obj: DbObject) -> str:
        return "\n".join(f"- `{ref.external_db or '?'}.{_bare(ref.target)}`"
                         for ref in self.graph.externals.get(obj.id, []))

    def _dependencies(self, obj: DbObject, depth: int, uses_title: str) -> list[str]:
        lines = []
        uses = self._uses(obj, depth)
        if uses:
            lines += self._section(f"{uses_title} ({ACCESS_LEGEND})", uses)
        lines += self._section("Calls", self._relation(self.graph.calls.get(obj.id, []), depth))
        lines += self._section("Called by / used by",
                               self._relation(self.graph.called_by.get(obj.id, []), depth))
        lines += self._section("Unresolved references (objects in databases not loaded)",
                               self._externals(obj))
        return lines

    def render_view(self, obj: DbObject) -> str:
        depth = 2
        lines = self._head(obj, [f"columns: {len(obj.columns)}"])
        lines += self._section("Columns", self._columns(obj, depth))
        lines += self._dependencies(obj, depth, "Uses")
        lines += self._section("Source", fenced(obj.sql) if obj.sql else "")
        return "\n".join(lines) + "\n"

    def render_routine(self, obj: DbObject) -> str:
        depth = 2
        facts = []
        if obj.kind == "function":
            facts.append(f"type: {ROUTINE_TYPES.get(obj.routine_type, 'function')}")
            if obj.returns:
                facts.append(f"returns: {obj.returns}")
        if obj.kind == "trigger":
            if obj.trigger_events:
                facts.append(f"events: {', '.join(obj.trigger_events)}")
            if obj.trigger_on:
                facts.append(f"on: {self.link(obj.trigger_on, depth)}")
        if obj.clr:
            facts.append("CLR routine")
        if obj.dynamic_sql:
            facts.append("WARNING: builds SQL at runtime (EXEC / sp_executesql); "
                         "objects used dynamically are not listed below")
        lines = self._head(obj, facts)

        params = md_table(
            ["Parameter", "Type", "Direction", "Default"],
            [[cell(p.name), cell(p.type) or "—",
              "OUTPUT" if p.output else ("READONLY" if p.readonly else "IN"),
              f"`{cell(p.default)}`" if p.default else ""]
             for p in obj.parameters]) if obj.parameters else ""
        lines += self._section("Parameters", params)
        if obj.kind == "function":
            lines += self._section("Result columns", self._columns(obj, depth))
        lines += self._dependencies(obj, depth, "Tables and views used")
        lines += self._section("Source", fenced(obj.sql) if obj.sql else "")
        return "\n".join(lines) + "\n"

    def render_tabletype(self, obj: DbObject) -> str:
        lines = self._head(obj, [f"columns: {len(obj.columns)}"])
        lines += self._section("Columns", self._columns(obj, 2))
        return "\n".join(lines) + "\n"

    # -- je Datenbank ------------------------------------------------------

    def render_db_index(self, db: Database) -> str:
        lines = [f"# Database {db.name}", ""]
        facts = [("version", db.version), ("collation", db.collation),
                 ("compatibility level", db.compatibility), ("source", db.source),
                 ("schemas", ", ".join(sorted(db.schemas)))]
        lines += [f"- {k}: {v}" for k, v in facts if v]
        uses = self.graph.db_uses.get(db.key, {})
        if uses:
            lines.append("- uses databases: " + ", ".join(
                f"{self._db_name(k)} ({n} refs)" for k, n in sorted(uses.items())))
        used = self.graph.db_used_by.get(db.key, {})
        if used:
            lines.append("- used by databases: " + ", ".join(
                f"{self._db_name(k)} ({n} refs)" for k, n in sorted(used.items())))
        lines += ["", "Also in this folder: [schema.sql](schema.sql) (DDL of all tables), "
                  "[relations.md](relations.md) (foreign keys and cross-database access)."]
        for kind in NAV:
            objects = db.of_kind(kind)
            if not objects:
                continue
            lines += ["", f"## {KINDS_EN[kind][1]} ({len(objects)})", ""]
            for obj in objects:
                desc = f" — {oneline(obj.description)}" if obj.description else ""
                lines.append(f"- [{obj.display}]({self.paths[obj.id].split('/', 1)[1]})"
                             f"{desc}")
        return "\n".join(lines) + "\n"

    def _db_name(self, key: str) -> str:
        db = self.catalog.by_key(key)
        return db.name if db else key

    def render_schema_sql(self, db: Database) -> str:
        parts = [f"-- Database {db.name}: tables" +
                 (f" (collation {db.collation})" if db.collation else ""),
                 "-- Generated by dbdoku from the .dacpac model; column comments are "
                 "MS_Description."]
        for obj in db.of_kind("table"):
            head = f"\n-- {obj.qualified}"
            if obj.description:
                head += f": {oneline(obj.description)}"
            parts.append(head)
            parts.append(ddl.create_table(obj, self.catalog, self.graph, comments=True))
        return "\n".join(parts) + "\n"

    def render_relations(self, db: Database) -> str:
        depth = 1
        lines = [f"# Relations of {db.name}", "",
                 "## Foreign keys (child (columns) → parent (columns))", ""]
        fks = sorted((fk for fk in self.catalog.foreign_keys
                      if fk.table.startswith(db.key + "|")),
                     key=lambda fk: (self.label(fk.table).lower(), fk.name.lower()))
        for fk in fks:
            lines.append(f"- {self.link(fk.table, depth)} ({', '.join(fk.columns)}) → "
                         f"{self.link(fk.ref_table, depth)} ({', '.join(fk.ref_columns)})"
                         f"  [{fk.name}]")
        if not fks:
            lines.append("(none)")

        cross = []
        for oid in sorted(self.graph.access, key=lambda o: self.label(o).lower()):
            if not oid.startswith(db.key + "|"):
                continue
            for target, letters in sorted(self.graph.access[oid].items()):
                if not target.startswith(db.key + "|"):
                    cross.append(f"- {self.link(oid, depth)} → {letters:<4} "
                                 f"{self.link(target, depth)}")
        if cross:
            lines += ["", f"## Access to other databases ({ACCESS_LEGEND})", ""] + cross
        return "\n".join(lines) + "\n"

    # -- Katalog -----------------------------------------------------------

    def render_llms_txt(self) -> str:
        lines = [f"# {self.title}", "",
                 "> SQL Server database documentation generated by dbdoku from .dacpac "
                 "files. Start with README.md for conventions; each database has an "
                 "index.md listing every object, a schema.sql with all table DDL and a "
                 "relations.md with foreign keys and cross-database access.", "",
                 "## Databases", ""]
        for db in self.catalog.databases:
            counts = ", ".join(f"{KINDS_EN[k][1].lower()}: {db.count(k)}"
                               for k in NAV if db.count(k))
            lines.append(f"- [{db.name}]({self.folders[db.key]}/index.md): {counts}")
        return "\n".join(lines) + "\n"

    def render_readme(self) -> str:
        dbs = ", ".join(db.name for db in self.catalog.databases)
        return f"""# {self.title} — guide for AI assistants

Documentation of the SQL Server databases {dbs}, generated by dbdoku from the
.dacpac schema models (no live connection: no row counts or statistics).

## Layout

- `llms.txt` — list of databases with object counts
- `<DB>/index.md` — every object of the database, one line each, with description
- `<DB>/schema.sql` — `CREATE TABLE` for all tables incl. keys, foreign keys,
  checks, indexes; column descriptions as `--` comments. Best single file to
  understand a database's data model.
- `<DB>/relations.md` — all foreign keys as `child (cols) → parent (cols)` and
  every access to objects in other databases
- `<DB>/{{tables,views,procedures,functions,triggers,types}}/<schema>.<name>.md` —
  one file per object: columns, keys, incoming/outgoing foreign keys, which
  routines read/write it (tables); parameters, used tables, call graph and full
  T-SQL source (routines and views)

## Conventions

- Access letters: {ACCESS_LEGEND}. The list of objects comes from the
  model; the access type is derived from the T-SQL source.
- Objects in the same database are named `schema.name`, objects in other
  databases `Database.schema.name`.
- Routines marked "builds SQL at runtime" use dynamic SQL; their dependency
  lists may be incomplete.
- Names in backticks without a link point to databases that were not loaded.

## How to find things

- Find an object by name: grep `index.md` files, or glob `*/*/<schema>.<name>.md`.
- Who writes to table X: open its file, section "Used by", look for I/U/D.
- Search source code: grep the `procedures/`, `functions/`, `triggers/` and
  `views/` folders.
- Join path between two tables: see `relations.md` of the database.
"""

    # -- alles schreiben ---------------------------------------------------

    def write(self) -> int:
        out = self.out
        out.mkdir(parents=True, exist_ok=True)

        def put(rel: str, text: str) -> None:
            path = out / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(text)

        put("README.md", self.render_readme())
        put("llms.txt", self.render_llms_txt())
        written = 2
        renderers = {
            "table": self.render_table,
            "view": self.render_view,
            "procedure": self.render_routine,
            "function": self.render_routine,
            "trigger": self.render_routine,
            "tabletype": self.render_tabletype,
        }
        for db in self.catalog.databases:
            self.home = db.key
            folder = self.folders[db.key]
            put(f"{folder}/index.md", self.render_db_index(db))
            put(f"{folder}/schema.sql", self.render_schema_sql(db))
            put(f"{folder}/relations.md", self.render_relations(db))
            written += 3
            for kind in NAV:
                for obj in db.of_kind(kind):
                    put(self.paths[obj.id], renderers[kind](obj))
                    written += 1
        return written
