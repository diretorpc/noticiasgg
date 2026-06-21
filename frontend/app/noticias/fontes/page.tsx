import Shell from "@/components/shell";
import FontesForm from "@/components/fontes-form";
import { PageHeader, Panel } from "@/components/ui";
import { fetchAgentConfig, fetchNewsApiSources, type NewsApiSource } from "@/lib/api";

export default async function FontesPage() {
  let initial = null;
  let available: NewsApiSource[] = [];
  let err: string | null = null;
  try {
    const cfg = await fetchAgentConfig();
    initial = {
      sourcesFinance: cfg.news.sources_finance,
      sourcesTech: cfg.news.sources_tech,
      rssFeeds: cfg.news.rss_feeds,
      rssFeedsAi: cfg.news.rss_feeds_ai,
      financeQuery: cfg.news.finance_query,
      aiQuery: cfg.news.ai_query,
    };
    try {
      available = await fetchNewsApiSources();
    } catch {
      available = []; // picker degrada; resto da página segue editável
    }
  } catch (e) {
    err = e instanceof Error ? e.message : "erro desconhecido";
  }

  return (
    <Shell active="/noticias/fontes">
      <main className="mx-auto max-w-3xl px-8 py-12">
        <PageHeader eyebrow="Notícias" title="Fontes & buscas">
          Controle quais fontes e termos o agente usa para coletar notícias.
          Mudanças valem na próxima coleta (cache de ~1 min).
        </PageHeader>

        {err || !initial ? (
          <Panel>
            <p className="text-sm text-foreground">Não foi possível carregar a config.</p>
            <p className="readout mt-1 text-xs text-muted-foreground">backend: {err}</p>
          </Panel>
        ) : (
          <FontesForm initial={initial} available={available} />
        )}
      </main>
    </Shell>
  );
}
