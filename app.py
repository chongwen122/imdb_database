import sqlite3
from flask import Flask, g, jsonify, abort, request
from flask_cors import CORS
from llm_service import LLMQueryService, LLMServiceError, SQLValidationError

app = Flask(__name__)
CORS(app)

DB_PATH = 'movies.db'
llm_query_service = LLMQueryService(db_path=DB_PATH)


def get_db():
    """获取当前请求的数据库连接"""
    if 'db' not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(exc):
    """请求结束时关闭连接"""
    db = g.pop('db', None)
    if db is not None:
        db.close()


def rows_to_list(rows):
    """将 sqlite3.Row 列表转为普通 dict 列表"""
    return [dict(row) for row in rows]


# ==================== 新增接口 ====================

@app.get('/api/movies/<int:movie_id>')
def get_movie_detail(movie_id):
    """
    GET /api/movies/<id>
    获取单部电影完整详情，包含演员列表和类型列表
    """
    db = get_db()

    # 获取电影基本信息和导演名
    movie = db.execute('''
        SELECT m.*, d.director_name
        FROM Movie m
        JOIN Director d ON m.director_id = d.director_id
        WHERE m.movie_id = ?
    ''', (movie_id,)).fetchone()

    if movie is None:
        abort(404, description=f'电影 ID {movie_id} 不存在')

    # 获取演员列表
    actors = db.execute('''
        SELECT a.actor_id, a.actor_name
        FROM Actor a
        JOIN Movie_Actor ma ON a.actor_id = ma.actor_id
        WHERE ma.movie_id = ?
        ORDER BY a.actor_name
    ''', (movie_id,)).fetchall()

    # 获取类型列表
    genres = db.execute('''
        SELECT g.genre_id, g.genre
        FROM Genre g
        JOIN Movie_Genre mg ON g.genre_id = mg.genre_id
        WHERE mg.movie_id = ?
        ORDER BY g.genre
    ''', (movie_id,)).fetchall()

    result = dict(movie)
    result['actors'] = rows_to_list(actors)
    result['genres'] = rows_to_list(genres)
    return jsonify(result)


@app.get('/api/movies/genre/<string:genre>')
def get_movies_by_genre(genre):
    """
    GET /api/movies/genre/<genre>
    按类型筛选电影列表
    """
    db = get_db()

    # 验证类型是否存在
    genre_row = db.execute(
        'SELECT genre_id FROM Genre WHERE genre = ?', (genre,)
    ).fetchone()
    if genre_row is None:
        abort(404, description=f'类型 "{genre}" 不存在')

    rows = db.execute('''
        SELECT m.movie_id, m.title, m.year, m.imdb_rating,
               m.votes, m.runtime, m.certificate,
               m.gross, m.overview, m.poster_link,
               d.director_name
        FROM Movie m
        JOIN Director d ON m.director_id = d.director_id
        JOIN Movie_Genre mg ON m.movie_id = mg.movie_id
        WHERE mg.genre_id = ?
        ORDER BY m.imdb_rating DESC
    ''', (genre_row['genre_id'],)).fetchall()

    return jsonify(rows_to_list(rows))


# ==================== 原有接口（保持不变） ====================

@app.get('/api/movies')
def get_movies():
    """
    GET /api/movies
    返回评分最高的电影列表。
    Query params:
      - limit  (int, default=10): 返回条数
      - offset (int, default=0):  分页偏移
    """
    try:
        limit = int(request.args.get('limit', 10))
        offset = int(request.args.get('offset', 0))
    except ValueError:
        abort(400, description='limit 和 offset 必须为整数')

    db = get_db()
    rows = db.execute(
        """
        SELECT m.movie_id, m.title, m.year, m.imdb_rating,
               m.meta_score, m.votes, m.gross, m.runtime,
               m.certificate, m.overview, m.poster_link,
               d.director_name
        FROM Movie m
        JOIN Director d ON m.director_id = d.director_id
        ORDER BY m.imdb_rating DESC
        LIMIT ? OFFSET ?
        """,
        (limit, offset)
    ).fetchall()

    return jsonify(rows_to_list(rows))


@app.get('/api/movies/director/<int:director_id>')
def get_movies_by_director(director_id):
    """
    GET /api/movies/director/<id>
    返回指定导演 ID 的所有电影，按评分降序。
    """
    db = get_db()

    director = db.execute(
        'SELECT * FROM Director WHERE director_id = ?', (director_id,)
    ).fetchone()

    if director is None:
        abort(404, description=f'导演 ID {director_id} 不存在')

    movies = db.execute(
        """
        SELECT m.movie_id, m.title, m.year, m.imdb_rating,
               m.meta_score, m.votes, m.gross, m.runtime,
               m.certificate, m.overview, m.poster_link
        FROM Movie m
        WHERE m.director_id = ?
        ORDER BY m.imdb_rating DESC
        """,
        (director_id,)
    ).fetchall()

    return jsonify({
        'director': dict(director),
        'movies': rows_to_list(movies),
        'total': len(movies)
    })


