'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import { href } from '@/lib/links';
import { useParams } from 'next/navigation';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useDropzone } from 'react-dropzone';
import {
  AlertTriangle,
  ArrowLeft,
  CheckCircle2,
  Download,
  FileText,
  Gavel,
  ImagePlus,
  Loader2,
  PackageCheck,
  Send,
  ShieldCheck,
  Sparkles,
  Trash2,
  Truck,
  UserRound,
  Wand2,
} from 'lucide-react';
import { toast } from 'sonner';
import { ApiError, apiBlob, apiRequest, errorMessage, uploadFiles } from '@/lib/api';
import { cn } from '@/lib/cn';
import { formatDate, formatDateTime, formatMoney, percent, timeAgo, titleCase } from '@/lib/format';
import type { DisputeDetail, EvidenceDocumentRef, FulfillmentEvidence } from '@/lib/types';
import { CATEGORY_LABELS, STATUS_LABELS, TRUST_LABELS } from '@/lib/constants';
import { PageSkeleton } from '@/components/ui/skeleton';
import { Alert } from '@/components/ui/alert';
import { Badge, statusTone } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardBody, CardHeader } from '@/components/ui/card';
import { Countdown } from '@/components/ui/countdown';
import { Modal } from '@/components/ui/modal';
import { Textarea, Input, Label } from '@/components/ui/input';
import { AuthImage } from '@/components/ui/auth-image';

type SavePayload = {
  version: number;
  narrative: string;
  conclusion: string;
  documents: EvidenceDocumentRef[];
  reason: string;
};

