"""Die kleinen Bausteine: Byte-Strom, Diagramme, Graph, Namen, Einfärbung.

Was sich ohne eine ganze .dacpac prüfen lässt, wird hier direkt geprüft.

    python3 -m unittest discover -s tests -v
"""

from __future__ import annotations

import io
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dbdoku import crud, erd, graph, highlight, render       # noqa: E402
from dbdoku.dacpac import NS, DacpacReader, _Sanitized, flag, prop   # noqa: E402

XMLNS = NS[1:-1]     # NS ist Clark-Notation ({uri}); als xmlns brauchen wir die URI
from dbdoku.model import (Catalog, Database, DbObject, ForeignKey,   # noqa: E402
                          Ref, display, gid, split_name)

from test_crud import katalog                                # noqa: E402


def fk(name: str, table: str, cols: list[str], ref_table: str,
       ref_cols: list[str] = None, ref_db: str = None) -> ForeignKey:
    return ForeignKey(name=name, table=table, columns=cols, ref_table=ref_table,
                      ref_columns=ref_cols or cols, ref_external_db=ref_db)


def mit_fks(cat: Catalog, *fks: ForeignKey) -> graph.Graph:
    cat.foreign_keys.extend(fks)
    return graph.build(cat, crud.analyze(cat))


class SanitizedStreamTest(unittest.TestCase):
    """Ungültige Zeichenreferenzen ersetzen – auch über Chunk-Grenzen hinweg."""

    @staticmethod
    def read_all(data: bytes, chunk: int) -> tuple[bytes, int]:
        stream = _Sanitized(io.BytesIO(data))
        out = bytearray()
        while True:
            buf = bytearray(chunk)
            n = stream.readinto(buf)
            if not n:
                break
            out += buf[:n]
        return bytes(out), stream.replaced

    def test_ersetzt_ungueltige_referenz(self) -> None:
        out, n = self.read_all(b"<a>x&#x1E;y</a>", 4096)
        self.assertEqual(out, b"<a>x?y</a>")
        self.assertEqual(n, 1)

    def test_gueltige_referenz_bleibt(self) -> None:
        out, n = self.read_all(b"<a>&amp;&#x20;&#65;</a>", 4096)
        self.assertEqual(out, b"<a>&amp;&#x20;&#65;</a>")
        self.assertEqual(n, 0)

    def test_referenz_ueber_die_chunk_grenze(self) -> None:
        """Winzige Puffer zerschneiden `&#x1E;` – ersetzt werden muss sie trotzdem."""
        data = b"<a>" + b"y" * 30 + b"&#x1E;" + b"z" * 30 + b"</a>"
        for chunk in (5, 7, 8, 16, 33):
            with self.subTest(chunk=chunk):
                out, n = self.read_all(data, chunk)
                self.assertEqual(out, data.replace(b"&#x1E;", b"?"))
                self.assertEqual(n, 1)

    def test_kaufmaennisches_und_am_ende(self) -> None:
        """Ein einzelnes `&` am Dateiende darf nicht hängenbleiben."""
        out, _ = self.read_all(b"<a>x&</a>", 4)
        self.assertEqual(out, b"<a>x&</a>")


class ReaderTest(unittest.TestCase):
    def test_origin_xml_liefert_erstellungszeit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "x.dacpac"
            with zipfile.ZipFile(path, "w") as z:
                z.writestr("model.xml",
                           f'<DataSchemaModel xmlns="{XMLNS}"><Model /></DataSchemaModel>')
                z.writestr("DacMetadata.xml",
                           f'<DacType xmlns="{XMLNS}"><Name>X</Name></DacType>')
                z.writestr("Origin.xml",
                           f'<DacOrigin xmlns="{XMLNS}">'
                           f'<Start>2024-05-06T07:08:09</Start></DacOrigin>')
            with DacpacReader(str(path)) as reader:
                meta = reader.metadata()
        self.assertEqual(meta["Created"], "2024-05-06T07:08:09")
        self.assertEqual(meta["Name"], "X")


class PropTest(unittest.TestCase):
    @staticmethod
    def el(xml: str) -> ET.Element:
        return ET.fromstring(xml.replace("<E", f"<E xmlns='{XMLNS}'", 1))

    def test_wert_als_attribut(self) -> None:
        el = self.el('<E><Property Name="A" Value="1" /></E>')
        self.assertEqual(prop(el, "A"), "1")

    def test_wert_als_kindelement(self) -> None:
        el = self.el('<E><Property Name="A"><Value>2</Value></Property></E>')
        self.assertEqual(prop(el, "A"), "2")

    def test_property_ganz_ohne_wert(self) -> None:
        el = self.el('<E><Property Name="A" /></E>')
        self.assertEqual(prop(el, "A"), "")

    def test_unbekannte_property(self) -> None:
        el = self.el('<E><Property Name="A" Value="1" /></E>')
        self.assertIsNone(prop(el, "B"))

    def test_flag(self) -> None:
        el = self.el('<E><Property Name="J" Value="True" />'
                     '<Property Name="N" Value="False" /></E>')
        self.assertTrue(flag(el, "J"))
        self.assertFalse(flag(el, "N"))
        self.assertFalse(flag(el, "fehlt"))


