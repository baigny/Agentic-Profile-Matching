# Test scenarios

## Post-scenario fixes (2026-09-10/11)
A final pass against the assignment brief, after scenarios 1-7 above first ran, found two
real gaps and applied fixes, re-verified live:
- **Part B**: "Compare the top 3 matches side by side" (the brief's own example) named no
  one, so `_mentioned_candidates` found nothing and the agent refused. Added `_resolve_candidates`
  (`ai/graph_nodes.py`) - falls back to ordinal phrasing ("top 3", "top three") against the
  already rank-ordered shortlist when fewer than 2 named candidates are found. Verified: "compare
  the top 3 candidates" -> correct 3 (rank 1-3).
- **Part C**: "improvement suggestions for borderline candidates" (Explainability) wasn't
  implemented anywhere. Added `suggest_improvements` tool (`ai/tools.py`) and wired it into
  the round-1 report for the bottom 2 of the shortlist. Verified: suggestions grounded in each
  candidate's actual resume gaps, not generic advice.
- Speed/cost: `suggest_improvements` batches all borderline candidates into one LLM call
  (was one call each, same pattern `compare_candidates` already used) and both tools' models
  switched `llama3.1` (8B) -> `llama3.2:3b` for CPU inference speed. Verified batching doesn't
  mix candidates up (distinct headers, correct resume-grounded content per person) and timed:
  old code (unbatched, 8B) ~10 min for round-1 + compare; new code (batched, 3B) ~4-5 min for
  the same. Found and fixed a regression from the smaller model: `compare_candidates`' prompt
  said "a one-sentence verdict" but 3B gave one per candidate instead of one overall - tightened
  the prompt to explicitly forbid per-candidate verdicts and require exactly one final `Verdict:`
  section. Transcripts: `output/scenario1b_ordinal_borderline_transcript_2026-09-10.txt` (old
  code), `output/scenario1c_batched_fastmodel_transcript_2026-09-10.txt` (new code).


Run each through `python scripts/chat_cli.py`, paste the JD, then follow the
turns below. Record actual output alongside "expected" for the submission.

## 1. Initial broad search
- Input: contents of `data/job_descriptions/jd_01_senior_backend_engineer.txt`
- Expected: round-1 report, top 10 ranked candidates with score/skills/reasoning; agent then pauses (interrupt) asking what's next.
- **Actual (run 2026-09-10, live `python scripts/chat_cli.py`, real Ollama `llama3.1` + ChromaDB, no mocks)**: PASS. Full JD (28 lines, multiple blank-line-separated sections) read correctly — this run caught and fixed a bug where the CLI's paste reader stopped at the *first* blank line, truncating any real JD after its first paragraph; fixed to require two consecutive blank lines (or EOF) to end paste. Graph ran `parse_jd -> extract_requirements -> search_resumes -> rank_candidates -> generate_report -> human_feedback` end to end. Round-1 report printed 10 ranked candidates (KAIYA JENKINS 83.2/100 top, ALEXANDER RYDER 66.0/100 tenth) with scores, years, matched skills, and reasoning. Agent then interrupted with "What would you like to do next?". Full transcript: `output/scenario1_transcript_2026-09-10.txt`.

## 2. Refinement changes ranking
- Continue scenario 1.
- Input: "only consider candidates with 5+ years and AWS experience"
- Expected: REFINE intent, `jd_text` appended, round resets to 1, re-search + re-rank produces a different top list, agent explains via the new report.
- **Actual (run 2026-09-10, live, real Ollama + ChromaDB)**: first attempt with "5+ years and AWS" produced an *identical* round-1 report — a real bug: `jd_text` got the refinement text appended, but nothing turned "5+ years" into a hard filter (the original JD already said 5 years / AWS, so the semantic re-embed barely moved), and there was no diff logic to explain *anything*, whether the ranking changed or not. Fixed in `ai/graph_nodes.py` + `ai/state.py`: `human_feedback`'s REFINE branch now regex-extracts a `min_years` cutoff from the user's text and passes it to `search_resumes` as a hard filter (already supported by `job_matcher.match`'s `where` clause, just never wired up from the conversational path), and stashes the pre-refine `shortlist` as `prior_shortlist`; `generate_report`'s round-1 path now diffs `prior_shortlist` vs the new `shortlist` and appends a "What changed" line (added/dropped/re-ranked). Re-tested with "only consider candidates with 10+ years and AWS experience": pool went 10 -> 9 candidates, KAHLIL JONES moved #5 -> #1, KAIYA JENKINS/ZACHARY WYNTON/AUSTIN REED/ALEXANDER RYDER dropped (all <10yrs), 3 new names entered. PASS after fix. Transcript: `output/scenario2_transcript_2026-09-10.txt`.

## 3. Compare candidates
- Continue scenario 1.
- Input: "compare the top 2 candidates" (naming both by name)
- Expected: COMPARE intent, inline head-to-head comparison text, then agent asks again (loop, no round change).
- **Actual (run 2026-09-10, live)**: PASS. "compare Kaiya Jenkins and Zachary Wynton" classified COMPARE, `compare_candidates` produced strengths/gaps for each + a verdict (Zachary stronger — more required skills matched: 21/28 vs 19/28), agent re-interrupted (no round change). Transcript: `output/scenario3_transcript_2026-09-10.txt`.

## 4. Explain a ranking
- Continue scenario 1.
- Input: "why did <candidate A> rank higher than <candidate B>"
- Expected: EXPLAIN intent, inline comparison referencing both candidates' scores/skills, then asks again.
- **Actual (run 2026-09-10, live)**: PASS. "why did Kaiya Jenkins rank higher than Zachary Wynton" classified EXPLAIN, inline answer correctly cited both scores (83.2 vs 77.1) and skill gaps (Kaiya lacks CD/Containerization/management, Zachary lacks Django), verdict correctly matched actual ranking order. Also used this run to verify a CLI readability fix (`scripts/chat_cli.py` now echoes `[YOU] <reply>` after each turn so piped/redirected transcripts show the full conversation, not just the agent's side). Transcript: `output/scenario4_transcript_2026-09-10.txt`.

## 5. Full 3-round screening to hire/no-hire
- Input: `jd_05_machine_learning_engineer.txt`
- Turn 2: "go to the next round" -> round 2 deep analysis of the 10.
- Turn 3: "next round" -> round 3 hire recommendation + interview questions for the top candidate.
- Expected: round counter advances 1 -> 2 -> 3, report content changes shape each round (list -> comparison -> recommendation+questions).
- **Actual (run 2026-09-10, live)**: PASS on graph mechanics. Round 1: top 10, KATHERINE WYLDE #1 (83.7/100). Round 2: `compare_candidates` ran all 45 pairwise comparisons across the 10, each with strengths/gaps/verdict. Round 3: correctly recommended KATHERINE WYLDE (pulled from the round-1 score-ranked `shortlist`, unaffected by round 2's prose) + 5 grounded screening questions referencing her actual resume content (Apache Airflow, NovaSpire Inc., NLTK/spaCy). **Known limitation found**: round 2's LLM-generated closing "top candidates" summary line contradicts its own pairwise verdicts — Katherine Wylde won every head-to-head shown in the transcript, yet the model's own summary list omits her entirely. Cosmetic/explainability issue only — round 3's actual recommendation is unaffected since it reads the state's score-ranked shortlist, not round 2's free-text summary. Transcript: `output/scenario5_transcript_2026-09-10.txt`.

## 6. Ambiguous / under-specified request
- Input: a JD with almost no explicit skills listed (e.g. a one-line description).
- Expected: `extract_requirements` returns thin/empty `must_have`; `search_resumes` still runs on semantic similarity alone; agent's round-1 report should show low keyword_match scores and reasoning noting "ranked on semantic similarity alone".
- **Actual (run 2026-09-10, live)**: PARTIAL — graph ran fine (round 1 report, interrupt, END all worked), but surfaced a real bug shared with `RAG-Based-Profile-Matching`'s ported code. Input JD was "Need a software person." — expected an empty `must_have` and "ranked on semantic similarity alone" reasoning. Instead every candidate showed a spurious "Matches 1/1 required skills (EE)". Root cause: `ai/job_matcher.py`'s `_normalize()` does raw substring containment (`_normalize(skill) in normalized_jd`) with no word boundaries, so the 2-letter "skill" token `EE` matches because "n**ee**d" contains "ee". This is the same bug visible as noise (`CE`, `EE`, `CD`, `CI` garbage "skills") in every other scenario's transcript, just usually masked by real matches alongside it — here, with no real skills in the JD, the false positive became the *only* match and changed the reported reasoning. Same class of issue the prior milestone's RAG review flagged ("chunking and metadata extraction rely on exact-header and regex patterns... narrow embedding layer"). Slated for fix as part of the `RAG-Based-Profile-Matching` improvement pass (and should be back-ported into this repo's `ai/job_matcher.py`, which is an unmodified copy). Transcript: `output/scenario6_transcript_2026-09-10.txt`.

## 7. End session
- Continue any scenario.
- Input: "thanks, that's all"
- Expected: END intent, graph reaches `END`, CLI prints `[SESSION ENDED]`.
- **Actual (run 2026-09-10, same live run as scenario 1)**: PASS. Reply "thanks, that's all" at the round-1 interrupt classified as END, no further AIMessage emitted (correct — END path only appends the HumanMessage), `snapshot.next` empty, CLI printed `[SESSION ENDED]`. Same transcript as scenario 1.
