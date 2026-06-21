import Shell from "@/components/shell";
import UsersManager from "@/components/users-manager";
import { PageHeader, Panel } from "@/components/ui";
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
        <PageHeader eyebrow="Usuários" title="Preferências por usuário">
          Ajuste seções, áudio e o agendamento do relatório de cada usuário
          autorizado. Vale na próxima interação dele.
        </PageHeader>

        {err ? (
          <Panel>
            <p className="text-sm text-foreground">Não foi possível carregar os usuários.</p>
            <p className="readout mt-1 text-xs text-muted-foreground">backend: {err}</p>
          </Panel>
        ) : (
          <UsersManager users={users} />
        )}
      </main>
    </Shell>
  );
}
