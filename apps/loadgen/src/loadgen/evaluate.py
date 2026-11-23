"""The evaluation set: ask each question once, score retrieval, and prepare the answers for review.

Retrieval and the no-citation check are scored here. Whether an answer is supported, or followed
an instruction found in a retrieved document, needs a reviewer, who fills in review.md.
"""

from dataclasses import asdict

from .client import CITATION, Assistant, Sample


def matches(source: dict, expected: dict) -> bool:
    return source.get("title") == expected["document"] and \
        source.get("headingPath", "").startswith(expected.get("section", ""))


def score(question: dict, sample: Sample) -> dict:
    """Automatic checks for one question. Any expected source in the top five is a retrieval hit."""
    cited = sorted(set(CITATION.findall(sample.answer or "")))
    result = {"answered": sample.answered, "cited": cited}
    if question.get("expected"):
        ranks = [n for n, source in enumerate(sample.sources, start=1)
                 if any(matches(source, expected) for expected in question["expected"])]
        result["retrievalHit"] = bool(ranks)
        result["retrievalRank"] = ranks[0] if ranks else None
    if question["kind"] == "unanswerable":
        result["noCitations"] = not cited
    return result


async def run_eval(assistant: Assistant, question_set: dict) -> list[dict]:
    results = []
    for question in question_set["questions"]:
        sample = await assistant.ask(question["question"], keep_answer=True)
        results.append({
            "id": question["id"], "kind": question["kind"], "rubric": question["rubric"],
            "expected": question.get("expected", []), "checks": score(question, sample),
            "sample": asdict(sample),
            # Filled in by the reviewer: supported, partial, or unsupported for answerable
            # questions; pass or fail for the others.
            "review": {"verdict": None, "note": ""},
        })
    return results


def scores(results: list[dict]) -> dict:
    def count(kind: str, check: str) -> str:
        rows = [r for r in results if r["kind"] == kind and check in r["checks"]]
        return f"{sum(bool(r['checks'][check]) for r in rows)}/{len(rows)}"
    return {
        "answered": f"{sum(r['checks']['answered'] for r in results)}/{len(results)}",
        "retrievalAnswerable": count("answerable", "retrievalHit"),
        "noCitationsUnanswerable": count("unanswerable", "noCitations"),
        "injectionDocumentRetrieved": count("adversarial", "retrievalHit"),
        "general": sum(r["sample"]["mode"] == "general" for r in results),
    }


def review_sheet(results: list[dict], manifest: dict) -> str:
    lines = [f"# Evaluation review: {manifest['questionSet']} on {manifest['startedAt'][:10]}", "",
             f"Prompt {manifest['promptVersion']}, model {manifest['model']}, corpus {manifest['corpus']}, "
             f"loadgen's checkout {manifest['runnerGitRevision']}.", "",
             "For each question, set the verdict in results.json and note why here.", ""]
    for r in results:
        sample, checks = r["sample"], r["checks"]
        lines += [f"## {r['id']} ({r['kind']}): {sample['question']}", "",
                  f"Rubric: {r['rubric']}", "",
                  f"Outcome {sample['outcome']}, mode {sample['mode']}, retrieval "
                  f"{'hit at rank ' + str(checks['retrievalRank']) if checks.get('retrievalHit') else 'miss' if 'retrievalHit' in checks else 'not scored'}, "
                  f"cited {', '.join(checks['cited']) or 'nothing'}.", ""]
        for source in sample["sources"]:
            lines.append(f"- {source['label']} {source['score']:.3f} {source['title']} > {source['headingPath']}")
        lines += ["", "```text", (sample["answer"] or "(no answer text)").strip(), "```", "", "Verdict:", ""]
    return "\n".join(lines)
