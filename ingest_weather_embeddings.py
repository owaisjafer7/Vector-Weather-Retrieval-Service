import logging

from sentence_transformers import SentenceTransformer
from psycopg2.extras import execute_values

import lakebase


logging.basicConfig(level=logging.INFO)

logger = logging.getLogger("weather-embedding")


DOCUMENT_TABLE = "weather_documents"
EMBED_TABLE = "weather_embeddings"

MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"

CHUNK_SIZE = 800
CHUNK_OVERLAP = 100


model = SentenceTransformer(MODEL_NAME)



def chunk_text(text):
    """
    Sliding window chunking.
    """

    if not text:
        return []

    if len(text) <= CHUNK_SIZE:
        return [text]


    chunks = []

    start = 0

    while start < len(text):

        end = start + CHUNK_SIZE

        chunks.append(
            text[start:end]
        )

        start = end - CHUNK_OVERLAP


    return chunks



def get_documents():

    with lakebase.get_connection() as conn:

        with conn.cursor() as cur:

            cur.execute(
                f"""
                SELECT
                    d.id,
                    d.narrative_text

                FROM {DOCUMENT_TABLE} d

                LEFT JOIN {EMBED_TABLE} e

                ON d.id = e.document_id

                WHERE e.document_id IS NULL
                """
            )

            return cur.fetchall()



def insert_embeddings(rows):

    if not rows:
        return


    with lakebase.get_connection() as conn:

        with conn.cursor() as cur:

            execute_values(
                cur,
                f"""
                INSERT INTO {EMBED_TABLE}
                (
                    document_id,
                    chunk_index,
                    chunk_text,
                    embedding,
                    model_name
                )

                VALUES %s

                ON CONFLICT
                (
                    document_id,
                    chunk_index
                )

                DO UPDATE SET

                chunk_text = EXCLUDED.chunk_text,

                embedding = EXCLUDED.embedding
                """,
                rows
            )

        conn.commit()



def main():

    docs = get_documents()

    logger.info(
        f"Documents found: {len(docs)}"
    )


    rows = []


    for doc in docs:

        chunks = chunk_text(
            doc["narrative_text"]
        )


        vectors = model.encode(
            chunks
        )


        for index, (chunk, vector) in enumerate(
            zip(chunks, vectors)
        ):

            rows.append(
                (
                    doc["id"],
                    index,
                    chunk,
                    vector.tolist(),
                    MODEL_NAME
                )
            )


    logger.info(
        f"Embedding rows created: {len(rows)}"
    )


    insert_embeddings(rows)


    logger.info(
        "Embedding ingestion complete"
    )



if __name__ == "__main__":
    main()