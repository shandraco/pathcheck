"""Register the four sources in Zetaris and check they answer. Run: python3 scripts/zetaris_setup.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pathcheck.data import TABLES, DataError, ZetarisData  # noqa: E402

z = ZetarisData()
print("SELECT 1:", "ok" if z.ping() else "FAILED (check ZETARIS_API_KEY and that Zetaris is running)")
for stmt in Path(__file__).resolve().parent.parent.joinpath("zetaris/register.sql").read_text().splitlines():
    if not stmt.strip() or stmt.startswith("--"):
        continue
    try:
        z._call("/sql-editor/sqls/run", {"queryId": __import__("uuid").uuid4().hex, "sql": stmt,
                                         "source": "SqlEditor", "limit": 10})
        print("ok  ", stmt[:70])
    except DataError as e:
        print("skip", stmt[:70], "->", str(e)[:120], "(fine if it already exists)")
for t, cols in TABLES.items():
    try:
        r = z.query(f"SELECT {', '.join(cols[:2])} FROM {z.db}.{t} LIMIT 3", cols[:2])
        print(f"{z.db}.{t}: {len(r['rows'])} sample rows, e.g. {r['rows'][:1]}")
    except DataError as e:
        print(f"{z.db}.{t}: FAILED {e}")
