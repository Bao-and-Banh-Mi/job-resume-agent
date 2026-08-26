# ADR-001: Local-First, Provider-Agnostic Architecture

- **Status:** Accepted
- **Date:** 2026-08-25
- **Decision owners:** Project maintainers

## Context

The product processes resumes, job descriptions, contact information, and potentially confidential employment evidence. The user wants to use an existing OpenAI, Anthropic, or local-model setup, but a hosted proxy would create unnecessary data retention and credential risk. Provider APIs and authentication mechanisms also differ.

## Decision

Build the MVP as a single-user, local-first application:

1. A local FastAPI backend owns the experience bank, tailoring pipeline, review state, and LaTeX/PDF rendering.
2. SQLite stores user data locally; the user can export the bank and wipe application data.
3. All model calls go through a provider adapter interface. Initial adapters are OpenAI, Anthropic, Ollama, and a deterministic NullAdapter for tests.
4. Provider secrets are stored through the operating system keychain, not SQLite, config files, logs, or hosted infrastructure.
5. The Chrome extension communicates only with the local backend. It never calls an LLM provider directly and never receives provider credentials.
6. The renderer and evidence linker are deterministic gates. Model output is a proposal and cannot bypass provenance or approval checks.

## Consequences

### Positive

- User-authored resume data does not pass through project-operated servers.
- Provider changes are isolated behind adapters.
- Offline and deterministic testing is possible with NullAdapter.
- A future hosted mode can be designed separately rather than accidentally emerging from the MVP.

### Negative

- Users must install and run a local backend.
- BYO API keys can be confusing and provider billing is the user's responsibility.
- Cross-device sync is not available in v1.
- Loopback authentication, keychain integration, and sandboxed LaTeX compilation add implementation work.

## Alternatives rejected

### Hosted project-operated LLM proxy

Rejected for v1 because it centralizes sensitive resume/JD data and provider credentials, increasing breach and compliance scope.

### Direct provider calls from the extension

Rejected because it would require exposing credentials to browser extension code and broadening extension/network permissions.

### Provider-specific implementation throughout the codebase

Rejected because it makes testing, local models, and future providers expensive and encourages accidental credential/data leakage.

## Revisit triggers

Create a superseding ADR before changing this decision if any of the following occurs:

- multi-user cloud sync becomes a product requirement;
- a provider offers a suitable user-scoped OAuth flow for a local app;
- the extension needs to communicate with a hosted service;
- a second LaTeX template materially changes the validator or renderer boundary.
