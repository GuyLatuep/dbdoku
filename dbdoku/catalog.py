"""Mehrere .dacpac zu einem Katalog zusammenfuehren.

Jede .dacpac wird einzeln gelesen (:mod:`dbdoku.extract`) und kennt ihre
Verweise auf andere Datenbanken bereits — DacFx notiert sie mit
``ExternalSource`` und einem Namen der Form ``[Faktura-DB]|[dbo].[blzrout]``.
Hier werden diese Verweise auf die tatsaechlichen Objekte der Nachbar-.dacpac
abgebildet, sodass aus einer bloßen Notiz ein echter Verweis wird.

Objekt-Ids werden dabei katalogweit eindeutig gemacht: aus ``[dbo].[Person]``
wird ``abacusdbs|[dbo].[Person]``. Zwei Datenbanken duerfen gleichnamige
Tabellen haben, ohne sich zu ueberschreiben.
"""

from __future__ import annotations

from pathlib import Path

from .extract import Extractor
from .model import Catalog, Database, gid


def load(paths: list[Path]) -> Catalog:
    catalog = Catalog()

    for path in sorted(paths, key=lambda p: p.name.lower()):
        extractor = Extractor()
        db = extractor.run(str(path))
        db.source = path.name
        if not db.name:
            # master.dacpac und msdb.dacpac tragen keinen Namen in DacMetadata.xml.
            db.name = path.stem
        catalog.sanitized_refs += getattr(extractor, "sanitized_refs", 0)
        catalog.databases.append(db)

    catalog.databases.sort(key=lambda d: d.name.lower())
    _globalize(catalog)
    _resolve_cross_references(catalog)
    return catalog


def _globalize(catalog: Catalog) -> None:
    """Lokale Ids durch katalogweite ersetzen."""
    for db in catalog.databases:
        renamed = {}
        for oid, obj in db.objects.items():
            obj.id = gid(db.key, oid)
            obj.db = db.name
            renamed[obj.id] = obj
        db.objects = renamed

        for fk in db.foreign_keys:
            fk.table = gid(db.key, fk.table)
            if not fk.ref_external_db:
                fk.ref_table = gid(db.key, fk.ref_table)

        catalog.objects.update(db.objects)
        catalog.foreign_keys.extend(db.foreign_keys)


def _resolve_cross_references(catalog: Catalog) -> None:
    """Verweise auf andere Datenbanken auf deren Objekte abbilden."""
    for db in catalog.databases:
        for obj in db.objects.values():
            for ref in obj.refs:
                if ref.external_db is None:
                    ref.target = gid(db.key, ref.target)
                    continue
                other = catalog.by_key(ref.external_db.lower())
                if other is None:
                    ref.resolved = False
                    catalog.unresolved_dbs.setdefault(ref.external_db, ref.source or "")
                    continue
                # Der Name der Nachbardatenbank kann anders geschrieben sein als
                # im Verweis (``[Faktura-DB]`` vs. ``FAKTURA-DB``).
                ref.external_db = other.name
                ref.target = gid(other.key, ref.target)
                ref.resolved = ref.target in catalog.objects

        for fk in db.foreign_keys:
            if not fk.ref_external_db:
                continue
            other = catalog.by_key(fk.ref_external_db.lower())
            if other is None:
                continue
            fk.ref_external_db = other.name
            candidate = gid(other.key, fk.ref_table)
            if candidate in catalog.objects:
                fk.ref_table = candidate


def dacpac_paths(sources: list[Path]) -> list[Path]:
    """Aus Dateien und Ordnern die Liste der .dacpac-Dateien machen."""
    out: list[Path] = []
    for source in sources:
        if source.is_dir():
            out.extend(sorted(source.glob("*.dacpac")))
        else:
            out.append(source)
    seen, unique = set(), []
    for path in out:
        resolved = path.resolve()
        if resolved not in seen:
            seen.add(resolved)
            unique.append(path)
    return unique
