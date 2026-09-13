"""Ausgabe für einen Katalog, der die selteneren Objektarten enthält.

Gerendert wird das erweiterte Modell aus ``test_extract_extended``: Sichten,
Trigger, Tabellenfunktionen, CLR, Indizes und Check-Constraints, dazu die
Sonderfälle des Katalogs – gleichnamige Datenbanken, eine leere Datenbank und
ein Fremdschlüssel in eine Nachbardatenbank, die einmal mitgeladen ist und
einmal nicht.

    python3 -m unittest discover -s tests -v
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dbdoku import catalog as cm, crud, graph, render       # noqa: E402
from dbdoku.__main__ import check_links                     # noqa: E402
from dbdoku.model import gid                                # noqa: E402

from test_dbdoku import NS, make_dacpac                     # noqa: E402
from test_extract_extended import EXTENDED, METADATA        # noqa: E402

NACHBAR = f"""<?xml version="1.0" encoding="utf-8"?>
<DataSchemaModel FileFormatVersion="1.2" SchemaVersion="2.9" xmlns="{NS}">
 <Model>
  <Element Type="SqlTable" Name="[dbo].[Fern]">
   <Relationship Name="Columns"><Entry>
    <Element Type="SqlSimpleColumn" Name="[dbo].[Fern].[FernId]">
     <Relationship Name="TypeSpecifier"><Entry>
      <Element Type="SqlTypeSpecifier"><Relationship Name="Type"><Entry>
       <References ExternalSource="BuiltIns" Name="[int]" />
      </Entry></Relationship></Element>
     </Entry></Relationship>
    </Element>
   </Entry></Relationship>
  </Element>
 </Model>
</DataSchemaModel>
"""

NACHBAR_META = f"""<?xml version="1.0" encoding="utf-8"?>
<DacType xmlns="{NS}"><Name>Nachbar</Name><Version>1.0.0.0</Version></DacType>
"""

LEER = f"""<?xml version="1.0" encoding="utf-8"?>
<DataSchemaModel xmlns="{NS}"><Model /></DataSchemaModel>
"""


def _meta(name: str) -> str:
    return (f'<?xml version="1.0" encoding="utf-8"?>'
            f'<DacType xmlns="{NS}"><Name>{name}</Name></DacType>')


def _mit_tabelle(table: str) -> str:
    return f"""<?xml version="1.0" encoding="utf-8"?>
<DataSchemaModel xmlns="{NS}"><Model>
 <Element Type="SqlTable" Name="[dbo].[{table}]" />
