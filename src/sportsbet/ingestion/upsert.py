"""Pandas SQL writer for repeatable stat refreshes and provider corrections."""
from sqlalchemy.dialects.postgresql import insert

def upsert_rows(keys: list[str]):
    def write(table, conn, columns, data_iter):
        rows = [dict(zip(columns, row)) for row in data_iter]
        if not rows:
            return 0
        stmt = insert(table.table).values(rows)
        stmt = stmt.on_conflict_do_update(index_elements=keys,
            set_={name:stmt.excluded[name] for name in columns if name not in keys})
        return conn.execute(stmt).rowcount
    return write