export default function DisputeDetailPage() {
  const params = useParams<{ id: string }>();
  const queryClient = useQueryClient();
  const [narrative, setNarrative] = useState('');
  const [conclusion, setConclusion] = useState('');
  const [documents, setDocuments] = useState<EvidenceDocumentRef[]>([]);
  const [reason, setReason] = useState('Merchant review');
  const [submitOpen, setSubmitOpen] = useState(false);
  const [acceptOpen, setAcceptOpen] = useState(false);
  const [acceptMessage, setAcceptMessage] = useState('');
  const [uploading, setUploading] = useState(false);
  const [preview, setPreview] = useState<{ id: string; name: string } | null>(null);

  const detailQuery = useQuery({
    queryKey: ['dispute', params.id],
    queryFn: () => apiRequest<DisputeDetail>(`/disputes/${params.id}`),
    enabled: Boolean(params.id),
    refetchInterval: (query) => {
      const data = query.state.data;
      if (!data) return false;
      if (data.evidence_state === 'generating') return 3000;
      if (data.submission_state === 'submitting' || data.submission_state === 'accepting')
        return 3000;
      return false;
    },
  });

  const detail = detailQuery.data;

  useEffect(() => {
    if (!detail) return;
    setNarrative(detail.evidence.narrative ?? '');
    setConclusion(detail.evidence.conclusion ?? '');
    setDocuments(detail.evidence.supporting_documents);
  }, [detail]);

  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ['dispute', params.id] });
    queryClient.invalidateQueries({ queryKey: ['disputes'] });
    queryClient.invalidateQueries({ queryKey: ['dashboard'] });
  };

  const generateMutation = useMutation({
    mutationFn: () => apiRequest(`/disputes/${params.id}/generate-evidence`, { method: 'POST' }),
    onSuccess: () => {
      toast.success('Evidence generation started');
      refresh();
    },
    onError: (error) => toast.error(errorMessage(error)),
  });

  const saveMutation = useMutation({
    mutationFn: (payload: SavePayload) =>
      apiRequest<DisputeDetail>(`/disputes/${params.id}/evidence`, {
        method: 'PUT',
        body: payload,
      }),
    onSuccess: (updated) => {
      toast.success('Evidence draft saved');
      queryClient.setQueryData(['dispute', params.id], updated);
    },
    onError: (error) => {
      if (error instanceof ApiError && error.code === 'EVIDENCE_VERSION_CONFLICT') {
        toast.error('This draft changed elsewhere. Reloading the latest version.');
        detailQuery.refetch();
        return;
      }
      toast.error(errorMessage(error));
    },
  });

  const submitMutation = useMutation({
    mutationFn: () =>
      apiRequest(`/disputes/${params.id}/submit`, {
        method: 'POST',
        body: { version: detail?.evidence.version ?? 0 },
      }),
    onSuccess: () => {
      setSubmitOpen(false);
      toast.success('Evidence submitted to Paystack');
      refresh();
    },
    onError: (error) => toast.error(errorMessage(error)),
  });

  const acceptMutation = useMutation({
    mutationFn: () =>
      apiRequest(`/disputes/${params.id}/accept`, {
        method: 'POST',
        body: acceptMessage ? { message: acceptMessage } : {},
      }),
    onSuccess: () => {
      setAcceptOpen(false);
      toast.success('Dispute accepted');
      refresh();
    },
    onError: (error) => toast.error(errorMessage(error)),
  });

  const onDrop = useCallback(async (files: File[]) => {
    if (!files.length) return;
    setUploading(true);
    try {
      const uploaded = await uploadFiles(files);
      setDocuments((current) => [
        ...current,
        ...uploaded.map((file) => ({
          file_id: file.id,
          file_name: file.file_name,
          caption: null,
          source: 'merchant' as const,
        })),
      ]);
      toast.success(`${uploaded.length} file${uploaded.length === 1 ? '' : 's'} uploaded`);
    } catch (error) {
      toast.error(errorMessage(error));
    } finally {
      setUploading(false);
    }
  }, []);

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: { 'image/*': ['.jpg', '.jpeg', '.png', '.webp', '.heic'] },
    maxFiles: 10,
  });

  const downloadPdf = async () => {
    try {
      const blob = await apiBlob(`/disputes/${params.id}/evidence-pdf`);
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement('a');
      anchor.href = url;
      anchor.download = `dispute-${detail?.paystack_dispute_id ?? params.id}-evidence.pdf`;
      anchor.click();
      URL.revokeObjectURL(url);
    } catch (error) {
      toast.error(errorMessage(error));
    }
  };

  if (detailQuery.isLoading) return <PageSkeleton />;
  if (detailQuery.isError || !detail) {
    return (
      <div className="space-y-6">
        <Link href="/disputes">
          <Button variant="outline">
            <ArrowLeft className="h-4 w-4" /> Back to disputes
          </Button>
        </Link>
        <Alert tone="danger" title="Could not load dispute">
          {errorMessage(detailQuery.error)}
        </Alert>
      </div>
    );
  }

  const can = (action: string) => detail.allowed_actions.includes(action as never);
  const editable = can('edit_evidence');
  const evidence = detail.evidence;
  const quality = evidence.quality ?? detail.quality;
  const generated = Boolean(evidence.narrative);
  const documentsChanged =
    JSON.stringify(documents.map((document) => document.file_id).sort()) !==
    JSON.stringify(evidence.supporting_documents.map((document) => document.file_id).sort());
  const dirty =
    narrative !== (evidence.narrative ?? '') ||
    conclusion !== (evidence.conclusion ?? '') ||
    documentsChanged;

  return (
    <div className="space-y-6">
      <Link
        href="/disputes"
        className="inline-flex items-center gap-2 text-[12px] font-semibold text-ink-500 hover:text-ink-800"
      >
        <ArrowLeft className="h-3.5 w-3.5" /> All disputes
      </Link>

      <div className="flex flex-col justify-between gap-4 lg:flex-row lg:items-end">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <Badge tone={statusTone(detail.status)}>{STATUS_LABELS[detail.status]}</Badge>
            <Badge tone={detail.urgency === 'critical' ? 'danger' : 'warning'}>
              {detail.category ? CATEGORY_LABELS[detail.category] : 'Unclassified'}
            </Badge>
            {detail.submission_flow ? (
              <span className="text-[11px] font-medium text-ink-500">
                {titleCase(detail.submission_flow)}
              </span>
            ) : null}
          </div>
          <h1 className="mt-3 text-[24px] font-semibold tracking-[-0.04em] text-ink-950">
            {formatMoney(detail.amount, detail.currency)}
          </h1>
          <p className="mt-1 text-sm text-ink-500">
            {detail.customer ? (
              <Link href={href.customer(detail.customer.id)} className="link">
                {detail.customer.name ?? detail.customer.email ?? 'Customer'}
              </Link>
            ) : (
              'Customer'
            )}{' '}
            ·{' '}
            <Link
              href={href.transaction(detail.transaction_reference)}
              className="link font-mono text-[12px]"
            >
              {detail.transaction_reference}
            </Link>
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2.5">
          <Countdown dueAt={detail.due_at} serverTime={detail.server_time} />
          {can('download_pdf') ? (
            <Button variant="outline" onClick={downloadPdf}>
              <Download className="h-4 w-4" /> Evidence PDF
            </Button>
          ) : null}
          {detail.recommendation === 'accept' && can('accept') ? (
            <Button variant="danger" onClick={() => setAcceptOpen(true)}>
              Accept dispute
            </Button>
          ) : null}
          {can('generate_evidence') ? (
            <Button onClick={() => generateMutation.mutate()} loading={generateMutation.isPending}>
              <Sparkles className="h-4 w-4" /> Generate evidence
            </Button>
          ) : null}
          {can('submit') ? (
            <Button onClick={() => setSubmitOpen(true)}>
              <Send className="h-4 w-4" /> Submit evidence
            </Button>
          ) : null}
        </div>
      </div>

      {detail.recommendation === 'accept' ? (
        <Alert tone="warning" title="This claim looks valid">
          The transaction facts suggest a duplicate or erroneous charge. Accepting refunds the
          customer and closes the dispute.
        </Alert>
      ) : null}

      {detail.submission_state === 'submitting' || detail.submission_state === 'accepting' ? (
        <Alert tone="info" title="Sending your response to Paystack">
          This usually completes in a few seconds. The status here updates automatically.
        </Alert>
      ) : null}

      {detail.submission_state === 'failed' ? (
        <Alert tone="danger" title="Submission failed">
          {detail.submission_error ??
            'Paystack rejected the response. Review the evidence and retry.'}
        </Alert>
      ) : null}

      {detail.evidence_state === 'generating' ? (
        <div className="surface flex items-center gap-3 px-5 py-4">
          <Loader2 className="h-5 w-5 animate-spin text-brand-600" />
          <div>
            <p className="text-[13px] font-semibold text-ink-900">Building your evidence draft</p>
            <p className="text-[12px] text-ink-500">
              Classifying the claim, assembling order facts and scoring the narrative.
            </p>
          </div>
        </div>
      ) : null}

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-[1.5fr_1fr]">
        <div className="space-y-6">
          <Card>
            <CardHeader
              title="Evidence draft"
              description={
                generated
                  ? `Version ${evidence.version} · ${evidence.generation_source ? titleCase(evidence.generation_source) : 'Merchant edit'}`
                  : 'Generate a draft or write your response from scratch.'
              }
              action={
                quality ? (
                  <Badge
                    tone={
                      quality.label === 'strong'
                        ? 'success'
                        : quality.label === 'moderate'
                          ? 'warning'
                          : 'danger'
                    }
                  >
                    {titleCase(quality.label)} · {quality.score}
                  </Badge>
                ) : null
              }
            />
            <CardBody className="space-y-5">
              <div>
                <div className="mb-2 flex items-center justify-between">
                  <Label htmlFor="narrative" className="mb-0">
                    Narrative to the bank
                  </Label>
                  <span className="text-[11px] text-ink-400">{narrative.length} characters</span>
                </div>
                <Textarea
                  id="narrative"
                  rows={12}
                  value={narrative}
                  onChange={(event) => setNarrative(event.target.value)}
                  placeholder="The evidence narrative will appear here once generated."
                  disabled={!editable}
                  className="min-h-64"
                />
              </div>

              <div>
                <Label htmlFor="conclusion">Conclusion</Label>
                <Textarea
                  id="conclusion"
                  rows={4}
                  value={conclusion}
                  onChange={(event) => setConclusion(event.target.value)}
                  placeholder="A concise closing statement supporting the response."
                  disabled={!editable}
                />
              </div>

              {quality?.suggestions.length ? (
                <div className="rounded-xl border border-amber-200 bg-amber-50/60 p-4">
                  <div className="flex items-center gap-2">
                    <Wand2 className="h-4 w-4 text-amber-700" />
                    <p className="text-[12px] font-semibold text-amber-900">AI suggestions</p>
                  </div>
                  <ul className="mt-2 space-y-1.5">
                    {quality.suggestions.map((suggestion) => (
                      <li
                        key={suggestion}
                        className="flex gap-2 text-[12px] leading-5 text-amber-800"
                      >
                        <span className="mt-2 h-1 w-1 shrink-0 rounded-full bg-amber-600" />
                        {suggestion}
                      </li>
                    ))}
                  </ul>
                </div>
              ) : null}

              <div>
                <div className="mb-2 flex items-center justify-between">
                  <p className="text-[13px] font-semibold text-ink-800">Supporting documents</p>
                  <span className="text-[11px] text-ink-400">{documents.length} attached</span>
                </div>
                <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-3">
                  {documents.map((document) => (
                    <div
                      key={document.file_id}
                      className="group relative overflow-hidden rounded-xl border border-brand-200 bg-ink-50"
                    >
                      {document.source === 'merchant' ? (
                        <AuthImage
                          fileId={document.file_id}
                          alt={document.file_name}
                          className="h-28 w-full"
                          onClick={() =>
                            setPreview({ id: document.file_id, name: document.file_name })
                          }
                        />
                      ) : (
                        <div className="flex h-28 w-full items-center justify-center text-ink-400">
                          <ImagePlus className="h-5 w-5" />
                        </div>
                      )}
                      <div className="border-t border-line bg-surface px-2.5 py-2">
                        <p className="truncate text-[10px] font-medium text-ink-700">
                          {document.file_name}
                        </p>
                        <p className="text-[9px] uppercase tracking-wide text-ink-400">
                          {document.source}
                        </p>
                      </div>
                      {editable && document.source === 'merchant' ? (
                        <button
                          type="button"
                          className="absolute right-1.5 top-1.5 flex h-7 w-7 items-center justify-center rounded-lg bg-surface/90 text-danger opacity-0 shadow transition group-hover:opacity-100"
                          onClick={() =>
                            setDocuments((current) =>
                              current.filter((item) => item.file_id !== document.file_id),
                            )
                          }
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                        </button>
                      ) : null}
                    </div>
                  ))}
                </div>

                {editable ? (
                  <div
                    {...getRootProps()}
                    className={cn(
                      'mt-3 flex cursor-pointer flex-col items-center justify-center rounded-xl border border-dashed px-4 py-6 text-center transition',
                      isDragActive
                        ? 'border-brand-400 bg-brand-50'
                        : 'border-line bg-surface hover:border-brand-300 hover:bg-brand-50/30',
                    )}
                  >
                    <input {...getInputProps()} />
                    {uploading ? (
                      <Loader2 className="h-5 w-5 animate-spin text-brand-600" />
                    ) : (
                      <ImagePlus className="h-5 w-5 text-ink-400" />
                    )}
                    <p className="mt-2 text-[12px] font-semibold text-ink-700">
                      Drop images here or click to upload
                    </p>
                    <p className="mt-0.5 text-[11px] text-ink-400">
                      JPEG, PNG, WebP or HEIC · visual proof strengthens the response
                    </p>
                  </div>
                ) : null}
              </div>

              {editable ? (
                <div className="flex flex-col gap-3 border-t border-line pt-4 sm:flex-row sm:items-end sm:justify-between">
                  <div className="flex-1">
                    <Label htmlFor="reason">Reason for change</Label>
                    <Input
                      id="reason"
                      value={reason}
                      onChange={(event) => setReason(event.target.value)}
                      placeholder="e.g. Added the courier delivery photo"
                    />
                  </div>
                  <Button
                    onClick={() =>
                      saveMutation.mutate({
                        version: evidence.version,
                        narrative,
                        conclusion,
                        documents,
                        reason,
                      })
                    }
                    loading={saveMutation.isPending}
                    disabled={!dirty || !narrative.trim() || !reason.trim()}
                  >
                    Save draft
                  </Button>
                </div>
              ) : null}
            </CardBody>
          </Card>

          <Card>
            <CardHeader title="Why this claim is being disputed" />
            <CardBody>
              <p className="text-sm leading-7 text-ink-700">
                {detail.reason ?? 'Paystack did not include a written reason for this dispute.'}
              </p>
              {detail.special_instructions ? (
                <div className="mt-4 rounded-xl bg-ink-50 p-3.5">
                  <p className="text-[11px] font-semibold uppercase tracking-[0.08em] text-ink-500">
                    Special instructions
                  </p>
                  <p className="mt-1 text-[13px] leading-6 text-ink-700">
                    {detail.special_instructions}
                  </p>
                </div>
              ) : null}
            </CardBody>
          </Card>
        </div>

        <div className="space-y-6">
          <ContextCard title="Transaction" icon={<FileText className="h-4 w-4" />}>
            <DetailRow
              label="Amount"
              value={formatMoney(
                evidence.transaction_receipt.amount,
                evidence.transaction_receipt.currency,
              )}
            />
            <DetailRow label="Paid" value={formatDateTime(evidence.transaction_receipt.paid_at)} />
            <DetailRow label="Channel" value={titleCase(evidence.transaction_receipt.channel)} />
            <DetailRow
              label="Reference"
              value={evidence.transaction_receipt.reference}
              mono
              to={href.transaction(evidence.transaction_receipt.reference)}
            />
            <DetailRow
              label="Customer"
              value={
                evidence.transaction_receipt.customer_name ??
                evidence.transaction_receipt.customer_email ??
                '—'
              }
              to={detail.customer ? href.customer(detail.customer.id) : undefined}
            />
          </ContextCard>

          <ContextCard title="Order" icon={<PackageCheck className="h-4 w-4" />}>
            {evidence.order_details ? (
              <>
                <DetailRow
                  label="Order"
                  value={evidence.order_details.order_number ?? 'View order'}
                  to={href.transaction(detail.transaction_reference)}
                />
                <DetailRow label="Description" value={evidence.order_details.description ?? '—'} />
                <DetailRow
                  label="Amount"
                  value={formatMoney(
                    evidence.order_details.amount,
                    evidence.order_details.currency,
                  )}
                />
                <DetailRow label="Created" value={formatDate(evidence.order_details.created_at)} />
              </>
            ) : (
              <p className="text-[12px] text-ink-400">
                This payment was not linked to an order. That weakens the evidence.
              </p>
            )}
          </ContextCard>

          <ContextCard title="Fulfillment" icon={<Truck className="h-4 w-4" />}>
            {evidence.fulfillment_evidence.length ? (
              <div className="space-y-4">
                {evidence.fulfillment_evidence.map((fulfillment, index) => (
                  <FulfillmentBlock
                    key={`${fulfillment.delivery_date}-${index}`}
                    fulfillment={fulfillment}
                    onPreview={setPreview}
                  />
                ))}
              </div>
            ) : (
              <p className="text-[12px] leading-5 text-ink-400">
                No fulfillment record attached. Add delivery proof to strengthen this response.
              </p>
            )}
          </ContextCard>

          <ContextCard title="Customer" icon={<UserRound className="h-4 w-4" />}>
            {evidence.customer_history ? (
              <>
                <DetailRow
                  label="Payments"
                  value={String(evidence.customer_history.payment_count)}
                />
                <DetailRow
                  label="Prior disputes"
                  value={String(evidence.customer_history.prior_disputes)}
                />
                <DetailRow
                  label="First paid"
                  value={formatDate(evidence.customer_history.first_payment_at)}
                />
              </>
            ) : (
              <p className="text-[12px] leading-5 text-ink-400">
                Shared email or first-time customer: the history block is intentionally omitted.
              </p>
            )}
          </ContextCard>

          {detail.readiness ? (
            <ContextCard title="Evidence readiness" icon={<ShieldCheck className="h-4 w-4" />}>
              <div className="flex items-center justify-between">
                <p className="text-sm font-semibold text-ink-900">
                  {titleCase(detail.readiness.label)}
                </p>
                <span className="text-xl font-semibold text-ink-950">{detail.readiness.score}</span>
              </div>
              <div className="mt-4 space-y-3">
                {detail.readiness.components.map((component) => (
                  <div key={component.key}>
                    <div className="flex items-center justify-between gap-2 text-[11px]">
                      <span
                        className={
                          component.status === 'available'
                            ? 'font-medium text-ink-700'
                            : 'text-ink-400'
                        }
                      >
                        {component.label}
                      </span>
                      <span className="text-ink-400">
                        {component.points}/{component.max_points}
                      </span>
                    </div>
                    <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-ink-100">
                      <div
                        className={
                          component.status === 'available'
                            ? 'h-full bg-brand-500'
                            : 'h-full bg-ink-200'
                        }
                        style={{ width: `${(component.points / component.max_points) * 100}%` }}
                      />
                    </div>
                    {component.suggestion ? (
                      <p className="mt-1 text-[10px] leading-4 text-ink-400">
                        {component.suggestion}
                      </p>
                    ) : null}
                  </div>
                ))}
              </div>
            </ContextCard>
          ) : null}

          <Card>
            <CardHeader title="Timeline" />
            <CardBody className="space-y-3 text-[12px]">
              <TimelineItem label="Dispute opened" value={formatDateTime(detail.created_at)} />
              {detail.evidence.generated_at ? (
                <TimelineItem
                  label="Evidence generated"
                  value={formatDateTime(detail.evidence.generated_at)}
                />
              ) : null}
              {detail.evidence.edited_at ? (
                <TimelineItem
                  label="Draft edited"
                  value={formatDateTime(detail.evidence.edited_at)}
                />
              ) : null}
              {detail.submitted_at ? (
                <TimelineItem
                  label="Submitted to Paystack"
                  value={formatDateTime(detail.submitted_at)}
                />
              ) : null}
              {detail.resolved_at ? (
                <TimelineItem label="Resolved" value={formatDateTime(detail.resolved_at)} />
              ) : null}
              {detail.submission_state ? (
                <div className="flex items-center justify-between">
                  <span className="text-ink-500">Submission state</span>
                  <Badge tone={statusTone(detail.submission_state)}>
                    {titleCase(detail.submission_state)}
                  </Badge>
                </div>
              ) : null}
            </CardBody>
          </Card>
        </div>
      </div>

      <Modal
        open={submitOpen}
        onClose={() => setSubmitOpen(false)}
        title="Submit this evidence to Paystack?"
        description="The draft becomes read-only and the evidence PDF is sent through the correct Paystack flow."
        footer={
          <>
            <Button variant="outline" onClick={() => setSubmitOpen(false)}>
              Keep editing
            </Button>
            <Button onClick={() => submitMutation.mutate()} loading={submitMutation.isPending}>
              <Send className="h-4 w-4" /> Submit evidence
            </Button>
          </>
        }
      >
        <div className="space-y-3 text-sm text-ink-600">
          <p>
            You are approving version {evidence.version} of this response. Paystack will receive the
            narrative, attached documents and fulfillment proof.
          </p>
          {quality ? (
            <div className="flex items-center gap-2 rounded-xl bg-ink-50 px-3.5 py-3">
              <CheckCircle2 className="h-4 w-4 text-brand-600" />
              <span className="text-[12px]">
                Quality score {quality.score} · {titleCase(quality.label)}
              </span>
            </div>
          ) : null}
        </div>
      </Modal>

      <Modal
        open={acceptOpen}
        onClose={() => setAcceptOpen(false)}
        title="Accept this dispute?"
        description="Paystack will refund the customer. This cannot be undone."
        footer={
          <>
            <Button variant="outline" onClick={() => setAcceptOpen(false)}>
              Cancel
            </Button>
            <Button
              variant="danger"
              onClick={() => acceptMutation.mutate()}
              loading={acceptMutation.isPending}
            >
              Accept and refund
            </Button>
          </>
        }
      >
        <div>
          <Label htmlFor="accept-message">Note to Paystack (optional)</Label>
          <Textarea
            id="accept-message"
            rows={4}
            value={acceptMessage}
            onChange={(event) => setAcceptMessage(event.target.value)}
            placeholder="e.g. Confirmed duplicate charge, accepting the claim."
          />
        </div>
      </Modal>

      <Modal
        open={Boolean(preview)}
        onClose={() => setPreview(null)}
        title={preview?.name ?? 'Evidence photo'}
        size="lg"
      >
        {preview ? (
          <AuthImage
            fileId={preview.id}
            alt={preview.name}
            className="max-h-[65vh] w-full rounded-xl"
          />
        ) : null}
      </Modal>
    </div>
  );
}

