'use client';

import { Suspense, useState } from 'react';
import Link from 'next/link';
import { useRouter, useSearchParams } from 'next/navigation';
import { Loader2, LockKeyhole } from 'lucide-react';
import { toast } from 'sonner';
import { AuthShell } from '@/components/auth/auth-shell';
import { Alert } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { FieldError, FieldHint, Input, Label } from '@/components/ui/input';
import { apiRequest, errorMessage } from '@/lib/api';

function ResetForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [email, setEmail] = useState(searchParams.get('email') ?? '');
  const [code, setCode] = useState('');
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [resending, setResending] = useState(false);

  const mismatch = confirm.length > 0 && confirm !== password;
  const valid = code.length === 6 && password.length >= 8 && password === confirm;

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setError(null);
    setSaving(true);
    try {
      await apiRequest('/auth/password-reset/confirm', {
        method: 'POST',
        body: { email, otp_code: code, password },
        noRefresh: true,
        noRedirect: true,
      });
      toast.success('Password updated. Sign in with your new password.');
      router.push(`/login?email=${encodeURIComponent(email)}`);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setSaving(false);
    }
  };

  const resend = async () => {
    setError(null);
    setResending(true);
    try {
      await apiRequest('/auth/password-reset', {
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
      title="Choose a new password"
      subtitle="Enter the code from your email and your new password. Other devices will be signed out."
      footer={
        <>
          <Link href="/login" className="font-semibold text-brand-700 hover:text-brand-800">
            Back to sign in
          </Link>
        </>
      }
    >
      <div className="mb-6 flex h-14 w-14 items-center justify-center rounded-2xl bg-brand-50 text-brand-700 ring-1 ring-inset ring-brand-200">
        <LockKeyhole className="h-6 w-6" />
      </div>
      <form onSubmit={submit} className="space-y-4">
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
          <Label htmlFor="code">Reset code</Label>
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
        </div>
        <div>
          <Label htmlFor="password">New password</Label>
          <Input
            id="password"
            type="password"
            autoComplete="new-password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            minLength={8}
            maxLength={128}
            required
          />
          <FieldHint>At least 8 characters.</FieldHint>
        </div>
        <div>
          <Label htmlFor="confirm">Confirm password</Label>
          <Input
            id="confirm"
            type="password"
            autoComplete="new-password"
            value={confirm}
            onChange={(event) => setConfirm(event.target.value)}
            error={mismatch}
            required
          />
          <FieldError>{mismatch ? 'Passwords do not match' : null}</FieldError>
        </div>
        <Button type="submit" size="lg" className="w-full" loading={saving} disabled={!valid}>
          Update password
        </Button>
        <Button
          type="button"
          variant="ghost"
          className="w-full"
          loading={resending}
          disabled={!email}
          onClick={resend}
        >
          Resend code
        </Button>
      </form>
    </AuthShell>
  );
}

export default function ResetPasswordPage() {
  return (
    <Suspense
      fallback={
        <div className="flex min-h-screen items-center justify-center bg-canvas">
          <Loader2 className="h-6 w-6 animate-spin text-brand-600" />
        </div>
      }
    >
      <ResetForm />
    </Suspense>
  );
}
