import os
import re
import time
import hashlib
import sqlite3
import json
import requests

from pathlib import Path
from threading import Lock
from datetime import timedelta
from functools import wraps

from flask import (
    Flask, render_template, jsonify, request, url_for,
    session as flask_session
)
from dotenv import load_dotenv
from werkzeug.security import generate_password_hash, check_password_hash


# ==================================================
# 1. CONFIGURATION
# ==================================================

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "cinemate-development-key")

app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.getenv("COOKIE_SECURE", "False").lower() == "true",
    PERMANENT_SESSION_LIFETIME=timedelta(days=7)
)

OMDB_API_KEY = os.getenv("OMDB_API_KEY", "").strip()
TRAKT_CLIENT_ID = os.getenv("TRAKT_CLIENT_ID", "").strip()

TRAKT_BASE_URL = "https://api.trakt.tv"
OMDB_BASE_URL = "https://www.omdbapi.com/"

MAX_RESULTS = 50
MAX_RECOMMENDATIONS = 12
CACHE_SECONDS = 3600

POSTER_FOLDER = Path(app.static_folder) / "posters"
POSTER_FOLDER.mkdir(parents=True, exist_ok=True)

http = requests.Session()
http.headers.update({"User-Agent": "CineMate/1.0"})


# ==================================================
# 2. SQLITE DATABASE
# ==================================================

DATABASE_FOLDER = Path(app.instance_path)
DATABASE_FOLDER.mkdir(parents=True, exist_ok=True)
DATABASE_PATH = DATABASE_FOLDER / "cinemate.db"


def get_db_connection():
    connection = sqlite3.connect(str(DATABASE_PATH), timeout=30)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout = 30000")
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def initialize_database():
    for attempt in range(5):
        connection = None
        try:
            connection = get_db_connection()

            connection.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    email TEXT NOT NULL UNIQUE,
                    password TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            connection.execute("""
                CREATE TABLE IF NOT EXISTS watchlist (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    imdb_id TEXT NOT NULL,
                    movie_data TEXT NOT NULL,
                    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
                    UNIQUE(user_id, imdb_id)
                )
            """)

            connection.execute("""
                CREATE TABLE IF NOT EXISTS reviews (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    imdb_id TEXT NOT NULL,
                    movie_title TEXT NOT NULL,
                    rating INTEGER NOT NULL CHECK(rating BETWEEN 1 AND 10),
                    review TEXT DEFAULT '',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
                    UNIQUE(user_id, imdb_id)
                )
            """)

            connection.execute("""
                CREATE TABLE IF NOT EXISTS watched_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    imdb_id TEXT NOT NULL,
                    movie_data TEXT NOT NULL,
                    watched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
                    UNIQUE(user_id, imdb_id)
                )
            """)

            connection.execute("""
                CREATE TABLE IF NOT EXISTS recommendation_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    preferences_json TEXT NOT NULL,
                    recommendations_json TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
                )
            """)

            indexes = [
                ("idx_watchlist_user_id", "watchlist(user_id)"),
                ("idx_reviews_user_id", "reviews(user_id)"),
                ("idx_reviews_imdb_id", "reviews(imdb_id)"),
                ("idx_watched_user_id", "watched_history(user_id)"),
                ("idx_recommendation_user_id", "recommendation_history(user_id)")
            ]
            for index_name, columns in indexes:
                connection.execute(
                    f"CREATE INDEX IF NOT EXISTS {index_name} ON {columns}"
                )

            connection.commit()
            print("Database initialized successfully.")
            return

        except sqlite3.OperationalError as error:
            if connection:
                connection.rollback()
            if "locked" in str(error).lower() and attempt < 4:
                print(f"Database busy. Retrying {attempt + 1}/5...")
                time.sleep(2)
                continue
            print("Database initialization error:", error)
            raise
        finally:
            if connection:
                connection.close()


initialize_database()


# ==================================================
# 3. HELPERS
# ==================================================

def login_required(function):
    @wraps(function)
    def wrapper(*args, **kwargs):
        if not flask_session.get("user_id"):
            return jsonify({
                "status": "error",
                "error": "Please login to continue."
            }), 401
        return function(*args, **kwargs)
    return wrapper


_cache = {}
_cache_lock = Lock()


def cache_get(key):
    with _cache_lock:
        item = _cache.get(key)
        if not item:
            return None
        value, expiry = item
        if time.time() > expiry:
            del _cache[key]
            return None
        return value


def cache_set(key, value):
    with _cache_lock:
        _cache[key] = (value, time.time() + CACHE_SECONDS)


def safe_json(value, fallback):
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return fallback


def valid_imdb_id(value):
    value = str(value or "").strip()
    return bool(re.fullmatch(r"tt\d{5,12}", value))


def json_error(message, status=400):
    return jsonify({"status": "error", "error": message}), status


