import { login } from "./actions";

export default async function LoginPage({
  searchParams,
}: {
  searchParams: Promise<{ error?: string }>;
}) {
  const { error } = await searchParams;

  return (
    <main className="flex min-h-screen items-center justify-center px-6">
      <div className="w-full max-w-sm">
        <div className="mb-8">
          <span className="eyebrow">Mesa de operações</span>
          <h1 className="mt-2 font-display text-2xl font-bold tracking-tight text-bone">
            noticiasgg
          </h1>
          <p className="mt-1 text-sm text-slate">
            Acesso restrito. Entre para inspecionar o agente.
          </p>
        </div>

        <form
          action={login}
          className="space-y-4 rounded-lg border border-line bg-surface p-6"
        >
          {error && (
            <p className="rounded-md border border-gold-dim/40 bg-gold-dim/10 px-3 py-2 text-sm text-gold">
              {error}
            </p>
          )}

          <label className="block">
            <span className="eyebrow">Email</span>
            <input
              name="email"
              type="email"
              required
              autoComplete="email"
              className="mt-1 w-full rounded-md border border-line bg-ink px-3 py-2 text-bone placeholder:text-slate/50 focus:border-gold focus:outline-none"
              placeholder="voce@exemplo.com"
            />
          </label>

          <label className="block">
            <span className="eyebrow">Senha</span>
            <input
              name="password"
              type="password"
              required
              autoComplete="current-password"
              className="mt-1 w-full rounded-md border border-line bg-ink px-3 py-2 text-bone placeholder:text-slate/50 focus:border-gold focus:outline-none"
              placeholder="••••••••"
            />
          </label>

          <button
            type="submit"
            className="w-full rounded-md bg-gold px-3 py-2 font-medium text-ink transition-colors hover:bg-bone"
          >
            Entrar
          </button>
        </form>
      </div>
    </main>
  );
}
