# Report Blueprint (LLM + Database Bonus)

## 1. Introduction and Motivation
- Project context: IMDb top-1000 analytical retrieval system
- Why LLM integration: reduce SQL barrier and improve exploratory querying
- Bonus focus: prompt engineering for accurate SQL generation

## 2. Design and Implementation
### 2.1 System architecture
- User NL query -> Prompt builder -> LLM -> SQL safety gateway -> SQLite executor
- ReAct repair loop for robustness

### 2.2 Context token strategy
- Full metadata compression and fixed context token injection
- Schema, PK/FK mapping, semantic ranking hints, safe defaults
- Zero-shot vs Few-shot vs Constrained prompt strategies

### 2.3 Local SQL safety gateway (engineering highlight)
- AST parser (sqlglot) checks for destructive statements
- Reject write operations: DROP / DELETE / UPDATE / INSERT / TRUNCATE / ALTER / CREATE
- Table whitelist and single-statement constraint
- Limit policy for broad listing

### 2.4 ReAct auto-repair loop
- Trigger condition: AST parse fail or SQL execution error
- Error stack feedback to model
- SQL rewrite attempts (max rounds)
- Return trace for observability in demo/report

### 2.5 APIs
- POST /api/query/nl
- POST /api/recommend/nl
- Response includes generated_sql, result_count, latency_ms, react_trace

## 3. Evaluation and Comparison
### 3.1 Prompt strategy comparison
- executable rate
- correctness rate
- average latency
- failure type distribution

### 3.2 Hard-case demonstrations
- Nolan collaboration + avg rating > 8
- top grossing ambiguity
- adversarial destructive prompt rejection

### 3.3 Ablation suggestion
- without context tokens
- without AST gateway
- without ReAct loop

## 4. Conclusion and Self-evaluation
- What worked well
- Current limitations
- Next iteration ideas

## 5. References
- sqlglot
- Gemini API
- MovieLens / Kaggle IMDb sources

## Appendix
- Core code excerpts
- Prompt versions
- Full evaluation logs