# ==================================================
# 4. AUTHENTICATION
# ==================================================

@app.route("/api/auth/register", methods=["POST"])
def register():
    data = request.get_json(silent=True) or {}
    name = str(data.get("name", "")).strip()
    email = str(data.get("email", "")).strip().lower()
    password = str(data.get("password", ""))

    if not name or len(name) > 80:
        return json_error("Name is required and must be under 80 characters.")
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email) or len(email) > 254:
        return json_error("Please enter a valid email address.")
    if not 8 <= len(password) <= 128:
        return json_error("Password must contain 8 to 128 characters.")

    connection = get_db_connection()
    try:
        cursor = connection.execute("""
            INSERT INTO users (name, email, password)
            VALUES (?, ?, ?)
        """, (name, email, generate_password_hash(password)))
        connection.commit()

        flask_session.clear()
        flask_session["user_id"] = cursor.lastrowid
        flask_session["user_name"] = name
        flask_session["user_email"] = email
        flask_session.permanent = True

        return jsonify({
            "status": "success",
            "message": "Account created successfully.",
            "user": {"id": cursor.lastrowid, "name": name, "email": email}
        }), 201
    except sqlite3.IntegrityError:
        return json_error("An account with this email already exists.", 409)
    except sqlite3.Error as error:
        print("Registration error:", error)
        return json_error("Unable to create your account.", 500)
    finally:
        connection.close()


@app.route("/api/auth/login", methods=["POST"])
def login():
    data = request.get_json(silent=True) or {}
    email = str(data.get("email", "")).strip().lower()
    password = str(data.get("password", ""))

    if not email or not password:
        return json_error("Email and password are required.")

    connection = get_db_connection()
    try:
        user = connection.execute("""
            SELECT id, name, email, password
            FROM users WHERE email = ?
        """, (email,)).fetchone()

        if not user or not check_password_hash(user["password"], password):
            return json_error("Incorrect email or password.", 401)

        flask_session.clear()
        flask_session["user_id"] = user["id"]
        flask_session["user_name"] = user["name"]
        flask_session["user_email"] = user["email"]
        flask_session.permanent = True

        return jsonify({
            "status": "success",
            "message": "Login successful.",
            "user": {"id": user["id"], "name": user["name"], "email": user["email"]}
        })
    finally:
        connection.close()


@app.route("/api/auth/status")
def auth_status():
    user_id = flask_session.get("user_id")
    if not user_id:
        return jsonify({"status": "success", "logged_in": False, "user": None})
    return jsonify({
        "status": "success",
        "logged_in": True,
        "user": {
            "id": user_id,
            "name": flask_session.get("user_name"),
            "email": flask_session.get("user_email")
        }
    })


@app.route("/api/auth/logout", methods=["POST"])
def logout():
    flask_session.clear()
    return jsonify({"status": "success", "message": "Logged out successfully."})


# ==================================================
# 5. PROFILE MANAGEMENT
# ==================================================

@app.route("/api/profile", methods=["GET"])
@login_required
def get_profile():
    connection = get_db_connection()
    try:
        user = connection.execute("""
            SELECT id, name, email, created_at FROM users WHERE id = ?
        """, (flask_session["user_id"],)).fetchone()
        if not user:
            return json_error("User not found.", 404)
        return jsonify({"status": "success", "user": dict(user)})
    finally:
        connection.close()


@app.route("/api/profile", methods=["PUT"])
@login_required
def update_profile():
    data = request.get_json(silent=True) or {}
    name = str(data.get("name", "")).strip()
    email = str(data.get("email", "")).strip().lower()
    current_password = str(data.get("current_password", ""))
    new_password = str(data.get("new_password", ""))

    if not name or len(name) > 80:
        return json_error("Name is required and must be under 80 characters.")
    if len(email) > 254 or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        return json_error("Please enter a valid email address.")
    if not current_password:
        return json_error("Enter your current password to save changes.")
    if new_password and not 8 <= len(new_password) <= 128:
        return json_error("New password must contain 8 to 128 characters.")

    connection = get_db_connection()
    try:
        user = connection.execute(
            "SELECT password FROM users WHERE id = ?",
            (flask_session["user_id"],)
        ).fetchone()

        if not user or not check_password_hash(user["password"], current_password):
            return json_error("Current password is incorrect.", 401)

        password_hash = (
            generate_password_hash(new_password)
            if new_password else user["password"]
        )

        connection.execute("""
            UPDATE users SET name = ?, email = ?, password = ?
            WHERE id = ?
        """, (name, email, password_hash, flask_session["user_id"]))
        connection.commit()

        flask_session["user_name"] = name
        flask_session["user_email"] = email

        return jsonify({
            "status": "success",
            "message": "Profile updated successfully.",
            "user": {
                "id": flask_session["user_id"],
                "name": name,
                "email": email
            }
        })
    except sqlite3.IntegrityError:
        return json_error("That email address is already in use.", 409)
    except sqlite3.Error as error:
        print("Profile update error:", error)
        return json_error("Unable to update profile.", 500)
    finally:
        connection.close()


