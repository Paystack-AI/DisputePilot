# DisputePilot + TrustLayer: Frontend Implementation Plan & UX Design Spec

**Paystack AI Builder Challenge 2026**  
**Document Version:** 1.0 (19 September 2026)  
**Target:** Merchant App, Public Trust Profile, and Embeddable Trust Widget  
**Prepared for:** Ashburg (Frontend)  
**Based on:** Frontend Role Guide, Paystack Architecture Doc, Project Path Spec, UI Mockup

---

## 1. Executive Summary

You are building **three surfaces on top of one backend**:
1. **Private Merchant App (DisputePilot):** Authenticated portal for dispute defense, reconciliation, fulfillment logging, and TrustLayer configuration.
2. **Public TrustLayer Profile:** Server-rendered, fast, cached, mobile-first public profile showing verified merchant operational trust signals with zero customer PII.
3. **Embeddable Trust Widget:** Lightweight vanilla TypeScript bundle (~10KB) rendering a sandboxed iframe badge with domain verification across merchant stores.

> **The One-Sentence Design Idea:**  
> Do not build a collection of dashboards; build a **guided workflow**: understand the payment, identify the issue, gather evidence, act, then maintain operational trust. Every screen must end in a clear next action leading seamlessly to the next.

### Key Decisions at a Glance

| Question | Decision | Rationale |
| :--- | :--- | :--- |
| **Language** | **TypeScript (strict mode)** | End-to-end compile-time safety across API contracts, financial calculations (kobo), and status enums. Zod runtime validation catches schema drift. |
| **Framework** | **Next.js 14+ (App Router)** | SSR/ISR for public profile pages, client components for interactive merchant views, Route Handlers as a BFF proxy. |
| **Styling & UI** | **Tailwind CSS + shadcn/ui** | Fast implementation; accessible primitives (Radix); design tokens map 1:1 to Figma. |
| **State Management**| **TanStack Query v5 + Zustand** | TanStack Query for server state caching/polling/retries; small Zustand stores for client UI state (sidebar, quick-log drawer, filters). |
| **Widget Bundle** | **Vanilla TypeScript (tsup/Vite)** | ~10KB bundle. Must **never** drag React or heavy libraries onto merchant storefronts. |
| **Native Mobile App?**| **No (Responsive Web / PWA)** | Responsive web serves all merchants and buyers efficiently without doubling development overhead. |
| **Customer Placement**| **Domain-Verified Iframe Badge** | Placed on product pages, pre-payment/cart page, order confirmation, plus link/QR code for WhatsApp/Instagram sellers. |

---

## 2. Review: What is Solid, What Was Missing

Comparison of the initial mockup against the project specifications:

| # | Area | Mockup Baseline | Spec / Guide Requirement | Action Taken in Spec |
| :- | :--- | :--- | :--- | :--- |
| 1 | **Dispute Deadline** | Simple "Needs response" pill | Live countdown, sticky critical banner under 8h, color-coded urgency | Added countdown to dashboard banner, dispute cards, and dispute details |
| 2 | **Reconciliation** | Sidebar link only | Core feature #1; demo opens with AI match acceptance | Designed lean workspace: tabs, AI match card, sticky summary bar |
| 3 | **Fulfillment Logging**| Not shown | Demo step: "merchant logs delivery proof"; readiness & trust depend on it | Added Quick-Log modal (<60s, 3 taps) + post-sale dashboard prompt |
| 4 | **Submit Control** | "Submit to Paystack" directly beside "Review Evidence" | AI evidence must be reviewable; never silently submitted | Gated submission behind explicit Review step + confirmation modal + 3-step progress |
| 5 | **TrustLayer States** | Only "Verified" | 4 deterministic states: *Verified, Established, Building Trust, Not Yet Rated* | Defined full state matrix, rendering logic, and default hide rules |
| 6 | **Actions & History** | Signals display only | Recommended actions loop, 7/30/90-day reason-coded state history | Added both panels to merchant TrustLayer screen |
| 7 | **Public Copy** | "Trusted Merchant", "Reliable Support", "Powered by trusted partners" | No UI claims unbacked by backend data; trust is informational, not a guarantee | Reworded strictly to 4 backed signals; removed unbacked claims |
| 8 | **Navigation Bug** | Settings highlighted "Reconciliation" in sidebar | Active navigation must strictly match route | Derived active state dynamically from the URL route |
| 9 | **Accept & Refund** | Not shown | Paystack Resolve API supports merchant-accepted with refund amount | Added secondary, confirmed destructive action on dispute detail |
| 10| **States & Mobile** | Mockup only showed desktop happy path | Loading, empty, error, success across desktop and mobile (390px) | Full state matrix and mobile layout specifications defined |
| 11| **Widget Embed** | Single arbitrary script tag | Secure embedding on external sites | Sandboxed iframe, domain verification, and graceful fallbacks |

