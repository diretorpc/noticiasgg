import { createClient } from "@/lib/supabase/server";

export type AgentConfig = {
  agent: {
    model: string;
    validator_model: string;
    anthropic_timeout_s: number;
    max_tool_rounds: number;
    max_tokens: number;
    tools: { name: string; description: string }[];
    system_market: string;
    system_chat: string;
    system_validator: string;
  };
  audio: {
    tts_voice: string;
    tts_speed: number;
    tts_model: string;
    transcribe_model: string;
    voices_disponiveis: string[];
  };
  news: {
    sources_finance: string[];
    sources_tech: string[];
    finance_query: string;
    ai_query: string;
    rss_feeds: { nome: string; url: string }[];
    rss_feeds_ai: { nome: string; url: string }[];
  };
};

export async function fetchAgentConfig(): Promise<AgentConfig> {
  const supabase = await createClient();
  const { data: { session } } = await supabase.auth.getSession();
  const token = session?.access_token;

  const res = await fetch(
    `${process.env.NEXT_PUBLIC_BACKEND_URL}/api/admin/agent-config`,
    {
      headers: { Authorization: `Bearer ${token}` },
      cache: "no-store",
    },
  );
  if (!res.ok) {
    throw new Error(`backend ${res.status}`);
  }
  return res.json();
}

export type NewsApiSource = {
  id: string;
  name: string;
  category: string;
  language: string;
  country: string;
};

export async function fetchNewsApiSources(): Promise<NewsApiSource[]> {
  const supabase = await createClient();
  const { data: { session } } = await supabase.auth.getSession();
  const token = session?.access_token;

  const res = await fetch(
    `${process.env.NEXT_PUBLIC_BACKEND_URL}/api/admin/newsapi-sources`,
    { headers: { Authorization: `Bearer ${token}` }, cache: "no-store" },
  );
  if (!res.ok) {
    throw new Error(`backend ${res.status}`);
  }
  const body = await res.json();
  return body.sources as NewsApiSource[];
}

export type UserPrefs = {
  sections: Record<string, boolean> | null;
  report_time: string | null;
  audio_for_text: boolean | null;
  audio_for_media: boolean | null;
  tts_voice: string | null;
  tts_speed: number | null;
};

export type AdminUser = {
  phone: string;
  name: string | null;
  preferences: UserPrefs | null;
};

export async function fetchUsers(): Promise<AdminUser[]> {
  const supabase = await createClient();
  const { data: { session } } = await supabase.auth.getSession();
  const res = await fetch(
    `${process.env.NEXT_PUBLIC_BACKEND_URL}/api/admin/users`,
    { headers: { Authorization: `Bearer ${session?.access_token}` }, cache: "no-store" },
  );
  if (!res.ok) throw new Error(`backend ${res.status}`);
  return (await res.json()).users as AdminUser[];
}
