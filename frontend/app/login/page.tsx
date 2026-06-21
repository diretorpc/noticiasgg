import { login } from "./actions";

export default async function LoginPage({
  searchParams,
}: {
  searchParams: Promise<{ error?: string }>;
}) {
  const { error } = await searchParams;

  return (
    <main className="flex min-h-screen items-center justify-center bg-background px-6">
      <div className="w-full max-w-sm">
        <div className="mb-8">
          <span className="eyebrow">Painel</span>
          <h1 className="mt-2 text-2xl font-semibold tracking-tight text-foreground">
            noticiasgg
          </h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Acesso restrito. Entre para gerenciar o agente.
          </p>
        </div>

        <form
          action={login}
          className="space-y-4 rounded-lg border border-border bg-card p-6 shadow-sm"
        >
          {error && (
            <p className="rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm text-destructive">
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
              className="mt-1 w-full rounded-md border border-border bg-input px-3 py-2 text-foreground placeholder:text-muted-foreground/50 focus:border-ring focus:outline-none"
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
              className="mt-1 w-full rounded-md border border-border bg-input px-3 py-2 text-foreground placeholder:text-muted-foreground/50 focus:border-ring focus:outline-none"
              placeholder="••••••••"
            />
          </label>

          <button
            type="submit"
            className="w-full rounded-md bg-primary px-3 py-2 font-medium text-primary-foreground transition-colors hover:bg-primary/90"
          >
            Entrar
          </button>
        </form>
      </div>
    </main>
  );
}
