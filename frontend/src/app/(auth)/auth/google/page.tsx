'use client';

import { Suspense, useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import { useRouter, useSearchParams } from 'next/navigation';
import { Loader2 } from 'lucide-react';
import { toast } from 'sonner';
import { AuthShell } from '@/components/auth/auth-shell';
import { Alert } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Input, Label } from '@/components/ui/input';
import { apiRequest, errorMessage } from '@/lib/api';
import { useAuthStore } from '@/stores/auth';

const ERRORS: Record<string, string> = {
  access_denied: 'Google sign in was cancelled.',
  oauth_failed: 'Google sign in could not be completed. Please try again.',
  google_email_not_verified: 'Your Google email is not verified. Verify it with Google first.',
  account_deactivated: 'This account is deactivated.',
};

/** Where Google sends the merchant back: ?code (sign in), ?signup_token (new account) or ?error */
function GoogleReturn() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const setSession = useAuthStore((state) => state.setSession);
  const code = searchParams.get('code');
  const signupToken = searchParams.get('signup_token');
  const errorParam = searchParams.get('error');
  const [error, setError] = useState<string | null>(
    errorParam ? (ERRORS[errorParam] ?? errorParam) : null,
  );
  const [businessName, setBusinessName] = useState('');
  const [saving, setSaving] = useState(false);
  const exchanged = useRef(false);

  useEffect(() => {
    // the code is single use: never send it twice (strict mode runs effects twice)
    if (!code || exchanged.current) return;
    exchanged.current = true;
    apiRequest('/auth/google/exchange', {
      method: 'POST',
      body: { code },
      noRefresh: true,
      noRedirect: true,
    })
      .then(() => {
        setSession();
        toast.success('Signed in with Google');
        router.replace('/');
      })
      .catch((err) => setError(errorMessage(err)));
  }, [code, router, setSession]);

  const complete = async (event: React.FormEvent) => {
    event.preventDefault();
    setError(null);
    setSaving(true);
    try {
      await apiRequest('/auth/google/complete', {
        method: 'POST',
        body: { signup_token: signupToken, business_name: businessName.trim() },
        noRefresh: true,
        noRedirect: true,
      });
      setSession();
      toast.success('Your workspace is ready');
      router.replace('/onboarding');
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setSaving(false);
    }
  };

  if (signupToken) {
    return (
      <AuthShell
        title="One last step"
        subtitle="Tell us your business name to finish creating your account."
      >
        <form onSubmit={complete} className="space-y-4">
          {error ? <Alert tone="danger">{error}</Alert> : null}
          <div>
            <Label htmlFor="business">Business name</Label>
            <Input
              id="business"
              value={businessName}
              onChange={(event) => setBusinessName(event.target.value)}
              maxLength={255}
              required
            />
          </div>
          <Button
            type="submit"
            size="lg"
            className="w-full"
            loading={saving}
            disabled={!businessName.trim()}
          >
            Create workspace
          </Button>
        </form>
      </AuthShell>
    );
  }

  if (error || !code) {
    return (
      <AuthShell title="Google sign in" subtitle="We couldn't sign you in.">
        <div className="space-y-4">
          <Alert tone="danger">{error ?? 'The sign in link is incomplete.'}</Alert>
          {errorParam === 'account_deactivated' ? (
            <Link href="/reactivate" className="block">
              <Button size="lg" className="w-full">
                Reactivate account
              </Button>
            </Link>
          ) : null}
          <Link href="/login" className="block">
            <Button variant="outline" size="lg" className="w-full">
              Back to sign in
            </Button>
          </Link>
        </div>
      </AuthShell>
    );
  }

  return <Spinner />;
}

function Spinner() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-canvas">
      <Loader2 className="h-6 w-6 animate-spin text-brand-600" />
    </div>
  );
}

export default function GoogleReturnPage() {
  return (
    <Suspense fallback={<Spinner />}>
      <GoogleReturn />
    </Suspense>
  );
}
