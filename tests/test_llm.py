"""Tests der KI-Ausgabe (``llm/``): Aufbau, Inhalt und Verweise.

    python3 -m unittest discover -s tests -v
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dbdoku import __main__ as cli                          # noqa: E402
from dbdoku import catalog as cm, crud, ddl, graph, llm     # noqa: E402
from dbdoku.model import gid                                # noqa: E402

from test_cli import run                                    # noqa: E402
from test_dbdoku import make_dacpac, make_katalog           # noqa: E402
from test_extract_extended import EXTENDED, METADATA        # noqa: E402
from test_render_extended import NACHBAR, NACHBAR_META      # noqa: E402


def write_llm(tmp: Path, paths: list[Path]) -> tuple[Path, object, object]:
    catalog = cm.load(paths)
    g = graph.build(catalog, crud.analyze(catalog))
    out = tmp / "llm"
    llm.LlmWriter(catalog, g, out, "Katalog").write()
    return out, catalog, g


class GrundkatalogTest(unittest.TestCase):
    """Testkatalog aus ``test_dbdoku`` samt Nachbardatenbank."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory()
        tmp = Path(cls._tmp.name)
        cls.out, cls.catalog, cls.graph = write_llm(tmp, make_katalog(tmp))

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    def read(self, *parts: str) -> str:
        return self.out.joinpath(*parts).read_text(encoding="utf-8")

    def test_aufbau(self) -> None:
        for name in ("README.md", "llms.txt"):
            self.assertTrue((self.out / name).is_file(), name)
        for db in ("TestDbs", "Fremd-DB"):
            for name in ("index.md", "schema.sql", "relations.md"):
                self.assertTrue((self.out / db / name).is_file(), f"{db}/{name}")
        self.assertTrue((self.out / "TestDbs" / "tables" / "dbo.Kunde.md").is_file())
        self.assertTrue((self.out / "TestDbs" / "procedures"
                         / "dbo.procKundeSpeichern.md").is_file())
        self.assertTrue((self.out / "TestDbs" / "types" / "dbo.Kunde.md").is_file())

    def test_jedes_objekt_hat_eine_datei(self) -> None:
        files = {p for p in self.out.rglob("*.md")
                 if p.parent.name in {"tables", "views", "procedures", "functions",
                                      "triggers", "types"}}
        self.assertEqual(len(files), self.catalog.total)

    def test_keine_toten_verweise(self) -> None:
        r = run(cli.check_links, self.out, True)
        self.assertEqual(r.code, 0, r.err)

    def test_llms_txt_listet_datenbanken(self) -> None:
        text = self.read("llms.txt")
        self.assertIn("# Katalog", text)
        self.assertIn("[TestDbs](TestDbs/index.md)", text)
        self.assertIn("tables: 2", text)

    def test_tabelle_mit_spalten_fremdschluessel_und_zugriff(self) -> None:
        text = self.read("TestDbs", "tables", "dbo.Kunde.md")
        self.assertIn("# Table TestDbs.dbo.Kunde", text)
        self.assertIn("| KundeId | int |", text)
        self.assertIn("PK", text)
        self.assertIn("## Referenced by (incoming foreign keys)", text)
        self.assertIn("[dbo.Bestellung](../tables/dbo.Bestellung.md)", text)
        self.assertIn("[dbo.procKundeSpeichern](../procedures/dbo.procKundeSpeichern.md)",
                      text)
        child = self.read("TestDbs", "tables", "dbo.Bestellung.md")
        self.assertIn("## Foreign keys (outgoing)", child)
        self.assertIn("FK_Bestellung_Kunde: (KundeId) → [dbo.Kunde]", child)
        self.assertIn("FK → [dbo.Kunde](../tables/dbo.Kunde.md).KundeId", child)

    def test_spaltenbeschreibung_landet_in_tabelle_und_schema(self) -> None:
        kunde = self.catalog.objects[gid("testdbs", "[dbo].[Kunde]")]
        desc = next(c.description for c in kunde.columns if c.name == "Name")
        self.assertTrue(desc)
        self.assertIn(desc, self.read("TestDbs", "tables", "dbo.Kunde.md"))
        self.assertIn(f"-- {desc}", self.read("TestDbs", "schema.sql"))

    def test_routine_mit_parametern_aufrufen_und_quelltext(self) -> None:
        text = self.read("TestDbs", "procedures", "dbo.procKundeSpeichern.md")
        self.assertIn("# Procedure TestDbs.dbo.procKundeSpeichern", text)
        self.assertIn("| @Name |", text)
        self.assertIn("## Calls", text)
        self.assertIn("[dbo.procHilf](../procedures/dbo.procHilf.md)", text)
        self.assertIn("[Fremd-DB.dbo.Kunde](../../Fremd-DB/tables/dbo.Kunde.md)", text)
        self.assertIn("## Source\n\n```sql\n", text)
        callee = self.read("TestDbs", "procedures", "dbo.procHilf.md")
        self.assertIn("## Called by / used by", callee)

    def test_schema_sql_entspricht_der_html_ddl(self) -> None:
        text = self.read("TestDbs", "schema.sql")
        self.assertIn("CREATE TABLE dbo.Kunde (", text)
        self.assertIn("FOREIGN KEY ([KundeId]) REFERENCES TestDbs.dbo.Kunde", text)
        bestellung = self.catalog.objects[gid("testdbs", "[dbo].[Bestellung]")]
        self.assertIn(ddl.create_table(bestellung, self.catalog, self.graph), text)

    def test_relations_listet_fremdschluessel_und_fremdzugriffe(self) -> None:
        text = self.read("TestDbs", "relations.md")
        self.assertIn("[dbo.Bestellung](tables/dbo.Bestellung.md) (KundeId) → "
                      "[dbo.Kunde](tables/dbo.Kunde.md) (KundeId)", text)
        self.assertIn("## Access to other databases", text)
        self.assertIn("../Fremd-DB/tables/dbo.Kunde.md", text)
        self.assertIn("(none)", self.read("Fremd-DB", "relations.md"))

    def test_datenbankindex(self) -> None:
        text = self.read("TestDbs", "index.md")
        self.assertIn("# Database TestDbs", text)
        self.assertIn("## Tables (2)", text)
        self.assertIn("- [dbo.Kunde](tables/dbo.Kunde.md)", text)
        self.assertIn("uses databases: Fremd-DB", text)
        self.assertIn("used by databases: TestDbs", self.read("Fremd-DB", "index.md"))


