"""Kommandozeile.

    python3 -m dbdoku dacpacs/ -o docs/
    python3 -m dbdoku eine.dacpac zweite.dacpac -o docs/
    python3 -m dbdoku dacpacs/ -o docs/ --llm      # zusätzlich docs/llm/ für KI
    python3 -m dbdoku --check-links docs/
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import re
import sys
import time
from pathlib import Path
from urllib.parse import unquote

from . import __version__, catalog as catalog_mod, crud, graph, llm, render
from .dacpac import DacpacError
from .model import KINDS


def build(sources: list[Path], out: Path, title: str, write_json: bool,
          quiet: bool, fulltext: bool = False, html: bool = True,
          for_llm: bool = False) -> int:
    def say(msg: str) -> None:
        if not quiet:
            print(msg, file=sys.stderr)

    paths = catalog_mod.dacpac_paths(sources)
    if not paths:
        print("Keine .dacpac-Dateien gefunden.", file=sys.stderr)
        return 2
    missing = [p for p in paths if not p.is_file()]
    if missing:
        print(f"Nicht gefunden: {', '.join(str(p) for p in missing)}", file=sys.stderr)
        return 2

    start = time.time()
    say(f"Lese {len(paths)} .dacpac …")
    try:
        cat = catalog_mod.load(paths)
    except DacpacError as exc:
        print(f"Fehler: {exc}", file=sys.stderr)
        return 2

    for db in cat.databases:
        counts = ", ".join(f"{db.count(k)} {KINDS[k][1]}" for k in render.NAV
                           if db.count(k))
        say(f"  {db.name:<22} {db.total:>5} Objekte" + (f"  ({counts})" if counts else ""))
    if cat.sanitized_refs:
        say(f"  Hinweis: {cat.sanitized_refs} ungültige XML-Zeichenreferenzen "
            "wurden durch '?' ersetzt.")
    if cat.unresolved_dbs:
        say(f"  Hinweis: nicht geladen und daher nicht verlinkt: "
            f"{', '.join(sorted(cat.unresolved_dbs))}")

    say("Analysiere Zugriffe …")
    access = crud.analyze(cat)
    g = graph.build(cat, access)
    cross = sum(sum(t.values()) for t in g.db_uses.values())
    say(f"  {cat.total} Objekte, {len(cat.foreign_keys)} Fremdschlüssel, "
        f"{cross} datenbankübergreifende Verweise")

    say(f"Schreibe nach {out} …")
    written = 0
    if html:
        renderer = render.Renderer(cat, g, out, title, fulltext)
        written = renderer.write()
        if fulltext:
            size = (out / "assets" / "quelltext.js").stat().st_size
            say(f"  Quelltextindex: {size / 1e6:.1f} MB (wird nur auf Wunsch geladen)")
    if for_llm:
        written += llm.LlmWriter(cat, g, out / "llm", title).write()
    if write_json:
        out.mkdir(parents=True, exist_ok=True)
        (out / "model.json").write_text(
            json.dumps(_as_dict(cat), ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8")

    say(f"Fertig: {written} Dateien in {time.time() - start:.1f} s.")
    if not quiet:
        print(out / "index.html" if html else out / "llm" / "README.md")
    return 0


def _as_dict(value) -> dict:
    def convert(v):
        if dataclasses.is_dataclass(v):
            return {k: convert(x) for k, x in dataclasses.asdict(v).items()}
        if isinstance(v, dict):
            return {k: convert(x) for k, x in v.items()}
        if isinstance(v, (list, tuple)):
            return [convert(x) for x in v]
        if isinstance(v, set):
            return sorted(v)
        return v

    return convert(value)


_HREF = re.compile(r'(?:href|xlink:href)="([^"]+)"')
_MD_LINK = re.compile(r"\]\(([^)\s]+)\)")
# Quelltextblöcke enthalten T-SQL wie ``[a](@b)``, das kein Verweis ist.
_MD_FENCE = re.compile(r"^(`{3,}).*?^\1$", re.M | re.S)


def check_links(root: Path, quiet: bool) -> int:
    pages = sorted(root.rglob("*.html")) + sorted(root.rglob("*.md"))
    if not pages:
        print(f"Keine HTML-Dateien oder Markdown-Dateien unter {root}.", file=sys.stderr)
        return 2
    broken: list[tuple[Path, str]] = []
    total = 0
    for page in pages:
        text = page.read_text(encoding="utf-8")
        if page.suffix == ".md":
            pattern, text = _MD_LINK, _MD_FENCE.sub("", text)
        else:
            pattern = _HREF
        for raw in pattern.findall(text):
            if raw.startswith(("#", "http:", "https:", "mailto:", "data:")):
                continue
            total += 1
            target = (page.parent / unquote(raw.split("#", 1)[0])).resolve()
            if not target.exists():
                broken.append((page, raw))
    if not quiet:
        print(f"{len(pages)} Seiten, {total} interne Verweise geprüft.")
    for page, raw in broken[:50]:
        print(f"  tot: {page.relative_to(root)} -> {raw}", file=sys.stderr)
    if broken:
        print(f"{len(broken)} tote Verweise.", file=sys.stderr)
        return 1
    if not quiet:
        print("Keine toten Verweise.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="dbdoku",
        description="Erzeugt eine verlinkte HTML-Dokumentation aus einer oder "
                    "mehreren .dacpac. Verweise zwischen den Datenbanken werden "
                    "aufgelöst.")
    parser.add_argument("quelle", type=Path, nargs="+",
                        help=".dacpac-Dateien oder ein Ordner mit .dacpac; "
                             "bei --check-links der Ausgabeordner")
    parser.add_argument("-o", "--out", type=Path, default=Path("docs"),
                        help="Ausgabeordner (Standard: docs)")
    parser.add_argument("-t", "--titel", default="Datenbankkatalog",
                        help="Titel der Dokumentation")
    parser.add_argument("--volltext", action="store_true",
                        help="Quelltext der Routinen und Sichten durchsuchbar "
                             "machen (eigener, großer Index, den die Suchseite "
                             "erst auf Wunsch nachlädt)")
    parser.add_argument("--no-json", action="store_true",
                        help="model.json nicht mitschreiben (vollständiger Datenabzug "
                             "für Skripte; als Kontext für KI ist --llm gedacht)")
    parser.add_argument("--llm", action="store_true",
                        help="zusätzlich llm/ schreiben: kompaktes Markdown je Objekt "
                             "plus schema.sql und relations.md je Datenbank, als "
                             "Kontext für KI-Assistenten wie Claude")
    parser.add_argument("--nur-llm", action="store_true",
                        help="nur llm/ schreiben, keine HTML-Seiten")
    parser.add_argument("--check-links", action="store_true",
                        help="erzeugte Dokumentation auf tote Verweise prüfen")
    parser.add_argument("-q", "--quiet", action="store_true",
                        help="keine Statusmeldungen")
    parser.add_argument("--version", action="version", version=f"dbdoku {__version__}")
    args = parser.parse_args(argv)

    if args.check_links:
        return check_links(args.quelle[0], args.quiet)
    return build(args.quelle, args.out, args.titel, not args.no_json, args.quiet,
                 args.volltext, html=not args.nur_llm,
                 for_llm=args.llm or args.nur_llm)


if __name__ == "__main__":
    raise SystemExit(main())
