"""One function per LangGraph node. Each takes/returns a partial AgentState dict."""
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from langchain_core.messages import AIMessage, HumanMessage
from langchain_ollama import ChatOllama
from langgraph.types import interrupt

from ai.tools import (
    compare_candidates,
    extract_requirements,
    generate_interview_questions,
    search_resumes,
    suggest_improvements,
)

ROUND1_TOP_N = 10
BORDERLINE_COUNT = 2  # bottom-N of the round-1 shortlist get improvement suggestions
_llm = ChatOllama(model="llama3.2:3b", temperature=0)

INTENT_LABELS = {"END", "NEXT_ROUND", "REFINE", "COMPARE", "EXPLAIN", "INTERVIEW_QUESTIONS"}


def parse_jd(state):
    """First HumanMessage in the conversation is treated as the job description."""
    for msg in state["messages"]:
        if isinstance(msg, HumanMessage):
            return {"jd_text": msg.content, "round": 1}
    return {"round": 1}


def extract_requirements_node(state):
    result = extract_requirements.invoke({"jd_text": state["jd_text"]})
    if not result["success"]:
        return {"requirements": {"must_have": [], "nice_to_have": []}}
    return {"requirements": {"must_have": result["must_have"], "nice_to_have": result["nice_to_have"]}}


def search_resumes_node(state):
    top_n = ROUND1_TOP_N if state.get("round", 1) == 1 else len(state.get("candidate_pool") or [])
    args = {"jd_text": state["jd_text"], "top_n": top_n or ROUND1_TOP_N}
    if state.get("min_years"):
        args["min_years"] = state["min_years"]
    result = search_resumes.invoke(args)
    candidates = result["candidates"] if result["success"] else []
    return {"candidate_pool": candidates}


def rank_candidates(state):
    ranked = sorted(state.get("candidate_pool", []), key=lambda c: c["match_score"], reverse=True)
    return {"shortlist": ranked}


def _ranking_diff(prior_shortlist, new_shortlist):
    """Compare two ranked shortlists and describe what a refinement changed."""
    prior_rank = {c["candidate_name"]: i for i, c in enumerate(prior_shortlist, start=1)}
    new_rank = {c["candidate_name"]: i for i, c in enumerate(new_shortlist, start=1)}

    dropped = [name for name in prior_rank if name not in new_rank]
    added = [name for name in new_rank if name not in prior_rank]
    moved = [
        (name, prior_rank[name], new_rank[name])
        for name in prior_rank
        if name in new_rank and prior_rank[name] != new_rank[name]
    ]

    if not dropped and not added and not moved:
        return "No change from the previous ranking - the refined criteria didn't move anyone in or out of the top list."

    parts = []
    if added:
        parts.append(f"Newly in the top list: {', '.join(added)}.")
    if dropped:
        parts.append(f"Dropped out of the top list: {', '.join(dropped)}.")
    if moved:
        moves = ", ".join(
            f"{name} (#{old} -> #{new})" for name, old, new in sorted(moved, key=lambda m: m[2])
        )
        parts.append(f"Re-ranked: {moves}.")
    return "What changed: " + " ".join(parts)


def _borderline_section(state):
    """Bottom-of-the-shortlist candidates are the ones a real recruiter would be unsure
    about - give each a few concrete, resume-grounded ways to become a stronger fit."""
    shortlist = state["shortlist"]
    if len(shortlist) < 3:
        return None

    borderline = shortlist[-BORDERLINE_COUNT:]
    result = suggest_improvements.invoke({
        "candidate_ids": [c["candidate_name"] for c in borderline],
        "candidate_pool": shortlist,
        "jd_text": state.get("jd_text", ""),
    })
    suggestions = result["suggestions"] if result["success"] else result.get("error", "")
    return f"Borderline candidates - improvement suggestions:\n\n{suggestions}"


