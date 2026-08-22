"""Tests gegen eine synthetische .dacpac.

    python3 -m unittest discover -s tests -v
"""

from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dbdoku import catalog as cm, crud, graph, render      # noqa: E402
from dbdoku.dacpac import DacpacError                      # noqa: E402
from dbdoku.extract import Extractor                       # noqa: E402
from dbdoku.model import gid, split_name                   # noqa: E402

NS = "http://schemas.microsoft.com/sqlserver/dac/Serialization/2012/02"

# Enthaelt bewusst eine in XML 1.0 unzulaessige Zeichenreferenz (&#x1E;),
# wie sie DacFx fuer Steuerzeichen in T-SQL-Literalen schreibt.
MODEL = f"""<?xml version="1.0" encoding="utf-8"?>
<DataSchemaModel FileFormatVersion="1.2" SchemaVersion="2.9" xmlns="{NS}">
 <Header>
  <CustomData Category="CompatibilityMode">
   <Metadata Name="CompatibilityMode" Value="150" />
  </CustomData>
 </Header>
 <Model>
  <Element Type="SqlDatabaseOptions">
   <Property Name="Collation" Value="Latin1_General_CI_AS" />
  </Element>
  <Element Type="SqlTable" Name="[dbo].[Kunde]">
   <Relationship Name="Columns">
    <Entry>
     <Element Type="SqlSimpleColumn" Name="[dbo].[Kunde].[KundeId]">
      <Property Name="IsNullable" Value="False" />
      <Property Name="IsIdentity" Value="True" />
      <Relationship Name="TypeSpecifier"><Entry>
       <Element Type="SqlTypeSpecifier"><Relationship Name="Type"><Entry>
        <References ExternalSource="BuiltIns" Name="[int]" />
       </Entry></Relationship></Element>
      </Entry></Relationship>
     </Element>
    </Entry>
    <Entry>
     <Element Type="SqlSimpleColumn" Name="[dbo].[Kunde].[Name]">
      <Relationship Name="TypeSpecifier"><Entry>
       <Element Type="SqlTypeSpecifier">
        <Property Name="Length" Value="80" />
        <Relationship Name="Type"><Entry>
         <References ExternalSource="BuiltIns" Name="[nvarchar]" />
        </Entry></Relationship>
       </Element>
      </Entry></Relationship>
     </Element>
    </Entry>
   </Relationship>
  </Element>
  <Element Type="SqlTable" Name="[dbo].[Bestellung]">
   <Relationship Name="Columns">
    <Entry>
     <Element Type="SqlSimpleColumn" Name="[dbo].[Bestellung].[BestellungId]">
      <Property Name="IsNullable" Value="False" />
      <Relationship Name="TypeSpecifier"><Entry>
       <Element Type="SqlTypeSpecifier"><Relationship Name="Type"><Entry>
        <References ExternalSource="BuiltIns" Name="[int]" />
       </Entry></Relationship></Element>
      </Entry></Relationship>
     </Element>
    </Entry>
    <Entry>
     <Element Type="SqlSimpleColumn" Name="[dbo].[Bestellung].[KundeId]">
      <Relationship Name="TypeSpecifier"><Entry>
       <Element Type="SqlTypeSpecifier"><Relationship Name="Type"><Entry>
        <References ExternalSource="BuiltIns" Name="[int]" />
       </Entry></Relationship></Element>
      </Entry></Relationship>
     </Element>
    </Entry>
   </Relationship>
  </Element>
  <Element Type="SqlPrimaryKeyConstraint" Name="[dbo].[PK_Kunde]">
   <Relationship Name="ColumnSpecifications"><Entry>
    <Element Type="SqlIndexedColumnSpecification">
     <Relationship Name="Column"><Entry>
      <References Name="[dbo].[Kunde].[KundeId]" />
     </Entry></Relationship>
    </Element>
   </Entry></Relationship>
   <Relationship Name="DefiningTable"><Entry>
    <References Name="[dbo].[Kunde]" />
   </Entry></Relationship>
  </Element>
  <Element Type="SqlForeignKeyConstraint" Name="[dbo].[FK_Bestellung_Kunde]">
   <Relationship Name="Columns"><Entry>
    <References Name="[dbo].[Bestellung].[KundeId]" />
   </Entry></Relationship>
   <Relationship Name="DefiningTable"><Entry>
    <References Name="[dbo].[Bestellung]" />
   </Entry></Relationship>
   <Relationship Name="ForeignColumns"><Entry>
    <References Name="[dbo].[Kunde].[KundeId]" />
   </Entry></Relationship>
   <Relationship Name="ForeignTable"><Entry>
    <References Name="[dbo].[Kunde]" />
   </Entry></Relationship>
  </Element>
  <Element Type="SqlDefaultConstraint">
   <Property Name="DefaultExpressionScript"><Value><![CDATA[(N'unbekannt')]]></Value></Property>
   <Relationship Name="ForColumn"><Entry>
    <References Name="[dbo].[Kunde].[Name]" />
   </Entry></Relationship>
  </Element>
  <Element Type="SqlProcedure" Name="[dbo].[procKundeSpeichern]">
   <Property Name="HeaderContents" Value="CREATE PROCEDURE [dbo].[procKundeSpeichern] @Name nvarchar(80) AS" />
   <Property Name="BodyScript"><Value><![CDATA[
    -- INSERT INTO dbo.Bestellung steht nur im Kommentar
    UPDATE k SET k.Name = @Name FROM dbo.Kunde AS k WHERE k.KundeId > 0
    INSERT INTO dbo.Bestellung (KundeId) SELECT KundeId FROM dbo.Kunde
    DELETE FROM [Fremd-DB].dbo.Kunde
    SELECT ']]>&#x1E;<![CDATA[' AS Steuerzeichen
    EXEC dbo.procHilf]]></Value></Property>
   <Relationship Name="BodyDependencies">
    <Entry><References Name="[dbo].[Kunde]" /></Entry>
    <Entry><References Name="[dbo].[Kunde].[Name]" /></Entry>
    <Entry><References Name="[dbo].[Bestellung]" /></Entry>
    <Entry><References Name="[dbo].[procHilf]" /></Entry>
    <Entry><References ExternalSource="Fremd-DB.dacpac" Name="[Fremd-DB]|[dbo].[Kunde]" /></Entry>
   </Relationship>
   <Relationship Name="Parameters"><Entry>
    <Element Type="SqlSubroutineParameter" Name="[dbo].[procKundeSpeichern].[@Name]">
     <Relationship Name="Type"><Entry>
      <Element Type="SqlTypeSpecifier">
       <Property Name="Length" Value="80" />
       <Relationship Name="Type"><Entry>
        <References ExternalSource="BuiltIns" Name="[nvarchar]" />
       </Entry></Relationship>
      </Element>
     </Entry></Relationship>
    </Element>
   </Entry></Relationship>
  </Element>
  <Element Type="SqlProcedure" Name="[dbo].[procHilf]">
   <Property Name="BodyScript"><Value><![CDATA[ SET @sql = 'SELECT 1' EXEC (@sql) ]]></Value></Property>
  </Element>
  <Element Type="SqlScalarFunction" Name="[dbo].[fnKundeName]">
   <Relationship Name="FunctionBody"><Entry>
    <Element Type="SqlScriptFunctionImplementation">
     <Property Name="BodyScript"><Value><![CDATA[
    BEGIN
     RETURN (SELECT TOP 1 Name FROM dbo.Kunde WHERE KundeId = @Id)
    END]]></Value></Property>
     <Annotation Type="SysCommentsObjectAnnotation">
      <Property Name="HeaderContents" Value="CREATE FUNCTION [dbo].[fnKundeName] (@Id int) RETURNS nvarchar(80) AS" />
     </Annotation>
    </Element>
   </Entry></Relationship>
   <Relationship Name="BodyDependencies">
    <Entry><References Name="[dbo].[Kunde]" /></Entry>
   </Relationship>
   <Relationship Name="Parameters"><Entry>
    <Element Type="SqlSubroutineParameter" Name="[dbo].[fnKundeName].[@Id]">
     <Relationship Name="Type"><Entry>
      <Element Type="SqlTypeSpecifier"><Relationship Name="Type"><Entry>
       <References ExternalSource="BuiltIns" Name="[int]" />
      </Entry></Relationship></Element>
     </Entry></Relationship>
    </Element>
   </Entry></Relationship>
   <Relationship Name="Type"><Entry>
    <Element Type="SqlTypeSpecifier">
     <Property Name="Length" Value="80" />
     <Relationship Name="Type"><Entry>
      <References ExternalSource="BuiltIns" Name="[nvarchar]" />
     </Entry></Relationship>
    </Element>
   </Entry></Relationship>
  </Element>
  <Element Type="SqlTableType" Name="[dbo].[Kunde]">
   <Relationship Name="Columns"><Entry>
    <Element Type="SqlTableTypeSimpleColumn" Name="[dbo].[Kunde].[Id]">
     <Relationship Name="TypeSpecifier"><Entry>
      <Element Type="SqlTypeSpecifier"><Relationship Name="Type"><Entry>
       <References ExternalSource="BuiltIns" Name="[int]" />
      </Entry></Relationship></Element>
     </Entry></Relationship>
    </Element>
   </Entry></Relationship>
  </Element>
  <Element Type="SqlExtendedProperty" Name="[SqlColumn].[dbo].[Kunde].[Name].[MS_Description]">
   <Property Name="Value"><Value><![CDATA[N'Der Name des Kunden']]></Value></Property>
   <Relationship Name="Host"><Entry>
    <References Name="[dbo].[Kunde].[Name]" />
   </Entry></Relationship>
  </Element>
 </Model>
</DataSchemaModel>
"""

