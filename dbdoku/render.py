"""Erzeugt die statische HTML-Dokumentation eines Datenbankkatalogs."""

from __future__ import annotations

import html
import json
import re
import shutil
from pathlib import Path

from . import erd
from .graph import Graph
from .highlight import highlight
from .model import ACCESS_LABEL, KINDS, Catalog, Database, DbObject

ASSETS = Path(__file__).parent / "assets"

# Reihenfolge der Objektarten in Navigation und Uebersicht.
NAV = ["table", "view", "procedure", "function", "trigger", "tabletype"]

_UNSAFE = re.compile(r"[^A-Za-z0-9._-]")


def esc(text: object) -> str:
    return html.escape(str(text if text is not None else ""))


def _slug(text: str) -> str:
    return _UNSAFE.sub("_", text) or "x"


class Renderer:
    def __init__(self, catalog: Catalog, graph: Graph, outdir: Path,
                 title: str = "Datenbankkatalog", fulltext: bool = False) -> None:
        self.catalog = catalog
        self.graph = graph
        self.out = outdir
        self.title = title
        self.fulltext = fulltext             # Quelltext mit in die Suche aufnehmen
        self.paths: dict[str, str] = {}      # Objekt-Id -> Pfad ab Wurzel
        self.db_paths: dict[str, str] = {}   # Datenbankschluessel -> Pfad ab Wurzel
        self.home = ""                       # Datenbank der gerade erzeugten Seite
        self._assign_paths()

    # -- Dateinamen und Verlinkung ----------------------------------------

    def _assign_paths(self) -> None:
        used: set[str] = set()
        for db in self.catalog.databases:
            folder = _slug(db.name)
            n = 1
            while folder.lower() in used:
                n += 1
                folder = f"{_slug(db.name)}~{n}"
            used.add(folder.lower())
            self.db_paths[db.key] = f"{folder}/index.html"

            taken: set[str] = set()
            for kind in NAV:
                sub = KINDS[kind][2]
                for obj in db.of_kind(kind):
                    slug = _slug(obj.display)
                    candidate, k = f"{sub}/{slug}.html", 1
                    while candidate.lower() in taken:
                        k += 1
                        candidate = f"{sub}/{slug}~{k}.html"
                    taken.add(candidate.lower())
                    self.paths[obj.id] = f"{folder}/{candidate}"

    def url(self, target: str, depth: int) -> str | None:
        path = self.paths.get(target)
        return None if path is None else ("../" * depth) + path

    def db_url(self, db_key: str, depth: int) -> str | None:
        path = self.db_paths.get(db_key)
        return None if path is None else ("../" * depth) + path

    def link(self, target: str, depth: int, label: str | None = None) -> str:
        """Verweis auf ein Objekt. Objekte anderer Datenbanken werden mit
        Datenbanknamen beschriftet, damit die Herkunft sichtbar bleibt."""
        obj = self.catalog.objects.get(target)
        if label is None and obj is not None:
            foreign = not target.startswith(self.home + "|")
            label = obj.qualified if foreign else obj.display
        text = esc(label if label is not None else target)
        href = self.url(target, depth)
        if href is None:
            return f'<span class="missing">{text}</span>'
        cls = "" if obj is None or target.startswith(self.home + "|") else ' class="xdb"'
        return f'<a href="{esc(href)}"{cls}>{text}</a>'

    def db_link(self, db_key: str, depth: int) -> str:
        db = self.catalog.by_key(db_key)
        href = self.db_url(db_key, depth)
        name = esc(db.name if db else db_key)
        return f'<a href="{esc(href)}">{name}</a>' if href else name

    # -- Grundgeruest ------------------------------------------------------

    def page(self, title: str, body: str, depth: int, active: str = "",
             extra_scripts: tuple[str, ...] = ()) -> str:
        base = "../" * depth
        scripts = "".join(f'<script src="{base}{esc(s)}"></script>'
                          for s in extra_scripts)
        current = self.catalog.by_key(self.home)

        items = []
        for db in self.catalog.databases:
            is_home = db.key == self.home
            sub = ""
            if is_home:
                links = []
                for kind in NAV:
                    count = db.count(kind)
                    if not count:
                        continue
                    cls = ' class="active"' if active == kind else ""
                    links.append(
                        f'<li{cls}><a href="{base}{_slug(db.name)}/'
                        f'{KINDS[kind][2]}/index.html">{esc(KINDS[kind][1])}'
                        f'<span class="count">{count}</span></a></li>')
                sub = f'<ul class="sub">{"".join(links)}</ul>'
            cls = ' class="active"' if is_home and active in ("db", *NAV) else ""
            items.append(
                f'<li{cls}><a href="{base}{esc(self.db_paths[db.key])}">'
                f'{esc(db.name)}<span class="count">{db.total}</span></a>{sub}</li>')

        home_cls = ' class="active"' if active == "index" else ""
        search_cls = ' class="active"' if active == "suche" else ""
        return f"""<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)} – {esc(current.name if current else self.title)}</title>
<link rel="stylesheet" href="{base}assets/style.css">
</head>
<body>
<a class="skip" href="#inhalt">Zum Inhalt</a>
<div class="layout">
<aside class="sidebar">
  <div class="brand"><a href="{base}index.html">{esc(self.title)}</a>
    <span class="ver">{len(self.catalog.databases)} Datenbanken ·
      {self.catalog.total} Objekte</span></div>
  <nav>
    <ul>
      <li{home_cls}><a href="{base}index.html">Übersicht</a></li>
      <li{search_cls}><a href="{base}suche.html">Suche</a></li>
    </ul>
    <div class="navhead">Datenbanken</div>
    <ul class="dbs">{''.join(items)}</ul>
  </nav>
  <div class="foot">erzeugt mit dbdoku</div>
</aside>
<main id="inhalt">
{body}
</main>
</div>
{scripts}<script src="{base}assets/app.js"></script>
</body>
</html>
"""

    # -- Bausteine ---------------------------------------------------------

    @staticmethod
    def section(title: str, body: str, note: str = "") -> str:
        if not body:
            return ""
        anchor = _UNSAFE.sub("-", title.lower())
        extra = f'<p class="note">{note}</p>' if note else ""
        return f'<section><h2 id="{esc(anchor)}">{esc(title)}</h2>{extra}{body}</section>'

    @staticmethod
    def table(headers: list[str], rows: list[list[str]], cls: str = "") -> str:
        if not rows:
            return ""
        head = "".join(f"<th>{esc(h)}</th>" for h in headers)
        body = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>"
                       for r in rows)
        classes = ("data " + cls).strip()
        return (f'<div class="tablewrap"><table class="{classes}">'
                f"<thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>")

    @staticmethod
    def details(summary: str, body: str, open_: bool = False) -> str:
        if not body:
            return ""
        attr = " open" if open_ else ""
        return (f"<details{attr}><summary>{esc(summary)}</summary>"
                f'<div class="detailbody">{body}</div></details>')

    @staticmethod
    def code(sql: str) -> str:
        sql = sql.replace("\r\n", "\n").replace("\r", "\n").strip("\n")
        if not sql:
            return ""
        lines = sql.count("\n") + 1
        gutter = "\n".join(str(i) for i in range(1, lines + 1))
        return (f'<div class="code"><pre class="gutter" aria-hidden="true">{gutter}</pre>'
                f'<pre class="sql"><code>{highlight(sql)}</code></pre></div>')

    @staticmethod
    def access_badges(letters: str) -> str:
        return "".join(
            f'<span class="acc acc-{l}" title="{esc(ACCESS_LABEL[l])}">{l}</span>'
            for l in letters)

    # -- Katalogübersicht --------------------------------------------------

    def render_index(self) -> str:
        self.home = ""
        cat, g = self.catalog, self.graph
        totals = {kind: sum(db.count(kind) for db in cat.databases) for kind in NAV}
        edges = sum(sum(t.values()) for t in g.db_uses.values())

        cards = [f'<div class="card"><span class="num">{len(cat.databases)}</span>'
                 f'<span class="lab">Datenbanken</span></div>',
                 f'<div class="card"><span class="num">{cat.total}</span>'
                 f'<span class="lab">Objekte</span></div>']
        for kind in NAV:
            if totals[kind]:
                cards.append(f'<div class="card"><span class="num">{totals[kind]}</span>'
                             f'<span class="lab">{esc(KINDS[kind][1])}</span></div>')
        cards.append(f'<div class="card"><span class="num">{len(cat.foreign_keys)}</span>'
                     f'<span class="lab">Fremdschlüssel</span></div>')
        cards.append(f'<div class="card"><span class="num">{edges}</span>'
                     f'<span class="lab">DB-übergreifende Verweise</span></div>')

        rows = []
        for db in cat.databases:
            uses = g.db_uses.get(db.key, {})
            used = g.db_used_by.get(db.key, {})
            rows.append([
                self.db_link(db.key, 0),
                str(db.total),
                str(db.count("table")),
                str(db.count("view")),
                str(db.count("procedure")),
                str(db.count("function")),
                str(sum(1 for fk in cat.foreign_keys
                        if fk.table.startswith(db.key + "|"))),
                str(len(uses)),
                str(len(used)),
                esc(db.source),
            ])
        overview = self.table(
            ["Datenbank", "Objekte", "Tabellen", "Sichten", "Prozeduren",
             "Funktionen", "FK", "benutzt", "benutzt von", "Quelle"],
            rows, "sortable")

        matrix_rows = []
        for db in cat.databases:
            uses = g.db_uses.get(db.key, {})
            if not uses:
                continue
            targets = ", ".join(
                f'{self.db_link(key, 0)} <span class="muted">({count})</span>'
                for key, count in sorted(uses.items(), key=lambda i: -i[1]))
            matrix_rows.append([self.db_link(db.key, 0), str(len(uses)), targets])
        matrix = self.table(["Datenbank", "Anzahl", "benutzt"], matrix_rows)

        missing = self.table(
            ["Datenbank", "erwartete Quelle"],
            [[esc(name), esc(source or "—")]
             for name, source in sorted(cat.unresolved_dbs.items())])

        empty = [db.name for db in cat.databases if not db.total]
        empty_note = ""
        if empty:
            empty_note = (f'<p class="note">Ohne Objekte und daher ohne Inhalt: '
                          f'{esc(", ".join(sorted(empty)))}.</p>')

        body = f"""
<header class="pagehead">
  <h1>{esc(self.title)}</h1>
  <p class="lead">{len(cat.databases)} Datenbanken mit {cat.total} Objekten.
     Verweise über Datenbankgrenzen sind aufgelöst und verlinkt.</p>
</header>
<div class="cards">{''.join(cards)}</div>
{self.section('Datenbanken', overview + empty_note)}
{self.section('Abhängigkeiten zwischen den Datenbanken', matrix,
              'In Klammern die Zahl der Verweise: Objektbezüge aus Quelltexten, '
              'Fremdschlüssel und erkannte Zugriffe zusammengenommen.')}
{self.section('Nicht geladene Datenbanken', missing,
              'Diese Datenbanken werden referenziert, liegen aber nicht als '
              '.dacpac vor. Verweise darauf bleiben unverlinkt.')}
"""
        return self.page("Übersicht", body, 0, "index")

    # -- Datenbankübersicht ------------------------------------------------

    def render_db_index(self, db: Database) -> str:
        self.home = db.key
        g = self.graph
        depth = 1

        cards = []
        for kind in NAV:
            count = db.count(kind)
            if count:
                cards.append(
                    f'<a class="card" href="{KINDS[kind][2]}/index.html">'
                    f'<span class="num">{count}</span>'
                    f'<span class="lab">{esc(KINDS[kind][1])}</span></a>')
        fks = [fk for fk in self.catalog.foreign_keys
               if fk.table.startswith(db.key + "|")]
        cards.append(f'<div class="card"><span class="num">{len(fks)}</span>'
                     f'<span class="lab">Fremdschlüssel</span></div>')

        meta_rows = [
            ["Datenbank", esc(db.name)],
            ["Quelle", esc(db.source)],
            ["Version", esc(db.version)],
            ["Erzeugt am", esc(db.created[:19].replace("T", " ") if db.created else "")],
            ["Sortierung", esc(db.collation)],
            ["Kompatibilitätsgrad", esc(db.compatibility)],
            ["Schemas", esc(", ".join(sorted(db.schemas)))],
        ]
        if db.assemblies:
            meta_rows.append(["CLR-Assemblies", esc(", ".join(sorted(db.assemblies)))])
        meta = self.table(["Eigenschaft", "Wert"],
                          [row for row in meta_rows if row[1]], "kv")

        ranked = sorted(((len(g.used_by.get(o.id, [])), o) for o in db.of_kind("table")),
                        key=lambda item: (-item[0], item[1].display.lower()))[:20]
        top_rows = []
        for count, obj in ranked:
            if not count:
                break
            users = g.used_by.get(obj.id, [])
            writers = sum(1 for _, l in users if set(l) & set("IUD"))
            foreign = sum(1 for r, _ in users if not r.startswith(db.key + "|"))
            top_rows.append([
                self.link(obj.id, depth), str(count), str(writers), str(foreign),
                str(len(g.fk_in.get(obj.id, []))), esc(obj.description or ""),
            ])
        top = self.table(
            ["Tabelle", "verwendet von", "davon schreibend", "davon aus anderen DB",
             "eingehende FK", "Beschreibung"], top_rows, "rank")

        svg, _, _ = erd.database_diagram(db.key, g, lambda k: self.db_url(k, depth))
        diagram = (f'<div class="erdwrap">{svg}</div>'
                   '<p class="note">Links die Datenbanken, die diese benutzt; '
                   'rechts die, die von ihr benutzt werden. Kästen sind verlinkt.</p>'
                   ) if svg else ""

        entry = g.entry_points(db.key)
        entry_note = ""
        if db.count("procedure"):
            entry_note = (f'<p class="note">{len(entry)} von {db.count("procedure")} '
                          'Prozeduren werden von keinem anderen Objekt des Katalogs '
                          'aufgerufen – sie werden also von außen gestartet. In der '
                          f'<a href="{KINDS["procedure"][2]}/index.html">Prozedurliste'
                          '</a> lassen sie sich über die Spalte „aufgerufen von“ '
                          'heraussortieren.</p>')

        body = f"""
<header class="pagehead">
  <div class="crumb"><a href="../index.html">Katalog</a> · Datenbank</div>
  <h1>{esc(db.name)}</h1>
  <p class="lead">{db.total} Objekte.</p>
</header>
<div class="cards">{''.join(cards)}</div>
{self.section('Eckdaten', meta)}
{self.section('Abhängigkeiten', diagram)}
{self.section('Meistgenutzte Tabellen', top,
              'Anzahl der Prozeduren, Sichten, Funktionen und Trigger, die auf die '
              'Tabelle zugreifen – auch aus anderen Datenbanken.')}
{self.section('Einstiegspunkte', entry_note)}
"""
        return self.page(db.name, body, depth, "db")

    # -- Listenseiten ------------------------------------------------------

    def render_list(self, db: Database, kind: str) -> str:
        self.home = db.key
        g = self.graph
        depth = 2
        _, plural, _ = KINDS[kind]
        objects = db.of_kind(kind)

        if kind == "table":
            headers = ["Name", "Schema", "Spalten", "FK aus", "FK ein",
                       "verwendet von", "aus anderen DB", "Beschreibung"]
            rows = []
            for o in objects:
                users = g.used_by.get(o.id, [])
                foreign = sum(1 for r, _ in users if not r.startswith(db.key + "|"))
                rows.append([
                    self.link(o.id, depth), esc(o.schema), str(len(o.columns)),
                    str(len(g.fk_out.get(o.id, []))), str(len(g.fk_in.get(o.id, []))),
                    str(len(users)), str(foreign), esc(o.description or ""),
                ])
        elif kind == "view":
            headers = ["Name", "Schema", "Spalten", "verwendet", "verwendet von",
                       "Beschreibung"]
            rows = [[
                self.link(o.id, depth), esc(o.schema), str(len(o.columns)),
                str(len(g.access.get(o.id, {}))), str(len(g.called_by.get(o.id, []))),
                esc(o.description or ""),
            ] for o in objects]
        elif kind in ("procedure", "trigger"):
            headers = ["Name", "Schema", "Parameter", "liest", "schreibt",
                       "ruft auf", "aufgerufen von", "Beschreibung"]
            rows = []
            for o in objects:
                acc = g.access.get(o.id, {})
                reads = sum(1 for v in acc.values() if "S" in v)
                writes = sum(1 for v in acc.values() if set(v) & set("IUD"))
                mark = ('<span class="warn-dot" title="enthält dynamisches SQL">◆'
                        "</span>" if o.dynamic_sql else "")
                rows.append([
                    self.link(o.id, depth) + " " + mark, esc(o.schema),
                    str(len(o.parameters)), str(reads), str(writes),
                    str(len(g.calls.get(o.id, []))), str(len(g.called_by.get(o.id, []))),
                    esc(o.description or ""),
                ])
        elif kind == "function":
            labels = {"scalar": "skalar", "inline_tvf": "Inline-TVF",
                      "mstvf": "Multi-Statement-TVF"}
            headers = ["Name", "Schema", "Art", "Rückgabe", "Parameter",
                       "aufgerufen von", "Beschreibung"]
            rows = [[
                self.link(o.id, depth), esc(o.schema),
                esc(labels.get(o.routine_type, "")), esc(o.returns or ""),
                str(len(o.parameters)), str(len(g.called_by.get(o.id, []))),
                esc(o.description or ""),
            ] for o in objects]
        else:  # tabletype
            headers = ["Name", "Schema", "Spalten", "Beschreibung"]
            rows = [[self.link(o.id, depth), esc(o.schema), str(len(o.columns)),
                     esc(o.description or "")] for o in objects]

        body = f"""
<header class="pagehead">
  <div class="crumb"><a href="../../index.html">Katalog</a> ·
    <a href="../index.html">{esc(db.name)}</a></div>
  <h1>{esc(plural)}</h1>
  <p class="lead">{len(objects)} Objekte in {esc(db.name)}.
     Spaltenüberschrift anklicken zum Sortieren.</p>
</header>
<input type="search" class="filter" data-filter="objects" placeholder="Filtern …"
       aria-label="Liste filtern">
<div id="objects">{self.table(headers, rows, 'sortable')}</div>
"""
        return self.page(f"{plural} – {db.name}", body, depth, kind)

    # -- Spaltenblock ------------------------------------------------------

    def _column_flags(self, obj: DbObject) -> dict[str, list[str]]:
        flags: dict[str, list[str]] = {}
        for index in obj.indexes:
            mark = {"primarykey": "PK", "unique": "UQ"}.get(index.kind, "IX")
            for col in index.columns:
                flags.setdefault(col, [])
                if mark not in flags[col]:
                    flags[col].append(mark)
        for fk in self.graph.fk_out.get(obj.id, []):
            for col in fk.columns:
                flags.setdefault(col, [])
                if "FK" not in flags[col]:
                    flags[col].append("FK")
        return flags

    def _columns(self, obj: DbObject, depth: int) -> str:
        if not obj.columns:
            return ""
        flags = self._column_flags(obj)
        fk_by_col: dict[str, str] = {}
        for fk in self.graph.fk_out.get(obj.id, []):
            for i, col in enumerate(fk.columns):
                target = fk.ref_columns[i] if i < len(fk.ref_columns) else ""
                if fk.ref_table in self.catalog.objects:
                    ref = self.catalog.objects[fk.ref_table]
                    label = (ref.display if fk.ref_table.startswith(self.home + "|")
                             else ref.qualified)
                    fk_by_col[col] = self.link(fk.ref_table, depth, f"{label}.{target}")
                else:
                    name = fk.ref_table.replace("[", "").replace("]", "")
                    fk_by_col[col] = (f'<span class="ext">{esc(fk.ref_external_db)}:'
                                      f'{esc(name)}.{esc(target)}</span>')

        rows = []
        for i, col in enumerate(obj.columns, 1):
            marks = "".join(f'<span class="flag flag-{m.lower()}">{m}</span>'
                            for m in flags.get(col.name, []))
            extra = []
            if col.identity:
                seed, inc = col.identity.split(",")
                extra.append(f'<span class="flag flag-id">IDENTITY({seed},{inc})</span>')
            if col.computed:
                extra.append('<span class="flag flag-calc">berechnet</span>')
            if col.rowguid:
                extra.append('<span class="flag">ROWGUIDCOL</span>')
            ref = fk_by_col.get(col.name, "")
            rows.append([
                str(i),
                f'<code class="col">{esc(col.name)}</code>' + "".join(extra),
                f'<code>{esc(col.type)}</code>' if col.type else "—",
                "" if col.nullable else '<span class="no">NOT NULL</span>',
                f"<code>{esc(col.default)}</code>" if col.default else "",
                marks + (f' <span class="fkref">→ {ref}</span>' if ref else ""),
                esc(col.description or ""),
            ])
        return self.table(
            ["#", "Spalte", "Datentyp", "NULL", "Standardwert", "Schlüssel",
             "Beschreibung"], rows, "cols")

    def _indexes(self, obj: DbObject) -> str:
        rows = []
        for index in obj.indexes:
            kind = {"primarykey": "Primärschlüssel", "unique": "Unique"}.get(
                index.kind, "Index")
            attrs = []
            if index.clustered:
                attrs.append("gruppiert")
            if index.unique and index.kind == "index":
                attrs.append("eindeutig")
            rows.append([
                esc(index.name or "(unbenannt)"), esc(kind),
                ", ".join(f"<code>{esc(c)}</code>" for c in index.columns) or "—",
                ", ".join(f"<code>{esc(c)}</code>" for c in index.included) or "",
                esc(", ".join(attrs)),
            ])
        return self.table(["Name", "Art", "Spalten", "eingeschlossen", "Eigenschaften"],
                          rows)

    def _used_by(self, obj: DbObject, depth: int) -> str:
        rows = []
        for routine_id, letters in self.graph.used_by.get(obj.id, []):
            routine = self.catalog.objects[routine_id]
            foreign = not routine_id.startswith(self.home + "|")
            rows.append([
                self.link(routine_id, depth),
                esc(KINDS[routine.kind][0]),
                (f'<span class="xdb-tag">{esc(routine.db)}</span>' if foreign
                 else '<span class="muted">eigene</span>'),
                self.access_badges(letters),
                esc(routine.description or ""),
            ])
        return self.table(["Objekt", "Art", "Datenbank", "Zugriff", "Beschreibung"],
                          rows, "usedby")

    def _diagram(self, obj: DbObject, depth: int) -> str:
        svg, shown, total = erd.diagram(obj.id, self.graph, lambda t: self.url(t, depth))
        if not svg:
            return ""
        note = ""
        if shown < total:
            note = (f'<p class="note">Es werden {shown} von {total} direkt verbundenen '
                    "Tabellen gezeichnet; die vollständigen Listen stehen darunter.</p>")
        mmd = erd.mermaid(obj.id, self.graph)
        extra = self.details("Mermaid-Quelltext",
                             f'<pre class="plain">{esc(mmd)}</pre>') if mmd else ""
        return (f'{note}<div class="erdwrap">{svg}</div>'
                '<p class="note">Pfeile zeigen vom Fremdschlüssel auf den '
                'referenzierten Primärschlüssel. Kästen sind verlinkt.</p>' + extra)

    def _foreign_keys(self, obj: DbObject, depth: int) -> tuple[str, str]:
        out_rows = []
        for fk in self.graph.fk_out.get(obj.id, []):
            if fk.ref_table in self.catalog.objects:
                target = self.link(fk.ref_table, depth)
            else:
                name = fk.ref_table.replace("[", "").replace("]", "")
                target = (f'<span class="ext">{esc(fk.ref_external_db)}: '
                          f'{esc(name)}</span>')
            actions = ", ".join(f"ON {k} {v}" for k, v in
                                (("DELETE", fk.on_delete), ("UPDATE", fk.on_update)) if v)
            out_rows.append([
                esc(fk.name),
                ", ".join(f"<code>{esc(c)}</code>" for c in fk.columns),
                target,
                ", ".join(f"<code>{esc(c)}</code>" for c in fk.ref_columns),
                esc(actions),
            ])
        in_rows = [[
            esc(fk.name), self.link(fk.table, depth),
            ", ".join(f"<code>{esc(c)}</code>" for c in fk.columns),
            ", ".join(f"<code>{esc(c)}</code>" for c in fk.ref_columns),
        ] for fk in self.graph.fk_in.get(obj.id, [])]
        return (
            self.table(["Constraint", "Spalte(n)", "Zieltabelle", "Zielspalte(n)",
                        "Aktionen"], out_rows),
            self.table(["Constraint", "Tabelle", "Spalte(n)", "verweist auf"], in_rows),
        )

    def _ddl(self, obj: DbObject) -> str:
        """``CREATE TABLE`` aus dem Modell rekonstruieren."""
        lines = [f"CREATE TABLE {obj.display} ("]
        parts = []
        for col in obj.columns:
            piece = f"    [{col.name}] {col.type or ''}".rstrip()
            if col.collation:
                piece += f" COLLATE {col.collation}"
            if col.identity:
                piece += f" IDENTITY({col.identity})"
            if col.default:
                piece += f" DEFAULT {col.default}"
            piece += "" if col.nullable else " NOT NULL"
            parts.append(piece)
        for index in obj.indexes:
            if index.kind not in ("primarykey", "unique"):
                continue
            name = f"CONSTRAINT [{index.name}] " if index.name else ""
            cols = ", ".join(f"[{c}]" for c in index.columns)
            if index.kind == "primarykey":
                clustered = " CLUSTERED" if index.clustered else ""
                parts.append(f"    {name}PRIMARY KEY{clustered} ({cols})")
            else:
                parts.append(f"    {name}UNIQUE ({cols})")
        for fk in self.graph.fk_out.get(obj.id, []):
            cols = ", ".join(f"[{c}]" for c in fk.columns)
            ref_cols = ", ".join(f"[{c}]" for c in fk.ref_columns)
            ref_obj = self.catalog.objects.get(fk.ref_table)
            ref = (ref_obj.qualified if ref_obj
                   else fk.ref_table.replace("[", "").replace("]", ""))
            parts.append(f"    CONSTRAINT [{fk.name}] FOREIGN KEY ({cols}) "
                         f"REFERENCES {ref} ({ref_cols})")
        for check in obj.checks:
            name = f"CONSTRAINT [{check.name}] " if check.name else ""
            parts.append(f"    {name}CHECK ({check.expression})")
        lines.append(",\n".join(parts))
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

    # -- Detailseiten ------------------------------------------------------

    def render_table(self, obj: DbObject) -> str:
        depth = 2
        fk_out, fk_in = self._foreign_keys(obj, depth)
        checks = self.table(
            ["Name", "Bedingung"],
            [[esc(c.name or "(unbenannt)"), f"<code>{esc(c.expression)}</code>"]
             for c in obj.checks])
        users = self.graph.used_by.get(obj.id, [])
        writers = sum(1 for _, letters in users if set(letters) & set("IUD"))
        foreign = sum(1 for r, _ in users if not r.startswith(self.home + "|"))
        badges = [f"{len(obj.columns)} Spalten", f"{len(users)} verwendende Objekte",
                  f"{writers} davon schreibend"]
        if foreign:
            badges.append(f"{foreign} aus anderen Datenbanken")

        body = f"""
{self._head(obj, badges)}
{self.section('Spalten', self._columns(obj, depth))}
{self.section('Schlüssel und Indizes', self._indexes(obj))}
{self.section('Check-Constraints', checks)}
{self.section('Beziehungsdiagramm', self._diagram(obj, depth))}
{self.section('Fremdschlüssel (ausgehend)', fk_out,
              'Diese Tabelle verweist auf die folgenden Tabellen.')}
{self.section('Referenziert von (eingehend)', fk_in,
              'Die folgenden Tabellen verweisen auf diese Tabelle.')}
{self.section('Verwendet von', self._used_by(obj, depth),
              'S = liest, I = fügt ein, U = ändert, D = löscht. Die Objektliste '
              'stammt aus dem Modell, die Zugriffsart wird aus dem Quelltext '
              'ermittelt.')}
{self.section('DDL', self.details('CREATE TABLE anzeigen', self.code(self._ddl(obj))))}
"""
        return self.page(f"Tabelle {obj.display}", body, depth, "table")

    def render_view(self, obj: DbObject) -> str:
        depth = 2
        body = f"""
{self._head(obj, [f'{len(obj.columns)} Spalten'])}
{self.section('Spalten', self._columns(obj, depth))}
{self.section('Verwendete Objekte', self._uses(obj, depth))}
{self.section('Verwendet von', self._callers(obj, depth))}
{self.section('Nicht auflösbare Verweise', self._externals(obj))}
{self.section('Quelltext', self.code(obj.sql))}
"""
        return self.page(f"Sicht {obj.display}", body, depth, "view")

    def render_routine(self, obj: DbObject) -> str:
        depth = 2
        params = self.table(
            ["Parameter", "Datentyp", "Richtung", "Standardwert"],
            [[f'<code class="col">{esc(p.name)}</code>',
              f"<code>{esc(p.type)}</code>" if p.type else "—",
              "OUTPUT" if p.output else ("READONLY" if p.readonly else "IN"),
              f"<code>{esc(p.default)}</code>" if p.default else ""]
             for p in obj.parameters])

        badges = []
        if obj.kind == "function":
            labels = {"scalar": "Skalarfunktion", "inline_tvf": "Inline-Tabellenfunktion",
                      "mstvf": "Multi-Statement-Tabellenfunktion"}
            badges.append(labels.get(obj.routine_type, "Funktion"))
            if obj.returns:
                badges.append(f"gibt {obj.returns} zurück")
        if obj.kind == "trigger":
            if obj.trigger_events:
                badges.append(" / ".join(obj.trigger_events))
            if obj.trigger_on and obj.trigger_on in self.catalog.objects:
                badges.append(f"auf {self.catalog.objects[obj.trigger_on].display}")
        badges.append(f"{len(obj.parameters)} Parameter")
        if obj.clr:
            badges.append("CLR")
        cross = {t.split("|", 1)[0] for t in self.graph.access.get(obj.id, {})
                 if not t.startswith(self.home + "|")}
        if cross:
            badges.append(f"greift auf {len(cross)} weitere Datenbank"
                          f"{'en' if len(cross) > 1 else ''} zu")

        warn = ""
        if obj.dynamic_sql:
            warn = ('<p class="warn">Diese Routine baut SQL zur Laufzeit zusammen '
                    '(<code>EXEC(…)</code> bzw. <code>sp_executesql</code>). Dynamisch '
                    'angesprochene Objekte stehen nicht im Modell – die folgenden '
                    'Listen können unvollständig sein.</p>')

        result = ""
        if obj.kind == "function" and obj.columns:
            result = self.section("Ergebnisspalten", self._columns(obj, depth))

        body = f"""
{self._head(obj, badges)}
{warn}
{self.section('Parameter', params)}
{result}
{self.section('Verwendete Tabellen und Sichten', self._uses(obj, depth),
              'S = liest, I = fügt ein, U = ändert, D = löscht.')}
{self.section('Ruft auf', self._calls(obj, depth))}
{self.section('Aufgerufen von', self._callers(obj, depth))}
{self.section('Nicht auflösbare Verweise', self._externals(obj))}
{self.section('Quelltext', self.code(obj.sql))}
"""
        return self.page(f"{KINDS[obj.kind][0]} {obj.display}", body, depth, obj.kind)

    def render_tabletype(self, obj: DbObject) -> str:
        depth = 2
        body = f"""
{self._head(obj, [f'{len(obj.columns)} Spalten'])}
{self.section('Spalten', self._columns(obj, depth))}
"""
        return self.page(f"Tabellentyp {obj.display}", body, depth, "tabletype")

    # -- gemeinsame Abschnitte --------------------------------------------

    def _head(self, obj: DbObject, badges: list[str]) -> str:
        chips = "".join(f'<span class="chip">{esc(b)}</span>' for b in badges if b)
        desc = (f'<p class="lead">{esc(obj.description)}</p>' if obj.description
                else '<p class="lead muted">Keine Beschreibung im Modell hinterlegt.</p>')
        return f"""
<header class="pagehead">
  <div class="crumb"><a href="../../index.html">Katalog</a> ·
    <a href="../index.html">{esc(obj.db)}</a> ·
    {esc(KINDS[obj.kind][0])}</div>
  <h1>{esc(obj.display)}</h1>
  {desc}
  <div class="chips"><span class="chip">Schema {esc(obj.schema)}</span>{chips}</div>
</header>"""

    def _uses(self, obj: DbObject, depth: int) -> str:
        access = self.graph.access.get(obj.id, {})
        rows = []
        for target_id, letters in sorted(
                access.items(),
                key=lambda i: self.catalog.objects[i[0]].qualified.lower()):
            target = self.catalog.objects[target_id]
            foreign = not target_id.startswith(self.home + "|")
            rows.append([
                self.link(target_id, depth),
                esc(KINDS[target.kind][0]),
                (f'<span class="xdb-tag">{esc(target.db)}</span>' if foreign
                 else '<span class="muted">eigene</span>'),
                self.access_badges(letters),
                esc(target.description or ""),
            ])
        return self.table(["Objekt", "Art", "Datenbank", "Zugriff", "Beschreibung"],
                          rows, "usedby")

    def _relation(self, ids: list[str], depth: int) -> str:
        rows = []
        for oid in ids:
            obj = self.catalog.objects[oid]
            foreign = not oid.startswith(self.home + "|")
            rows.append([
                self.link(oid, depth), esc(KINDS[obj.kind][0]),
                (f'<span class="xdb-tag">{esc(obj.db)}</span>' if foreign
                 else '<span class="muted">eigene</span>'),
                esc(obj.description or ""),
            ])
        return self.table(["Objekt", "Art", "Datenbank", "Beschreibung"], rows)

    def _calls(self, obj: DbObject, depth: int) -> str:
        return self._relation(self.graph.calls.get(obj.id, []), depth)

    def _callers(self, obj: DbObject, depth: int) -> str:
        return self._relation(self.graph.called_by.get(obj.id, []), depth)

    def _externals(self, obj: DbObject) -> str:
        rows = []
        for ref in self.graph.externals.get(obj.id, []):
            name = ref.target.split("|", 1)[-1].replace("[", "").replace("]", "")
            rows.append([esc(ref.external_db or ""), f"<code>{esc(name)}</code>"])
        return self.table(["Datenbank", "Objekt"], rows)

    # -- Suche -------------------------------------------------------------

    def render_search(self) -> str:
        self.home = ""
        if self.fulltext:
            lead = ("Sucht über alle Datenbanken hinweg in Objektnamen und "
                    "Beschreibungen. Auf Wunsch wird auch der Quelltext der "
                    "Routinen und Sichten durchsucht; der dafür nötige Index "
                    "wird erst beim Einschalten geladen.")
            option = ('<label class="opt"><input type="checkbox" id="src">'
                      ' Quelltext durchsuchen</label>\n')
        else:
            lead = ("Sucht über alle Datenbanken hinweg in Objektnamen und "
                    "Beschreibungen. Der Quelltext der Routinen ist nicht "
                    "indiziert – dafür sind die Abschnitte „Verwendet von“ und "
                    "„Ruft auf“ auf den Objektseiten gedacht.")
            option = ""
        body = f"""
<header class="pagehead">
  <h1>Suche</h1>
  <p class="lead">{lead}</p>
</header>
<input type="search" id="q" class="filter big" placeholder="Objekt oder Beschreibung …"
       autofocus aria-label="Suchbegriff">
{option}<div id="results" class="results"><p class="note">Mindestens zwei Zeichen eingeben.</p></div>
"""
        return self.page("Suche", body, 0, "suche", ("assets/suchindex.js",))

    def search_index(self) -> str:
        """Der Index als Skript, nicht als JSON.

        Beim Öffnen über ``file://`` verbieten Browser ``fetch`` auf lokale
        Dateien; ein ``<script>`` wird dagegen geladen. Die Dokumentation soll
        ohne Webserver funktionieren.
        """
        entries = []
        for db in self.catalog.databases:
            for kind in NAV:
                for obj in db.of_kind(kind):
                    entries.append([obj.display, KINDS[kind][0], self.paths[obj.id],
                                    obj.description or "", db.name])
        data = json.dumps(entries, ensure_ascii=False, separators=(",", ":"))
        return f"window.DBDOKU_INDEX={data};\n"

    def source_index(self) -> str:
        """Der Quelltext aller Objekte, in der Reihenfolge von :meth:`search_index`.

        Eigene Datei, weil sie ein Vielfaches des Namensindex wiegt. Die
        Suchseite laedt sie erst nach, wenn die Volltextsuche eingeschaltet
        wird — wieder als ``<script>``, damit ``file://`` funktioniert.
        """
        bodies = []
        for db in self.catalog.databases:
            for kind in NAV:
                for obj in db.of_kind(kind):
                    bodies.append(obj.sql)
        data = json.dumps(bodies, ensure_ascii=False, separators=(",", ":"))
        return f"window.DBDOKU_SOURCE={data};\n"

    # -- alles schreiben ---------------------------------------------------

    def write(self) -> int:
        out = self.out
        out.mkdir(parents=True, exist_ok=True)
        (out / "assets").mkdir(exist_ok=True)
        for name in ("style.css", "app.js"):
            shutil.copyfile(ASSETS / name, out / "assets" / name)
        (out / "assets" / "suchindex.js").write_text(self.search_index(),
                                                     encoding="utf-8")
        if self.fulltext:
            (out / "assets" / "quelltext.js").write_text(self.source_index(),
                                                         encoding="utf-8")

        written = 2
        (out / "index.html").write_text(self.render_index(), encoding="utf-8")
        (out / "suche.html").write_text(self.render_search(), encoding="utf-8")

        renderers = {
            "table": self.render_table,
            "view": self.render_view,
            "procedure": self.render_routine,
            "function": self.render_routine,
            "trigger": self.render_routine,
            "tabletype": self.render_tabletype,
        }
        for db in self.catalog.databases:
            db_page = out / self.db_paths[db.key]
            db_page.parent.mkdir(parents=True, exist_ok=True)
            db_page.write_text(self.render_db_index(db), encoding="utf-8")
            written += 1

            for kind in NAV:
                objects = db.of_kind(kind)
                if not objects:
                    continue
                folder = db_page.parent / KINDS[kind][2]
                folder.mkdir(exist_ok=True)
                (folder / "index.html").write_text(self.render_list(db, kind),
                                                   encoding="utf-8")
                written += 1
                render = renderers[kind]
                self.home = db.key
                for obj in objects:
                    (out / self.paths[obj.id]).write_text(render(obj), encoding="utf-8")
                    written += 1
        return written
