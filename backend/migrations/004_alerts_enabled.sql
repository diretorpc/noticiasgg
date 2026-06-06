-- Migration 004: alerts_enabled
-- Controla quais usuários recebem alertas automáticos de preço e notícias.
-- Executar no Supabase SQL Editor.

ALTER TABLE authorized_users
    ADD COLUMN IF NOT EXISTS alerts_enabled BOOLEAN NOT NULL DEFAULT false;