# ==================================================
# 6. WATCHLIST
# ==================================================

@app.route("/api/watchlist", methods=["GET"])
@login_required
def get_watchlist():
    connection = get_db_connection()
    try:
        rows = connection.execute("""
            SELECT imdb_id, movie_data, added_at
            FROM watchlist WHERE user_id = ?
            ORDER BY added_at DESC, id DESC
        """, (flask_session["user_id"],)).fetchall()

        movies = []
        for row in rows:
            movie = safe_json(row["movie_data"], None)
            if isinstance(movie, dict):
                movie["imdbID"] = row["imdb_id"]
                movie["addedAt"] = row["added_at"]
                movies.append(movie)

        return jsonify({"status": "success", "movies": movies, "total": len(movies)})
    finally:
        connection.close()


@app.route("/api/watchlist", methods=["POST"])
@login_required
def add_to_watchlist():
    data = request.get_json(silent=True) or {}
    movie = data.get("movie", data)
    if not isinstance(movie, dict):
        return json_error("Invalid movie information.")

    imdb_id = str(movie.get("imdbID") or movie.get("imdb_id") or "").strip()
    title = str(movie.get("Title") or movie.get("title") or "").strip()
    if not valid_imdb_id(imdb_id) or not title or len(title) > 300:
        return json_error("Valid movie IMDb ID and title are required.")

    movie_data = dict(movie)
    movie_data.update({"imdbID": imdb_id, "Title": title})

    connection = get_db_connection()
    try:
        cursor = connection.execute("""
            INSERT INTO watchlist (user_id, imdb_id, movie_data)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id, imdb_id) DO NOTHING
        """, (
            flask_session["user_id"], imdb_id,
            json.dumps(movie_data, ensure_ascii=False)
        ))
        connection.commit()
        exists = cursor.rowcount == 0
        return jsonify({
            "status": "success",
            "message": "Movie is already in your watchlist." if exists else "Movie saved to your watchlist.",
            "already_exists": exists
        }), 200 if exists else 201
    except sqlite3.Error as error:
        print("Add watchlist error:", error)
        return json_error("Unable to add movie.", 500)
    finally:
        connection.close()


@app.route("/api/watchlist/<path:imdb_id>", methods=["DELETE"])
@login_required
def remove_from_watchlist(imdb_id):
    connection = get_db_connection()
    try:
        cursor = connection.execute("""
            DELETE FROM watchlist WHERE user_id = ? AND imdb_id = ?
        """, (flask_session["user_id"], imdb_id))
        connection.commit()
        if cursor.rowcount == 0:
            return json_error("Movie was not found in your watchlist.", 404)
        return jsonify({"status": "success", "message": "Movie removed from your watchlist."})
    finally:
        connection.close()


# ==================================================
# 7. WATCHED HISTORY
# ==================================================

@app.route("/api/watched", methods=["GET"])
@login_required
def get_watched_history():
    connection = get_db_connection()
    try:
        rows = connection.execute("""
            SELECT imdb_id, movie_data, watched_at
            FROM watched_history WHERE user_id = ?
            ORDER BY watched_at DESC, id DESC
        """, (flask_session["user_id"],)).fetchall()

        movies = []
        for row in rows:
            movie = safe_json(row["movie_data"], None)
            if isinstance(movie, dict):
                movie["imdbID"] = row["imdb_id"]
                movie["watchedAt"] = row["watched_at"]
                movies.append(movie)
        return jsonify({"status": "success", "movies": movies, "total": len(movies)})
    finally:
        connection.close()


@app.route("/api/watched", methods=["POST"])
@login_required
def add_watched_movie():
    data = request.get_json(silent=True) or {}
    movie = data.get("movie", data)
    if not isinstance(movie, dict):
        return json_error("Invalid movie information.")

    imdb_id = str(movie.get("imdbID") or movie.get("imdb_id") or "").strip()
    title = str(movie.get("Title") or movie.get("title") or "").strip()
    if not valid_imdb_id(imdb_id) or not title or len(title) > 300:
        return json_error("Valid movie IMDb ID and title are required.")

    movie_data = dict(movie)
    movie_data.update({"imdbID": imdb_id, "Title": title})

    connection = get_db_connection()
    try:
        connection.execute("""
            INSERT INTO watched_history (user_id, imdb_id, movie_data)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id, imdb_id) DO UPDATE SET
                movie_data = excluded.movie_data,
                watched_at = CURRENT_TIMESTAMP
        """, (
            flask_session["user_id"], imdb_id,
            json.dumps(movie_data, ensure_ascii=False)
        ))
        connection.commit()
        return jsonify({"status": "success", "message": "Movie added to watched history."})
    except sqlite3.Error as error:
        print("Watched history error:", error)
        return json_error("Unable to save watched movie.", 500)
    finally:
        connection.close()