class ErweiterterKatalogTest(unittest.TestCase):
    """Seltenere Objektarten: Sichten, Trigger, Tabellenfunktionen, CLR, Indizes."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory()
        tmp = Path(cls._tmp.name)
        paths = [make_dacpac(tmp, "Erweitert", EXTENDED, METADATA),
                 make_dacpac(tmp, "Nachbar", NACHBAR, NACHBAR_META)]
        cls.out, cls.catalog, cls.graph = write_llm(tmp, paths)

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    def read(self, *parts: str) -> str:
        return self.out.joinpath(*parts).read_text(encoding="utf-8")

    def test_keine_toten_verweise(self) -> None:
        self.assertEqual(run(cli.check_links, self.out, True).code, 0)

    def test_indizes_checks_und_spaltenmerkmale(self) -> None:
        text = self.read("ErweitertDb", "tables", "dbo.Artikel.md")
        self.assertIn("IX_Artikel_Bezeichnung: UNIQUE INDEX CLUSTERED (Bezeichnung) "
                      "INCLUDE (Preis)", text)
        self.assertIn("CK_Artikel_Preis: ([Preis]>(0))", text)
        self.assertIn("IDENTITY(1000,5)", text)
        self.assertIn("ROWGUIDCOL", text)
        self.assertIn("| Gesamt | computed |  | `AS ([Preis]*[Menge])` |", text)
        self.assertIn("../../Nachbar/tables/dbo.Fern.md", text)

    def test_berechnete_spalte_als_ausdruck_in_der_ddl(self) -> None:
        text = self.read("ErweitertDb", "schema.sql")
        self.assertIn("[Gesamt] AS ([Preis]*[Menge])", text)
        self.assertIn("CREATE UNIQUE CLUSTERED INDEX [IX_Artikel_Bezeichnung]", text)

    def test_trigger(self) -> None:
        text = self.read("ErweitertDb", "triggers", "dbo.trArtikel.md")
        self.assertIn("- events: INSERT, UPDATE", text)
        self.assertIn("- on: [dbo.Artikel](../tables/dbo.Artikel.md)", text)
        self.assertIn("SU   [dbo.Artikel]", text)

    def test_tabellenfunktion_und_clr(self) -> None:
        text = self.read("ErweitertDb", "functions", "dbo.fnArtikelTabelle.md")
        self.assertIn("multi-statement table-valued function", text)
        self.assertIn("## Result columns", text)
        self.assertIn("CLR routine", self.read("ErweitertDb", "functions", "dbo.fnClr.md"))

    def test_parameterrichtung_und_offene_verweise(self) -> None:
        text = self.read("ErweitertDb", "procedures", "dbo.procMitTabellenparameter.md")
        self.assertIn("| @Liste | dbo.ArtikelListe | READONLY |", text)
        self.assertIn("| @Anzahl | int | OUTPUT | `(0)` |", text)
        self.assertIn("`Nachbar2.dbo.Fern2`", text)

    def test_sicht(self) -> None:
        text = self.read("ErweitertDb", "views", "dbo.vArtikel.md")
        self.assertIn("# View ErweitertDb.dbo.vArtikel", text)
        self.assertIn("```sql", text)

    def test_eingehender_fremdschluessel_aus_anderer_datenbank(self) -> None:
        text = self.read("Nachbar", "tables", "dbo.Fern.md")
        self.assertIn("FK_Artikel_Fern: [ErweitertDb.dbo.Artikel]"
                      "(../../ErweitertDb/tables/dbo.Artikel.md)", text)


class BausteineTest(unittest.TestCase):
    def test_zelle_ist_einzeilig_und_maskiert(self) -> None:
        self.assertEqual(llm.cell("a |\n b"), "a \\| b")
        self.assertEqual(llm.cell(None), "")

    def test_codeblock_waehlt_laengeren_zaun(self) -> None:
        self.assertEqual(llm.fenced("x"), "```sql\nx\n```")
        self.assertTrue(llm.fenced("a ``` b").startswith("````sql\n"))

    def test_fremdschluesselaktionen_in_der_ddl(self) -> None:
        from dbdoku.model import Catalog, DbObject, ForeignKey
        from dbdoku.graph import Graph
        obj = DbObject(id="d|[dbo].[A]", kind="table", schema="dbo", name="A")
        fk = ForeignKey(name="FK", table=obj.id, columns=["x"], ref_table="d|[dbo].[B]",
                        ref_columns=["y"], on_delete="Cascade", on_update="NoAction")
        g = Graph(catalog=Catalog(), access={}, fk_out={obj.id: [fk]})
        text = ddl.create_table(obj, Catalog(), g)
        self.assertIn("REFERENCES dbo.B ([y]) ON DELETE CASCADE", text)
        self.assertNotIn("ON UPDATE", text)


class CliTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.src = self.tmp / "src"
        self.src.mkdir()
        make_katalog(self.src)
        self.out = self.tmp / "docs"

    def test_llm_zusaetzlich_zur_html(self) -> None:
        r = run(cli.main, [str(self.src), "-o", str(self.out), "--llm"])
        self.assertEqual(r.code, 0, r.err)
        self.assertTrue((self.out / "index.html").is_file())
        self.assertTrue((self.out / "llm" / "llms.txt").is_file())
        self.assertTrue((self.out / "model.json").is_file())
        self.assertEqual(run(cli.check_links, self.out, True).code, 0)

    def test_nur_llm_schreibt_kein_html(self) -> None:
        r = run(cli.main, [str(self.src), "-o", str(self.out), "--nur-llm", "--no-json"])
        self.assertEqual(r.code, 0, r.err)
        self.assertFalse(list(self.out.rglob("*.html")))
        self.assertFalse((self.out / "model.json").exists())
        self.assertIn("README.md", r.out)

    def test_ohne_llm_kein_ordner(self) -> None:
        run(cli.main, [str(self.src), "-o", str(self.out), "-q"])
        self.assertFalse((self.out / "llm").exists())


if __name__ == "__main__":
    unittest.main()
