import json
import logging
import os

from flask import Flask, jsonify, request
from sentence_transformers import SentenceTransformer

import lakebase
from weather_client import WeatherClient


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("weather-app")

app = Flask(__name__)

WEATHER_TABLE_NAME = os.environ.get(
    "WEATHER_TABLE_NAME",
    "weather_documents",
)

WEATHER_EMBEDDING_TABLE_NAME = os.environ.get(
    "WEATHER_EMBEDDING_TABLE_NAME",
    "weather_embeddings",
)


embedding_model = None

def get_embedding_model():
    global embedding_model
    if embedding_model is None:
        embedding_model = SentenceTransformer(
            "sentence-transformers/all-MiniLM-L6-v2"
        )
    return embedding_model


def weather_search_logic(query, top_k, source_type=None):
    model = get_embedding_model()
    query_embedding = model.encode(query).tolist()
    query_vector = str(query_embedding)
    with lakebase.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT COUNT(*) AS count
                FROM {WEATHER_EMBEDDING_TABLE_NAME}
                """
            )
            count = cur.fetchone()["count"]
            if count == 0:
                return {"results": []}
            if source_type:
                cur.execute(
                    f"""
                    SELECT
                        d.id,
                        d.location,
                        d.headline,
                        d.source_type,
                        e.chunk_text,
                        1 - (e.embedding <=> %s::vector) AS similarity
                    FROM {WEATHER_EMBEDDING_TABLE_NAME} e
                    JOIN {WEATHER_TABLE_NAME} d
                    ON d.id = e.document_id
                    WHERE d.source_type = %s
                    ORDER BY e.embedding <=> %s::vector
                    LIMIT %s
                    """,
                    (
                        query_vector,
                        source_type,
                        query_vector,
                        top_k,
                    ),
                )

            else:
                cur.execute(
                    f"""
                    SELECT
                        d.id,
                        d.location,
                        d.headline,
                        d.source_type,
                        e.chunk_text,
                        1 - (e.embedding <=> %s::vector) AS similarity
                    FROM {WEATHER_EMBEDDING_TABLE_NAME} e
                    JOIN {WEATHER_TABLE_NAME} d
                    ON d.id = e.document_id
                    ORDER BY e.embedding <=> %s::vector
                    LIMIT %s
                    """,
                    (
                        query_vector,
                        query_vector,
                        top_k,
                    ),
                )

            rows = cur.fetchall()

    return {
        "results": [
            {
                "id": row["id"],
                "location": row["location"],
                "headline": row["headline"],
                "source_type": row["source_type"],
                "chunk_text": row["chunk_text"],
                "similarity": float(row["similarity"]),
            }
            for row in rows
        ]
    }


@app.route("/healthz")
def healthz():
    return jsonify(
        {"status": "ok"}
    )


@app.errorhandler(Exception)
def handle_exception(err):
    logger.exception("Unhandled exception")

    return jsonify(
        {"error": str(err)}), 500

@app.route("/weather/sync", methods=["POST"])
def weather_sync():
    body = request.json if request.is_json else {}
    locations = body.get(
        "locations",
        [
            "Chicago, IL",
            "Austin, TX",
            "Miami, FL",
            "Denver, CO",
            "Seattle, WA",
        ],
    )

    try:
        limit = int(body.get("limit", 50))
    except Exception:
        limit = 50

    limit = max(1, min(limit, 500))

    client = WeatherClient()
    documents = []

    for location in locations:
        try:
            docs = client.fetch_locations(
                [location],
                limit=limit,
            )
            documents.extend(docs)
        except Exception:
            logger.exception(
                f"Failed syncing {location}"
            )
    documents = documents[:limit]

    with lakebase.get_connection() as conn:
        with conn.cursor() as cur:

            for doc in documents:
                cur.execute(
                    f"""
                    INSERT INTO {WEATHER_TABLE_NAME}
                    (
                        id,
                        location,
                        source_type,
                        headline,
                        narrative_text,
                        issued_at,
                        payload,
                        synced_at
                    )
                    VALUES
                    (
                        %s,
                        %s,
                        %s,
                        %s,
                        %s,
                        %s,
                        %s,
                        now()
                    )
                    ON CONFLICT(id)
                    DO UPDATE SET
                        narrative_text =
                            EXCLUDED.narrative_text,
                        payload =
                            EXCLUDED.payload,
                        synced_at =
                            EXCLUDED.synced_at
                    """,
                    (
                        doc["id"],
                        doc["location"],
                        doc["source_type"],
                        doc["headline"],
                        doc["narrative_text"],
                        doc["issued_at"],
                        json.dumps(doc["payload"]),
                    ),
                )

        conn.commit()

    return jsonify(
        {
            "synced": len(documents)
        }
    )


@app.route("/weather/search", methods=["POST"])
def weather_search():
    body = request.json if request.is_json else {}

    query = body.get("query")

    if not query or not isinstance(query, str):
        return jsonify(
            {
                "error": "query is required"
            }
        ), 400

    top_k = body.get("top_k", 5)
    source_type = body.get("source_type")

    try:
        top_k = int(top_k)
    except Exception:
        top_k = 5

    top_k = max(1, min(top_k, 20))

    if source_type and source_type not in [
        "alert",
        "forecast",
    ]:
        return jsonify(
            {
                "error": (
                    "source_type must be "
                    "alert or forecast"
                )
            }
        ), 400

    return jsonify(
        weather_search_logic(
            query,
            top_k,
            source_type,
        )
    )


@app.route("/weather/search", methods=["GET"])
def weather_search_get():
    query = request.args.get("query")

    if not query:
        return jsonify(
            {
                "error": "query is required"
            }
        ), 400

    top_k = request.args.get("top_k", 5)
    source_type = request.args.get("source_type")

    try:
        top_k = int(top_k)
    except Exception:
        top_k = 5

    top_k = max(1, min(top_k, 20))

    if source_type and source_type not in [
        "alert",
        "forecast",
    ]:
        return jsonify(
            {
                "error": (
                    "source_type must be "
                    "alert or forecast"
                )
            }
        ), 400

    return jsonify(
        weather_search_logic(
            query,
            top_k,
            source_type,
        )
    )

 if __name__ == '__main__':
    host = os.getenv('FLASK_RUN_HOST', '0.0.0.0')
    port = int(os.getenv('FLASK_RUN_PORT', 8000))
    app.run(debug=True, host=host, port=port)
    print(f"Flask app running on http://{host}:{port}")