@app.route("/api/watched/<imdb_id>", methods=["DELETE"])
@login_required
def remove_watched_movie(imdb_id):
    connection = get_db_connection()
    try:
        cursor = connection.execute("""
            DELETE FROM watched_history WHERE user_id = ? AND imdb_id = ?
        """, (flask_session["user_id"], imdb_id))
        connection.commit()
        if cursor.rowcount == 0:
            return json_error("Movie was not found in watched history.", 404)
        return jsonify({"status": "success", "message": "Movie removed from watched history."})
    finally:
        connection.close()


# ==================================================
# 8. REVIEWS AND RATINGS
# ==================================================

@app.route("/api/reviews/<imdb_id>", methods=["GET"])
def get_movie_reviews(imdb_id):
    if not valid_imdb_id(imdb_id):
        return json_error("Invalid IMDb ID.")

    connection = get_db_connection()
    try:
        rows = connection.execute("""
            SELECT r.id, r.imdb_id, r.movie_title, r.rating, r.review,
                   r.created_at, r.updated_at, u.name AS user_name
            FROM reviews r
            JOIN users u ON u.id = r.user_id
            WHERE r.imdb_id = ?
            ORDER BY r.updated_at DESC
        """, (imdb_id,)).fetchall()

        reviews = [dict(row) for row in rows]
        average = round(sum(r["rating"] for r in reviews) / len(reviews), 1) if reviews else 0
        return jsonify({
            "status": "success",
            "reviews": reviews,
            "total": len(reviews),
            "average_rating": average
        })
    finally:
        connection.close()


@app.route("/api/reviews", methods=["POST"])
@login_required
def save_movie_review():
    data = request.get_json(silent=True) or {}
    imdb_id = str(data.get("imdb_id", "")).strip()
    title = str(data.get("movie_title", "")).strip()
    review = str(data.get("review", "")).strip()

    try:
        rating = int(data.get("rating"))
    except (TypeError, ValueError):
        rating = 0

    if not valid_imdb_id(imdb_id):
        return json_error("A valid IMDb ID is required.")
    if not title or len(title) > 300:
        return json_error("A valid movie title is required.")
    if not 1 <= rating <= 10:
        return json_error("Rating must be between 1 and 10.")
    if len(review) > 2000:
        return json_error("Review must be 2000 characters or fewer.")

    connection = get_db_connection()
    try:
        connection.execute("""
            INSERT INTO reviews (user_id, imdb_id, movie_title, rating, review)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(user_id, imdb_id) DO UPDATE SET
                movie_title = excluded.movie_title,
                rating = excluded.rating,
                review = excluded.review,
                updated_at = CURRENT_TIMESTAMP
        """, (flask_session["user_id"], imdb_id, title, rating, review))
        connection.commit()
        return jsonify({"status": "success", "message": "Your review has been saved."})
    except sqlite3.Error as error:
        print("Review save error:", error)
        return json_error("Unable to save your review.", 500)
    finally:
        connection.close()


@app.route("/api/reviews/<imdb_id>", methods=["DELETE"])
@login_required
def delete_movie_review(imdb_id):
    connection = get_db_connection()
    try:
        cursor = connection.execute("""
            DELETE FROM reviews WHERE user_id = ? AND imdb_id = ?
        """, (flask_session["user_id"], imdb_id))
        connection.commit()
        if cursor.rowcount == 0:
            return json_error("Your review was not found.", 404)
        return jsonify({"status": "success", "message": "Your review was deleted."})
    finally:
        connection.close()


# ==================================================
# 9. RECOMMENDATION HISTORY
# ==================================================

@app.route("/api/recommendation-history", methods=["GET"])
@login_required
def get_recommendation_history():
    connection = get_db_connection()
    try:
        rows = connection.execute("""
            SELECT id, preferences_json, recommendations_json, created_at
            FROM recommendation_history
            WHERE user_id = ?
            ORDER BY created_at DESC, id DESC
            LIMIT 50
        """, (flask_session["user_id"],)).fetchall()

        history = []
        for row in rows:
            history.append({
                "id": row["id"],
                "preferences": safe_json(row["preferences_json"], {}),
                "recommendations": safe_json(row["recommendations_json"], []),
                "created_at": row["created_at"]
            })
        return jsonify({"status": "success", "history": history, "total": len(history)})
    finally:
        connection.close()


