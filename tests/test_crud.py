"""Zugriffsanalyse: Quelltext säubern, Namen auflösen, Schreibzugriffe finden.

    python3 -m unittest discover -s tests -v
"""

from __future__ import annotations

import unittest
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dbdoku import crud                                     # noqa: E402
from dbdoku.model import Catalog, Database, DbObject, Ref, gid   # noqa: E402


def katalog(*dbs: tuple[str, list[str]]) -> Catalog:
    """Ein Katalog aus Datenbanknamen und ihren ``schema.tabelle``-Namen."""
    cat = Catalog()
    for name, tables in dbs:
        db = Database(name=name)
        for qualified in tables:
            schema, table = qualified.split(".")
            oid = gid(db.key, f"[{schema}].[{table}]")
            obj = DbObject(id=oid, kind="table", schema=schema, name=table,
                           db=name)
            db.objects[oid] = obj
            cat.objects[oid] = obj
        cat.databases.append(db)
    return cat


def zugriffe(cat: Catalog, body: str, home: str = "haupt",
             refs: list[str] = ()) -> dict[str, str]:
    """Eine Prozedur mit ``body`` analysieren und ihre Zugriffe liefern."""
    oid = gid(home, "[dbo].[proc]")
    proc = DbObject(id=oid, kind="procedure", schema="dbo", name="proc",
                    body=body, refs=[Ref(target=r) for r in refs])
    cat.objects[oid] = proc
    db = cat.by_key(home)
    assert db is not None
    db.objects[oid] = proc
    return crud.analyze(cat)[oid]


class StripNoiseTest(unittest.TestCase):
    def test_zeilenkommentar(self) -> None:
        self.assertEqual(crud.strip_noise("SELECT 1 -- weg\nFROM t").split(),
                         ["SELECT", "1", "FROM", "t"])

    def test_zeilenkommentar_bis_dateiende(self) -> None:
        self.assertEqual(crud.strip_noise("SELECT 1 -- weg").strip(), "SELECT 1")

    def test_blockkommentar(self) -> None:
        self.assertEqual(crud.strip_noise("A /* weg */ B").split(), ["A", "B"])

    def test_verschachtelter_blockkommentar(self) -> None:
        """T-SQL erlaubt Verschachtelung – das innere */ beendet nicht alles."""
        self.assertEqual(
            crud.strip_noise("A /* aussen /* innen */ immer noch weg */ B").split(),
            ["A", "B"])

    def test_unbeendeter_blockkommentar(self) -> None:
        self.assertEqual(crud.strip_noise("A /* der Rest fehlt").strip(), "A")

    def test_stringliteral(self) -> None:
        self.assertEqual(crud.strip_noise("WHERE x = 'DELETE FROM t'").split(),
                         ["WHERE", "x", "="])

    def test_verdoppeltes_anfuehrungszeichen(self) -> None:
        """'a''b' ist ein Literal, kein Ende gefolgt von neuem Anfang."""
        self.assertEqual(crud.strip_noise("A 'a''b' B").split(), ["A", "B"])

    def test_unbeendetes_literal(self) -> None:
        self.assertEqual(crud.strip_noise("A 'der Rest fehlt").strip(), "A")

    def test_klammerbezeichner_bleibt(self) -> None:
        self.assertEqual(crud.strip_noise("FROM [dbo].[Ta ble]"),
                         "FROM [dbo].[Ta ble]")

    def test_unbeendeter_klammerbezeichner(self) -> None:
        self.assertEqual(crud.strip_noise("FROM [dbo"), "FROM [dbo")

    def test_wortgrenzen_bleiben_erhalten(self) -> None:
        """Entferntes wird durch ein Leerzeichen ersetzt, nicht gelöscht."""
        self.assertNotIn("FROMJOIN", crud.strip_noise("FROM'x'JOIN"))


class ResolverTest(unittest.TestCase):
    def setUp(self) -> None:
        self.cat = katalog(("Haupt", ["dbo.Kunde", "verkauf.Kunde"]),
                           ("Nachbar", ["dbo.Kunde"]))
        self.r = crud.Resolver(self.cat)

    def test_zweiteiliger_name(self) -> None:
        self.assertEqual(self.r.resolve("dbo.Kunde", "haupt"),
                         gid("haupt", "[dbo].[Kunde]"))

    def test_mehrdeutiger_kurzname_bleibt_offen(self) -> None:
        """`Kunde` gibt es in zwei Schemata – da ist nichts zu entscheiden."""
        self.assertIsNone(self.r.resolve("Kunde", "haupt"))

    def test_eindeutiger_kurzname(self) -> None:
        self.assertEqual(self.r.resolve("Kunde", "nachbar"),
                         gid("nachbar", "[dbo].[Kunde]"))

    def test_dreiteiliger_name_trifft_die_nachbardatenbank(self) -> None:
        self.assertEqual(self.r.resolve("[Nachbar].dbo.Kunde", "haupt"),
                         gid("nachbar", "[dbo].[Kunde]"))

    def test_eigene_datenbank_dreiteilig_genannt(self) -> None:
        self.assertEqual(self.r.resolve("Haupt.dbo.Kunde", "haupt"),
                         gid("haupt", "[dbo].[Kunde]"))

    def test_unbekannte_datenbank_wird_nicht_lokal_gedeutet(self) -> None:
        """Der wichtigste Fall: lieber nichts als die falsche Tabelle."""
        self.assertIsNone(self.r.resolve("[Fehlt].dbo.Kunde", "haupt"))

    def test_temporaere_tabelle_und_tabellenvariable(self) -> None:
        self.assertIsNone(self.r.resolve("#tmp", "haupt"))
        self.assertIsNone(self.r.resolve("@liste", "haupt"))

    def test_leerer_name(self) -> None:
        self.assertIsNone(self.r.resolve("   ", "haupt"))

    def test_unbekannte_tabelle(self) -> None:
        self.assertIsNone(self.r.resolve("dbo.GibtEsNicht", "haupt"))


