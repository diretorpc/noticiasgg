"use client";

import { useState } from "react";
import { ScheduleGridEditor } from "@/components/schedule-grid";
import { saveMePrefs, saveMeSchedule, type MeData } from "@/lib/selflink";

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

export function MeEditor({ token, data }: { token: string; data: MeData }) {
  const [sections, setSections] = useState<Record<string, boolean>>(data.sections ?? defaultSections());
  const [audioText, setAudioText] = useState(Boolean(data.audio.audio_for_text));
  const [audioMedia, setAudioMedia] = useState(Boolean(data.audio.audio_for_media));
  const [voice, setVoice] = useState(data.audio.tts_voice ?? "nova");
  const [speed, setSpeed] = useState(data.audio.tts_speed ?? 0.85);
  const [status, setStatus] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function savePrefs() {
    setBusy(true);
    setStatus("Salvando…");
    try {
      await saveMePrefs(token, {
        sections,
        audio_for_text: audioText,
        audio_for_media: audioMedia,
        tts_voice: voice,
        tts_speed: speed,
      });
      setStatus("Salvo.");
    } catch (e) {
      setStatus("Erro: " + (e instanceof Error ? e.message : "desconhecido"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-6">
      {data.name && <p className="text-sm text-muted-foreground">Olá, {data.name.split(" ")[0]}!</p>}

      <ScheduleGridEditor
        showEngineToggle={false}
        reloadKey={token}
        load={() => Promise.resolve({ schedule: data.schedule, use_new_engine: false })}
        save={({ schedule }) => saveMeSchedule(token, schedule)}
      />

      <section className="rounded-lg border border-border bg-card p-5">
        <h2 className="mb-3 text-sm font-medium uppercase tracking-wide text-muted-foreground">Seções do chat</h2>
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

      {status && <p className="text-sm text-primary">{status}</p>}
      <button onClick={savePrefs} disabled={busy}
        className="rounded-md bg-primary px-4 py-2 font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50">
        Salvar seções e áudio
      </button>
    </div>
  );
}
