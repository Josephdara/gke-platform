-- Applied by ingest, which owns the rag schema. pgvector's init script creates the schema, the
-- ingest and rag_api roles, and the vector extension before this runs.

CREATE TABLE embedding_config (
    id integer PRIMARY KEY CHECK (id = 1),
    model text NOT NULL,
    revision text NOT NULL,
    dimensions integer NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now()
);

-- One row per corpus path. active_revision is the SHA-256 whose chunks retrieval reads; a
-- document's new revision is loaded first and switched to in one transaction.
CREATE TABLE documents (
    id bigserial PRIMARY KEY,
    path text NOT NULL UNIQUE,
    title text NOT NULL,
    source_url text NOT NULL,
    license text NOT NULL,
    attribution text NOT NULL,
    active_revision text,
    retired boolean NOT NULL DEFAULT false,
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE chunks (
    id text PRIMARY KEY,
    document_id bigint NOT NULL REFERENCES documents (id) ON DELETE CASCADE,
    revision text NOT NULL,
    ordinal integer NOT NULL,
    heading_path text NOT NULL,
    text text NOT NULL,
    token_count integer NOT NULL,
    embedding vector(384) NOT NULL
);
CREATE INDEX chunks_document_revision ON chunks (document_id, revision);

CREATE TABLE ingest_runs (
    id bigserial PRIMARY KEY,
    started_at timestamptz NOT NULL DEFAULT now(),
    finished_at timestamptz,
    corpus_revision text NOT NULL,
    status text NOT NULL,
    report jsonb
);

-- Conversation storage for signed-in users. rag-api writes these and nothing else.
CREATE TABLE conversations (
    id uuid PRIMARY KEY,
    user_id text NOT NULL,
    title text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX conversations_user ON conversations (user_id, updated_at DESC);

CREATE TABLE messages (
    id bigserial PRIMARY KEY,
    conversation_id uuid NOT NULL REFERENCES conversations (id) ON DELETE CASCADE,
    role text NOT NULL CHECK (role IN ('user', 'assistant')),
    content text NOT NULL,
    -- Cited passages are copied here, so an answer keeps them after a document is retired.
    citations jsonb NOT NULL DEFAULT '[]',
    created_at timestamptz NOT NULL DEFAULT now()
);

-- rag-api reads the corpus and owns only conversation data.
GRANT SELECT ON embedding_config, documents, chunks TO rag_api;
GRANT SELECT, INSERT, UPDATE, DELETE ON conversations, messages TO rag_api;
GRANT USAGE ON SEQUENCE messages_id_seq TO rag_api;
