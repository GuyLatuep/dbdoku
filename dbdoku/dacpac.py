"""Zugriff auf die ``model.xml`` in einer .dacpac.

Zwei Besonderheiten machen das noetig:

1. ``model.xml`` ist nicht XML-1.0-konform. Aus T-SQL-Stringliteralen stammende
   Steuerzeichen werden als ``&#x1E;`` o. ae. serialisiert; ein konformer Parser
   bricht darauf mit ``reference to invalid character number`` ab. Der
   ``_Sanitized``-Stream ersetzt solche Referenzen beim Lesen.
2. Die Datei ist gross (bei grossen Datenbanken einige zehn MB). Ein DOM-Parse kostet ~1 GB RAM,
   deshalb wird gestreamt und nach jedem Top-Level-Objekt aufgeraeumt.
"""

from __future__ import annotations

import io
import re
import zipfile
import xml.etree.ElementTree as ET
from collections.abc import Iterator

NS = "{http://schemas.microsoft.com/sqlserver/dac/Serialization/2012/02}"

# In XML 1.0 unzulaessige Zeichenreferenzen: alles < 0x20 ausser \t \n \r.
_BAD_REF = re.compile(
    rb"&#(?:"
    rb"x0*(?:[0-8BbCcEeFf]|1[0-9A-Fa-f])"   # hexadezimal
    rb"|0*(?:[0-8]|1[124-9]|2[0-9]|3[01])"  # dezimal
    rb");"
)
_MAX_REF = 12  # laengste Zeichenreferenz, die nicht ueber Chunks zerrissen werden darf


class DacpacError(Exception):
    """Die Datei laesst sich nicht als .dacpac lesen."""


class _Sanitized(io.RawIOBase):
    """Byte-Stream, der unzulaessige Zeichenreferenzen durch ``?`` ersetzt."""

    def __init__(self, raw: io.BufferedIOBase) -> None:
        self._raw = raw
        self._buf = b""
        self._eof = False
        self.replaced = 0

    def readable(self) -> bool:
        return True

    def readinto(self, target) -> int:  # type: ignore[override]
        want = len(target)
        while not self._eof and len(self._buf) < want + _MAX_REF:
            chunk = self._raw.read(1 << 20)
            if not chunk:
                self._eof = True
                break
            self._buf += chunk

        out, self._buf = self._buf[:want], self._buf[want:]
        if not self._eof:
            # Eine angefangene Entity nicht ueber die Chunk-Grenze zerreissen.
            cut = out.rfind(b"&")
            if cut != -1 and cut > len(out) - _MAX_REF:
                self._buf = out[cut:] + self._buf
                out = out[:cut]

        out, n = _BAD_REF.subn(b"?", out)
        self.replaced += n
        target[: len(out)] = out
        return len(out)


class DacpacReader:
    """Liest Metadaten und Modellobjekte aus einer .dacpac."""

    def __init__(self, path: str) -> None:
        self.path = path
        try:
            self._zip = zipfile.ZipFile(path)
        except zipfile.BadZipFile as exc:
            raise DacpacError(f"{path} ist kein gültiges .dacpac-Paket "
                              f"(kein ZIP-Archiv): {exc}") from exc
        if "model.xml" not in self._zip.namelist():
            self._zip.close()
            raise DacpacError(f"{path} enthält keine model.xml – "
                              "ist das wirklich eine .dacpac?")
        self.sanitized_refs = 0

    def close(self) -> None:
        self._zip.close()

    def __enter__(self) -> DacpacReader:
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def part(self, name: str) -> bytes | None:
        try:
            return self._zip.read(name)
        except KeyError:
            return None

    def metadata(self) -> dict[str, str]:
        """Name, Version und Erstellzeitpunkt aus DacMetadata.xml / Origin.xml."""
        meta: dict[str, str] = {}
        for part, keys in (
            ("DacMetadata.xml", ("Name", "Version", "Description")),
            ("Origin.xml", ("ProductVersion",)),
        ):
            raw = self.part(part)
            if not raw:
                continue
            root = ET.fromstring(raw.decode("utf-8-sig"))
            for key in keys:
                el = root.find(f".//{NS}{key}")
                if el is not None and el.text:
                    meta[key] = el.text
            if part == "Origin.xml":
                start = root.find(f".//{NS}Start")
                if start is not None and start.text:
                    meta["Created"] = start.text
        return meta

    def model_header(self) -> ET.Element | None:
        """Der ``<Header>``-Block (Assembly-Referenzen, Kompatibilitaetsgrad)."""
        for el in self._iter_raw(("Header",)):
            return el
        return None

    def iter_elements(self) -> Iterator[ET.Element]:
        """Alle Top-Level-``<Element>`` unter ``<Model>``, jeweils vollstaendig.

        Nach jedem ``yield`` wird der Teilbaum freigegeben; Aufrufer duerfen das
        Element danach nicht mehr verwenden.
        """
        yield from self._iter_raw(("Element",))

    def _iter_raw(self, tags: tuple[str, ...]) -> Iterator[ET.Element]:
        wanted = {NS + t for t in tags}
        with self._zip.open("model.xml") as raw:
            stream = _Sanitized(raw)
            ctx = ET.iterparse(io.BufferedReader(stream), events=("start", "end"))
            _, root = next(ctx)
            depth = 0
            for event, el in ctx:
                if el.tag not in wanted:
                    continue
                if event == "start":
                    depth += 1
                    continue
                depth -= 1
                if depth == 0:
                    yield el
                    el.clear()
                    root.clear()
            self.sanitized_refs += stream.replaced


# --------------------------------------------------------------------------
# kleine Helfer fuer den Umgang mit den Modell-Elementen
# --------------------------------------------------------------------------

def prop(el: ET.Element, name: str) -> str | None:
    """Wert einer ``<Property>`` — als Attribut *oder* als ``<Value>``-Kind.

    Beide Schreibweisen kommen im selben Modell vor (z. B. ``HeaderContents``).
    """
    for p in el.findall(f"{NS}Property"):
        if p.get("Name") != name:
            continue
        if (val := p.get("Value")) is not None:
            return val
        child = p.find(f"{NS}Value")
        if child is not None:
            return child.text or ""
        return ""
    return None


def flag(el: ET.Element, name: str) -> bool:
    return (prop(el, name) or "").lower() == "true"


def annotation(el: ET.Element, type_name: str) -> ET.Element | None:
    """Die erste ``<Annotation>`` eines Typs — dort steht z. B. der Kopftext."""
    for ann in el.findall(f"{NS}Annotation"):
        if ann.get("Type") == type_name:
            return ann
    return None


def relationship(el: ET.Element, name: str) -> ET.Element | None:
    for rel in el.findall(f"{NS}Relationship"):
        if rel.get("Name") == name:
            return rel
    return None


def entries(el: ET.Element, name: str) -> list[ET.Element]:
    """Die ``<Entry>``-Kinder einer benannten Relationship."""
    rel = relationship(el, name)
    return rel.findall(f"{NS}Entry") if rel is not None else []


def rel_references(el: ET.Element, name: str) -> list[ET.Element]:
    """Die ``<References>`` einer Relationship (eine Ebene tief)."""
    out = []
    for entry in entries(el, name):
        out.extend(entry.findall(f"{NS}References"))
    return out


def rel_elements(el: ET.Element, name: str) -> list[ET.Element]:
    """Die verschachtelten ``<Element>`` einer Relationship."""
    out = []
    for entry in entries(el, name):
        out.extend(entry.findall(f"{NS}Element"))
    return out
