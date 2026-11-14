"""TODO: store and search vectors using PostgreSQL + pgvector."""
from typing import Any
import psycopg
from pgvector import Vector
from pgvector.psycopg import register_vector
from psycopg.types.json import Jsonb
from .models import Chunk


class PgVectorStore:
    def __init__(self, database_url: str, dimensions: int) -> None:
        """TODO: retain connection settings; validate model dimensions."""
        # raise NotImplementedError("TODO: initialize store")
        if dimensions <= 0:
            raise ValueError("dimensions must be positive")

        self.database_url = database_url
        self.dimensions = dimensions

    def create_schema(self) -> None:
        """TODO: create table with vector column and source/page/filter metadata."""
        # raise NotImplementedError("TODO: create_schema")
        sql = f"""
            CREATE EXTENSION IF NOT EXISTS vector;

            CREATE TABLE IF NOT EXISTS chunks (
                strategy TEXT NOT NULL,
                chunk_id TEXT NOT NULL,
                document_id TEXT NOT NULL,
                source TEXT NOT NULL,
                page INTEGER NOT NULL,
                text TEXT NOT NULL,
                metadata JSONB DEFAULT '{{}}',
                embedding VECTOR({self.dimensions}) NOT NULL,
                PRIMARY KEY (strategy, chunk_id)
            );
        """

        with psycopg.connect(self.database_url) as conn:
            with conn.cursor() as cur:
                cur.execute(sql)
    def upsert(self, strategy: str, chunks: list[Chunk], vectors: list[list[float]]) -> None:
        """TODO: validate lengths/dimensions and write stable IDs without duplicates.

        When re-ingesting changed source documents, remove obsolete chunks too.
        """
        # raise NotImplementedError("TODO: upsert")

        # 1. Validate input
        if len(chunks) != len(vectors):
            raise ValueError(
                "Chunks and vectors must have the same length"
            )

        if not strategy:
            raise ValueError("Strategy must not be empty")

        for vector in vectors:
            if len(vector) != self.dimensions:
                raise ValueError(
                    f"Expected {self.dimensions} dimensions, "
                    f"got {len(vector)}"
                )

        # Nothing to insert
        if not chunks:
            return

        # 2. Identify documents being updated
        document_ids = list({
            chunk.document_id for chunk in chunks
        })

        chunk_ids = [chunk.chunk_id for chunk in chunks]

        # 3. SQL statements
        delete_sql = """
            DELETE FROM chunks
            WHERE strategy = %s
            AND document_id = ANY(%s)
            AND NOT (chunk_id = ANY(%s))
        """

        insert_sql = """
            INSERT INTO chunks (
                strategy,
                chunk_id,
                document_id,
                source,
                page,
                text,
                metadata,
                embedding
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (strategy, chunk_id)
            DO UPDATE SET
                document_id = EXCLUDED.document_id,
                source = EXCLUDED.source,
                page = EXCLUDED.page,
                text = EXCLUDED.text,
                metadata = EXCLUDED.metadata,
                embedding = EXCLUDED.embedding
        """

        # 4. Execute database operations
        with psycopg.connect(self.database_url) as conn:
            register_vector(conn)

            with conn.cursor() as cur:

                # Remove obsolete chunks of these documents
                cur.execute(
                    delete_sql,
                    (strategy, document_ids, chunk_ids)
                )

                # Insert or update chunks
                records = [
                    (
                        strategy,
                        chunk.chunk_id,
                        chunk.document_id,
                        chunk.source,
                        chunk.page,
                        chunk.text,
                        Jsonb(chunk.metadata),
                        Vector(vector)
                    )
                    for chunk, vector in zip(chunks, vectors)
                ]

                cur.executemany(insert_sql, records)

    def search(self, strategy: str, query_vector: list[float], top_k: int = 3,
               filters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        """TODO: filter permitted metadata in SQL, rank by cosine distance, return top-k.

        Return chunk ID, text, score and metadata. Parameterize user-supplied values.
        """
        # raise NotImplementedError("TODO: search")
        # 1. Validate input
        if len(query_vector) != self.dimensions:
            raise ValueError(
                f"Expected {self.dimensions} dimensions, "
                f"got {len(query_vector)}"
            )

        if top_k <= 0:
            raise ValueError("top_k must be positive")

        if not strategy:
            raise ValueError("Strategy must not be empty")

        # 2. Build SQL query
        sql = """
            SELECT
                chunk_id,
                text,
                metadata,
                embedding <=> %s AS distance
            FROM chunks
            WHERE strategy = %s
        """

        params = [Vector(query_vector), strategy]

        # 3. Apply metadata filters
        if filters:
            for key, value in filters.items():
                sql += " AND metadata ->> %s = %s"
                params.extend([key, str(value)])

        # 4. Rank by cosine distance
        sql += """
            ORDER BY embedding <=> %s
            LIMIT %s
        """

        params.extend([Vector(query_vector), top_k])

        # 5. Execute query
        results = []

        with psycopg.connect(self.database_url) as conn:
            register_vector(conn)

            with conn.cursor() as cur:
                cur.execute(sql, params)

                rows = cur.fetchall()

                for row in rows:
                    chunk_id, text, metadata, distance = row

                    results.append({
                        "chunk_id": chunk_id,
                        "text": text,
                        "metadata": metadata,
                        "score": 1.0 - float(distance)
                    })

        return results