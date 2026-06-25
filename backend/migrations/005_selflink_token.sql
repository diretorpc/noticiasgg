-- Migration 005: selflink_token
-- Token opaco por usuário para a página self-service /me (acesso sem login).
-- Revogar = setar NULL. Regenerar = sobrescrever.
-- Executar no Supabase SQL Editor.

ALTER TABLE authorized_users
    ADD COLUMN IF NOT EXISTS selflink_token TEXT;

-- Índice único parcial: garante unicidade dos tokens ativos sem colidir os NULL
-- (usuários sem link). Acelera o lookup em get_by_selflink_token.
CREATE UNIQUE INDEX IF NOT EXISTS authorized_users_selflink_token_key
    ON authorized_users (selflink_token)
    WHERE selflink_token IS NOT NULL;
