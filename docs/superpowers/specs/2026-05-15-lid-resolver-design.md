# LID Resolver — Design Spec

**Goal:** Corrigir o envio de mensagens pelo webhook para que o agente responda pelo mesmo JID pelo qual a mensagem chegou, em vez de tentar resolver o número de telefone. Também informar o usuário não autorizado de que o pedido de acesso foi enviado ao admin.

**Architecture:** Ao receber uma mensagem, o `remoteJid` fornecido pela Evolution API é o identificador garantido para aquele usuário. O agente passa a usar esse JID diretamente como destino de todas as respostas no webhook, eliminando a dependência de resolução de número de telefone pela Evolution API.

**Tech Stack:** Python, FastAPI, Evolution API v1.8.2, Supabase

---

## Contexto

`whatsapp.send_message(number, text)` aceita qualquer string como `number` — número de telefone ou JID (ex: `139247134720249@lid`, `5534999301855@s.whatsapp.net`). A Evolution API roteia pelo JID sem falha.

O problema: o webhook usa `authorized["phone"]` como destino. Para alguns usuários (ex: Ricardim), a Evolution API não consegue resolver o telefone para um JID WhatsApp válido, resultando em mensagens nunca entregues.

A correção: usar `remote_jid` (o JID que chegou na mensagem) como destino de respostas no webhook, e `pending["lid"]` para a mensagem de boas-vindas na autorização.

---

## Mudanças

### Arquivo único: `backend/api/main.py`

**1. Webhook handler — introduzir `target_jid`**

Após `target_phone = authorized["phone"]`, adicionar:
```python
target_jid = remote_jid
```

Substituir todas as chamadas `whatsapp.send_message(target_phone, ...)` dentro do bloco do usuário autorizado por `whatsapp.send_message(target_jid, ...)`. Isso cobre:
- Confirmação de preferências
- Confirmação de feedback de notícias
- Reset de feedback de notícias
- Resposta normal do agente

Manter `whatsapp.send_message(admin_phone, ...)` para notificações ao admin (já funcionam).

**2. Bloco de usuário não autorizado — confirmação ao solicitante**

Após notificar o admin, enviar mensagem ao próprio usuário não autorizado usando `remote_jid`:

```python
whatsapp.send_message(
    remote_jid,
    "Vou enviar uma mensagem para o admin liberar o seu acesso, só um momento! 🙏",
)
```

Esse envio não bloqueia o fluxo: se falhar (ex: número bloqueado), o webhook retorna normalmente. Envolver em `try/except` com log de warning.

**3. `_handle_admin_command` — mensagem de boas-vindas pelo LID**

```python
# Antes
whatsapp.send_message(phone, "Olá! Você foi autorizado...")

# Depois
whatsapp.send_message(pending["lid"], "Olá! Você foi autorizado...")
```

`pending["lid"]` é o `remoteJid` capturado quando o novo usuário enviou a primeira mensagem — garantidamente válido.

---

## Sem Mudanças Em

- `backend/services/whatsapp.py` — já aceita JIDs
- `backend/api/send_report.py` — relatórios n8n chegam com telefone, funcionam para todos os usuários atuais
- `backend/api/cron_report.py` — idem
- `backend/services/supabase.py` — nenhuma alteração de schema

---

## Testes

Atualizar `backend/tests/test_webhook_prefs.py` e `backend/tests/test_webhook_news_feedback.py` para verificar que `whatsapp.send_message` é chamado com `remote_jid` (o JID) em vez de `target_phone`.

Adicionar `backend/tests/test_webhook_lid.py` com testes unitários cobrindo:
- Resposta normal usa `remote_jid`
- Confirmação de preferência usa `remote_jid`
- Confirmação de feedback usa `remote_jid`
- Admin continua usando `admin_phone`
- Mensagem de boas-vindas na autorização usa `pending["lid"]`
- Usuário não autorizado recebe confirmação via `remote_jid`
- Falha ao notificar usuário não autorizado não derruba o webhook
