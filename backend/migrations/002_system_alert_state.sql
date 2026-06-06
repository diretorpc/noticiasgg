-- Migration 002: system_alert_state
-- Rastreia o último disparo de cada regra de alerta do sistema.
-- Executar no Supabase SQL Editor.

CREATE TABLE IF NOT EXISTS system_alert_state (
    rule_id           TEXT        PRIMARY KEY,
    last_triggered_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE system_alert_state ENABLE ROW LEVEL SECURITY;