def _round1_report(state):
    lines = [f"Round 1 - top {len(state['shortlist'])} of the pool:\n"]
    for i, c in enumerate(state["shortlist"], start=1):
        lines.append(
            f"{i}. {c['candidate_name']} - {c['match_score']}/100 "
            f"({c['years_experience']} yrs, skills: {c.get('matched_skills', [])})"
        )
        lines.append(f"   {c.get('reasoning', '')}")

    prior_shortlist = state.get("prior_shortlist")
    if prior_shortlist:
        lines.append("")
        lines.append(_ranking_diff(prior_shortlist, state["shortlist"]))

    borderline_section = _borderline_section(state)
    if borderline_section:
        lines.append("")
        lines.append(borderline_section)

    return "\n".join(lines)


def _deterministic_verdict(shortlist):
    """The LLM's own closing verdict can contradict its pairwise strengths/gaps text once
    the shortlist gets large (observed: it dropped the actual top scorer from its own summary).
    Replace it with a verdict grounded in the state's score-ranked shortlist, which round 3
    already trusts over any round-2 free text."""
    if not shortlist:
        return "Verdict: no candidates to recommend."
    top = shortlist[0]
    return (
        f"Verdict: {top['candidate_name']} is the strongest candidate overall "
        f"(score {top['match_score']}/100 - {top.get('reasoning', '')})"
    )


def _round2_report(state):
    ids = [c["candidate_name"] for c in state["shortlist"]]
    result = compare_candidates.invoke({"candidate_ids": ids, "candidate_pool": state["shortlist"]})
    comparison = result["comparison"] if result["success"] else result.get("error", "comparison failed")
    comparison = re.split(r"\n?\s*Verdict:", comparison, maxsplit=1, flags=re.IGNORECASE)[0].rstrip()
    comparison += "\n\n" + _deterministic_verdict(state["shortlist"])
    return f"Round 2 - deep analysis of the top {len(ids)}:\n\n{comparison}"


def _round3_report(state):
    top = state["shortlist"][0] if state["shortlist"] else None
    if top is None:
        return "Round 3 - no candidates left to recommend."
    q_result = generate_interview_questions.invoke({
        "candidate_id": top["candidate_name"],
        "candidate_pool": state["shortlist"],
        "jd_text": state.get("jd_text", ""),
    })
    questions = q_result["questions"] if q_result["success"] else q_result.get("error", "")
    return (
        f"Round 3 - hire recommendation:\n\n"
        f"Recommend: {top['candidate_name']} (score {top['match_score']}/100)\n"
        f"{top.get('reasoning', '')}\n\n"
        f"Suggested screening questions:\n{questions}"
    )


def generate_report(state):
    round_num = state.get("round", 1)
    if round_num == 1:
        report = _round1_report(state)
    elif round_num == 2:
        report = _round2_report(state)
    else:
        report = _round3_report(state)
    return {
        "messages": [AIMessage(content=report)],
        "last_action": f"report_round_{round_num}",
        "prior_shortlist": [],
    }


def _extract_min_years(text):
    """Pull a 'N+ years' / 'N years' style cutoff out of free-text refinement, if present."""
    match = re.search(r"(\d+)\s*\+?\s*years?", text.lower())
    return int(match.group(1)) if match else None


def _mentioned_candidates(text, pool):
    text_lower = text.lower()
    hits = []
    for c in pool:
        name = c["candidate_name"]
        if name.lower() in text_lower or name.split()[0].lower() in text_lower:
            hits.append(name)
    return hits


_WORD_NUMBERS = {
    "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10,
}


def _ordinal_count(text):
    """Pull a count out of phrasing like 'top 3', 'top three', 'the top two candidates'."""
    text_lower = text.lower()
    match = re.search(r"top\s+(\d+)", text_lower)
    if match:
        return int(match.group(1))
    for word, n in _WORD_NUMBERS.items():
        if re.search(rf"top\s+{word}\b", text_lower):
            return n
    return None


def _resolve_candidates(text, pool):
    """Resolve which shortlist candidates the user means: named mentions first
    ('compare Jane and John'), falling back to ordinal rank references
    ('compare the top 3', 'top two candidates') since pool is already rank-ordered."""
    named = _mentioned_candidates(text, pool)
    if len(named) >= 2:
        return named
    n = _ordinal_count(text)
    if n and n >= 2:
        return [c["candidate_name"] for c in pool[:n]]
    return named


