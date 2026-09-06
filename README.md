# Agentic Profile Matching

Third project in a series: `LLM-Powered-File-System-Assistant` (Milestone 1, single-shot
tool calling) -> `RAG-Based-Profile-Matching` (Milestone 2, fixed retrieval pipeline) ->
this one (Milestone 3, LangGraph agent with human-in-the-loop and multi-round screening).

## What's different from Milestone 1/2
- Milestone 1: one LLM call decides which of 4 file tools to call, no state across turns.
- Milestone 2: a fixed pipeline — embed JD -> retrieve -> score -> reason — always runs in that order.
- Milestone 3 (here): a **LangGraph** `StateGraph` with real conversational state (`AgentState`),
  a human-in-the-loop interrupt after every report, LLM-classified user intent routing the graph
  to different nodes (refine criteria / go deeper / compare / explain / end), and a 3-round
  screening flow (broad list -> deep comparison -> hire/no-hire recommendation).

## Stack
- **Ollama `llama3.1`**, local, no API key, no cost — used for `extract_requirements`,
  `compare_candidates`, `generate_interview_questions`, and intent classification.
- **ChromaDB** — vector store, reused unmodified from `RAG-Based-Profile-Matching`.
- **sentence-transformers** (`all-MiniLM-L6-v2`) — local embeddings, no API key.
- **LangGraph** — the agent graph, checkpointed with `MemorySaver` so `interrupt()`/`Command(resume=...)`
  can pause for and resume with real user input across CLI turns.

## Setup
```
pip install -r requirements.txt
ollama pull llama3.1
```
`chroma_db/` and `data/resumes/` are copied from `RAG-Based-Profile-Matching` — already
ingested, no re-run of ingestion needed.

## Run
```
python scripts/chat_cli.py
```
Paste a job description (e.g. contents of `data/job_descriptions/jd_01_senior_backend_engineer.txt`)
as the first input. The agent runs `parse_jd -> extract_requirements -> search_resumes ->
rank_candidates -> generate_report`, then pauses and asks what's next. Reply with things like:
- "only consider 5+ years and AWS" — refines criteria, re-searches (round resets to 1).
- "compare Jane Doe and John Smith" — inline head-to-head comparison.
- "why did Jane rank higher than John" — inline ranking explanation.
- "next round" — advances screening (round 2 deep analysis, round 3 hire recommendation).
- "that's all, thanks" — ends the session.

## Architecture
See [docs/state_machine.md](docs/state_machine.md) for the full graph diagram and node
responsibilities. See [PLAN.md](PLAN.md) for the assignment breakdown this was built against.

## Reused from prior milestones (unmodified)
- `backend/fs_tools.py`, `backend/embeddings.py`, `backend/vector_store.py`,
  `backend/chunking.py`, `backend/metadata_extractor.py` — copied from `RAG-Based-Profile-Matching`.
- `ai/job_matcher.py` — hybrid (0.6 semantic / 0.4 keyword) scoring, powers the `search_resumes` tool.

## Test scenarios
See [eval/test_scenarios.md](eval/test_scenarios.md) — 7 scripted conversation flows
(initial search, refinement, compare, explain, full 3-round screening, ambiguous JD, end session).

## Demo video
Manual step, not automated — 5-6 min screen capture showing a full 3-round screening,
one refinement round-trip, and one explain-ranking question with agent reasoning visible.