@app.get('/api/stats/genres')
def get_genre_stats():
    """
    GET /api/stats/genres
    统计各类型电影数量及平均评分，按电影数量降序。
    """
    db = get_db()
    rows = db.execute(
        """
        SELECT g.genre_id, g.genre,
               COUNT(mg.movie_id) AS movie_count,
               ROUND(AVG(m.imdb_rating), 2) AS avg_rating
        FROM Genre g
        LEFT JOIN Movie_Genre mg ON g.genre_id = mg.genre_id
        LEFT JOIN Movie m ON mg.movie_id = m.movie_id
        GROUP BY g.genre_id, g.genre
        ORDER BY movie_count DESC
        """
    ).fetchall()

    return jsonify(rows_to_list(rows))


@app.get('/api/movies/top')
def get_top_movies():
    """
    GET /api/movies/top
    获取评分最高的电影，评分相同时按投票数降序。
    Query params:
      - top_n (int, default=10, max=100): 返回条数
    """
    try:
        top_n = int(request.args.get('top_n', 10))
    except ValueError:
        abort(400, description='top_n 必须为整数')
    if top_n < 1 or top_n > 100:
        abort(400, description='top_n 范围为 1 ~ 100')

    db = get_db()
    rows = db.execute(
        """
        SELECT m.movie_id, m.title, m.year, m.imdb_rating,
               m.votes, m.runtime, m.certificate,
               m.gross, m.overview, m.poster_link,
               d.director_name
        FROM Movie m
        JOIN Director d ON m.director_id = d.director_id
        ORDER BY m.imdb_rating DESC, m.votes DESC
        LIMIT ?
        """,
        (top_n,)
    ).fetchall()

    return jsonify(rows_to_list(rows))


@app.get('/api/stats/genres/rating')
def get_genre_avg_rating():
    """
    GET /api/stats/genres/rating
    按类型统计平均评分及电影总数，结果按平均分降序。
    """
    db = get_db()
    rows = db.execute(
        """
        SELECT g.genre_id, g.genre,
               COUNT(mg.movie_id) AS movie_count,
               ROUND(AVG(m.imdb_rating), 2) AS avg_rating
        FROM Genre g
        JOIN Movie_Genre mg ON g.genre_id = mg.genre_id
        JOIN Movie m ON mg.movie_id = m.movie_id
        GROUP BY g.genre_id, g.genre
        ORDER BY avg_rating DESC
        """
    ).fetchall()

    return jsonify(rows_to_list(rows))


@app.get('/api/stats/actors/<int:actor_id>')
def get_actor_movies(actor_id):
    """
    GET /api/stats/actors/<actor_id>
    根据演员 ID 查询该演员的参演信息及所有电影列表，按评分降序。
    """
    db = get_db()

    actor = db.execute(
        'SELECT * FROM Actor WHERE actor_id = ?', (actor_id,)
    ).fetchone()

    if actor is None:
        abort(404, description=f'演员 ID {actor_id} 不存在')

    movies = db.execute(
        """
        SELECT m.movie_id, m.title, m.year, m.imdb_rating,
               m.votes, m.runtime, m.certificate,
               m.gross, m.overview, m.poster_link,
               d.director_name
        FROM Movie m
        JOIN Movie_Actor ma ON m.movie_id = ma.movie_id
        JOIN Director d ON m.director_id = d.director_id
        WHERE ma.actor_id = ?
        ORDER BY m.imdb_rating DESC
        """,
        (actor_id,)
    ).fetchall()

    return jsonify({
        'actor': dict(actor),
        'movie_count': len(movies),
        'avg_rating': round(
            sum(r['imdb_rating'] for r in movies) / len(movies), 2
        ) if movies else None,
        'movies': rows_to_list(movies)
    })


@app.post('/api/query/nl')
def query_natural_language():
    """
    POST /api/query/nl
    Body:
      {
        "query": "top 5 sci-fi movies after 2010",
        "strategy": "constrained"  # optional: zero-shot|few-shot|constrained
      }
    """
    data = request.get_json(silent=True) or {}
    query = (data.get('query') or '').strip()
    strategy = (data.get('strategy') or 'constrained').strip()

    if not query:
        abort(400, description='query is required')

    try:
        result = llm_query_service.generate_nl2sql(query=query, strategy=strategy)
        return jsonify(result)
    except (LLMServiceError, SQLValidationError) as e:
        return jsonify({
            'error': str(e),
            'query': query,
            'strategy': strategy,
            'results': [],
            'result_count': 0,
        }), 400


@app.post('/api/recommend/nl')
def recommend_natural_language():
    """
    POST /api/recommend/nl
    Body:
      {
        "query": "Recommend emotional drama movies",
        "strategy": "constrained"  # optional: zero-shot|few-shot|constrained
      }
    """
    data = request.get_json(silent=True) or {}
    query = (data.get('query') or '').strip()
    strategy = (data.get('strategy') or 'constrained').strip()

    if not query:
        abort(400, description='query is required')

    try:
        result = llm_query_service.generate_recommendations(query=query, strategy=strategy)
        return jsonify(result)
    except (LLMServiceError, SQLValidationError) as e:
        return jsonify({
            'error': str(e),
            'query': query,
            'strategy': strategy,
            'results': [],
            'result_count': 0,
        }), 400


# 错误处理
@app.errorhandler(400)
@app.errorhandler(404)
def handle_error(e):
    return jsonify({'error': e.description}), e.code


if __name__ == '__main__':
    app.run(debug=True, port=7777)