METADATA = f"""<?xml version="1.0" encoding="utf-8"?>
<DacType xmlns="{NS}"><Name>TestDbs</Name><Version>2.1.0.0</Version></DacType>
"""


FREMD_MODEL = f"""<?xml version="1.0" encoding="utf-8"?>
<DataSchemaModel FileFormatVersion="1.2" SchemaVersion="2.9" xmlns="{NS}">
 <Model>
  <Element Type="SqlTable" Name="[dbo].[Kunde]">
   <Relationship Name="Columns"><Entry>
    <Element Type="SqlSimpleColumn" Name="[dbo].[Kunde].[KundeId]">
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

FREMD_METADATA = f"""<?xml version="1.0" encoding="utf-8"?>
<DacType xmlns="{NS}"><Name>Fremd-DB</Name><Version>1.0.0.0</Version></DacType>
"""


def make_dacpac(directory: Path, name: str = "Test",
                model: str = MODEL, metadata: str = METADATA) -> Path:
    path = directory / f"{name}.dacpac"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("model.xml", model)
        z.writestr("DacMetadata.xml", metadata)
    return path


def make_katalog(directory: Path, mit_nachbar: bool = True) -> list[Path]:
    """Testkatalog: die Hauptdatenbank, wahlweise mit der Nachbardatenbank,
    die eine gleichnamige Tabelle enthält."""
    paths = [make_dacpac(directory)]
    if mit_nachbar:
        paths.append(make_dacpac(directory, "Fremd-DB", FREMD_MODEL,
                                 FREMD_METADATA))
    return paths


class Fixture:
    """Gemeinsamer Katalog. Kein TestCase, damit die Tests nicht mehrfach laufen."""

    mit_nachbar = True

    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory()
        paths = make_katalog(Path(cls._tmp.name), cls.mit_nachbar)
        cls.catalog = cm.load(paths)
        cls.db = cls.catalog.by_key("testdbs")
        cls.access = crud.analyze(cls.catalog)
        cls.graph = graph.build(cls.catalog, cls.access)

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    @staticmethod
    def oid(name: str, db: str = "testdbs") -> str:
        return gid(db, name)


class ExtractTest(Fixture, unittest.TestCase):
    def test_metadaten(self) -> None:
        self.assertEqual(self.db.name, "TestDbs")
        self.assertEqual(self.db.version, "2.1.0.0")
        self.assertEqual(self.db.collation, "Latin1_General_CI_AS")
        self.assertEqual(self.db.compatibility, "150")
        self.assertEqual(self.db.source, "Test.dacpac")

    def test_objektzahlen(self) -> None:
        self.assertEqual(len(self.db.of_kind("table")), 2)
        self.assertEqual(len(self.db.of_kind("procedure")), 2)
        # Der Tabellentyp heisst wie eine Tabelle und darf sie nicht verdraengen.
        self.assertEqual(len(self.db.of_kind("tabletype")), 1)

    def test_spalten(self) -> None:
        kunde = self.catalog.objects[self.oid("[dbo].[Kunde]")]
        name = {c.name: c for c in kunde.columns}["Name"]
        self.assertEqual(name.type, "nvarchar(80)")
        self.assertTrue(name.nullable)
        self.assertEqual(name.default, "(N'unbekannt')")
        self.assertEqual(name.description, "Der Name des Kunden")
        ident = {c.name: c for c in kunde.columns}["KundeId"]
        self.assertEqual(ident.identity, "1,1")
        self.assertFalse(ident.nullable)

    def test_primaerschluessel(self) -> None:
        kunde = self.catalog.objects[self.oid("[dbo].[Kunde]")]
        self.assertEqual([i.kind for i in kunde.indexes], ["primarykey"])
        self.assertEqual(kunde.indexes[0].columns, ["KundeId"])

    def test_fremdschluessel(self) -> None:
        fks = [fk for fk in self.catalog.foreign_keys
               if fk.table == self.oid("[dbo].[Bestellung]")]
        self.assertEqual(len(fks), 1)
        fk = fks[0]
        self.assertEqual(fk.ref_table, self.oid("[dbo].[Kunde]"))
        self.assertEqual(fk.columns, ["KundeId"])
        self.assertIn(fk, self.graph.fk_in[self.oid("[dbo].[Kunde]")])

    def test_ungueltige_zeichenreferenz(self) -> None:
        """&#x1E; darf den Parser nicht sprengen, der Rest muss ankommen."""
        proc = self.catalog.objects[self.oid("[dbo].[procKundeSpeichern]")]
        self.assertIn("Steuerzeichen", proc.body)
        self.assertIn("EXEC dbo.procHilf", proc.body)

    def test_parameter_und_kopf(self) -> None:
        proc = self.catalog.objects[self.oid("[dbo].[procKundeSpeichern]")]
        self.assertEqual([p.name for p in proc.parameters], ["@Name"])
        self.assertEqual(proc.parameters[0].type, "nvarchar(80)")
        self.assertTrue(proc.sql.startswith("CREATE PROCEDURE"))

    def test_funktion_hat_quelltext(self) -> None:
        """Bei Funktionen liegen Kopf und Rumpf unter ``FunctionBody``."""
        fn = self.catalog.objects[self.oid("[dbo].[fnKundeName]")]
        self.assertTrue(fn.sql.startswith("CREATE FUNCTION"))
        self.assertIn("RETURN (SELECT TOP 1 Name FROM dbo.Kunde", fn.sql)
        self.assertEqual([p.name for p in fn.parameters], ["@Id"])
        self.assertEqual(fn.returns, "nvarchar(80)")


