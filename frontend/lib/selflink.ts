import type { ScheduleGrid } from "@/lib/config";

export type MeAudio = {
  audio_for_text: boolean | null;
  audio_for_media: boolean | null;
  tts_voice: string | null;
  tts_speed: number | null;
};

export type MeData = {
  name: string;
  // Opcional: página aberta contra um backend antigo não manda o campo. Ausente = não
  // sabemos, então a tela se comporta como antes (sem aviso).
  envio_ligado?: boolean;
  schedule?: ScheduleGrid;
  audio: MeAudio;
};

const BACKEND = process.env.NEXT_PUBLIC_BACKEND_URL;

export async function fetchMe(token: string): Promise<MeData> {
  const res = await fetch(`${BACKEND}/api/me?token=${encodeURIComponent(token)}`, { cache: "no-store" });
  if (!res.ok) throw new Error(`backend ${res.status}`);
  return res.json();
}

export async function saveMePrefs(
  token: string,
  body: MeAudio,
): Promise<void> {
  const res = await fetch(`${BACKEND}/api/me?token=${encodeURIComponent(token)}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`backend ${res.status}`);
}

// Devolve `envio_ligado` lido pelo backend na hora do PUT (o admin pode ter mudado a
// chave depois do GET); undefined se o backend for antigo.
export async function saveMeSchedule(token: string, schedule: ScheduleGrid): Promise<boolean | undefined> {
  const res = await fetch(`${BACKEND}/api/me/schedule?token=${encodeURIComponent(token)}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ schedule }),
  });
  if (!res.ok) throw new Error(`backend ${res.status}`);
  const body = (await res.json().catch(() => ({}))) as { envio_ligado?: unknown };
  return typeof body.envio_ligado === "boolean" ? body.envio_ligado : undefined;
}
