# AgentOS — Product UI Build Prompt

> A build-ready specification for the AgentOS application UI. Hand this file to an AI
> UI builder (v0, Lovable, Bolt, Claude artifacts) or a frontend engineer. It covers the
> design system and every core screen: onboarding, agent selection, agent configuration,
> the dashboard, connectors, realtime billing, and payment.
>
> **Scope:** UI only. Wire data to the AgentOS FastAPI backend later; for now use
> realistic mock data and stubbed handlers. Build against a stable component set so
> screens stay consistent.

---

## 0. How to use this file

- **Fast path:** paste the **Master Prompt** (§2) to scaffold the app, then refine each
  screen against its section.
- **Faithful path:** build screen by screen (§6–§12), pulling tokens and components from
  the design system (§3–§5).
- **Golden rule:** when a choice isn't specified, choose *more whitespace, fewer colors,
  crisper hairlines*. The brand is calm precision, not a typical SaaS dashboard.

---

## 1. What AgentOS is (context for tone & copy)

AgentOS is the control plane for a company's AI agent workforce — one place to **deploy**
agents (Support Desk, Receptionist, Social Media, HR), **connect** them to existing tools,
and **pay** for everything they do on a single balance. Think "payroll and mission-control
for AI agents." Every screen should reinforce two feelings: *this is serious
infrastructure* and *this is calm and in control.*

---

## 2. Master Prompt (paste-ready)

> Build a responsive web application UI for **AgentOS**, a platform to deploy, configure,
> connect, and pay AI agents. **Visual language:** serene, premium, near-white minimalism
> with generous whitespace and a signature of fine, flowing grey contour lines (like a
> topographic/flow-field drawing) used sparingly as a corner accent on the canvas and on
> empty/hero states — grounded by the precise, technical-drawing sensibility of
> professional engineering software (hairline rules, a visible column grid, small
> mono-spaced uppercase labels, numbered sections, measurement-style ticks, confident bold
> black headlines). Borrow that engineering *sensibility* only — never any real company's
> logo, name, or trademark. **Palette:** monochrome — warm off-white canvas, near-black
> ink, a graded set of greys, hairline borders — with exactly one restrained accent
> (blueprint cobalt) reserved for primary actions, active states, and live/positive
> billing signals. **Type:** a confident grotesk for display, a neutral sans for body
> (Inter), and a mono (IBM Plex Mono) for small uppercase technical labels and all numeric
> values (money, tokens, counts). **App shell:** a slim left sidebar (wordmark, primary nav,
> wallet balance pill, account), a thin top bar (page title + breadcrumbs, environment
> switcher, global "New agent" action), and a content canvas with a quiet line-art accent
> in the top-right corner. **Screens:** (1) seamless onboarding — a stepped flow:
> create workspace → pick first agent → connect a tool → fund wallet → launch; (2) agent
> selection — a gallery of role templates as precise annotated cards; (3) agent
> configuration — a focused editor with left settings nav, live-preview/test panel, and a
> cost-estimate strip; (4) dashboard — fleet overview with stat tiles, a spend-over-time
> chart, per-agent status table, and recent activity; (5) connectors — a catalog of 3rd-party
> integrations with connected/available states and a scoped-permission connect flow;
> (6) realtime billing — a live metering view with current balance, burn rate, per-agent
> spend, budgets/caps, and a usage ledger; (7) payment — add funds / top-up and billing
> settings with a clean checkout. **Components:** buttons, inputs, selects, toggles, tabs,
> cards, tables, modals, drawers, toasts, empty states, skeleton loaders, and a status-dot
> system (running / paused / error / draft). **Motion:** slow and subtle — content fades
> and rises a few pixels on mount; the line-art drifts gently; honor prefers-reduced-motion.
> **Accessibility:** WCAG AA contrast (avoid low-contrast grey body text), visible focus
> rings, full keyboard nav, decorative art aria-hidden, live regions for billing updates.
> Flat and hairline — no heavy shadows, no gradients, no glassmorphism, no emoji, no stock
> illustration. Use mock data throughout and stub all actions. Deliver as React + TypeScript
> + Tailwind, Google Fonts only, line-art as SVG/canvas, components cleanly separated.

