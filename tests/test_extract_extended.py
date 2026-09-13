"""Extraktion der selteneren Modellelemente.

Die Haupt-.dacpac in ``test_dbdoku`` deckt den Normalfall ab: Tabelle, Spalte,
Prozedur, Fremdschlüssel. Hier steht alles, was daneben im Modell vorkommen
kann – Sichten, Trigger, Tabellenfunktionen, CLR, Indizes, Check-Constraints –
und die Typformen, die DacFx unterschiedlich serialisiert.

    python3 -m unittest discover -s tests -v
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dbdoku.extract import extract                          # noqa: E402
from dbdoku.model import gid                                # noqa: E402

from test_dbdoku import NS, make_dacpac                     # noqa: E402


def _typespec(base: str, *props: str, builtin: bool = True) -> str:
    """Ein ``TypeSpecifier`` mit optionalen Length-/Precision-Properties."""
    src = ' ExternalSource="BuiltIns"' if builtin else ""
    return f"""
   <Relationship Name="TypeSpecifier"><Entry>
    <Element Type="SqlTypeSpecifier">
     {''.join(props)}
     <Relationship Name="Type"><Entry>
      <References{src} Name="[{base}]" />
     </Entry></Relationship>
    </Element>
   </Entry></Relationship>"""


def _col(table: str, name: str, spec: str) -> str:
    return f"""
    <Entry>
     <Element Type="SqlSimpleColumn" Name="[dbo].[{table}].[{name}]">{spec}
     </Element>
    </Entry>"""


EXTENDED = f"""<?xml version="1.0" encoding="utf-8"?>
<DataSchemaModel FileFormatVersion="1.2" SchemaVersion="2.9" xmlns="{NS}">
 <Model>
  <Element Type="SqlSchema" Name="[verkauf]" />
  <Element Type="SqlAssembly" Name="[MeineAssembly]" />

  <Element Type="SqlTable" Name="[dbo].[Artikel]">
   <Relationship Name="Columns">
    {_col("Artikel", "ArtikelId", _typespec("int"))}
    {_col("Artikel", "Bezeichnung",
          _typespec("nvarchar", '<Property Name="IsMax" Value="True" />'))}
    {_col("Artikel", "Preis",
          _typespec("decimal", '<Property Name="Precision" Value="18" />',
                    '<Property Name="Scale" Value="2" />'))}
    {_col("Artikel", "Menge",
          _typespec("decimal", '<Property Name="Precision" Value="9" />'))}
    {_col("Artikel", "Erfasst",
          _typespec("time", '<Property Name="Scale" Value="7" />'))}
    {_col("Artikel", "Rohdaten",
          _typespec("image", '<Property Name="Length" Value="16" />'))}
    <Entry>
     <Element Type="SqlSimpleColumn" Name="[dbo].[Artikel].[Zeile]">
      <Property Name="IsRowGuidColumn" Value="True" />
      <Property Name="Collation" Value="Latin1_General_BIN2" />
      {_typespec("uniqueidentifier")}
     </Element>
    </Entry>
    <Entry>
     <Element Type="SqlSimpleColumn" Name="[dbo].[Artikel].[Nummer]">
      <Property Name="IsIdentity" Value="True" />
      <Property Name="IdentitySeed" Value="1000" />
      <Property Name="IdentityIncrement" Value="5" />
      {_typespec("int")}
     </Element>
    </Entry>
    <Entry>
     <Element Type="SqlComputedColumn" Name="[dbo].[Artikel].[Gesamt]">
      <Property Name="ExpressionScript"><Value><![CDATA[([Preis]*[Menge])]]></Value></Property>
      <Relationship Name="ExpressionDependencies">
       <Entry><References Name="[dbo].[Artikel].[Preis]" /></Entry>
      </Relationship>
     </Element>
    </Entry>
    <Entry>
     <Element Type="SqlSimpleColumn" Name="[dbo].[Artikel].[Ohne]">
      <Relationship Name="TypeSpecifier"><Entry>
       <Element Type="SqlTypeSpecifier" />
      </Entry></Relationship>
     </Element>
    </Entry>
   </Relationship>
  </Element>

  <Element Type="SqlView" Name="[dbo].[vArtikel]">
   <Property Name="QueryScript"><Value><![CDATA[SELECT ArtikelId FROM dbo.Artikel]]></Value></Property>
   <Relationship Name="Columns">
    {_col("vArtikel", "ArtikelId", _typespec("int"))}
   </Relationship>
   <Relationship Name="QueryDependencies">
    <Entry><References Name="[dbo].[Artikel]" /></Entry>
   </Relationship>
   <Annotation Type="SysCommentsObjectAnnotation">
    <Property Name="HeaderContents" Value="CREATE VIEW [dbo].[vArtikel] AS" />
   </Annotation>
  </Element>

  <Element Type="SqlDmlTrigger" Name="[dbo].[trArtikel]">
   <Property Name="IsInsertTrigger" Value="True" />
   <Property Name="IsUpdateTrigger" Value="True" />
   <Property Name="BodyScript"><Value><![CDATA[ UPDATE dbo.Artikel SET Menge = 0 ]]></Value></Property>
   <Relationship Name="Parent"><Entry>
    <References Name="[dbo].[Artikel]" />
   </Entry></Relationship>
   <Relationship Name="BodyDependencies">
    <Entry><References Name="[dbo].[Artikel]" /></Entry>
   </Relationship>
  </Element>

  <Element Type="SqlDmlTrigger" Name="[dbo].[trOhneAlles]">
   <Property Name="BodyScript"><Value><![CDATA[ SELECT 1 ]]></Value></Property>
   <Relationship Name="Parent"><Entry>
    <References Name="[dbo].[NichtModelliert]" />
   </Entry></Relationship>
  </Element>

  <Element Type="SqlInlineTableValuedFunction" Name="[dbo].[fnArtikelListe]">
   <Relationship Name="FunctionBody"><Entry>
    <Element Type="SqlScriptFunctionImplementation">
     <Property Name="BodyScript"><Value><![CDATA[ RETURN SELECT 1 AS x ]]></Value></Property>
    </Element>
   </Entry></Relationship>
   <Relationship Name="Columns">
    {_col("fnArtikelListe", "x", _typespec("int"))}
   </Relationship>
  </Element>

  <Element Type="SqlMultiStatementTableValuedFunction" Name="[dbo].[fnArtikelTabelle]">
   <Property Name="ReturnTableVariable" Value="@ergebnis" />
   <Relationship Name="FunctionBody"><Entry>
    <Element Type="SqlScriptFunctionImplementation">
     <Property Name="BodyScript"><Value><![CDATA[ BEGIN RETURN END ]]></Value></Property>
    </Element>
   </Entry></Relationship>
   <Relationship Name="Columns">
    {_col("fnArtikelTabelle", "y", _typespec("int"))}
   </Relationship>
  </Element>

  <Element Type="SqlScalarFunction" Name="[dbo].[fnClr]">
   <Relationship Name="FunctionBody"><Entry>
    <Element Type="SqlClrFunctionImplementation">
     <Property Name="ClassName" Value="MeineKlasse" />
     <Property Name="MethodName" Value="Rechne" />
    </Element>
   </Entry></Relationship>
  </Element>

  <Element Type="SqlProcedure" Name="[dbo].[procMitTabellenparameter]">
   <Relationship Name="Parameters">
    <Entry>
     <Element Type="SqlSubroutineParameter" Name="[dbo].[procMitTabellenparameter].[@Liste]">
      <Property Name="IsReadOnly" Value="True" />
      <Relationship Name="Type"><Entry>
       <References Name="[dbo].[ArtikelListe]" />
      </Entry></Relationship>
     </Element>
    </Entry>
    <Entry>
     <Element Type="SqlSubroutineParameter" Name="[dbo].[procMitTabellenparameter].[@Anzahl]">
      <Property Name="IsOutput" Value="True" />
      <Property Name="DefaultExpressionScript"><Value><![CDATA[(0)]]></Value></Property>
      <Relationship Name="Type"><Entry>
       <Element Type="SqlTypeSpecifier"><Relationship Name="Type"><Entry>
        <References ExternalSource="BuiltIns" Name="[int]" />
       </Entry></Relationship></Element>
      </Entry></Relationship>
     </Element>
    </Entry>
   </Relationship>
   <Relationship Name="BodyDependencies">
    <Entry><References /></Entry>
    <Entry><References Name="[dbo]" /></Entry>
    <Entry><References ExternalSource="BuiltIns" Name="[int]" /></Entry>
    <Entry><References Name="[dbo].[GibtEsNicht]" /></Entry>
    <Entry><References ExternalSource="Nachbar.dacpac" Name="[dbo].[Fern]" /></Entry>
    <Entry><References ExternalSource="Nachbar2" Name="[dbo].[Fern2]" /></Entry>
   </Relationship>
  </Element>

  <Element Type="SqlUniqueConstraint" Name="[dbo].[UQ_Artikel_Nummer]">
   <Property Name="IsClustered" Value="False" />
   <Relationship Name="ColumnSpecifications"><Entry>
    <Element Type="SqlIndexedColumnSpecification">
     <Relationship Name="Column"><Entry>
      <References Name="[dbo].[Artikel].[Nummer]" />
     </Entry></Relationship>
    </Element>
   </Entry></Relationship>
   <Relationship Name="DefiningTable"><Entry>
    <References Name="[dbo].[Artikel]" />
   </Entry></Relationship>
  </Element>

  <Element Type="SqlIndex" Name="[dbo].[Artikel].[IX_Artikel_Bezeichnung]">
   <Property Name="IsUnique" Value="True" />
   <Property Name="IsClustered" Value="True" />
   <Relationship Name="ColumnSpecifications"><Entry>
    <Element Type="SqlIndexedColumnSpecification">
     <Relationship Name="Column"><Entry>
      <References Name="[dbo].[Artikel].[Bezeichnung]" />
     </Entry></Relationship>
    </Element>
   </Entry></Relationship>
   <Relationship Name="IncludedColumns"><Entry>
    <References Name="[dbo].[Artikel].[Preis]" />
   </Entry></Relationship>
   <Relationship Name="IndexedObject"><Entry>
    <References Name="[dbo].[Artikel]" />
   </Entry></Relationship>
  </Element>

  <!-- Index, dessen Spalten direkt unter `Columns` stehen statt unter
       `ColumnSpecifications`. -->
  <Element Type="SqlIndex" Name="[dbo].[Artikel].[IX_Artikel_Menge]">
   <Relationship Name="Columns"><Entry>
    <References Name="[dbo].[Artikel].[Menge]" />
   </Entry></Relationship>
   <Relationship Name="IndexedObject"><Entry>
    <References Name="[dbo].[Artikel]" />
   </Entry></Relationship>
  </Element>

  <Element Type="SqlCheckConstraint" Name="[dbo].[CK_Artikel_Preis]">
   <Property Name="CheckExpressionScript"><Value><![CDATA[([Preis]>(0))]]></Value></Property>
   <Relationship Name="DefiningTable"><Entry>
    <References Name="[dbo].[Artikel]" />
   </Entry></Relationship>
  </Element>

  <!-- Verwaiste Constraints: ohne Tabelle darf nichts passieren. -->
  <Element Type="SqlPrimaryKeyConstraint" Name="[dbo].[PK_Verwaist]" />
  <Element Type="SqlIndex" Name="[dbo].[IX_Verwaist]" />
  <Element Type="SqlCheckConstraint" Name="[dbo].[CK_Verwaist]" />
  <Element Type="SqlForeignKeyConstraint" Name="[dbo].[FK_Verwaist]" />
  <Element Type="SqlDefaultConstraint" Name="[dbo].[DF_Verwaist]" />

  <!-- Fremdschlüssel ohne ForeignTable: unvollständig, also zu überspringen. -->
  <Element Type="SqlForeignKeyConstraint" Name="[dbo].[FK_OhneZiel]">
   <Relationship Name="DefiningTable"><Entry>
    <References Name="[dbo].[Artikel]" />
   </Entry></Relationship>
  </Element>

  <!-- Fremdschlüssel in eine Nachbardatenbank. -->
  <Element Type="SqlForeignKeyConstraint" Name="[dbo].[FK_Artikel_Fern]">
   <Relationship Name="Columns"><Entry>
    <References Name="[dbo].[Artikel].[ArtikelId]" />
   </Entry></Relationship>
   <Relationship Name="DefiningTable"><Entry>
    <References Name="[dbo].[Artikel]" />
   </Entry></Relationship>
   <Relationship Name="ForeignColumns"><Entry>
    <References Name="[Nachbar]|[dbo].[Fern].[FernId]" />
   </Entry></Relationship>
   <Relationship Name="ForeignTable"><Entry>
    <References ExternalSource="Nachbar.dacpac" Name="[Nachbar]|[dbo].[Fern]" />
   </Entry></Relationship>
  </Element>

  <!-- Beschreibung einer Tabelle (zweiteiliger Host) … -->
  <Element Type="SqlExtendedProperty" Name="[SqlTableBase].[dbo].[Artikel].[MS_Description]">
   <Property Name="Value"><Value><![CDATA['Alle Artikel, auch die ''alten''']]></Value></Property>
   <Relationship Name="Host"><Entry>
    <References Name="[dbo].[Artikel]" />
   </Entry></Relationship>
  </Element>
  <!-- … eines Parameters … -->
  <Element Type="SqlExtendedProperty" Name="[SqlSubroutineParameter].[dbo].[procMitTabellenparameter].[@Anzahl].[MS_Description]">
   <Property Name="Value"><Value><![CDATA[N'Wie viele']]></Value></Property>
   <Relationship Name="Host"><Entry>
    <References Name="[dbo].[procMitTabellenparameter].[@Anzahl]" />
   </Entry></Relationship>
  </Element>
  <!-- … und zwei, die nichts beitragen. -->
  <Element Type="SqlExtendedProperty" Name="[SqlTableBase].[dbo].[Artikel].[Andere]">
   <Property Name="Value"><Value><![CDATA[N'egal']]></Value></Property>
  </Element>
  <Element Type="SqlExtendedProperty" Name="[SqlTableBase].[dbo].[Artikel].[MS_Description]">
   <Property Name="Value"><Value><![CDATA[N'']]></Value></Property>
  </Element>

  <Element Type="SqlUnbekanntesDing" Name="[dbo].[Egal]" />
 </Model>
