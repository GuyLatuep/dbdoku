"""Tests der Kommandozeile: ``build``, ``check_links`` und ``main``.

    python3 -m unittest discover -s tests -v
"""

from __future__ import annotations

import io
import json
import tempfile
import unittest
import zipfile
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dbdoku import __main__ as cli                          # noqa: E402
from dbdoku import catalog as cm                            # noqa: E402

from test_dbdoku import MODEL, make_dacpac, make_katalog     # noqa: E402


class Run:
    """Ergebnis eines CLI-Laufs samt abgefangener Ausgabe."""

    def __init__(self, code: int, out: str, err: str) -> None:
        self.code, self.out, self.err = code, out, err


def run(fn, *args, **kwargs) -> Run:
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = fn(*args, **kwargs)
    return Run(code, out.getvalue(), err.getvalue())


class BuildTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.src = self.tmp / "src"
        self.src.mkdir()
        make_katalog(self.src)
        self.out = self.tmp / "docs"
        self.addCleanup(self._tmp.cleanup)

    def test_erzeugt_dokumentation_und_model_json(self) -> None:
        r = run(cli.build, [self.src], self.out, "Katalog", True, True)
        self.assertEqual(r.code, 0)
        self.assertTrue((self.out / "index.html").exists())
        model = json.loads((self.out / "model.json").read_text(encoding="utf-8"))
        self.assertIn("databases", model)
        # Mengen werden als sortierte Listen serialisiert, nicht als set.
        schemas = model["databases"][0]["schemas"]
        self.assertIsInstance(schemas, list)
        self.assertEqual(schemas, sorted(schemas))

    def test_no_json_laesst_model_json_weg(self) -> None:
        r = run(cli.build, [self.src], self.out, "Katalog", False, True)
        self.assertEqual(r.code, 0)
        self.assertFalse((self.out / "model.json").exists())

    def test_quiet_schweigt(self) -> None:
        r = run(cli.build, [self.src], self.out, "Katalog", True, True)
        self.assertEqual(r.out, "")
        self.assertEqual(r.err, "")

    def test_ohne_quiet_wird_berichtet(self) -> None:
        r = run(cli.build, [self.src], self.out, "Katalog", True, False)
        self.assertEqual(r.code, 0)
        # Der Pfad der Startseite geht nach stdout, der Fortschritt nach stderr.
        self.assertIn("index.html", r.out)
        self.assertIn("Lese 2 .dacpac", r.err)
        self.assertIn("Analysiere Zugriffe", r.err)
        self.assertIn("Fertig:", r.err)
        self.assertIn("TestDbs", r.err)
        # Die synthetische .dacpac enthält eine ungültige Zeichenreferenz.
        self.assertIn("ungültige XML-Zeichenreferenzen", r.err)

    def test_fehlende_nachbardatenbank_wird_gemeldet(self) -> None:
        src = self.tmp / "allein"
        src.mkdir()
        make_katalog(src, mit_nachbar=False)
        r = run(cli.build, [src], self.out, "Katalog", True, False)
        self.assertEqual(r.code, 0)
        self.assertIn("nicht geladen und daher nicht verlinkt", r.err)
        self.assertIn("Fremd-DB", r.err)

    def test_volltext_meldet_indexgroesse(self) -> None:
        r = run(cli.build, [self.src], self.out, "Katalog", False, False,
                fulltext=True)
        self.assertEqual(r.code, 0)
        self.assertTrue((self.out / "assets" / "quelltext.js").exists())
        self.assertIn("Quelltextindex:", r.err)
        self.assertIn("MB", r.err)

    def test_leerer_ordner(self) -> None:
        leer = self.tmp / "leer"
        leer.mkdir()
        r = run(cli.build, [leer], self.out, "Katalog", True, True)
        self.assertEqual(r.code, 2)
        self.assertIn("Keine .dacpac-Dateien gefunden.", r.err)

    def test_datei_fehlt(self) -> None:
        r = run(cli.build, [self.tmp / "gibtesnicht.dacpac"], self.out,
                "Katalog", True, True)
        self.assertEqual(r.code, 2)
        self.assertIn("Nicht gefunden:", r.err)

    def test_kaputte_dacpac_bricht_nicht_durch(self) -> None:
        """Ein DacpacError wird zur Fehlermeldung, nicht zum Traceback."""
        kaputt = self.tmp / "kaputt.dacpac"
        kaputt.write_text("kein zip", encoding="utf-8")
        r = run(cli.build, [kaputt], self.out, "Katalog", True, True)
        self.assertEqual(r.code, 2)
        self.assertTrue(r.err.startswith("Fehler:"))


