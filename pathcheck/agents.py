"""The PathCheck agent team: Planner, Researcher, Prerequisite engine, Analyst, Checker.

Not a fixed pipeline:
- Planner turns a student's question into targets, transcript and policy topics.
- Researcher queries Zetaris; when a course is blocked it goes back for the missing
  prerequisites (and theirs) to build a path; when no policy text is found it asks the
  Planner for broader search terms.
- Analyst drafts the answer. Every claim must cite World Model evidence.
- Checker rejects claims that cite nothing, cite evidence that does not exist, or
  contradict the deterministic prerequisite engine, and sends them back to the Analyst.
  A judge model also checks policy claims against the cited policy text.
Anything a transcript cannot settle (consent, standing) is escalated to a human advisor.
"""
import json
import re
import time
import uuid

from . import config
from .data import TABLES, DataError, open_data
from .llm import LLMError, MeterlessClient, parse_json
from .prereq import CODE, evaluate, norm
from .world_model import WorldModel, stable_id

DB = config.ZETARIS_DB
TERMS = ["Fall 2026", "Spring 2027"]

PLANNER_SYS = f"""You are the Planner in a university advising agent team at Wichita State University.
Read the student's message and extract what must be checked. Course codes look like "CS 400".
Reply with JSON only:
{{"target_courses": ["CS 400"], "completed": ["CS 311"], "in_progress": [], "term": "one of {TERMS} or empty",
"program": "degree name words to search, or empty", "policy_topics": ["2-4 short search words each, e.g.
'online course' 'F-1', 'full-time enrollment', 'course repeat'"], "student_type": "international|domestic|unknown",
"intent": "one sentence"}}"""

ANALYST_SYS = """You are the Analyst in a university advising agent team. You get grounded evidence
from the catalog, the class schedule, programs and policy pages, plus the prerequisite engine's exact
verdict for each course. Write the answer a careful advisor would give.
Rules: the status of each course MUST equal the engine's verdict. Every claim cites evidence_ids from
the evidence given. Never invent a rule, date or number. If the evidence does not settle something,
put it in ask_advisor instead of guessing. Plain words; the student is not an expert.
Reply with JSON only:
{"summary": "2-3 sentences", "courses": [{"code": "CS 400", "status": "eligible|blocked|needs_advisor",
"why": [{"claim": "...", "evidence_ids": ["course:..."]}], "next_step": "..."}],
"policy_notes": [{"claim": "...", "evidence_ids": ["policy:..."]}], "ask_advisor": ["..."]}"""

JUDGE_SYS = """You are the Checker. For each claim decide if the cited text actually supports it.
Be strict: reject claims that add facts, numbers or conditions not in the text.
Reply with JSON only: {"verdicts": [{"i": 0, "supported": true, "reason": "short"}]}"""


