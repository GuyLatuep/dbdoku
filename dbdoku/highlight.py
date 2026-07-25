"""Sehr einfache T-SQL-Einfaerbung fuer die Quelltextanzeige."""

from __future__ import annotations

import html
import re

KEYWORDS = {
    "add", "all", "alter", "and", "any", "as", "asc", "begin", "between", "break",
    "by", "case", "cast", "catch", "check", "close", "coalesce", "collate",
    "column", "commit", "constraint", "continue", "convert", "create", "cross",
    "cursor", "database", "deallocate", "declare", "default", "delete", "desc",
    "distinct", "drop", "else", "end", "except", "exec", "execute", "exists",
    "fetch", "for", "foreign", "from", "full", "function", "go", "goto", "grant",
    "group", "having", "identity", "if", "in", "index", "inner", "insert",
    "intersect", "into", "is", "join", "key", "left", "like", "merge", "next",
    "no", "not", "null", "nvarchar", "of", "off", "on", "open", "option", "or",
    "order", "outer", "output", "over", "partition", "primary", "print",
    "procedure", "raiserror", "read", "references", "return", "returns",
    "revert", "right", "rollback", "rowcount", "schema", "select", "set",
    "table", "then", "throw", "top", "tran", "transaction", "trigger", "truncate",
    "try", "union", "unique", "update", "use", "using", "values", "view", "when",
    "where", "while", "with",
}

_TOKEN = re.compile(
    r"(--[^\n]*"
    r"|/\*.*?\*/"
    r"|N?'(?:[^']|'')*'"
    r"|\[[^\]]*\]"
    r"|@@?\w+"
    r"|#{1,2}\w+"
    r"|\b\d+(?:\.\d+)?\b"
    r"|\w+)",
    re.DOTALL,
)


def highlight(sql: str) -> str:
    """T-SQL nach HTML — escaped und mit ``<span>``-Klassen versehen."""
    out: list[str] = []
    pos = 0
    for match in _TOKEN.finditer(sql):
        if match.start() > pos:
            out.append(html.escape(sql[pos:match.start()]))
        token = match.group(0)
        escaped = html.escape(token)
        head = token[:2]
        if head == "--" or head == "/*":
            out.append(f'<span class="c">{escaped}</span>')
        elif token[0] == "'" or head.lower() == "n'":
            out.append(f'<span class="s">{escaped}</span>')
        elif token[0] == "@":
            out.append(f'<span class="v">{escaped}</span>')
        elif token[0] == "#":
            out.append(f'<span class="t">{escaped}</span>')
        elif token[0] == "[":
            out.append(f'<span class="id">{escaped}</span>')
        elif token[0].isdigit():
            out.append(f'<span class="n">{escaped}</span>')
        elif token.lower() in KEYWORDS:
            out.append(f'<span class="k">{escaped}</span>')
        else:
            out.append(escaped)
        pos = match.end()
    out.append(html.escape(sql[pos:]))
    return "".join(out)
