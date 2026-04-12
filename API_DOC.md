# IMDB Movie Database — API 文档

**Backend**: Flask + SQLite (`movies.db`)
**Base URL**: `http://127.0.0.1:7777`

---

## 启动说明

```bash
pip install flask flask-cors sqlglot
export LLM_PROVIDER="openrouter"
export OPENROUTER_API_KEY="your_openrouter_key"
export LLM_MODEL="minimax/minimax-m2.5:free"
python app.py
```

服务默认运行在 `http://127.0.0.1:7777`，debug 模式开启。

说明：
- 推荐使用 OpenRouter：`LLM_PROVIDER=openrouter` + `OPENROUTER_API_KEY`。
- 当前默认模型可设置为 `LLM_MODEL=minimax/minimax-m2.5:free`。
- 兼容 Gemini：当 `LLM_PROVIDER=gemini` 时读取 `GEMINI_API_KEY`，模型可用 `LLM_MODEL` 或 `GEMINI_MODEL`。
- 可通过 `LLM_MAX_RETRIES` 与 `LLM_RETRY_BASE_SEC` 启用 API 重试退避，缓解抖动超时。
- 建议安装 `sqlglot` 以启用本地 AST 安全网关（更严格地过滤危险 SQL）。

---

## 接口列表

### 0. 自然语言转 SQL 查询（LLM）

| 项目 | 内容 |
|------|------|
| Method | `POST` |
| Endpoint | `/api/query/nl` |

**请求体**

```json
{
    "query": "show top 5 sci-fi movies after 2010",
    "strategy": "constrained"
}
```

- `query`：自然语言问题（必填）
- `strategy`：提示词策略（可选），可取 `zero-shot` / `few-shot` / `constrained`，默认 `constrained`

**返回示例（成功）**

```json
{
    "generated_sql": "SELECT ... LIMIT 50",
    "latency_ms": 132,
    "query": "show top 5 sci-fi movies after 2010",
    "result_count": 5,
    "react_rounds": 0,
    "react_trace": [],
    "results": [
        {
            "movie_id": 130,
            "title": "Inception",
            "imdb_rating": 8.8,
            "year": 2010
        }
    ],
    "strategy": "constrained"
}
```

**可靠性机制**

- 本地 AST 安全网关（推荐安装 `sqlglot`）：
    - 仅允许 `SELECT` / `WITH ... SELECT`
    - 拦截 `DROP/DELETE/TRUNCATE/UPDATE/INSERT/ALTER/CREATE` 等破坏性语句
    - 仅允许白名单表
    - 自动补齐 `LIMIT`（非聚合列表查询）
- ReAct 修正循环：
    - 若解析失败或执行报错，系统将错误信息反馈给模型并请求重写 SQL
    - 返回 `react_trace` 记录每轮失败 SQL 与报错

**返回示例（失败）**

```json
{
    "error": "Only SELECT (or WITH...SELECT) queries are allowed.",
    "query": "drop table Movie",
    "result_count": 0,
    "results": [],
    "strategy": "constrained"
}
```

---

### 0.1 自然语言推荐查询（LLM）

| 项目 | 内容 |
|------|------|
| Method | `POST` |
| Endpoint | `/api/recommend/nl` |

**请求体**

```json
{
    "query": "recommend emotional drama movies",
    "strategy": "constrained"
}
```

响应结构与 `/api/query/nl` 一致，主要区别在于提示词会偏向推荐结果排序。

---

### 1. 获取电影列表

| 项目 | 内容 |
|------|------|
| Method | `GET` |
| Endpoint | `/api/movies` |

**Query 参数**

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `limit` | int | 10 | 返回条数 |
| `offset` | int | 0 | 分页偏移 |

**请求示例**

```
GET http://127.0.0.1:7777/api/movies
GET http://127.0.0.1:7777/api/movies?limit=5&offset=0
```

**返回示例**