---

## 3. Decisions to Settle with the Team

1. **Route Names:** Use `/dashboard`, `/transactions`, `/disputes`, `/reconciliation`, `/trustlayer`, `/settings`. Merchant TrustLayer tabs live under `/trustlayer`. Public pages live under `(public)` route group (`/t/[slug]`, `/embed/[slug]`).
2. **Score Thresholds:** Do **not** hardcode numeric thresholds (e.g., 70 vs 80) in the frontend. Backend must return semantic labels with every score (`well_defended`, `moderate`, `vulnerable`).
3. **API Prefix & Routing:** Use `/api/v1` base and proxy all browser requests through Next.js Route Handlers (`/api/[...path]`).
4. **Merchant ID in URLs:** Authenticated calls query `/trust/me` (retrieving the ID from the verified session cookie) to prevent ID enumeration. Only public endpoints take a merchant slug.
5. **Dispute Window Calculation:** Calculate purely from server `due_at` adjusted by server-client clock skew, never hardcoding a fixed 16-hour window.
6. **Token Storage:** Store JWT access and refresh tokens strictly in `httpOnly`, `Secure`, `SameSite` cookies handled by the Next.js proxy; tokens must never touch JavaScript `localStorage`.

---

## 4. Architecture & Technology Stack

```
PAYSTACK
  Transactions / Verify API
  Disputes API & Webhooks
  Upload URL + Resolve
          ▲
          │
DISPUTEPILOT BACKEND
  Reconciliation Engine
  Customer Ledger
  Fulfillment Logger
  Dispute + Evidence + AI
  Deterministic Trust Engine
          ▲
          │ REST API + WebSockets (/api/v1)
          ▼
FRONTEND SCOPE
┌─────────────────────────────────────────────────────────────┐
│ Next.js App Router (BFF Proxy)                              │
│                                                             │
│ ┌──────────────────────────┐   ┌──────────────────────────┐ │
│ │ Merchant App (Auth)      │   │ Public Surface           │ │
│ │  - Dashboard             │   │  - /t/[slug] Profile     │ │
│ │  - Transactions + Detail │   │  - /embed/[slug] Iframe  │ │
│ │  - Disputes + AI Review  │   └──────────────────────────┘ │
│ │  - Reconciliation        │   ┌──────────────────────────┐ │
│ │  - TrustLayer Settings   │   │ Widget Package           │ │
│ └──────────────────────────┘   │  - ~10KB Vanilla TS      │ │
│                                │  - Sandboxed Loader      │ │
│                                └──────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
```

### Core Architectural Rules
1. **Single Typed API Client (`lib/api.ts`):** Components never call `fetch` directly. All responses pass through runtime Zod parsing (`schema.parse(json)`).
2. **BFF Proxy (`app/api/[...path]/route.ts`):** Forwards requests to backend `/api/v1`, attaches `httpOnly` auth cookies, eliminates CORS issues, and keeps Paystack keys off client bundles.
3. **No Business Logic in Browser:** The browser formats and displays; it does not calculate trust scores or dispute readiness.
4. **Separation of Public Surface:** Public profiles (`/t/[slug]`) and widgets are served with strict Content-Security-Policy (CSP), no merchant cookies, and independent caching.
5. **Reusable Single-Instance Primitives:** One `StatusBadge`, one `MoneyText`, one `CountdownTimer`, one `TrustBadge`.

---

## 5. Project Directory Structure

