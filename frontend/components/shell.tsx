import Link from "next/link";
import { signOut } from "@/app/actions";
import { createClient } from "@/lib/supabase/server";

const NAV = [
  { href: "/", label: "Visão geral" },
  { href: "/agente", label: "Agente" },
  { href: "/relatorio", label: "Relatório" },
  { href: "/noticias/fontes", label: "Notícias" },
  { href: "/usuarios", label: "Usuários" },
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
      <aside className="flex w-60 shrink-0 flex-col border-r border-sidebar-border bg-sidebar text-sidebar-foreground">
        <div className="border-b border-sidebar-border px-6 py-5">
          <span className="eyebrow text-sidebar-foreground/60">Painel</span>
          <p className="mt-1 text-lg font-semibold tracking-tight text-sidebar-foreground">
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
                    ? "bg-sidebar-primary text-sidebar-primary-foreground"
                    : "text-sidebar-foreground/70 hover:bg-sidebar-accent/40 hover:text-sidebar-foreground"
                }`}
              >
                {item.label}
              </Link>
            );
          })}
        </nav>

        <div className="border-t border-sidebar-border p-3">
          <p className="truncate px-3 pb-2 text-xs text-sidebar-foreground/60">{user?.email}</p>
          <form action={signOut}>
            <button
              type="submit"
              className="w-full rounded-md px-3 py-2 text-left text-sm text-sidebar-foreground/70 transition-colors hover:bg-sidebar-accent/40 hover:text-sidebar-foreground"
            >
              Sair
            </button>
          </form>
        </div>
      </aside>

      <div className="flex-1 bg-background">{children}</div>
    </div>
  );
}
