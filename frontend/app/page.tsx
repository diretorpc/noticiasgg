import Shell from "@/components/shell";
import { PageHeader, NavCard, Chip } from "@/components/ui";
import { fetchAgentConfig, fetchUsers } from "@/lib/api";

export default async function HomePage() {
  let model = "—";
  let tools = "—";
  let sources = "—";
  let users = "—";
  try {
    const cfg = await fetchAgentConfig();
    model = cfg.agent.model;
    tools = String(cfg.agent.tools.length);
    sources = String(cfg.news.sources_finance.length + cfg.news.sources_tech.length);
  } catch {
    /* status degrada para — */
  }
  try {
    users = String((await fetchUsers()).length);
  } catch {
    /* idem */
  }

  return (
    <Shell active="/">
      <main className="mx-auto max-w-4xl px-8 py-12">
        <PageHeader eyebrow="Visão geral" title="Painel do agente">
          Inspecione e ajuste como o agente coleta dados, conversa e envia
          relatórios pelo WhatsApp.
        </PageHeader>

        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <Chip label="Modelo" value={model} />
          <Chip label="Usuários" value={users} />
          <Chip label="Fontes" value={sources} />
          <Chip label="Ferramentas" value={tools} />
        </div>

        <div className="mt-10 grid gap-3 sm:grid-cols-2">
          <NavCard
            href="/agente"
            eyebrow="Inspecionar"
            title="Agente"
            desc="Modelo, áudio, ferramentas, prompts e fontes de notícia."
          />
          <NavCard
            href="/noticias/fontes"
            eyebrow="Editar"
            title="Notícias"
            desc="Fontes NewsAPI, feeds RSS e queries de busca."
          />
          <NavCard
            href="/usuarios"
            eyebrow="Editar"
            title="Usuários"
            desc="Preferências, áudio e agendamento do relatório por usuário."
          />
        </div>
      </main>
    </Shell>
  );
}
