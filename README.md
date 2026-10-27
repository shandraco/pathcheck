# PathCheck

**Can I take this class? Straight answers from the catalog, with the proof.**

PathCheck is an agent team that answers students' registration questions (prerequisites, when a class is offered, online rules for international students) using the university's own catalog, class schedule, degree programs and policy pages. Every reason links to its source. Anything the data cannot settle goes to a human advisor instead of being guessed.

Built for the Open Agent Hackathon 2026, Track 2: **The Agent That Can Explain Why**.

## The problem

Advisors at large public universities each carry hundreds of students, and the rules students need are spread across a course catalog, a class schedule, program pages and policy pages that do not link to each other. A wrong answer costs a semester, money, or, for an international student, their visa status (for example, only one fully online course of up to 3 credits counts toward an F-1 student's full-time load at WSU). Chatbots make this worse when they answer confidently without checking.

## How it works

```
Student question
   │
   ▼
Planner ──────────► Researcher ──► Zetaris (one SQL layer over 4 separate sources)
 ▲   (targets, transcript,  │         pathcheck.courses · sections · programs · policies
 │    policy topics)        ▼
 │                 Meterless World Model  ◄── every row stored with the SQL and source that produced it
 │                          │
 │   no policy text found   ▼
 └──── broader terms ── Prerequisite engine (exact rules from catalog text; no model)
                            │  blocked? ──► Researcher fetches the missing prerequisites (2 levels)
                            ▼
                         Analyst (Nemotron via Meterless Nightshift) drafts the answer, citing evidence ids
                            │
                            ▼
                         Checker: rejects claims that cite nothing, cite missing or outdated
                         evidence, mention unchecked courses, or contradict the prerequisite engine;
                         a judge model checks policy claims against the cited text
                            │ rejected? ──► back to the Analyst (up to 3 rounds); still wrong → removed
                            ▼
                         Answer: per class "You can take it / Not yet / Check with your advisor",
                         reasons with clickable sources, rules that apply, questions for the advisor
```

Not a fixed pipeline: the run branches on blocked courses (path finding), thin evidence (re-planning), outdated pages (rejected) and rejected claims (revision loop).

## Sponsor technology

| Sponsor | Where it is used |
|---|---|
| **Zetaris** (data layer) | The four sources are registered as separate Lightning REST tables in one Lightning database (`zetaris/register.sql`). Every agent query is SQL sent to the Zetaris REST API (`pathcheck/data.py`). The trace shows each query, its row count and time. |
| **Meterless Engine: World Model** | `pathcheck/world_model.py`: hybrid entity graph plus run timeline; content-hash stable ids; append-only JSONL log with canonical replay; first-class relationships with provenance; agent attribution on every write; context builder used by the Analyst; state changes (outdated pages archived by the Checker). Tests: `tests/test_engine.py`. |
| **Meterless Nightshift** (primary AI provider) | `pathcheck/llm.py` follows the "Add Meterless as a provider" contract: OpenAI-compatible `/v1`, Bearer token, `meterless-app` and `meterless-scope` headers, status from `GET /v1/models` (online / unauthorized / offline), URL normalisation. Three lanes: fast (Planner), deep (Analyst), judge (Checker). |
| **NVIDIA Nemotron** | Served through Nightshift (NVIDIA key in Nightshift's Providers tab). The trace and every result record the exact model id that handled each agent's request. |

## Run it

Needs Python 3.10+ and nothing else (standard library only).

```bash
git clone https://github.com/shandraco/pathcheck && cd pathcheck
cp .env.example .env            # fill in Zetaris and Nightshift settings
python3 scripts/zetaris_setup.py   # registers the 4 sources in Zetaris, checks they answer
python3 -m pathcheck.server        # http://127.0.0.1:8931
```

No Zetaris or Nightshift available? `SAMPLE_MODE=true python3 -m pathcheck.server` runs on a local SQLite copy of the same data with recorded model replies (`samples/replay.json`), and falls back to the rule-based answer for new questions.

Command line: `python3 -m pathcheck.cli "I finished CS 311 and MATH 322. Can I take CS 400 and CS 560 in Spring 2027?"`

Tests: `python3 tests/test_engine.py`

## Evidence for judges

- `samples/`: three sample questions with full outputs.
- `logs/<run>.trace.jsonl`: every agent step, SQL query and model id. `logs/<run>.world.jsonl`: the World Model append log; `WorldModel.replay()` rebuilds the run's state from it.

## Data and pre-existing work

The data is a public snapshot of Wichita State University's catalog, class schedule, program and policy pages, crawled before the hackathon by the author (declared as a pre-existing component). `scripts/build_data.py` turns it into the four source files in `data/`. All agent, engine, checker and app code was written during the build window.
