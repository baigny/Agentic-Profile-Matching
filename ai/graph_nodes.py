"""One function per LangGraph node. Each takes/returns a partial AgentState dict."""
import os
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
)

ROUND1_TOP_N = 10
_llm = ChatOllama(model="llama3.1", temperature=0)

INTENT_LABELS = {"END", "NEXT_ROUND", "REFINE", "COMPARE", "EXPLAIN"}


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
    result = search_resumes.invoke({"jd_text": state["jd_text"], "top_n": top_n or ROUND1_TOP_N})
    candidates = result["candidates"] if result["success"] else []
    return {"candidate_pool": candidates}


def rank_candidates(state):
    ranked = sorted(state.get("candidate_pool", []), key=lambda c: c["match_score"], reverse=True)
    return {"shortlist": ranked}


def _round1_report(state):
    lines = [f"Round 1 - top {len(state['shortlist'])} of the pool:\n"]
    for i, c in enumerate(state["shortlist"], start=1):
        lines.append(
            f"{i}. {c['candidate_name']} - {c['match_score']}/100 "
            f"({c['years_experience']} yrs, skills: {c.get('matched_skills', [])})"
        )
        lines.append(f"   {c.get('reasoning', '')}")
    return "\n".join(lines)


def _round2_report(state):
    ids = [c["candidate_name"] for c in state["shortlist"]]
    result = compare_candidates.invoke({"candidate_ids": ids, "candidate_pool": state["shortlist"]})
    comparison = result["comparison"] if result["success"] else result.get("error", "comparison failed")
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
    return {"messages": [AIMessage(content=report)], "last_action": f"report_round_{round_num}"}


def _mentioned_candidates(text, pool):
    text_lower = text.lower()
    hits = []
    for c in pool:
        name = c["candidate_name"]
        if name.lower() in text_lower or name.split()[0].lower() in text_lower:
            hits.append(name)
    return hits


def _classify_intent(user_text):
    prompt = (
        "Classify the user's request into exactly one label: END, NEXT_ROUND, REFINE, COMPARE, EXPLAIN.\n"
        "END = satisfied, done, thanks, stop.\n"
        "NEXT_ROUND = wants deeper analysis, next screening round, or a hire recommendation.\n"
        "REFINE = wants to change search criteria (skills, years, seniority) and re-search.\n"
        "COMPARE = wants a head-to-head comparison of specific named candidates.\n"
        "EXPLAIN = asks why one candidate ranked above/below another.\n"
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
        return {
            "messages": new_messages,
            "jd_text": refined_jd,
            "round": 1,
            "last_action": "refine",
        }

    if intent == "NEXT_ROUND":
        next_round = min(state.get("round", 1) + 1, 3)
        return {"messages": new_messages, "round": next_round, "last_action": "next_round"}

    if intent == "COMPARE":
        ids = _mentioned_candidates(user_text, state.get("shortlist", []))
        if len(ids) < 2:
            answer = "Name at least two candidates from the shortlist to compare."
        else:
            result = compare_candidates.invoke({"candidate_ids": ids, "candidate_pool": state["shortlist"]})
            answer = result["comparison"] if result["success"] else result.get("error", "comparison failed")
        return {"messages": new_messages + [AIMessage(content=answer)], "last_action": "answered"}

    if intent == "EXPLAIN":
        ids = _mentioned_candidates(user_text, state.get("shortlist", []))
        if len(ids) < 2:
            answer = "Name two candidates from the shortlist so I can explain the ranking."
        else:
            result = compare_candidates.invoke({"candidate_ids": ids, "candidate_pool": state["shortlist"]})
            answer = result["comparison"] if result["success"] else result.get("error", "comparison failed")
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
