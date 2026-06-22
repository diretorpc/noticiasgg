"use client";

import { useEffect, useState } from "react";
import { fetchMe, type MeData } from "@/lib/selflink";
import { MeEditor } from "@/components/me-editor";

export default function MePage() {
  const [token, setToken] = useState<string | null>(null);
  const [data, setData] = useState<MeData | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    const t = new URLSearchParams(window.location.search).get("token");
    if (!t) {
      setErr("Link inválido. Peça um novo ao administrador.");
      return;
    }
    setToken(t);
    // remove o token da URL (reduz vazamento em histórico/referrer)
    window.history.replaceState({}, "", "/me");
    fetchMe(t)
      .then(setData)
      .catch(() => setErr("Link inválido ou revogado. Peça um novo ao administrador."));
  }, []);

  return (
    <main className="mx-auto max-w-2xl px-6 py-10">
      <div className="mb-8">
        <span className="eyebrow">Minhas configurações</span>
        <h1 className="mt-1 text-2xl font-semibold tracking-tight text-foreground">noticiasgg</h1>
      </div>
      {err && <p className="rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm text-destructive">{err}</p>}
      {!err && !data && <p className="text-sm text-muted-foreground">Carregando…</p>}
      {token && data && <MeEditor token={token} data={data} />}
    </main>
  );
}
