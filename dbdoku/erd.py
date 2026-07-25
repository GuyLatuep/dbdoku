"""Beziehungsdiagramme als Inline-SVG.

Bewusst ohne Mermaid o. ae.: die Diagramme sind klein und regelmaessig, und die
Ausgabe soll ohne Netzverbindung und ohne mitgelieferte JS-Bibliothek
funktionieren. Der Mermaid-Quelltext wird zusaetzlich ausgegeben, damit man ihn
in ein Wiki oder Ticket kopieren kann.

Zwei Diagrammarten: die Nachbarschaft einer Tabelle (:func:`diagram`) und die
Abhaengigkeiten einer Datenbank (:func:`database_diagram`). Beide teilen sich
dasselbe Layout — Mitte, linke Spalte, rechte Spalte.
"""

from __future__ import annotations

import html
from typing import Optional, Tuple

from .graph import Graph
from .model import ForeignKey

ROW = 44          # vertikaler Abstand zweier Nachbarknoten
BOX_H = 26
MIN_GAP = 64      # kleinster horizontaler Abstand zwischen den Spalten
PAD = 12
CHAR_W = 6.7      # Schaetzung fuer 12.5px Monospace
LABEL_W = 5.9     # Schaetzung fuer 10.5px Monospace
MAX_SIDE = 12     # mehr Nachbarn je Seite werden nicht gezeichnet

# (Beschriftung, Kantentext, Ziel-Id oder None). Als typing-Alias geschrieben,
# weil er zur Laufzeit ausgewertet wird und Python 3.9 dort kein `X | None` kann.
Node = Tuple[str, str, Optional[str]]


def _width(text: str) -> float:
    return max(70.0, len(text) * CHAR_W + 22)


def _gap(labels: list[str]) -> float:
    """Spaltenabstand so waehlen, dass die Kantenbeschriftungen hineinpassen."""
    longest = max((len(l) for l in labels), default=0)
    return max(MIN_GAP, longest * LABEL_W + 26)


def _box(x: float, y: float, w: float, label: str, href: str | None,
         cls: str) -> str:
    rect = (
        f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{BOX_H}" '
        f'rx="5" class="{cls}"/>'
        f'<text x="{x + w / 2:.1f}" y="{y + BOX_H / 2 + 4.3:.1f}" '
        f'text-anchor="middle" class="erd-text">{html.escape(label)}</text>'
    )
    if href:
        return f'<a href="{html.escape(href, quote=True)}">{rect}</a>'
    return rect


def _edge(x1: float, y1: float, x2: float, y2: float, label: str,
          anchor: str = "start", arrow_at_neighbour: bool = False) -> str:
    """Kante von (x1,y1) — dem Nachbarknoten — nach (x2,y2) — der Mitte.

    Die Beschriftung sitzt am Nachbarende, nicht in der Mitte: bei einem Dutzend
    Kanten, die auf denselben Punkt zulaufen, wuerden mittige Beschriftungen
    uebereinanderliegen.

    Die Pfeilspitze zeigt immer auf die referenzierte Seite. Verweist die Mitte
    auf den Nachbarn, sitzt sie am Nachbarende (``marker-start`` dreht sich dank
    ``auto-start-reverse`` von der Kante weg).
    """
    mid = (x1 + x2) / 2
    marker = ('marker-start="url(#erd-arrow)"' if arrow_at_neighbour
              else 'marker-end="url(#erd-arrow)"')
    path = (
        f'<path d="M {x1:.1f} {y1:.1f} C {mid:.1f} {y1:.1f} {mid:.1f} {y2:.1f} '
        f'{x2:.1f} {y2:.1f}" class="erd-edge" {marker}/>'
    )
    if not label:
        return path
    lx = x1 + (7 if anchor == "start" else -7)
    return (
        f'{path}<text x="{lx:.1f}" y="{y1 - 5:.1f}" text-anchor="{anchor}" '
        f'class="erd-label">{html.escape(label)}</text>'
    )