</Model></DataSchemaModel>
"""


def render_to(tmp: Path, paths: list[Path]) -> tuple[Path, object]:
    catalog = cm.load(paths)
    g = graph.build(catalog, crud.analyze(catalog))
    out = tmp / "docs"
    render.Renderer(catalog, g, out, "Katalog").write()
    return out, catalog


class ErweiterterKatalogTest(unittest.TestCase):
    """Erweiterte Datenbank samt Nachbardatenbank, alles auflösbar."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory()
        tmp = Path(cls._tmp.name)
        paths = [make_dacpac(tmp, "Erweitert", EXTENDED, METADATA),
                 make_dacpac(tmp, "Nachbar", NACHBAR, NACHBAR_META)]
        cls.out, cls.catalog = render_to(tmp, paths)

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    def page(self, *parts: str) -> str:
        return (self.out.joinpath(*parts)).read_text(encoding="utf-8")

    def test_keine_toten_verweise(self) -> None:
        self.assertEqual(check_links(self.out, quiet=True), 0)

    def test_tabellenseite_zeigt_spaltenmerkmale(self) -> None:
        page = self.page("ErweitertDb", "tabellen", "dbo.Artikel.html")
        self.assertIn("IDENTITY(1000,5)", page)
        self.assertIn("berechnet", page)
        self.assertIn("ROWGUIDCOL", page)
        self.assertIn("Alle Artikel", page)          # Tabellenbeschreibung
        self.assertIn("nvarchar(max)", page)
        self.assertIn("decimal(18,2)", page)

    def test_tabellenseite_zeigt_indizes_und_checks(self) -> None:
        page = self.page("ErweitertDb", "tabellen", "dbo.Artikel.html")
        self.assertIn("UQ_Artikel_Nummer", page)
        self.assertIn("IX_Artikel_Bezeichnung", page)
        self.assertIn("CK_Artikel_Preis", page)
        self.assertIn("gruppiert", page)
        self.assertIn("eindeutig", page)

    def test_ddl_wird_rekonstruiert(self) -> None:
        page = self.page("ErweitertDb", "tabellen", "dbo.Artikel.html")
        self.assertIn("dbo.Artikel (", page)     # eingefärbt: CREATE TABLE …
        # Schlüsselwörter stecken in <span>; geprüft wird, was dazwischen steht.
        self.assertIn("Latin1_General_BIN2", page)
        self.assertIn("CLUSTERED", page)
        self.assertIn("INCLUDE (", page)
        self.assertIn("[FK_Artikel_Fern]", page)
        self.assertIn("[CK_Artikel_Preis]", page)

    def test_fremdschluessel_in_die_nachbardatenbank_ist_verlinkt(self) -> None:
        page = self.page("ErweitertDb", "tabellen", "dbo.Artikel.html")
        self.assertIn("Nachbar.dbo.Fern", page)
        self.assertIn("../../Nachbar/tabellen/dbo.Fern.html", page)

    def test_nachbartabelle_kennt_ihren_nutzer(self) -> None:
        page = self.page("Nachbar", "tabellen", "dbo.Fern.html")
        self.assertIn("ErweitertDb.dbo.Artikel", page)

    def test_sichtseite(self) -> None:
        page = self.page("ErweitertDb", "sichten", "dbo.vArtikel.html")
        self.assertIn("vArtikel]", page)         # eingefärbt: CREATE VIEW …
        self.assertIn("dbo.Artikel", page)

    def test_triggerseite(self) -> None:
        page = self.page("ErweitertDb", "trigger", "dbo.trArtikel.html")
        self.assertIn("INSERT / UPDATE", page)
        self.assertIn("auf dbo.Artikel", page)

    def test_tabellenfunktion_zeigt_ergebnisspalten(self) -> None:
        page = self.page("ErweitertDb", "funktionen", "dbo.fnArtikelListe.html")
        self.assertIn("Inline-Tabellenfunktion", page)
        self.assertIn("Ergebnisspalten", page)
        self.assertIn("gibt TABLE zurück", page)

    def test_clr_funktion(self) -> None:
        page = self.page("ErweitertDb", "funktionen", "dbo.fnClr.html")
        self.assertIn("CLR", page)
        self.assertIn("MeineKlasse.Rechne", page)

    def test_prozedur_zeigt_parameterrichtung(self) -> None:
        page = self.page("ErweitertDb", "prozeduren",
                         "dbo.procMitTabellenparameter.html")
        self.assertIn("OUTPUT", page)
        self.assertIn("READONLY", page)
        self.assertIn("dbo.ArtikelListe", page)

    def test_datenbankseite_nennt_assemblies(self) -> None:
        page = self.page("ErweitertDb", "index.html")
        self.assertIn("CLR-Assemblies", page)
        self.assertIn("MeineAssembly", page)

    def test_listenseiten_je_objektart(self) -> None:
        for sub in ("tabellen", "sichten", "prozeduren", "funktionen", "trigger"):
            with self.subTest(sub=sub):
                self.assertTrue((self.out / "ErweitertDb" / sub / "index.html").exists())

    def test_sichtenliste_zaehlt_spalten(self) -> None:
        page = self.page("ErweitertDb", "sichten", "index.html")
        self.assertIn("dbo.vArtikel", page)


