"use client";

import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import { saveUserPrefs, resetUserPrefs, previewReport, fetchSchedule, saveSchedule } from "@/lib/config";
import type { AdminUser } from "@/lib/api";

const ENGINE_SECTIONS: [string, string][] = [
  ["commodities", "Commodities"],
  ["bolsas", "Bolsas"],
  ["cambio_cripto", "Câmbio/Cripto"],
  ["noticias", "Notícias"],
  ["analise", "Análise"],
  ["politica", "Política"],
];
const WEEKDAYS = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"]; // índice = weekday 0-6

function parseHours(raw: string): number[] {
  const seen = new Set<number>();
  for (const part of raw.split(",")) {
    const n = parseInt(part.trim(), 10);
    if (Number.isInteger(n) && n >= 0 && n <= 23) seen.add(n);
  }
  return [...seen].sort((a, b) => a - b);
}

function ScheduleGridEditor({ phone }: { phone: string }) {
  const [cells, setCells] = useState<Record<string, Record<number, string>>>({});
  const [useNew, setUseNew] = useState(false);
  const [status, setStatus] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let alive = true;
    fetchSchedule(phone).then((res) => {
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
  }, [phone]);

  function setCell(sec: string, wd: number, value: string) {
    setCells((c) => ({ ...c, [sec]: { ...c[sec], [wd]: value } }));
  }

  async function save() {
    setBusy(true);
    setStatus("Salvando…");
    const schedule: Record<string, Record<string, number[]>> = {};
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
      await saveSchedule(phone, { use_new_engine: useNew, schedule });
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
        Agendamento (motor novo)
      </h2>
      <label className="mb-4 flex items-center gap-2 text-sm text-foreground">
        <input type="checkbox" checked={useNew} onChange={() => setUseNew((v) => !v)} />
        Usar motor novo para este usuário
      </label>
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
      <button onClick={save} disabled={busy}
        className="mt-3 rounded-md bg-primary px-4 py-2 font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50">
        Salvar agendamento
      </button>
    </section>
  );
}

const SECTIONS: [string, string][] = [
  ["market", "Mercado"],
  ["crypto", "Cripto"],
  ["indicators_us", "Indicadores EUA"],
  ["indicators_br", "Indicadores BR"],
  ["news", "Notícias"],
  ["commodities_br", "Commodities"],
  ["politics_br", "Política"],
  ["polls_br", "Pesquisas"],
];
const VOICES = ["nova", "shimmer", "alloy", "echo", "fable", "onyx"];

function defaultSections(): Record<string, boolean> {
  return Object.fromEntries(SECTIONS.map(([k]) => [k, true]));
}

