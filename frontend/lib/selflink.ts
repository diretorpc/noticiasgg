import type { ScheduleGrid } from "@/lib/config";

export type MeAudio = {
  audio_for_text: boolean | null;
  audio_for_media: boolean | null;
  tts_voice: string | null;
  tts_speed: number | null;
};

export type MeData = {
  name: string;
  schedule?: ScheduleGrid;
  sections: Record<string, boolean> | null;
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
  body: { sections: Record<string, boolean> | null } & MeAudio,
): Promise<void> {
  const res = await fetch(`${BACKEND}/api/me?token=${encodeURIComponent(token)}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`backend ${res.status}`);
}

export async function saveMeSchedule(token: string, schedule: ScheduleGrid): Promise<void> {
  const res = await fetch(`${BACKEND}/api/me/schedule?token=${encodeURIComponent(token)}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ schedule }),
  });
  if (!res.ok) throw new Error(`backend ${res.status}`);
}
