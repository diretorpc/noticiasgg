-- Migration 006: processed_messages
-- Deduplicação de mensagens do WhatsApp já processadas pelo webhook.
-- A Evolution reenvia a MESMA mensagem (mesmo key.id) a cada ~65s quando o
-- webhook demora a responder; sem esta trava o agente responde do zero a cada
-- reenvio (gerando respostas diferentes). A etiqueta é reservada no início do
-- processamento, então o reenvio bate na chave primária e é descartado.
-- Executar no Supabase SQL Editor.

CREATE TABLE IF NOT EXISTS processed_messages (
    message_id   TEXT        PRIMARY KEY,
    processed_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE processed_messages ENABLE ROW LEVEL SECURITY;

-- Limpeza automática de registros com mais de 2 dias (evita crescimento infinito).
-- Rodar manualmente ou configurar pg_cron se disponível:
-- DELETE FROM processed_messages WHERE processed_at < now() - interval '2 days';
