import Shell from "@/components/shell";
import { PageHeader } from "@/components/ui";
import { fetchReportPrompts, type ReportPrompt } from "@/lib/api";
import { ReportPromptsEditor } from "@/components/report-prompts-editor";

export default async function RelatorioPage() {
  let prompts: ReportPrompt[] = [];
  let err: string | null = null;
  try {
    prompts = await fetchReportPrompts();
  } catch (e) {
    err = e instanceof Error ? e.message : "erro desconhecido";
  }

  return (
    <Shell active="/relatorio">
      <main className="mx-auto max-w-3xl px-8 py-12">
        <PageHeader eyebrow="Editar" title="Relatório">
          Prompts das 6 seções do relatório diário. Salvar vale no próximo envio.
        </PageHeader>
        {err ? (
          <p className="text-sm text-muted-foreground">Não foi possível carregar os prompts: {err}</p>
        ) : (
          <ReportPromptsEditor initial={prompts} />
        )}
      </main>
    </Shell>
  );
}
