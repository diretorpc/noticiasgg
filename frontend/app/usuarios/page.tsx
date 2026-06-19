import Shell from "@/components/shell";
import UsersManager from "@/components/users-manager";
import { fetchUsers, type AdminUser } from "@/lib/api";

export default async function UsuariosPage() {
  let users: AdminUser[] = [];
  let err: string | null = null;
  try {
    users = await fetchUsers();
  } catch (e) {
    err = e instanceof Error ? e.message : "erro desconhecido";
  }

  return (
    <Shell active="/usuarios">
      <main className="mx-auto max-w-4xl px-8 py-12">
        <span className="eyebrow">Usuários</span>
        <h1 className="mt-2 font-display text-3xl font-bold tracking-tight text-bone">
          Preferências por usuário
        </h1>
        <p className="mt-2 max-w-xl text-sm text-slate">
          Ajuste seções do relatório, horário, voz e áudio de cada usuário autorizado.
          Vale na próxima interação dele.
        </p>

        <div className="mt-8">
          {err ? (
            <div className="rounded-lg border border-line bg-surface p-6">
              <p className="text-sm text-bone">Não foi possível carregar os usuários.</p>
              <p className="mt-1 readout text-xs text-slate">backend: {err}</p>
            </div>
          ) : (
            <UsersManager users={users} />
          )}
        </div>
      </main>
    </Shell>
  );
}
