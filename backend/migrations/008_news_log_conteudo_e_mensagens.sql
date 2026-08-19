-- Migration 008: conteúdo capturado da matéria + id da mensagem por destinatário
-- Executar no Supabase SQL Editor. NÃO altera a 007 (já em produção, conferida
-- em 18/08/2026 — ver ESTADO.md) — só ALTER TABLE nela e uma tabela nova.
--
-- Por que existe (achados do dono, 18/08/2026, revisão da Story 1):
-- 1. news_log guardava um PONTEIRO (a URL), não a notícia. Para responder
--    "me fale mais sobre aquela notícia" depois, o agente teria que buscar o
--    artigo NAQUELA hora — e para os 6 feeds de busca do Google Notícias
--    (30% do volume) o `url` é uma página de redirecionamento em JS que o
--    fetch simples do ScraperAPI nunca lê (medido 18/08/2026: 6 de 6 devolvem
--    404). `conteudo` resolve guardando o TEXTO no momento do alerta, não o
--    endereço.
-- 2. "Qual notícia é essa" não pode ser o modelo ESCOLHENDO entre uma lista —
--    isso é o mesmo tipo de adivinhação que este projeto existe para
--    eliminar. news_log_messages guarda o id EXATO da mensagem que o
--    WhatsApp devolve no envio (`resposta["key"]["id"]`), e o webhook casa
--    pelo `contextInfo.stanzaId` da resposta citada — comparação de string,
--    não julgamento de LLM.

-- Parte A — texto da matéria, capturado na hora do alerta (não um ponteiro
-- que expira). `conteudo_fonte` diz de onde veio: hoje só "read_article"
-- (extração via ScraperAPI, com fallback render=true para link do Google
-- Notícias — ver backend/services/web_search.py). NULL quando a captura
-- falhou ou não veio nada útil: campo ausente é honesto, o agente vê e diz
-- que não tem o texto; nunca grava markup nem página de erro.
ALTER TABLE news_log ADD COLUMN IF NOT EXISTS conteudo TEXT;
ALTER TABLE news_log ADD COLUMN IF NOT EXISTS conteudo_fonte TEXT;

-- Parte B — id da mensagem ENVIADA, por destinatário. Cada destinatário
-- recebe uma mensagem DIFERENTE da Evolution, com um id diferente — não cabe
-- numa coluna só de news_log. FK com CASCADE: se um dia a linha de news_log
-- for limpa (retenção de 90 dias sugerida na 007), as mensagens órfãs somem
-- junto — elas não têm sentido sem a notícia que apontam.
CREATE TABLE IF NOT EXISTS news_log_messages (
    id           BIGSERIAL   PRIMARY KEY,
    news_log_id  BIGINT      NOT NULL REFERENCES news_log(id) ON DELETE CASCADE,
    phone        TEXT        NOT NULL,
    message_id   TEXT        NOT NULL,
    sent_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- O webhook casa por message_id (contextInfo.stanzaId da resposta citada) —
-- é a consulta do caminho quente do Parte C, precisa de índice.
CREATE INDEX IF NOT EXISTS news_log_messages_message_id_idx ON news_log_messages (message_id);
CREATE INDEX IF NOT EXISTS news_log_messages_news_log_id_idx ON news_log_messages (news_log_id);

ALTER TABLE news_log_messages ENABLE ROW LEVEL SECURITY;
