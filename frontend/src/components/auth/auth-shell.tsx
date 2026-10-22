import { CalendarCheck, ShieldCheck, Zap } from 'lucide-react';
import { Brand } from '@/components/brand';
import { ThemeToggle } from '@/components/theme-toggle';

const points = [
  { icon: Zap, text: 'Evidence drafted for you, ready before the Paystack deadline' },
  { icon: CalendarCheck, text: 'Daily reconciliation keeps every payment dispute-ready' },
  { icon: ShieldCheck, text: 'TrustLayer turns your track record into customer trust' },
];

export function AuthShell({
  children,
  title,
  subtitle,
  footer,
}: {
  children: React.ReactNode;
  title: string;
  subtitle: string;
  footer?: React.ReactNode;
}) {
  return (
    <div className="min-h-screen bg-canvas lg:grid lg:grid-cols-[minmax(0,5fr)_minmax(0,6fr)]">
      <section className="hidden flex-col justify-between bg-navy px-12 py-10 text-white lg:flex">
        <Brand light />

        <div className="max-w-md">
          <h1 className="text-[28px] font-semibold leading-[1.2] tracking-[-0.02em]">
            Reconcile daily. Defend instantly. Never lose a dispute again.
          </h1>
          <ul className="mt-8 space-y-4">
            {points.map((point) => (
              <li key={point.text} className="flex items-start gap-3 text-[14px] text-white/75">
                <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-white/10">
                  <point.icon className="h-3.5 w-3.5 text-white" />
                </span>
                <span className="pt-1">{point.text}</span>
              </li>
            ))}
          </ul>
        </div>

        <figure className="max-w-md border-t border-white/10 pt-6">
          <blockquote className="text-[13px] leading-6 text-white/70">
            &ldquo;We used to lose money to chargebacks because we could not respond in time. Now
            our evidence is always ready.&rdquo;
          </blockquote>
          <figcaption className="mt-2 text-[12px] text-white/50">Amara, Lagos</figcaption>
        </figure>
      </section>

      <section className="flex min-h-screen flex-col px-5 py-6 sm:px-10">
        <div className="flex items-center justify-between">
          <div className="lg:invisible">
            <Brand />
          </div>
          <ThemeToggle />
        </div>
        <div className="mx-auto flex w-full max-w-[380px] flex-1 flex-col justify-center py-10">
          <div className="mb-7">
            <h2 className="text-[24px] font-semibold tracking-[-0.02em] text-ink-950">{title}</h2>
            <p className="mt-1 text-[13px] leading-5 text-ink-500">{subtitle}</p>
          </div>
          {children}
          {footer ? (
            <div className="mt-7 text-center text-[13px] text-ink-500">{footer}</div>
          ) : null}
        </div>
        <p className="text-center text-[11px] text-ink-400">
          © {new Date().getFullYear()} DisputePilot
        </p>
      </section>
    </div>
  );
}
