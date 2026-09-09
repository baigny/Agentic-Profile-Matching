# Test scenarios

Seven conversation-flow scenarios covering the required interaction types (initial search,
refinement, compare, explain, multi-round screening, ambiguous input, session end). Each was
run live against `python scripts/chat_cli.py` with real Ollama (`llama3.2:3b`) and the ingested
ChromaDB index — no mocks. Full transcripts are in `output/`.

`scripts/run_scenarios.py` automates six of these seven flows (session-end is exercised as the
final turn of each) end to end against the real compiled graph, and writes a fresh transcript to
`output/auto_<scenario>_<date>.txt` on every run:
```
python scripts/run_scenarios.py                  # all scenarios
python scripts/run_scenarios.py compare explain   # a subset
```

## Scenario summary

| # | Scenario | Input | Result | Transcript |
|---|---|---|---|---|
| 1 | Initial broad search | JD 01 (senior backend engineer) | PASS | `scenario1_transcript_2026-09-10.txt` |
| 2 | Refinement changes ranking | "only consider candidates with 10+ years and AWS experience" | PASS | `scenario2_transcript_2026-09-10.txt` |
| 3 | Compare candidates | "compare Kaiya Jenkins and Zachary Wynton" | PASS | `scenario3_transcript_2026-09-10.txt` |
| 4 | Explain a ranking | "why did Kaiya Jenkins rank higher than Zachary Wynton" | PASS | `scenario4_transcript_2026-09-10.txt` |
| 5 | Full 3-round screening | JD 05 (ML engineer), "next round" x2 | PASS | `scenario5_transcript_2026-09-10.txt` |
| 6 | Ambiguous / under-specified JD | "Need a software person." | PASS | `scenario6_transcript_2026-09-10.txt` |
| 7 | End session | "thanks, that's all" | PASS | same as scenario 1 |

## 1. Initial broad search
- **Input**: contents of `data/job_descriptions/jd_01_senior_backend_engineer.txt`.
- **Expected**: graph runs `parse_jd -> extract_requirements -> search_resumes -> rank_candidates -> generate_report -> human_feedback` end to end; round-1 report lists top 10 ranked candidates with score/skills/reasoning; agent pauses on interrupt asking what's next.
- **Result**: PASS. 10 ranked candidates returned with scores, years, matched skills, and reasoning; agent interrupted with "What would you like to do next?".

