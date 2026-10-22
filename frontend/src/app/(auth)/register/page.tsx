'use client';

import { useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { Eye, EyeOff } from 'lucide-react';
import { toast } from 'sonner';
import { AuthShell } from '@/components/auth/auth-shell';
import { GoogleButton } from '@/components/auth/google-button';
import { Alert } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { FieldError, FieldHint, Input, Label } from '@/components/ui/input';
import { apiRequest, errorMessage } from '@/lib/api';

const schema = z
  .object({
    business_name: z.string().min(2, 'Enter your business name').max(255),
    email: z.string().email('Enter a valid email address'),
    password: z.string().min(8, 'Password must be at least 8 characters').max(128),
    confirm_password: z.string(),
    terms: z.literal(true, {
      errorMap: () => ({ message: 'Accept the merchant data use agreement to continue' }),
    }),
  })
  .refine((values) => values.password === values.confirm_password, {
    message: 'Passwords do not match',
    path: ['confirm_password'],
  });

type FormValues = z.infer<typeof schema>;

export default function RegisterPage() {
  const router = useRouter();
  const [showPassword, setShowPassword] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: {
      business_name: '',
      email: '',
      password: '',
      confirm_password: '',
    },
  });

  const onSubmit = async (values: FormValues) => {
    setFormError(null);
    try {
      await apiRequest('/auth/register', {
        method: 'POST',
        body: {
          business_name: values.business_name,
          email: values.email,
          password: values.password,
        },
        noRefresh: true,
        noRedirect: true,
      });
      toast.success('Verification code sent');
      router.push(`/verify?email=${encodeURIComponent(values.email)}`);
    } catch (error) {
      setFormError(errorMessage(error));
    }
  };

  return (
    <AuthShell
      title="Create your workspace"
      subtitle="Connect Paystack, reconcile your sales and build evidence continuously."
      footer={
        <>
          Already have an account?{' '}
          <Link href="/login" className="font-semibold text-brand-700 hover:text-brand-800">
            Sign in
          </Link>
        </>
      }
    >
      <form onSubmit={handleSubmit(onSubmit)} className="space-y-4">
        {formError ? <Alert tone="danger">{formError}</Alert> : null}

        <div>
          <Label htmlFor="business_name">Business name</Label>
          <Input
            id="business_name"
            autoComplete="organization"
            placeholder="Amara Furniture"
            error={Boolean(errors.business_name)}
            {...register('business_name')}
          />
          <FieldError>{errors.business_name?.message}</FieldError>
        </div>

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
          <Label htmlFor="password">Password</Label>
          <div className="relative">
            <Input
              id="password"
              type={showPassword ? 'text' : 'password'}
              autoComplete="new-password"
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

        <div>
          <Label htmlFor="confirm_password">Confirm password</Label>
          <Input
            id="confirm_password"
            type={showPassword ? 'text' : 'password'}
            autoComplete="new-password"
            placeholder="Repeat your password"
            error={Boolean(errors.confirm_password)}
            {...register('confirm_password')}
          />
          <FieldError>{errors.confirm_password?.message}</FieldError>
        </div>

        <label className="flex items-start gap-2.5 rounded-xl border border-line bg-white px-3.5 py-3 text-[12px] leading-5 text-ink-600">
          <input
            type="checkbox"
            className="mt-0.5 h-4 w-4 rounded border-ink-300 text-brand-600 focus:ring-brand-400"
            {...register('terms')}
          />
          <span>
            I accept the merchant data use agreement and understand that DisputePilot only reads
            transactions, disputes and order evidence from Paystack.
          </span>
        </label>
        <FieldError>{errors.terms?.message}</FieldError>
        <FieldHint>
          We will email a six-digit code to verify your account. If it does not arrive, check your
          spam or junk folder.
        </FieldHint>

        <Button type="submit" size="lg" className="w-full" loading={isSubmitting}>
          Create account
        </Button>
      </form>
      <div className="mt-5">
        <GoogleButton label="Sign up with Google" />
      </div>
    </AuthShell>
  );
}
