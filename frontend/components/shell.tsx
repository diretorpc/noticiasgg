import Link from "next/link";
import { signOut } from "@/app/actions";
import { createClient } from "@/lib/supabase/server";

const NAV = [
  { href: "/", label: "Visão geral" },
  { href: "/agente", label: "Agente" },
  { href: "/noticias/fontes", label: "Notícias" },
];

export default async function Shell({
  children,
  active,
}: {
  children: React.ReactNode;
  active: string;
}) {
  const supabase = await createClient();
  const { data: { user } } = await supabase.auth.getUser();

  return (
    <div className="flex min-h-screen">
      <aside className="flex w-60 shrink-0 flex-col border-r border-line bg-surface">
        <div className="border-b border-line px-6 py-5">
          <span className="eyebrow">Mesa de operações</span>
          <p className="mt-1 font-display text-lg font-bold tracking-tight text-bone">
            noticiasgg
          </p>
        </div>

        <nav className="flex flex-1 flex-col gap-1 p-3">
          {NAV.map((item) => {
            const isActive = item.href === active;
            return (
              <Link
                key={item.href}
                href={item.href}
                aria-current={isActive ? "page" : undefined}
                className={`rounded-md px-3 py-2 text-sm transition-colors ${
                  isActive
                    ? "bg-raised text-bone"
                    : "text-slate hover:bg-raised/50 hover:text-bone"
                }`}
              >
                {item.label}
              </Link>
            );
          })}
        </nav>

        <div className="border-t border-line p-3">
          <p className="truncate px-3 pb-2 text-xs text-slate">{user?.email}</p>
          <form action={signOut}>
            <button
              type="submit"
              className="w-full rounded-md px-3 py-2 text-left text-sm text-slate transition-colors hover:bg-raised/50 hover:text-bone"
            >
              Sair
            </button>
          </form>
        </div>
      </aside>

      <div className="flex-1">{children}</div>
    </div>
  );
}
