"""Rueckwaertsindizes: Aufrufgraph, Verwendungen, Fremdschluessel-Nachbarschaft.

Alle Indizes sind katalogweit, Kanten ueber Datenbankgrenzen stehen also
gleichberechtigt neben den internen.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from .model import Catalog, ForeignKey, Ref

ROUTINE_KINDS = ("procedure", "function", "trigger")


@dataclass
class Graph:
    catalog: Catalog
    access: dict[str, dict[str, str]]                    # routine -> tabelle -> 'SIUD'
    used_by: dict[str, list[tuple[str, str]]] = field(default_factory=dict)
    calls: dict[str, list[str]] = field(default_factory=dict)
    called_by: dict[str, list[str]] = field(default_factory=dict)
    fk_out: dict[str, list[ForeignKey]] = field(default_factory=dict)
    fk_in: dict[str, list[ForeignKey]] = field(default_factory=dict)
    externals: dict[str, list[Ref]] = field(default_factory=dict)
    db_uses: dict[str, dict[str, int]] = field(default_factory=dict)   # db -> db -> Kanten
    db_used_by: dict[str, dict[str, int]] = field(default_factory=dict)

    def neighbours(self, table_id: str) -> list[str]:
        """Alle ueber Fremdschluessel direkt verbundenen Tabellen."""
        out: list[str] = []
        for fk in self.fk_out.get(table_id, []):
            if fk.ref_table not in out and fk.ref_table in self.catalog.objects:
                out.append(fk.ref_table)
        for fk in self.fk_in.get(table_id, []):
            if fk.table not in out:
                out.append(fk.table)
        return out

    def entry_points(self, db_key: str | None = None) -> list[str]:
        """Prozeduren, die von keinem anderen Objekt aufgerufen werden."""
        return sorted(
            (oid for oid, obj in self.catalog.objects.items()
             if obj.kind == "procedure" and not self.called_by.get(oid)
             and (db_key is None or oid.startswith(db_key + "|"))),
            key=lambda oid: self.catalog.objects[oid].display.lower(),
        )

    def is_cross_db(self, a: str, b: str) -> bool:
        return a.split("|", 1)[0] != b.split("|", 1)[0]


def build(catalog: Catalog, access: dict[str, dict[str, str]]) -> Graph:
    g = Graph(catalog=catalog, access=access)
    objects = catalog.objects

    def label(oid: str) -> str:
        obj = objects.get(oid)
        return obj.qualified.lower() if obj else oid

    used_by: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for routine_id, tables in access.items():
        for table_id, letters in tables.items():
            used_by[table_id].append((routine_id, letters))
    for users in used_by.values():
        users.sort(key=lambda item: label(item[0]))
    g.used_by = dict(used_by)

    calls: dict[str, list[str]] = {}
    called_by: dict[str, list[str]] = defaultdict(list)
    externals: dict[str, list[Ref]] = {}
    db_uses: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))

    for oid, obj in objects.items():
        home = oid.split("|", 1)[0]
        targets: list[str] = []
        unresolved: dict[tuple[str, str], Ref] = {}
        for ref in obj.refs:
            if ref.target == oid:
                continue                       # Selbstbezug (z. B. eigener Parameter)
            if not ref.resolved or ref.target not in objects:
                if ref.is_external:
                    unresolved.setdefault((ref.external_db or "", ref.target), ref)
                continue
            other = ref.target.split("|", 1)[0]
            if other != home:
                db_uses[home][other] += 1
            target = objects[ref.target]
            if target.kind in ROUTINE_KINDS and ref.target not in targets:
                targets.append(ref.target)
        if targets:
            targets.sort(key=label)
            calls[oid] = targets
            for target in targets:
                called_by[target].append(oid)
        if unresolved:
            externals[oid] = sorted(
                unresolved.values(), key=lambda r: (r.external_db or "", r.target))

    for callers in called_by.values():
        callers.sort(key=label)

    g.calls = calls
    g.called_by = dict(called_by)
    g.externals = externals

    fk_out: dict[str, list[ForeignKey]] = defaultdict(list)
    fk_in: dict[str, list[ForeignKey]] = defaultdict(list)
    for fk in catalog.foreign_keys:
        fk_out[fk.table].append(fk)
        if fk.ref_table in objects:
            fk_in[fk.ref_table].append(fk)
            home, other = fk.table.split("|", 1)[0], fk.ref_table.split("|", 1)[0]
            if home != other:
                db_uses[home][other] += 1
    g.fk_out = dict(fk_out)
    g.fk_in = dict(fk_in)

    # Zugriffe aus der Schreibanalyse zaehlen ebenfalls als Datenbankkante.
    for routine_id, tables in access.items():
        home = routine_id.split("|", 1)[0]
        for table_id in tables:
            other = table_id.split("|", 1)[0]
            if other != home:
                db_uses[home][other] += 1

    g.db_uses = {k: dict(v) for k, v in db_uses.items()}
    used_by_db: dict[str, dict[str, int]] = defaultdict(dict)
    for source, targets in g.db_uses.items():
        for target, count in targets.items():
            used_by_db[target][source] = count
    g.db_used_by = dict(used_by_db)
    return g