class NamenTest(unittest.TestCase):
    def test_maskierte_klammer(self) -> None:
        """`]]` innerhalb eines Bezeichners ist eine einzelne `]`."""
        self.assertEqual(split_name("[dbo].[A]]B]"), ["dbo", "A]B"])

    def test_gemischt_maskiert_und_nackt(self) -> None:
        self.assertEqual(split_name("dbo.[Mit Platz].Id"),
                         ["dbo", "Mit Platz", "Id"])

    def test_anzeigeform(self) -> None:
        self.assertEqual(display("[dbo].[Kunde]"), "dbo.Kunde")


class KatalogZugriffTest(unittest.TestCase):
    def setUp(self) -> None:
        self.cat = katalog(("Haupt", ["dbo.A"]), ("Nachbar", ["dbo.B"]))

    def test_db_of(self) -> None:
        db = self.cat.db_of(gid("nachbar", "[dbo].[B]"))
        self.assertIsNotNone(db)
        self.assertEqual(db.name, "Nachbar")

    def test_db_of_unbekannt(self) -> None:
        self.assertIsNone(self.cat.db_of("fehlt|[dbo].[X]"))


class GraphTest(unittest.TestCase):
    def setUp(self) -> None:
        self.cat = katalog(("Haupt", ["dbo.Kunde", "dbo.Bestellung"]),
                           ("Nachbar", ["dbo.Fern"]))
        self.kunde = gid("haupt", "[dbo].[Kunde]")
        self.best = gid("haupt", "[dbo].[Bestellung]")
        self.fern = gid("nachbar", "[dbo].[Fern]")

    def test_nachbarn_beider_richtungen(self) -> None:
        g = mit_fks(self.cat,
                    fk("FK1", self.best, ["KundeId"], self.kunde),
                    fk("FK2", self.kunde, ["FernId"], self.fern))
        self.assertEqual(g.neighbours(self.kunde), [self.fern, self.best])

    def test_nachbarn_ohne_ziel_im_katalog(self) -> None:
        """Ein Fremdschlüssel ins Nirgendwo taucht nicht als Nachbar auf."""
        g = mit_fks(self.cat,
                    fk("FK", self.kunde, ["X"], "fehlt|[dbo].[Weg]", ref_db="Fehlt"))
        self.assertEqual(g.neighbours(self.kunde), [])

    def test_nachbarn_werden_nicht_doppelt_gezaehlt(self) -> None:
        g = mit_fks(self.cat,
                    fk("FK1", self.best, ["A"], self.kunde),
                    fk("FK2", self.best, ["B"], self.kunde))
        self.assertEqual(g.neighbours(self.kunde), [self.best])

    def test_is_cross_db(self) -> None:
        g = mit_fks(self.cat)
        self.assertTrue(g.is_cross_db(self.kunde, self.fern))
        self.assertFalse(g.is_cross_db(self.kunde, self.best))

    def test_selbstbezug_erzeugt_keine_kante(self) -> None:
        """Eine Routine, die sich selbst referenziert, ruft sich nicht auf."""
        oid = gid("haupt", "[dbo].[proc]")
        proc = DbObject(id=oid, kind="procedure", schema="dbo", name="proc",
                        refs=[Ref(target=oid)])
        self.cat.objects[oid] = proc
        self.cat.by_key("haupt").objects[oid] = proc
        g = mit_fks(self.cat)
        self.assertNotIn(oid, g.calls)

    def test_einstiegspunkte_je_datenbank(self) -> None:
        for name in ("aussen", "innen"):
            oid = gid("haupt", f"[dbo].[{name}]")
            self.cat.objects[oid] = DbObject(id=oid, kind="procedure",
                                             schema="dbo", name=name)
            self.cat.by_key("haupt").objects[oid] = self.cat.objects[oid]
        self.cat.objects[gid("haupt", "[dbo].[aussen]")].refs = [
            Ref(target=gid("haupt", "[dbo].[innen]"))]
        g = mit_fks(self.cat)
        self.assertEqual(g.entry_points("haupt"), [gid("haupt", "[dbo].[aussen]")])
        self.assertEqual(g.entry_points("nachbar"), [])


