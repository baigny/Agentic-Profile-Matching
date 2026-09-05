"""Builds and compiles the LangGraph StateGraph for the profile-matching agent.

Graph: START -> parse_jd -> extract_requirements -> search_resumes ->
rank_candidates -> generate_report -> human_feedback -> (loop or END)
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from ai.graph_nodes import (
    extract_requirements_node,
    generate_report,
    human_feedback,
    parse_jd,
    rank_candidates,
    route_after_feedback,
    search_resumes_node,
)
from ai.state import AgentState


def build_graph():
    graph = StateGraph(AgentState)

    graph.add_node("parse_jd", parse_jd)
    graph.add_node("extract_requirements", extract_requirements_node)
    graph.add_node("search_resumes", search_resumes_node)
    graph.add_node("rank_candidates", rank_candidates)
    graph.add_node("generate_report", generate_report)
    graph.add_node("human_feedback", human_feedback)

    graph.add_edge(START, "parse_jd")
    graph.add_edge("parse_jd", "extract_requirements")
    graph.add_edge("extract_requirements", "search_resumes")
    graph.add_edge("search_resumes", "rank_candidates")
    graph.add_edge("rank_candidates", "generate_report")
    graph.add_edge("generate_report", "human_feedback")
    graph.add_conditional_edges(
        "human_feedback",
        route_after_feedback,
        {
            "extract_requirements": "extract_requirements",
            "generate_report": "generate_report",
            "human_feedback": "human_feedback",
            "END": END,
        },
    )

    return graph.compile(checkpointer=MemorySaver())


def new_thread_config(thread_id="session-1"):
    return {"configurable": {"thread_id": thread_id}}