@app.route("/api/recommendation-history", methods=["POST"])
@login_required
def save_recommendation_history():
    data = request.get_json(silent=True) or {}
    preferences = data.get("preferences", {})
    movies = data.get("recommendations", [])

    if not isinstance(preferences, dict) or not isinstance(movies, list):
        return json_error("Invalid recommendation history data.")
    if len(movies) > 50:
        return json_error("A history entry can contain at most 50 movies.")

    try:
        preferences_json = json.dumps(preferences, ensure_ascii=False)
        movies_json = json.dumps(movies, ensure_ascii=False)
        if len(preferences_json) + len(movies_json) > 1_000_000:
            return json_error("Recommendation history entry is too large.", 413)
    except (TypeError, ValueError):
        return json_error("Invalid recommendation information.")

    connection = get_db_connection()
    try:
        cursor = connection.execute("""
            INSERT INTO recommendation_history
                (user_id, preferences_json, recommendations_json)
            VALUES (?, ?, ?)
        """, (flask_session["user_id"], preferences_json, movies_json))
        connection.commit()
        return jsonify({
            "status": "success",
            "message": "Recommendation history saved.",
            "id": cursor.lastrowid
        }), 201
    finally:
        connection.close()


@app.route("/api/recommendation-history/<int:history_id>", methods=["DELETE"])
@login_required
def delete_recommendation_history(history_id):
    connection = get_db_connection()
    try:
        cursor = connection.execute("""
            DELETE FROM recommendation_history
            WHERE id = ? AND user_id = ?
        """, (history_id, flask_session["user_id"]))
        connection.commit()
        if cursor.rowcount == 0:
            return json_error("Recommendation history entry not found.", 404)
        return jsonify({"status": "success", "message": "History entry deleted."})
    finally:
        connection.close()


@app.route("/api/recommendation-history", methods=["DELETE"])
@login_required
def clear_recommendation_history():
    connection = get_db_connection()
    try:
        connection.execute(
            "DELETE FROM recommendation_history WHERE user_id = ?",
            (flask_session["user_id"],)
        )
        connection.commit()
        return jsonify({"status": "success", "message": "Recommendation history cleared."})
    finally:
        connection.close()


# ==================================================
# 10. LANGUAGE AND GENRE MAPPINGS
# ==================================================

LANGUAGE_CODES = {
    "english": "en", "hindi": "hi", "bengali": "bn",
    "japanese": "ja", "korean": "ko", "french": "fr",
    "spanish": "es", "tamil": "ta", "telugu": "te",
    "malayalam": "ml", "kannada": "kn", "chinese": "zh",
    "german": "de", "italian": "it", "portuguese": "pt",
    "russian": "ru", "thai": "th", "turkish": "tr", "arabic": "ar"
}
LANGUAGE_NAMES = {code: name.title() for name, code in LANGUAGE_CODES.items()}

GENRE_SLUGS = {
    "action": "action", "adventure": "adventure", "animation": "animation",
    "comedy": "comedy", "crime": "crime", "drama": "drama",
    "fantasy": "fantasy", "horror": "horror", "mystery": "mystery",
    "romance": "romance", "sci-fi": "science-fiction",
    "science fiction": "science-fiction", "science-fiction": "science-fiction",
    "thriller": "thriller", "war": "war", "western": "western",
    "documentary": "documentary", "history": "history", "music": "music",
    "family": "family"
}


def clean_language(language):
    if not language:
        return None
    value = str(language).strip().lower()
    if value in ("all", "any", "all languages", ""):
        return None
    return LANGUAGE_CODES.get(value, value)


def clean_genres(genres):
    if not genres:
        return []
    if isinstance(genres, str):
        genres = [genres]
    result = []
    for genre in genres:
        slug = GENRE_SLUGS.get(str(genre).strip().lower())
        if slug and slug not in result:
            result.append(slug)
    return result


def display_genres(genres):
    if not genres:
        return "N/A"
    return ", ".join(str(g).replace("-", " ").title() for g in genres)


def display_languages(languages):
    if not languages:
        return "N/A"
    return ", ".join(
        LANGUAGE_NAMES.get(str(code).lower(), str(code).upper())
        for code in languages
    )


# ==================================================
# 11. POSTER CACHE AND API HELPERS
# ==================================================

def cache_poster_image(image_url):
    if not image_url or image_url == "N/A":
        return ""

    image_url = str(image_url).strip()
    if image_url.startswith("//"):
        image_url = "https:" + image_url
    elif image_url.startswith(("walter-r2.trakt.tv/", "media.trakt.tv/")):
        image_url = "https://" + image_url

    if not image_url.startswith(("https://", "http://")):
        return ""

    cache_key = hashlib.md5(image_url.encode("utf-8")).hexdigest()
    cached = cache_get(("poster", cache_key))
    if cached:
        return cached

    try:
        response = http.get(image_url, timeout=15)
        response.raise_for_status()
        content_type = response.headers.get("Content-Type", "").lower()
        if "image" not in content_type:
            return ""

        extension = ".jpg"
        if "webp" in content_type:
            extension = ".webp"
        elif "png" in content_type:
            extension = ".png"
        elif "gif" in content_type:
            extension = ".gif"

        filename = cache_key + extension
        file_path = POSTER_FOLDER / filename
        if not file_path.exists():
            file_path.write_bytes(response.content)

        local_url = url_for("static", filename=f"posters/{filename}")
        cache_set(("poster", cache_key), local_url)
        return local_url
    except requests.RequestException as error:
        print("Poster download failed:", error)
        return ""