class DiagrammTest(unittest.TestCase):
    def setUp(self) -> None:
        self.cat = katalog(("Haupt", ["dbo.Kunde", "dbo.Bestellung"]))
        self.kunde = gid("haupt", "[dbo].[Kunde]")
        self.best = gid("haupt", "[dbo].[Bestellung]")

    @staticmethod
    def url(target: str) -> str:
        return f"{target}.html"

    def test_gleiche_beziehung_wird_nur_einmal_gezeichnet(self) -> None:
        """Zwei Constraints mit gleichem Ziel und gleichen Spalten: ein Kasten."""
        g = mit_fks(self.cat,
                    fk("FK1", self.best, ["KundeId"], self.kunde),
                    fk("FK2", self.best, ["KundeId"], self.kunde))
        svg, shown, total = erd.diagram(self.kunde, g, self.url)
        self.assertEqual(shown, 1)
        self.assertEqual(svg.count("<rect"), 2)      # Nachbar plus Mittelkasten

    def test_ausgehende_beziehung_wird_entdoppelt(self) -> None:
        g = mit_fks(self.cat,
                    fk("FK1", self.kunde, ["A"], self.best),
                    fk("FK2", self.kunde, ["A"], self.best))
        _, shown, _ = erd.diagram(self.kunde, g, self.url)
        self.assertEqual(shown, 1)

    def test_unauflösbares_ziel_wird_ohne_verweis_gezeichnet(self) -> None:
        g = mit_fks(self.cat,
                    fk("FK", self.kunde, ["X"], "[dbo].[Weg]", ref_db="Fehlt"))
        svg, shown, _ = erd.diagram(self.kunde, g, self.url)
        self.assertEqual(shown, 1)
        self.assertIn("Fehlt: dbo.Weg", svg)

    def test_beziehung_ohne_spalten_bekommt_keine_beschriftung(self) -> None:
        g = mit_fks(self.cat, fk("FK", self.best, [], self.kunde))
        svg, _, _ = erd.diagram(self.kunde, g, self.url)
        self.assertIn("<path", svg)
        self.assertNotIn("erd-label", svg)

    def test_zu_viele_nachbarn_werden_abgeschnitten(self) -> None:
        cat = katalog(("Haupt", ["dbo.Kunde"] + [f"dbo.T{i}" for i in range(15)]))
        kunde = gid("haupt", "[dbo].[Kunde]")
        g = mit_fks(cat, *[fk(f"FK{i}", gid("haupt", f"[dbo].[T{i}]"),
                              [f"S{i}"], kunde) for i in range(15)])
        _, shown, total = erd.diagram(kunde, g, self.url)
        self.assertEqual(total, 15)
        self.assertEqual(shown, erd.MAX_SIDE)

    def test_beschriftung_eines_unbekannten_ziels(self) -> None:
        """Rückfallebene: ohne Objekt bleibt nur der Name in Klammernotation."""
        self.assertEqual(erd._label(self.cat, "[dbo].[Weg]", "haupt"), "dbo.Weg")

    def test_eingehende_beziehung_aus_unbekannter_tabelle(self) -> None:
        """Zeigt ein Fremdschlüssel von nirgendwo her, wird er nicht gezeichnet."""
        g = mit_fks(self.cat,
                    fk("FK", "fehlt|[dbo].[Weg]", ["X"], self.kunde))
        _, shown, _ = erd.diagram(self.kunde, g, self.url)
        self.assertEqual(shown, 0)

    def test_datenbankdiagramm_unbekannter_schluessel(self) -> None:
        g = mit_fks(self.cat)
        self.assertEqual(erd.database_diagram("gibtesnicht", g, self.url),
                         ("", 0, 0))

    def test_mermaid_ohne_beziehungen_ist_leer(self) -> None:
        g = mit_fks(self.cat)
        self.assertEqual(erd.mermaid(self.kunde, g), "")


class HighlightTest(unittest.TestCase):
    def test_temporaere_tabelle(self) -> None:
        self.assertIn('<span class="t">#tmp</span>',
                      highlight.highlight("SELECT * FROM #tmp"))

    def test_variable_kommentar_und_zahl(self) -> None:
        out = highlight.highlight("-- Hinweis\nSELECT @x, 42, 'text', [dbo].[T]")
        self.assertIn('<span class="c">-- Hinweis</span>', out)
        self.assertIn('<span class="v">@x</span>', out)
        self.assertIn('<span class="n">42</span>', out)
        self.assertIn('<span class="s">&#x27;text&#x27;</span>', out)
        self.assertIn('<span class="id">[dbo]</span>', out)


class RendererBausteinTest(unittest.TestCase):
    def setUp(self) -> None:
        cat = katalog(("Haupt", ["dbo.Kunde"]))
        with tempfile.TemporaryDirectory() as tmp:
            self.r = render.Renderer(cat, mit_fks(cat), Path(tmp) / "docs")

    def test_verweis_auf_ein_objekt_ohne_seite(self) -> None:
        """Ohne Zielseite bleibt der Name stehen, aber unverlinkt."""
        out = self.r.link("haupt|[dbo].[GibtEsNicht]", 0, "dbo.GibtEsNicht")
        self.assertEqual(out, '<span class="missing">dbo.GibtEsNicht</span>')

    def test_leere_bausteine_liefern_nichts(self) -> None:
        self.assertEqual(self.r.details("Titel", ""), "")
        self.assertEqual(self.r.code(""), "")
        self.assertEqual(self.r.table(["A"], []), "")
        self.assertEqual(self.r.section("Titel", ""), "")

    def test_details_aufgeklappt(self) -> None:
        self.assertIn("<details open>", self.r.details("T", "x", open_=True))


if __name__ == "__main__":
    unittest.main()
