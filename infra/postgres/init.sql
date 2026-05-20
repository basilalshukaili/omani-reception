-- Omani Reception — init.sql
-- Runs once on first Postgres boot (empty data dir) via /docker-entrypoint-initdb.d/.
-- P0 scope: enable extensions and create a single sanity table so we can verify init.sql executed.
-- The real schema (kb_chunk, conversations, messages, etc.) lands in P2 (Memory & RAG).

-- ---------- extensions ----------
CREATE EXTENSION IF NOT EXISTS vector;    -- pgvector — embeddings & similarity search (P2)
CREATE EXTENSION IF NOT EXISTS pg_trgm;   -- trigram index — fuzzy Arabic match support (P2)

-- ---------- sanity check table ----------
-- Tiny table whose mere existence proves init.sql ran on first boot.
-- Safe to keep across phases; later migrations may drop it once we have real tables.
CREATE TABLE IF NOT EXISTS _health_check (
    id         SERIAL PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO _health_check DEFAULT VALUES;

-- ---------- kb_chunk (stub — real schema lands in P2) ----------
-- NOTE: real schema lands in P2 (Memory & RAG); for P0 we only enable extensions
-- and do a sanity check. Sketched here so reviewers see where it will live:
--
-- CREATE TABLE kb_chunk (
--     id           BIGSERIAL PRIMARY KEY,
--     business_id  TEXT NOT NULL,
--     source       TEXT NOT NULL,            -- file path or URL
--     lang         TEXT NOT NULL,            -- 'ar' | 'en' | 'mixed'
--     text         TEXT NOT NULL,
--     embedding    VECTOR(768),              -- text-embedding-004 dims
--     metadata     JSONB NOT NULL DEFAULT '{}'::jsonb,
--     created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
-- );
-- CREATE INDEX kb_chunk_embedding_ivfflat
--     ON kb_chunk USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
-- CREATE INDEX kb_chunk_text_trgm
--     ON kb_chunk USING gin (text gin_trgm_ops);

-- ---------- verification (run manually after `docker-compose up`) ----------
-- docker exec -it reception_postgres psql -U reception -d reception -c \
--   "SELECT extname, extversion FROM pg_extension WHERE extname IN ('vector', 'pg_trgm');"
-- Expected: two rows, vector >= 0.7.x, pg_trgm >= 1.6.
--
-- docker exec -it reception_postgres psql -U reception -d reception -c \
--   "SELECT count(*) FROM _health_check;"
-- Expected: 1.
