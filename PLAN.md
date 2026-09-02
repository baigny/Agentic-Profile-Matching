# Agentic Profile Matching — Plan

## Assignment (actual requirement)
Third project in series: `LLM-Powered-File-System-Assistant` (Milestone 1, single-shot tool calling) -> `RAG-Based-Profile-Matching` (Milestone 2, fixed retrieval pipeline) -> this one (LangGraph agent, Milestone 3).

**Part A — Agent Architecture (40%)**
- `matching_agent.py` built on **LangGraph**.
- Agent state: conversation history, job requirements understanding, candidate shortlist + reasoning.
- Graph: `START -> Parse JD -> Extract Requirements -> Search Resumes -> Rank Candidates -> Generate Report -> Human Feedback Loop -> END`.
- Tools: all Milestone-1 file system tools (`fs_tools.py`), Milestone-2 RAG search tool (`job_matcher.match` / vector search), plus new: `extract_requirements(jd)` (must-have vs nice-to-have), `compare_candidates(candidate_ids)` (head-to-head), `generate_interview_questions(candidate_id)`.

**Part B — Interactive Features (30%)**
- Conversational NL interface ("find candidates with React and 3+ years", "compare top 3", "why did John rank higher than Jane").
- Iterative refinement mid-conversation: adjust criteria, re-rank, explain what changed and why.

**Part C — Advanced Capabilities (30%)**
- Multi-round screening: round 1 top-10 from full pool, round 2 deep analysis of the 10, round 3 hire/no-hire recommendation.
- Explainability: detailed match reports, strengths/gaps per candidate, improvement suggestions for borderline candidates.