class AsDictTest(unittest.TestCase):
    def test_konvertiert_dataclass_dict_liste_und_menge(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = make_katalog(Path(tmp))
            data = cli._as_dict(cm.load(paths))
        db = data["databases"][0]
        self.assertIsInstance(data, dict)
        self.assertIsInstance(db["objects"], dict)
        self.assertIsInstance(db["foreign_keys"], list)
        self.assertIsInstance(db["schemas"], list)
        # Muss ohne Umweg über einen Encoder JSON-fähig sein.
        json.dumps(data, ensure_ascii=False)


class CheckLinksTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def test_ohne_html_dateien(self) -> None:
        r = run(cli.check_links, self.tmp, True)
        self.assertEqual(r.code, 2)
        self.assertIn("Keine HTML-Dateien", r.err)

    def test_heile_verweise(self) -> None:
        (self.tmp / "a.html").write_text('<a href="b.html">b</a>', encoding="utf-8")
        (self.tmp / "b.html").write_text("ok", encoding="utf-8")
        r = run(cli.check_links, self.tmp, False)
        self.assertEqual(r.code, 0)
        self.assertIn("2 Seiten, 1 interne Verweise geprüft.", r.out)
        self.assertIn("Keine toten Verweise.", r.out)

    def test_toter_verweis(self) -> None:
        (self.tmp / "a.html").write_text('<a href="weg.html">x</a>', encoding="utf-8")
        r = run(cli.check_links, self.tmp, True)
        self.assertEqual(r.code, 1)
        self.assertIn("tot: a.html -> weg.html", r.err)
        self.assertIn("1 tote Verweise.", r.err)

    def test_externe_und_ankerverweise_werden_uebergangen(self) -> None:
        (self.tmp / "a.html").write_text(
            '<a href="#oben">o</a><a href="https://example.invalid/x">e</a>'
            '<a href="http://example.invalid/y">e</a>'
            '<a href="mailto:wer@example.invalid">m</a>'
            '<a href="data:text/plain,x">d</a>',
            encoding="utf-8")
        r = run(cli.check_links, self.tmp, False)
        self.assertEqual(r.code, 0)
        self.assertIn("1 Seiten, 0 interne Verweise geprüft.", r.out)

    def test_anker_und_prozentkodierung_am_ziel(self) -> None:
        """Der Anker gehört nicht zum Dateinamen, %20 schon."""
        (self.tmp / "mit platz.html").write_text("ok", encoding="utf-8")
        (self.tmp / "a.html").write_text(
            '<a href="mit%20platz.html#unten">x</a>', encoding="utf-8")
        r = run(cli.check_links, self.tmp, True)
        self.assertEqual(r.code, 0)

    def test_svg_xlink_wird_mitgeprueft(self) -> None:
        (self.tmp / "a.html").write_text(
            '<svg><a xlink:href="weg.html"><rect/></a></svg>', encoding="utf-8")
        r = run(cli.check_links, self.tmp, True)
        self.assertEqual(r.code, 1)

    def test_es_werden_hoechstens_50_gemeldet(self) -> None:
        links = "".join(f'<a href="weg{i}.html">x</a>' for i in range(60))
        (self.tmp / "a.html").write_text(links, encoding="utf-8")
        r = run(cli.check_links, self.tmp, True)
        self.assertEqual(r.code, 1)
        self.assertEqual(r.err.count("  tot:"), 50)
        self.assertIn("60 tote Verweise.", r.err)


class MainTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def test_baut_mit_standardwerten(self) -> None:
        src = self.tmp / "src"
        src.mkdir()
        make_katalog(src)
        out = self.tmp / "docs"
        r = run(cli.main, [str(src), "-o", str(out), "-q"])
        self.assertEqual(r.code, 0)
        self.assertTrue((out / "index.html").exists())
        self.assertTrue((out / "model.json").exists())

    def test_titel_landet_in_der_seite(self) -> None:
        src = self.tmp / "src"
        src.mkdir()
        make_katalog(src)
        out = self.tmp / "docs"
        run(cli.main, [str(src), "-o", str(out), "-t", "Mein Katalog",
                       "--no-json", "-q"])
        self.assertIn("Mein Katalog",
                      (out / "index.html").read_text(encoding="utf-8"))
        self.assertFalse((out / "model.json").exists())

    def test_check_links_wird_durchgereicht(self) -> None:
        (self.tmp / "a.html").write_text('<a href="weg.html">x</a>',
                                         encoding="utf-8")
        r = run(cli.main, ["--check-links", str(self.tmp), "-q"])
        self.assertEqual(r.code, 1)

    def test_version(self) -> None:
        from dbdoku import __version__
        out = io.StringIO()
        with redirect_stdout(out), self.assertRaises(SystemExit) as raised:
            cli.main(["--version"])
        self.assertEqual(raised.exception.code, 0)
        self.assertIn(__version__, out.getvalue())


class PathsTest(unittest.TestCase):
    def test_doppelt_genannte_dateien_zaehlen_einmal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = make_dacpac(Path(tmp))
            paths = cm.dacpac_paths([path, path, Path(tmp)])
            self.assertEqual(len(paths), 1)

    def test_namenlose_dacpac_erbt_den_dateinamen(self) -> None:
        """master.dacpac und msdb.dacpac tragen keinen Namen in DacMetadata.xml."""
        with tempfile.TemporaryDirectory() as tmp:
            ohne_namen = '<?xml version="1.0" encoding="utf-8"?><DacType />'
            path = make_dacpac(Path(tmp), "master", MODEL, ohne_namen)
            catalog = cm.load([path])
            self.assertEqual(catalog.databases[0].name, "master")


if __name__ == "__main__":
    unittest.main()
