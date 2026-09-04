"use client";

import { useState } from "react";
import { saveSojaFretes, resetSojaFretes } from "@/lib/config";
import type { SojaFretes } from "@/lib/api";

function formatUltimaEdicao(v: SojaFretes): string {
  if (!v.is_custom || !v.updated_at) {
    return "nunca salvos — usando padrão";
  }
  // timeZone fixo: sem isto o servidor (build/SSR, UTC) e o browser do
  // usuário (America/Sao_Paulo) formatam datas perto da meia-noite em dias
  // diferentes — hydration mismatch (achado 6).
  const quem = v.updated_by ? ` por ${v.updated_by}` : "";
  const instante = new Date(v.updated_at);
  if (v.idade_dias == null || Number.isNaN(instante.getTime())) {
    return `Última edição: data ilegível${quem} — salve de novo`;
  }
  const data = instante.toLocaleDateString("pt-BR", { timeZone: "America/Sao_Paulo" });
  const dias = v.idade_dias === 1 ? "1 dia" : `${v.idade_dias} dias`;
  return `Última edição: ${data}${quem} · há ${dias}`;
}

function formatDefaultsConfirm(v: SojaFretes): string {
  // Fonte dos valores é `v.defaults` (o default de fato), não `v.pracas[].valor`
  // (que traz o valor EFETIVO — seria o próprio valor customizado no confirm
  // de "voltar ao padrão", achado 3). A ordem segue `pracas` (a mesma da UI).
  return v.pracas
    .map((p) => (v.defaults[p.chave as keyof typeof v.defaults] ?? 0).toFixed(2).replace(".", ","))
    .join(" / ");
}

// Vírgula é o separador natural em pt-BR; Number("9,5") seria NaN → null → 422.
function numero(texto: string): number {
  return Number(String(texto).trim().replace(",", "."));
}

export function SojaFretesEditor({ initial }: { initial: SojaFretes }) {
  const [meta, setMeta] = useState(initial);
  const [valores, setValores] = useState(() =>
    Object.fromEntries(initial.pracas.map((p) => [p.chave, String(p.valor)])),
  );
  const [status, setStatus] = useState<string | null>(
    initial.erro ? `Aviso: ${initial.erro}` : initial.aviso ? `Aviso: ${initial.aviso}` : null,
  );
  const [busy, setBusy] = useState(false);

  async function save() {
    setBusy(true);
    setStatus("Salvando…");
    try {
      const fresh = await saveSojaFretes({
        pontal: numero(valores.pontal),
        uberaba: numero(valores.uberaba),
        canarana: numero(valores.canarana),
      });
      setMeta(fresh);
      setValores(Object.fromEntries(fresh.pracas.map((p) => [p.chave, String(p.valor)])));
      setStatus("Salvo. Vale na próxima mensagem das 12h.");
    } catch (e) {
      setStatus("Erro: " + (e instanceof Error ? e.message : "desconhecido"));
    } finally {
      setBusy(false);
    }
  }

  async function reset() {
    if (!window.confirm(`Voltar ao padrão (${formatDefaultsConfirm(meta)})? O valor customizado será perdido.`)) return;
    setBusy(true);
    setStatus("Resetando…");
    try {
      const fresh = await resetSojaFretes();
      setMeta(fresh);
      setValores(Object.fromEntries(fresh.pracas.map((p) => [p.chave, String(p.valor)])));
      setStatus("Resetado para o padrão.");
    } catch (e) {
      setStatus("Erro: " + (e instanceof Error ? e.message : "desconhecido"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="rounded-lg border border-border bg-card p-5">
      <div className="mb-4 flex items-center justify-between">
        <h2 className="text-sm font-medium uppercase tracking-wide text-muted-foreground">
          Fretes por praça
        </h2>
        {meta.envelhecido && (
          <span className="rounded-full bg-amber-500/15 px-2 py-0.5 text-xs text-amber-500">
            envelhecido
          </span>
        )}
      </div>

      <div className="grid gap-4 sm:grid-cols-3">
        {meta.pracas.map((p) => (
          <label key={p.chave} className="block">
            <span className="eyebrow mb-1 block">{p.rotulo}</span>
            <input
              type="number"
              step="0.01"
              min="0.01"
              value={valores[p.chave] ?? ""}
              onChange={(e) => setValores((v) => ({ ...v, [p.chave]: e.target.value }))}
              className="block w-full rounded-md border border-border bg-input px-3 py-2 text-sm text-foreground"
            />
          </label>
        ))}
      </div>

      <p className="mt-3 text-xs text-muted-foreground">{formatUltimaEdicao(meta)}</p>

      {status && <p className="mt-2 text-sm text-primary">{status}</p>}

      <div className="mt-4 flex flex-wrap gap-3">
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
          Voltar ao padrão
        </button>
      </div>
    </section>
  );
}
