# ADR 002 — Svenbot Link: iPhone-to-Mac agent with one shared UI

**Status:** Proposed, 2026-11-21. **This file is a specification, NOT a deployed remote access system or an implementation claim.** Owner repository: Svyable/svenbot. It builds on the separate Chrome Companion v0.7.2 and the future durable Mission Control scheduler (#14).

## User outcome

From an iPhone, say: "Check my Etsy orders, draft replies, reconcile my listings, and ask before publishing." A Mac that the user paired acts as the local execution node. The phone and computer show the same tasks, progress, sources, approval prompts and final artifacts. No copying secrets into a chat window; API access is via a narrowly scoped OAuth connector or a secret form whose contents are hidden from the model.

### Platform truth

- **Chrome on iOS does not install Chrome Web Store desktop extensions.** Ship the iPhone side as an installable HTTPS **PWA** opened from Chrome and added to Home Screen; share the reusable UI/design system with the Mac Chrome extension. It is one product/identity, not literally the same extension binary. Google: https://support.google.com/chrome/answer/9658361?co=GENIE.Platform%3DiOS&hl=en-001 and https://support.google.com/chrome/thread/328134795/adding-extensions-to-iphone-chrome-app
- **Phone PWA cannot inspect arbitrary other Chrome tabs, continuously control apps while backgrounded, or use Mac APIs.** For iPhone share-sheet extensions/Siri/Shortcuts and more device permissions, a separately distributed native iOS or Safari extension wrapper may eventually be required. Apple Safari web extensions require an app wrapper: https://developer.apple.com/documentation/safariservices/safari-web-extensions
- **Mac Chrome MV3 workers are not persistent daemons.** The actual always-on scheduler, models, filesystem controls and credential vault must run in a signed Mac companion/helper (can be installed as one app). It can be used without opening Chrome. If the Mac sleeps, local execution stops; jobs should show "waiting for Mac", never "completed." https://developer.chrome.com/docs/extensions/develop/concepts/service-workers/lifecycle
- **Outside-home access requires network transport.** Default ease-of-use path: an opt-in hosted rendezvous/message relay that carries opaque end-to-end encrypted envelopes only, while Mac initiates outbound connections (no router port forwarding). Advanced self-hosted mode: Tailscale Serve private HTTPS. A relay still learns limited metadata/availability and must not be marketed as "zero cloud"; APIs like Etsy themselves receive authorized API calls.

## Minimal setup target

1. On Mac, install the signed **Svenbot Mac** app. It installs/starts a user-scoped local helper with explicit consent, discovers Ollama/llama.cpp and supported hardware, and offers one model. It does **not** automatically download a large model, require Terminal or request Full Disk Access at install.
2. Mac app displays **Pair your iPhone** QR code. On iPhone, open the branded HTTPS PWA in Chrome (Add to Home Screen optional), scan the code with camera or open its link. Confirm a human-readable device identity and short authentication phrase on both devices.
3. Phone immediately shows connected status, chat, model, tasks, approvals and sources. Mac extension is optional for browser-tab access: user can add it when they need page reading or browser actions. Never request broad host permissions at initial install.
4. "Connect Etsy" opens **Etsy OAuth 2.0 authorization with PKCE**, requesting the smallest supported scopes. Mac connector stores tokens in macOS Keychain, uses them via a tool adapter, and passes results—not secrets—to the model. Sensitive mutations require an explicit action preview and approval.
5. Speak or type an instruction from the phone. Show task state, delegated tool scopes, what is awaiting approval, what actually completed and what failed.

**One app + one QR + one explicit integration authorization** is the target, not a promise already achieved. Chrome on Mac may require separate extension installation to read tabs.

## Architecture

```text
iPhone Chrome -> installable PWA (HTTPS; same UI components as Mac)
    | account-less device identity; QR pins Mac pairing public key
    | encrypted command, status and approval envelopes
    v
Hosted minimal relay (no model, no Etsy credentials, no plaintext)
    ^ outbound-only Mac connection; short offline ciphertext retention
    |
Mac Svenbot companion/helper (background user process)
    |- authenticated device list + revocation
    |- durable Mission Control (#14): queued/leased/blocked/uncertain/completed
    |- local model router: small model by hardware, user upgrades explicitly
    |- OAuth/secret vault in macOS Keychain; connector-specific scopes
    |- explicit tool-capability policy + review before writes
    |- durable artifacts/evidence receipts locally, minimized phone copies
    |
Mac Chrome extension (optional; separate scoped adapter)
    |- activeTab user consent, page context, preview, browser approvals
    |- never a universal remote command endpoint
```

## Security requirements (gates, not TODO comments)

**Device pairing.** QR is short-lived and one-time-use, carrying rendezvous ID, relay origin and a pinned Mac device public key fingerprint, never permanent API credentials. Use well-reviewed, interoperable cryptographic primitives (e.g. Web Crypto P-256 ECDH/HKDF/AES-GCM with an audited compatible Mac library). Have the Mac explicitly accept/reject the enrolling phone key and confirm a short verification phrase. Do not invent custom encryption. Secure private keys in platform stores where supported; test backup/restore, key rotation, revocation and lost phones. Relay MUST NOT be able to impersonate a new device without explicit pairing consent.

**Wire protocol.** Versioned envelopes with authenticated sender/device identity, message ID, expiry, replay prevention, max bytes, sequence semantics and idempotency key. Queue ciphertext with bounded TTL. Ack, retry and cancellation are distinct from execution; never call an Etsy write complete merely because the relay received it. Persist action ledger before invoking side effects. For uncertain external writes, reconcile with provider or require human review before retrying.

**Permissions.** Explicit, deny-by-default capabilities: start with `chat`, `list_tasks`, `inspect_artifact`, `request_approval`; Etsy connector grants read-only before write scopes. No generalized `run_shell`, `read_home_directory`, `click_anything` or multi-tab Chrome permissions by default. The model proposes tool calls and explanations; a separate policy engine authenticates the device, checks scopes, expiry and user approval before invoking real tools. Page contents, emails and documents are untrusted prompt-injection surfaces.

**Secrets.** Never ask users to paste Etsy API keys into chat or extension content scripts. Display a dedicated credential handoff / OAuth browser flow. Store any provider secret on the Mac in Keychain, avoid logging token values, never include them in model prompts, relay messages, artifacts or support bundles. Clear/disconnect/revoke credentials. Etsy official docs: https://developer.etsy.com/documentation/essentials/authentication/ ; Apple Keychain: https://developer.apple.com/documentation/security/keychain-services .

**Transport/uptime.** End-to-end encrypt payloads before sending to a hosted relay; relay operator can still see metadata such as destination, time and sizes. TLS and authenticated relay access still required. The Mac must be online and awake to perform local tasks. Background browser service workers alone cannot guarantee continuous work; the user-scoped Mac helper must own queued jobs. PWA push notifications require installation/permission/platform support; don't claim unrestricted background voice or iPhone app automation.

**Separation.** A mobile phone cannot automatically obtain the Mac extension's page permissions. A paired device can request actions, but every Mac capability has its own consent boundary. No public unauthenticated listener, no wildcard CORS or port-forwarding advice as the default.

**Business/IP.** Recreate the workflow and user benefits; do not use Grok Bot proprietary code, designs, service trademarks, distribution assets or private APIs. Open source and weights are separately licensed; pin exact versions and audit dependencies.

## Model tiers (no magical default)

- **Inkling 2 Small is not a small Mac model:** 594B total / 17B active parameters per official card, impractical on normal consumer Macs. https://huggingface.co/thinkingmachines/Inkling-2-Small
- **Inkling 2 Mini (released 2026-11-20)**: 26.4B total, ~20GB weights, vendor-supported for Apple silicon with **32GB or more unified memory**. Apache-2.0 model license. Good opt-in "power" model on eligible machines, *not* the zero-friction default for all. https://thinkingmachines.ai/model-card/inkling-2-mini/ and https://thinkingmachines.ai/news/inkling-2-mini/
- **Default**: choose a much smaller tested local text model (e.g. Qwen 3.5 0.8B/4B tiers or Gemma 4 E2B) based on real available unified RAM and measured throughput. Show download/installation size, license, capabilities and consent before obtaining weights. Phone remains mostly a control/chat client; do not download 20GB weights to an iPhone as a prerequisite.
- Model selection must be tied to independent real-machine task-quality, first-token latency, memory and browser-automation reliability tests. Larger is not automatically better.

## Build roadmap and acceptance

**L1 — Same interface, no dangerous tools.** Refactor shared conversation/task status UI for Mac extension and HTTPS PWA. PWA works in Chrome iPhone without extensions, supports chat/task status and ephemeral approval mock. Mac agent serves a local authenticated endpoint behind a private HTTPS development tunnel. No real remote capability until crypto/pairing is verified. Tests: mobile Safari/Chrome safe areas, offline status, keyboard, voice permissions, real iPhone browser testing.

**L2 — Real device pairing + relay.** One-time QR enrollment, pinned device keys, encrypted messages, explicit Mac confirmation, revocation, two-way task state, offline queue and reconnect. Keep relay stateless for content and never store plaintext. Test two independent devices across mobile data and home Wi-Fi, expired QR/replay, stolen token, relay compromise simulation, duplicate delivery, Mac sleep, browser close. Demonstrate that the server cannot decrypt sample commands.

**L3 — Persistent mission execution.** Reuse #14 DAG scheduler with 20-task replay fixture. Explicit task approval, typed tools, audit trail, artifacts and progress. Tests for crashes before/after provider side effects, replay, concurrency, expiry, cancellation and remote device revocation.

**L4 — Etsy connector.** Registered developer app, OAuth PKCE, read-only inventory/orders first. Dry-run listing updates with diff preview; approved mutations with idempotency/reconciliation. Test revoked/expired token, scope downgrade, duplicate event, wrong shop and rollback semantics. Include financial and customer-data privacy review.

**L5 — Product polish.** Signed/notarized Mac app, extension Web Store, branded iPhone PWA, install instructions, model presets, microphone/voice UI, notifications, support and recovery. Later native iPhone wrapper for Shortcuts/Share Sheet and richer device integration.

### Go/no-go tests

- Fresh user: Mac app install + QR scan + iPhone chat on different networks without CLI, router changes or manual credentials for the pairing itself.
- 0 unapproved external writes in a deliberate prompt-injection and approval-bypass test suite.
- At-least-once transport and **exactly-once local recording**; no claim of globally exactly-once Etsy calls without provider guarantees.
- 100% confirmed queued-vs-executing-vs-completed status correctness across 20-task offline/restart fixture.
- Model never receives Etsy refresh tokens or plaintext pairing secrets in captured trace fixtures.
- Time-to-first-action, memory use, power consumption, model downloads and phone data transfer measured on specified hardware.
- Complete privacy disclosures: PWA/relay presence, Mac uptime dependency, third-party Etsy API, local model/provider logging.

## Prior art / source links

- Grok Bot user-facing desktop+phone workflow: https://docs.x.ai/grok-bot/mobile , https://docs.x.ai/grok-bot/security
- Chrome iOS extension limitation and PWA installation: https://support.google.com/chrome/thread/328134795/adding-extensions-to-iphone-chrome-app and https://support.google.com/chrome/answer/9658361?co=GENIE.Platform%3DiOS&hl=en-001
- Etsy OAuth + PKCE: https://developer.etsy.com/documentation/essentials/authentication/
- MV3 service workers: https://developer.chrome.com/docs/extensions/develop/concepts/service-workers/lifecycle
- Apple Keychain: https://developer.apple.com/documentation/security/keychain-services
- Private HTTPS alternative Tailscale Serve: https://tailscale.com/docs/features/tailscale-serve
- Inkling 2 Mini vendor model card: https://thinkingmachines.ai/model-card/inkling-2-mini/

**Non-goals for the first PR:** pretending Chrome iOS supports the extension, copying Grok Bot binaries, installing models silently, exposing API keys to a model, bypassing vendor UI/API limits, unattended payment or listing changes, deploying an unreviewed relay, or claiming the Mac can work when it is asleep/offline.
