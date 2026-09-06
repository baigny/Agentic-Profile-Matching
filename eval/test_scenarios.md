# Test scenarios

Run each through `python scripts/chat_cli.py`, paste the JD, then follow the
turns below. Record actual output alongside "expected" for the submission.

## 1. Initial broad search
- Input: contents of `data/job_descriptions/jd_01_senior_backend_engineer.txt`
- Expected: round-1 report, top 10 ranked candidates with score/skills/reasoning; agent then pauses (interrupt) asking what's next.

## 2. Refinement changes ranking
- Continue scenario 1.
- Input: "only consider candidates with 5+ years and AWS experience"
- Expected: REFINE intent, `jd_text` appended, round resets to 1, re-search + re-rank produces a different top list, agent explains via the new report.

## 3. Compare candidates
- Continue scenario 1.
- Input: "compare the top 2 candidates" (naming both by name)
- Expected: COMPARE intent, inline head-to-head comparison text, then agent asks again (loop, no round change).

## 4. Explain a ranking
- Continue scenario 1.
- Input: "why did <candidate A> rank higher than <candidate B>"
- Expected: EXPLAIN intent, inline comparison referencing both candidates' scores/skills, then asks again.

## 5. Full 3-round screening to hire/no-hire
- Input: `jd_05_machine_learning_engineer.txt`
- Turn 2: "go to the next round" -> round 2 deep analysis of the 10.
- Turn 3: "next round" -> round 3 hire recommendation + interview questions for the top candidate.
- Expected: round counter advances 1 -> 2 -> 3, report content changes shape each round (list -> comparison -> recommendation+questions).

## 6. Ambiguous / under-specified request
- Input: a JD with almost no explicit skills listed (e.g. a one-line description).
- Expected: `extract_requirements` returns thin/empty `must_have`; `search_resumes` still runs on semantic similarity alone; agent's round-1 report should show low keyword_match scores and reasoning noting "ranked on semantic similarity alone".

## 7. End session
- Continue any scenario.
- Input: "thanks, that's all"
- Expected: END intent, graph reaches `END`, CLI prints `[SESSION ENDED]`.
