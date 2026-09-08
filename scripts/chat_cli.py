"""Interactive chat CLI for the LangGraph profile-matching agent.

Usage: python scripts/chat_cli.py
Paste/type a job description as the first message, then respond to the
agent's prompts (refine criteria, ask for next round, compare candidates,
ask "why did X rank over Y", or say "done" to end).
"""
import os
import sys
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.types import Command

from ai.matching_agent import build_graph, new_thread_config


def _print_new_messages(chunk_state, seen_count):
    messages = chunk_state.get("messages", [])
    for msg in messages[seen_count:]:
        if isinstance(msg, AIMessage) and msg.content:
            print(f"\n[AGENT]\n{msg.content}\n")
    return len(messages)


def main():
    graph = build_graph()
    thread_id = str(uuid.uuid4())
    config = new_thread_config(thread_id)

    print("Paste the job description (multi-line OK, blank lines within it are fine),")
    print("then an empty line twice (or Ctrl-D) to finish:")
    lines = []
    blank_run = 0
    while True:
        try:
            line = input()
        except EOFError:
            break
        if not line.strip():
            blank_run += 1
            if lines and blank_run >= 2:
                break
            continue
        blank_run = 0
        lines.append(line)
    jd_text = "\n".join(lines).strip()
    if not jd_text:
        print("No job description given, exiting.")
        return

    seen = 0
    state = None
    for event in graph.stream({"messages": [HumanMessage(content=jd_text)]}, config=config):
        state = list(event.values())[0]

    snapshot = graph.get_state(config)
    seen = _print_new_messages(snapshot.values, seen)

    while True:
        interrupts = snapshot.tasks[0].interrupts if snapshot.tasks else []
        if not interrupts:
            print("\n[SESSION ENDED]")
            break

        prompt_text = interrupts[0].value.get("question", "Your response:")
        try:
            user_reply = input(f"\n{prompt_text}\n> ").strip()
        except EOFError:
            print("\n[SESSION ENDED]")
            break
        print(f"[YOU] {user_reply}")

        for event in graph.stream(Command(resume=user_reply), config=config):
            pass

        snapshot = graph.get_state(config)
        seen = _print_new_messages(snapshot.values, seen)

        if not snapshot.next:
            print("\n[SESSION ENDED]")
            break


if __name__ == "__main__":
    main()
