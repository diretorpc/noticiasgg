"use client";

import { createClient } from "@/lib/supabase/client";

export async function upsertConfig(key: string, value: unknown): Promise<void> {
  const supabase = createClient();
  const { data: { user } } = await supabase.auth.getUser();
  const { error } = await supabase.from("agent_config").upsert(
    {
      key,
      value,
      updated_by: user?.email ?? null,
      updated_at: new Date().toISOString(),
    },
    { onConflict: "key" },
  );
  if (error) throw new Error(error.message);
}

export async function deleteConfig(key: string): Promise<void> {
  const supabase = createClient();
  const { error } = await supabase.from("agent_config").delete().eq("key", key);
  if (error) throw new Error(error.message);
}

export type RssCheck = {
  valid: boolean;
  item_count: number;
  sample_title: string | null;
  error: string | null;
};

export async function validateRss(url: string): Promise<RssCheck> {
  const supabase = createClient();
  const { data: { session } } = await supabase.auth.getSession();
  const res = await fetch(
    `${process.env.NEXT_PUBLIC_BACKEND_URL}/api/admin/validate-rss`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${session?.access_token}`,
      },
      body: JSON.stringify({ url }),
    },
  );
  if (!res.ok) {
    return { valid: false, item_count: 0, sample_title: null, error: `backend ${res.status}` };
  }
  return res.json();
}

export type UserPrefsInput = {
  phone: string;
  sections: Record<string, boolean> | null;
  report_time: string | null;
  audio_for_text: boolean | null;
  audio_for_media: boolean | null;
  tts_voice: string | null;
  tts_speed: number | null;
};

export async function saveUserPrefs(body: UserPrefsInput): Promise<void> {
  const supabase = createClient();
  const { data: { session } } = await supabase.auth.getSession();
  const res = await fetch(
    `${process.env.NEXT_PUBLIC_BACKEND_URL}/api/admin/user-prefs`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${session?.access_token}`,
      },
      body: JSON.stringify(body),
    },
  );
  if (!res.ok) throw new Error(`backend ${res.status}`);
}

export async function resetUserPrefs(phone: string): Promise<void> {
  const supabase = createClient();
  const { data: { session } } = await supabase.auth.getSession();
  const res = await fetch(
    `${process.env.NEXT_PUBLIC_BACKEND_URL}/api/admin/user-prefs/${encodeURIComponent(phone)}`,
    { method: "DELETE", headers: { Authorization: `Bearer ${session?.access_token}` } },
  );
  if (!res.ok) throw new Error(`backend ${res.status}`);
}

export async function previewReport(
  phone: string,
  sections: Record<string, boolean> | null = null,
): Promise<string[]> {
  const supabase = createClient();
  const { data: { session } } = await supabase.auth.getSession();
  const res = await fetch(
    `${process.env.NEXT_PUBLIC_BACKEND_URL}/api/admin/preview-report`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${session?.access_token}`,
      },
      body: JSON.stringify({ phone, sections }),
    },
  );
  if (!res.ok) throw new Error(`backend ${res.status}`);
  return (await res.json()).messages as string[];
}

export type ScheduleGrid = Record<string, Record<string, number[]>>;

export type ScheduleResponse = {
  use_new_engine: boolean;
  schedule: ScheduleGrid;
};

export async function fetchSchedule(phone: string): Promise<ScheduleResponse> {
  const supabase = createClient();
  const { data: { session } } = await supabase.auth.getSession();
  const res = await fetch(
    `${process.env.NEXT_PUBLIC_BACKEND_URL}/api/admin/schedules/${encodeURIComponent(phone)}`,
    { headers: { Authorization: `Bearer ${session?.access_token}` }, cache: "no-store" },
  );
  if (!res.ok) throw new Error(`backend ${res.status}`);
  return res.json();
}

export async function saveSchedule(
  phone: string,
  body: { use_new_engine: boolean; schedule: ScheduleGrid },
): Promise<void> {
  const supabase = createClient();
  const { data: { session } } = await supabase.auth.getSession();
  const res = await fetch(
    `${process.env.NEXT_PUBLIC_BACKEND_URL}/api/admin/schedules/${encodeURIComponent(phone)}`,
    {
      method: "PUT",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${session?.access_token}`,
      },
      body: JSON.stringify(body),
    },
  );
  if (!res.ok) throw new Error(`backend ${res.status}`);
}

export async function saveReportPrompt(section: string, prompt: string): Promise<void> {
  const supabase = createClient();
  const { data: { session } } = await supabase.auth.getSession();
  const res = await fetch(
    `${process.env.NEXT_PUBLIC_BACKEND_URL}/api/admin/report-prompts/${encodeURIComponent(section)}`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${session?.access_token}` },
      body: JSON.stringify({ prompt }),
    },
  );
  if (!res.ok) throw new Error(`backend ${res.status}`);
}

export async function resetReportPrompt(section: string): Promise<void> {
  const supabase = createClient();
  const { data: { session } } = await supabase.auth.getSession();
  const res = await fetch(
    `${process.env.NEXT_PUBLIC_BACKEND_URL}/api/admin/report-prompts/${encodeURIComponent(section)}`,
    { method: "DELETE", headers: { Authorization: `Bearer ${session?.access_token}` } },
  );
  if (!res.ok) throw new Error(`backend ${res.status}`);
}

export async function previewSection(section: string, prompt: string): Promise<string> {
  const supabase = createClient();
  const { data: { session } } = await supabase.auth.getSession();
  const res = await fetch(
    `${process.env.NEXT_PUBLIC_BACKEND_URL}/api/admin/preview-section`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${session?.access_token}` },
      body: JSON.stringify({ section, prompt }),
    },
  );
  if (!res.ok) throw new Error(`backend ${res.status}`);
  return (await res.json()).text as string;
}
