"use client";

import { useState } from "react";
import { ScheduleGridEditor } from "@/components/schedule-grid";
import { saveMePrefs, saveMeSchedule, type MeData } from "@/lib/selflink";

const VOICES = ["nova", "shimmer", "alloy", "echo", "fable", "onyx"];

export function MeEditor({ token, data }: { token: string; data: MeData }) {
  const [audioText, setAudioText] = useState(Boolean(data.audio.audio_for_text));
  const [audioMedia, setAudioMedia] = useState(Boolean(data.audio.audio_for_media));
  const [voice, setVoice] = useState(VOICES.includes(data.audio.tts_voice ?? "") ? data.audio.tts_voice! : "nova");
  const [speed, setSpeed] = useState(() => {
    const s = Number(data.audio.tts_speed ?? 0.85);
    return Number.isFinite(s) ? Math.min(1.5, Math.max(0.5, s)) : 0.85;
  });
  const [status, setStatus] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function savePrefs() {
    setBusy(true);
    setStatus("Salvando…");
    try {
      await saveMePrefs(token, {
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
        Salvar áudio
      </button>
    </div>
  );
}