def trakt_request(endpoint, params=None):
    if not TRAKT_CLIENT_ID:
        print("ERROR: TRAKT_CLIENT_ID missing in .env")
        return None

    params = params or {}
    cache_key = ("trakt", endpoint, tuple(sorted(params.items())))
    cached = cache_get(cache_key)
    if cached is not None:
        return cached

    headers = {
        "Content-Type": "application/json",
        "trakt-api-version": "2",
        "trakt-api-key": TRAKT_CLIENT_ID
    }

    try:
        response = http.get(
            f"{TRAKT_BASE_URL}/{endpoint.lstrip('/')}",
            headers=headers, params=params, timeout=20
        )
        if response.status_code == 200:
            data = response.json()
            cache_set(cache_key, data)
            return data
        print("Trakt API error:", response.status_code, response.text[:300])
        return None
    except requests.RequestException as error:
        print("Trakt connection error:", error)
        return None


def omdb_request(params):
    if not OMDB_API_KEY:
        return {}

    params = dict(params)
    params["apikey"] = OMDB_API_KEY
    cache_key = ("omdb", tuple(sorted(params.items())))
    cached = cache_get(cache_key)
    if cached is not None:
        return cached

    try:
        response = http.get(OMDB_BASE_URL, params=params, timeout=15)
        response.raise_for_status()
        data = response.json()
        if data.get("Response") == "True":
            cache_set(cache_key, data)
            return data
        return {}
    except requests.RequestException as error:
        print("OMDb connection error:", error)
        return {}


def get_omdb_poster(imdb_id):
    details = omdb_request({"i": imdb_id, "plot": "short"}) if imdb_id else {}
    poster = details.get("Poster", "")
    return cache_poster_image(poster) if poster and poster != "N/A" else ""


# ==================================================
# 12. MOVIE NORMALIZATION AND FILTERS
# ==================================================

def normalize_movie(item):
    if not isinstance(item, dict):
        return None

    trakt_movie = item.get("movie", item)
    if not isinstance(trakt_movie, dict):
        return None

    ids = trakt_movie.get("ids") or {}
    title = trakt_movie.get("title")
    if not title:
        return None

    imdb_id = ids.get("imdb", "")
    genres = trakt_movie.get("genres") or []
    languages = trakt_movie.get("languages") or []
    primary_language = trakt_movie.get("language")

    if primary_language and primary_language not in languages:
        languages.insert(0, primary_language)

    rating = trakt_movie.get("rating")
    rating = str(round(float(rating), 1)) if rating is not None else "N/A"

    images = trakt_movie.get("images") or {}
    poster_images = (images.get("poster") or [])
    poster_url = cache_poster_image(poster_images[0]) if poster_images else ""

    if not poster_url and imdb_id:
        poster_url = get_omdb_poster(imdb_id)
    if not poster_url:
        poster_url = "https://placehold.co/300x450/151515/ffffff?text=Poster+Unavailable"

    return {
        "Title": title,
        "Year": str(trakt_movie.get("year") or "N/A"),
        "imdbID": imdb_id,
        "traktID": ids.get("trakt", ""),
        "Type": "movie",
        "Poster": poster_url,
        "Genre": display_genres(genres),
        "Language": display_languages(languages),
        "imdbRating": rating,
        "Plot": trakt_movie.get("overview") or "No description available.",
        "Runtime": f'{trakt_movie.get("runtime")} min' if trakt_movie.get("runtime") else "N/A",
        "Released": trakt_movie.get("released") or "N/A",
        "Director": "N/A",
        "Actors": "N/A",
        "Writer": "N/A",
        "Country": trakt_movie.get("country") or "N/A",
        "trailer": trakt_movie.get("trailer") or "",
        "homepage": trakt_movie.get("homepage") or "",
        "Source": "Trakt"
    }


def enrich_with_omdb(movie):
    if not movie or not movie.get("imdbID"):
        return movie

    details = omdb_request({"i": movie["imdbID"], "plot": "full"})
    if not details:
        return movie

    for field in (
        "Genre", "Language", "imdbRating", "Plot", "Runtime",
        "Released", "Director", "Actors", "Writer", "Country"
    ):
        value = details.get(field)
        if value and value != "N/A":
            movie[field] = value

    poster = details.get("Poster")
    if poster and poster != "N/A":
        local_poster = cache_poster_image(poster)
        if local_poster:
            movie["Poster"] = local_poster

    movie["Source"] = "Trakt + OMDb"
    return movie


