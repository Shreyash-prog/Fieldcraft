# Fieldcraft — Vision

This document describes where Fieldcraft is headed. It is **forward-looking**: almost nothing in this file is built yet. The current, working system is described in `README.md`; the work required to get from here to there is in `HARDENING.md`. This file exists so the repo reflects intent, not just current state.

## The thesis

AI made writing code cheap. It did not make *shipping trustworthy software in someone else's environment* cheap. Teams adopting coding agents hit three walls: **trust** (is the change actually correct, and did the agent cut a corner to get there?), **control** (can I keep an autonomous agent inside guardrails — which files, which systems, which operations need a human?), and **proof** (is AI actually making us faster/cheaper/better, and where is it falling short?).

Fieldcraft's core already targets that: a governed loop that runs agents safely and *measures how effectively the human+AI delivered*. The vision extends that core into a **product surface** a customer can adopt.

## The product: a work board over a governed, measured agent runtime

The customer-facing surface is a **Jira-style board**. Work items (tickets) are the unit. Each ticket carries the context an agent needs and connects to the systems it must act on — all under access the customer configures. Running a ticket kicks off the governed, measured loop that already exists, now operating against real connected systems instead of bundled sample tasks.

### Connections (the integration fabric)

Each ticket can attach and draw on:

1. **Codebase** — a real remote repository (GitHub/GitLab/Bitbucket): authenticated connect, clone, branch, and PR. The agent works on a branch; changes land as reviewable PRs, never direct pushes.
2. **Codebase knowledge brain** — an Obsidian-style linked-notes knowledge layer for the codebase (conventions, architecture, gotchas, glossary). The current Field Guide + flywheel is the seed of this: it already bootstraps a repo into traps/conventions/retrieval and learns over time. The vision makes it a first-class, linkable, human-curated knowledge graph.
3. **Reference documentation** — Confluence pages, PDFs, and other docs attached to a ticket for the agent to consult (design docs, runbooks, API specs).
4. **Operational connections**, each with **access controlled and configured by the customer**:
   - **Cloud (AWS / Azure / GCP)** — scoped access for infrastructure tasks. The customer configures exactly what the agent may create, edit, or delete, per connection.
   - **Databases** — scoped access for data operations, again with the operation set (read / write / DDL / delete) controlled per connection.
   - Other developer-grade connections as needed (CI/CD, issue trackers, observability, secrets stores) — same principle: least privilege, customer-configured, fully audited.

The non-negotiable design principle across every connection: **the customer configures the access; the agent never holds standing credentials; every action is scoped, approved where destructive, and audited.**

### What running a ticket does

Pick a ticket → the graph runs (plan → code → verify → critic → review → integrate) against the connected systems → policy and scoped credentials gate every external action → a human reviews and approves (especially destructive ops) → the ticket closes with an **after-action score** (was it effective, efficient, and how well did the human+AI operate) and a complete **audit trail** of every action and decision.

### The single view

One product view shows everything for a ticket: the connections, the live run timeline, the diff/PR, the policy decisions, the credential grants used, the human-review gate, and the measurement. The current web app (overview, SSE timeline, diff viewer, history, policy editor, reports) is the prototype of this view.

## Who it's for

- **Forward-deployed / solutions engineers** dropped into a customer environment to ship AI solutions fast — Fieldcraft is the harness that lets them run agents *safely* on the customer's systems and *prove* the delivery worked.
- **Engineering leaders** adopting AI tooling who need governance (audit, policy, least-privilege) and a defensible effectiveness metric.
- **Platform / DevEx teams** who would own an internal "safe way to run agents against our systems."

## Differentiation

Code-generation tools (Cursor, Copilot, Devin) help you *generate*. Engineering-analytics tools (LinearB, DX) measure *human* teams. Fieldcraft measures **human+AI delivery effectiveness at the loop level** and **governs the agent while it acts across a customer's trust boundary** — the combination is the differentiator, and the per-node measurement of the graph is a genuinely novel piece.

## What must be true first

This vision is a **trust-boundary product**, and the trust boundary is the part not yet built. Before any real connection is wired — especially cloud and database access — the prerequisites in `HARDENING.md` are not optional; they are the foundation. In particular: sandboxed, credential-free execution; authentication and tenant isolation; a real scoped-credential backend (not the current in-memory model); durable spend enforcement; and provenance/injection defenses on all ingested content. Building a convincing *demo* of the connection fabric is achievable soon; building the *safe, real* version is the substantial work ahead.
