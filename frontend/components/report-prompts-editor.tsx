"use client";

import { useState } from "react";
import { saveReportPrompt, resetReportPrompt, previewSection } from "@/lib/config";
import type { ReportPrompt } from "@/lib/api";

const LABELS: Record<string, string> = {
  commodities: "Commodities",
  bolsas: "Bolsas",
  cambio_cripto: "Câmbio & Cripto",
  noticias: "Notícias",
  analise: "Análise",
  politica: "Política",
};

export function ReportPromptsEditor({ initial }: { initial: ReportPrompt[] }) {
  return (
    <div className="space-y-5">
      {initial.map((p) => (
        <PromptCard key={p.section} prompt={p} />
      ))}
    </div>
  );
}

function PromptCard({ prompt }: { prompt: ReportPrompt }) {
  const [text, setText] = useState(prompt.value);
  const [isCustom, setIsCustom] = useState(prompt.is_custom);
  const [status, setStatus] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [preview, setPreview] = useState<string | null>(null);

  async function save() {
    setBusy(true);
    setStatus("Salvando…");
    try {
      await saveReportPrompt(prompt.section, text);
      setIsCustom(true);
      setStatus("Salvo. Vale no próximo relatório (até ~60s para propagar).");
    } catch (e) {
      setStatus("Erro: " + (e instanceof Error ? e.message : "desconhecido"));
    } finally {
      setBusy(false);
    }
  }

  async function reset() {
    if (!window.confirm("Resetar para o prompt padrão? O texto customizado será perdido.")) return;
    setBusy(true);
    setStatus("Resetando…");
    try {
      await resetReportPrompt(prompt.section);
      setText(prompt.default);
      setIsCustom(false);
      setPreview(null);
      setStatus("Resetado para o padrão.");
    } catch (e) {
      setStatus("Erro: " + (e instanceof Error ? e.message : "desconhecido"));
    } finally {
      setBusy(false);
    }
  }

  async function test() {
    setBusy(true);
    setPreview(null);
    setStatus("Gerando teste (motor real, pode levar ~30s)…");
    try {
      const out = await previewSection(prompt.section, text);
      setPreview(out);
      setStatus(out ? null : "Motor não retornou texto.");
    } catch (e) {
      setStatus("Erro no teste: " + (e instanceof Error ? e.message : "desconhecido"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="rounded-lg border border-border bg-card p-5">
      <div className="mb-2 flex items-center justify-between">
        <h2 className="text-sm font-medium uppercase tracking-wide text-muted-foreground">
          {LABELS[prompt.section] ?? prompt.section}
        </h2>
        <span
          className={`rounded-full px-2 py-0.5 text-xs ${
            isCustom ? "bg-primary/15 text-primary" : "bg-muted text-muted-foreground"
          }`}
        >
          {isCustom ? "customizado" : "padrão"}
        </span>
      </div>

      <textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        rows={10}
        className="block w-full rounded-md border border-border bg-input px-3 py-2 text-xs leading-relaxed text-foreground"
      />
      <p className="mt-1 text-right text-xs text-muted-foreground">{text.length} caracteres</p>

      {status && <p className="mt-1 text-sm text-primary">{status}</p>}

      <div className="mt-3 flex flex-wrap gap-3">
        <button
          onClick={save}
          disabled={busy}
          className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
        >
          Salvar
        </button>
        <button
          onClick={reset}
          disabled={busy}
          className="rounded-md border border-border px-4 py-2 text-sm text-muted-foreground hover:text-foreground disabled:opacity-50"
        >
          Resetar padrão
        </button>
        <button
          onClick={test}
          disabled={busy}
          className="rounded-md border border-border px-4 py-2 text-sm text-muted-foreground hover:text-foreground disabled:opacity-50"
        >
          Testar
        </button>
      </div>

      {preview && (
        <pre className="mt-3 max-h-80 overflow-auto whitespace-pre-wrap rounded-md bg-background p-3 text-xs leading-relaxed text-foreground">
          {preview}
        </pre>
      )}
    </section>
  );
}
