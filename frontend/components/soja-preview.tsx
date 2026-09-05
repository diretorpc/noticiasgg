import { Panel } from "@/components/ui";
import type { SojaPreview } from "@/lib/api";

// "dd/mm hh:mm BRT" a partir de um epoch (segundos) — sempre na hora de
// Brasília, nunca a do servidor (build/SSR roda em UTC). Este componente é
// Server Component (sem "use client"): a formatação já sai pronta no HTML
// enviado, sem risco de hydration mismatch (não há re-render no cliente).
function formatEpochBRT(epoch: number | null): string | null {
  // `!epoch` (não `== null`) descarta epoch 0 também (achado 3, 2ª revisão):
  // `new Date(0)` é 01/01/1970 UTC, que em BRT (UTC-3) vira "31/12 21:00" —
  // uma data que nunca existiu pro usuário e que passava como se fosse real.
  if (!epoch) return null;
  const partes = new Intl.DateTimeFormat("pt-BR", {
    timeZone: "America/Sao_Paulo",
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).formatToParts(new Date(epoch * 1000));
  const parte = (tipo: string) => partes.find((p) => p.type === tipo)?.value ?? "";
  return `${parte("day")}/${parte("month")} ${parte("hour")}:${parte("minute")} BRT`;
}

// Linha de defasagem (achado 3) — nunca entra na mensagem do WhatsApp em si
// (resposta 9 do primo: sem data lá), só nesta prévia do painel.
function formatDefasagem(preview: SojaPreview): string | null {
  if (!preview.porto_data_ref && preview.cbot_atualizado_em == null && preview.dolar_atualizado_em == null) {
    return null;
  }
  const cepea = `CEPEA de ${preview.porto_data_ref ?? "indisponível"}`;
  const cbot = `${preview.cbot_simbolo ?? "CBOT"} pregão de ${formatEpochBRT(preview.cbot_atualizado_em) ?? "indisponível"}`;
  const dolar = `dólar ${formatEpochBRT(preview.dolar_atualizado_em) ?? "indisponível"}`;
  return `${cepea} · ${cbot} · ${dolar}`;
}

export function SojaPreviewPanel({
  preview,
  error,
}: {
  preview: SojaPreview | null;
  error: string | null;
}) {
  return (
    <Panel title="Prévia da mensagem" className="mt-6">
      {error || !preview ? (
        <p className="text-sm text-muted-foreground">Não foi possível carregar a prévia: {error}</p>
      ) : (
        <>
          {/* Fonte do SISTEMA, de propósito — não `.readout` (IBM Plex Mono):
              o emoji precisa renderizar com cor, e a webfont mono do app não
              cobre esses glyphs. */}
          <pre
            className="whitespace-pre-wrap text-sm text-foreground"
            style={{ fontFamily: "system-ui, -apple-system, sans-serif" }}
          >
            {preview.texto}
          </pre>

          {formatDefasagem(preview) && (
            <p className="mt-2 text-xs text-muted-foreground">{formatDefasagem(preview)}</p>
          )}

          {preview.indisponiveis.length > 0 && (
            <p className="mt-3 text-xs text-amber-500">
              Indisponível agora: {preview.indisponiveis.join(", ")}
            </p>
          )}

          {preview.avisos.length > 0 && (
            <ul className="mt-2 space-y-1 text-xs text-amber-500">
              {preview.avisos.map((aviso, i) => (
                <li key={i}>{aviso}</li>
              ))}
            </ul>
          )}
        </>
      )}
    </Panel>
  );
}
