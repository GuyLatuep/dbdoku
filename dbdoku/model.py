"""Datenmodell der extrahierten Datenbank.

Kanonische Objekt-Id ist der DacFx-Name in Klammernotation, z. B. ``[dbo].[Person]``.
Der Anzeigename ist die punktierte Form ohne Klammern, z. B. ``dbo.Person``.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Objektarten und ihre Darstellung in der Oberflaeche.
KINDS = {
    "table": ("Tabelle", "Tabellen", "tabellen"),
    "view": ("Sicht", "Sichten", "sichten"),
    "procedure": ("Prozedur", "Prozeduren", "prozeduren"),
    "function": ("Funktion", "Funktionen", "funktionen"),
    "trigger": ("Trigger", "Trigger", "trigger"),
    "tabletype": ("Tabellentyp", "Tabellentypen", "typen"),
}

# Zugriffsarten in fester Reihenfolge (Select, Insert, Update, Delete).
ACCESS_ORDER = "SIUD"
ACCESS_LABEL = {
    "S": "liest",
    "I": "fuegt ein",
    "U": "aendert",
    "D": "loescht",
}


def split_name(name: str) -> list[str]:
    """``[dbo].[Person].[Id]`` -> ``['dbo', 'Person', 'Id']``.

    Verdoppelte schliessende Klammern sind in DacFx die Maskierung fuer ``]``.
    """
    parts: list[str] = []
    i, n = 0, len(name)
    while i < n:
        if name[i] == "[":
            i += 1
            buf = []
            while i < n:
                if name[i] == "]":
                    if i + 1 < n and name[i + 1] == "]":
                        buf.append("]")
                        i += 2
                        continue
                    i += 1
                    break
                buf.append(name[i])
                i += 1
            parts.append("".join(buf))
        elif name[i] == ".":
            i += 1
        else:  # unmaskierter Bezeichner
            j = i
            while j < n and name[j] != ".":
                j += 1
            parts.append(name[i:j])
            i = j
    return parts


def display(name: str) -> str:
    """Klammernotation -> punktierte Anzeigeform."""
    return ".".join(split_name(name))


@dataclass
class Ref:
    """Eine aufgeloeste Referenz aus einer Relationship.

    Nach dem Zusammenfuehren mehrerer .dacpac (siehe :mod:`dbdoku.catalog`)
    enthaelt ``target`` eine katalogweite Id; ``external_db`` bleibt gesetzt,
    solange die Referenz aus einer anderen Datenbank stammt.
    """

    target: str                     # Objekt-Id, katalogweit eindeutig
    column: str | None = None       # Spaltenname, falls die Referenz spaltengenau war
    external_db: str | None = None  # Fremddatenbank, falls objektfremd
    source: str | None = None       # ExternalSource-Attribut (…dacpac)
    resolved: bool = True           # False = Ziel ist in keiner geladenen Datenbank

    @property
    def is_external(self) -> bool:
        return self.external_db is not None


@dataclass
class Column:
    name: str
    type: str = ""
    nullable: bool = True
    identity: str | None = None      # 'seed,increment' falls Identity
    default: str | None = None
    collation: str | None = None
    computed: bool = False
    rowguid: bool = False
    description: str | None = None
    refs: list[Ref] = field(default_factory=list)  # bei berechneten/Sicht-Spalten


@dataclass
class Parameter:
    name: str
    type: str = ""
    output: bool = False
    readonly: bool = False
    default: str | None = None


@dataclass
class Index:
    name: str | None
    columns: list[str] = field(default_factory=list)
    included: list[str] = field(default_factory=list)
    unique: bool = False
    clustered: bool = False
    kind: str = "index"  # 'index' | 'primarykey' | 'unique'


@dataclass
class ForeignKey:
    name: str
    table: str
    columns: list[str]
    ref_table: str
    ref_columns: list[str]
    on_delete: str | None = None
    on_update: str | None = None
    ref_external_db: str | None = None


@dataclass
class Check:
    name: str | None
    expression: str


@dataclass
class DbObject:
    """Tabelle, Sicht, Prozedur, Funktion, Trigger oder Tabellentyp."""

    id: str
    kind: str
    schema: str = ""
    name: str = ""
    db: str = ""                    # Name der Datenbank, zu der das Objekt gehoert
    description: str | None = None

    # Tabellen / Sichten / Tabellentypen
    columns: list[Column] = field(default_factory=list)
    indexes: list[Index] = field(default_factory=list)
    checks: list[Check] = field(default_factory=list)

    # Routinen
    parameters: list[Parameter] = field(default_factory=list)
    header: str = ""
    body: str = ""
    returns: str | None = None
    routine_type: str = ""          # 'procedure', 'scalar', 'inline_tvf', …
    clr: bool = False
    trigger_on: str | None = None
    trigger_events: list[str] = field(default_factory=list)

    # Beziehungen
    refs: list[Ref] = field(default_factory=list)   # ausgehende Abhaengigkeiten
    dynamic_sql: bool = False

    @property
    def display(self) -> str:
        return f"{self.schema}.{self.name}" if self.schema else self.name

    @property
    def qualified(self) -> str:
        """Mit Datenbank davor — fuer Verweise ueber Datenbankgrenzen."""
        return f"{self.db}.{self.display}" if self.db else self.display

    @property
    def sql(self) -> str:
        """Vollstaendiger Quelltext, soweit im Modell vorhanden.

        DacFx legt Kopf (``CREATE PROCEDURE … AS``) und Rumpf getrennt ab.
        """
        head = self.header.strip("\r\n")
        if head and self.body:
            return f"{head}\n{self.body}"
        return head or self.body


@dataclass
class Database:
    name: str = ""
    version: str = ""
    created: str = ""
    collation: str = ""
    compatibility: str = ""
    source: str = ""                # Dateiname der .dacpac
    objects: dict[str, DbObject] = field(default_factory=dict)
    foreign_keys: list[ForeignKey] = field(default_factory=list)
    schemas: set[str] = field(default_factory=set)
    external_dbs: dict[str, str] = field(default_factory=dict)  # db -> quelle.dacpac
    assemblies: list[str] = field(default_factory=list)

    @property
    def key(self) -> str:
        """Katalogweiter Schluessel. SQL-Server-Datenbanknamen sind nicht
        gross-/kleinschreibungsempfindlich: eine Referenz auf ``[Faktura-DB]``
        meint dieselbe Datenbank wie die .dacpac namens ``FAKTURA-DB``."""
        return self.name.lower()

    def of_kind(self, kind: str) -> list[DbObject]:
        return sorted(
            (o for o in self.objects.values() if o.kind == kind),
            key=lambda o: (o.schema.lower(), o.name.lower()),
        )

    def count(self, kind: str) -> int:
        return sum(1 for o in self.objects.values() if o.kind == kind)

    @property
    def total(self) -> int:
        return len(self.objects)


@dataclass
class Catalog:
    """Mehrere zusammengehoerende Datenbanken mit aufgeloesten Querverweisen."""

    databases: list[Database] = field(default_factory=list)
    objects: dict[str, DbObject] = field(default_factory=dict)   # katalogweite Id
    foreign_keys: list[ForeignKey] = field(default_factory=list)
    unresolved_dbs: dict[str, str] = field(default_factory=dict)  # name -> quelle
    sanitized_refs: int = 0

    def by_key(self, key: str) -> Database | None:
        for db in self.databases:
            if db.key == key:
                return db
        return None

    def db_of(self, gid: str) -> Database | None:
        return self.by_key(gid.split("|", 1)[0])

    @property
    def total(self) -> int:
        return len(self.objects)


def gid(db_key: str, oid: str) -> str:
    """Katalogweite Objekt-Id aus Datenbankschluessel und lokalem Namen."""
    return f"{db_key}|{oid}"
