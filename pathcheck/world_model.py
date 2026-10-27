"""Meterless World Model engine (headless), as used by the Why Now agents.

Implements the parts of the Meterless World Model Agent Engine this product relies on:
- Hybrid aggregate: entity graph (companies, signals, sources, claims) plus a run timeline.
- Entity records with identity, semantics, provenance, lifecycle and agent attribution.
- Stable content-hash IDs, so agents writing the same fact converge on one record.
- Append-only JSONL log; canonical state is reconstructed from the log (replayable).
- First-class relationship records with provenance.
- A context builder that agents call instead of joining tables themselves.
- Idempotent ingest: writing the same observation twice changes nothing.
"""
import hashlib
import json
import time

from . import config

SCHEMA_VERSION = 1


def stable_id(kind: str, key: str) -> str:
    return f"{kind}:" + hashlib.sha1(f"{kind}|{key.strip().lower()}".encode()).hexdigest()[:12]


class WorldModel:
    def __init__(self, run_id: str, log_path=None):
        self.run_id = run_id
        self.log_path = log_path or (config.LOG_DIR / f"{run_id}.world.jsonl")
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self.entities: dict[str, dict] = {}
        self.edges: dict[str, dict] = {}
        self.timeline: list[dict] = []
        self._seen: set[str] = set()

    # ---- append log -------------------------------------------------------
    def _append(self, op: dict) -> bool:
        digest = hashlib.sha1(json.dumps({k: op[k] for k in op if k not in ("at",)}, sort_keys=True,
                                         default=str).encode()).hexdigest()
        if digest in self._seen:
            return False  # idempotent: same write twice is a no-op
        self._seen.add(digest)
        op = {"v": SCHEMA_VERSION, "run": self.run_id, "at": time.time(), **op}
        with self.log_path.open("a") as f:
            f.write(json.dumps(op, default=str) + "\n")
        self._apply(op)
        return True

    def _apply(self, op: dict) -> None:
        if op["op"] == "upsert_entity":
            cur = self.entities.get(op["id"])
            rec = dict(op["record"])
            if cur:
                rec = {**cur, **{k: v for k, v in rec.items() if v not in (None, "")}}
                rec["provenance"] = cur["provenance"] + [p for p in op["record"]["provenance"]
                                                         if p not in cur["provenance"]]
            self.entities[op["id"]] = rec
        elif op["op"] == "link":
            self.edges[op["id"]] = op["record"]
        elif op["op"] == "set_state":
            if op["id"] in self.entities:
                self.entities[op["id"]]["state"] = op["state"]
                self.entities[op["id"]]["state_reason"] = op.get("reason", "")
        elif op["op"] == "event":
            self.timeline.append(op["record"])

    @classmethod
    def replay(cls, log_path) -> "WorldModel":
        """Canonical reconstruction: rebuild the whole world from its append log."""
        with open(log_path) as f:
            lines = [json.loads(line) for line in f if line.strip()]
        wm = cls(lines[0]["run"] if lines else "replay", log_path=log_path)
        for op in lines:
            wm._apply(op)
        return wm

    # ---- writes -----------------------------------------------------------
    def upsert(self, kind, key, attrs, provenance, agent, confidence=None, state="active") -> str:
        eid = stable_id(kind, key)
        record = {"id": eid, "kind": kind, "key": key, **attrs, "state": state, "confidence": confidence,
                  "provenance": [provenance], "agent": agent}
        self._append({"op": "upsert_entity", "id": eid, "record": record})
        return eid

    def link(self, src, rel, dst, agent, provenance=None, weight=1.0) -> str:
        rid = stable_id("rel", f"{src}|{rel}|{dst}")
        self._append({"op": "link", "id": rid, "record": {"id": rid, "from": src, "type": rel, "to": dst,
                                                          "weight": weight, "agent": agent,
                                                          "provenance": provenance}})
        return rid

    def set_state(self, eid, state, reason, agent) -> None:
        self._append({"op": "set_state", "id": eid, "state": state, "reason": reason, "agent": agent})

    def event(self, agent, action, detail) -> None:
        self._append({"op": "event", "record": {"agent": agent, "action": action, "detail": detail,
                                                "t": round(time.time(), 3)}})

    # ---- ingest from the data layer -----------------------------------------
    def ingest_rows(self, table: str, result: dict, agent: str) -> list[str]:
        """Turn Zetaris rows into grounded entities; provenance = engine + SQL + row key."""
        from .data import KEYS
        kind = {"courses": "course", "sections": "section", "programs": "program", "policies": "policy"}[table]
        ids = []
        for row in result["rows"]:
            key = row.get(KEYS[table])
            if not key:
                continue
            prov = {"engine": result["engine"], "sql": result["sql"], "table": table, "row": key}
            eid = self.upsert(kind, str(key), {"data": row, "url": row.get("url", "")}, prov, agent)
            ids.append(eid)
            if kind == "section" and row.get("code"):
                self.link(stable_id("course", row["code"]), "offered_as", eid, agent, provenance=key)
        return ids

    def course_context(self, code: str) -> dict:
        """Everything grounded about one course, for an agent prompt. No joins in agents."""
        co = self.entities.get(stable_id("course", code))
        if not co:
            return {}
        secs = [self.entities[e["to"]] for e in self.edges.values()
                if e["from"] == co["id"] and e["type"] == "offered_as" and e["to"] in self.entities]
        return {"evidence_id": co["id"], **{k: co["data"].get(k) for k in ("code", "title", "credits",
                                                                          "prerequisites", "corequisites", "url")},
                "sections": [{"evidence_id": s["id"], **{k: s["data"].get(k) for k in
                                                         ("term", "section", "days", "times", "modality")}}
                             for s in secs]}

    def evidence(self, eid: str) -> dict | None:
        return self.entities.get(eid)

    def stats(self) -> dict:
        kinds: dict[str, int] = {}
        for e in self.entities.values():
            kinds[e["kind"]] = kinds.get(e["kind"], 0) + 1
        return {"entities": kinds, "relationships": len(self.edges), "events": len(self.timeline),
                "log": str(self.log_path.name)}


