-- Migration 003: sent_news
-- Deduplicação de notícias já enviadas como alerta.
-- Executar no Supabase SQL Editor.

CREATE TABLE IF NOT EXISTS sent_news (
    news_id TEXT        PRIMARY KEY,
    sent_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE sent_news ENABLE ROW LEVEL SECURITY;

-- Limpeza automática de registros com mais de 7 dias (evita crescimento infinito)
-- Rodar manualmente ou configurar pg_cron se disponível:
-- DELETE FROM sent_news WHERE sent_at < now() - interval '7 days';
