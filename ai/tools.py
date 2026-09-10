"""Tool surface for the LangGraph agent.

Milestone-1 fs tools + Milestone-2 RAG search are wrapped unmodified;
extract_requirements / compare_candidates / generate_interview_questions
are new LLM-backed tools for this milestone. Every tool returns a dict and
never raises, matching backend/fs_tools.py's convention.
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from langchain_core.tools import tool
from langchain_ollama import ChatOllama

from ai import job_matcher
from backend import fs_tools

# llama3.2:3b instead of llama3.1 (8B) - much faster on CPU, small quality tradeoff.
# extract_requirements' JSON parsing already fails soft (falls back to empty
# must_have/nice_to_have) if the smaller model's output isn't valid JSON.
# num_predict caps generation length so a large shortlist (round-2 compare_candidates
# over 10 candidates) can't run away into a very long response.
MODEL = "llama3.2:3b"
_llm = ChatOllama(model=MODEL, temperature=0, num_predict=700)


def _resume_text(resume_path):
    result = fs_tools.read_file(resume_path)
    return result["content"] if result["success"] else ""


def _find_candidate(pool, candidate_id):
    """candidate_id is the resume filename (e.g. 'resume_02_backend_engineer.txt')
    or the bare candidate name — matched against candidate_pool entries."""
    for c in pool:
        if os.path.basename(c["resume_path"]) == candidate_id or c["candidate_name"] == candidate_id:
            return c
    return None


@tool
def search_resumes(jd_text: str, top_n: int = 10, min_years: int = None) -> dict:
    """Semantic + keyword search over the ingested resume collection for a job description.
    Returns ranked candidates with match_score, matched_skills, and reasoning."""
    try:
        results = job_matcher.match(jd_text, top_n=top_n, min_years=min_years)
        return {"success": True, "candidates": results}
    except Exception as e:
        return {"success": False, "error": str(e)}


@tool
def extract_requirements(jd_text: str) -> dict:
    """Parse a job description into must-have vs nice-to-have requirements using the LLM."""
    prompt = (
        "Read this job description and split its requirements into must-have and "
        "nice-to-have lists. Reply with ONLY a JSON object of the form "
        '{"must_have": ["..."], "nice_to_have": ["..."]}, no other text.\n\n'
        f"Job description:\n{jd_text}"
    )
    try:
        response = _llm.invoke(prompt)
        parsed = json.loads(response.content)
        return {
            "success": True,
            "must_have": parsed.get("must_have", []),
            "nice_to_have": parsed.get("nice_to_have", []),
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


@tool
def compare_candidates(candidate_ids: list[str], candidate_pool: list[dict]) -> dict:
    """Head-to-head comparison of two or more candidates already in the candidate pool.
    candidate_ids are resume filenames or candidate names. Returns LLM comparison text."""
    try:
        picked = [_find_candidate(candidate_pool, cid) for cid in candidate_ids]
        missing = [cid for cid, c in zip(candidate_ids, picked) if c is None]
        if missing:
            return {"success": False, "error": f"Candidate(s) not found in pool: {missing}"}

        summary_blocks = []
        for c in picked:
            summary_blocks.append(
                f"{c['candidate_name']} (score {c['match_score']}/100, "
                f"{c['years_experience']} yrs, skills: {c.get('matched_skills', [])})\n"
                f"reasoning: {c.get('reasoning', '')}"
            )
        prompt = (
            "Evaluate each candidate below for the same role. For EACH candidate, one heading "
            "with their name followed by ONE short paragraph (2-3 sentences) giving their "
            "strengths and gaps relative to the job requirements. Do NOT repeat pairwise "
            "comparisons or restate another candidate's info under each heading, and do NOT "
            "give a verdict per candidate. After ALL candidates are covered, end your reply "
            "with exactly one final section titled 'Verdict:' naming the single strongest "
            "candidate and why.\n\n"
            + "\n\n".join(summary_blocks)
        )
        response = _llm.invoke(prompt)
        return {"success": True, "comparison": response.content}
    except Exception as e:
        return {"success": False, "error": str(e)}


@tool
def generate_interview_questions(candidate_id: str, candidate_pool: list[dict], jd_text: str = "") -> dict:
    """Generate screening interview questions for one candidate, grounded in their resume
    text and (if given) gaps against the job description."""
    try:
        candidate = _find_candidate(candidate_pool, candidate_id)
        if candidate is None:
            return {"success": False, "error": f"Candidate not found in pool: {candidate_id}"}

        resume_text = _resume_text(candidate["resume_path"])
        prompt = (
            f"Candidate resume:\n{resume_text}\n\n"
            + (f"Job description:\n{jd_text}\n\n" if jd_text else "")
            + "Write 5 screening interview questions for this candidate. Prioritize probing "
            "any skills claimed but not clearly demonstrated, and any gaps against the job "
            "description if one was given. Number them 1-5, one per line."
        )
        response = _llm.invoke(prompt)
        return {"success": True, "questions": response.content}
    except Exception as e:
        return {"success": False, "error": str(e)}


@tool
def suggest_improvements(candidate_ids: list[str], candidate_pool: list[dict], jd_text: str = "") -> dict:
    """For one or more borderline candidates, suggest concrete ways each could become a
    stronger fit for the job description - grounded in their actual resume gaps, not
    generic advice. Batches all candidates into a single LLM call."""
    try:
        picked = [_find_candidate(candidate_pool, cid) for cid in candidate_ids]
        missing = [cid for cid, c in zip(candidate_ids, picked) if c is None]
        if missing:
            return {"success": False, "error": f"Candidate(s) not found in pool: {missing}"}

        blocks = []
        for c in picked:
            resume_text = _resume_text(c["resume_path"])
            blocks.append(
                f"=== {c['candidate_name']} (score {c.get('match_score', 'N/A')}/100, "
                f"matched skills: {c.get('matched_skills', [])}) ===\n{resume_text}"
            )
        prompt = (
            "\n\n".join(blocks) + "\n\n"
            + (f"Job description:\n{jd_text}\n\n" if jd_text else "")
            + "Each candidate above is borderline for this role - matched some but not all "
            "required skills. For EACH candidate, write 3 concrete, specific suggestions for "
            "how they could become a stronger fit (skills to gain, experience to build, "
            "certifications to pursue), grounded in an actual gap between their resume and "
            "the job description - not generic career advice. Group your answer under each "
            "candidate's name as a heading, numbered 1-3 under each."
        )
        response = _llm.invoke(prompt)
        return {"success": True, "suggestions": response.content}
    except Exception as e:
        return {"success": False, "error": str(e)}


@tool
def read_file(filepath: str) -> dict:
    """Read a file (.txt, .pdf, .docx, .pptx) and return its content."""
    return fs_tools.read_file(filepath)


@tool
def list_files(directory: str, extension: str = None) -> dict:
    """List files in a directory, optionally filtered by extension."""
    return {"success": True, "files": fs_tools.list_files(directory, extension)}


@tool
def write_file(filepath: str, content: str) -> dict:
    """Write text content to a file, creating parent directories if needed."""
    return fs_tools.write_file(filepath, content)


@tool
def search_in_file(filepath: str, keyword: str) -> dict:
    """Search for a keyword (case-insensitive) in a file or every file in a directory."""
    return fs_tools.search_in_file(filepath, keyword)


TOOLS = [
    search_resumes,
    extract_requirements,
    compare_candidates,
    generate_interview_questions,
    suggest_improvements,
    read_file,
    list_files,
    write_file,
    search_in_file,
]
