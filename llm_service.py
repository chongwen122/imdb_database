import json
import importlib
import os
import re
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    sqlglot = importlib.import_module("sqlglot")
    exp = importlib.import_module("sqlglot.expressions")
    ParseError = getattr(importlib.import_module("sqlglot.errors"), "ParseError")
    HAS_SQLGLOT = True
except Exception:
    HAS_SQLGLOT = False
    sqlglot = None
    exp = None
    ParseError = Exception


SCHEMA_CONTEXT = """
You are generating SQL for a SQLite database named movies.db.

Tables:
1) Movie(
    movie_id INTEGER PRIMARY KEY,
    title TEXT,
    year INTEGER,
    certificate TEXT,
    runtime INTEGER,
    imdb_rating REAL,
    meta_score REAL,
    votes INTEGER,
    gross REAL,
    overview TEXT,
    poster_link TEXT,
    director_id INTEGER
)

2) Director(
    director_id INTEGER PRIMARY KEY,
    director_name TEXT
)

3) Actor(
    actor_id INTEGER PRIMARY KEY,
    actor_name TEXT
)

4) Genre(
    genre_id INTEGER PRIMARY KEY,
    genre TEXT
)

5) Movie_Actor(
    movie_id INTEGER,
    actor_id INTEGER,
    PRIMARY KEY(movie_id, actor_id)
)

6) Movie_Genre(
    movie_id INTEGER,
    genre_id INTEGER,
    PRIMARY KEY(movie_id, genre_id)
)

Relationships:
- Movie.director_id -> Director.director_id
- Movie_Actor joins Movie and Actor
- Movie_Genre joins Movie and Genre
""".strip()


FEW_SHOT_EXAMPLES = """
Q: Show top 5 movies by IMDb rating.
SQL: SELECT m.movie_id, m.title, m.year, m.imdb_rating
FROM Movie m
ORDER BY m.imdb_rating DESC, m.votes DESC
LIMIT 5;

Q: List movies directed by Christopher Nolan ordered by rating.
SQL: SELECT m.movie_id, m.title, m.year, m.imdb_rating
FROM Movie m
JOIN Director d ON m.director_id = d.director_id
WHERE d.director_name = 'Christopher Nolan'
ORDER BY m.imdb_rating DESC, m.votes DESC
LIMIT 50;

Q: Find drama movies with rating above 8.5.
SQL: SELECT m.movie_id, m.title, m.year, m.imdb_rating
FROM Movie m
JOIN Movie_Genre mg ON m.movie_id = mg.movie_id
JOIN Genre g ON mg.genre_id = g.genre_id
WHERE g.genre = 'Drama' AND m.imdb_rating > 8.5
ORDER BY m.imdb_rating DESC, m.votes DESC
LIMIT 50;

Q: Show top 10 highest grossing movies in film history style ranking.
SQL: SELECT m.movie_id, m.title, m.year, m.gross, d.director_name
FROM Movie m
JOIN Director d ON m.director_id = d.director_id
WHERE m.gross IS NOT NULL
ORDER BY m.gross DESC
LIMIT 10;

Q: Find actors who collaborated most with Christopher Nolan and have average movie rating above 8.
SQL: SELECT a.actor_id, a.actor_name,
    COUNT(*) AS collaboration_count,
    ROUND(AVG(m.imdb_rating), 2) AS avg_rating
FROM Actor a
JOIN Movie_Actor ma ON a.actor_id = ma.actor_id
JOIN Movie m ON ma.movie_id = m.movie_id
JOIN Director d ON m.director_id = d.director_id
WHERE d.director_name = 'Christopher Nolan'
GROUP BY a.actor_id, a.actor_name
HAVING AVG(m.imdb_rating) > 8
ORDER BY collaboration_count DESC, avg_rating DESC
LIMIT 50;
""".strip()


