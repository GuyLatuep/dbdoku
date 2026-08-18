"""Zugriffsart je Tabelle (Select/Insert/Update/Delete) aus dem T-SQL-Body.

Die *Menge* der beruehrten Objekte stammt aus den von DacFx aufgeloesten
Abhaengigkeiten und ist damit exakt. Hier wird ausschliesslich die *Art* des
Zugriffs bestimmt, und die steht im Modell nicht — sie muss aus dem Quelltext
gelesen werden.

Grenzen des Verfahrens: dynamisch zusammengebautes SQL ist nicht analysierbar.
Betroffene Routinen werden ueber ``DbObject.dynamic_sql`` markiert und in der
Ausgabe mit einem Hinweis versehen.
"""

from __future__ import annotations

import re

from .model import Catalog, DbObject, split_name

# Ein Objektbezeichner: [a].[b].[c] oder a.b.c oder @var oder #temp
_NAME = r"(?:\[[^\]]*\]|[A-Za-z_@#][\w@#$]*)(?:\s*\.\s*(?:\[[^\]]*\]|[\w@#$]*))*"

# Woerter, die niemals ein Tabellenalias sind.
_NOT_ALIAS = {
    "as", "on", "where", "inner", "left", "right", "full", "cross", "outer",
    "join", "group", "order", "having", "set", "with", "union", "except",
    "intersect", "option", "apply", "pivot", "unpivot", "for", "when", "and",
    "or", "select", "insert", "update", "delete", "merge", "exec", "execute",
    "values", "into", "from", "begin", "end", "if", "else", "while", "return",
    "declare", "print", "raiserror", "go", "using", "output", "top", "distinct",
    "case", "then", "not", "in", "exists", "between", "like", "is", "null",
    "commit", "rollback", "tran", "transaction", "open", "close", "fetch",
    "cursor", "table", "index", "nolock", "readpast", "updlock", "rowlock",
    "holdlock", "tablock", "tablockx", "xlock", "serializable", "snapshot",
}

_WRITES: list[tuple[str, re.Pattern[str]]] = [
    ("I", re.compile(r"\bINSERT\s+(?:TOP\s*\([^)]*\)\s*)?(?:INTO\s+)?(" + _NAME + ")",
                     re.IGNORECASE)),
    ("U", re.compile(r"\bUPDATE\s+(?:TOP\s*\([^)]*\)\s*)?(" + _NAME + ")", re.IGNORECASE)),
    ("D", re.compile(r"\bDELETE\s+(?:TOP\s*\([^)]*\)\s*)?(?:FROM\s+)?(" + _NAME + ")",
                     re.IGNORECASE)),
    ("I", re.compile(r"\bMERGE\s+(?:TOP\s*\([^)]*\)\s*)?(?:INTO\s+)?(" + _NAME + ")",
                     re.IGNORECASE)),
    ("D", re.compile(r"\bTRUNCATE\s+TABLE\s+(" + _NAME + ")", re.IGNORECASE)),
    ("I", re.compile(r"\bSELECT\b.*?\bINTO\s+(" + _NAME + ")", re.IGNORECASE | re.DOTALL)),
]

# Quelle eines Alias: FROM/JOIN/UPDATE/INTO <objekt> [AS] <alias>
_ALIAS = re.compile(
    r"\b(?:FROM|JOIN|UPDATE|INTO)\s+(" + _NAME + r")\s+(?:AS\s+)?(\[[^\]]+\]|[A-Za-z_]\w*)",
    re.IGNORECASE,
)

# Eine MERGE-Anweisung kann zusaetzlich UPDATE und DELETE ausloesen.
_MERGE_UPDATE = re.compile(r"\bWHEN\s+MATCHED\b.{0,120}?\bTHEN\s+UPDATE\b",
                           re.IGNORECASE | re.DOTALL)
_MERGE_DELETE = re.compile(r"\bWHEN\s+MATCHED\b.{0,120}?\bTHEN\s+DELETE\b",
                           re.IGNORECASE | re.DOTALL)


def strip_noise(sql: str) -> str:
    """Kommentare und Stringliterale entfernen, Bezeichner erhalten.

    Ersetzt jedes entfernte Stueck durch ein Leerzeichen, damit Wortgrenzen
    erhalten bleiben (``FROM'x'JOIN`` wird nicht zu ``FROMJOIN``).
    """
    out: list[str] = []
    i, n = 0, len(sql)
    while i < n:
        c = sql[i]
        if c == "-" and sql.startswith("--", i):
            j = sql.find("\n", i)
            i = n if j == -1 else j
            out.append(" ")
        elif c == "/" and sql.startswith("/*", i):
            depth, i = 1, i + 2          # T-SQL erlaubt verschachtelte Blockkommentare
            while i < n and depth:
                if sql.startswith("/*", i):
                    depth, i = depth + 1, i + 2
                elif sql.startswith("*/", i):
                    depth, i = depth - 1, i + 2
                else:
                    i += 1
            out.append(" ")
        elif c == "'":
            i += 1
            while i < n:
                if sql[i] == "'":
                    if i + 1 < n and sql[i + 1] == "'":
                        i += 2
                        continue
                    i += 1
                    break
                i += 1
            out.append(" ")
        elif c == "[":
            j = sql.find("]", i)
            if j == -1:
                out.append(sql[i:])
                break
            out.append(sql[i:j + 1])
            i = j + 1
        else:
            out.append(c)
            i += 1
    return "".join(out)


