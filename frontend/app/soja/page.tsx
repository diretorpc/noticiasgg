import Shell from "@/components/shell";
import { PageHeader } from "@/components/ui";
import { fetchSojaFretes, type SojaFretes } from "@/lib/api";
import { SojaFretesEditor } from "@/components/soja-fretes-editor";

export default async function SojaPage() {
  let fretes: SojaFretes | null = null;
  let err: string | null = null;
  try {
    fretes = await fetchSojaFretes();
  } catch (e) {
    err = e instanceof Error ? e.message : "erro desconhecido";
  }

  return (
    <Shell active="/soja">
      <main className="mx-auto max-w-3xl px-8 py-12">
        <PageHeader eyebrow="Editar" title="Soja Disponível">
          Fretes (R$/sc) descontados do Porto para cada praça. Salvar vale na próxima
          mensagem das 12h.
        </PageHeader>
        {err || !fretes ? (
          <p className="text-sm text-muted-foreground">Não foi possível carregar os fretes: {err}</p>
        ) : (
          <SojaFretesEditor initial={fretes} />
        )}
      </main>
    </Shell>
  );
}