def normalized_movie_genres(movie):
    result = set()
    for value in str(movie.get("Genre", "")).split(","):
        slug = GENRE_SLUGS.get(value.strip().lower())
        if slug:
            result.add(slug)
    return result


def movie_matches_filters(movie, selected_genres=None, selected_language=None):
    selected_genres = selected_genres or []
    movie_genres = normalized_movie_genres(movie)

    if selected_genres and not any(g in movie_genres for g in selected_genres):
        return False

    if selected_language:
        language_values = [
            value.strip().lower()
            for value in str(movie.get("Language", "")).split(",")
        ]
        language_name = LANGUAGE_NAMES.get(selected_language, selected_language).lower()
        if selected_language.lower() not in language_values and language_name not in language_values:
            return False

    return True


def fetch_trakt_movies(chart="popular", genres=None, language=None, limit=MAX_RESULTS):
    params = {"extended": "full", "limit": min(max(int(limit), 1), 100)}
    if genres:
        params["genres"] = ",".join(genres)
    if language:
        params["languages"] = language

    data = trakt_request(f"movies/{chart}", params)
    if not isinstance(data, list):
        return []

    return [movie for item in data if (movie := normalize_movie(item))]


def fetch_trakt_search(query, limit=MAX_RESULTS):
    data = trakt_request("search/movie", {
        "query": query,
        "extended": "full",
        "limit": min(max(int(limit), 1), 100)
    })
    if not isinstance(data, list):
        return []
    return [movie for item in data if (movie := normalize_movie(item))]


# ==================================================
# 13. WEBSITE AND CORE API ROUTES
# ==================================================

@app.route("/")
def home():
    return render_template("index.html")


@app.route("/api/health")
def health():
    return jsonify({
        "status": "success",
        "message": "CineMate API is running",
        "trakt_configured": bool(TRAKT_CLIENT_ID),
        "omdb_configured": bool(OMDB_API_KEY),
        "poster_cache": str(POSTER_FOLDER),
        "authentication": "enabled",
        "database": str(DATABASE_PATH),
        "watchlist_database": "enabled",
        "phase_7_features": {
            "reviews": "enabled",
            "watched_history": "enabled",
            "profile_management": "enabled",
            "recommendation_history": "enabled",
            "trending_movies": "enabled",
            "upcoming_movies": "enabled"
        }
    })


@app.route("/api/search")
def search_movies():
    query = request.args.get("q", "").strip()
    if not query:
        return jsonify({"status": "success", "movies": [], "totalResults": 0})

    movies = fetch_trakt_search(query, MAX_RESULTS)
    return jsonify({
        "status": "success",
        "movies": movies,
        "totalResults": len(movies)
    })


@app.route("/api/movie/<imdb_id>")
def movie_details(imdb_id):
    if not valid_imdb_id(imdb_id):
        return json_error("Invalid IMDb ID.")

    details = omdb_request({"i": imdb_id, "plot": "full"})
    if details:
        poster = details.get("Poster", "")
        if poster and poster != "N/A":
            local_poster = cache_poster_image(poster)
            if local_poster:
                details["Poster"] = local_poster
        return jsonify({"status": "success", "movie": details})

    data = trakt_request(f"search/imdb/{imdb_id}", {
        "type": "movie",
        "extended": "full"
    })
    if isinstance(data, list) and data:
        movie = normalize_movie(data[0])
        if movie:
            return jsonify({"status": "success", "movie": movie})

    return json_error("Movie details not found.", 404)


@app.route("/api/discover")
def discover_movies():
    chart_requests = {
        "trending": ("trending", []),
        "popular": ("popular", []),
        "action": ("popular", ["action"]),
        "comedy": ("popular", ["comedy"]),
        "drama": ("popular", ["drama"]),
        "horror": ("popular", ["horror"]),
        "romance": ("popular", ["romance"]),
        "thriller": ("popular", ["thriller"]),
        "science-fiction": ("popular", ["science-fiction"])
    }

    collections = {}
    for name, (chart, genres) in chart_requests.items():
        collections[name] = fetch_trakt_movies(chart, genres, limit=20)

    return jsonify({"status": "success", "collections": collections})


@app.route("/api/movies/trending")
def trending_movies():
    movies = fetch_trakt_movies("trending", limit=30)
    return jsonify({"status": "success", "movies": movies, "total": len(movies)})


@app.route("/api/movies/upcoming")
def upcoming_movies():
    # Trakt anticipated is an anticipation/popularity chart, not a complete
    # release-calendar feed.
    movies = fetch_trakt_movies("anticipated", limit=30)
    return jsonify({"status": "success", "movies": movies, "total": len(movies)})