class KatalogTest(Fixture, unittest.TestCase):
    def test_beide_datenbanken_geladen(self) -> None:
        self.assertEqual([d.name for d in self.catalog.databases],
                         ["Fremd-DB", "TestDbs"])
        self.assertEqual(self.catalog.unresolved_dbs, {})

    def test_gleichnamige_tabellen_bleiben_getrennt(self) -> None:
        """Beide Datenbanken haben dbo.Kunde – die dürfen sich nicht überschreiben."""
        self.assertIn(self.oid("[dbo].[Kunde]"), self.catalog.objects)
        self.assertIn(self.oid("[dbo].[Kunde]", "fremd-db"), self.catalog.objects)
        eigen = self.catalog.objects[self.oid("[dbo].[Kunde]")]
        fremd = self.catalog.objects[self.oid("[dbo].[Kunde]", "fremd-db")]
        self.assertEqual(eigen.db, "TestDbs")
        self.assertEqual(fremd.db, "Fremd-DB")
        self.assertEqual(fremd.qualified, "Fremd-DB.dbo.Kunde")

    def test_querverweis_ist_aufgeloest(self) -> None:
        proc = self.catalog.objects[self.oid("[dbo].[procKundeSpeichern]")]
        extern = [r for r in proc.refs if r.is_external]
        self.assertEqual(len(extern), 1)
        self.assertTrue(extern[0].resolved)
        self.assertEqual(extern[0].target, self.oid("[dbo].[Kunde]", "fremd-db"))

    def test_datenbankkanten(self) -> None:
        self.assertIn("fremd-db", self.graph.db_uses.get("testdbs", {}))
        self.assertIn("testdbs", self.graph.db_used_by.get("fremd-db", {}))


