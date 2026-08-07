# Weather Intelligence — Unstructured Data → Lakebase Vector Search → REST API

## Overview

I was able to build most of this project using Zach's video for day 2. I made things overly difficult for myself by trying to deploy the app onto Databricks but failed. On testing the app on a .ipynb file I was able to see the data ingestion and the outputs required correctly. I even went above and beyond and did all 3/5 extra credit tasks. This project extends the Databricks Lakebase reference application by building a semantic search pipeline over unstructured weather data.

The pipeline:

1. Retrieves weather text from the National Weather Service (NWS) API.
2. Stores normalized weather documents in Lakebase (Postgres).
3. Generates vector embeddings using `sentence-transformers`.
4. Stores embeddings using PostgreSQL `pgvector`.
5. Exposes a Flask REST API for semantic weather search.

The final application supports queries such as:

```json
POST /weather/search

{
  "query": "flash flood risk near rivers",
  "top_k": 5
}
```

and returns the most semantically relevant weather documents ranked by similarity.

---

# Data Source

## National Weather Service API (NWS)

This project uses the National Weather Service API:

```
https://api.weather.gov
```

The NWS API was selected because:

* It is free and does not require an API key.
* It provides high-quality public weather information.
* It contains unstructured narrative text that is useful for semantic retrieval.

The application uses two types of weather data:

### Weather Alerts

Endpoint:

```
/alerts/active
```

Alert data contains narrative text such as:

* flood warnings
* severe weather descriptions
* safety instructions
* hazard explanations

These records are stored with:

```
source_type = "alert"
```

### Forecast Narratives

Endpoint:

```
/forecast
```

Forecast records contain detailed natural language descriptions such as:

```
Sunny, with a high near 78.
Northwest wind around 6 mph.
```

These records are stored with:

```
source_type = "forecast"
```

---

# Schema Design

The pipeline uses two Lakebase tables.

## weather_documents

Stores the original weather documents.

| Column         | Description                |
| -------------- | -------------------------- |
| id             | Stable document identifier |
| location       | Weather location           |
| source_type    | alert or forecast          |
| headline       | Weather event/title        |
| narrative_text | Text used for embedding    |
| issued_at      | Original issue timestamp   |
| payload        | Raw NWS JSON response      |
| synced_at      | Lakebase sync timestamp    |

Example:

```
Flash Flood Warning
A flash flood warning means...
```

---

## weather_embeddings

Stores vectorized chunks of weather documents.

| Column      | Description                     |
| ----------- | ------------------------------- |
| id          | Primary key                     |
| document_id | Reference to weather_documents  |
| chunk_index | Chunk ordering                  |
| chunk_text  | Text represented by the vector  |
| embedding   | pgvector 384-dimensional vector |
| model_name  | Embedding model used            |
| created_at  | Embedding creation timestamp    |

The table uses:

```
VECTOR(384)
```

because the embedding model is:

```
sentence-transformers/all-MiniLM-L6-v2
```

This model was chosen because it matches the existing news retrieval pipeline and produces compact 384-dimensional embeddings suitable for pgvector similarity search.

---

# Chunking Strategy

Weather narratives are usually short, but some alerts contain longer descriptions and instructions.

The pipeline uses sliding-window chunking:

```
CHUNK_SIZE = 800 characters

CHUNK_OVERLAP = 100 characters
```

This allows larger documents to be split into searchable sections while maintaining context between chunks.

---

# End-to-End Pipeline

## 1. Sync Weather Documents

The Flask API provides:

```
POST /weather/sync
```

Example:

```json
{
  "locations": [
    "Chicago, IL",
    "Austin, TX"
  ],
  "limit": 50
}
```

The endpoint:

1. Resolves locations using the NWS API.
2. Fetches alerts and forecast narratives.
3. Normalizes the response.
4. Upserts records into:

```
weather_documents
```

Example response:

```json
{
  "synced": 50
}
```

---

## 2. Generate Embeddings

Run the embedding ingestion script:

```
python ingest_weather_embeddings.py
```

The script:

1. Reads unembedded rows from:

```
weather_documents
```

2. Splits text into chunks.
3. Generates embeddings using:

```
sentence-transformers/all-MiniLM-L6-v2
```

4. Writes vectors into:

```
weather_embeddings
```

using psycopg2.

Embeddings are stored as:

```
VECTOR(384)
```

and indexed using pgvector HNSW:

```
vector_cosine_ops
```

for efficient similarity retrieval.

---

## 3. Search Weather Documents

The Flask API exposes:

```
POST /weather/search
```

Example request:

```json
{
  "query": "heavy rain and flooding risk",
  "top_k": 5
}
```

The endpoint:

1. Embeds the search query using the same MiniLM model.
2. Performs cosine similarity search using pgvector:

```sql
ORDER BY embedding <=> query_vector
```

3. Returns the most relevant documents.

Example response:

```json
{
  "results": [
    {
      "location": "Chicago, IL",
      "headline": "Flood Warning",
      "chunk_text": "Heavy rainfall may cause flooding...",
      "similarity": 0.82
    }
  ]
}
```

---

# API Endpoints

## Health Check

```
GET /healthz
```

Response:

```json
{
  "status": "ok"
}
```

---

## Weather Sync

```
POST /weather/sync
```

Fetches and stores weather documents.

---

## Weather Search

```
POST /weather/search
```

Performs semantic vector retrieval.

Optional filtering:

```json
{
  "query": "storm warnings",
  "source_type": "alert"
}
```

Supported values:

```
alert
forecast
```

---

# Known Limitations

## Location Resolution

Currently, locations depend on the NWS point lookup process.

Possible improvements:

* Add geocoding support.
* Accept latitude/longitude directly.
* Cache resolved NWS grid points.

---

## Freshness

Weather data changes frequently.

Current workflow requires manual synchronization.

Future improvements:

* Schedule Databricks Jobs for automatic refresh.
* Periodically update active alerts.
* Remove expired weather documents.

---

## Retrieval Quality

The current system uses pure vector similarity.

Potential improvements:

* Add metadata filtering by date.
* Combine vector similarity with keyword search.
* Add reranking models.
* Add an LLM layer for RAG-style summaries.

---

## Scaling

The current implementation is designed for a moderate number of weather documents.

Future improvements:

* Batch embedding generation.
* Parallel ingestion workers.
* Benchmark HNSW index performance.
* Add monitoring and logging metrics.

---

# Conclusion

This project demonstrates an end-to-end unstructured data retrieval pipeline using:

* National Weather Service API
* Databricks Lakebase
* PostgreSQL
* pgvector
* Sentence Transformer embeddings
* Flask REST APIs

The final system converts weather narratives into searchable vector representations and enables semantic retrieval of weather intelligence.