def _normalize(raw: str) -> list[str]:
    """Rohen Bezeichner in Namensteile zerlegen (Klammern und Leerraum weg)."""
    return [p for p in split_name(re.sub(r"\s*\.\s*", ".", raw.strip())) if p]


class Resolver:
    """Bildet Namen aus dem Quelltext auf katalogweite Objekt-Ids ab.

    Kennt alle geladenen Datenbanken, damit dreiteilige Namen wie
    ``[Fremd-DB].dbo.Kunde`` auf die Tabelle *jener* Datenbank zeigen und
    nicht auf die gleichnamige der eigenen.
    """

    def __init__(self, catalog: Catalog) -> None:
        self.by_qualified: dict[tuple[str, str], str] = {}   # (dbkey, schema.name)
        self.by_bare: dict[tuple[str, str], str | None] = {}  # None = mehrdeutig
        self.known_dbs = {db.key for db in catalog.databases}
        for oid, obj in catalog.objects.items():
            if obj.kind not in ("table", "view"):
                continue
            dbkey = oid.split("|", 1)[0]
            self.by_qualified[(dbkey, f"{obj.schema}.{obj.name}".lower())] = oid
            bare = (dbkey, obj.name.lower())
            self.by_bare[bare] = None if bare in self.by_bare else oid

    def resolve(self, raw: str, home: str) -> str | None:
        """``home`` ist der Datenbankschluessel der aufrufenden Routine."""
        parts = _normalize(raw)
        if not parts:
            return None
        last = parts[-1]
        if last.startswith(("@", "#")):
            return None              # Tabellenvariable oder temporaere Tabelle

        dbkey = home
        if len(parts) >= 3:
            named = parts[-3].lower()
            if named and named != home:
                if named not in self.known_dbs:
                    return None      # Datenbank nicht geladen: nicht lokal deuten
                dbkey = named
        if len(parts) >= 2:
            if (oid := self.by_qualified.get((dbkey, f"{parts[-2]}.{last}".lower()))):
                return oid
        return self.by_bare.get((dbkey, last.lower()))


def analyze(catalog: Catalog) -> dict[str, dict[str, str]]:
    """Zugriffsarten aller Routinen und Sichten ermitteln.

    Rueckgabe: ``{routine_id: {tabellen_id: "SIU"}}`` — die Buchstaben in der
    Reihenfolge Select, Insert, Update, Delete. Ids sind katalogweit, Zugriffe
    ueber Datenbankgrenzen stehen also ganz normal mit drin.
    """
    resolver = Resolver(catalog)
    result: dict[str, dict[str, str]] = {}

    for oid, obj in catalog.objects.items():
        if obj.kind not in ("procedure", "function", "trigger", "view"):
            continue
        result[oid] = _analyze_one(obj, resolver, catalog)
    return result


def _analyze_one(obj: DbObject, resolver: Resolver, catalog: Catalog) -> dict[str, str]:
    access: dict[str, set[str]] = {}
    home = obj.id.split("|", 1)[0]

    # 1. Alle aufgeloesten Abhaengigkeiten auf Tabellen/Sichten gelten als Lesezugriff.
    for ref in obj.refs:
        if not ref.resolved:
            continue
        target = catalog.objects.get(ref.target)
        if target is not None and target.kind in ("table", "view"):
            access.setdefault(ref.target, set()).add("S")

    # 2. Schreibzugriffe aus dem Quelltext nachtragen.
    sql = strip_noise(obj.sql)
    if sql.strip():
        aliases: dict[str, str] = {}
        for match in _ALIAS.finditer(sql):
            alias = _normalize(match.group(2))
            if not alias or alias[-1].lower() in _NOT_ALIAS:
                continue
            if (oid := resolver.resolve(match.group(1), home)) is not None:
                aliases[alias[-1].lower()] = oid

        for letter, pattern in _WRITES:
            for match in pattern.finditer(sql):
                raw = match.group(1)
                oid = resolver.resolve(raw, home)
                if oid is None:
                    parts = _normalize(raw)
                    oid = aliases.get(parts[-1].lower()) if parts else None
                if oid is None:
                    continue
                access.setdefault(oid, set()).add(letter)
                if letter == "I" and match.group(0).lower().lstrip().startswith("merge"):
                    tail = sql[match.end():match.end() + 4000]
                    if _MERGE_UPDATE.search(tail):
                        access[oid].add("U")
                    if _MERGE_DELETE.search(tail):
                        access[oid].add("D")

    return {
        oid: "".join(letter for letter in "SIUD" if letter in letters)
        for oid, letters in sorted(access.items())
    }
