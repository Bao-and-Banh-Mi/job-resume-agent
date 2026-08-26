# Security and Privacy

Privacy is a design constraint, not a compliance checklist. This document is prescriptive — if a change violates a stated posture below, it needs an ADR.

## 1. Trust boundaries

There are four:

1. **User's browser tab** — untrusted. Content scripts read the DOM but never grant the page any capability back.
2. **Chrome extension** — semi-trusted. Talks only to the local backend on loopback.
3. **Local backend** — the "trusted computing base" of the app. Owns the bank and evidence.
4. **Third-party LLM provider** — trusted only to receive the specific prompt the user's tailoring run built, over the user's own credentials, over the user's own network egress.

No data crosses a boundary in ways the user did not initiate.

## 2. Threat model

We enumerate concrete threats and, for each, the design's mitigation.

### T1 — Malicious webpage tries to exfiltrate the bank

*Vector:* a JD page hosts crafted JS that tries to talk to the extension or to `127.0.0.1`.

*Mitigations:*
- Extension has **no `externally_connectable`** (no web pages can `postMessage` to the extension).
- Backend binds to `127.0.0.1` only, uses a **per-install self-signed TLS cert pinned by the extension on first run**, and requires a per-request bearer token issued during pinning. Page-origin JS cannot obtain this token.
- Backend rejects requests without the correct `Origin` header (limited allowlist including the extension's chrome-extension:// origin and the UI origin served by the backend itself) and enforces CORS strictly.

### T2 — Extension permission overreach

*Vector:* extension quietly gains broad host permissions in an update, allowing page-content exfiltration.

*Mitigations:*
- Extension ships with the **narrowest possible `host_permissions`** (see §4). Any broadening requires an ADR + version bump users see at update time.
- **No remote code execution.** MV3 is strict on this; we do not use `chrome.scripting.executeScript` with remote-fetched code, and we do not load remote scripts in the popup/side panel.

### T3 — Provider adapter leaks bank content into logs

*Vector:* an adapter accidentally logs full prompts including PII / NDA-adjacent content.

*Mitigations:*
- Adapter logs are redacted by default; prompts are logged only in `--debug` mode and only under `~/.local/share/job-resume-agent/debug/` with `0600` perms.
- Provider requests are annotated with a `prompt_id` (ULID) so users can grep for a specific request without dumping content.

### T4 — Fabrication reaches export

*Vector:* the LLM emits a bullet with an invented metric; a bug in the evidence linker misses it; the user clicks *Approve all*.

*Mitigations:*
- The evidence linker is deterministic and property-tested; new numeric tokens absent from cited evidence classify as `unsupported`, gating export (see [`data-model.md`](data-model.md)).
- The *Approve all* button surfaces a distinct confirmation whenever any bullet is `inferred` or `unsupported`; unsupported bullets cannot be approved without either editing to match evidence or adding evidence.

### T5 — Credential theft from disk

*Vector:* another process on the user's machine reads the provider API key.

*Mitigations:*
- API keys live in the OS keychain (Keychain on macOS, Credential Manager on Windows, Secret Service on Linux). We store only a `secret_ref` in the DB.
- Ollama needs no key.
- If the OS keychain is unavailable (some Linux headless setups), we refuse to persist and prompt for the key per-session, with a clear rationale.

### T6 — `pdflatex` sandbox escape or shell injection via user text

*Vector:* the user's bank text contains crafted LaTeX that runs shell commands or reads files.

*Mitigations:*
- `pdflatex -no-shell-escape` unconditionally.
- LaTeX AST validator (see [`technical-architecture.md#latex-validation-strategy`](technical-architecture.md#6-latex-validation-strategy)) rejects `\write18`, `\input`, `\include`, `\catcode`, `\usepackage`, and any command not on the template's allowlist.
- The binder escapes LaTeX-special characters (`# % & _ $ ^ ~ \`) in user-supplied text before insertion.
- Per-request temp dir, CPU/wall-clock timeouts, OS sandboxing where available.

### T7 — Draft invalidation after bank edit

*Vector:* user edits the bank, then exports a stale draft that references bullets/evidence that changed or were deleted.

*Mitigations:*
- Drafts snapshot `bank_version`. If the current bank version differs at export time, the UI blocks export and requires a re-evidence pass against the current bank.

### T8 — Extension MITM on loopback

*Vector:* a local attacker (malware) proxies `127.0.0.1` traffic.

*Mitigations:*
- Loopback TLS with a per-install cert whose fingerprint is pinned by the extension on first run.
- Bearer token bound to the pinning ceremony; rotated on `wipe`.
- Residual risk: local malware with equivalent user privilege can already dump the SQLite DB directly. We document this rather than pretend to defend against it.

### T9 — Telemetry drift

*Vector:* future contributor adds "helpful" telemetry that leaks JD content or bank content.

*Mitigations:*
- Telemetry is **off** in v1. Adding any is an ADR-worthy decision. When added, it is anonymous, opt-in, and never includes user-authored strings.

## 3. Data classification

| Data | Classification | Where it lives | Egress rules |
|---|---|---|---|
| Experience bank + evidence | **Sensitive-PII** | Local SQLite + app-data dir | Only the specific retrieved items go to the user's chosen LLM |
| Provider API keys | **Secret** | OS keychain | Never in DB, logs, or crash reports |
| JD text and URL | **Sensitive** | Local DB | Sent to LLM for tailoring only |
| Rendered PDF / .tex | **Sensitive** | User-chosen output dir | Never uploaded |
| Fixture data in repo | **Public-synthetic** | Repo | N/A |
| Debug logs | **Sensitive if enabled** | `~/.local/share/job-resume-agent/debug/` | Never uploaded |

## 4. Extension permissions rationale

Manifest V3. Minimum viable set:

| Permission | Why we ask | Why not broader |
|---|---|---|
| `activeTab` | Read the JD on the tab the user activates the extension on | Avoids blanket `<all_urls>` host permission |
| `scripting` | Inject the JD extractor when the user clicks the button | Only used with `activeTab`; no remote scripts |
| `storage` | Store extension-local settings (backend cert pin, feature flags) | `chrome.storage.local` is per-extension and per-profile |
| `sidePanel` | Host the extension's UI | No new privileges vs. popup |
| `host_permissions` (narrow allowlist) | Auto-run JD detector on `linkedin.com/jobs/*`, `*.greenhouse.io/jobs/*`, `*.lever.co/*/jobs/*`, `*.ashbyhq.com/*`, `*.myworkdayjobs.com/*` | Broader host permissions would let the extension read any page silently |

**Deliberately not requested:**

- `<all_urls>` — would let the extension read every page. We use per-site allowlists + `activeTab` for the generic fallback.
- `webRequest` / `declarativeNetRequest` — no need; we don't inspect or block traffic.
- `cookies` — never needed; we do not authenticate to job boards.
- `identity` — we don't do OAuth in the extension.
- `nativeMessaging` — no; the backend runs as a normal user process, communication is HTTPS-loopback.

## 5. Credentials

- API keys go into the OS keychain the moment the user pastes them; they are never written to SQLite, config files, or logs.
- The DB stores a `secret_ref` string. On startup the backend resolves it via the keychain adapter (`keyring` on Python) or refuses to start.
- On `wipe`, keychain entries in the `job-resume-agent:*` namespace are removed.
- If the user pastes a key into the review UI, the browser input has `autocomplete="off"` and the value is transmitted to the backend over loopback TLS and immediately handed to the keychain — never persisted in a form draft, never echoed to the DOM.

## 6. Provider OAuth vs. BYO-key (design decision)

We prefer BYO API key over provider OAuth in v1 because:

- OpenAI and Anthropic **do not currently offer a consumer OAuth flow** that grants scoped access to a user's chat completions on their behalf; access is via API keys created in the user's console.
- OAuth flows that *do* exist (e.g., Google, Azure) are provider- and account-tier-specific and add substantial UX and support burden for a local-first tool.
- A BYO key that the user pastes into their local machine and that never leaves it is *strictly less surface* than an OAuth flow terminating on a server we operate.

If a provider adds a proper user-scoped OAuth flow suitable for locally-installed apps (with refresh tokens stored client-side), we will add it as an optional path in a later phase (see [`roadmap.md`](roadmap.md#m4)). Until then, key-based auth via OS keychain is the safe default.

## 7. Data flow constraint (enforced in CI)

A CI check greps for:
- Non-provider modules importing provider SDKs (`openai`, `anthropic`, `ollama`).
- HTTP client instantiations outside `packages/providers/*` and the backend's loopback server.
- New `host_permissions` in the extension manifest.

Any violation fails CI. Loopholes require an ADR.

## 8. Incident posture

Because there is no hosted service, a "security incident" in v1 is a local vulnerability (e.g., a `pdflatex` sandbox escape). Response:

1. Publish an advisory in the repo's `SECURITY.md` (added when v1 ships).
2. Ship a patched release; the extension auto-updates via Chrome Web Store; the backend prompts the user to update on startup.
3. If the vuln allowed credential exfiltration, prompt users to rotate their API keys and re-run `wipe`.

## 9. What we explicitly do *not* claim

- We do not claim SOC2, ISO 27001, or any certification. There is no hosted service to certify.
- We do not claim the model won't hallucinate. We claim we will *catch and refuse to ship* hallucinations that add facts, via the evidence linker.
- We do not claim to defend against a compromised operating system or a malicious admin.
