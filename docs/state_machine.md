# Agent state machine

```mermaid
flowchart TD
    START([START]) --> parse_jd[parse_jd]
    parse_jd --> extract_requirements[extract_requirements]
    extract_requirements --> search_resumes[search_resumes]
    search_resumes --> rank_candidates[rank_candidates]
    rank_candidates --> generate_report[generate_report]
    generate_report --> human_feedback{{human_feedback}}

    human_feedback -->|REFINE| extract_requirements
    human_feedback -->|NEXT_ROUND| generate_report
    human_feedback -->|COMPARE / EXPLAIN /<br/>INTERVIEW_QUESTIONS| answered([answered inline])
    answered -->|asks again| human_feedback
    human_feedback -->|END| DONE([END])
```
See "Node responsibilities" and "Screening rounds" below for what each edge label means in detail.

## Node responsibilities
- **parse_jd** — takes the first human message as the job description, sets `round = 1`.
- **extract_requirements** — LLM call, splits JD into `must_have` / `nice_to_have`.
- **search_resumes** — hybrid semantic+keyword search (`ai/job_matcher.py`, ported from Milestone 2) against ChromaDB, top-10 for round 1.
- **rank_candidates** — sorts `candidate_pool` by `match_score` into `shortlist`.
- **generate_report** — round-dependent: round 1 = ranked list + reasoning + a ranking-change
  explanation (if this report followed a REFINE) + improvement suggestions for the bottom 2
  ("borderline") candidates, round 2 = LLM head-to-head deep analysis of the shortlist, round 3
  = hire/no-hire recommendation + interview questions for the top candidate.
- **human_feedback** — `interrupt()`s the graph for real user input, classifies intent (REFINE / NEXT_ROUND / COMPARE / EXPLAIN / INTERVIEW_QUESTIONS / END) via LLM, routes accordingly. COMPARE/EXPLAIN/INTERVIEW_QUESTIONS are answered inline without leaving this node. COMPARE/EXPLAIN resolve which candidates the user means by name first, falling back to ordinal rank ("compare the top 3") against the already rank-ordered shortlist; INTERVIEW_QUESTIONS resolves a single candidate the same way ("generate interview questions for the top candidate" / by name).

## Screening rounds
| round | trigger | behavior |
|---|---|---|
| 1 | initial JD | broad search, top 10 of the full pool |
| 2 | user says "go deeper" / "next round" | `compare_candidates` LLM deep-dive on the 10 |
| 3 | user says "next round" again | hire/no-hire recommendation + interview questions for top pick |
