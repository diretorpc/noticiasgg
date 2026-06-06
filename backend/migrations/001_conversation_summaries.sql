-- Migration 001: conversation_summaries
-- Tabela para armazenar o resumo comprimido do histórico de cada usuário.
-- Executar no Supabase SQL Editor.

CREATE TABLE IF NOT EXISTS conversation_summaries (
    phone       TEXT        PRIMARY KEY,
    summary     TEXT        NOT NULL,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE conversation_summaries ENABLE ROW LEVEL SECURITY;
