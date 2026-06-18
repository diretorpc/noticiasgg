import Link from "next/link";
import Shell from "@/components/shell";

export default function HomePage() {
  return (
    <Shell active="/">
      <main className="mx-auto max-w-3xl px-8 py-12">
        <span className="eyebrow">Visão geral</span>
        <h1 className="mt-2 font-display text-3xl font-bold tracking-tight text-bone">
          Painel do agente
        </h1>
        <p className="mt-2 max-w-xl text-sm text-slate">
          Inspecione como o agente está configurado. Nesta fase o painel é
          somente leitura — controle de edição chega nas próximas etapas.
        </p>

        <div className="mt-10 grid gap-3 sm:grid-cols-2">
          <Link
            href="/agente"
            className="group rounded-lg border border-line bg-surface p-5 transition-colors hover:border-gold-dim"
          >
            <span className="eyebrow">Inspecionar</span>
            <p className="mt-2 font-display text-lg font-medium text-bone">
              Agente
              <span className="ml-2 text-gold transition-transform group-hover:translate-x-0.5 inline-block">
                →
              </span>
            </p>
            <p className="mt-1 text-sm text-slate">
              Modelo, áudio, ferramentas, prompts e fontes de notícia.
            </p>
          </Link>
        </div>
      </main>
    </Shell>
  );
}