## 2. Refinement changes ranking
- **Setup**: continue scenario 1.
- **Input**: "only consider candidates with 10+ years and AWS experience".
- **Expected**: REFINE intent classified; `min_years` extracted and applied as a hard filter; round resets to 1; re-ranked shortlist differs from scenario 1; report explains what changed.
- **Result**: PASS. Pool narrowed 10 -> 9 candidates; top candidate changed (#5 -> #1 for the candidate meeting the new years cutoff); candidates below the cutoff dropped out; report's "What changed" section correctly listed additions/drops/re-ranks.

## 3. Compare candidates
- **Setup**: continue scenario 1.
- **Input**: "compare Kaiya Jenkins and Zachary Wynton".
- **Expected**: COMPARE intent; inline head-to-head comparison with strengths/gaps per candidate and one verdict; agent re-interrupts (no round change).
- **Result**: PASS. Comparison produced strengths/gaps for each candidate and a single verdict naming the stronger candidate by matched-skill count; no round change.

## 4. Explain a ranking
- **Setup**: continue scenario 1.
- **Input**: "why did Kaiya Jenkins rank higher than Zachary Wynton".
- **Expected**: EXPLAIN intent; inline comparison referencing both candidates' scores/skills; verdict consistent with their actual rank order.
- **Result**: PASS. Answer cited both scores and specific skill gaps; verdict matched the actual ranking order.

## 5. Full 3-round screening to hire/no-hire
- **Input**: `jd_05_machine_learning_engineer.txt`.
- **Turn 2**: "next round" -> round 2 deep analysis of the top 10.
- **Turn 3**: "next round" -> round 3 hire recommendation + interview questions for the top candidate.
- **Expected**: round counter advances 1 -> 2 -> 3; report shape changes each round (ranked list -> comparison -> recommendation + questions); round 3's pick is consistent with round 1's score ranking.
- **Result**: PASS. Round 1 produced a top-10 shortlist; round 2 produced a full comparison across the 10 with a verdict; round 3 recommended the actual top-ranked candidate (by `match_score`, independent of round 2's free text) with 5 interview questions grounded in that candidate's resume content.

## 6. Ambiguous / under-specified request
- **Input**: a one-line JD with no explicit skills ("Need a software person.").
- **Expected**: `extract_requirements` returns an empty/thin `must_have`; `search_resumes` still runs on semantic similarity alone; reasoning notes low keyword match.
- **Result**: PASS. Graph completed round 1, interrupt, and END normally; reasoning correctly showed no forced/spurious required-skill matches.

## 7. End session
- **Setup**: continue any scenario.
- **Input**: "thanks, that's all".
- **Expected**: END intent; graph reaches `END`; CLI prints `[SESSION ENDED]`.
- **Result**: PASS. No further agent message emitted; session ended cleanly.

## Fix log
Issues found while running the scenarios above, with root cause and resolution:

| Area | Issue | Fix |
|---|---|---|
| CLI paste input | Multi-line JD paste stopped at the first blank line, truncating the JD. | `scripts/chat_cli.py` now requires two consecutive blank lines (or EOF) to end paste. |
| Ordinal compare/explain | "Compare the top 3 matches" (assignment's own example) named no candidates by name, so the agent refused. | Added `_resolve_candidates` (`ai/graph_nodes.py`) — falls back to ordinal phrasing ("top 3", "top three") against the rank-ordered shortlist when fewer than 2 named candidates are found. |
| Borderline explainability | Improvement suggestions for borderline candidates weren't implemented. | Added `suggest_improvements` tool (`ai/tools.py`), wired into the round-1 report for the bottom 2 of the shortlist, grounded in each candidate's actual resume gaps. |
| Refinement had no effect | A refinement like "5+ years and AWS" only appended text to `jd_text`; nothing turned it into a hard filter, and there was no diff logic to report what changed. | `human_feedback`'s REFINE branch (`ai/graph_nodes.py`) now regex-extracts a `min_years` cutoff and passes it to `search_resumes` as a hard filter (`job_matcher.match`'s existing `where` clause); `generate_report` diffs `prior_shortlist` vs the new `shortlist` and reports additions/drops/re-ranks. |
| Inference speed | `llama3.1` (8B) on CPU made round-1 + compare take ~10 minutes. | Switched to `llama3.2:3b`; batched `suggest_improvements` into one LLM call across all borderline candidates instead of one call each. |
| Skill matching false positives | `ai/job_matcher.py`'s `_normalize()` did raw substring containment on a punctuation-stripped blob, so a 2-letter parenthetical degree acronym parsed as a "skill" (e.g. "EE") substring-matched inside unrelated words ("n**ee**d"). Visible as `CE`/`EE`/`CD`/`CI` noise in every scenario's `matched_skills`. | `_normalize()` now tokenizes on word boundaries and rejoins with `\|` delimiters, so a skill's token sequence must appear as whole, adjacent tokens. Verified: required-skill counts dropped from inflated values to the real ones, ranking order corrected, real matches (AWS, Python, Docker, etc.) unaffected. |
| Round-2 verdict inconsistency | `compare_candidates` reasons over all 10 shortlisted candidates in a single LLM call; at that scale its closing verdict could contradict the strengths/gaps it had just written (observed: it dropped the candidate it called strongest in every pairwise comparison). | `_round2_report` (`ai/graph_nodes.py`) strips the LLM's own verdict line and replaces it with one grounded in the state's score-ranked `shortlist` — the same source of truth round 3 already uses. |
| Round-2 latency and repetition | `compare_candidates`' original prompt asked for head-to-head comparisons, which the model interpreted as one full pairwise write-up per candidate against the top candidate — repeating the same strengths/gaps text ~9 times over a 10-candidate shortlist and taking ~11 minutes on CPU. | Reworded the prompt (`ai/tools.py`) to ask for one short paragraph per candidate (strengths/gaps against the job requirements, not against each other), and added `num_predict=700` to `ChatOllama` to cap generation length. Re-verified: same 10-candidate scenario now takes ~8 minutes with no repeated text, one paragraph per candidate. |

## Known limitations (not fixed, documented)
- Resume pool is 32 (curated, verifiable), not the assignment brief's illustrative "100" — round 1 still performs a genuine broad-search-to-top-10 cut over the full pool.
- Metadata extraction (`backend/metadata_extractor.py`, ported unmodified from Milestone 2) is regex/exact-header based; it can still produce noisy entries in a candidate's raw `skills` list (separate from the `matched_skills` used for scoring, which is now word-boundary safe). A structural fix (e.g. NER-based extraction) is out of scope for this milestone.
