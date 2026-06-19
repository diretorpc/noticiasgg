import Shell from "@/components/shell";
import FontesForm from "@/components/fontes-form";
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
        <span className="eyebrow">Notícias</span>
        <h1 className="mt-2 font-display text-3xl font-bold tracking-tight text-bone">
          Fontes &amp; buscas
        </h1>
        <p className="mt-2 max-w-xl text-sm text-slate">
          Controle de quais fontes e termos o agente usa para coletar notícias.
          Mudanças valem na próxima coleta (cache de ~1 min).
        </p>

        <div className="mt-8">
          {err || !initial ? (
            <div className="rounded-lg border border-line bg-surface p-6">
              <p className="text-sm text-bone">Não foi possível carregar a config.</p>
              <p className="mt-1 readout text-xs text-slate">backend: {err}</p>
            </div>
          ) : (
            <FontesForm initial={initial} available={available} />
          )}
        </div>
      </main>
    </Shell>
  );
}