def _render(center: str, left: list[Node], right: list[Node], url_of,
            aria: str) -> tuple[str, int, int]:
    """Gemeinsames Layout: Mitte, Verweisziele links, Verweisende rechts."""
    total = len(left) + len(right)
    if total == 0:
        return "", 0, 0
    left_shown, right_shown = left[:MAX_SIDE], right[:MAX_SIDE]
    shown = len(left_shown) + len(right_shown)

    lw = max((_width(l) for l, _, _ in left_shown), default=0.0)
    cw = _width(center)
    rw = max((_width(l) for l, _, _ in right_shown), default=0.0)

    left_x = PAD
    center_x = PAD + (lw + _gap([c for _, c, _ in left_shown]) if lw else 0)
    right_x = center_x + cw + (_gap([c for _, c, _ in right_shown]) if rw else 0)
    width = right_x + rw + PAD

    rows = max(len(left_shown), len(right_shown), 1)
    height = rows * ROW + PAD * 2
    cy = height / 2 - BOX_H / 2

    def column_y(index: int, count: int) -> float:
        span = count * ROW
        top = (height - span) / 2 + (ROW - BOX_H) / 2
        return top + index * ROW

    parts = [
        f'<svg viewBox="0 0 {width:.0f} {height:.0f}" width="{width:.0f}" '
        f'height="{height:.0f}" class="erd" role="img" '
        f'aria-label="{html.escape(aria, quote=True)}">',
        '<defs><marker id="erd-arrow" viewBox="0 0 8 8" refX="7" refY="4" '
        'markerWidth="7" markerHeight="7" orient="auto-start-reverse">'
        '<path d="M 0 1 L 7 4 L 0 7 z" class="erd-arrow"/></marker></defs>',
    ]

    # Kanten zuerst, damit die Kaesten darueber liegen.
    for i, (_, cols, _) in enumerate(left_shown):
        parts.append(_edge(left_x + lw, column_y(i, len(left_shown)) + BOX_H / 2,
                           center_x, cy + BOX_H / 2, cols, "start",
                           arrow_at_neighbour=True))
    for i, (_, cols, _) in enumerate(right_shown):
        parts.append(_edge(right_x, column_y(i, len(right_shown)) + BOX_H / 2,
                           center_x + cw, cy + BOX_H / 2, cols, "end"))

    for i, (label, _, target) in enumerate(left_shown):
        parts.append(_box(left_x, column_y(i, len(left_shown)), lw, label,
                          url_of(target) if target else None, "erd-box"))
    for i, (label, _, target) in enumerate(right_shown):
        parts.append(_box(right_x, column_y(i, len(right_shown)), rw, label,
                          url_of(target) if target else None, "erd-box"))
    parts.append(_box(center_x, cy, cw, center, None, "erd-box erd-center"))
    parts.append("</svg>")
    return "".join(parts), shown, total


def _label(catalog, table_id: str, home: str) -> str:
    """Tabellen aus anderen Datenbanken werden mit Datenbank benannt."""
    obj = catalog.objects.get(table_id)
    if obj is None:
        return table_id.replace("[", "").replace("]", "")
    return obj.display if table_id.startswith(home + "|") else obj.qualified


def diagram(table_id: str, graph: Graph, url_of) -> tuple[str, int, int]:
    """Nachbarschaft einer Tabelle. Liefert SVG, gezeigte und vorhandene Kanten."""
    catalog = graph.catalog
    center = catalog.objects[table_id]
    home = table_id.split("|", 1)[0]

    left: list[Node] = []
    seen: set[tuple[str, str]] = set()
    for fk in graph.fk_out.get(table_id, []):
        if fk.ref_table in catalog.objects:
            label, target = _label(catalog, fk.ref_table, home), fk.ref_table
        else:
            label, target = f"{fk.ref_external_db or '?'}: " + \
                fk.ref_table.replace("[", "").replace("]", ""), None
        key = (label, ",".join(fk.columns))
        if key in seen:
            continue
        seen.add(key)
        left.append((label, ", ".join(fk.columns), target))

    right: list[Node] = []
    seen.clear()
    for fk in graph.fk_in.get(table_id, []):
        if fk.table not in catalog.objects:
            continue
        label = _label(catalog, fk.table, home)
        key = (label, ",".join(fk.columns))
        if key in seen:
            continue
        seen.add(key)
        right.append((label, ", ".join(fk.columns), fk.table))

    return _render(center.display, left, right, url_of,
                   f"Beziehungen von {center.qualified}")


def database_diagram(db_key: str, graph: Graph, url_of) -> tuple[str, int, int]:
    """Welche Datenbanken diese benutzt und von welchen sie benutzt wird."""
    catalog = graph.catalog
    db = catalog.by_key(db_key)
    if db is None:
        return "", 0, 0

    def name_of(key: str) -> str:
        other = catalog.by_key(key)
        return other.name if other else key

    left: list[Node] = [
        (name_of(key), f"{count} Verweise" if count > 1 else "1 Verweis", key)
        for key, count in sorted(graph.db_uses.get(db_key, {}).items(),
                                 key=lambda i: -i[1])
    ]
    right: list[Node] = [
        (name_of(key), f"{count} Verweise" if count > 1 else "1 Verweis", key)
        for key, count in sorted(graph.db_used_by.get(db_key, {}).items(),
                                 key=lambda i: -i[1])
    ]
    return _render(db.name, left, right, url_of,
                   f"Abhaengigkeiten von {db.name}")


def mermaid(table_id: str, graph: Graph) -> str:
    """Gleiches Tabellendiagramm als Mermaid-Quelltext zum Kopieren."""
    catalog = graph.catalog
    center = catalog.objects[table_id]
    home = table_id.split("|", 1)[0]
    lines = ["erDiagram"]

    def node(name: str) -> str:
        return name.replace(".", "_").replace("-", "_")

    def add(fk: ForeignKey, parent: str, child: str) -> None:
        cols = ", ".join(fk.columns) or fk.name
        lines.append(f'    {node(parent)} ||--o{{ {node(child)} : "{cols}"')

    for fk in graph.fk_out.get(table_id, []):
        if fk.ref_table in catalog.objects:
            parent = _label(catalog, fk.ref_table, home)
        else:
            parent = f"{fk.ref_external_db}_" + fk.ref_table.replace("[", "").replace("]", "")
        add(fk, parent, center.display)
    for fk in graph.fk_in.get(table_id, []):
        if fk.table in catalog.objects:
            add(fk, center.display, _label(catalog, fk.table, home))
    return "\n".join(lines) if len(lines) > 1 else ""
