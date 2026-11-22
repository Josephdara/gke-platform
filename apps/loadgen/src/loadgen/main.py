"""loadgen load | eval: streams questions through the assistant and writes the results to --out."""

import argparse
import asyncio
from datetime import UTC, datetime
import json
from pathlib import Path
import subprocess
import sys

import yaml

from .client import Assistant, SignInFailed, now
from .evaluate import review_sheet, run_eval, scores
from .load import run_load, sample_line, summarize


def git_revision() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True,
                              check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="loadgen", description=__doc__)
    parser.add_argument("mode", choices=["load", "eval"])
    parser.add_argument("--url", required=True, help="The assistant's origin, such as https://assistant.example.com")
    parser.add_argument("--username", required=True)
    parser.add_argument("--password-file", required=True, type=Path, help="A file holding only the password")
    parser.add_argument("--questions", type=Path, default=Path("eval/questions.yaml"))
    parser.add_argument("--out", type=Path, help="Output directory; default results/<time>-<mode>")
    parser.add_argument("--concurrency", type=int, default=2, help="load: requests in flight at once")
    parser.add_argument("--duration", type=float, default=300, help="load: seconds to keep starting requests")
    parser.add_argument("--kinds", default="answerable", help="load: comma-separated question kinds to cycle through")
    args = parser.parse_args(argv)
    if not 1 <= args.concurrency <= 16 or args.duration <= 0:
        parser.error("--concurrency must be 1 to 16 and --duration positive")
    return args


async def run(args: argparse.Namespace) -> int:
    question_set = yaml.safe_load(args.questions.read_text())
    out = args.out or Path("results") / f"{datetime.now(UTC):%Y%m%dT%H%M%SZ}-{args.mode}"
    out.mkdir(parents=True, exist_ok=True)
    assistant = Assistant(args.url)
    try:
        await assistant.sign_in(args.username, args.password_file.read_text().strip())
        status = await assistant.status()
        manifest = {
            "mode": args.mode, "url": args.url, "startedAt": now(), "gitRevision": git_revision(),
            "promptVersion": status["promptVersion"], "model": status["model"]["alias"],
            "questionSet": question_set["version"], "corpus": question_set["corpus"],
        }
        if args.mode == "load":
            kinds = set(args.kinds.split(","))
            questions = [q["question"] for q in question_set["questions"] if q["kind"] in kinds]
            manifest |= {"concurrency": args.concurrency, "durationSeconds": args.duration, "kinds": sorted(kinds)}
            with (out / "samples.jsonl").open("w") as stream:
                def record(sample):
                    stream.write(json.dumps(sample_line(sample)) + "\n")
                    stream.flush()
                    print(f"{sample.started_at} {sample.outcome:<24} ttft {sample.ttft_s} total {sample.total_s}", flush=True)
                samples = await run_load(assistant, questions, args.concurrency, args.duration, record)
            summary = {"manifest": manifest | {"endedAt": now()}, **summarize(samples)}
            (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
            print(json.dumps({k: summary[k] for k in ("requests", "answered", "outcomes", "ttftSeconds", "totalSeconds")}))
        else:
            results = await run_eval(assistant, question_set)
            manifest["endedAt"] = now()
            report = {"manifest": manifest, "scores": scores(results), "results": results}
            (out / "results.json").write_text(json.dumps(report, indent=2) + "\n")
            (out / "review.md").write_text(review_sheet(results, manifest))
            print(json.dumps(report["scores"]))
        print(f"Wrote {out}")
        return 0
    except SignInFailed as exc:
        print(f"Sign-in failed: {exc}", file=sys.stderr)
        return 2
    finally:
        await assistant.close()


def main(argv: list[str] | None = None) -> None:
    sys.exit(asyncio.run(run(parse_args(sys.argv[1:] if argv is None else argv))))