---

## 3. Design system

### 3.1 Design principles

1. **Whitespace is the primary material.** Dense data, calmly spaced. When unsure, add room.
2. **Monochrome first, one accent.** Build everything in greys + ink; the cobalt accent is a
   scalpel — primary actions, active nav, live "money moving" signals, and nothing else.
3. **Flowing + precise, together.** The soft line-art is balanced everywhere by crisp
   structure — a hairline rule, a mono label, an aligned grid. Neither alone is the brand.
4. **Hairlines, not shadows.** Define edges with 1px borders. Reserve a single whisper-soft
   shadow only for overlays (modals, dropdowns, drawers).
5. **A grid you can feel.** Align to a clear column grid; let it surface occasionally as
   edge ticks or faint column rules — an engineering signal.
6. **Mono for anything measured.** Money, token counts, percentages, timestamps, IDs, and
   section numbers are all set in the mono face. Prose is the sans.
7. **Status is a language.** A consistent status-dot + label system across the whole app so
   state is readable at a glance.
8. **Calm motion only.** Nothing bounces or rushes.

### 3.2 Color tokens

| Token | Light | Use |
| --- | --- | --- |
| `--canvas` | `#F6F5F2` | App background — warm off-white |
| `--surface` | `#FCFCFB` | Cards, panels, table surface |
| `--surface-2` | `#F0EFEC` | Inset areas, hover rows, code/mono chips |
| `--ink` | `#111111` | Headlines, primary text, primary button fill |
| `--body` | `#2A2A2A` | Body text (AA on canvas) |
| `--muted` | `#6B6B6B` | Secondary text, mono labels — large/secondary only |
| `--line` | `#B9B8B4` | Flowing line-art strokes |
| `--hairline` | `#DAD9D5` | Borders, dividers, grid lines |
| `--accent` | `#1B4DFF` | Primary action, active nav, focus ring, live spend |
| `--accent-weak` | `#E8EDFF` | Accent tint — active backgrounds, selected rows |
| `--success` | `#1F9D55` | Healthy budget, successful payment, running |
| `--warning` | `#B7791F` | Approaching cap, degraded |
| `--danger` | `#C0362C` | Over budget, error, failed payment, stopped |

Optional dark mode: invert to a near-black canvas (`#0E0E0F`), surfaces `#161617`, keep the
same accent and status hues. Light is primary — ship it first.

### 3.3 Typography

| Role | Font (free) | Spec |
| --- | --- | --- |
| Display / headings | Archivo or Space Grotesk | 600–800; tight tracking; large |
| Body / UI | Inter | 400–500; 14–16px |
| Mono / technical | IBM Plex Mono | 11–13px, UPPERCASE for labels, tabular-nums for values |

- Section eyebrows and nav labels: mono, uppercase, `letter-spacing: 0.08em`, muted.
- **All numeric values use `font-variant-numeric: tabular-nums`** so figures align in tables
  and the billing meter doesn't jitter as it updates.

### 3.4 Spacing, grid, radius

- 8px spacing scale (4 / 8 / 12 / 16 / 24 / 32 / 48 / 64).
- 12-column grid, ~1280px max content width, 24–32px gutters, generous side padding.
- Radius: `--r-sm: 6px` (inputs, chips), `--r-md: 10px` (cards, buttons),
  `--r-lg: 14px` (modals, large panels). No pill buttons except status/wallet chips.
- Borders: 1px `--hairline` default; 1.5px `--accent` on focus/active.

### 3.5 The line-art motif, in product

The flowing grey lines are the brand signature — but inside a working app they must stay
*quiet*. Rules:

- **Default placement:** a single soft line-art field bleeding off the **top-right corner**
  of the main canvas (as in the reference), fading to nothing within ~30–40% of the width.
  Never behind dense tables or forms where it would reduce legibility.
- **Hero/empty states:** the lines may be larger and more present (onboarding, empty
  dashboards, the launch screen) — this is where the motif breathes.