```json
[
    {
        "certificate": "A",
        "director_name": "Frank Darabont",
        "gross": 28341469.0,
        "imdb_rating": 9.3,
        "meta_score": 80.0,
        "movie_id": 1,
        "overview": "Two imprisoned men bond over a number of years, finding solace and eventual redemption through acts of common decency.",
        "poster_link": "https://m.media-amazon.com/images/M/MV5BMDFkYTc0MGEtZmNhMC00ZDIzLWFmNTEtODM1ZmRlYWMwMWFmXkEyXkFqcGdeQXVyMTMxODk2OTU@._V1_UX67_CR0,0,67,98_AL_.jpg",
        "runtime": 142,
        "title": "The Shawshank Redemption",
        "votes": 2343110,
        "year": 1994
    }
]
```

---

### 2. 获取指定导演的所有电影

| 项目 | 内容 |
|------|------|
| Method | `GET` |
| Endpoint | `/api/movies/director/<id>` |

**路径参数**

| 参数 | 类型 | 说明 |
|------|------|------|
| `id` | int | 导演的 `director_id` |

**请求示例**

```
GET http://127.0.0.1:7777/api/movies/director/1
```

**返回示例**

```json
{
    "director": {
        "director_id": 1,
        "director_name": "Frank Darabont"
    },
    "movies": [
        {
            "certificate": "A",
            "gross": 28341469.0,
            "imdb_rating": 9.3,
            "meta_score": 80.0,
            "movie_id": 1,
            "overview": "Two imprisoned men bond over a number of years, finding solace and eventual redemption through acts of common decency.",
            "poster_link": "https://m.media-amazon.com/images/M/MV5BMDFkYTc0MGEtZmNhMC00ZDIzLWFmNTEtODM1ZmRlYWMwMWFmXkEyXkFqcGdeQXVyMTMxODk2OTU@._V1_UX67_CR0,0,67,98_AL_.jpg",
            "runtime": 142,
            "title": "The Shawshank Redemption",
            "votes": 2343110,
            "year": 1994
        },
        {
            "certificate": "A",
            "gross": 136801374.0,
            "imdb_rating": 8.6,
            "meta_score": 61.0,
            "movie_id": 26,
            "overview": "The lives of guards on Death Row are affected by one of their charges: a black man accused of child murder and rape, yet who has a mysterious gift.",
            "poster_link": "https://m.media-amazon.com/images/M/MV5BMTUxMzQyNjA5MF5BMl5BanBnXkFtZTYwOTU2NTY3._V1_UX67_CR0,0,67,98_AL_.jpg",
            "runtime": 189,
            "title": "The Green Mile",
            "votes": 1147794,
            "year": 1999
        }
    ],
    "total": 2
}
```

**错误响应（导演不存在）**

```json
{ "error": "导演 ID 999 不存在" }
```

HTTP 状态码：`404`

---

### 3. 统计各类型电影数量

| 项目 | 内容 |
|------|------|
| Method | `GET` |
| Endpoint | `/api/stats/genres` |

无参数。Genre 在建表时已拆分为独立表（`Genre` + `Movie_Genre`），直接 JOIN 统计，无需字符串分割。

**请求示例**

```
GET http://127.0.0.1:7777/api/stats/genres
```

**返回示例**

```json
[
    {
        "avg_rating": 7.96,
        "genre": "Drama",
        "genre_id": 1,
        "movie_count": 722
    },
    {
        "avg_rating": 7.9,
        "genre": "Comedy",
        "genre_id": 11,
        "movie_count": 233
    }
]
```

结果按 `movie_count` 降序排列。

---

### 4. 获取评分最高的电影 Top N

| 项目     | 内容              |
|----------|-------------------|
| Method   | `GET`             |
| Endpoint | `/api/movies/top` |

**Query 参数**

| 参数    | 类型 | 默认值 | 说明                  |
|---------|------|--------|-----------------------|
| `top_n` | int  | 10     | 返回条数，范围 1 ~ 100 |

评分相同时按 `votes`（投票数）降序排列。

**请求示例**

```
GET http://127.0.0.1:7777/api/movies/top
GET http://127.0.0.1:7777/api/movies/top?top_n=5
```

**返回示例**

