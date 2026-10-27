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

## Disclosure

1. **Models through Nightshift:** NVIDIA Nemotron on three Meterless lanes. In our runs Nightshift routed the fast (Planner), deep (Analyst) and judge (Checker) lanes to `nvidia/nemotron-3.5-bolt-e4b`, and occasionally to `nvidia/nemotron-3-ultra-550b-a55b`. The exact model is logged on every request.
2. **Agent framework:** none. The agent team, loops and checker are plain Python (standard library only).
3. **Sponsor integration:** see "Sponsor technology" above.
4. **AI coding tool:** Claude Code (Anthropic). All generated code was reviewed and tested by the team.
5. **External tools and libraries:** Python standard library; `playwright-core`, macOS `say` and ffmpeg for the demo video and deck only.
6. **Data:** a real public snapshot of Wichita State University pages (see below). No synthetic data.
7. **Adapted open source:** none beyond the Meterless engine specifications and provider contract.
8. **Known limitations:** the sample runs in `samples/` used live Nemotron through Nightshift with the local SQLite copy of the four sources (`SAMPLE_MODE=true LLM_LIVE=true`); the Zetaris path (`zetaris/register.sql`, `pathcheck/data.py`) is implemented to the Zetaris REST API but was not exercised end to end in this build. Small models sometimes return malformed JSON; the run then falls back to the rule-based answer for that step and logs it. The data is a snapshot, so live catalog pages win for anything binding.
9. **Sample mode:** `SAMPLE_MODE=true` uses the local data copy and replays recorded Nightshift replies (`samples/replay.json`); prompts without a recording fall back to the rule-based planner, analyst and checker, and the trace says so. `LLM_LIVE=true` keeps local data but sends model calls to Nightshift.

## Data and pre-existing work

The data is a public snapshot of Wichita State University's catalog, class schedule, program and policy pages, crawled 22 September to 14 October 2026, before the build window, by the author for an earlier project (declared as a pre-existing component). `scripts/build_data.py` turns it into the four source files in `data/`. All agent, engine, checker and app code was written during the build window.
