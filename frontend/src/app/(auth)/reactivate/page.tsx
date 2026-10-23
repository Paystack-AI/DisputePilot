'use client';

import { Suspense, useState } from 'react';
import Link from 'next/link';
import { useRouter, useSearchParams } from 'next/navigation';
import { Loader2, RotateCcw } from 'lucide-react';
import { toast } from 'sonner';
import { AuthShell } from '@/components/auth/auth-shell';
import { Alert } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { FieldHint, Input, Label } from '@/components/ui/input';
import { apiRequest, errorMessage } from '@/lib/api';
import { useAuthStore } from '@/stores/auth';
import { GoogleButton } from '@/components/auth/google-button';

function ReactivateForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const setSession = useAuthStore((state) => state.setSession);
  const [email, setEmail] = useState(searchParams.get('email') ?? '');
  const [code, setCode] = useState('');
  const [sent, setSent] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const request = async () => {
    setError(null);
    setBusy(true);
    try {
      await apiRequest('/auth/reactivate/request', {
        method: 'POST',
        body: { email },
        noRefresh: true,
        noRedirect: true,
      });
      setSent(true);
      toast.success('Check your email for a code');
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const confirm = async () => {
    setError(null);
    setBusy(true);
    try {
      await apiRequest('/auth/reactivate', {
        method: 'POST',
        body: { email, otp_code: code },
        noRefresh: true,
        noRedirect: true,
      });
      setSession();
      toast.success('Welcome back. Your account is active again.');
      router.replace('/');
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <AuthShell
      title="Reactivate your account"
      subtitle="Your account was deactivated. Confirm it's you and everything is restored as you left it."
      footer={
        <>
          <Link href="/login" className="font-semibold text-brand-700 hover:text-brand-800">
            Back to sign in
          </Link>
        </>
      }
    >
      <div className="mb-6 flex h-14 w-14 items-center justify-center rounded-xl bg-brand-50 text-brand-700 ring-1 ring-inset ring-brand-200">
        <RotateCcw className="h-6 w-6" />
      </div>
      <form
        onSubmit={(event) => {
          event.preventDefault();
          if (sent) confirm();
          else request();
        }}
        className="space-y-4"
      >
        {error ? <Alert tone="danger">{error}</Alert> : null}
        <div>
          <Label htmlFor="email">Email</Label>
          <Input
            id="email"
            type="email"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            disabled={sent}
            required
          />
        </div>
        {sent ? (
          <div>
            <Label htmlFor="code">Code from your email</Label>
            <Input
              id="code"
              inputMode="numeric"
              autoComplete="one-time-code"
              placeholder="000000"
              maxLength={6}
              value={code}
              onChange={(event) => setCode(event.target.value.replace(/\D/g, '').slice(0, 6))}
              className="text-center text-lg font-semibold tracking-[0.45em]"
              required
            />
            <FieldHint>
              If the code does not arrive, check your spam or junk folder before resending.
            </FieldHint>
          </div>
        ) : null}
        <Button
          type="submit"
          size="lg"
          className="w-full"
          loading={busy}
          disabled={sent && code.length !== 6}
        >
          {sent ? 'Reactivate account' : 'Email me a code'}
        </Button>
        {sent ? (
          <Button type="button" variant="ghost" className="w-full" onClick={request}>
            Resend code
          </Button>
        ) : null}
      </form>
      <div className="mt-5">
        <GoogleButton intent="reactivate" label="Reactivate with Google" />
      </div>
    </AuthShell>
  );
}

export default function ReactivatePage() {
  return (
    <Suspense
      fallback={
        <div className="flex min-h-screen items-center justify-center bg-canvas">
          <Loader2 className="h-6 w-6 animate-spin text-brand-600" />
        </div>
      }
    >
      <ReactivateForm />
    </Suspense>
  );
}
