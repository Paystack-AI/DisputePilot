'use client';

import { Suspense, useState } from 'react';
import Link from 'next/link';
import { useRouter, useSearchParams } from 'next/navigation';
import { Loader2, MailCheck } from 'lucide-react';
import { toast } from 'sonner';
import { AuthShell } from '@/components/auth/auth-shell';
import { Alert } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { FieldError, Input, Label } from '@/components/ui/input';
import { apiRequest, errorMessage } from '@/lib/api';

function VerifyForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const initialEmail = searchParams.get('email') ?? '';
  const [email, setEmail] = useState(initialEmail);
  const [code, setCode] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [verifying, setVerifying] = useState(false);
  const [resending, setResending] = useState(false);

  const verify = async (event: React.FormEvent) => {
    event.preventDefault();
    setError(null);
    setVerifying(true);
    try {
      await apiRequest('/auth/verify', {
        method: 'POST',
        body: { email, otp_code: code },
        noRefresh: true,
        noRedirect: true,
      });
      toast.success('Email verified');
      router.push(`/login?verified=1&email=${encodeURIComponent(email)}`);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setVerifying(false);
    }
  };

  const resend = async () => {
    setError(null);
    setResending(true);
    try {
      await apiRequest('/auth/verify/resend', {
        method: 'POST',
        body: { email },
        noRefresh: true,
        noRedirect: true,
      });
      toast.success('A new code is on its way');
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setResending(false);
    }
  };

  return (
    <AuthShell
      title="Verify your email"
      subtitle="Enter the six-digit code we sent to your work email."
      footer={
        <>
          Wrong email?{' '}
          <Link href="/register" className="font-semibold text-brand-700 hover:text-brand-800">
            Start over
          </Link>
        </>
      }
    >
      <div className="mb-6 flex h-14 w-14 items-center justify-center rounded-2xl bg-brand-50 text-brand-700 ring-1 ring-inset ring-brand-200">
        <MailCheck className="h-6 w-6" />
      </div>
      <form onSubmit={verify} className="space-y-4">
        {error ? <Alert tone="danger">{error}</Alert> : null}
        <div>
          <Label htmlFor="email">Email</Label>
          <Input
            id="email"
            type="email"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            required
          />
        </div>
        <div>
          <Label htmlFor="code">Verification code</Label>
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
          <FieldError>
            {code.length > 0 && code.length < 6 ? 'Enter all six digits' : null}
          </FieldError>
        </div>
        <Button
          type="submit"
          size="lg"
          className="w-full"
          loading={verifying}
          disabled={code.length !== 6}
        >
          Verify email
        </Button>
        <Button
          type="button"
          variant="ghost"
          className="w-full"
          loading={resending}
          onClick={resend}
        >
          Resend code
        </Button>
      </form>
    </AuthShell>
  );
}

export default function VerifyPage() {
  return (
    <Suspense
      fallback={
        <div className="flex min-h-screen items-center justify-center bg-canvas">
          <Loader2 className="h-6 w-6 animate-spin text-brand-600" />
        </div>
      }
    >
      <VerifyForm />
    </Suspense>
  );
}
