# LLM Prompt Worklog

Use this file to maintain complete prompt exploration evidence for the report appendix.

## Experiment Record Template

- Date:
- Owner:
- Task type: NL2SQL / Recommendation
- Prompt version:
- Strategy: zero-shot / few-shot / constrained-template
- Model: gemini-2.0-flash (or other)
- Input question:
- Generated SQL:
- SQL validation result: pass / fail
- Execution result: success / error
- Result correctness: correct / partially correct / incorrect
- Latency (ms):
- Error type (if failed):
- Fix action:
- Notes:

---

## Prompt Version Log

### Kickoff (2026-04-12)
- Objective: create reproducible NL2SQL workflow before prompt tuning
- Completed:
	- created evaluation set file (`nl2sql_eval_set.json`)
	- added prompt strategies in `llm_service.py`
	- wired APIs in `app.py` (`/api/query/nl`, `/api/recommend/nl`)
	- added batch evaluation script `run_prompt_eval.py`
- Next:
	- run three strategy batches and fill summary table
	- annotate failure taxonomy by real errors

### Engineering Upgrade (2026-04-12)
- Objective: improve reliability with strict local SQL safety gateway and self-repair loop
- Completed:
	- introduced fixed metadata context pack (`context_tokens.json`) for full-context prompt injection
	- expanded complex few-shot SQL examples (ranking, collaboration, HAVING logic)
	- implemented AST-based SQL validation path (via `sqlglot`, when available)
	- blocked destructive operations at keyword + AST levels
	- added ReAct SQL repair loop with error feedback and retry trace (`react_trace`)
- Notes:
	- fallback validator remains available when `sqlglot` is not installed
	- report/demo files prepared: `REPORT_BLUEPRINT_LLM.md`, `DEMO_BENCHMARK.md`

### V1 (baseline)
- Objective:
- Key instructions:
- Known issues:

### V2 (few-shot)
- Objective:
- Added examples:
- Known issues:

### V3 (constrained)
- Objective:
- Added SQL policy:
- Known issues:

---

## Failure Taxonomy

- F1: Wrong table or column name
- F2: Missing join condition
- F3: Invalid aggregation or group by
- F4: Unbounded result set (no LIMIT)
- F5: Non-read-only SQL generated
- F6: Semantic mismatch with user intent

---

## Evaluation Summary Table

| Prompt Version | Strategy | #Cases | Executable Rate | Correctness Rate | Avg Latency (ms) | Notes |
|---|---|---:|---:|---:|---:|---|
| V1 | zero-shot | 12 | 50.00% | TBD | 10195 | Gemini 3 Flash run; top failure = API read timeout |
| V2 | few-shot | 12 | 33.33% | TBD | 14137 | Gemini 3 Flash run; top failure = API read timeout |
| V3 | constrained | 12 | 25.00% | TBD | 19131 | Gemini 3 Flash run; top failure = API read timeout |
