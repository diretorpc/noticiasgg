-- Migration 011: claim_token em processed_messages
--
-- Por quê: o cliente HTTP do backend repete um POST que estourou o tempo
-- (_RetryTransport). Quando o INSERT da reserva já tinha gravado e só a
-- RESPOSTA se perdeu, a repetição batia na chave primária e voltava 409.
-- O código lia 409 como "reenvio da Evolution" e descartava a mensagem — os
-- reenvios seguintes batiam no mesmo 409, então a pergunta do usuário ficava
-- sem resposta para sempre, sem erro nenhum no log.
--
-- Com o token, o 409 deixa de ser ambíguo: a repetição do transporte manda o
-- MESMO token (é a mesma requisição), enquanto um reenvio da Evolution é outra
-- execução, com token novo. Linha antiga tem o campo NULL e continua contando
-- como reserva anterior legítima.
--
-- ORDEM: aplicar ANTES de publicar o backend que grava a coluna. Sem ela o
-- PostgREST recusa o INSERT, a reserva falha e o webhook cai no caminho de
-- segurança que processa mesmo assim — não perde mensagem, mas perde a
-- proteção contra duplicata enquanto durar.
--
-- Executar no Supabase SQL Editor (ou via `supabase db query --linked -f`).
-- Reversão: ALTER TABLE processed_messages DROP COLUMN IF EXISTS claim_token;

ALTER TABLE processed_messages
    ADD COLUMN IF NOT EXISTS claim_token TEXT;

-- Recarrega o cache de schema do PostgREST: sem isso o INSERT com a coluna
-- nova continua devolvendo 400 durante a janela de cache.
NOTIFY pgrst, 'reload schema';
