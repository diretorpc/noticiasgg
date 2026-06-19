"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { saveUserPrefs, resetUserPrefs } from "@/lib/config";
import type { AdminUser } from "@/lib/api";

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
const HOURS = ["", "06:00", "07:00", "08:00", "09:00", "12:00", "18:00", "19:00", "20:00", "21:00"];

function defaultSections(): Record<string, boolean> {
  return Object.fromEntries(SECTIONS.map(([k]) => [k, true]));
}

function UserForm({ user }: { user: AdminUser }) {
  const router = useRouter();
  const p = user.preferences;
  const [sections, setSections] = useState<Record<string, boolean>>(p?.sections ?? defaultSections());
  const [reportTime, setReportTime] = useState(p?.report_time ?? "");
  const [audioText, setAudioText] = useState(Boolean(p?.audio_for_text));
  const [audioMedia, setAudioMedia] = useState(Boolean(p?.audio_for_media));
  const [voice, setVoice] = useState(p?.tts_voice ?? "nova");
  const [speed, setSpeed] = useState(p?.tts_speed ?? 0.85);
  const [status, setStatus] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function save() {
    setBusy(true);
    setStatus("Salvando…");
    try {
      await saveUserPrefs({
        phone: user.phone,
        sections,
        report_time: reportTime || null,
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
      <section className="rounded-lg border border-line bg-surface p-5">
        <h2 className="mb-3 font-display text-sm font-medium uppercase tracking-wide text-slate">Relatório diário</h2>
        <label className="block">
          <span className="eyebrow">Horário de envio</span>
          <select value={reportTime} onChange={(e) => setReportTime(e.target.value)}
            className="mt-1 block rounded-md border border-line bg-ink px-3 py-2 text-sm text-bone">
            {HOURS.map((h) => <option key={h} value={h}>{h || "não enviar"}</option>)}
          </select>
        </label>
        <div className="mt-3 grid grid-cols-2 gap-2">
          {SECTIONS.map(([k, label]) => (
            <label key={k} className="flex items-center gap-2 text-sm text-bone">
              <input type="checkbox" checked={sections[k] ?? false}
                onChange={() => setSections((s) => ({ ...s, [k]: !s[k] }))} />
              {label}
            </label>
          ))}
        </div>
      </section>

      <section className="rounded-lg border border-line bg-surface p-5 space-y-3">
        <h2 className="font-display text-sm font-medium uppercase tracking-wide text-slate">Áudio</h2>
        <label className="flex items-center gap-2 text-sm text-bone">
          <input type="checkbox" checked={audioText} onChange={() => setAudioText((v) => !v)} />
          Responder textos em áudio
        </label>
        <label className="flex items-center gap-2 text-sm text-bone">
          <input type="checkbox" checked={audioMedia} onChange={() => setAudioMedia((v) => !v)} />
          Responder mídias em áudio
        </label>
        <label className="block">
          <span className="eyebrow">Voz</span>
          <select value={voice} onChange={(e) => setVoice(e.target.value)}
            className="mt-1 block rounded-md border border-line bg-ink px-3 py-2 text-sm text-bone">
            {VOICES.map((v) => <option key={v} value={v}>{v}</option>)}
          </select>
        </label>
        <label className="block">
          <span className="eyebrow">Velocidade ({speed})</span>
          <input type="range" min={0.5} max={1.5} step={0.05} value={speed}
            onChange={(e) => setSpeed(parseFloat(e.target.value))} className="mt-1 block w-full" />
        </label>
      </section>

      {status && <p className="text-sm text-gold">{status}</p>}
      <div className="flex gap-3">
        <button onClick={save} disabled={busy}
          className="rounded-md bg-gold px-4 py-2 font-medium text-ink hover:bg-bone disabled:opacity-50">Salvar</button>
        <button onClick={reset} disabled={busy}
          className="rounded-md border border-line px-4 py-2 text-sm text-slate hover:text-bone disabled:opacity-50">Resetar padrões</button>
      </div>
    </div>
  );
}

export default function UsersManager({ users }: { users: AdminUser[] }) {
  const [selected, setSelected] = useState(users[0]?.phone ?? null);
  if (users.length === 0) {
    return <p className="text-sm text-slate">Nenhum usuário autorizado ainda.</p>;
  }
  const current = users.find((u) => u.phone === selected) ?? users[0];
  return (
    <div className="grid gap-6 md:grid-cols-[220px_1fr]">
      <aside className="space-y-1">
        {users.map((u) => (
          <button key={u.phone} onClick={() => setSelected(u.phone)}
            className={`block w-full rounded-md px-3 py-2 text-left text-sm ${
              u.phone === current.phone ? "bg-raised text-bone" : "text-slate hover:bg-raised/50 hover:text-bone"
            }`}>
            <span className="block">{u.name || "sem nome"}</span>
            <span className="readout text-xs text-slate">{u.phone}</span>
          </button>
        ))}
      </aside>
      <UserForm key={current.phone} user={current} />
    </div>
  );
}
