-- Migration 007: news_log
-- Registro LEGÍVEL da notícia entregue como alerta. Separado de `sent_news`
-- de propósito: `sent_news` é um índice de dedup (duas linhas por notícia —
-- hash do título e hash da URL) com limpeza de 7 dias. Aqui a notícia é a
-- linha, e ela precisa sobreviver mais tempo para o agente conseguir
-- responder "me fale mais sobre aquela notícia".
-- Executar no Supabase SQL Editor.
--
-- Colunas pareadas (revisão de 18/08/2026 — achados A2, A3, A6):
--   fonte x feed: `fonte` é o veículo real (ex: "Farm Progress"), preenchido a
--     partir do <source> do Google Notícias quando existe; senão cai para o
--     apelido do feed. `feed` guarda SEMPRE o apelido da consulta que achou a
--     notícia (ex: "GN USDA/WASDE") — sem isso o registro atribuía a notícia à
--     busca, não ao jornal que escreveu.
--   url x url_publisher: `url` é o link que o alerta manda (a busca do Google
--     Notícias devolve uma página JS de ~592 KB, ilegível por read_article).
--     `url_publisher` é o domínio do veículo real, quando o feed informa.
--   resumo x resumo_fonte: `resumo` é a ANÁLISE de impacto gerada pelo Haiku
--     classificador — não é fato da fonte. `resumo_fonte` é a descrição crua
--     do RSS/NewsAPI. Ancorar o agente na análise de outro LLM seria a mesma
--     doença que esta tabela existe para curar.

CREATE TABLE IF NOT EXISTS news_log (
    id              BIGSERIAL   PRIMARY KEY,
    news_id         TEXT        NOT NULL,
    titulo_pt       TEXT,
    titulo_original TEXT,
    fonte           TEXT,
    feed            TEXT,
    url             TEXT,
    url_publisher   TEXT,
    categoria       TEXT,
    resumo          TEXT,
    resumo_fonte    TEXT,
    direcao         TEXT,
    -- NUMERIC, não INT: o score vem do JSON do classificador Haiku. Um dia que
    -- ele devolver 7.5, INT faz o PostgREST responder 400 e a LINHA INTEIRA se
    -- perde — visível só como um logger.warning, porque log_sent_news engole a
    -- exceção de propósito. Aceitar float custa nada e salva o registro.
    score           NUMERIC,
    ativos          JSONB,
    publicado_em    TIMESTAMPTZ,
    sent_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS news_log_sent_at_idx ON news_log (sent_at DESC);

ALTER TABLE news_log ENABLE ROW LEVEL SECURITY;

-- Limpeza sugerida (rodar à mão ou via pg_cron):
-- DELETE FROM news_log WHERE sent_at < now() - interval '90 days';
