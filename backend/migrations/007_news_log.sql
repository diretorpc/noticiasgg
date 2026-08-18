-- Migration 007: news_log
-- Registro LEGÍVEL da notícia entregue como alerta. Separado de `sent_news`
-- de propósito: `sent_news` é um índice de dedup (duas linhas por notícia —
-- hash do título e hash da URL) com limpeza de 7 dias. Aqui a notícia é a
-- linha, e ela precisa sobreviver mais tempo para o agente conseguir
-- responder "me fale mais sobre aquela notícia".
-- Executar no Supabase SQL Editor.

CREATE TABLE IF NOT EXISTS news_log (
    id              BIGSERIAL   PRIMARY KEY,
    news_id         TEXT        NOT NULL,
    titulo_pt       TEXT,
    titulo_original TEXT,
    fonte           TEXT,
    url             TEXT,
    categoria       TEXT,
    resumo          TEXT,
    direcao         TEXT,
    score           INT,
    ativos          JSONB,
    publicado_em    TIMESTAMPTZ,
    sent_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS news_log_sent_at_idx ON news_log (sent_at DESC);

ALTER TABLE news_log ENABLE ROW LEVEL SECURITY;

-- Limpeza sugerida (rodar à mão ou via pg_cron):
-- DELETE FROM news_log WHERE sent_at < now() - interval '90 days';
