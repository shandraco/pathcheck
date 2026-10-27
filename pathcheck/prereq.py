"""Deterministic prerequisite evaluation from catalog text.

Catalog strings look like "MATH 322 , CS 400 ; STAT 460 or IME 254" or
"CS 580 and senior standing.; Pre- or corequisite(s): PHIL 354 or PHIL 385".
`,` `;` and `and` join required groups; `or` joins alternatives inside a group.
Anything that is not a course code (standing, consent, placement) cannot be checked
from a transcript, so it is returned as a condition for a human advisor.
"""
import re

CODE = re.compile(r"\b([A-Z]{2,5})\s?(\d{3}[A-Z]?)\b")


def norm(code: str) -> str:
    m = CODE.search(code.upper())
    return f"{m.group(1)} {m.group(2)}" if m else code.strip().upper()


def parse(text: str) -> dict:
    """{"groups": [[alt, ...], ...], "coreq_groups": [...], "conditions": [str, ...]}"""
    text = (text or "").replace(" ", " ").strip()
    out = {"groups": [], "coreq_groups": [], "conditions": [], "consent_groups": []}
    if not text:
        return out
    parts = re.split(r"pre- or corequisite\(s\):", text, maxsplit=1, flags=re.I)
    main, coreq = parts[0], (parts[1] if len(parts) > 1 else "")
    for part, key in ((main, "groups"), (coreq, "coreq_groups")):
        for clause in re.split(r"\s*[;,]\s*|\s+and\s+", part or ""):
            clause = clause.strip(" .")
            if not clause:
                continue
            codes = [f"{a} {b}" for a, b in CODE.findall(clause)]
            leftover = CODE.sub("", clause)
            leftover = re.sub(r"\b(or|with|a|an|grade|of|better|minimum|c-|c|b|d|\(|\))\b", " ", leftover, flags=re.I)
            leftover = re.sub(r"[\s.,()-]+", " ", leftover).strip()
            if codes:
                out[key].append(codes)
                if re.search(r"consent|permission|standing|admission|placement", leftover, re.I):
                    out["conditions"].append(clause)  # "CS 647 or instructor's consent"
                    if key == "groups":
                        out["consent_groups"].append(len(out["groups"]) - 1)
            elif clause:
                out["conditions"].append(clause)
    return out


def evaluate(course: str, prereq_text: str, completed: set[str], in_progress: set[str] = frozenset()) -> dict:
    """Return status eligible / blocked / needs_advisor with the exact reasons."""
    p = parse(prereq_text)
    done = {norm(c) for c in completed}
    now = {norm(c) for c in in_progress}
    missing, satisfied = [], []
    consent_only = []
    for i, g in enumerate(p["groups"]):
        hit = [c for c in g if c in done]
        if hit:
            satisfied.append({"any_of": g, "met_by": hit})
        elif i in p["consent_groups"]:
            consent_only.append({"any_of": g, "or": "instructor/department consent"})
        else:
            missing.append({"any_of": g, "met_by": []})
    co_missing = []
    for g in p["coreq_groups"]:
        if not any(c in done or c in now for c in g):
            co_missing.append({"any_of": g, "met_by": []})
    if missing:
        status = "blocked"
    elif p["conditions"] or co_missing or consent_only:
        status = "needs_advisor"
    else:
        status = "eligible"
    return {"course": norm(course), "status": status, "missing": missing, "satisfied": satisfied,
            "take_with": co_missing, "consent_route": consent_only, "conditions": p["conditions"], "rule_text": prereq_text}
