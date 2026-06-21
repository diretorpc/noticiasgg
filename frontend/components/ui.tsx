import Link from "next/link";

export function PageHeader({
  eyebrow,
  title,
  children,
}: {
  eyebrow: string;
  title: string;
  children?: React.ReactNode;
}) {
  return (
    <header className="mb-8">
      <span className="eyebrow">{eyebrow}</span>
      <h1 className="mt-2 text-3xl font-semibold tracking-tight text-foreground">
        {title}
      </h1>
      {children && (
        <p className="mt-2 max-w-xl text-sm text-muted-foreground">{children}</p>
      )}
    </header>
  );
}

export function Panel({
  title,
  children,
  className = "",
}: {
  title?: string;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <section className={`rounded-lg border border-border bg-card shadow-sm ${className}`}>
      {title && (
        <h2 className="border-b border-border px-5 py-3 text-xs font-medium uppercase tracking-wider text-muted-foreground">
          {title}
        </h2>
      )}
      <div className="p-5">{children}</div>
    </section>
  );
}

export function Field({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-4 border-b border-border py-2.5 last:border-0">
      <dt className="eyebrow shrink-0">{label}</dt>
      <dd className="readout text-right text-sm">{value}</dd>
    </div>
  );
}

export function Chip({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-border bg-muted/40 px-3 py-2">
      <span className="eyebrow block">{label}</span>
      <span className="readout mt-0.5 block text-sm text-primary">{value}</span>
    </div>
  );
}

export function NavCard({
  href,
  eyebrow,
  title,
  desc,
}: {
  href: string;
  eyebrow: string;
  title: string;
  desc: string;
}) {
  return (
    <Link
      href={href}
      className="group rounded-lg border border-border bg-card p-5 shadow-sm transition-colors hover:border-primary/50"
    >
      <span className="eyebrow">{eyebrow}</span>
      <p className="mt-2 text-lg font-medium text-foreground">
        {title}
        <span className="ml-2 inline-block text-primary transition-transform group-hover:translate-x-0.5">
          →
        </span>
      </p>
      <p className="mt-1 text-sm text-muted-foreground">{desc}</p>
    </Link>
  );
}
