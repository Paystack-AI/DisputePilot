'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ArrowLeft, KeyRound, PowerOff, UserRound } from 'lucide-react';
import { toast } from 'sonner';
import { apiRequest, errorMessage } from '@/lib/api';
import type { Merchant } from '@/lib/types';
import { useAuthStore } from '@/stores/auth';
import { PageHeader } from '@/components/ui/page-header';
import { Card, CardBody, CardHeader } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { FieldError, FieldHint, Input, Label } from '@/components/ui/input';
import { Modal } from '@/components/ui/modal';
import { PageSkeleton } from '@/components/ui/skeleton';

export default function AccountSettingsPage() {
  const queryClient = useQueryClient();
  const merchantQuery = useQuery({
    queryKey: ['merchant', 'me'],
    queryFn: () => apiRequest<Merchant>('/auth/me'),
  });
  const merchant = merchantQuery.data;

  const [businessName, setBusinessName] = useState('');
  useEffect(() => {
    if (merchant) setBusinessName(merchant.business_name);
  }, [merchant]);

  const profileMutation = useMutation({
    mutationFn: () =>
      apiRequest<Merchant>('/auth/me', {
        method: 'PATCH',
        body: { business_name: businessName.trim() },
      }),
    onSuccess: (updated) => {
      queryClient.setQueryData(['merchant', 'me'], updated);
      queryClient.invalidateQueries({ queryKey: ['trust'] });
      toast.success('Business name updated');
    },
    onError: (error) => toast.error(errorMessage(error)),
  });

  if (merchantQuery.isLoading || !merchant) return <PageSkeleton />;

  return (
    <div className="space-y-6">
      <Link
        href="/settings"
        className="inline-flex items-center gap-2 text-[12px] font-semibold text-ink-500 hover:text-ink-800"
      >
        <ArrowLeft className="h-3.5 w-3.5" /> Settings
      </Link>
      <PageHeader
        eyebrow="Your account"
        title="Account"
        description="Your business profile, password and account status."
      />

      <div className="grid max-w-3xl gap-6">
        <Card>
          <CardHeader
            title="Business profile"
            description="Shown on your public trust page and in dispute evidence."
            action={<UserRound className="h-4 w-4 text-ink-400" />}
          />
          <CardBody className="space-y-4">
            <div>
              <Label htmlFor="business">Business name</Label>
              <Input
                id="business"
                value={businessName}
                onChange={(event) => setBusinessName(event.target.value)}
                maxLength={255}
              />
            </div>
            <div>
              <Label>Sign-in email</Label>
              <Input value={merchant.email ?? merchant.google_email ?? ''} disabled />
              <FieldHint>
                {merchant.google_email ? `Google account: ${merchant.google_email}. ` : ''}
                Contact support to change your sign-in email.
              </FieldHint>
            </div>
            <Button
              onClick={() => profileMutation.mutate()}
              loading={profileMutation.isPending}
              disabled={!businessName.trim() || businessName.trim() === merchant.business_name}
            >
              Save profile
            </Button>
          </CardBody>
        </Card>

        <PasswordCard hasPassword={Boolean(merchant.email)} />
        <DeactivateCard />
      </div>
    </div>
  );
}