```text
disputepilot-web/
|-- src/
|   |-- app/
|   |   |-- (auth)/
|   |   |   |-- login/page.tsx
|   |   |   `-- register/page.tsx           # + Paystack connect onboarding
|   |   |-- (app)/
|   |   |   |-- layout.tsx                  # AppShell: sidebar, topbar, auth guard
|   |   |   |-- dashboard/page.tsx
|   |   |   |-- transactions/page.tsx
|   |   |   |-- transactions/[reference]/page.tsx
|   |   |   |-- disputes/page.tsx
|   |   |   |-- disputes/[id]/page.tsx      # Flagship screen
|   |   |   |-- reconciliation/page.tsx
|   |   |   |-- customers/page.tsx          # Optional / mini-ledger
|   |   |   |-- customers/[id]/page.tsx
|   |   |   |-- orders/page.tsx
|   |   |   |-- trustlayer/page.tsx         # Tabs: Overview | Public profile | Widget
|   |   |   `-- settings/page.tsx
|   |   |-- (public)/
|   |   |   |-- t/[slug]/page.tsx           # Public TrustLayer profile (SSR + ISR)
|   |   |   `-- embed/[slug]/page.tsx       # Iframe target used by the widget
|   |   `-- api/[...path]/route.ts          # BFF proxy to backend /api/v1
|   |-- components/
|   |   |-- ui/                             # shadcn primitives (Button, Card, Dialog, Tabs)
|   |   |-- layout/                         # AppShell, Sidebar, TopBar, MobileTabBar
|   |   |-- shared/                         # MoneyText, PaystackRef, ChannelBadge, StatusBadge, CountdownTimer
|   |   |-- dashboard/                      # MetricCard, RevenueChart, ReadinessRing, NudgeCard
|   |   |-- transactions/                   # TransactionTable, Timeline
|   |   |-- disputes/                       # DisputeCard, AIDraftEditor, EvidenceChecklist, SubmitStepper
|   |   |-- reconciliation/                 # MatchCard, SummaryBar, Drawer
|   |   |-- fulfillment/                    # QuickLogModal, ProofDropzone
|   |   |-- trustlayer/                     # TrustBadge, TrustCard, SignalList, TrustHistory, EmbedCodeBlock
|   |   `-- charts/ tables/
|   |-- features/                           # Custom React Query hooks (use-disputes.ts, use-trust.ts)
|   |-- lib/                                # api.ts, auth.ts, money.ts, time.ts, query-keys.ts, realtime.ts
|   |-- schemas/                            # Zod schemas (source of truth for runtime validation)
|   |-- types/                              # TypeScript types generated via z.infer
|   `-- mocks/                              # MSW handlers + fixtures (strong / incomplete / new merchant)
|-- widget/                                 # Separate standalone package (~10KB vanilla TS)
|   |-- src/loader.ts
|   `-- vite.config.ts
|-- tests/
|   |-- unit/
|   `-- e2e/demo-path.spec.ts
`-- tailwind.config.ts
```

---

## 6. UX Direction & Design System

### 6.1 Design Principles
- **Guided Workflow:** Every screen ends with the next best action: payment → dispute → evidence → trust. No dead ends.
- **Urgency is Visible:** Deadlines are prominent, live, and color-coded. Critical disputes cannot be missed.
- **Evidence Over Assertion:** Show exactly what exists and what is missing, with clear suggestions for every gap.
- **Calm Trust:** TrustLayer is quiet and factual: icon, status, one explanatory sentence, last-updated date. No hype, no stars, no arbitrary ratings.
- **Precise Money:** All currency uses tabular numerals (`font-mono` / `tabular-nums`), integer minor units (kobo), and `Intl.NumberFormat`.
- **AI Assists, Humans Decide:** AI content is clearly badged, completely editable, and never submitted without an explicit review and confirmation modal.

### 6.2 Color Palette & Design Tokens

```typescript
// tailwind.config.ts (excerpt)
theme: {
  extend: {
    colors: {
      navy: '#081F44', // Sidebar, headings, primary buttons on light surfaces
      brand: '#0066FF', // Links, active navigation, primary action, AI accents
      success: {
        DEFAULT: '#10B981',
        text: '#047857',
        tint: '#E7F8F1'
      },
      warning: {
        DEFAULT: '#F59E0B',
        text: '#92400E',
        tint: '#FEF3DC'
      },
      danger: {
        DEFAULT: '#EF4444',
        text: '#B91C1C',
        tint: '#FDECEC'
      },
      info: {
        DEFAULT: '#0066FF',
        text: '#0052CC',
        tint: '#EAF2FF'
      },
      surface: {
        bg: '#F8FAFC',
        card: '#FFFFFF',
        border: '#E2E8F0'
      },
      neutral: {
        gray: '#64748B',
        textSecondary: '#475569'
      },
      text: {
        primary: '#0F172A'
      }
    },
    borderRadius: {
      md: '6px',  // Inputs and buttons
      xl: '12px', // Cards and modals
      full: '9999px' // Pills and badges
    },
    fontFamily: {
      sans: ['var(--font-inter)', 'system-ui'],
      mono: ['ui-monospace', 'JetBrains Mono', 'monospace']
    }
  }
}
```

### 6.3 Universal Status Semantics

| Domain | Value | Label Shown | Color Representation |
| :--- | :--- | :--- | :--- |
| **Transaction** | `success` / `failed` / `abandoned` / `reversed` | Successful / Failed / Abandoned / Reversed | green / red / gray / amber |
| **Reconciliation** | `auto_matched` / `manually_matched` / `unmatched` / `flagged` / `ai_suggested` | Matched (auto) / Matched / Unmatched / Flagged / AI suggestion (87%) | green / green / amber / red / blue |
| **Dispute** | `pending` / `evidence_generated` / `submitted` / `won` / `lost` / `auto_accepted` | Needs evidence / Draft ready / Submitted / Won / Lost / Auto-accepted | red-or-amber by urgency / blue / blue / green / red / gray |
| **Readiness** | `well_defended` / `moderate` / `vulnerable` | Well-defended / Moderate / Vulnerable | green / amber / red |
| **Evidence Quality**| `strong` / `moderate` / `weak` | Strong / Moderate / Weak | green / amber / red |
| **Countdown** | `>8h` / `4-8h` / `<4h` / `<1h` | hh:mm:ss | green / amber / red / red pulsing |
| **TrustLayer** | `verified` / `established` / `building_trust` / `not_rated` | Verified / Established / Building Trust / Not Yet Rated | green / blue / amber / gray |

### 6.4 Paystack-Specific Considerations
- **Currency Formatting:** Default `NGN` (₦), with dynamic support for `GHS`, `KES`, `ZAR`. Amounts stored in minor units (`kobo`), formatted via `formatMoney(minor, currency)`.
- **References:** Paystack references (e.g., `T829104xxxx`) are monospace, never truncated without a copy button, and link to `/transactions/[reference]`.
- **Payment Channels:** Distinct icons and labels for Card, Bank Transfer, USSD, and Mobile Money.
- **Environment Modes:** Explicit "Live" vs "Test mode" pill in top-bar header.

---

## 7. Golden Path Demo Flow (10 Steps)

The end-to-end hackathon demonstration flow:
1. **Login & Onboarding:** Connect Paystack test key; review progress bar during initial 247-transaction sync.
2. **Dashboard Overview:** Metric cards, TrustLayer status card, and reconciliation quick view ("3 need review").
3. **Reconciliation:** View AI suggestion (*"87% match for Order #1032"*), accept match with undo toast, complete session.
4. **Log Fulfillment:** Open Quick-Log modal (<60s), snap/upload delivery proof photo, save; dispute readiness and trust score instantly recalculate.
5. **TrustLayer Exploration:** Merchant views updated score; recommended action count shrinks from 3 to 2; inspects live widget preview.
6. **Customer Storefront:** View simulated merchant product page showing the domain-verified trust badge; tap to view popover trust card and link to `/t/acme-store`.
7. **Dispute Ingestion:** Realtime dispute notification arrives; toast triggers; sticky red banner appears with live countdown (<8h).
8. **Dispute Detail (Flagship):** Joined transaction/order/customer context loaded; AI evidence draft generated with `Quality: Strong`; review missing evidence suggestion.
9. **Review & Multi-Step Submission:** Merchant reviews draft, opens confirmation modal, observes 3-step progress stepper (*Prepare PDF → Upload + attach → Resolve with Paystack*); success banner and PDF download link appear.
10. **Resolution:** Dispute status updates live to `Won`; TrustLayer event history reflects reason-coded trust preservation.

---

## 8. Detailed Screen Specifications

### 8.1 Login & Onboarding (`/login`, `/register`)
- **Purpose:** Seamless zero-confusion onboarding from registration to first synced dataset.
- **Flow:** 4-step wizard:
  1. Paystack Secret Key entry (masked input, server-side validated, retrieves business name).
  2. Notification preferences.
  3. Initial sync progress bar (`"Syncing 247 transactions..."`).
  4. First reconciliation prompt.
- **States:** Invalid key error, slow sync indicator (*"You can leave, we'll notify you"*), sync failure with retry.

### 8.2 Merchant Dashboard (`/dashboard`)
- **Sticky Critical Dispute Banner:** Displays total amount at risk and live server-corrected countdown (`"6h 23m remaining"`). Non-dismissible while critical disputes exist.
- **Metric Cards:** Total Revenue, Total Transactions, Open Disputes, Dispute Readiness percentage.
- **Date Range Selector:** 7, 30, and 90-day filters driving all cards and charts.
- **TrustLayer Status Widget:** Current badge, last-updated timestamp, 4 qualitative signal dots, and `"X actions could improve this >"` link.
- **Reconciliation Quick View:** Daily summary (`14 synced - 11 matched - 3 need review`) with `"Start reconciliation"` CTA.
- **Dispute Readiness Distribution Ring:** Interactive ring showing Well-defended (green), Moderate (amber), and Vulnerable (red). Clicking a segment filters transactions.
- **Post-Sale Fulfillment Nudge:** Highlights unfulfilled paid orders (`"Order #1048 was paid ₦45,000. Has it been fulfilled?"`) opening Quick-Log directly.

### 8.3 Transactions & Details (`/transactions`, `/transactions/[reference]`)
- **List View:** Search bar, date range, channel filter, status filter. Table columns: Reference, Customer, Amount, Channel, Status, Reconciliation, Date.
- **Detail View:** Joined vertical timeline:
  - *Payment Card* (Amount, channel, fees, Paystack reference).
  - *Order Card* (Order ID, line items, store channel).
  - *Fulfillment Card* (Delivery status, tracking number, proof photos).
  - *Dispute/Evidence Card* (Status, reason, readiness score).
- **Actions:** Link to order (drawer), flag/unflag transaction, quick-log fulfillment.

### 8.4 Flagship Dispute Detail Screen (`/disputes/[id]`)
- **Header:** Dispute ID, Paystack status, internal status, and prominent **Live Countdown Timer** (`hh:mm:ss`).
- **Left Panel (Evidence Workspace):**
  - **AI Evidence Draft:** Persistent banner: *"AI-generated draft. Not submitted. Review and edit before sending to Paystack."* Rich text editor with auto-save indicator and "Regenerate" confirmation.
  - **Quality Badge:** Server-driven label (`Strong`, `Moderate`, `Weak`) with numeric indicator.
  - **Evidence Checklist:** Interactive checklist showing status for Payment confirmation, Customer info, Delivery photo, Order details, Fulfillment record, Customer communication. Displays AI tips for missing items.
  - **File Dropzone:** Drag-and-drop or camera capture for receipts, waybills, and chat screenshots.
  - **Action Bar:**
    - Primary: `"Review evidence"` → triggers `"Submit to Paystack"` confirmation modal.
    - Secondary: `"Accept & refund"` (confirmed destructive modal).
- **Submission Stepper Modal (3 Steps):**
  1. *Prepare PDF* (Backend compiles evidence bundle).
  2. *Upload + Attach* (Upload URL requested, binary PUT, evidence linked).
  3. *Resolve with Paystack* (PUT resolve to Paystack API).
  *Per-step error handling with idempotent retries.*
- **Right Panel (Read-Only Context):**
  - Transaction facts, Order details, Fulfillment proofs, Customer lifetime statistics (7 transactions, ₦1.2M, 0 prior disputes), and Dispute AI categorization (e.g., *"Chargeback - 94% confidence"*).

### 8.5 Reconciliation & Quick-Log Modal (`/reconciliation`)
- **Reconciliation Workspace:**
  - Status tabs: `All`, `Matched`, `Unmatched`, `Flagged`.
  - **AI Match Suggestion Card:** Side-by-side comparison of Paystack payment vs order record, confidence score (e.g., `87% match`), one-sentence AI reasoning, and `Accept match` / `Not a match` actions.
  - **Sticky Summary Bar:** Real-time counts and values for Matched, Unmatched, and Flagged items + `"Complete reconciliation"` button.
- **Quick-Log Fulfillment Modal:**
  - Target: complete in <60 seconds with 3 taps.
  - Order selector (search by order ID, customer name, amount).
  - Delivery proof photo upload / mobile camera capture.
  - Fulfillment type selector: *Delivery*, *Service*, *Digital*, *Pickup*.
  - Collapsible tracking details (carrier, tracking number, signed receipt).
  - On save: instant toast confirmation + live recalculation of dispute readiness and TrustLayer signals.

### 8.6 TrustLayer Merchant Configuration (`/trustlayer`)
- **Status & Share Panel:** Displays current public status, merchant-only internal score, public URL (`trustlayer.app/acme-store`), copy link, and QR code download.
- **4 Trust Signals:** Payment history, Fulfillment activity, Dispute handling, Operational consistency.
- **Recommended Actions Loop:** Actionable tasks that directly boost trust (e.g., *"Log fulfillment for 6 orders"*, *"Reconcile 3 unmatched payments"*).
- **Trust History Chart:** 7, 30, and 90-day reason-coded timeline logging every state change and event.
- **Live Widget Preview:** Real-time interactive preview of the customer badge.
- **Widget Settings & Embed Code:**
  - Variant picker: *Compact* (inline 28px), *Standard* (card), *Detailed* (panel).
  - Rules: Option to *"Only show when Established or above"*.
  - Code generators: Script tag, Sandboxed iframe, Direct Link + QR, SVG badge, WhatsApp share link.
- **Domain Verification:** Lists authorized domains (e.g., `acmestore.com [Verified]`) with DNS TXT / meta-tag verification instructions.

---

## 9. TrustLayer on the Customer End

### 9.1 Three-Tier Architecture
1. **Tier 1: Domain-Verified Badge:** Small, quiet indicator rendered directly on merchant storefronts.
2. **Tier 2: Trust Card:** Interactive popover (desktop) or bottom sheet (mobile) triggered by tapping the badge; summarizes verified facts in 10 seconds.
3. **Tier 3: Public Profile Page (`/t/[slug]`):** Dedicated standalone page explaining the merchant's operational record, verification methodology, and privacy notices.

### 9.2 Placements on Merchant Stores
- **Product Page (Compact Variant):** Placed directly beneath the "Add to Cart" button to resolve customer hesitation without altering page layout.
- **Pre-Payment / Cart Page (Standard Card):** Placed directly above the "Pay with Paystack" button prior to redirect. *This is the highest-value conversion moment.*
- **Order Confirmation Page (Standard or Link):** Placed below the order receipt to build post-purchase confidence and repeat trust.
- **Offline / Social Sellers (Link + QR):** Shared via WhatsApp catalogs, Instagram bio links, invoices, and physical delivery notes.

### 9.3 Public Privacy & Anti-Spoofing Rules (NDPA 2023)

```
┌──────────────────────────────────────┬────────────────────────────────────────┐
│ ALLOWED ON PUBLIC SURFACES           │ NEVER ALLOWED ON PUBLIC SURFACES       │
├──────────────────────────────────────┼────────────────────────────────────────┤
│ • Merchant business name & logo      │ • Customer names, emails, phone numbers│
│ • Verified domain name               │ • Individual transaction amounts/dates │
│ • 1 of 4 Public Trust States         │ • Individual dispute counts or cases   │
│ • One-sentence meaning explanation   │ • Evidence files or customer messages  │
│ • 4 Qualitative signal readings      │ • Internal numeric scores (0-100)      │
│ • Last updated timestamp             │ • Secret keys, API tokens, backend IDs │
│ • Status stability over 90 days      │ • Unverified marketing claims          │
└──────────────────────────────────────┴────────────────────────────────────────┘
```

#### Anti-Spoofing Controls:
- **Frame Ancestors & CSP:** Backend serves `Content-Security-Policy: frame-ancestors` matching only the merchant's verified domains.
- **Fail Closed:** If a domain is unverified, the network request fails, or payload is expired (>5 minutes), the widget **renders nothing**.
- **No Layout Shift:** Pre-allocated dimensions ensure zero Cumulative Layout Shift (CLS).

### 9.4 Approved Copy Guide

| Approved Trust Copy | Prohibited Copy (Overclaims / Unbacked) |
| :--- | :--- |
| **TrustLayer Verified** | *Trusted Merchant*, *100% Safe*, *Guaranteed* |
| **Verified payment and fulfillment record** | *Top Rated*, *5 Stars*, *Best Merchant* |
| **Consistent successful transactions** | *Zero disputes* (implies an impossible guarantee) |
| **Updated [Date]** | *Real-time verified* |
| **An informational signal, not a guarantee** | *Paystack Endorsed*, *Powered by trusted partners* |

---

## 10. Data Layer, Auth & Realtime

### 10.1 API Client Implementation (`lib/api.ts`)

```typescript
import { z } from 'zod';