function UserForm({ user }: { user: AdminUser }) {
  const router = useRouter();
  const p = user.preferences;
  const [sections, setSections] = useState<Record<string, boolean>>(p?.sections ?? defaultSections());
  const [audioText, setAudioText] = useState(Boolean(p?.audio_for_text));
  const [audioMedia, setAudioMedia] = useState(Boolean(p?.audio_for_media));
  const [voice, setVoice] = useState(p?.tts_voice ?? "nova");
  const [speed, setSpeed] = useState(p?.tts_speed ?? 0.85);
  const [status, setStatus] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [preview, setPreview] = useState<string[] | null>(null);
  const [previewing, setPreviewing] = useState(false);

  async function runPreview() {
    setPreviewing(true);
    setPreview(null);
    setStatus("Gerando pré-visualização (motor novo, 6 seções)… pode levar ~30s.");
    try {
      const messages = await previewReport(user.phone, null);
      setPreview(messages);
      setStatus(messages.length ? null : "Motor não retornou nenhuma seção.");
    } catch (e) {
      setStatus("Erro no preview: " + (e instanceof Error ? e.message : "desconhecido"));
    } finally {
      setPreviewing(false);
    }
  }

  async function save() {
    setBusy(true);
    setStatus("Salvando…");
    try {
      await saveUserPrefs({
        phone: user.phone,
        sections,
        report_time: p?.report_time ?? null,
        audio_for_text: audioText,
        audio_for_media: audioMedia,
        tts_voice: voice,
        tts_speed: speed,
      });
      setStatus("Salvo. Vale na próxima interação do usuário.");
      router.refresh();
    } catch (e) {
      setStatus("Erro: " + (e instanceof Error ? e.message : "desconhecido"));
    } finally {
      setBusy(false);
    }
  }

  async function reset() {
    setBusy(true);
    setStatus("Resetando…");
    try {
      await resetUserPrefs(user.phone);
      setStatus("Resetado para os padrões. Recarregue para ver.");
      router.refresh();
    } catch (e) {
      setStatus("Erro: " + (e instanceof Error ? e.message : "desconhecido"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-6">
      <section className="rounded-lg border border-border bg-card p-5">
        <h2 className="text-sm font-medium uppercase tracking-wide text-muted-foreground">Seções do chat</h2>
        <p className="mb-3 mt-1 text-xs text-muted-foreground">Quais seções entram quando o usuário pede um relatório pelo WhatsApp. O relatório agendado é configurado na grade abaixo.</p>
        <div className="grid grid-cols-2 gap-2">
          {SECTIONS.map(([k, label]) => (
            <label key={k} className="flex items-center gap-2 text-sm text-foreground">
              <input type="checkbox" checked={sections[k] ?? false}
                onChange={() => setSections((s) => ({ ...s, [k]: !s[k] }))} />
              {label}
            </label>
          ))}
        </div>
      </section>

      <section className="rounded-lg border border-border bg-card p-5 space-y-3">
        <h2 className="text-sm font-medium uppercase tracking-wide text-muted-foreground">Áudio</h2>
        <label className="flex items-center gap-2 text-sm text-foreground">
          <input type="checkbox" checked={audioText} onChange={() => setAudioText((v) => !v)} />
          Responder textos em áudio
        </label>
        <label className="flex items-center gap-2 text-sm text-foreground">
          <input type="checkbox" checked={audioMedia} onChange={() => setAudioMedia((v) => !v)} />
          Responder mídias em áudio
        </label>
        <label className="block">
          <span className="eyebrow">Voz</span>
          <select value={voice} onChange={(e) => setVoice(e.target.value)}
            className="mt-1 block rounded-md border border-border bg-input px-3 py-2 text-sm text-foreground">
            {VOICES.map((v) => <option key={v} value={v}>{v}</option>)}
          </select>
        </label>
        <label className="block">
          <span className="eyebrow">Velocidade ({speed})</span>
          <input type="range" min={0.5} max={1.5} step={0.05} value={speed}
            onChange={(e) => setSpeed(parseFloat(e.target.value))} className="mt-1 block w-full" />
        </label>
      </section>

      <ScheduleGridEditor phone={user.phone} />

      {status && <p className="text-sm text-primary">{status}</p>}
      <div className="flex flex-wrap gap-3">
        <button onClick={save} disabled={busy}
          className="rounded-md bg-primary px-4 py-2 font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50">Salvar</button>
        <button onClick={reset} disabled={busy}
          className="rounded-md border border-border px-4 py-2 text-sm text-muted-foreground hover:text-foreground disabled:opacity-50">Resetar padrões</button>
        <button onClick={runPreview} disabled={previewing}
          className="rounded-md border border-border px-4 py-2 text-sm text-muted-foreground hover:text-foreground disabled:opacity-50">
          {previewing ? "Gerando…" : "Pré-visualizar relatório"}
        </button>
      </div>

      {preview && (
        <section className="rounded-lg border border-border bg-card p-5">
          <h2 className="mb-3 text-sm font-medium uppercase tracking-wide text-muted-foreground">
            Pré-visualização — motor novo ({preview.length} {preview.length === 1 ? "mensagem" : "mensagens"})
          </h2>
          <p className="mb-3 text-xs text-muted-foreground">
            Não enviado a ninguém. Cada bloco é uma mensagem separada no WhatsApp.
          </p>
          <div className="space-y-3">
            {preview.map((msg, i) => (
              <pre key={i}
                className="whitespace-pre-wrap rounded-md border border-border bg-input p-3 text-sm text-foreground">
                {msg}
              </pre>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}

export default function UsersManager({ users }: { users: AdminUser[] }) {
  const [selected, setSelected] = useState(users[0]?.phone ?? null);
  if (users.length === 0) {
    return <p className="text-sm text-muted-foreground">Nenhum usuário autorizado ainda.</p>;
  }
  const current = users.find((u) => u.phone === selected) ?? users[0];
  return (
    <div className="grid gap-6 md:grid-cols-[220px_1fr]">
      <aside className="space-y-1">
        {users.map((u) => (
          <button key={u.phone} onClick={() => setSelected(u.phone)}
            className={`block w-full rounded-md px-3 py-2 text-left text-sm ${
              u.phone === current.phone ? "bg-primary/15 text-foreground" : "text-muted-foreground hover:bg-muted/50 hover:text-foreground"
            }`}>
            <span className="block">{u.name || "sem nome"}</span>
            <span className="readout text-xs text-muted-foreground">{u.phone}</span>
          </button>
        ))}
      </aside>
      <UserForm key={current.phone} user={current} />
    </div>
  );
}