function PasswordCard({ hasPassword }: { hasPassword: boolean }) {
  const [current, setCurrent] = useState('');
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const mismatch = confirm.length > 0 && confirm !== password;

  const passwordMutation = useMutation({
    mutationFn: () =>
      apiRequest('/auth/me', {
        method: 'PATCH',
        body: { password, current_password: current },
      }),
    onSuccess: () => {
      setCurrent('');
      setPassword('');
      setConfirm('');
      toast.success('Password changed. Other devices have been signed out.');
    },
    onError: (error) => toast.error(errorMessage(error)),
  });

  return (
    <Card>
      <CardHeader
        title="Change password"
        description="Changing it signs you out everywhere else."
        action={<KeyRound className="h-4 w-4 text-ink-400" />}
      />
      <CardBody className="space-y-4">
        {!hasPassword ? (
          <p className="text-[12px] leading-5 text-ink-500">
            You sign in with Google. To add a password,{' '}
            <Link href="/forgot-password" className="font-semibold text-brand-700">
              reset it by email
            </Link>
            .
          </p>
        ) : (
          <>
            <div>
              <Label htmlFor="current">Current password</Label>
              <Input
                id="current"
                type="password"
                autoComplete="current-password"
                value={current}
                onChange={(event) => setCurrent(event.target.value)}
              />
              <FieldHint>
                Forgotten it?{' '}
                <Link href="/forgot-password" className="font-semibold text-brand-700">
                  Reset by email
                </Link>
              </FieldHint>
            </div>
            <div className="grid gap-4 sm:grid-cols-2">
              <div>
                <Label htmlFor="new">New password</Label>
                <Input
                  id="new"
                  type="password"
                  autoComplete="new-password"
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  minLength={8}
                  maxLength={128}
                />
              </div>
              <div>
                <Label htmlFor="confirm">Confirm new password</Label>
                <Input
                  id="confirm"
                  type="password"
                  autoComplete="new-password"
                  value={confirm}
                  onChange={(event) => setConfirm(event.target.value)}
                  error={mismatch}
                />
                <FieldError>{mismatch ? 'Passwords do not match' : null}</FieldError>
              </div>
            </div>
            <Button
              onClick={() => passwordMutation.mutate()}
              loading={passwordMutation.isPending}
              disabled={password.length < 8 || password !== confirm || !current}
            >
              Update password
            </Button>
          </>
        )}
      </CardBody>
    </Card>
  );
}

function DeactivateCard() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const clear = useAuthStore((state) => state.clear);
  const [open, setOpen] = useState(false);
  const [code, setCode] = useState('');
  const [sent, setSent] = useState(false);

  const requestMutation = useMutation({
    mutationFn: () => apiRequest('/auth/me/deactivate/request', { method: 'POST' }),
    onSuccess: () => {
      setSent(true);
      toast.success('We emailed you a confirmation code');
    },
    onError: (error) => toast.error(errorMessage(error)),
  });

  const deactivateMutation = useMutation({
    mutationFn: () =>
      apiRequest('/auth/me/deactivate', { method: 'POST', body: { otp_code: code } }),
    onSuccess: () => {
      clear();
      queryClient.clear();
      toast.success('Your account is deactivated');
      router.replace('/login');
    },
    onError: (error) => toast.error(errorMessage(error)),
  });

  return (
    <Card className="ring-1 ring-red-100">
      <CardHeader
        title="Deactivate account"
        description="Stops syncing and signs you out everywhere. Your records are kept, and you can reactivate any time by signing in."
        action={<PowerOff className="h-4 w-4 text-danger" />}
      />
      <CardBody>
        <Button variant="danger" onClick={() => setOpen(true)}>
          Deactivate account
        </Button>
      </CardBody>

      <Modal
        open={open}
        onClose={() => setOpen(false)}
        title="Deactivate your account?"
        description="We'll email a code to confirm it's you."
        size="sm"
        footer={
          <>
            <Button variant="ghost" onClick={() => setOpen(false)}>
              Cancel
            </Button>
            {sent ? (
              <Button
                variant="danger"
                disabled={code.length !== 6}
                loading={deactivateMutation.isPending}
                onClick={() => deactivateMutation.mutate()}
              >
                Deactivate
              </Button>
            ) : (
              <Button
                variant="danger"
                loading={requestMutation.isPending}
                onClick={() => requestMutation.mutate()}
              >
                Email me a code
              </Button>
            )}
          </>
        }
      >
        {sent ? (
          <div>
            <Label htmlFor="deactivate-code">Confirmation code</Label>
            <Input
              id="deactivate-code"
              inputMode="numeric"
              autoComplete="one-time-code"
              placeholder="000000"
              maxLength={6}
              value={code}
              onChange={(event) => setCode(event.target.value.replace(/\D/g, '').slice(0, 6))}
              className="text-center text-lg font-semibold tracking-[0.45em]"
            />
            <button
              type="button"
              className="mt-2 text-[12px] font-semibold text-brand-700"
              onClick={() => requestMutation.mutate()}
            >
              Resend code
            </button>
          </div>
        ) : (
          <p className="text-[13px] leading-6 text-ink-600">
            Open disputes keep their deadlines with Paystack. Respond to them before you go.
          </p>
        )}
      </Modal>
    </Card>
  );
}
