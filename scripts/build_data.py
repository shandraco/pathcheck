"""Export four separate sources from the WSU catalog snapshot (crawled before the hackathon).

Each becomes a JSON file in data/ that Zetaris registers as its own REST table, so the
agent joins courses, the class schedule, degree programs and policy pages through one
SQL layer. Run: python3 scripts/build_data.py <path-to-shocktalk.db>
"""
import json
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TERMS = {"202710": "Fall 2026", "202720": "Spring 2027"}
POLICY_URL = re.compile(r"international|registrar|policies|academic-affairs|financial-aid|graduate-school/"
                        r"|catalog\.wichita\.edu/(undergraduate|graduate)/(academic|policies|admission)", re.I)


def chunks(text, size=900):
    paras, cur = re.split(r"\n{2,}", text), ""
    for p in paras:
        if len(cur) + len(p) > size and cur:
            yield cur.strip()
            cur = ""
        cur += p + "\n\n"
    if cur.strip():
        yield cur.strip()


def main(db):
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    courses = [{"code": r["code"], "title": r["title"], "credits": r["credits"], "level": r["level"],
                "prerequisites": r["prerequisites"] or "", "corequisites": r["corequisites"] or "",
                "description": (r["description"] or "")[:400], "url": r["url"]}
               for r in con.execute("SELECT * FROM courses")]
    sections = [{"term": TERMS.get(str(r["term"]), str(r["term"])), "code": r["code"], "section": r["section"],
                 "days": r["days"] or "", "times": r["times"] or "", "modality": r["modality"] or "",
                 "credits": r["credits"], "crn": r["crn"]}
                for r in con.execute("SELECT * FROM sections")]
    programs = [{"program_id": f"p{i}", "name": r["name"], "level": r["level"], "degree": r["degree"] or "",
                 "college": r["college"] or "", "requirements": (r["requirements"] or "")[:12000], "url": r["url"]}
                for i, r in enumerate(con.execute("SELECT * FROM programs"))]
    policies = []
    for r in con.execute("SELECT id, url, title, text FROM documents"):
        if not POLICY_URL.search(r["url"] or "") or not r["text"]:
            continue
        for j, c in enumerate(chunks(r["text"])):
            policies.append({"policy_id": f"d{r['id']}_{j}", "title": r["title"] or "", "url": r["url"],
                             "text": c})
    for name, data in (("courses", courses), ("sections", sections), ("programs", programs),
                       ("policies", policies)):
        (ROOT / "data" / f"{name}.json").write_text(json.dumps(data, ensure_ascii=False))
        print(f"data/{name}.json: {len(data)} rows")


if __name__ == "__main__":
    main(sys.argv[1])
