import { CheckCircle2, Clock3, ShieldCheck, Sparkles } from 'lucide-react';
import { Brand } from '@/components/brand';
import { Countdown } from '@/components/ui/countdown';
import { formatMoney } from '@/lib/format';

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
  const dueAt = new Date(Date.now() + 6 * 3_600_000 + 23 * 60_000).toISOString();

  return (
    <div className="min-h-screen bg-canvas lg:grid lg:grid-cols-[1.05fr_0.95fr]">
      <section className="relative hidden overflow-hidden bg-ink-950 px-12 py-10 text-white lg:flex lg:flex-col">
        <div className="absolute inset-0 grid-fade opacity-40" />
        <div className="absolute -right-40 top-24 h-96 w-96 rounded-full bg-brand-500/20 blur-3xl" />
        <div className="absolute -bottom-32 -left-24 h-96 w-96 rounded-full bg-amber-400/10 blur-3xl" />

        <div className="relative z-10">
          <Brand light />
        </div>

        <div className="relative z-10 my-auto max-w-lg py-16">
          <div className="mb-6 inline-flex items-center gap-2 rounded-full border border-white/15 bg-white/5 px-3 py-1.5 text-[11px] font-semibold text-brand-200">
            <Sparkles className="h-3.5 w-3.5" />
            Built for the Paystack merchant
          </div>
          <h1 className="text-balance text-[48px] font-semibold leading-[1.02] tracking-[-0.05em]">
            Defend every payment. Prove every promise.
          </h1>
          <p className="mt-5 max-w-md text-[15px] leading-7 text-ink-300">
            Reconcile payments, turn order history into dispute evidence, and publish a trust
            profile your customers can verify.
          </p>

          <div className="mt-9 space-y-3.5">
            {[
              {
                icon: CheckCircle2,
                text: 'Daily reconciliation that links every payment to an order',
              },
              { icon: ShieldCheck, text: 'AI evidence drafts assembled before the deadline' },
              { icon: Clock3, text: 'Live countdowns, alerts and one-click submission' },
            ].map((item) => (
              <div key={item.text} className="flex items-center gap-3 text-[13px] text-ink-200">
                <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-white/8 ring-1 ring-inset ring-white/10">
                  <item.icon className="h-4 w-4 text-brand-300" />
                </div>
                {item.text}
              </div>
            ))}
          </div>

          <div className="mt-10 rotate-[-1deg] rounded-2xl border border-white/10 bg-white/[0.07] p-4 shadow-float backdrop-blur">
            <div className="flex items-center justify-between">
              <p className="text-[11px] font-semibold uppercase tracking-[0.12em] text-ink-400">
                Dispute requires attention
              </p>
              <Countdown dueAt={dueAt} serverTime={new Date().toISOString()} compact />
            </div>
            <div className="mt-3 flex items-end justify-between">
              <div>
                <p className="text-[11px] text-ink-300">Chargeback · Original order</p>
                <p className="mt-0.5 text-2xl font-semibold tracking-[-0.03em] text-white">
                  {formatMoney(15_000_000, 'NGN')}
                </p>
              </div>
              <div className="rounded-xl bg-brand-500 px-3 py-2 text-[11px] font-bold text-white">
                Review now
              </div>
            </div>
          </div>
        </div>

        <div className="relative z-10 flex items-center justify-between border-t border-white/10 pt-5 text-[11px] text-ink-400">
          <span>Paystack AI Builder Challenge 2026</span>
          <span>Reconcile daily. Defend instantly.</span>
        </div>
      </section>

      <section className="flex min-h-screen flex-col px-5 py-8 sm:px-10 lg:px-16">
        <div className="lg:hidden">
          <Brand />
        </div>
        <div className="mx-auto flex w-full max-w-[420px] flex-1 flex-col justify-center py-10">
          <div className="mb-8">
            <h2 className="text-[32px] font-semibold tracking-[-0.04em] text-ink-950">{title}</h2>
            <p className="mt-2 text-sm leading-6 text-ink-500">{subtitle}</p>
          </div>
          {children}
          {footer ? (
            <div className="mt-8 text-center text-[13px] text-ink-500">{footer}</div>
          ) : null}
        </div>
        <div className="mx-auto flex w-full max-w-[420px] items-center justify-between text-[11px] text-ink-400">
          <span>© {new Date().getFullYear()} DisputePilot</span>
          <span>Secure by design</span>
        </div>
      </section>
    </div>
  );
}