def _resolve_single_candidate(text, pool):
    """Resolve which single shortlist candidate the user means: named mention first,
    falling back to ordinal rank ('the top candidate' -> pool[0], 'the #2 candidate' -> pool[1])."""
    named = _mentioned_candidates(text, pool)
    if named:
        return named[0]
    if pool and re.search(r"\btop\b", text.lower()):
        n = _ordinal_count(text) or 1
        if 1 <= n <= len(pool):
            return pool[n - 1]["candidate_name"]
    return None


def _classify_intent(user_text):
    prompt = (
        "Classify the user's request into exactly one label: "
        "END, NEXT_ROUND, REFINE, COMPARE, EXPLAIN, INTERVIEW_QUESTIONS.\n"
        "END = satisfied, done, thanks, stop.\n"
        "NEXT_ROUND = wants deeper analysis, next screening round, or a hire recommendation.\n"
        "REFINE = wants to change search criteria (skills, years, seniority) and re-search.\n"
        "COMPARE = wants a head-to-head comparison of specific named candidates.\n"
        "EXPLAIN = asks why one candidate ranked above/below another.\n"
        "INTERVIEW_QUESTIONS = asks for interview or screening questions for a specific candidate.\n"
        f"User message: {user_text}\n"
        "Reply with only the label, nothing else."
    )
    label = _llm.invoke(prompt).content.strip().upper()
    for known in INTENT_LABELS:
        if known in label:
            return known
    return "END"


def human_feedback(state):
    """Pauses the graph for real user input (LangGraph interrupt), classifies intent,
    and either answers inline (COMPARE/EXPLAIN) or routes to the next node."""
    user_text = interrupt({"question": "What would you like to do next?"})
    new_messages = [HumanMessage(content=user_text)]

    intent = _classify_intent(user_text)

    if intent == "REFINE":
        refined_jd = f"{state['jd_text']}\n\nAdditional requirement: {user_text}"
        new_min_years = _extract_min_years(user_text)
        min_years = max(state.get("min_years") or 0, new_min_years or 0) or None
        return {
            "messages": new_messages,
            "jd_text": refined_jd,
            "round": 1,
            "last_action": "refine",
            "min_years": min_years,
            "prior_shortlist": state.get("shortlist", []),
        }

    if intent == "NEXT_ROUND":
        next_round = min(state.get("round", 1) + 1, 3)
        return {"messages": new_messages, "round": next_round, "last_action": "next_round"}

    if intent == "COMPARE":
        ids = _resolve_candidates(user_text, state.get("shortlist", []))
        if len(ids) < 2:
            answer = "Name at least two candidates (or say 'top N') from the shortlist to compare."
        else:
            result = compare_candidates.invoke({"candidate_ids": ids, "candidate_pool": state["shortlist"]})
            answer = result["comparison"] if result["success"] else result.get("error", "comparison failed")
        return {"messages": new_messages + [AIMessage(content=answer)], "last_action": "answered"}

    if intent == "EXPLAIN":
        ids = _resolve_candidates(user_text, state.get("shortlist", []))
        if len(ids) < 2:
            answer = "Name two candidates (or say 'top N') from the shortlist so I can explain the ranking."
        else:
            result = compare_candidates.invoke({"candidate_ids": ids, "candidate_pool": state["shortlist"]})
            answer = result["comparison"] if result["success"] else result.get("error", "comparison failed")
        return {"messages": new_messages + [AIMessage(content=answer)], "last_action": "answered"}

    if intent == "INTERVIEW_QUESTIONS":
        candidate_id = _resolve_single_candidate(user_text, state.get("shortlist", []))
        if not candidate_id:
            answer = "Name a candidate (or say 'the top candidate') from the shortlist to generate interview questions for."
        else:
            result = generate_interview_questions.invoke({
                "candidate_id": candidate_id,
                "candidate_pool": state["shortlist"],
                "jd_text": state.get("jd_text", ""),
            })
            answer = result["questions"] if result["success"] else result.get("error", "question generation failed")
        return {"messages": new_messages + [AIMessage(content=answer)], "last_action": "answered"}

    return {"messages": new_messages, "last_action": "end"}


def route_after_feedback(state):
    action = state.get("last_action")
    if action == "refine":
        return "extract_requirements"
    if action == "next_round":
        return "generate_report"
    if action == "answered":
        return "human_feedback"
    return "END"