```json
[
    {
        "certificate": "A",
        "director_name": "Frank Darabont",
        "gross": 28341469.0,
        "imdb_rating": 9.3,
        "movie_id": 1,
        "overview": "Two imprisoned men bond over a number of years, finding solace and eventual redemption through acts of common decency.",
        "poster_link": "https://m.media-amazon.com/images/M/MV5BMDFkYTc0MGEtZmNhMC00ZDIzLWFmNTEtODM1ZmRlYWMwMWFmXkEyXkFqcGdeQXVyMTMxODk2OTU@._V1_UX67_CR0,0,67,98_AL_.jpg",
        "runtime": 142,
        "title": "The Shawshank Redemption",
        "votes": 2343110,
        "year": 1994
    }
]
```

**错误响应**

```json
{ "error": "top_n 范围为 1 ~ 100" }
```

HTTP 状态码：`400`

---

### 5. 按类型统计平均评分

| 项目     | 内容                       |
|----------|----------------------------|
| Method   | `GET`                      |
| Endpoint | `/api/stats/genres/rating` |

无参数。联结 `Genre`、`Movie_Genre`、`Movie` 三表，计算每个类型的平均 `imdb_rating` 及电影总数，结果按平均分降序排列。

**请求示例**

```
GET http://127.0.0.1:7777/api/stats/genres/rating
```

**返回示例**

```json
[
    {
        "avg_rating": 8.01,
        "genre": "War",
        "genre_id": 15,
        "movie_count": 51
    },
    {
        "avg_rating": 8.0,
        "genre": "Western",
        "genre_id": 9,
        "movie_count": 20
    }
]
```

结果按 `avg_rating` 降序排列。

---

### 6. 根据演员 ID 查询参演电影

| 项目     | 内容                          |
|----------|-------------------------------|
| Method   | `GET`                         |
| Endpoint | `/api/stats/actors/<actor_id>` |

**路径参数**

| 参数       | 类型 | 说明          |
|------------|------|---------------|
| `actor_id` | int  | 演员的 `actor_id` |

返回该演员的基本信息、参演电影总数、平均评分，以及完整的参演电影列表（含导演名），按 `imdb_rating` 降序排列。

**请求示例**

```
GET http://127.0.0.1:7777/api/stats/actors/12
```

**返回示例**

```json
{
    "actor": {
        "actor_id": 12,
        "actor_name": "Clint Eastwood"
    },
    "avg_rating": 7.96,
    "movie_count": 12,
    "movies": [
        {
            "certificate": "A",
            "director_name": "Sergio Leone",
            "gross": 6100000.0,
            "imdb_rating": 8.8,
            "movie_id": 13,
            "overview": "A bounty hunting scam joins two men in an uneasy alliance against a third in a race to find a fortune in gold buried in a remote cemetery.",
            "poster_link": "https://m.media-amazon.com/images/M/MV5BOTQ5NDI3MTI4MF5BMl5BanBnXkFtZTgwNDQ4ODE5MDE@._V1_UX67_CR0,0,67,98_AL_.jpg",
            "runtime": 161,
            "title": "Il buono, il brutto, il cattivo",
            "votes": 688390,
            "year": 1966
        },
        {
            "certificate": "U",
            "director_name": "Sergio Leone",
            "gross": 15000000.0,
            "imdb_rating": 8.3,
            "movie_id": 116,
            "overview": "Two bounty hunters with the same intentions team up to track down a Western outlaw.",
            "poster_link": "https://m.media-amazon.com/images/M/MV5BNWM1NmYyM2ItMTFhNy00NDU0LThlYWUtYjQyYTJmOTY0ZmM0XkEyXkFqcGdeQXVyNjU0OTQ0OTY@._V1_UX67_CR0,0,67,98_AL_.jpg",
            "runtime": 132,
            "title": "Per qualche dollaro in più",
            "votes": 232772,
            "year": 1965
        }
  ]
}
```

**错误响应（演员不存在）**

```json
{ "error": "演员 ID 999 不存在" }
```

HTTP 状态码：`404`

所有错误统一返回以下结构：

```json
{ "error": "错误描述" }
```

| 状态码 | 含义                              |
|--------|-----------------------------------|
| 400    | 请求参数错误（如 limit 传了非整数） |
| 404    | 资源不存在（如导演 ID 不存在）      |