export async function api<T>(
  path: string,
  schema: z.ZodType<T>,
  init?: RequestInit
): Promise<T> {
  const res = await fetch('/api/v1' + path, {
    credentials: 'include',
    headers: {
      'Content-Type': 'application/json',
      ...init?.headers,
    },
    ...init,
  });

  if (!res.ok) {
    const errorBody = await res.json().catch(() => ({}));
    throw {
      status: res.status,
      code: errorBody.code || 'UNKNOWN_ERROR',
      message: errorBody.message || 'An unexpected error occurred',
      requestId: res.headers.get('x-request-id'),
    };
  }

  const json = await res.json();
  return schema.parse(json); // Fails loudly if backend contract drifts
}
```

### 10.2 Server-Skew Corrected Countdown (`lib/countdown.ts`)

```typescript
export function getRemainingMs(
  dueAtIso: string,
  serverNowIso: string,
  clientFetchedAtMs: number
): number {
  const serverTimeAtFetch = Date.parse(serverNowIso);
  const clientClockSkew = serverTimeAtFetch - clientFetchedAtMs;
  const correctedCurrentTime = Date.now() + clientClockSkew;
  return Date.parse(dueAtIso) - correctedCurrentTime;
}
```

### 10.3 TanStack Query Caching & Polling Policies

| Data Resource | Stale Time | Refetch / Invalidation Triggers | Policy Notes |
| :--- | :--- | :--- | :--- |
| **Dashboard** | 30s | Window focus + realtime events | Per-widget queries so partial failures don't blank the view |
| **Transactions List**| 60s | Window focus, after sync | `keepPreviousData: true` while filtering |
| **Disputes List** | 15s | Realtime events + 30s polling fallback | Fast response to incoming chargebacks |
| **Dispute Detail** | 0s | Realtime events + mutation response | Countdown is client-ticked, never refetched continuously |
| **Evidence Draft** | 0s | Returns updated draft from mutation | Debounced auto-save |
| **Merchant Trust** | 60s | Invalidation on fulfillment/match mutations | Synchronized with action list updates |
| **Public Trust** | 5 mins | Server cached (ISR / On-demand revalidation) | Zero client-side polling |

### 10.4 Realtime WebSocket Events & Fallback

| Event Name | UI Impact |
| :--- | :--- |
| `dispute.created` | Instant toast, sticky critical banner, badge increment, invalidates disputes & dashboard queries |
| `dispute.updated` / `.resolved` | Updates dispute status in-place, triggers resolution banner, invalidates TrustLayer |
| `deadline.warning` (8h, 4h) | Escalates banner color from amber to red; displays warning toast |
| `transaction.synced` / `reconciliation.updated` | Updates synced/matched counts in quick view |
| `evidence.ready` | Dispatches toast with direct *"Review draft"* action link |
| `trust.updated` | Refreshes merchant TrustLayer card and logs reason-coded event |

*Fallback:* If the WebSocket disconnects, TanStack Query automatically engages a 30-second polling fallback while a discreet `"Reconnecting..."` badge is shown.

---

## 11. State Matrix & Accessibility

### 11.1 State Matrix Across Core Screens

| Screen | Loading State | Empty State | Error State | Success State | Mobile (390px) |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Dashboard** | Card skeletons | Connect Paystack prompt | Per-card retry | Live metrics & feeds | Single column, 2x2 grid |
| **Transactions** | Row skeletons | No matches + clear filters | Retry button | Filterable table | Stacked cards |
| **Dispute Detail**| Split skeletons | No evidence yet (Generate CTA) | Retry / Submission retry | Submitted banner + PDF | Stacked layout |
| **Reconciliation**| List skeletons | "All matched" celebration | Retry AI service | Side-by-side match card | Stacked cards |
| **TrustLayer** | Card skeletons | "Not Yet Rated" guide | Retry recalculation | Full signals + embed | Stacked panels |
| **Widget** | Height reserved | Widget hidden (fail-closed) | Widget hidden (fail-closed) | Verified badge | 44px tap target |

### 11.2 Accessibility Checklist
- **Color Independence:** Status is never indicated by color alone; always pair with icons and semantic text.
- **Contrast Ratios:** Text meets WCAG AA 4.5:1 minimums on all backgrounds.
- **Screen Reader Announcements (`aria-live`):** Dispute countdowns announce politely only at thresholds (8h, 4h, 1h), never every second.
- **Focus Trapping:** Modal dialogs (Evidence Review, Quick-Log, Confirmation) trap focus and restore focus to trigger elements upon exit.

---

## 12. 14-Day Implementation Schedule

```
Day 1-2:   Foundations, Next.js App, Tailwind Tokens, Zod Schemas, MSW Fixtures
Day 3:     Dashboard with Mock Data, MetricCards, RevenueChart, Critical Banner
Day 4:     Transactions List & Timeline Detail View
Day 5:     Reconciliation Lean Workspace, MatchCard, Quick-Log Fulfillment Modal
Day 6:     Disputes List, CountdownTimer, Urgency Sorting, Dispute Detail Layout
Day 7:     Flagship Evidence Review: AIDraftEditor, Checklist, SubmitStepper Modal
Day 8:     TrustLayer Merchant Screen: Signals, History, Actions, Embed Code Block
Day 9:     Public Trust Profile (/t/[slug]), Vanilla TS Widget Bundle, Test Storefront
Day 10-11: Integration Pass with Live Backend API, WebSockets & Error Handling
Day 12:    Responsive Layouts, Accessibility (a11y), and Performance Audits
Day 13:    Golden Path Seed Scenarios, E2E Playwright Tests, Demo Rehearsal
Day 14:    Demo Day: Feature Freeze, Mock Mode Fallback, Recorded Video Backup
```

---

## 13. Definition of Done

1. **Every core screen** supports Desktop (1440px) and Mobile (390px) with dedicated Loading, Empty, Error, and Success states.
2. **Every Paystack transaction reference** acts as a clickable link navigating directly to its detail view.
3. **Dispute details** clearly demonstrate what evidence is present and what is missing; AI-generated evidence is explicitly reviewable and cannot be submitted silently.
4. **TrustLayer public surfaces** expose **zero customer PII** or private dispute evidence; trust statuses remain consistent across dashboard, widget, and public profile.
5. **No unsupported claims:** Public UI contains zero exaggerated claims (no *"100% safe"*, no *"zero disputes"*).
6. **Reusable components:** Shared codebase features single instances of `StatusBadge`, `MoneyText`, `CountdownTimer`, and `TrustBadge`.
7. **End-to-End Golden Path:** The full 10-step demo flow runs flawlessly from login to resolution without dead ends on both desktop and mobile viewports.
