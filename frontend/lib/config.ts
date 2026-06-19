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
