import Shell from "@/components/shell";
import { fetchAgentConfig, type AgentConfig } from "@/lib/api";

function Field({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-4 border-b border-line py-2.5 last:border-0">
      <dt className="eyebrow shrink-0">{label}</dt>
      <dd className="readout text-right text-sm">{value}</dd>
    </div>
  );
}

function Panel({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="rounded-lg border border-line bg-surface p-5">
      <h2 className="mb-3 font-display text-sm font-medium uppercase tracking-wide text-slate">
        {title}
      </h2>
      {children}
    </section>
  );
}

function Chip({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-line bg-raised px-3 py-2">
      <span className="eyebrow block">{label}</span>
      <span className="readout text-sm text-gold">{value}</span>
    </div>
  );
}

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
        <span className="eyebrow">Configuração</span>
        <h1 className="mt-2 font-display text-3xl font-bold tracking-tight text-bone">
          Agente
        </h1>

        <div className="mt-4 flex items-center gap-2 rounded-md border border-gold-dim/40 bg-gold-dim/10 px-3 py-2">
          <span aria-hidden>🔒</span>
          <p className="text-sm text-gold">
            Somente leitura. Edição de áudio e texto chega na próxima fase.
          </p>
        </div>

        {err ? (
          <div className="mt-8 rounded-lg border border-line bg-surface p-6">
            <p className="text-sm text-bone">Não foi possível carregar a config.</p>
            <p className="mt-1 readout text-xs text-slate">backend: {err}</p>
            <p className="mt-3 text-sm text-slate">
              Confira <span className="readout text-bone">NEXT_PUBLIC_BACKEND_URL</span> e o{" "}
              <span className="readout text-bone">SUPABASE_URL</span> no backend.
            </p>
          </div>
        ) : (
          cfg && (
            <div className="mt-8 space-y-5">
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
                  <Field
                    label="Vozes"
                    value={cfg.audio.voices_disponiveis.join(", ")}
                  />
                </dl>
              </Panel>

              <Panel title={`Ferramentas (${cfg.agent.tools.length})`}>
                <ul className="space-y-2">
                  {cfg.agent.tools.map((t) => (
                    <li key={t.name} className="border-b border-line pb-2 last:border-0">
                      <span className="readout text-sm text-gold">{t.name}</span>
                      <p className="mt-0.5 text-xs text-slate">{t.description}</p>
                    </li>
                  ))}
                </ul>
              </Panel>

              <Panel title="Fontes de notícia">
                <dl>
                  <Field label="Finance" value={cfg.news.sources_finance.join(", ")} />
                  <Field label="Tech" value={cfg.news.sources_tech.join(", ")} />
                  <Field
                    label="RSS"
                    value={cfg.news.rss_feeds.map((f) => f.nome).join(", ")}
                  />
                  <Field
                    label="RSS IA"
                    value={cfg.news.rss_feeds_ai.map((f) => f.nome).join(", ")}
                  />
                </dl>
              </Panel>

              <Panel title="System prompts">
                {([
                  ["system_market", cfg.agent.system_market],
                  ["system_chat", cfg.agent.system_chat],
                  ["system_validator", cfg.agent.system_validator],
                ] as const).map(([name, body]) => (
                  <details key={name} className="border-b border-line py-2 last:border-0">
                    <summary className="eyebrow cursor-pointer select-none">
                      {name}
                    </summary>
                    <pre className="mt-2 max-h-80 overflow-auto whitespace-pre-wrap rounded-md bg-ink p-3 text-xs leading-relaxed text-bone">
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
