# dbdoku

Erzeugt aus einer oder mehreren `.dacpac` eine vollständig verlinkte
HTML-Dokumentation: alle Tabellen mit ihren Beziehungen, alle Prozeduren,
Funktionen, Sichten und Trigger mit den Tabellen, auf die sie zugreifen, und wer
wen aufruft. **Verweise zwischen den Datenbanken werden aufgelöst und verlinkt** –
eine Prozedur, die in eine Nachbardatenbank schreibt, taucht dort unter
„Verwendet von“ auf.

Reines Python 3 aus der Standardbibliothek – keine Installation, kein
`pip install`, kein Webserver. Die Ausgabe funktioniert per Doppelklick auf
`index.html`.

## Verwendung

Ein ganzer Ordner (der Normalfall bei zusammengehörenden Datenbanken):

```sh
python3 -m dbdoku dacpacs/ -o docs/ -t "Datenbankkatalog"
open docs/index.html
```

Einzelne Dateien gehen ebenso:

```sh
python3 -m dbdoku datenbank.dacpac fremd-db.dacpac -o docs/
```

Optionen:

| Option | Wirkung |
|---|---|
| `-o`, `--out` | Ausgabeordner (Standard: `docs`) |
| `-t`, `--titel` | Titel der Dokumentation (Standard: „Datenbankkatalog“) |
| `--volltext` | Quelltext der Routinen und Sichten durchsuchbar machen; schreibt zusätzlich `assets/quelltext.js` (bei großen Katalogen zweistellige MB), das die Suchseite erst lädt, wenn man dort „Quelltext durchsuchen“ einschaltet |
| `--no-json` | `model.json` nicht mitschreiben (spart bei großen Katalogen einiges) |
| `--check-links` | erzeugte Dokumentation auf tote Verweise prüfen: `python3 -m dbdoku --check-links docs/` |
| `-q`, `--quiet` | keine Statusmeldungen |

## Aufbau der Ausgabe

```
docs/
  index.html              Katalogübersicht: alle Datenbanken, Abhängigkeiten
  suche.html              Suche über alle Datenbanken
  <Datenbank>/
    index.html            Eckdaten, Abhängigkeitsdiagramm, meistgenutzte Tabellen
    tabellen/  sichten/  prozeduren/  funktionen/  trigger/  typen/
```

## Was die Dokumentation enthält

**Tabellenseite** – Spalten mit Datentyp, NULL-Barkeit, Standardwert,
Identity und Beschreibung; Primärschlüssel, Unique-Constraints und Indizes;
Check-Constraints; ausgehende und eingehende Fremdschlüssel (verlinkt);
ein Beziehungsdiagramm der direkten Nachbarn; die Liste aller Prozeduren,
Sichten, Funktionen und Trigger, die auf die Tabelle zugreifen, mit der
Zugriffsart; das rekonstruierte `CREATE TABLE`.

**Prozedur-, Funktions- und Triggerseite** – Parameter mit Typ, Richtung und
Standardwert; verwendete Tabellen und Sichten mit Zugriffsart; „Ruft auf“ und
„Aufgerufen von“; Abhängigkeiten zu anderen Datenbanken; der vollständige
T-SQL-Quelltext mit Zeilennummern und Einfärbung.

**Katalogseite** – alle Datenbanken mit Kennzahlen und die Abhängigkeitsmatrix:
welche Datenbank welche benutzt und wie oft.

**Datenbankseite** – Eckdaten, ein Diagramm der benutzten und benutzenden
Datenbanken, die meistgenutzten Tabellen und die Einstiegspunkte.

**Listenseiten** je Objektart und Datenbank, sortierbar und filterbar, sowie eine
Suche über alle Datenbanken. Die Suche kennt Objektnamen und Beschreibungen; mit
`--volltext` erzeugt kommt auf der Suchseite ein Schalter „Quelltext
durchsuchen“ dazu. Er lädt den Quelltextindex nach – das dauert einen Moment und
kostet Arbeitsspeicher, deshalb ist er nicht voreingestellt – und findet danach
auch Treffer im T-SQL, mit Fundstelle im Ausschnitt.

Die Zugriffsart wird als `S I U D` angezeigt: **S**elect (liest),
**I**nsert (fügt ein), **U**pdate (ändert), **D**elete (löscht).

## Woher die Angaben stammen

Die `.dacpac` enthält in `model.xml` das von DacFx aufgelöste Modell. Welche
Objekte eine Routine berührt, steht dort explizit (`BodyDependencies`) und ist
damit exakt – es wird nicht aus dem Text geraten.