class OhneNachbarTest(unittest.TestCase):
    """Dieselbe Datenbank allein: der Fremdschlüssel bleibt unauflösbar."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory()
        tmp = Path(cls._tmp.name)
        cls.out, cls.catalog = render_to(
            tmp, [make_dacpac(tmp, "Erweitert", EXTENDED, METADATA)])

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    def test_keine_toten_verweise(self) -> None:
        self.assertEqual(check_links(self.out, quiet=True), 0)

    def test_offener_fremdschluessel_wird_unverlinkt_ausgewiesen(self) -> None:
        page = (self.out / "ErweitertDb" / "tabellen" / "dbo.Artikel.html").read_text(
            encoding="utf-8")
        self.assertIn('class="ext"', page)
        self.assertIn("Nachbar", page)
        self.assertNotIn("Nachbar/tabellen", page)

    def test_katalogseite_listet_nicht_geladene_datenbanken(self) -> None:
        page = (self.out / "index.html").read_text(encoding="utf-8")
        self.assertIn("Nicht geladene Datenbanken", page)
        self.assertIn("Nachbar", page)

    def test_offene_verweise_auf_der_routinenseite(self) -> None:
        page = (self.out / "ErweitertDb" / "prozeduren" /
                "dbo.procMitTabellenparameter.html").read_text(encoding="utf-8")
        self.assertIn("Nicht auflösbare Verweise", page)


class SonderfaelleTest(unittest.TestCase):
    def test_gleichnamige_datenbanken_bekommen_eigene_ordner(self) -> None:
        """Zwei .dacpac mit demselben Namen dürfen sich nicht überschreiben."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            paths = [make_dacpac(tmp, "eins", _mit_tabelle("A"), _meta("Ver kauf")),
                     make_dacpac(tmp, "zwei", _mit_tabelle("B"), _meta("Ver:kauf"))]
            out, _ = render_to(tmp, paths)
            # Beide Namen ergeben denselben Ordnernamen; der zweite weicht aus.
            self.assertTrue((out / "Ver_kauf" / "index.html").exists())
            self.assertTrue((out / "Ver_kauf~2" / "index.html").exists())
            self.assertEqual(check_links(out, quiet=True), 0)

    def test_gleichnamige_objekte_bekommen_eigene_seiten(self) -> None:
        """Zwei Namen, ein Dateiname: der zweite muss ausweichen."""
        model = f"""<?xml version="1.0" encoding="utf-8"?>
<DataSchemaModel xmlns="{NS}"><Model>
 <Element Type="SqlTable" Name="[dbo].[A B]" />
 <Element Type="SqlTable" Name="[dbo].[A:B]" />
</Model></DataSchemaModel>
"""
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            out, _ = render_to(tmp, [make_dacpac(tmp, "d", model, _meta("D"))])
            seiten = sorted(p.name for p in (out / "D" / "tabellen").glob("*.html"))
            self.assertEqual(seiten, ["dbo.A_B.html", "dbo.A_B~2.html", "index.html"])
            self.assertEqual(check_links(out, quiet=True), 0)

    def test_grosse_nachbarschaft_wird_beschnitten(self) -> None:
        """Mehr Nachbarn als gezeichnet werden: die Seite sagt es dazu."""
        tabellen = "".join(
            f'''<Element Type="SqlTable" Name="[dbo].[T{i}]" />
 <Element Type="SqlForeignKeyConstraint" Name="[dbo].[FK{i}]">
  <Relationship Name="Columns"><Entry><References Name="[dbo].[T{i}].[Id]" /></Entry></Relationship>
  <Relationship Name="DefiningTable"><Entry><References Name="[dbo].[T{i}]" /></Entry></Relationship>
  <Relationship Name="ForeignColumns"><Entry><References Name="[dbo].[Mitte].[Id]" /></Entry></Relationship>
  <Relationship Name="ForeignTable"><Entry><References Name="[dbo].[Mitte]" /></Entry></Relationship>
 </Element>''' for i in range(15))
        model = f"""<?xml version="1.0" encoding="utf-8"?>
<DataSchemaModel xmlns="{NS}"><Model>
 <Element Type="SqlTable" Name="[dbo].[Mitte]" />
 {tabellen}
</Model></DataSchemaModel>
"""
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            out, _ = render_to(tmp, [make_dacpac(tmp, "v", model, _meta("VieleDb"))])
            page = (out / "VieleDb" / "tabellen" / "dbo.Mitte.html").read_text(
                encoding="utf-8")
            self.assertIn("von 15 direkt verbundenen", page)
            self.assertEqual(check_links(out, quiet=True), 0)

    def test_leere_datenbank_wird_ausgewiesen(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            paths = [make_dacpac(tmp, "leer", LEER, _meta("LeerDb")),
                     make_dacpac(tmp, "voll", _mit_tabelle("A"), _meta("VollDb"))]
            out, _ = render_to(tmp, paths)
            page = (out / "index.html").read_text(encoding="utf-8")
            self.assertIn("Ohne Objekte und daher ohne Inhalt", page)
            self.assertIn("LeerDb", page)
            self.assertEqual(check_links(out, quiet=True), 0)


if __name__ == "__main__":
    unittest.main()