- **Weight & color:** 0.75–1px strokes, `--line`, low contrast. They whisper.
- **Precision counterpoint:** pair the organic lines with a faint hairline grid or a few
  small mono coordinate/tick marks at a corner, so the form reads as *measured*.
- **Rendering:** static SVG by default; a lightweight canvas flow-field only on hero/empty
  states if animating (pause off-screen, honor reduced-motion). Always `aria-hidden`.

### 3.6 Core components (build once, reuse)

- **Buttons:** primary (ink fill / white text), accent (cobalt fill — reserved for the key
  action on a screen), secondary (hairline border, ink text), ghost (text + hover underline),
  destructive (danger border/text). Sizes sm/md. States: hover, active, disabled, loading.
- **Inputs / selects / textareas:** hairline border, `--surface` fill, mono helper text,
  inline validation; focus = accent ring.
- **Toggle / switch, segmented control, tabs** (underline style, mono labels).
- **Cards:** `--surface`, hairline border, optional mono eyebrow + number (01 / 02).
- **Tables:** hairline row dividers, `--surface-2` hover, sortable headers in mono, tabular
  numerics right-aligned, sticky header on scroll.
- **Status dot + label:** a 8px dot in the status hue + mono uppercase label
  (`RUNNING` / `PAUSED` / `ERROR` / `DRAFT` / `CONNECTED`).
- **Wallet pill:** mono balance with the accent dot, in the sidebar and top bar.
- **Overlays:** modal (centered, soft shadow, hairline), right-side drawer (config/connect
  flows), toast (bottom-right, mono status word + message), confirm dialog.
- **Feedback:** skeleton loaders (hairline shimmer, not spinners where possible), empty
  states (line-art + one line + one action), error states, inline live-region updates.

---

## 4. App shell & navigation

A persistent shell wraps every screen except onboarding and payment-checkout.

- **Left sidebar (collapsible, ~240px):**
  - Wordmark top (medium grotesk, slight positive tracking — echoes the splash).
  - Primary nav with mono labels: **Dashboard · Agents · Connectors · Billing · Settings.**
    Active item: accent left-border + `--accent-weak` background + ink text.
  - A **Wallet** pill near the bottom: mono balance (e.g. `$1,284.50`) with an accent dot and
    a small "Add funds" link → payment page.
  - Account row at the very bottom: workspace name + avatar + menu.
- **Top bar (~56px, hairline bottom border):**
  - Page title + breadcrumb (mono).
  - **Environment switcher** (`LIVE` / `TEST`) as a small segmented control — reinforces the
    "real system" feel; TEST uses a subtle striped marker.
  - Global **+ New agent** button (accent) on the right.
  - Line-art accent bleeds from the top-right corner behind the top bar into the canvas.
- **Canvas:** max-width container, generous padding, the quiet corner line-art, content grid.

Keyboard: `g then d/a/c/b` to jump between sections; `cmd/ctrl-k` command palette (optional,
on-brand — mono, hairline).

---

## 5. Shared patterns

- **Page header block:** mono eyebrow (section number + name) → bold grotesk H1 → one-line
  muted subhead → primary action right-aligned.
- **Status everywhere:** every agent, connector, run, and payment shows the status-dot system.
- **Money formatting:** mono, tabular-nums, always with currency symbol; micro-amounts shown
  to 4 decimals in ledgers (`$0.0024`), rolled amounts to 2 (`$1,284.50`).