@app.route("/api/recommendations", methods=["POST"])
def recommendations():
    data = request.get_json(silent=True) or {}
    raw_genres = data.get("genres", [])
    raw_language = data.get("language", "")

    if isinstance(raw_genres, str):
        raw_genres = [raw_genres]

    selected_genres = clean_genres(raw_genres)
    selected_language = clean_language(raw_language)

    watchlist = data.get("watchlist", [])
    if not isinstance(watchlist, list):
        watchlist = []

    movies = fetch_trakt_movies(
        chart="popular",
        genres=selected_genres,
        language=selected_language,
        limit=100
    )

    if len(movies) < MAX_RECOMMENDATIONS:
        trending = fetch_trakt_movies(
            chart="trending",
            genres=selected_genres,
            language=selected_language,
            limit=50
        )
        known_ids = {
            movie.get("imdbID") or movie.get("traktID")
            for movie in movies
        }
        for movie in trending:
            movie_id = movie.get("imdbID") or movie.get("traktID")
            if movie_id and movie_id not in known_ids:
                movies.append(movie)
                known_ids.add(movie_id)

    filtered = [
        movie for movie in movies
        if movie_matches_filters(movie, selected_genres, selected_language)
    ]

    watchlist_ids = set()
    for item in watchlist:
        movie_id = (
            item.get("imdbID") or item.get("id") or item.get("traktID")
            if isinstance(item, dict) else str(item)
        )
        if movie_id:
            watchlist_ids.add(str(movie_id))

    filtered = [
        movie for movie in filtered
        if str(movie.get("imdbID") or movie.get("traktID")) not in watchlist_ids
    ]

    def rating_value(movie):
        try:
            return float(movie.get("imdbRating", 0))
        except (TypeError, ValueError):
            return 0

    filtered.sort(key=rating_value, reverse=True)
    final_movies = [
        enrich_with_omdb(movie)
        for movie in filtered[:MAX_RECOMMENDATIONS]
    ]

    response = {
        "status": "success",
        "recommendations": final_movies,
        "total": len(final_movies),
        "selectedLanguage": raw_language or "All",
        "selectedGenres": raw_genres
    }

    # Automatically retain recommendation sessions for logged-in users.
    if flask_session.get("user_id") and final_movies:
        connection = get_db_connection()
        try:
            connection.execute("""
                INSERT INTO recommendation_history
                    (user_id, preferences_json, recommendations_json)
                VALUES (?, ?, ?)
            """, (
                flask_session["user_id"],
                json.dumps({
                    "genres": raw_genres,
                    "language": raw_language or "All"
                }, ensure_ascii=False),
                json.dumps(final_movies, ensure_ascii=False)
            ))
            connection.commit()
        except sqlite3.Error as error:
            print("Automatic recommendation history save failed:", error)
        finally:
            connection.close()

    return jsonify(response)


# ==================================================
# 14. ERROR HANDLERS
# ==================================================

@app.errorhandler(404)
def page_not_found(error):
    return jsonify({
        "status": "error",
        "error": "Route not found",
        "available_routes": [
            "/", "/api/health",
            "/api/auth/register", "/api/auth/login",
            "/api/auth/status", "/api/auth/logout",
            "/api/profile",
            "/api/watchlist", "/api/watchlist/<imdb_id>",
            "/api/watched", "/api/watched/<imdb_id>",
            "/api/reviews", "/api/reviews/<imdb_id>",
            "/api/recommendation-history",
            "/api/recommendation-history/<history_id>",
            "/api/movies/trending", "/api/movies/upcoming",
            "/api/search?q=batman", "/api/discover",
            "/api/recommendations", "/api/movie/<imdb_id>"
        ]
    }), 404


@app.errorhandler(500)
def internal_server_error(error):
    return jsonify({
        "status": "error",
        "error": "An internal server error occurred."
    }), 500


# ==================================================
# 15. START SERVER
# ==================================================

if __name__ == "__main__":
    print("\n====================================")
    print("          CINEMATE SERVER")
    print("====================================")
    print("OMDb configured:", bool(OMDB_API_KEY))
    print("Trakt configured:", bool(TRAKT_CLIENT_ID))
    print("Authentication: Enabled")
    print("Database:", DATABASE_PATH)
    print("Watchlist database: Enabled")
    print("Phase 7 features: Enabled")
    print("Poster folder:", POSTER_FOLDER)
    print("\nREGISTERED ROUTES:")
    print(app.url_map)
    print("\nWebsite: http://127.0.0.1:5000/")
    print("Health:  http://127.0.0.1:5000/api/health")
    print("====================================\n")

    app.run(
        host="127.0.0.1",
        port=5000,
        debug=True,
        use_reloader=False
    )