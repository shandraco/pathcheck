"""Data layer: Zetaris (the real one) and a SQLite stand-in for SAMPLE_MODE.

Both expose `query(sql, columns)` over the same three tables, addressed as
<db>.courses, <db>.sections, <db>.programs and <db>.policies, so the agents' SQL is identical.
Every query is returned with its SQL and the engine that ran it, for provenance.
"""
import json
import sqlite3
import time
import urllib.error
import urllib.request
import uuid

from . import config

TABLES = {
    "courses": ["code", "title", "credits", "level", "prerequisites", "corequisites", "description", "url"],
    "sections": ["term", "code", "section", "days", "times", "modality", "credits", "crn"],
    "programs": ["program_id", "name", "level", "degree", "college", "requirements", "url"],
    "policies": ["policy_id", "title", "url", "text"],
}
KEYS = {"courses": "code", "sections": "crn", "programs": "program_id", "policies": "policy_id"}


class DataError(Exception):
    pass


class ZetarisData:
    engine = "zetaris"

    def __init__(self):
        if not config.ZETARIS_API_KEY:
            raise DataError("ZETARIS_API_KEY is not set")
        self.base = config.ZETARIS_REST_URL.rstrip("/")
        self.db = config.ZETARIS_DB

    def _call(self, path, body=None, timeout=120):
        req = urllib.request.Request(
            self.base + path, method="POST" if body else "GET",
            data=json.dumps(body).encode() if body else None,
            headers={"Authorization": f"Bearer {config.ZETARIS_API_KEY}", "X-Org-ID": config.ZETARIS_ORG_ID,
                     "X-Request-ID": str(uuid.uuid4()), "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode() or "null")
        except urllib.error.HTTPError as e:
            raise DataError(f"Zetaris HTTP {e.code}: {e.read().decode(errors='replace')[:200]}") from e
        except (urllib.error.URLError, OSError) as e:
            raise DataError(f"Zetaris unreachable at {self.base}: {e}") from e

    def ping(self) -> bool:
        try:
            return bool(self.query("SELECT 1 AS ok", ["ok"])["rows"])
        except DataError:
            return False

    def query(self, sql, columns, limit=200):
        t = time.time()
        out = self._call("/sql-editor/sqls/run",
                         {"queryId": str(uuid.uuid4()), "sql": sql, "source": "SqlEditor", "limit": limit})
        raw = out.get("data") if isinstance(out, dict) else out
        rows = []
        for r in raw or []:
            if isinstance(r, dict):
                rows.append({c: r.get(c) for c in columns} if columns else r)
            else:
                rows.append(dict(zip(columns, r)))
        # Some responses echo a header row; drop it.
        if rows and all(str(rows[0].get(c)) == c for c in columns):
            rows = rows[1:]
        return {"rows": rows, "sql": sql, "engine": self.engine, "ms": int((time.time() - t) * 1000)}


class SampleData:
    """SQLite with an attached database named like the Zetaris one, loaded from data/*.json."""
    engine = "sample-sqlite"

    def __init__(self):
        self.db = config.ZETARIS_DB
        self.conn = sqlite3.connect(":memory:", check_same_thread=False)
        self.conn.execute(f"ATTACH DATABASE ':memory:' AS {self.db}")
        for table, cols in TABLES.items():
            self.conn.execute(f"CREATE TABLE {self.db}.{table} ({', '.join(cols)})")
            data = json.loads((config.ROOT / "data" / f"{table}.json").read_text())
            self.conn.executemany(f"INSERT INTO {self.db}.{table} VALUES ({', '.join('?' * len(cols))})",
                                  [[d.get(c) for c in cols] for d in data])

    def ping(self) -> bool:
        return True

    def query(self, sql, columns, limit=200):
        t = time.time()
        try:
            cur = self.conn.execute(sql)
        except sqlite3.Error as e:
            raise DataError(f"SQL error: {e}") from e
        names = [d[0] for d in cur.description]
        rows = [dict(zip(names, r)) for r in cur.fetchmany(limit)]
        return {"rows": rows, "sql": sql, "engine": self.engine, "ms": int((time.time() - t) * 1000)}


def open_data():
    if config.SAMPLE_MODE:
        return SampleData()
    return ZetarisData()