</DataSchemaModel>
"""

METADATA = f"""<?xml version="1.0" encoding="utf-8"?>
<DacType xmlns="{NS}"><Name>ErweitertDb</Name><Version>1.2.3.4</Version></DacType>
"""


class ExtendedModelTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory()
        path = make_dacpac(Path(cls._tmp.name), "Erweitert", EXTENDED, METADATA)
        cls.db = extract(str(path))
        cls.obj = cls.db.objects

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    def art(self):
        return self.obj["[dbo].[Artikel]"]

    def cols(self) -> dict:
        return {c.name: c for c in self.art().columns}

    # -- Typen -------------------------------------------------------------

    def test_max_laenge(self) -> None:
        self.assertEqual(self.cols()["Bezeichnung"].type, "nvarchar(max)")

    def test_precision_und_scale(self) -> None:
        self.assertEqual(self.cols()["Preis"].type, "decimal(18,2)")

    def test_precision_ohne_scale(self) -> None:
        self.assertEqual(self.cols()["Menge"].type, "decimal(9)")

    def test_scale_ohne_precision(self) -> None:
        self.assertEqual(self.cols()["Erfasst"].type, "time(7)")

    def test_laenge_bei_untypischem_typ(self) -> None:
        """`image` steht in keiner der beiden Listen, die Länge gilt trotzdem."""
        self.assertEqual(self.cols()["Rohdaten"].type, "image(16)")

    def test_typspezifizierer_ohne_typ(self) -> None:
        self.assertEqual(self.cols()["Ohne"].type, "")

    def test_benutzerdefinierter_tabellentyp_als_parameter(self) -> None:
        proc = self.obj["[dbo].[procMitTabellenparameter]"]
        liste = {p.name: p for p in proc.parameters}["@Liste"]
        self.assertEqual(liste.type, "dbo.ArtikelListe")
        self.assertTrue(liste.readonly)

    def test_ausgabeparameter_mit_standardwert(self) -> None:
        proc = self.obj["[dbo].[procMitTabellenparameter]"]
        anzahl = {p.name: p for p in proc.parameters}["@Anzahl"]
        self.assertEqual(anzahl.type, "int")
        self.assertTrue(anzahl.output)
        self.assertEqual(anzahl.default, "(0)")

    # -- Spalten -----------------------------------------------------------

    def test_identity_mit_startwert_und_schrittweite(self) -> None:
        self.assertEqual(self.cols()["Nummer"].identity, "1000,5")

    def test_rowguid_und_collation(self) -> None:
        zeile = self.cols()["Zeile"]
        self.assertTrue(zeile.rowguid)
        self.assertEqual(zeile.collation, "Latin1_General_BIN2")

    def test_berechnete_spalte(self) -> None:
        gesamt = self.cols()["Gesamt"]
        self.assertTrue(gesamt.computed)
        self.assertEqual(gesamt.type, "berechnet")
        self.assertEqual(gesamt.default, "([Preis]*[Menge])")
        self.assertEqual([r.target for r in gesamt.refs], ["[dbo].[Artikel]"])

    # -- Objektarten -------------------------------------------------------

    def test_sicht(self) -> None:
        view = self.obj["[dbo].[vArtikel]"]
        self.assertEqual(view.kind, "view")
        self.assertIn("SELECT ArtikelId", view.body)
        self.assertTrue(view.sql.startswith("CREATE VIEW"))
        self.assertEqual([c.name for c in view.columns], ["ArtikelId"])
        self.assertIn("[dbo].[Artikel]", [r.target for r in view.refs])

    def test_trigger_ohne_ereignisse_und_ohne_tabelle(self) -> None:
        """Kommt vor, wenn die Tabelle des Triggers nicht mitmodelliert ist."""
        trg = self.obj["[dbo].[trOhneAlles]"]
        self.assertEqual(trg.trigger_events, [])
        self.assertEqual(trg.trigger_on, "[dbo].[NichtModelliert]")

    def test_abhaengigkeit_auf_unbekanntes_objekt(self) -> None:
        proc = self.obj["[dbo].[procMitTabellenparameter]"]
        self.assertIn("[dbo].[GibtEsNicht]", [r.target for r in proc.refs])

    def test_trigger(self) -> None:
        trg = self.obj["[dbo].[trArtikel]"]
        self.assertEqual(trg.kind, "trigger")
        self.assertEqual(trg.trigger_on, "[dbo].[Artikel]")
        self.assertEqual(trg.trigger_events, ["INSERT", "UPDATE"])

    def test_inline_tabellenfunktion(self) -> None:
        fn = self.obj["[dbo].[fnArtikelListe]"]
        self.assertEqual(fn.routine_type, "inline_tvf")
        self.assertEqual(fn.returns, "TABLE")
        self.assertEqual([c.name for c in fn.columns], ["x"])

    def test_mehrschrittige_tabellenfunktion(self) -> None:
        fn = self.obj["[dbo].[fnArtikelTabelle]"]
        self.assertEqual(fn.returns, "TABLE @ergebnis")

    def test_clr_funktion_zeigt_bindung_statt_quelltext(self) -> None:
        fn = self.obj["[dbo].[fnClr]"]
        self.assertTrue(fn.clr)
        self.assertEqual(fn.body, "-- CLR: MeineKlasse.Rechne")

    def test_unbekannte_elementart_wird_uebergangen(self) -> None:
        self.assertNotIn("[dbo].[Egal]", self.obj)

    # -- Indizes und Constraints ------------------------------------------

    def test_indizes_sind_sortiert(self) -> None:
        """Primärschlüssel, dann Unique, dann der Rest – hier ohne PK."""
        idx = self.art().indexes
        self.assertEqual([i.kind for i in idx], ["unique", "index", "index"])

    def test_unique_constraint(self) -> None:
        uq = self.art().indexes[0]
        self.assertEqual(uq.name, "UQ_Artikel_Nummer")
        self.assertEqual(uq.columns, ["Nummer"])
        self.assertTrue(uq.unique)
        self.assertFalse(uq.clustered)

    def test_index_mit_eingeschlossenen_spalten(self) -> None:
        idx = {i.name: i for i in self.art().indexes}["IX_Artikel_Bezeichnung"]
        self.assertEqual(idx.columns, ["Bezeichnung"])
        self.assertEqual(idx.included, ["Preis"])
        self.assertTrue(idx.unique)
        self.assertTrue(idx.clustered)

    def test_index_mit_spalten_ohne_spezifikation(self) -> None:
        idx = {i.name: i for i in self.art().indexes}["IX_Artikel_Menge"]
        self.assertEqual(idx.columns, ["Menge"])
        self.assertFalse(idx.unique)

    def test_check_constraint(self) -> None:
        self.assertEqual([c.name for c in self.art().checks],
                         ["CK_Artikel_Preis"])
        self.assertEqual(self.art().checks[0].expression, "([Preis]>(0))")

    def test_verwaiste_constraints_werden_ignoriert(self) -> None:
        """Ohne auflösbare Tabelle darf nichts angehängt werden."""
        self.assertEqual(len(self.art().indexes), 3)
        self.assertEqual(len(self.art().checks), 1)
        self.assertEqual([fk.name for fk in self.db.foreign_keys],
                         ["FK_Artikel_Fern"])

    def test_fremdschluessel_in_nachbardatenbank(self) -> None:
        fk = self.db.foreign_keys[0]
        self.assertEqual(fk.table, "[dbo].[Artikel]")
        self.assertEqual(fk.columns, ["ArtikelId"])
        self.assertEqual(fk.ref_table, "[dbo].[Fern]")
        self.assertEqual(fk.ref_columns, ["FernId"])
        self.assertEqual(fk.ref_external_db, "Nachbar")

    # -- Beschreibungen und Sonstiges -------------------------------------

    def test_tabellenbeschreibung_mit_verdoppelten_anfuehrungszeichen(self) -> None:
        self.assertEqual(self.art().description,
                         "Alle Artikel, auch die 'alten'")

    def test_parameterbeschreibung_sprengt_nichts(self) -> None:
        proc = self.obj["[dbo].[procMitTabellenparameter]"]
        self.assertEqual([p.name for p in proc.parameters],
                         ["@Liste", "@Anzahl"])

    def test_schema_und_assembly(self) -> None:
        self.assertIn("verkauf", self.db.schemas)
        self.assertIn("dbo", self.db.schemas)
        self.assertEqual(self.db.assemblies, ["MeineAssembly"])

    def test_fremddatenbanken_eingesammelt(self) -> None:
        """Aus `ExternalSource` mit und ohne `.dacpac`-Endung."""
        self.assertIn("Nachbar", self.db.external_dbs)
        self.assertIn("Nachbar2", self.db.external_dbs)

    def test_unbrauchbare_referenzen_werden_verworfen(self) -> None:
        """Ohne Name, mit nur einem Namensteil, und eingebaute Typen: nichts davon
        gehört in den Abhängigkeitsgraphen."""
        proc = self.obj["[dbo].[procMitTabellenparameter]"]
        self.assertEqual(sorted(r.target for r in proc.refs),
                         ["[dbo].[Fern2]", "[dbo].[Fern]", "[dbo].[GibtEsNicht]"])

    def test_metadaten(self) -> None:
        self.assertEqual(self.db.name, "ErweitertDb")
        self.assertEqual(self.db.version, "1.2.3.4")
        # Ohne Header-Element bleibt der Kompatibilitätsgrad leer.
        self.assertEqual(self.db.compatibility, "")


if __name__ == "__main__":
    unittest.main()
