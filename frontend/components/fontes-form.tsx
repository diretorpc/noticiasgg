"use client";

import { useState } from "react";
// tokens: identidade LogisticOne (dark)
import { useRouter } from "next/navigation";
import { upsertConfig, deleteConfig, validateRss, type RssCheck } from "@/lib/config";
import type { NewsApiSource } from "@/lib/api";

type Feed = { nome: string; url: string };

type Props = {
  initial: {
    sourcesFinance: string[];
    sourcesTech: string[];
    rssFeeds: Feed[];
    rssFeedsAi: Feed[];
    financeQuery: string;
    aiQuery: string;
  };
  available: NewsApiSource[];
};

function SourcePicker({
  label,
  selected,
  onToggle,
  options,
}: {
  label: string;
  selected: string[];
  onToggle: (id: string) => void;
  options: NewsApiSource[];
}) {
  const [filter, setFilter] = useState("");

  if (options.length === 0) {
    return (
      <div>
        <span className="eyebrow">{label}</span>
        <p className="mt-1 text-sm text-muted-foreground">
          Lista da NewsAPI indisponível agora. Fontes atuais:{" "}
          <span className="readout text-foreground">{selected.join(", ") || "nenhuma"}</span>
        </p>
      </div>
    );
  }

  const shown = options.filter((o) =>
    o.name.toLowerCase().includes(filter.toLowerCase()),
  );
  return (
    <div>
      <span className="eyebrow">{label}</span>
      <input
        value={filter}
        onChange={(e) => setFilter(e.target.value)}
        placeholder="filtrar fontes"
        className="mt-1 w-full rounded-md border border-border bg-input px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground/50 focus:border-ring focus:outline-none"
      />
      <div className="mt-2 max-h-48 overflow-auto rounded-md border border-border">
        {shown.map((o) => (
          <label key={o.id} className="flex items-center gap-2 px-3 py-1.5 text-sm hover:bg-muted/40">
            <input
              type="checkbox"
              checked={selected.includes(o.id)}
              onChange={() => onToggle(o.id)}
            />
            <span className="readout text-foreground">{o.id}</span>
            <span className="text-muted-foreground">· {o.name}</span>
          </label>
        ))}
      </div>
    </div>
  );
}

type CheckState = RssCheck | "loading" | undefined;

function CheckResult({ state }: { state: CheckState }) {
  if (state === undefined) return null;
  if (state === "loading") return <p className="text-xs text-muted-foreground">testando…</p>;
  if (state.valid) {
    return (
      <p className="text-xs text-emerald-400">
        ✓ válido · {state.item_count} itens
        {state.sample_title ? ` · "${state.sample_title}"` : ""}
      </p>
    );
  }
  return <p className="text-xs text-red-400">✗ {state.error ?? "feed inválido"}</p>;
}

function FeedEditor({
  label,
  feeds,
  setFeeds,
}: {
  label: string;
  feeds: Feed[];
  setFeeds: (f: Feed[]) => void;
}) {
  const [checks, setChecks] = useState<Record<number, CheckState>>({});

  async function test(i: number) {
    const url = feeds[i].url.trim();
    if (!url) return;
    setChecks((c) => ({ ...c, [i]: "loading" }));
    const result = await validateRss(url);
    setChecks((c) => ({ ...c, [i]: result }));
  }

  function update(i: number, patch: Partial<Feed>) {
    setFeeds(feeds.map((x, j) => (j === i ? { ...x, ...patch } : x)));
    setChecks((c) => ({ ...c, [i]: undefined })); // edição invalida o último teste
  }

  return (
    <div>
      <span className="eyebrow">{label}</span>
      <div className="mt-2 space-y-3">
        {feeds.map((f, i) => (
          <div key={i} className="space-y-1">
            <div className="flex gap-2">
              <input
                value={f.nome}
                onChange={(e) => update(i, { nome: e.target.value })}
                placeholder="nome"
                className="w-1/3 rounded-md border border-border bg-input px-2 py-1.5 text-sm text-foreground"
              />
              <input
                value={f.url}
                onChange={(e) => update(i, { url: e.target.value })}
                placeholder="https://…/rss"
                className="flex-1 rounded-md border border-border bg-input px-2 py-1.5 text-sm text-foreground"
              />
              <button
                type="button"
                onClick={() => test(i)}
                className="rounded-md border border-border px-2 text-xs text-primary hover:bg-muted/40"
              >
                testar
              </button>
              <button
                type="button"
                onClick={() => setFeeds(feeds.filter((_, j) => j !== i))}
                className="rounded-md border border-border px-2 text-muted-foreground hover:text-foreground"
              >
                ✕
              </button>
            </div>
            <CheckResult state={checks[i]} />
          </div>
        ))}
        <button
          type="button"
          onClick={() => setFeeds([...feeds, { nome: "", url: "" }])}
          className="text-sm text-primary hover:text-foreground"
        >
          + adicionar feed
        </button>
      </div>
    </div>
  );
}