- **Loading:** skeletons that match final layout; never a full-screen spinner.
- **Empty states:** line-art + a single sentence + a single action (e.g. "No agents yet.
  Deploy your first." → Browse templates).

---

## 6. Screen — Seamless onboarding

**Goal:** from signup to a live agent in under two minutes, as a calm stepped flow. This is
the one place the line-art is most present.

**Layout:** a centered, single-column flow over the near-white canvas with a prominent but
soft line-art field (top-right, drifting). A slim **progress rail** at the top: numbered mono
steps with a hairline connecting line; completed steps get an accent tick.

**Steps:**

1. **Create workspace** — workspace name, optional company size select. One field in focus,
   big and calm. Mono helper text. "Continue" (accent).
2. **Pick your first agent** — a compact 2×2 of the four role templates (Support Desk,
   Receptionist, Social Media, HR), each a precise card with a mono label, one-line
   description, and a tiny line-style icon. Selecting one highlights it (accent border +
   `--accent-weak`). "Use this agent."
3. **Connect a tool** — show 3–4 relevant connectors for the chosen role (e.g. Slack, Gmail,
   a CRM) as connect cards; connecting opens the scoped-permission drawer (§9). This step is
   **skippable** ("I'll do this later") — don't force it.
4. **Fund your wallet** — a friendly first top-up: three preset amounts ($20 / $50 / $100) as
   selectable tiles + custom amount, with a mono line explaining "You only pay for what your
   agents actually do." Also skippable with a small free-trial credit note if applicable.
5. **Launch** — a confirmation moment: the line-art swells gently, a bold "Your agent is
   live." headline, a summary card (agent · connected tools · balance), and a primary
   "Go to dashboard." Subtle, premium, not confetti.

**Behavior:** each step validates before advancing; back is always available; progress
persists if they drop off. On mobile, steps stack full-width. Honor reduced-motion (freeze
line-art, instant step transitions).

---

## 7. Screen — Agent selection (template gallery)

**Goal:** browse and deploy role templates; the "hire an agent" moment.

**Layout:**
- Page header: eyebrow `02 · AGENTS`, H1 "Deploy an agent", subhead "Roles, ready to work."
- A left filter column (mono labels): category (Support, Front office, Marketing, People,
  Custom), and a search field. Keep it quiet — hairlines only.
- A responsive **card grid** (3-up desktop, 2-up tablet, 1-up mobile) of template cards:
  - Mono eyebrow with a template number and category.
  - Role name (grotesk), one-line description.
  - A tiny line-art role glyph in the contour style (not a filled icon, not an emoji).
  - A row of mono capability chips (e.g. `CHAT` `VOICE` `CRM`).
  - Footer: an "Estimated cost" mono hint (e.g. `~$0.03 / conversation`) and a **Deploy**
    button (accent). Hover lifts the card only by brightening its border.
- Include a **"Start from scratch / Custom agent"** card as the last tile (dashed hairline
  border, line-art hint) → opens configuration (§8) with an empty config.

**The four starter templates** (name · one-liner · default tools):
- **Support Desk** — Answers customer questions and resolves tickets. · Helpdesk, Slack, KB.
- **Receptionist** — Greets, routes, and books across voice and chat. · Telephony, Calendar.
- **Social Media** — Drafts, schedules, and replies across channels. · X, LinkedIn, Buffer.
- **HR Agent** — Handles onboarding, policy Q&A, and leave requests. · HRIS, Email, Docs.

Clicking **Deploy** goes straight into configuration (§8) pre-filled from the template.

---

## 8. Screen — Agent configuration

**Goal:** a focused, powerful editor that resolves the "plug-and-play vs. deeply
configurable" tension — opinionated defaults up top, depth on demand. Default-good,
allow-deep.

**Layout:** three regions.

- **Left settings nav (sticky, mono labels):** Identity · Behavior · Knowledge · Tools &
  connectors · Guardrails · Schedule · Budget. A section is a scroll target or a tab.
- **Center editor (the main column):**
  - **Identity** — agent name, role (from template), avatar/line-glyph, short description,
    status toggle (Draft / Live).
  - **Behavior** — model select (with a mono cost hint per model), system prompt / instructions
    (large monospace-friendly textarea), tone and verbosity controls, example conversations.
  - **Knowledge** — attach documents / URLs / a knowledge base; show indexed sources as mono
    chips; drag-drop upload zone with the line-art hint in empty state.
  - **Tools & connectors** — enable capabilities and bind connectors; each tool row has a
    scope summary and a status dot; "Add connector" opens the connectors drawer (§9).
  - **Guardrails** — allowed/blocked topics, escalation-to-human rules, data-handling toggles,
    max actions per run. Present as clear toggles + mono helper text.
  - **Schedule** — always-on vs. active hours vs. triggered; timezone; concurrency limit.
  - **Budget** — a per-agent cap (daily/monthly), soft-alert threshold, and action on breach
    (alert / throttle / stop). This visually ties to the billing system (§11).
- **Right panel — live test & cost (sticky):**
  - A **test console**: send a sample message / simulate a call; stream the agent's response;
    show each tool call as a precise log line with a status dot. This proves the config works.
  - A **cost estimate strip**: as config changes (model, tools, knowledge size), show an
    updating mono estimate — `~$0.031 / run` and a projected `~$46 / mo at 1.5k runs`. Values
    animate calmly (tabular-nums, no jitter).

**Footer bar (sticky):** version indicator (mono, e.g. `v3 · draft`), "Discard", and
"Save & deploy" (accent). Saving pins a config version (reinforce the "config is versioned"
idea with a tiny mono version chip).

**Behavior:** autosave drafts; unsaved-changes guard; validation inline; everything keyboard
navigable. Config is a form, but it should feel like tuning an instrument — precise and
responsive.

---

## 9. Screen — Connectors

**Goal:** connect agents to the tools a company already uses, with permissions as a
first-class, visible thing.

**Layout:**
- Page header: eyebrow `03 · CONNECTORS`, H1 "Connect your tools", subhead "Give your agents
  scoped access to the systems you already run."
- A **segmented filter**: All · Connected · Messaging · CRM · Email · Calendar · Voice ·
  Custom (MCP/HTTP).
- A **catalog grid** of connector cards (3–4 up). Each card:
  - A line-style monochrome logo mark placeholder (never a real third-party logo — use a
    neutral glyph + name) and the connector name.
  - A one-line description of what agents can do with it.
  - A **status chip**: `CONNECTED` (success dot + account name) or `AVAILABLE`.
  - Action: "Connect" (accent) or "Manage" (secondary) if connected.
- Always include a **Generic MCP / HTTP** card as the escape hatch (custom integrations).

**Connect flow (right drawer):**
1. **Choose scopes** — a checklist of permissions the connector can grant (e.g. "Read
   messages", "Post messages", "Read contacts"), each with a mono scope name and plain
   description. Default to least privilege.
2. **Authorize** — a stubbed OAuth-style step ("Continue to {Service}") → simulated return.
3. **Bind** — choose which agents may use this connector and with which scopes.
4. **Done** — success toast; card flips to `CONNECTED`; show the granted scopes as mono chips.

**Manage state:** for a connected tool, show the account, granted scopes, which agents use it,
last-used timestamp (mono), a "Re-authorize" and a destructive "Disconnect" (with confirm).

**Emphasize trust:** every connector view makes scopes and which-agent-can-use-what explicit.
Keep it calm and legible — this is a security surface.

---

## 10. Screen — Dashboard

**Goal:** fleet mission-control at a glance — who's running, what it's costing, what just
happened.

**Layout (top to bottom):**
- Page header: eyebrow `01 · DASHBOARD`, H1 "Your agent workforce", subhead with workspace
  name. Quiet line-art in the top-right corner.
- **Stat tile row (4 tiles, hairline-separated):**
  - Active agents (count + status breakdown dots).
  - Spend today (mono money + delta vs. yesterday).
  - Runs today (count + sparkline).
  - Wallet balance (mono + "days of runway at current burn" mono hint).
  Tiles are flat, hairline-bordered, mono numerics, no heavy color — the accent appears only
  on the live/spend figure.
- **Spend over time chart:** a clean line/area chart of spend across the last 30 days, with a
  toggle for per-agent breakdown (stacked). Hairline axes, mono tick labels, single accent
  line for total, muted greys for per-agent series. Minimal, precise — follow the dataviz
  principles (accessible, tabular-nums, no chartjunk). Hover = mono tooltip.
- **Agents table:** every agent as a row — status dot + name, role, model, runs today, spend
  today (mono), budget usage (a thin hairline progress bar, accent fill, turning warning/danger
  near the cap), and a row action menu (pause / configure / view). Sortable mono headers,
  sticky header, hover highlight. This is the daily driver — make it fast and legible.
- **Recent activity feed:** a compact, timestamped (mono) stream of notable events — runs
  completed, caps hit, connector errors, top-ups — each with a status dot. Keep it a quiet
  right rail or a section below the table.

**Empty state:** if no agents, the line-art is larger and centered with "Deploy your first
agent" → agent selection.

---

## 11. Screen — Realtime billing

**Goal:** the moat, made visible — accurate, live, per-agent spend with budgets and a usage
ledger. This screen should feel like a precision instrument panel (the telecom-charging
heritage, expressed as calm engineering UI).

**Layout:**
- Page header: eyebrow `04 · BILLING`, H1 "Spend & settlement", subhead "What every agent is
  costing you, in real time."
- **Live meter header (hero of this screen):**
  - Current **wallet balance** (large mono, accent dot) with a live "updating" micro-indicator.
  - **Burn rate** — current spend velocity (e.g. `$0.42 / min`, mono) with a small live
    sparkline that ticks calmly.
  - **Runway** — projected days/hours at current burn.
  - A subtle accent pulse or a single moving tick conveys "live" — never flashing or loud.
  Use an `aria-live="polite"` region so updates are announced, with tabular-nums so figures
  don't jitter.
- **Per-agent spend breakdown:** a table or horizontal bar list — each agent with its live
  spend today, this month, share of total (thin accent bars), and its budget usage. Over-cap
  agents show the danger state.
- **Budgets & caps panel:** workspace-level and per-agent budgets as editable rows — period,
  limit (mono), current usage bar, and action-on-breach (alert / throttle / stop). Create/edit
  in a drawer. Alerts show as a quiet banner when a threshold is near.
- **Usage ledger (the audit trail):** an append-only, newest-first table of rated usage
  events — timestamp (mono), agent, run id (mono, truncated), provider/model, quantity
  (tokens / calls), unit price, and line cost (mono, 4-decimal). Filter by agent / date /
  type. A "Reconciles with provider invoices" mono note reinforces trust. Export button.
- **Cost composition:** a small, precise breakdown of spend by type — model tokens vs. tool/API
  fees vs. platform fee — as a minimal stacked bar or a clean legend+figures block (not a pie).

**Tone:** everything mono, aligned, exact. This is where "one place to see and pay for all
your agents" becomes tangible — make it feel trustworthy and alive without being noisy.

---

## 12. Screen — Payment / Add funds

**Goal:** fund the wallet and manage billing settings with a clean, confidence-inspiring
checkout. (Stub the processor; present it as Stripe-style without any Stripe branding.)

**Layout:**
- Page header: eyebrow `· PAYMENT`, H1 "Add funds", subhead "Top up your balance. Agents draw
  from it as they work."
- **Two-column (desktop), stacked (mobile):**
  - **Left — amount & method:**
    - Current balance (large mono, accent).
    - Preset top-up tiles ($20 / $50 / $100 / $250) + custom amount field (mono).
    - Optional **auto-reload** toggle: "Automatically add $__ when balance falls below $__"
      — a key retention feature; present it calmly with mono fields.
    - Payment method: a clean card form (number / expiry / CVC / name) with inline validation,
      brand-neutral card glyph, and saved-methods list if any. Hairline fields, accent focus.
  - **Right — summary (sticky):**
    - Order summary: amount, any fee line, total (mono).
    - A reassurance block: "You only pay for what your agents do. Unused balance stays yours."
    - **Pay** / **Add funds** button (accent), with idle / loading / success / error states.
    - Trust row: mono "Secured payment · PCI compliant" (generic, no real brand marks).
- **States:** processing (button "Processing…", disabled), success (in-place confirmation —
  "Added $50.00. New balance $1,334.50." with a calm check, not confetti; link back to
  dashboard), error (inline, specific, retryable).
- **Billing settings tab/section:** billing email, invoices list (mono dates + amounts +
  download), payment methods management, and the link between a depleted balance and agents
  pausing (explain it plainly).

**Behavior:** full keyboard nav, labelled fields, `aria-live` on the result, never store or
log card data (it's a stub); make it obvious where a real processor plugs in.

---

## 13. Motion & interaction (global)

- **Mount:** content fades in and rises 8–16px (400–600ms, ease-out), lightly staggered.
- **Line-art:** drifts slowly (20–40s loop) on hero/empty states; static elsewhere.
- **Hover:** buttons shift subtly; cards brighten their border (no shadow lift); links
  underline; table rows get `--surface-2`.
- **Live billing:** figures update smoothly with tabular-nums (no layout shift); the live
  indicator is a single calm pulse/tick, never flashing.
- **Overlays:** drawers slide in from the right (240–320ms); modals fade+scale from 98%.
- **Reduced motion:** `prefers-reduced-motion: reduce` freezes line-art and replaces all
  transitions with instant state changes. Required.

---

## 14. Responsive & accessibility

- **Breakpoints:** design for ~375 / 768 / 1280+. Sidebar collapses to an icon rail, then a
  drawer on mobile; the top bar keeps the wallet pill and "+ New agent".
- **Tables on mobile:** collapse to stacked cards (label:value rows, mono values) rather than
  horizontal scroll where possible.
- **Contrast:** body text uses `--ink`/`--body` on `--canvas` (AA); reserve `--muted` grey for
  large or secondary text only — verify every pair. Do not put small grey body text on
  off-white.
- **Keyboard:** full tab order, visible accent focus rings, skip-to-content, no keyboard traps;
  modals/drawers trap focus correctly and close on Esc.
- **Screen readers:** semantic landmarks (header/nav/main), one H1 per screen, ordered
  headings, status dots paired with text labels (never color alone), decorative line-art
  `aria-hidden`, billing updates in polite live regions.
- **Forms:** real labels, inline errors tied with `aria-describedby`, clear required markers.

---

## 15. Tech, output & what to avoid

**Stack & output:**
- React + TypeScript + Tailwind (or your builder's default) — componentized, one component
  per concept (Sidebar, TopBar, StatTile, AgentCard, ConnectorCard, UsageLedger, LiveMeter,
  TopUpForm, Stepper, StatusDot, WalletPill, …).
- Google Fonts only (Archivo/Space Grotesk, Inter, IBM Plex Mono). No paid/licensed assets.
- Line-art as inline SVG (static) or a lightweight canvas flow-field (hero/empty only).
- Mock data in a `mockData.ts`; stub all handlers with clear TODOs where the AgentOS API wires
  in. Keep routes for each screen so it's navigable.
- Tokens as CSS variables / Tailwind theme extension so the palette is swappable.

**What to avoid:**
- Generic SaaS looks: purple/indigo gradients, glassmorphism, neon glows, blurry blobs.
- Heavy drop shadows and 3D — stay flat and hairline (one soft shadow for overlays only).
- Stock illustrations, 3D robots, clip-art agents, or filled emoji icons. The line-art and
  minimal line-glyphs are the only imagery.
- Any real company's logo, name, or trademark (including payment processors and the
  engineering tools whose *sensibility* inspired this) — use neutral glyphs and generic labels.
- Color used decoratively — the accent means "action / live / money", nothing else.
- Jittery or flashing live updates; loud success animations; dark patterns in payment
  (pre-checked auto-reload, hidden fees, fake urgency).

---

## 16. Build order (suggested)

1. Design system + app shell (sidebar, top bar, tokens, line-art accent, core components).
2. Dashboard (proves the shell, tiles, chart, table, status language).
3. Agent selection → Agent configuration (the deploy→tune core loop).
4. Connectors (catalog + scoped connect drawer).
5. Realtime billing (live meter + ledger + budgets).
6. Payment (top-up + settings).
7. Onboarding (ties it together; build last so the destinations exist).

Build each screen against this file, keep the whole thing calm and exact, and let the
whitespace and hairlines — not color — carry the premium feel.
