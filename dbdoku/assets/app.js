/* dbdoku – Sortierung, Filter und Suche. Ohne Abhaengigkeiten. */
(function () {
  "use strict";

  var fold = function (s) {
    return s.toLowerCase()
      .replace(/ä/g, "ae").replace(/ö/g, "oe").replace(/ü/g, "ue")
      .replace(/ß/g, "ss");
  };

  /* -------------------------------------------------- Spalten sortieren */

  function sortable(table) {
    var headers = table.tHead ? table.tHead.rows[0].cells : [];
    Array.prototype.forEach.call(headers, function (th, index) {
      th.addEventListener("click", function () {
        var body = table.tBodies[0];
        var rows = Array.prototype.slice.call(body.rows);
        var desc = th.classList.contains("asc");

        Array.prototype.forEach.call(headers, function (other) {
          other.classList.remove("asc", "desc");
        });
        th.classList.add(desc ? "desc" : "asc");

        var key = function (row) {
          var text = (row.cells[index] || {}).textContent || "";
          return text.trim();
        };
        var numeric = rows.every(function (row) {
          var v = key(row);
          return v === "" || /^-?\d+(\.\d+)?$/.test(v);
        });

        rows.sort(function (a, b) {
          var x = key(a), y = key(b);
          var result = numeric
            ? (parseFloat(x || "0") - parseFloat(y || "0"))
            : fold(x).localeCompare(fold(y), "de");
          return desc ? -result : result;
        });
        var frag = document.createDocumentFragment();
        rows.forEach(function (row) { frag.appendChild(row); });
        body.appendChild(frag);
      });
    });
  }

  Array.prototype.forEach.call(document.querySelectorAll("table.sortable"), sortable);

  /* ------------------------------------------------------ Listen filtern */

  var filter = document.querySelector(".filter[data-filter]");
  if (filter) {
    var scope = document.getElementById(filter.getAttribute("data-filter"));
    var rows = scope ? Array.prototype.slice.call(scope.querySelectorAll("tbody tr")) : [];
    var cache = rows.map(function (row) { return fold(row.textContent); });
    var apply = function () {
      var terms = fold(filter.value).split(/\s+/).filter(Boolean);
      rows.forEach(function (row, i) {
        var hit = terms.every(function (t) { return cache[i].indexOf(t) !== -1; });
        row.style.display = hit ? "" : "none";
      });
    };
    filter.addEventListener("input", apply);
    apply();
  }

  /* --------------------------------------------------------------- Suche */

  var box = document.getElementById("q");
  var results = document.getElementById("results");
  if (box && results) {
    // suchindex.js wird als <script> geladen, damit die Suche auch beim
    // Oeffnen ueber file:// funktioniert.
    var index = null;
    if (window.DBDOKU_INDEX) {
      index = window.DBDOKU_INDEX.map(function (row) {
        return { name: row[0], kind: row[1], url: row[2], desc: row[3], db: row[4],
                 hay: fold(row[4] + " " + row[0] + " " + row[3]) };
      });
    } else {
      results.innerHTML = '<p class="note">Der Suchindex konnte nicht geladen ' +
        'werden (assets/suchindex.js fehlt). Die Listenseiten haben jeweils ' +
        'ein eigenes Filterfeld.</p>';
    }

    var escapeHtml = function (s) {
      return s.replace(/[&<>"]/g, function (c) {
        return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c];
      });
    };

    var mark = function (text, terms) {
      var out = escapeHtml(text);
      terms.forEach(function (t) {
        if (!t) { return; }
        var re = new RegExp("(" + t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&") + ")", "ig");
        out = out.replace(re, "<mark>$1</mark>");
      });
      return out;
    };

    /* ------------------------------------------------- Volltext (optional) */

    // Der Quelltextindex ist gross und wird deshalb erst nachgeladen, wenn
    // die Volltextsuche eingeschaltet wird.
    var srcBox = document.getElementById("src");
    var srcState = "off";   // off | laden | bereit | fehlt

    var foldSource = function () {
      var src = window.DBDOKU_SOURCE || [];
      index.forEach(function (row, i) {
        row.sql = src[i] || "";
        row.sqlhay = row.sql ? fold(row.sql) : "";
      });
    };

    var loadSource = function (done) {
      if (srcState === "bereit" || srcState === "fehlt") { return done(); }
      srcState = "laden";
      results.innerHTML = '<p class="note">Quelltextindex wird geladen …</p>';
      var script = document.createElement("script");
      script.src = "assets/quelltext.js";
      script.onload = function () {
        foldSource();
        srcState = "bereit";
        done();
      };
      script.onerror = function () {
        srcState = "fehlt";
        done();
      };
      document.head.appendChild(script);
    };

    // Ausschnitt um den ersten Treffer, damit die Fundstelle sichtbar wird.
    var snippet = function (row, terms) {
      var at = -1;
      terms.forEach(function (t) {
        var p = row.sqlhay.indexOf(t);
        if (p !== -1 && (at === -1 || p < at)) { at = p; }
      });
      if (at === -1) { return ""; }
      var from = Math.max(0, at - 60);
      var text = row.sql.slice(from, at + 140).replace(/\s+/g, " ");
      return (from > 0 ? "… " : "") + text + " …";
    };

    function run(value) {
      var terms = fold(value).split(/\s+/).filter(Boolean);
      if (!terms.length || value.trim().length < 2) {
        results.innerHTML = '<p class="note">Mindestens zwei Zeichen eingeben.</p>';
        return;
      }
      if (index === null) { return; }
      var withSource = !!(srcBox && srcBox.checked) && srcState === "bereit";
      var hits = [];
      index.forEach(function (row) {
        var meta = terms.every(function (t) { return row.hay.indexOf(t) !== -1; });
        var sql = !meta && withSource && row.sqlhay &&
          terms.every(function (t) {
            return row.hay.indexOf(t) !== -1 || row.sqlhay.indexOf(t) !== -1;
          });
        if (meta || sql) {
          row.onlySql = !meta;
          hits.push(row);
        }
      });
      // Namenstreffer zuerst, kuerzere Namen vor laengeren; reine
      // Quelltexttreffer ans Ende.
      var first = terms[0];
      hits.sort(function (a, b) {
        var an = fold(a.name).indexOf(first), bn = fold(b.name).indexOf(first);
        var ar = an === 0 ? 0 : (an > 0 ? 1 : 2);
        var br = bn === 0 ? 0 : (bn > 0 ? 1 : 2);
        return (a.onlySql ? 1 : 0) - (b.onlySql ? 1 : 0) || ar - br ||
               a.name.length - b.name.length || a.name.localeCompare(b.name, "de");
      });

      var shown = hits.slice(0, 300);
      var note = hits.length + " Treffer" +
        (hits.length > shown.length ? ", die ersten " + shown.length + " werden gezeigt" : "");
      if (srcBox && srcBox.checked && srcState === "fehlt") {
        note += " – der Quelltextindex (assets/quelltext.js) fehlt";
      }
      var html = '<p class="note">' + note + "</p><ul>";
      shown.forEach(function (row) {
        var url = row.onlySql ? row.url + "#quelltext" : row.url;
        html += '<li><span class="dbtag">' + escapeHtml(row.db) + "</span>" +
          '<a href="' + url + '">' + mark(row.name, terms) + "</a>" +
          '<span class="kind">' + escapeHtml(row.kind) + "</span>" +
          (row.desc ? '<span class="desc">' + mark(row.desc, terms) + "</span>" : "") +
          (row.onlySql
            ? '<span class="hit"><code>' + mark(snippet(row, terms), terms) + "</code></span>"
            : "") +
          "</li>";
      });
      results.innerHTML = html + "</ul>";
    }

    var timer = null;
    box.addEventListener("input", function () {
      window.clearTimeout(timer);
      var value = box.value;
      timer = window.setTimeout(function () { run(value); }, 90);
    });

    if (srcBox) {
      srcBox.addEventListener("change", function () {
        if (srcBox.checked) {
          loadSource(function () { run(box.value); });
        } else {
          run(box.value);
        }
      });
    }
  }
})();