export default function FontesForm({ initial, available }: Props) {
  const router = useRouter();
  const [sourcesFinance, setSourcesFinance] = useState(initial.sourcesFinance);
  const [sourcesTech, setSourcesTech] = useState(initial.sourcesTech);
  const [rssFeeds, setRssFeeds] = useState(initial.rssFeeds);
  const [rssFeedsAi, setRssFeedsAi] = useState(initial.rssFeedsAi);
  const [financeQuery, setFinanceQuery] = useState(initial.financeQuery);
  const [aiQuery, setAiQuery] = useState(initial.aiQuery);
  const [status, setStatus] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const toggle = (list: string[], set: (v: string[]) => void, id: string) =>
    set(list.includes(id) ? list.filter((x) => x !== id) : [...list, id]);

  async function save() {
    setBusy(true);
    setStatus("Salvando…");
    try {
      const cleanFeeds = (f: Feed[]) => f.filter((x) => x.url.trim());
      await upsertConfig("news.sources_finance", sourcesFinance);
      await upsertConfig("news.sources_tech", sourcesTech);
      await upsertConfig("news.rss_feeds", cleanFeeds(rssFeeds));
      await upsertConfig("news.rss_feeds_ai", cleanFeeds(rssFeedsAi));
      await upsertConfig("news.finance_query", financeQuery);
      await upsertConfig("news.ai_query", aiQuery);
      setStatus("Salvo. As mudanças valem na próxima coleta (~1 min de cache).");
      router.refresh();
    } catch (e) {
      setStatus("Erro ao salvar: " + (e instanceof Error ? e.message : "desconhecido"));
    } finally {
      setBusy(false);
    }
  }

  async function restoreDefaults() {
    setBusy(true);
    setStatus("Restaurando padrões…");
    try {
      for (const key of [
        "news.sources_finance", "news.sources_tech", "news.rss_feeds",
        "news.rss_feeds_ai", "news.finance_query", "news.ai_query",
      ]) {
        await deleteConfig(key);
      }
      setStatus("Padrões restaurados. Recarregue a página para ver os valores originais.");
      router.refresh();
    } catch (e) {
      setStatus("Erro ao restaurar: " + (e instanceof Error ? e.message : "desconhecido"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-8">
      <section className="rounded-lg border border-border bg-card p-5 space-y-4">
        <h2 className="text-sm font-medium uppercase tracking-wide text-muted-foreground">Fontes NewsAPI</h2>
        <SourcePicker label="Finanças" selected={sourcesFinance} options={available}
          onToggle={(id) => toggle(sourcesFinance, setSourcesFinance, id)} />
        <SourcePicker label="Tech / IA" selected={sourcesTech} options={available}
          onToggle={(id) => toggle(sourcesTech, setSourcesTech, id)} />
      </section>

      <section className="rounded-lg border border-border bg-card p-5 space-y-4">
        <h2 className="text-sm font-medium uppercase tracking-wide text-muted-foreground">Feeds RSS</h2>
        <FeedEditor label="Geral" feeds={rssFeeds} setFeeds={setRssFeeds} />
        <FeedEditor label="IA" feeds={rssFeedsAi} setFeeds={setRssFeedsAi} />
      </section>

      <section className="rounded-lg border border-border bg-card p-5 space-y-4">
        <h2 className="text-sm font-medium uppercase tracking-wide text-muted-foreground">Queries de busca</h2>
        <label className="block">
          <span className="eyebrow">Finanças</span>
          <textarea value={financeQuery} onChange={(e) => setFinanceQuery(e.target.value)} rows={3}
            className="mt-1 w-full rounded-md border border-border bg-input px-3 py-2 text-sm text-foreground" />
        </label>
        <label className="block">
          <span className="eyebrow">IA</span>
          <textarea value={aiQuery} onChange={(e) => setAiQuery(e.target.value)} rows={3}
            className="mt-1 w-full rounded-md border border-border bg-input px-3 py-2 text-sm text-foreground" />
        </label>
      </section>

      {status && <p className="text-sm text-primary">{status}</p>}

      <div className="flex gap-3">
        <button onClick={save} disabled={busy}
          className="rounded-md bg-primary px-4 py-2 font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50">
          Salvar
        </button>
        <button onClick={restoreDefaults} disabled={busy}
          className="rounded-md border border-border px-4 py-2 text-sm text-muted-foreground hover:text-foreground disabled:opacity-50">
          Restaurar padrões
        </button>
      </div>
    </div>
  );
}
