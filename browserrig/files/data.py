import sqlite3

from .content import ParsedContent, ReadContext, cell_text


def read_sqlite(context: ReadContext) -> ParsedContent:
    details = ParsedContent((), "sqlite")

    def blocks():
        connection = sqlite3.connect(
            context.path.resolve().as_uri() + "?mode=ro&immutable=1", uri=True
        )
        try:
            connection.execute("PRAGMA trusted_schema=OFF")
            names = tuple(
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_schema "
                    "WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
                )
            )
            details.sheets = names
            yield "# Database tables\n\n" + ", ".join(names) + "\n\n"
            if not names:
                return
            selected = context.request.sheet or names[0]
            if selected not in names:
                raise ValueError(
                    f"Unknown table {selected!r}; available: {', '.join(names)}"
                )
            details.sheet = selected
            quoted = '"' + selected.replace('"', '""') + '"'
            cursor = connection.execute(f"SELECT * FROM {quoted}")
            columns = [column[0] for column in cursor.description]
            yield "| " + " | ".join(cell_text(name) for name in columns) + " |\n"
            yield "| " + " | ".join("---" for _ in columns) + " |\n"
            for row in cursor:
                if any(isinstance(value, bytes) for value in row):
                    details.limitations.append(
                        "Binary BLOB values are shown by byte length, not decoded"
                    )
                yield (
                    "| "
                    + " | ".join(
                        "NULL"
                        if value is None
                        else f"[binary: {len(value)} bytes]"
                        if isinstance(value, bytes)
                        else cell_text(value)
                        for value in row
                    )
                    + " |\n"
                )
        finally:
            connection.close()

    details.blocks = blocks()
    return details