class Team:
    def __init__(self, emit=None, sample_mode=None):
        self.run_id = time.strftime("run-%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:4]
        self.emit_cb = emit or (lambda e: None)
        config.LOG_DIR.mkdir(exist_ok=True)
        self.wm = WorldModel(self.run_id)
        self.llm = MeterlessClient(sample_mode=sample_mode)
        self.data = open_data()
        self.trace_path = config.LOG_DIR / f"{self.run_id}.trace.jsonl"
        self.models_used: dict[str, str] = {}

    # ---- plumbing ------------------------------------------------------------
    def emit(self, agent, action, detail=None, **extra):
        ev = {"run": self.run_id, "agent": agent, "action": action, "detail": detail, **extra,
              "t": round(time.time(), 3)}
        with self.trace_path.open("a") as f:
            f.write(json.dumps(ev, default=str) + "\n")
        self.wm.event(agent, action, detail if isinstance(detail, str) else action)
        self.emit_cb(ev)

    def ask(self, agent, lane, system, user, fallback):
        """Model call through Meterless Nightshift; a rule-based fallback only if no model answers."""
        msgs = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        try:
            r = self.llm.chat(msgs, lane)
            out = parse_json(r["text"])
            self.models_used[agent] = r["model"]
            self.emit(agent, "model_reply", f"{r['model']} via {r['source']}", model=r["model"], lane=lane,
                      source=r["source"])
            return out
        except LLMError as e:
            self.models_used[agent] = "rule-based fallback"
            self.emit(agent, "model_fallback", str(e)[:160], model="rule-based fallback", lane=lane)
            return fallback()

    def sql(self, agent, purpose, sql, table):
        res = self.data.query(sql, TABLES[table])
        self.emit(agent, "sql", purpose, sql=sql, engine=res["engine"], rows=len(res["rows"]), ms=res["ms"])
        self.wm.ingest_rows(table, res, agent)
        return res["rows"]

    # ---- agents --------------------------------------------------------------
    def plan(self, question, feedback=""):
        user = question + (f"\n\nFeedback from the Checker: {feedback}" if feedback else "")
        p = self.ask("planner", config.LANE_FAST, PLANNER_SYS, user, lambda: heuristic_plan(question, feedback))
        p["target_courses"] = [norm(c) for c in p.get("target_courses", []) if CODE.search(c.upper())]
        p["completed"] = [norm(c) for c in p.get("completed", []) if CODE.search(c.upper())]
        p["in_progress"] = [norm(c) for c in p.get("in_progress", []) if CODE.search(c.upper())]
        self.emit("planner", "plan", p.get("intent", ""), plan=p)
        return p

    def fetch_courses(self, codes, purpose):
        codes = sorted({c for c in codes if c and stable_id("course", c) not in self.wm.entities})
        if not codes:
            return
        in_list = ", ".join(f"'{c}'" for c in codes)
        self.sql("researcher", purpose, f"SELECT {', '.join(TABLES['courses'])} FROM {DB}.courses "
                 f"WHERE code IN ({in_list})", "courses")
        self.sql("researcher", "check the class schedule", f"SELECT {', '.join(TABLES['sections'])} "
                 f"FROM {DB}.sections WHERE code IN ({in_list})", "sections")

    def search_policies(self, topics):
        found = 0
        for t in topics[:4]:
            words = [w.replace("'", "") for w in re.findall(r"[\w-]+", t.lower()) if len(w) > 2][:3]
            if not words:
                continue
            where = " AND ".join(f"LOWER(text) LIKE '%{w}%'" for w in words)
            # Rank chunks where the words sit together, and pages titled with them, first.
            pair = " ".join(words[-2:])
            order = (f"CASE WHEN LOWER(text) LIKE '%{pair}%' THEN 0 ELSE 1 END, "
                     f"CASE WHEN LOWER(title) LIKE '%{words[0]}%' THEN 0 ELSE 1 END, LENGTH(text)")
            rows = self.sql("researcher", f"search policy pages: {t}", f"SELECT {', '.join(TABLES['policies'])} "
                            f"FROM {DB}.policies WHERE {where} ORDER BY {order} LIMIT 4", "policies")
            for r in rows:
                yrs = [int(y) for y in re.findall(r"20(1\d|2[0-4])", (r.get("title") or "") + (r.get("url") or ""))]
                if yrs:
                    self.wm.set_state(stable_id("policy", r["policy_id"]), "archived",
                                      f"dated page (20{max(yrs)}); not used as evidence", "checker")
                    self.emit("checker", "reject_stale", f"ignored outdated page: {r.get('title')}")
                else:
                    found += 1
        return found

    def find_program(self, words):
        ws = [w for w in re.findall(r"[a-z]+", (words or "").lower()) if len(w) > 2][:3]
        if not ws:
            return
        where = " AND ".join(f"LOWER(name) LIKE '%{w}%'" for w in ws)
        self.sql("researcher", f"find degree program: {words}", f"SELECT {', '.join(TABLES['programs'])} "
                 f"FROM {DB}.programs WHERE {where} LIMIT 3", "programs")

    def evaluate_all(self, plan):
        done, now = set(plan["completed"]), set(plan["in_progress"])
        verdicts = {}
        for code in plan["target_courses"]:
            ctx = self.wm.course_context(code)
            if not ctx:
                verdicts[code] = {"course": code, "status": "not_found", "missing": [], "conditions": []}
                continue
            v = evaluate(code, ctx.get("prerequisites", ""), done, now)
            if plan.get("term"):
                v["offered_in_term"] = [s for s in ctx["sections"] if s["term"] == plan["term"]]
            verdicts[code] = v
            fid = self.wm.upsert("finding", f"{self.run_id}|{code}", {"data": v}, {"engine": "prereq-rules",
                                 "rule_text": v["rule_text"]}, "prereq_engine")
            self.wm.link(stable_id("course", code), "evaluated_as", fid, "prereq_engine")
            self.emit("prereq_engine", "verdict", f"{code}: {v['status']}", verdict=v)
        return verdicts

    def build_path(self, verdicts, depth=2):
        """Branch: for blocked courses fetch the missing prerequisites (and theirs) to show a path."""
        frontier = [c for v in verdicts.values() for g in v.get("missing", []) for c in g["any_of"]]
        for level in range(depth):
            if not frontier:
                break
            self.fetch_courses(frontier, f"fetch missing prerequisites (level {level + 1})")
            nxt = []
            for c in frontier:
                ctx = self.wm.course_context(c)
                if ctx:
                    from .prereq import parse
                    nxt += [x for g in parse(ctx.get("prerequisites", ""))["groups"] for x in g]
            frontier = nxt

    def analyse(self, question, plan, verdicts, feedback=""):
        evidence = {
            "courses": [self.wm.course_context(c) for c in sorted({*plan["target_courses"],
                        *[x for v in verdicts.values() for g in v.get("missing", []) for x in g["any_of"]]})],
            "engine_verdicts": verdicts,
            "policies": [{"evidence_id": e["id"], "title": e["data"]["title"], "url": e["url"],
                          "text": e["data"]["text"][:700]} for e in self.wm.entities.values()
                         if e["kind"] == "policy" and e["state"] == "active"],
            "programs": [{"evidence_id": e["id"], "name": e["data"]["name"], "url": e["url"]}
                         for e in self.wm.entities.values() if e["kind"] == "program"],
        }
        evidence["courses"] = [c for c in evidence["courses"] if c]
        user = json.dumps({"question": question, "student": {k: plan.get(k) for k in
                          ("completed", "in_progress", "term", "student_type")}, "evidence": evidence}, default=str)
        if feedback:
            user += f"\n\nThe Checker rejected these claims; fix or drop them:\n{feedback}"
        out = self.ask("analyst", config.LANE_DEEP, ANALYST_SYS, user,
                       lambda: heuristic_answer(plan, verdicts, self.wm))
        self.emit("analyst", "draft", out.get("summary", "")[:200] if isinstance(out, dict) else "")
        return out if isinstance(out, dict) else {}

    def check(self, answer, verdicts):
        rejected, judge = [], []
        # models sometimes return a claim as bare text; keep it as an uncited claim so it is rejected, not crashed on
        as_claim = lambda w: w if isinstance(w, dict) else {"claim": str(w), "evidence_ids": []}
        answer["courses"] = [c for c in answer.get("courses", []) if isinstance(c, dict)]
        for c in answer["courses"]:
            c["why"] = [as_claim(w) for w in c.get("why", [])]
        answer["policy_notes"] = [as_claim(w) for w in answer.get("policy_notes", [])]
        for c in answer.get("courses", []):
            code = norm(c.get("code", ""))
            engine = verdicts.get(code, {}).get("status")
            if engine and c.get("status") != engine:
                rejected.append({"where": code, "claim": f"status {c.get('status')}",
                                 "reason": f"prerequisite engine says {engine}"})
                c["status"] = engine  # the rules win; the analyst is told why
            for w in c.get("why", []):
                self._check_claim(w, rejected, judge, code)
        for w in answer.get("policy_notes", []):
            self._check_claim(w, rejected, judge, "policy")
        if judge:
            items = [{"i": i, "claim": w["claim"], "text": [self.wm.entities[e]["data"].get("text") or
                                                            self.wm.entities[e]["data"].get("prerequisites") or
                                                            json.dumps(self.wm.entities[e]["data"])[:500]
                                                            for e in w["evidence_ids"]]}
                     for i, w in enumerate(judge)]
            out = self.ask("checker", config.LANE_JUDGE, JUDGE_SYS, json.dumps(items, default=str),
                           lambda: {"verdicts": [{"i": i, "supported": True, "reason": "evidence exists"}
                                                 for i in range(len(items))]})
            vs = {v.get("i"): v for v in (out.get("verdicts", []) if isinstance(out, dict) else [])}
            for i, w in enumerate(judge):
                v = vs.get(i, {"supported": True, "reason": "no verdict"})
                w["status"] = "supported" if v.get("supported") else "rejected"
                w["check"] = v.get("reason", "")
                if not v.get("supported"):
                    rejected.append({"where": "claim", "claim": w["claim"], "reason": "judge: " + w["check"]})
        self.emit("checker", "verdict", f"{len(rejected)} problems found", rejected=rejected)
        return rejected

    def _resolve_id(self, eid):
        """Models cite the engine's verdict (e.g. "engine_verdicts.CS 400"); that verdict comes from the course's catalog entry."""
        eid = str(eid)
        if eid in self.wm.entities or eid.split(":")[0] in ("course", "section", "policy", "program"):
            return eid
        m = CODE.search(eid)
        cid = stable_id("course", f"{m.group(1)} {m.group(2)}") if m else None
        return cid if cid in self.wm.entities else eid

    def _check_claim(self, w, rejected, judge, where):
        ids = w["evidence_ids"] = [self._resolve_id(e) for e in w.get("evidence_ids") or []]
        reason = None
        if not ids:
            reason = "cites no evidence"
        elif any(e not in self.wm.entities for e in ids):
            reason = "cites evidence that does not exist"
        elif any(self.wm.entities[e]["state"] != "active" for e in ids):
            reason = "cites an outdated page"
        else:
            for code in {f"{a} {b}" for a, b in CODE.findall(w.get("claim", ""))}:
                if stable_id("course", code) not in self.wm.entities:
                    reason = f"mentions {code}, which was never looked up"
        if reason:
            w["status"], w["check"] = "rejected", reason
            rejected.append({"where": where, "claim": w.get("claim"), "reason": reason})
        else:
            judge.append(w)

    # ---- orchestration -------------------------------------------------------------
    def run(self, question):
        t0 = time.time()
        st = self.llm.status()
        self.emit("system", "start", question, engine=self.data.engine, llm=st["state"])
        plan = self.plan(question)
        if not plan["target_courses"] and not plan.get("policy_topics"):
            plan = self.plan(question, "Nothing to check was found. List the course codes and policy topics.")
        try:
            self.fetch_courses(plan["target_courses"] + plan["completed"], "look up the courses asked about")
            if plan.get("program"):
                self.find_program(plan["program"])
            topics = list(plan.get("policy_topics") or [])
            if plan.get("student_type") == "international" and not any("f-1" in t.lower() for t in topics):
                topics.append("F-1 online course")
            if topics and not self.search_policies(topics):
                self.emit("checker", "too_thin", "no policy text found; asking the planner for broader terms")
                broader = self.plan(question, f"No policy pages matched {topics}. Give 2-3 broader one-word topics.")
                self.search_policies(broader.get("policy_topics") or [])
        except DataError as e:
            self.emit("system", "error", str(e))
            raise
        verdicts = self.evaluate_all(plan)
        if any(v["status"] == "blocked" for v in verdicts.values()):
            self.build_path(verdicts)
        feedback, answer = "", {}
        for rnd in range(1, config.MAX_ROUNDS + 1):
            self.emit("system", "round", f"analysis round {rnd}")
            answer = self.analyse(question, plan, verdicts, feedback)
            rejected = self.check(answer, verdicts)
            if not rejected:
                break
            if rnd < config.MAX_ROUNDS:
                feedback = json.dumps(rejected)[:3000]
                self.emit("checker", "send_back", f"{len(rejected)} claims sent back to the analyst")
        # Whatever is still rejected after the last round is removed, not shown.
        for c in answer.get("courses", []):
            c["why"] = [w for w in c.get("why", []) if w.get("status") != "rejected"]
        answer["policy_notes"] = [w for w in answer.get("policy_notes", []) if w.get("status") != "rejected"]
        result = {"run_id": self.run_id, "question": question, "plan": plan, "verdicts": verdicts,
                  "answer": answer, "evidence": self.evidence_index(answer), "models": self.models_used,
                  "data_engine": self.data.engine, "llm": st["state"], "world": self.wm.stats(),
                  "seconds": round(time.time() - t0, 1)}
        (config.LOG_DIR / f"{self.run_id}.result.json").write_text(json.dumps(result, indent=1, default=str))
        self.emit("system", "done", f"answered in {result['seconds']} s", result=result)
        return result

    def evidence_index(self, answer):
        ids = {e for c in answer.get("courses", []) for w in c.get("why", []) for e in w.get("evidence_ids", [])}
        ids |= {e for w in answer.get("policy_notes", []) for e in w.get("evidence_ids", [])}
        out = {}
        for i in ids:
            e = self.wm.entities.get(i)
            if e:
                d = e["data"]
                out[i] = {"kind": e["kind"], "label": d.get("code") or d.get("title") or d.get("name") or i,
                          "url": e.get("url") or d.get("url"), "sql": e["provenance"][0].get("sql"),
                          "engine": e["provenance"][0].get("engine"),
                          "excerpt": (d.get("text") or d.get("prerequisites") or
                                      f"{d.get('term', '')} {d.get('section', '')} {d.get('days', '')} "
                                      f"{d.get('times', '')} {d.get('modality', '')}")[:400]}
        return out


# ---- rule-based fallbacks (used only when no model is reachable) ----------------------
def heuristic_plan(question, feedback=""):
    codes = [f"{a} {b}" for a, b in CODE.findall(question.upper())]
    q = question.lower()
    split = re.split(r"\b(?:take|taking|enrol|enroll|register for|sign up for)\b", q, maxsplit=1)
    after = {f"{a} {b}" for a, b in CODE.findall(split[1].upper())} if len(split) > 1 else set(codes[-1:])
    targets = [c for c in codes if c in after]
    done = [c for c in codes if c not in after]
    term = next((t for t in TERMS if t.split()[0].lower() in q), "")
    topics = []
    if "online" in q and not re.search(r"\bf-?1\b|international", q):
        topics.append("online courses")
    if re.search(r"\bf-?1\b|international|visa", q):
        topics += ["F-1 online course", "F-1 full course load"]
    if "repeat" in q or "retake" in q:
        topics.append("repeat course")
    if "withdraw" in q or "drop" in q:
        topics.append("withdraw course")
    return {"target_courses": targets, "completed": done, "in_progress": [], "term": term, "program": "",
            "policy_topics": topics if "broader" not in feedback else [t.split()[0] for t in topics],
            "student_type": "international" if re.search(r"\bf-?1\b|international", q) else "unknown",
            "intent": "check eligibility and rules for the courses asked about"}


def heuristic_answer(plan, verdicts, wm):
    courses = []
    for code, v in verdicts.items():
        ctx = wm.course_context(code)
        if not ctx:
            continue
        why = []
        if v["missing"]:
            miss = "; ".join(" or ".join(g["any_of"]) for g in v["missing"])
            why.append({"claim": f"The catalog lists the prerequisite as \"{v['rule_text']}\". Still missing: {miss}.",
                        "evidence_ids": [ctx["evidence_id"]]})
        elif v["rule_text"]:
            why.append({"claim": f"The catalog prerequisite \"{v['rule_text']}\" is met by your completed courses.",
                        "evidence_ids": [ctx["evidence_id"]]})
        for cond in v.get("conditions", []):
            why.append({"claim": f"The catalog also requires: {cond}. A transcript cannot confirm this.",
                        "evidence_ids": [ctx["evidence_id"]]})
        secs = v.get("offered_in_term")
        if secs is not None:
            why.append({"claim": f"{len(secs)} section(s) are listed for {plan['term']}" +
                        (f", for example {secs[0]['days']} {secs[0]['times']} ({secs[0]['modality']})." if secs else "."),
                        "evidence_ids": [s["evidence_id"] for s in secs[:2]] or [ctx["evidence_id"]]})
        step = {"eligible": "You can register.", "blocked": "Take the missing course(s) first.",
                "needs_advisor": "Ask your advisor or the department to confirm before registering."}[v["status"]]
        courses.append({"code": code, "status": v["status"], "why": why, "next_step": step})
    pol = [e for e in wm.entities.values() if e["kind"] == "policy" and e["state"] == "active"][:3]
    notes = [{"claim": f"Relevant policy page: {p['data']['title']}", "evidence_ids": [p["id"]]} for p in pol]
    ask = [c for v in verdicts.values() for c in v.get("conditions", [])]
    return {"summary": "; ".join(f"{c['code']}: {c['status'].replace('_', ' ')}" for c in courses),
            "courses": courses, "policy_notes": notes, "ask_advisor": ask}
