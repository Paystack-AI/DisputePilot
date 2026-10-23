'use client';

import { Suspense, useState } from 'react';
import Link from 'next/link';
import { useRouter, useSearchParams } from 'next/navigation';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { Eye, EyeOff, Loader2 } from 'lucide-react';
import { toast } from 'sonner';
import { AuthShell } from '@/components/auth/auth-shell';
import { GoogleButton } from '@/components/auth/google-button';
import { Alert } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { FieldError, Input, Label } from '@/components/ui/input';
import { ApiError, apiRequest, errorMessage } from '@/lib/api';
import { useAuthStore } from '@/stores/auth';

const schema = z.object({
  email: z.string().email('Enter a valid email address'),
  password: z.string().min(8, 'Password must be at least 8 characters'),
});

type FormValues = z.infer<typeof schema>;

function LoginForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const setSession = useAuthStore((state) => state.setSession);
  const [showPassword, setShowPassword] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  const next = searchParams.get('next');
  const verified = searchParams.get('verified');

  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: { email: searchParams.get('email') ?? '', password: '' },
  });

  const onSubmit = async (values: FormValues) => {
    setFormError(null);
    try {
      await apiRequest('/auth/login', {
        method: 'POST',
        body: values,
        noRefresh: true,
        noRedirect: true,
      });
      setSession();
      toast.success('Welcome back');
      router.replace(next && next.startsWith('/') ? next : '/');
    } catch (error) {
      if (error instanceof ApiError && error.code === 'EMAIL_NOT_VERIFIED') {
        router.push(`/verify?email=${encodeURIComponent(values.email)}`);
        return;
      }
      if (error instanceof ApiError && error.code === 'ACCOUNT_DEACTIVATED') {
        router.push(`/reactivate?email=${encodeURIComponent(values.email)}`);
        return;
      }
      setFormError(errorMessage(error));
    }
  };

  return (
    <AuthShell
      title="Welcome back"
      subtitle="Sign in to reconcile payments, defend disputes and manage your trust profile."
      footer={
        <>
          New to DisputePilot?{' '}
          <Link href="/register" className="font-semibold text-brand-700 hover:text-brand-800">
            Create an account
          </Link>
        </>
      }
    >
      <form onSubmit={handleSubmit(onSubmit)} className="space-y-4">
        {verified ? (
          <Alert tone="success" title="Email verified">
            Sign in with your password to open your workspace.
          </Alert>
        ) : null}
        {formError ? <Alert tone="danger">{formError}</Alert> : null}

        <div>
          <Label htmlFor="email">Work email</Label>
          <Input
            id="email"
            type="email"
            autoComplete="email"
            placeholder="you@business.com"
            error={Boolean(errors.email)}
            {...register('email')}
          />
          <FieldError>{errors.email?.message}</FieldError>
        </div>

        <div>
          <div className="flex items-center justify-between">
            <Label htmlFor="password">Password</Label>
            <Link
              href="/forgot-password"
              className="mb-1.5 text-[12px] font-semibold text-brand-700 hover:text-brand-800"
            >
              Forgot password?
            </Link>
          </div>
          <div className="relative">
            <Input
              id="password"
              type={showPassword ? 'text' : 'password'}
              autoComplete="current-password"
              placeholder="At least 8 characters"
              className="pr-11"
              error={Boolean(errors.password)}
              {...register('password')}
            />
            <button
              type="button"
              className="absolute right-1 top-1 flex h-9 w-9 items-center justify-center rounded-lg text-ink-400 hover:bg-ink-50 hover:text-ink-700"
              onClick={() => setShowPassword((value) => !value)}
              aria-label={showPassword ? 'Hide password' : 'Show password'}
            >
              {showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
            </button>
          </div>
          <FieldError>{errors.password?.message}</FieldError>
        </div>

        <Button type="submit" size="lg" className="w-full" loading={isSubmitting}>
          {isSubmitting ? (
            'Signing in'
          ) : (
            <>
              Sign in <ArrowIcon />
            </>
          )}
        </Button>

        <p className="text-center text-[11px] leading-5 text-ink-400">
          Your Paystack secret key is encrypted and never exposed to the browser.
        </p>
      </form>
      <div className="mt-5">
        <GoogleButton />
      </div>
    </AuthShell>
  );
}

function ArrowIcon() {
  return (
    <span className="ml-1 inline-flex h-5 w-5 items-center justify-center rounded-full bg-white/15">
      <svg
        viewBox="0 0 24 24"
        className="h-3 w-3"
        fill="none"
        stroke="currentColor"
        strokeWidth="2.5"
      >
        <path d="M5 12h14M13 6l6 6-6 6" />
      </svg>
    </span>
  );
}

export default function LoginPage() {
  return (
    <Suspense
      fallback={
        <div className="flex min-h-screen items-center justify-center bg-canvas">
          <Loader2 className="h-6 w-6 animate-spin text-brand-600" />
        </div>
      }
    >
      <LoginForm />
    </Suspense>
  );
}
