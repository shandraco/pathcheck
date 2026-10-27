"""Tests for the Meterless World Model engine, the prerequisite rules and the Checker."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["SAMPLE_MODE"] = "true"

from pathcheck.prereq import evaluate  # noqa: E402
from pathcheck.world_model import WorldModel, stable_id  # noqa: E402
from pathcheck.llm import normalize_base_url  # noqa: E402


class WorldModelTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()) / "w.jsonl"
        self.wm = WorldModel("t1", log_path=self.tmp)
        self.res = {"engine": "test", "sql": "SELECT ...", "rows": [
            {"code": "CS 400", "title": "Data Structures", "prerequisites": "CS 311", "url": "u"}]}

    def test_stable_ids_converge(self):
        self.assertEqual(stable_id("course", "CS 400"), stable_id("course", " cs 400 "))

    def test_ingest_is_idempotent(self):
        self.wm.ingest_rows("courses", self.res, "researcher")
        n = len(self.tmp.read_text().splitlines())
        self.wm.ingest_rows("courses", self.res, "researcher")
        self.assertEqual(n, len(self.tmp.read_text().splitlines()))

    def test_provenance_and_attribution(self):
        eid = self.wm.ingest_rows("courses", self.res, "researcher")[0]
        e = self.wm.entities[eid]
        self.assertEqual(e["provenance"][0]["sql"], "SELECT ...")
        self.assertEqual(e["agent"], "researcher")

    def test_replay_reconstructs_state(self):
        self.wm.ingest_rows("courses", self.res, "researcher")
        self.wm.set_state(stable_id("course", "CS 400"), "archived", "test", "checker")
        again = WorldModel.replay(self.tmp)
        self.assertEqual(again.entities.keys(), self.wm.entities.keys())
        self.assertEqual(again.entities[stable_id("course", "CS 400")]["state"], "archived")


class PrereqTest(unittest.TestCase):
    def test_blocked_lists_missing(self):
        v = evaluate("CS 560", "MATH 322 , CS 400 ; STAT 460 or IME 254", {"MATH 322", "CS 400"})
        self.assertEqual(v["status"], "blocked")
        self.assertEqual(v["missing"][0]["any_of"], ["STAT 460", "IME 254"])

    def test_alternatives(self):
        self.assertEqual(evaluate("CS 560", "MATH 322 , CS 400 ; STAT 460 or IME 254",
                                  {"MATH 322", "CS 400", "IME 254"})["status"], "eligible")

    def test_consent_goes_to_advisor(self):
        self.assertEqual(evaluate("CS 647", "CS 540 or instructor's consent", set())["status"], "needs_advisor")

    def test_standing_and_coreq(self):
        v = evaluate("CS 598", "CS 580 and senior standing.; Pre- or corequisite(s): PHIL 354 or PHIL 385",
                     {"CS 580"}, {"PHIL 354"})
        self.assertEqual(v["status"], "needs_advisor")
        self.assertIn("senior standing", v["conditions"])


class ProviderTest(unittest.TestCase):
    def test_base_url_normalized(self):
        for raw in ("127.0.0.1:8088", "http://127.0.0.1:8088/v1", "http://127.0.0.1:8088/v1/chat/completions",
                    "http://127.0.0.1:8088/healthz"):
            self.assertEqual(normalize_base_url(raw), "http://127.0.0.1:8088/v1")


class CheckerTest(unittest.TestCase):
    def test_checker_overrides_wrong_status_and_rejects_uncited(self):
        from pathcheck.agents import Team
        t = Team(sample_mode=True)
        t.fetch_courses(["CS 560"], "test")
        plan = {"target_courses": ["CS 560"], "completed": ["MATH 322"], "in_progress": [], "term": ""}
        verdicts = t.evaluate_all(plan)
        bad = {"courses": [{"code": "CS 560", "status": "eligible",
                            "why": [{"claim": "You meet every prerequisite.", "evidence_ids": []},
                                    {"claim": "CS 999 is not needed.", "evidence_ids": [stable_id("course", "CS 560")]}]}],
               "policy_notes": []}
        rejected = t.check(bad, verdicts)
        self.assertEqual(bad["courses"][0]["status"], "blocked")
        reasons = " ".join(r["reason"] for r in rejected)
        self.assertIn("prerequisite engine says blocked", reasons)
        self.assertIn("cites no evidence", reasons)
        self.assertIn("never looked up", reasons)

    def test_checker_accepts_engine_verdict_citation(self):
        from pathcheck.agents import Team
        t = Team(sample_mode=True)
        t.fetch_courses(["CS 560"], "test")
        rejected = []
        ok = {"claim": "CS 560 still has a missing prerequisite.", "evidence_ids": ["engine_verdicts.CS 560"]}
        t._check_claim(ok, rejected, judge=[], where="course")
        self.assertEqual(ok["evidence_ids"], [stable_id("course", "CS 560")])
        self.assertEqual(rejected, [])
        loose = {"courses": [{"code": "CS 560", "status": "blocked", "why": ["CS 560 is hard."]}], "policy_notes": ["x"]}
        self.assertTrue(any(r["reason"] == "cites no evidence" for r in t.check(loose, {})))
        bad = {"claim": "CS 560 is easy.", "evidence_ids": ["engine_verdicts.MATH 999"]}
        t._check_claim(bad, rejected, judge=[], where="course")
        self.assertIn("does not exist", rejected[0]["reason"])

if __name__ == "__main__":
    unittest.main(verbosity=2)