class AccessTest(Fixture, unittest.TestCase):
    def test_zugriffsarten(self) -> None:
        acc = self.access[self.oid("[dbo].[procKundeSpeichern]")]
        # UPDATE ueber Alias muss der Tabelle zugeordnet werden.
        self.assertEqual(acc[self.oid("[dbo].[Kunde]")], "SU")
        self.assertEqual(acc[self.oid("[dbo].[Bestellung]")], "SI")

    def test_kommentar_zaehlt_nicht(self) -> None:
        """Das INSERT im Kommentar darf keinen Schreibzugriff erzeugen."""
        body = crud.strip_noise(
            self.catalog.objects[self.oid("[dbo].[procKundeSpeichern]")].body)
        self.assertNotIn("nur im Kommentar", body)

    def test_loeschen_trifft_die_fremde_tabelle(self) -> None:
        """DELETE FROM [Fremd-DB].dbo.Kunde gehört zu Fremd-DB, nicht zur eigenen."""
        acc = self.access[self.oid("[dbo].[procKundeSpeichern]")]
        self.assertNotIn("D", acc[self.oid("[dbo].[Kunde]")])
        self.assertIn("D", acc[self.oid("[dbo].[Kunde]", "fremd-db")])

    def test_fremde_tabelle_kennt_ihren_nutzer(self) -> None:
        users = dict(self.graph.used_by[self.oid("[dbo].[Kunde]", "fremd-db")])
        self.assertIn(self.oid("[dbo].[procKundeSpeichern]"), users)

    def test_dynamisches_sql_erkannt(self) -> None:
        self.assertTrue(self.catalog.objects[self.oid("[dbo].[procHilf]")].dynamic_sql)
        self.assertFalse(
            self.catalog.objects[self.oid("[dbo].[procKundeSpeichern]")].dynamic_sql)

    def test_aufrufgraph(self) -> None:
        self.assertEqual(self.graph.calls[self.oid("[dbo].[procKundeSpeichern]")],
                         [self.oid("[dbo].[procHilf]")])
        self.assertEqual(self.graph.called_by[self.oid("[dbo].[procHilf]")],
                         [self.oid("[dbo].[procKundeSpeichern]")])


