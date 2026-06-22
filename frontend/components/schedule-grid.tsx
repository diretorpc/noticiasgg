"use client";

import { useState, useEffect } from "react";
import type { ScheduleGrid } from "@/lib/config";

const ENGINE_SECTIONS: [string, string][] = [
  ["commodities", "Commodities"],
  ["bolsas", "Bolsas"],
  ["cambio_cripto", "Câmbio/Cripto"],
  ["noticias", "Notícias"],
  ["analise", "Análise"],
  ["politica", "Política"],
];
const WEEKDAYS = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"];

function parseHours(raw: string): number[] {
  const seen = new Set<number>();
  for (const part of raw.split(",")) {
    const n = parseInt(part.trim(), 10);
    if (Number.isInteger(n) && n >= 0 && n <= 23) seen.add(n);
  }
  return [...seen].sort((a, b) => a - b);
}

export function ScheduleGridEditor({
  load,
  save,
  showEngineToggle,
  reloadKey,
}: {
  load: () => Promise<{ schedule?: ScheduleGrid; use_new_engine: boolean }>;
  save: (args: { schedule: ScheduleGrid; use_new_engine: boolean }) => Promise<void>;
  showEngineToggle: boolean;
  reloadKey: string;
}) {
  const [cells, setCells] = useState<Record<string, Record<number, string>>>({});
  const [useNew, setUseNew] = useState(false);
  const [status, setStatus] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let alive = true;
    load().then((res) => {
      if (!alive) return;
      const next: Record<string, Record<number, string>> = {};
      for (const [sec] of ENGINE_SECTIONS) {
        next[sec] = {};
        for (let wd = 0; wd < 7; wd++) {
          const hours = res.schedule?.[sec]?.[String(wd)] ?? [];
          next[sec][wd] = hours.join(",");
        }
      }
      setCells(next);
      setUseNew(res.use_new_engine);
    }).catch(() => setStatus("Erro ao carregar agendamento."));
    return () => { alive = false; };
    // reloadKey é a dep estável; load é arrow inline (muda toda render) de propósito
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [reloadKey]);

  function setCell(sec: string, wd: number, value: string) {
    setCells((c) => ({ ...c, [sec]: { ...c[sec], [wd]: value } }));
  }

  async function onSave() {
    setBusy(true);
    setStatus("Salvando…");
    const schedule: ScheduleGrid = {};
    for (const [sec] of ENGINE_SECTIONS) {
      for (let wd = 0; wd < 7; wd++) {
        const hours = parseHours(cells[sec]?.[wd] ?? "");
        if (hours.length) {
          schedule[sec] = schedule[sec] ?? {};
          schedule[sec][String(wd)] = hours;
        }
      }
    }
    try {
      await save({ use_new_engine: useNew, schedule });
      setStatus("Agendamento salvo.");
    } catch (e) {
      setStatus("Erro: " + (e instanceof Error ? e.message : "desconhecido"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="rounded-lg border border-border bg-card p-5">
      <h2 className="mb-3 text-sm font-medium uppercase tracking-wide text-muted-foreground">
        Agendamento
      </h2>
      {showEngineToggle && (
        <label className="mb-4 flex items-center gap-2 text-sm text-foreground">
          <input type="checkbox" checked={useNew} onChange={() => setUseNew((v) => !v)} />
          Usar motor novo para este usuário
        </label>
      )}
      <div className="overflow-x-auto">
        <table className="w-full border-collapse text-sm">
          <thead>
            <tr>
              <th className="p-1 text-left text-xs text-muted-foreground"></th>
              {WEEKDAYS.map((d) => (
                <th key={d} className="p-1 text-xs font-normal text-muted-foreground">{d}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {ENGINE_SECTIONS.map(([sec, label]) => (
              <tr key={sec}>
                <td className="p-1 pr-3 text-xs text-foreground">{label}</td>
                {WEEKDAYS.map((_, wd) => (
                  <td key={wd} className="p-1">
                    <input
                      value={cells[sec]?.[wd] ?? ""}
                      onChange={(e) => setCell(sec, wd, e.target.value)}
                      placeholder="—"
                      className="w-14 rounded border border-border bg-input px-1 py-1 text-center text-xs text-foreground"
                    />
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="mt-2 text-xs text-muted-foreground">Horas BRT separadas por vírgula (ex: 7,12). Vazio = não envia.</p>
      {status && <p className="mt-2 text-sm text-primary">{status}</p>}
      <button onClick={onSave} disabled={busy}
        className="mt-3 rounded-md bg-primary px-4 py-2 font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50">
        Salvar agendamento
      </button>
    </section>
  );
}