Nicht im Modell steht, **wie** zugegriffen wird. Ob eine Prozedur eine Tabelle
liest oder beschreibt, ermittelt dbdoku deshalb aus dem T-SQL: Kommentare und
Stringliterale werden entfernt, dann werden `INSERT` / `UPDATE` / `DELETE` /
`MERGE` / `TRUNCATE` / `SELECT … INTO` gesucht und über Tabellenaliasse
aufgelöst. Alles, was in den Abhängigkeiten steht und nicht als Schreibzugriff
erkannt wurde, gilt als Lesezugriff.

### Grenzen

* **Dynamisches SQL** (`EXEC(@sql)`, `sp_executesql`) ist grundsätzlich nicht
  analysierbar – die betroffenen Objekte sind in der Ausgabe mit einem Hinweis
  markiert, ihre Abhängigkeitslisten können unvollständig sein.
* **Fremde Datenbanken**: Zugriffe wie `[Fremd-DB].dbo.Kunde` werden auf die
  Tabelle *jener* Datenbank abgebildet, sofern deren `.dacpac` mitgeladen ist –
  und niemals mit der gleichnamigen lokalen Tabelle verwechselt. Fehlt die
  Nachbardatenbank, bleibt der Verweis unverlinkt und wird auf der Katalogseite
  unter „Nicht geladene Datenbanken“ ausgewiesen.
* CLR-Routinen haben keinen T-SQL-Rumpf; statt des Quelltextes wird die
  gebundene Klasse und Methode angezeigt.

## Zwei Eigenheiten des Formats

Beides ist behandelt, aber gut zu wissen, falls die Datei anderweitig
verarbeitet werden soll:

1. `model.xml` ist **nicht XML-1.0-konform**. Steuerzeichen aus T-SQL-Literalen
   werden als `&#x1E;` o. ä. serialisiert; konforme Parser brechen mit
   `reference to invalid character number` ab. dbdoku ersetzt solche Referenzen
   beim Lesen durch `?` und meldet, wie oft das vorkam.
2. Die Datei kann groß sein (bei umfangreichen Datenbanken einige zehn MB
   entpackt). dbdoku streamt sie mit `iterparse` und gibt jedes Objekt nach der
   Verarbeitung frei – Laufzeit rund 11 Sekunden für einen Katalog aus 23
   Datenbanken mit 7.500 Objekten.

Dazu kommt beim Zusammenführen: Datenbanknamen sind in SQL Server nicht
groß-/kleinschreibungsempfindlich. Ein Verweis auf `[Fremd-DB]` meint dieselbe
Datenbank wie die `.dacpac` namens `FREMD-DB`; `master.dacpac` und
`msdb.dacpac` tragen überhaupt keinen Namen und werden über den Dateinamen
zugeordnet.

## Tests

```sh
python3 -m unittest discover -s tests
```

Die Tests bauen zwei synthetische `.dacpac` mit einer gleichnamigen Tabelle und
einem Querverweis zwischen ihnen. Geprüft werden Extraktion, Zusammenführung,
Zugriffsanalyse, Aufrufgraph und Ausgabe – einschließlich der ungültigen
Zeichenreferenz, der Auflösung über Datenbankgrenzen und des Falls, dass die
Nachbardatenbank *nicht* mitgeladen ist (dann darf nichts fälschlich der lokalen
Tabelle zugeschrieben werden).

## Aufbau

| Datei | Aufgabe |
|---|---|
| `dbdoku/dacpac.py` | ZIP-Zugriff, Sanitizing-Stream, `iterparse`-Gerüst |
| `dbdoku/extract.py` | `model.xml` → Objektmodell einer Datenbank |
| `dbdoku/catalog.py` | mehrere .dacpac zusammenführen, Querverweise auflösen |
| `dbdoku/model.py` | Dataclasses und Namensbehandlung |
| `dbdoku/crud.py` | Zugriffsart aus dem T-SQL |
| `dbdoku/graph.py` | Rückwärtsindizes, Aufrufgraph |
| `dbdoku/erd.py` | Beziehungsdiagramme als Inline-SVG |
| `dbdoku/highlight.py` | T-SQL-Einfärbung |
| `dbdoku/render.py` | HTML-Erzeugung |
| `dbdoku/assets/` | Stylesheet und Skript der erzeugten Seiten |

## Lizenz

MIT – siehe [LICENSE](LICENSE).
