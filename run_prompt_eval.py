import argparse
import json
import time
from collections import Counter
from pathlib import Path

from llm_service import LLMQueryService, LLMServiceError, SQLValidationError


def load_eval_cases(eval_file: Path):
    with eval_file.open("r", encoding="utf-8") as f:
        return json.load(f)


def evaluate(service: LLMQueryService, cases, strategy: str):
    records = []
    for case in cases:
        task = case.get("task", "NL2SQL")
        query = case["query"]
        started = time.perf_counter()

        try:
            if task == "Recommendation":
                out = service.generate_recommendations(query=query, strategy=strategy)
            else:
                out = service.generate_nl2sql(query=query, strategy=strategy)

            elapsed = int((time.perf_counter() - started) * 1000)
            records.append(
                {
                    "id": case["id"],
                    "task": task,
                    "query": query,
                    "strategy": strategy,
                    "status": "success",
                    "result_count": out.get("result_count", 0),
                    "latency_ms": out.get("latency_ms", elapsed),
                    "generated_sql": out.get("generated_sql", ""),
                    "error": None,
                }
            )
        except (LLMServiceError, SQLValidationError, Exception) as e:  # Keep full batch running.
            elapsed = int((time.perf_counter() - started) * 1000)
            records.append(
                {
                    "id": case["id"],
                    "task": task,
                    "query": query,
                    "strategy": strategy,
                    "status": "error",
                    "result_count": 0,
                    "latency_ms": elapsed,
                    "generated_sql": "",
                    "error": str(e),
                }
            )

    return records


def summarize(records):
    total = len(records)
    if total == 0:
        return {
            "total": 0,
            "success": 0,
            "error": 0,
            "executable_rate": 0.0,
            "avg_latency_ms": 0,
        }

    success = sum(1 for r in records if r["status"] == "success")
    error = total - success
    avg_latency = int(sum(r["latency_ms"] for r in records) / total)

    return {
        "total": total,
        "success": success,
        "error": error,
        "executable_rate": round(success / total, 4),
        "avg_latency_ms": avg_latency,
    }


def write_jsonl(records, path: Path):
    with path.open("w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def top_error(records, max_len: int = 120):
    errors = [r["error"] for r in records if r.get("error")]
    if not errors:
        return ""
    most_common = Counter(errors).most_common(1)[0][0]
    return most_common if len(most_common) <= max_len else most_common[: max_len - 3] + "..."


def write_markdown_summary(rows, path: Path):
    lines = [
        "# Prompt Strategy Evaluation Summary",
        "",
        "| Strategy | #Cases | Success | Error | Executable Rate | Avg Latency (ms) | Top Error |",
        "|---|---:|---:|---:|---:|---:|---|",
    ]

    for row in rows:
        lines.append(
            "| {strategy} | {cases} | {success} | {error} | {rate} | {latency} | {top_error} |".format(
                strategy=row["strategy"],
                cases=row["total"],
                success=row["success"],
                error=row["error"],
                rate=f"{row['executable_rate'] * 100:.2f}%",
                latency=row["avg_latency_ms"],
                top_error=row["top_error"] or "",
            )
        )

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description="Run NL2SQL prompt strategy evaluation.")
    parser.add_argument("--eval-file", default="nl2sql_eval_set.json")
    parser.add_argument("--strategy", default="constrained", choices=["zero-shot", "few-shot", "constrained"])
    parser.add_argument("--all-strategies", action="store_true")
    parser.add_argument("--db", default="movies.db")
    parser.add_argument("--out", default=None)
    parser.add_argument("--summary-out", default="prompt_eval_summary.md")
    args = parser.parse_args()

    eval_file = Path(args.eval_file)
    cases = load_eval_cases(eval_file)
    service = LLMQueryService(db_path=args.db)

    strategies = ["zero-shot", "few-shot", "constrained"] if args.all_strategies else [args.strategy]

    summary_rows = []
    output_files = []

    for strategy in strategies:
        records = evaluate(service=service, cases=cases, strategy=strategy)
        summary = summarize(records)
        summary["strategy"] = strategy
        summary["top_error"] = top_error(records)
        summary_rows.append(summary)

        out_file = Path(args.out) if args.out and len(strategies) == 1 else Path(f"eval_results_{strategy}.jsonl")
        write_jsonl(records, out_file)
        output_files.append(str(out_file))

    summary_path = Path(args.summary_out)
    write_markdown_summary(summary_rows, summary_path)

    print(
        json.dumps(
            {
                "summaries": summary_rows,
                "outputs": output_files,
                "summary_markdown": str(summary_path),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