function ContextCard({
  title,
  icon,
  children,
}: {
  title: string;
  icon: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <Card>
      <CardHeader
        title={
          <span className="flex items-center gap-2">
            <span className="text-ink-400">{icon}</span>
            {title}
          </span>
        }
      />
      <CardBody className="space-y-2.5">{children}</CardBody>
    </Card>
  );
}

function DetailRow({
  label,
  value,
  mono,
  to,
}: {
  label: string;
  value: string;
  mono?: boolean;
  // the record this value is, when it has its own page
  to?: string;
}) {
  const classes = cn(
    'max-w-[62%] text-right font-medium text-ink-800',
    mono && 'font-mono text-[11px]',
    to && 'text-brand-600 hover:underline',
  );
  return (
    <div className="flex items-start justify-between gap-4 text-[12px]">
      <span className="text-ink-500">{label}</span>
      {to ? (
        <Link href={to} className={classes}>
          {value}
        </Link>
      ) : (
        <span className={classes}>{value}</span>
      )}
    </div>
  );
}

function TimelineItem({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-start justify-between gap-4">
      <span className="text-ink-500">{label}</span>
      <span className="text-right font-medium text-ink-700">{value}</span>
    </div>
  );
}

function FulfillmentBlock({
  fulfillment,
  onPreview,
}: {
  fulfillment: FulfillmentEvidence;
  onPreview: (value: { id: string; name: string }) => void;
}) {
  return (
    <div className="rounded-xl border border-line bg-ink-50/60 p-3">
      <div className="flex items-center justify-between gap-2">
        <p className="text-[12px] font-semibold text-ink-800">{titleCase(fulfillment.type)}</p>
        <span className="text-[10px] text-ink-400">{formatDate(fulfillment.delivery_date)}</span>
      </div>
      <div className="mt-2 space-y-1.5 text-[11px]">
        {fulfillment.tracking_number ? (
          <p className="text-ink-500">
            Tracking <span className="font-mono text-ink-700">{fulfillment.tracking_number}</span>
          </p>
        ) : null}
        {fulfillment.recipient_name ? (
          <p className="text-ink-500">
            Received by <span className="text-ink-700">{fulfillment.recipient_name}</span>
          </p>
        ) : null}
        {fulfillment.notes ? <p className="leading-5 text-ink-500">{fulfillment.notes}</p> : null}
      </div>
      {fulfillment.photos.length ? (
        <div className="mt-2.5 grid grid-cols-3 gap-1.5">
          {fulfillment.photos.map((photo) => (
            <AuthImage
              key={photo.file_id}
              fileId={photo.file_id}
              alt={photo.file_name}
              className="h-16 w-full"
              onClick={() => onPreview({ id: photo.file_id, name: photo.file_name })}
            />
          ))}
        </div>
      ) : null}
    </div>
  );
}