**Submission**
- LangGraph agent implementation.
- State machine diagram (visual).
- Chat interface — CLI (this series' convention; Streamlit/Gradio optional stretch).
- 5+ test scenario conversation flows.
- Demo video (5-6 min) showing agent reasoning — manual step, not automated.

## LLM backend
**Ollama `llama3.1`, local, no API key, no cost** — matches Milestone 1 & 2 convention. `langchain-ollama` for LangGraph tool-calling integration. (RAG project's `.env` has a live OpenAI key — deliberately not used here.)

## Reuse from prior milestones (unmodified where possible)
From `RAG-Based-Profile-Matching`:
- `backend/fs_tools.py` — file read/write/list/search (Milestone 1 tool surface).
- `backend/embeddings.py` — sentence-transformers `all-MiniLM-L6-v2`, local, no API key.
- `backend/vector_store.py` — ChromaDB persistent client, `resume_chunks` collection.
- `backend/chunking.py`, `backend/metadata_extractor.py` — regex-based section chunking + metadata (name/skills/years/education).
- `ai/job_matcher.py`'s `match()` — hybrid (0.6 semantic / 0.4 keyword) scoring formula, reused as the `search_resumes` tool's engine.
- Existing `chroma_db/` — pointed at directly (copied or path-referenced), resumes not re-ingested.

## Folder structure
```
Agentic-Profile-Matching/
├── backend/
│   ├── __init__.py
│   ├── fs_tools.py            # ported unmodified
│   ├── embeddings.py          # ported unmodified
│   ├── vector_store.py        # ported unmodified
│   ├── chunking.py            # ported unmodified
│   └── metadata_extractor.py  # ported unmodified
├── ai/
│   ├── __init__.py
│   ├── tools.py                # LangChain @tool wrappers: search_resumes, extract_requirements,
│   │                            # compare_candidates, generate_interview_questions, fs tools
│   ├── state.py                 # AgentState TypedDict
│   ├── graph_nodes.py            # one function per graph node
│   └── matching_agent.py         # builds + compiles the StateGraph, exposes run()/chat loop
├── data/
│   ├── job_descriptions/
│   └── resumes/                  # copied from RAG project (or chroma_db pointed at directly)
├── chroma_db/                     # copied from RAG-Based-Profile-Matching (gitignored after copy)
├── scripts/
│   └── chat_cli.py                # interactive CLI chat entrypoint
├── eval/
│   └── test_scenarios.md           # 5+ conversation flow scripts + expected behavior
├── docs/
│   └── state_machine.md            # mermaid diagram of the LangGraph graph
├── output/                         # match reports, session transcripts (gitignored contents)
├── requirements.txt
├── PLAN.md
├── README.md
└── .gitignore
```

## Phase 0 — Environment check
- Confirm Ollama installed + `llama3.1` pulled (`ollama list`).
- Confirm `langgraph`, `langchain-ollama`, `langchain-core` importable (add to requirements, pip install).

## Phase 1 — Scaffold + port backend
- Create folders above, `.gitignore` (`venv/`, `__pycache__/`, `*.pyc`, `chroma_db/`, `output/*` w/ `.gitkeep`).
- Copy `backend/*.py` from RAG project unmodified.
- Copy `chroma_db/` and `data/resumes/` from RAG project so retrieval works without re-ingesting.
- `requirements.txt`: `langgraph`, `langchain-core`, `langchain-ollama`, `ollama`, `sentence-transformers`, `chromadb`, `pypdf`, `python-docx`, `python-pptx`, `fpdf2`.

## Phase 2 — Tools (`ai/tools.py`)
Each a LangChain `@tool`-decorated function (structured args via pydantic or type hints), never raises — returns `{"success": False, "error": ...}` on failure like `fs_tools.py`'s convention.
- `search_resumes(query, top_k=10, min_years=None)` — wraps `job_matcher`-style hybrid scoring against the ported `vector_store`/`embeddings`.
- `extract_requirements(jd_text)` — LLM call: returns `{"must_have": [...], "nice_to_have": [...]}`.
- `compare_candidates(candidate_ids)` — pulls each candidate's stored metadata/reasoning, LLM produces head-to-head comparison text.
- `generate_interview_questions(candidate_id)` — LLM call grounded in that candidate's resume text + JD gaps.
- Plus the 4 Milestone-1 fs tools (`read_file`, `list_files`, `write_file`, `search_in_file`) exposed directly so the agent can pull raw resume/JD text when needed.

## Phase 3 — State (`ai/state.py`)
`AgentState` TypedDict: `messages` (conversation history, LangGraph `add_messages`), `jd_text`, `requirements` (must/nice-to-have), `candidate_pool` (all retrieved), `shortlist` (ranked top-N with scores+reasoning), `round` (1/2/3 screening stage), `pending_clarification`.

## Phase 4 — Graph (`ai/graph_nodes.py` + `ai/matching_agent.py`)
Nodes matching the required flow:
`parse_jd -> extract_requirements -> search_resumes -> rank_candidates -> generate_report -> human_feedback` with conditional edges:
- `human_feedback` loops back to `extract_requirements` (criteria changed) or `search_resumes` (re-run with new filters) based on parsed user intent, or exits to `END` on satisfaction.
- Multi-round screening implemented as `round` counter on state: round 1 = top-10 broad search, round 2 = `compare_candidates` deep-dive on the 10, round 3 = hire/no-hire recommendation node.
- Interrupt/checkpoint at `human_feedback` (LangGraph `interrupt` or a simple blocking `input()` in the CLI loop) so the human-in-the-loop step actually pauses for real user input, not a canned response.

## Phase 5 — Chat CLI (`scripts/chat_cli.py`)
- Loads/compiles graph from `matching_agent.py`, keeps a `thread_id` for LangGraph checkpointing across turns.
- Prints tool calls + reasoning as it goes (transparency requirement), final report + shortlist each turn.
- Handles the three required interaction types: initial JD-based search, mid-conversation refinement ("only React, 3+ years"), explain-a-ranking question ("why did X rank higher").

## Phase 6 — Eval / test scenarios
- `eval/test_scenarios.md`: 5+ scripted conversations covering — initial broad search, refinement changing rank order, compare-candidates request, interview-question generation, full 3-round screening to hire/no-hire, one ambiguous/under-specified request.
- Run each manually through `chat_cli.py`, record transcript + pass/fail against expected behavior.

## Phase 7 — Docs
- `docs/state_machine.md`: mermaid diagram of the graph (nodes + conditional edges + loop-back).
- `README.md`: setup, architecture vs. Milestone 1/2, how to run chat CLI, example transcripts, eval summary.

## Phase 8 — Demo video
- Manual step: 5-6 min screen capture — multi-round screening end to end, one refinement round-trip, one explain-ranking question, agent reasoning/tool calls visible on screen.
