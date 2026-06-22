"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { saveUserPrefs, resetUserPrefs, previewReport, fetchSchedule, saveSchedule, generateSelflink, revokeSelflink } from "@/lib/config";
import { ScheduleGridEditor } from "@/components/schedule-grid";
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
  const [linkUrl, setLinkUrl] = useState<string | null>(null);
  const [linkStatus, setLinkStatus] = useState<string | null>(null);

  async function genLink() {
    setLinkStatus("Gerando…");
    try {
      const { url } = await generateSelflink(user.phone);
      setLinkUrl(url);
      setLinkStatus("Link gerado. Copie e envie ao usuário.");
    } catch (e) {
      setLinkStatus("Erro: " + (e instanceof Error ? e.message : "desconhecido"));
    }
  }

  async function revLink() {
    if (!window.confirm("Revogar o link atual? Quem tiver o link perde o acesso.")) return;
    setLinkStatus("Revogando…");
    try {
      await revokeSelflink(user.phone);
      setLinkUrl(null);
      setLinkStatus("Link revogado.");
    } catch (e) {
      setLinkStatus("Erro: " + (e instanceof Error ? e.message : "desconhecido"));
    }
  }

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

      <ScheduleGridEditor
        showEngineToggle
        reloadKey={user.phone}
        load={() => fetchSchedule(user.phone)}
        save={(args) => saveSchedule(user.phone, args)}
      />

      <section className="rounded-lg border border-border bg-card p-5 space-y-3">
        <h2 className="text-sm font-medium uppercase tracking-wide text-muted-foreground">Link self-service</h2>
        <p className="text-xs text-muted-foreground">Gere um link para o usuário editar a própria config (grade, seções, áudio) sem login.</p>
        <div className="flex flex-wrap gap-3">
          <button onClick={genLink} type="button"
            className="rounded-md border border-border px-4 py-2 text-sm text-muted-foreground hover:text-foreground">Gerar link</button>
          <button onClick={revLink} type="button"
            className="rounded-md border border-border px-4 py-2 text-sm text-muted-foreground hover:text-foreground">Revogar</button>
        </div>
        {linkUrl && (
          <input readOnly value={linkUrl} onFocus={(e) => e.currentTarget.select()}
            className="block w-full rounded-md border border-border bg-input px-3 py-2 text-xs text-foreground" />
        )}
        {linkStatus && <p className="text-sm text-primary">{linkStatus}</p>}
      </section>

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
