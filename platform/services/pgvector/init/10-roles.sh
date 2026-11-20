#!/usr/bin/env bash
# Runs once, when the database is first initialized. It creates the two application roles,
# the schema ingest owns, and the vector extension, which needs the superuser. The passwords
# are read inside psql, so they never appear in a process's arguments. Kustomize turns this
# file into a ConfigMap for the cluster, and the local Compose stack mounts it directly.
# The subshell keeps these options from reaching the entrypoint if the script is sourced.
(
set -eu
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<'SQL'
\set ingest_password `cat "$PGVECTOR_SECRETS_DIR/ingest"`
\set rag_api_password `cat "$PGVECTOR_SECRETS_DIR/rag-api"`
CREATE EXTENSION IF NOT EXISTS vector;
CREATE ROLE ingest LOGIN PASSWORD :'ingest_password';
CREATE ROLE rag_api LOGIN PASSWORD :'rag_api_password';
REVOKE ALL ON DATABASE :"DBNAME" FROM PUBLIC;
GRANT CONNECT ON DATABASE :"DBNAME" TO ingest, rag_api;
CREATE SCHEMA rag AUTHORIZATION ingest;
GRANT USAGE ON SCHEMA rag TO rag_api;
ALTER ROLE ingest SET search_path = rag, public;
ALTER ROLE rag_api SET search_path = rag, public;
SQL
)
