"""Automated conversation-flow runner.

Drives the real compiled LangGraph (real Ollama + ChromaDB, no mocks) through the
scripted turns for each scenario in docs/test_scenarios.md, end to end, and saves a
full transcript per scenario to output/. Complements (does not replace) the manual
runs already logged in docs/test_scenarios.md.

Usage:
    python scripts/run_scenarios.py [scenario_name ...]   # default: run all
"""
import os
import sys
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.types import Command

from ai.matching_agent import build_graph, new_thread_config

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "output")
JD_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "job_descriptions")


def _read_jd(filename):
    with open(os.path.join(JD_DIR, filename), encoding="utf-8") as f:
        return f.read().strip()


SCENARIOS = {
    "initial_search": {
        "jd_text": lambda: _read_jd("jd_01_senior_backend_engineer.txt"),
        "turns": ["thanks, that's all"],
    },
    "refinement": {
        "jd_text": lambda: _read_jd("jd_01_senior_backend_engineer.txt"),
        "turns": [
            "only consider candidates with 10+ years and AWS experience",
            "thanks, that's all",
        ],
    },
    "compare": {
        "jd_text": lambda: _read_jd("jd_01_senior_backend_engineer.txt"),
        "turns": ["compare the top 2 candidates", "thanks, that's all"],
    },
    "explain": {
        "jd_text": lambda: _read_jd("jd_01_senior_backend_engineer.txt"),
        "turns": [
            "why did the top 2 candidates rank in that order",
            "thanks, that's all",
        ],
    },
    "interview_questions": {
        "jd_text": lambda: _read_jd("jd_01_senior_backend_engineer.txt"),
        "turns": [
            "generate interview questions for the top candidate",
            "thanks, that's all",
        ],
    },
    "multi_round_screening": {
        "jd_text": lambda: _read_jd("jd_05_machine_learning_engineer.txt"),
        "turns": ["next round", "next round", "thanks, that's all"],
    },
    "ambiguous_jd": {
        "jd_text": lambda: "Need a software person.",
        "turns": ["thanks, that's all"],
    },
}


def run_scenario(name, spec):
    lines = [f"=== SCENARIO: {name} ===", ""]
    graph = build_graph()
    config = new_thread_config(thread_id=f"run-scenarios-{name}")

    jd_text = spec["jd_text"]()
    lines.append(f"[JD]\n{jd_text}\n")

    seen = 0
    for _ in graph.stream({"messages": [HumanMessage(content=jd_text)]}, config=config):
        pass
    snapshot = graph.get_state(config)
    seen = _append_new_messages(snapshot.values, seen, lines)

    for turn in spec["turns"]:
        interrupts = snapshot.tasks[0].interrupts if snapshot.tasks else []
        if not interrupts:
            lines.append("[SESSION ENDED before this turn]")
            break
        lines.append(f"[YOU] {turn}")
        for _ in graph.stream(Command(resume=turn), config=config):
            pass
        snapshot = graph.get_state(config)
        seen = _append_new_messages(snapshot.values, seen, lines)
        if not snapshot.next:
            lines.append("[SESSION ENDED]")
            break

    return "\n".join(lines)


def _append_new_messages(state_values, seen_count, lines):
    messages = state_values.get("messages", [])
    for msg in messages[seen_count:]:
        if isinstance(msg, AIMessage) and msg.content:
            lines.append(f"\n[AGENT]\n{msg.content}\n")
    return len(messages)


def main():
    requested = sys.argv[1:] or list(SCENARIOS.keys())
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    for name in requested:
        if name not in SCENARIOS:
            print(f"Unknown scenario: {name} (choices: {list(SCENARIOS.keys())})")
            continue
        print(f"Running scenario: {name} ...")
        transcript = run_scenario(name, SCENARIOS[name])
        out_path = os.path.join(OUTPUT_DIR, f"auto_{name}_{date.today().isoformat()}.txt")
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(transcript)
        print(f"  saved: {out_path}")


if __name__ == "__main__":
    main()