SEMANTIC_HINTS = """
Ranking intent hints:
- "highest rating", "top rated", "best" => ORDER BY imdb_rating DESC, then votes DESC.
- "top grossing", "box office top" => ORDER BY gross DESC.
- "most collaborated" => GROUP BY actor/director with COUNT(*) DESC.
- "average rating above X" => HAVING AVG(imdb_rating) > X.

Disambiguation policy:
- If user asks for "top" without number, use LIMIT 10.
- If user asks broad listing, use LIMIT 50.
""".strip()


FORBIDDEN_KEYWORDS = {
    "insert",
    "update",
    "delete",
    "drop",
    "alter",
    "truncate",
    "create",
    "attach",
    "detach",
    "pragma",
    "replace",
    "vacuum",
}

ALLOWED_TABLES = {
    "movie",
    "director",
    "actor",
    "genre",
    "movie_actor",
    "movie_genre",
}


class LLMServiceError(Exception):
    pass


class SQLValidationError(Exception):
    pass


class LLMQueryService:
    def __init__(
        self,
        db_path: str = "movies.db",
        model: Optional[str] = None,
        context_tokens_path: str = "context_tokens.json",
        max_react_rounds: int = 2,
    ) -> None:
        self._load_local_env(db_path)
        self.db_path = db_path
        self.provider = os.getenv("LLM_PROVIDER", "openrouter").strip().lower()
        default_model = (
            "minimax/minimax-m2.5:free"
            if self.provider == "openrouter"
            else "gemini-3-flash-preview"
        )
        self.model = model or os.getenv("LLM_MODEL") or os.getenv("GEMINI_MODEL") or default_model
        self.max_api_retries = max(0, int(os.getenv("LLM_MAX_RETRIES", "2")))
        self.retry_base_sec = float(os.getenv("LLM_RETRY_BASE_SEC", "1.2"))
        self.context_tokens_path = context_tokens_path
        self.max_react_rounds = max_react_rounds
        self.context_tokens = self._load_context_tokens()

    def _load_local_env(self, db_path: str) -> None:
        # Load .env colocated with db/service when environment variables are not set.
        env_file = Path(db_path).resolve().parent / ".env"
        if not env_file.exists():
            return

        try:
            lines = env_file.read_text(encoding="utf-8").splitlines()
        except Exception:
            return

        for line in lines:
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue

            key, value = stripped.split("=", 1)
            key = key.strip()
            if not key:
                continue

            value = value.strip().strip('"').strip("'")
            # Keep shell-exported values as higher priority.
            os.environ.setdefault(key, value)

    def generate_nl2sql(self, query: str, strategy: str = "constrained") -> Dict[str, Any]:
        safe_sql, rows, latency_ms, react_trace = self._run_sql_pipeline(
            query=query,
            strategy=strategy,
            recommendation=False,
        )
        return {
            "query": query,
            "strategy": strategy,
            "generated_sql": safe_sql,
            "result_count": len(rows),
            "latency_ms": latency_ms,
            "react_rounds": len(react_trace),
            "react_trace": react_trace,
            "results": rows,
        }

    def generate_recommendations(self, query: str, strategy: str = "constrained") -> Dict[str, Any]:
        safe_sql, rows, latency_ms, react_trace = self._run_sql_pipeline(
            query=query,
            strategy=strategy,
            recommendation=True,
        )
        return {
            "query": query,
            "strategy": strategy,
            "generated_sql": safe_sql,
            "result_count": len(rows),
            "latency_ms": latency_ms,
            "react_rounds": len(react_trace),
            "react_trace": react_trace,
            "results": rows,
        }

    def _run_sql_pipeline(
        self,
        query: str,
        strategy: str,
        recommendation: bool,
    ) -> Tuple[str, List[Dict[str, Any]], int, List[Dict[str, Any]]]:
        prompt = self._build_sql_prompt(query=query, strategy=strategy, recommendation=recommendation)
        raw = self._call_llm(prompt)
        sql = self._extract_sql(raw)

        react_trace: List[Dict[str, Any]] = []

        for round_idx in range(self.max_react_rounds + 1):
            try:
                safe_sql = self._validate_and_rewrite_sql(sql)
                rows, latency_ms = self._execute_sql(safe_sql)
                return safe_sql, rows, latency_ms, react_trace
            except (SQLValidationError, sqlite3.Error) as err:
                react_trace.append(
                    {
                        "round": round_idx + 1,
                        "failed_sql": sql,
                        "error": str(err),
                    }
                )
                if round_idx >= self.max_react_rounds:
                    raise SQLValidationError(
                        f"SQL failed after ReAct retries. last_error={err}"
                    ) from err
                sql = self._repair_sql_with_react(
                    query=query,
                    failed_sql=sql,
                    error_message=str(err),
                    recommendation=recommendation,
                )

        raise SQLValidationError("Unexpected SQL pipeline termination.")

    def _build_sql_prompt(self, query: str, strategy: str, recommendation: bool) -> str:
        token_context = self.context_tokens
        base_rules = (
            "Return exactly one SQLite SQL statement and nothing else. "
            "Only generate read-only SQL. "
            "Use only existing tables and columns. "
            "Always include LIMIT <= 50 for list queries."
        )

        task_hint = (
            "User asks for recommendations. Prefer returning movie rows ordered by relevance and rating."
            if recommendation
            else "User asks for database retrieval. Generate accurate SQL for the request."
        )

        if strategy == "zero-shot":
            return (
                f"{SCHEMA_CONTEXT}\n\n"
                f"Context tokens:\n{token_context}\n\n"
                f"Semantic hints:\n{SEMANTIC_HINTS}\n\n"
                f"Rules: {base_rules}\n"
                f"Task: {task_hint}\n"
                f"User query: {query}\n"
            )

        if strategy == "few-shot":
            return (
                f"{SCHEMA_CONTEXT}\n\n"
                f"Context tokens:\n{token_context}\n\n"
                f"Semantic hints:\n{SEMANTIC_HINTS}\n\n"
                f"Rules: {base_rules}\n\n"
                f"Examples:\n{FEW_SHOT_EXAMPLES}\n\n"
                f"Task: {task_hint}\n"
                f"User query: {query}\n"
            )

        # constrained (default)
        return (
            f"{SCHEMA_CONTEXT}\n\n"
            f"Context tokens:\n{token_context}\n\n"
            f"Semantic hints:\n{SEMANTIC_HINTS}\n\n"
            "Hard constraints:\n"
            "1) Only SELECT queries are allowed.\n"
            "2) No schema modification and no data modification.\n"
            "3) Single statement only (no multiple statements).\n"
            "4) Use explicit JOIN conditions when joining tables.\n"
            "5) Add ORDER BY for ranking requests.\n"
            "6) Add LIMIT 50 if user does not provide a smaller limit.\n"
            "7) Return plain SQL only.\n\n"
            f"Examples:\n{FEW_SHOT_EXAMPLES}\n\n"
            f"Task: {task_hint}\n"
            f"User query: {query}\n"
        )

    def _repair_sql_with_react(
        self,
        query: str,
        failed_sql: str,
        error_message: str,
        recommendation: bool,
    ) -> str:
        task_hint = (
            "recommendation-oriented ranking query"
            if recommendation
            else "information extraction query"
        )
        prompt = (
            "You are in SQL self-repair mode. Rewrite a failed SQL query using the database context.\n"
            "Return SQL only, one statement, SQLite dialect.\n"
            "Must be read-only and safe.\n\n"
            f"{SCHEMA_CONTEXT}\n\n"
            f"Context tokens:\n{self.context_tokens}\n\n"
            f"Task type: {task_hint}\n"
            f"User query: {query}\n"
            f"Failed SQL: {failed_sql}\n"
            f"Engine/validator error: {error_message}\n"
        )
        raw = self._call_llm(prompt)
        return self._extract_sql(raw)

    def _load_context_tokens(self) -> str:
        token_file = Path(self.context_tokens_path)
        if not token_file.is_absolute():
            token_file = Path(self.db_path).resolve().parent / token_file

        if token_file.exists():
            try:
                data = json.loads(token_file.read_text(encoding="utf-8"))
                return json.dumps(data, ensure_ascii=False, separators=(",", ":"))
            except Exception:
                pass

        # Fallback to a compact built-in context package.
        fallback = {
            "tables": ["Movie", "Director", "Actor", "Genre", "Movie_Actor", "Movie_Genre"],
            "primary_keys": {
                "Movie": "movie_id",
                "Director": "director_id",
                "Actor": "actor_id",
                "Genre": "genre_id",
            },
            "foreign_keys": [
                "Movie.director_id -> Director.director_id",
                "Movie_Actor.movie_id -> Movie.movie_id",
                "Movie_Actor.actor_id -> Actor.actor_id",
                "Movie_Genre.movie_id -> Movie.movie_id",
                "Movie_Genre.genre_id -> Genre.genre_id",
            ],
            "ranking_fields": ["imdb_rating", "votes", "gross"],
            "defaults": {"broad_limit": 50, "top_limit": 10},
        }
        return json.dumps(fallback, ensure_ascii=False, separators=(",", ":"))

    def _call_llm(self, prompt: str) -> str:
        last_error: Optional[Exception] = None
        for attempt in range(self.max_api_retries + 1):
            try:
                if self.provider == "openrouter":
                    return self._call_openrouter(prompt)
                if self.provider == "gemini":
                    return self._call_gemini(prompt)
                raise LLMServiceError(f"Unsupported LLM_PROVIDER: {self.provider}")
            except LLMServiceError as e:
                last_error = e
                if attempt >= self.max_api_retries:
                    break
                # Exponential backoff for transient 5xx/timeout jitter.
                sleep_s = self.retry_base_sec * (2 ** attempt)
                time.sleep(sleep_s)

        raise LLMServiceError(f"LLM call failed after retries: {last_error}")

    def _call_openrouter(self, prompt: str) -> str:
        api_key = os.getenv("OPENROUTER_API_KEY")
        if not api_key:
            raise LLMServiceError("OPENROUTER_API_KEY is not set in environment variables.")

        endpoint = "https://openrouter.ai/api/v1/chat/completions"
        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": "You generate safe, accurate SQLite queries. Return SQL only.",
                },
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.1,
            "max_tokens": 500,
        }
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        }

        req = urllib.request.Request(
            endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=35) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            err = e.read().decode("utf-8", errors="replace")
            raise LLMServiceError(f"OpenRouter HTTP error: {e.code} {err}") from e
        except (urllib.error.URLError, TimeoutError) as e:
            raise LLMServiceError(f"OpenRouter network error: {e}") from e

        try:
            content = data["choices"][0]["message"]["content"]
            if isinstance(content, list):
                merged = []
                for part in content:
                    if isinstance(part, dict) and "text" in part:
                        merged.append(str(part["text"]))
                return "\n".join(merged).strip()
            return str(content).strip()
        except (KeyError, IndexError, TypeError) as e:
            raise LLMServiceError(f"Unexpected OpenRouter response: {data}") from e

    def _call_gemini(self, prompt: str) -> str:
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise LLMServiceError("GEMINI_API_KEY is not set in environment variables.")

        endpoint = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{urllib.parse.quote(self.model)}:generateContent?key={urllib.parse.quote(api_key)}"
        )

        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.1,
                "maxOutputTokens": 500,
            },
        }

        req = urllib.request.Request(
            endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=35) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            err = e.read().decode("utf-8", errors="replace")
            raise LLMServiceError(f"Gemini API HTTP error: {e.code} {err}") from e
        except (urllib.error.URLError, TimeoutError) as e:
            raise LLMServiceError(f"Gemini API network error: {e}") from e

        try:
            return data["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError, TypeError) as e:
            raise LLMServiceError(f"Unexpected Gemini response: {data}") from e

    def _extract_sql(self, model_output: str) -> str:
        # Prefer SQL fenced block when present.
        block_match = re.search(r"```sql\s*(.*?)```", model_output, re.IGNORECASE | re.DOTALL)
        if block_match:
            return block_match.group(1).strip()

        code_match = re.search(r"```\s*(.*?)```", model_output, re.DOTALL)
        if code_match:
            return code_match.group(1).strip()

        return model_output.strip()

    def _validate_and_rewrite_sql(self, sql: str) -> str:
        candidate = " ".join(sql.strip().split())
        if not candidate:
            raise SQLValidationError("Generated SQL is empty.")

        lowered = candidate.lower()

        # Single statement only.
        if ";" in candidate[:-1]:
            raise SQLValidationError("Multiple SQL statements are not allowed.")

        # Remove trailing semicolon for simpler checks/execution.
        if candidate.endswith(";"):
            candidate = candidate[:-1].strip()
            lowered = candidate.lower()

        if not (lowered.startswith("select ") or lowered.startswith("with ")):
            raise SQLValidationError("Only SELECT (or WITH...SELECT) queries are allowed.")

        for bad in FORBIDDEN_KEYWORDS:
            if re.search(rf"\b{re.escape(bad)}\b", lowered):
                raise SQLValidationError(f"Forbidden keyword detected: {bad}")

        if HAS_SQLGLOT:
            try:
                ast = sqlglot.parse_one(candidate, read="sqlite")
            except ParseError as e:
                raise SQLValidationError(f"AST parse failed: {e}") from e

            forbidden_nodes = tuple(
                cls
                for cls in [
                    getattr(exp, "Delete", None),
                    getattr(exp, "Drop", None),
                    getattr(exp, "Insert", None),
                    getattr(exp, "Update", None),
                    getattr(exp, "Create", None),
                    getattr(exp, "Alter", None),
                    getattr(exp, "TruncateTable", None),
                    getattr(exp, "Command", None),
                    getattr(exp, "Merge", None),
                ]
                if cls is not None
            )
            for node in ast.walk():
                if isinstance(node, forbidden_nodes):
                    raise SQLValidationError(f"Forbidden AST node detected: {node.key}")

            cte_cls = getattr(exp, "CTE", tuple())
            if not isinstance(ast, (exp.Select, exp.Union, exp.Subquery, cte_cls)):
                # WITH queries usually compile into Select/Union. Keep explicit restriction here.
                if not (isinstance(ast, exp.Expression) and ast.find(exp.Select)):
                    raise SQLValidationError("Only SELECT-oriented AST is allowed.")

            referenced = [t.name.lower() for t in ast.find_all(exp.Table)]
            unknown = [t for t in referenced if t not in ALLOWED_TABLES]
            if unknown:
                raise SQLValidationError(f"Unknown or disallowed table referenced: {sorted(set(unknown))}")

            has_limit = any(s.args.get("limit") is not None for s in ast.find_all(exp.Select))
            has_agg = any(True for _ in ast.find_all(exp.AggFunc))
            if not has_limit and not has_agg:
                candidate = f"{ast.sql(dialect='sqlite')} LIMIT 50"
            else:
                candidate = ast.sql(dialect="sqlite")

            return candidate

        # Allow-table check (best-effort).
        referenced = re.findall(r"\b(?:from|join)\s+([a-zA-Z_][a-zA-Z0-9_]*)", lowered)
        unknown = [t for t in referenced if t not in ALLOWED_TABLES]
        if unknown:
            raise SQLValidationError(f"Unknown or disallowed table referenced: {sorted(set(unknown))}")

        # Enforce bounded result for non-aggregate listing queries.
        has_limit = re.search(r"\blimit\s+\d+\b", lowered) is not None
        if not has_limit and "count(" not in lowered and "avg(" not in lowered and "sum(" not in lowered:
            candidate += " LIMIT 50"

        return candidate

    def _execute_sql(self, sql: str) -> Tuple[List[Dict[str, Any]], int]:
        start = time.perf_counter()
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(sql).fetchall()
            latency_ms = int((time.perf_counter() - start) * 1000)
            return [dict(r) for r in rows], latency_ms
        finally:
            conn.close()
