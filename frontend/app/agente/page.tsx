import Shell from "@/components/shell";
import { PageHeader, Panel, Field, Chip } from "@/components/ui";
import { fetchAgentConfig, type AgentConfig } from "@/lib/api";

export default async function AgentePage() {
  let cfg: AgentConfig | null = null;
  let err: string | null = null;
  try {
    cfg = await fetchAgentConfig();
  } catch (e) {
    err = e instanceof Error ? e.message : "erro desconhecido";
  }

  return (
    <Shell active="/agente">
      <main className="mx-auto max-w-3xl px-8 py-12">
        <PageHeader eyebrow="Configuração" title="Agente" />

        <div className="mb-8 flex items-center gap-2 rounded-md border border-primary/30 bg-primary/10 px-3 py-2">
          <span aria-hidden>🔒</span>
          <p className="text-sm text-primary">
            Somente leitura. Os prompts ficam protegidos para preservar a integridade factual.
          </p>
        </div>

        {err ? (
          <Panel>
            <p className="text-sm text-foreground">Não foi possível carregar a config.</p>
            <p className="readout mt-1 text-xs text-muted-foreground">backend: {err}</p>
            <p className="mt-3 text-sm text-muted-foreground">
              Confira <span className="readout text-foreground">NEXT_PUBLIC_BACKEND_URL</span> e o{" "}
              <span className="readout text-foreground">SUPABASE_URL</span> no backend.
            </p>
          </Panel>
        ) : (
          cfg && (
            <div className="space-y-5">
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                <Chip label="Modelo" value={cfg.agent.model} />
                <Chip label="Timeout" value={`${cfg.agent.anthropic_timeout_s}s`} />
                <Chip label="Tool rounds" value={String(cfg.agent.max_tool_rounds)} />
                <Chip label="Tools" value={String(cfg.agent.tools.length)} />
              </div>

              <Panel title="Modelo & limites">
                <dl>
                  <Field label="Modelo" value={cfg.agent.model} />
                  <Field label="Validador" value={cfg.agent.validator_model} />
                  <Field label="Timeout (s)" value={cfg.agent.anthropic_timeout_s} />
                  <Field label="Max tool rounds" value={cfg.agent.max_tool_rounds} />
                  <Field label="Max tokens" value={cfg.agent.max_tokens} />
                </dl>
              </Panel>

              <Panel title="Áudio">
                <dl>
                  <Field label="Voz TTS" value={cfg.audio.tts_voice} />
                  <Field label="Velocidade" value={cfg.audio.tts_speed} />
                  <Field label="Modelo TTS" value={cfg.audio.tts_model} />
                  <Field label="Transcrição" value={cfg.audio.transcribe_model} />
                  <Field label="Vozes" value={cfg.audio.voices_disponiveis.join(", ")} />
                </dl>
              </Panel>

              <Panel title={`Ferramentas (${cfg.agent.tools.length})`}>
                <ul className="space-y-2">
                  {cfg.agent.tools.map((t) => (
                    <li key={t.name} className="border-b border-border pb-2 last:border-0">
                      <span className="readout text-sm text-primary">{t.name}</span>
                      <p className="mt-0.5 text-xs text-muted-foreground">{t.description}</p>
                    </li>
                  ))}
                </ul>
              </Panel>

              <Panel title="Fontes de notícia">
                <dl>
                  <Field label="Finance" value={cfg.news.sources_finance.join(", ")} />
                  <Field label="Tech" value={cfg.news.sources_tech.join(", ")} />
                  <Field label="RSS" value={cfg.news.rss_feeds.map((f) => f.nome).join(", ")} />
                  <Field label="RSS IA" value={cfg.news.rss_feeds_ai.map((f) => f.nome).join(", ")} />
                </dl>
              </Panel>

              <Panel title="System prompts">
                {([
                  ["system_market", cfg.agent.system_market],
                  ["system_chat", cfg.agent.system_chat],
                  ["system_validator", cfg.agent.system_validator],
                ] as const).map(([name, body]) => (
                  <details key={name} className="border-b border-border py-2 last:border-0">
                    <summary className="eyebrow cursor-pointer select-none">{name}</summary>
                    <pre className="mt-2 max-h-80 overflow-auto whitespace-pre-wrap rounded-md bg-background p-3 text-xs leading-relaxed text-foreground">
                      {body}
                    </pre>
                  </details>
                ))}
              </Panel>
            </div>
          )
        )}
      </main>
    </Shell>
  );
}