class SchreibzugriffTest(unittest.TestCase):
    def setUp(self) -> None:
        self.cat = katalog(("Haupt", ["dbo.Kunde", "dbo.Archiv"]))
        self.kunde = gid("haupt", "[dbo].[Kunde]")
        self.archiv = gid("haupt", "[dbo].[Archiv]")

    def test_insert_update_delete(self) -> None:
        acc = zugriffe(self.cat, """
            INSERT INTO dbo.Kunde (Name) VALUES ('x')
            UPDATE dbo.Kunde SET Name = 'y'
            DELETE FROM dbo.Kunde
        """)
        self.assertEqual(acc[self.kunde], "IUD")

    def test_truncate_gilt_als_loeschen(self) -> None:
        acc = zugriffe(self.cat, "TRUNCATE TABLE dbo.Archiv")
        self.assertEqual(acc[self.archiv], "D")

    def test_select_into_gilt_als_einfuegen(self) -> None:
        acc = zugriffe(self.cat, "SELECT * INTO dbo.Archiv FROM dbo.Kunde")
        self.assertEqual(acc[self.archiv], "I")

    def test_top_klausel_stoert_nicht(self) -> None:
        acc = zugriffe(self.cat, "DELETE TOP (10) FROM dbo.Kunde")
        self.assertEqual(acc[self.kunde], "D")

    def test_merge_ohne_zusatzklauseln(self) -> None:
        acc = zugriffe(self.cat, "MERGE INTO dbo.Kunde AS z USING dbo.Archiv AS q "
                                 "ON z.Id = q.Id WHEN NOT MATCHED THEN INSERT (Id) "
                                 "VALUES (q.Id);")
        self.assertEqual(acc[self.kunde], "I")

    def test_merge_mit_update_und_delete(self) -> None:
        """WHEN MATCHED THEN UPDATE/DELETE gehören zum selben Ziel."""
        acc = zugriffe(self.cat, """
            MERGE INTO dbo.Kunde AS z USING dbo.Archiv AS q ON z.Id = q.Id
            WHEN MATCHED AND q.Weg = 1 THEN DELETE
            WHEN MATCHED THEN UPDATE SET z.Name = q.Name
            WHEN NOT MATCHED THEN INSERT (Id) VALUES (q.Id);
        """)
        self.assertEqual(acc[self.kunde], "IUD")

    def test_alias_wird_aufgeloest(self) -> None:
        acc = zugriffe(self.cat,
                       "UPDATE k SET k.Name = 'x' FROM dbo.Kunde AS k")
        self.assertEqual(acc[self.kunde], "U")

    def test_schluesselwort_ist_kein_alias(self) -> None:
        """`FROM dbo.Kunde WHERE` darf `WHERE` nicht als Alias führen."""
        acc = zugriffe(self.cat, "DELETE FROM dbo.Kunde WHERE Id = 1")
        self.assertEqual(acc, {self.kunde: "D"})

    def test_unbekanntes_ziel_wird_uebergangen(self) -> None:
        self.assertEqual(zugriffe(self.cat, "INSERT INTO #tmp (x) VALUES (1)"), {})

    def test_abhaengigkeit_ohne_quelltext_ist_lesend(self) -> None:
        acc = zugriffe(self.cat, "", refs=[self.kunde])
        self.assertEqual(acc[self.kunde], "S")

    def test_leerer_rumpf_ergibt_nichts(self) -> None:
        self.assertEqual(zugriffe(self.cat, "   \n  "), {})

    def test_nur_kommentar_ergibt_nichts(self) -> None:
        """Nach dem Säubern bleibt nichts übrig – die Schleife muss das aushalten."""
        self.assertEqual(zugriffe(self.cat, "-- INSERT INTO dbo.Kunde"), {})

    def test_lesen_und_schreiben_zusammen(self) -> None:
        acc = zugriffe(self.cat, "INSERT INTO dbo.Kunde (Id) SELECT Id FROM dbo.Archiv",
                       refs=[self.kunde, self.archiv])
        self.assertEqual(acc[self.kunde], "SI")
        self.assertEqual(acc[self.archiv], "S")

    def test_unaufgeloeste_referenz_zaehlt_nicht(self) -> None:
        oid = gid("haupt", "[dbo].[proc2]")
        proc = DbObject(id=oid, kind="procedure", schema="dbo", name="proc2",
                        refs=[Ref(target="fehlt|[dbo].[X]", resolved=False)])
        self.cat.objects[oid] = proc
        self.cat.by_key("haupt").objects[oid] = proc
        self.assertEqual(crud.analyze(self.cat)[oid], {})

    def test_nur_routinen_und_sichten_werden_analysiert(self) -> None:
        """Tabellen haben keinen Rumpf und tauchen im Ergebnis nicht auf."""
        result = crud.analyze(self.cat)
        self.assertNotIn(self.kunde, result)


if __name__ == "__main__":
    unittest.main()
