import Shell from "@/components/shell";
import { PageHeader } from "@/components/ui";
import { fetchSojaFretes, fetchSojaPreview } from "@/lib/api";
import { SojaFretesEditor } from "@/components/soja-fretes-editor";
import { SojaPreviewPanel } from "@/components/soja-preview";

export default async function SojaPage() {
  // `allSettled`, não dois `await` em sequência (achado 4): a prévia chama
  // coleta AO VIVO e pode demorar/travar sozinha — se ela dependesse de
  // `fretes` já ter resolvido (ou vice-versa), uma falha lenta atrasaria ou
  // derrubaria a página inteira. Cada uma falha (ou demora) sozinha.
  const [fretesResult, previewResult] = await Promise.allSettled([
    fetchSojaFretes(),
    fetchSojaPreview(),
  ]);

  const fretes = fretesResult.status === "fulfilled" ? fretesResult.value : null;
  const err =
    fretesResult.status === "rejected"
      ? (fretesResult.reason instanceof Error ? fretesResult.reason.message : "erro desconhecido")
      : null;

  const preview = previewResult.status === "fulfilled" ? previewResult.value : null;
  const previewErr =
    previewResult.status === "rejected"
      ? (previewResult.reason instanceof Error ? previewResult.reason.message : "erro desconhecido")
      : null;

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
        <SojaPreviewPanel preview={preview} error={previewErr} />
      </main>
    </Shell>
  );
}