class OhneNachbarTest(Fixture, unittest.TestCase):
    """Fehlt die Nachbardatenbank, darf nichts fälschlich lokal gedeutet werden."""

    mit_nachbar = False

    def test_verweis_bleibt_offen(self) -> None:
        self.assertIn("Fremd-DB", self.catalog.unresolved_dbs)
        proc = self.catalog.objects[self.oid("[dbo].[procKundeSpeichern]")]
        self.assertFalse([r for r in proc.refs if r.is_external][0].resolved)

    def test_kein_falscher_loeschzugriff(self) -> None:
        acc = self.access[self.oid("[dbo].[procKundeSpeichern]")]
        self.assertNotIn("D", acc[self.oid("[dbo].[Kunde]")])

    def test_offener_verweis_wird_ausgewiesen(self) -> None:
        refs = self.graph.externals[self.oid("[dbo].[procKundeSpeichern]")]
        self.assertEqual([r.external_db for r in refs], ["Fremd-DB"])


class RenderTest(Fixture, unittest.TestCase):
    def test_erzeugt_seiten_ohne_tote_verweise(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "docs"
            written = render.Renderer(self.catalog, self.graph, out).write()
            # je Objekt eine Seite, dazu Übersicht, Suche, je Datenbank eine
            # Startseite und je Objektart darin eine Listenseite
            listen = sum(len({o.kind for o in db.objects.values()})
                         for db in self.catalog.databases)
            self.assertEqual(
                written,
                self.catalog.total + 2 + len(self.catalog.databases) + listen)

            page = (out / "TestDbs" / "tabellen" / "dbo.Kunde.html").read_text(
                encoding="utf-8")
            self.assertIn("Der Name des Kunden", page)
            self.assertIn("nvarchar(80)", page)
            # Verweise werden ab dem Wurzelverzeichnis aufgebaut.
            self.assertIn('href="../../TestDbs/prozeduren/'
                          'dbo.procKundeSpeichern.html"', page)
            self.assertIn("<svg", page)          # Beziehungsdiagramm

            # Tabelle und gleichnamiger Tabellentyp bekommen eigene Seiten.
            self.assertTrue((out / "TestDbs" / "typen" / "dbo.Kunde.html").exists())

            from dbdoku.__main__ import check_links
            self.assertEqual(check_links(out, quiet=True), 0)

    def test_querverweis_wird_verlinkt(self) -> None:
        """Die fremde Tabelle verlinkt zurück auf die Prozedur der Nachbardatenbank."""
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "docs"
            render.Renderer(self.catalog, self.graph, out).write()
            page = (out / "Fremd-DB" / "tabellen" / "dbo.Kunde.html").read_text(
                encoding="utf-8")
            self.assertIn("../../TestDbs/prozeduren/dbo.procKundeSpeichern.html", page)
            self.assertIn("TestDbs.dbo.procKundeSpeichern", page)

    def test_ohne_volltext_kein_quelltextindex(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "docs"
            render.Renderer(self.catalog, self.graph, out).write()
            self.assertFalse((out / "assets" / "quelltext.js").exists())
            self.assertNotIn('id="src"',
                             (out / "suche.html").read_text(encoding="utf-8"))

    def test_volltext_schreibt_quelltextindex(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "docs"
            render.Renderer(self.catalog, self.graph, out,
                            fulltext=True).write()
            self.assertIn('id="src"',
                          (out / "suche.html").read_text(encoding="utf-8"))

            index = json.loads(
                (out / "assets" / "suchindex.js").read_text(encoding="utf-8")
                .split("=", 1)[1].rstrip(";\n"))
            source = json.loads(
                (out / "assets" / "quelltext.js").read_text(encoding="utf-8")
                .split("=", 1)[1].rstrip(";\n"))
            # Beide Listen sind gleich lang und gleich sortiert; die Suchseite
            # verknuepft sie ueber den Listenplatz.
            self.assertEqual(len(index), len(source))
            at = [row[0] for row in index].index("dbo.procKundeSpeichern")
            self.assertIn("KundeId", source[at])

    def test_sonderzeichen_werden_maskiert(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "docs"
            render.Renderer(self.catalog, self.graph, out).write()
            proc = (out / "TestDbs" / "prozeduren" /
                    "dbo.procKundeSpeichern.html").read_text(encoding="utf-8")
            self.assertIn("&gt;", proc)          # aus "k.KundeId > 0"
            self.assertNotIn("KundeId > 0", proc)


class FehlerTest(unittest.TestCase):
    def test_kein_zip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "kaputt.dacpac"
            path.write_text("kein zip", encoding="utf-8")
            with self.assertRaises(DacpacError):
                Extractor().run(str(path))

    def test_zip_ohne_model(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "leer.dacpac"
            with zipfile.ZipFile(path, "w") as z:
                z.writestr("Origin.xml", "<x/>")
            with self.assertRaises(DacpacError):
                Extractor().run(str(path))

    def test_ordner_wird_aufgeloest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            make_katalog(Path(tmp))
            paths = cm.dacpac_paths([Path(tmp)])
            self.assertEqual(sorted(p.name for p in paths),
                             ["Fremd-DB.dacpac", "Test.dacpac"])


class NamenTest(unittest.TestCase):
    def test_split_name(self) -> None:
        self.assertEqual(split_name("[dbo].[Person].[Id]"), ["dbo", "Person", "Id"])
        self.assertEqual(split_name("dbo.Person"), ["dbo", "Person"])
        self.assertEqual(split_name("[a]]b].[c]"), ["a]b", "c"])


if __name__ == "__main__":
    unittest.main()
