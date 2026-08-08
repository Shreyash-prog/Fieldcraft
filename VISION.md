# Fieldcraft — Vision

**The measure-and-govern layer for AI-assisted software delivery.**

*This document describes where Fieldcraft is headed and the roles it serves — the full product vision, not (mostly) what is built today. A short "where this stands today" note at the end grounds it against the working product. Throughout, each capability is marked **core** (rides the measurement/governance substrate that largely exists), **reach** (needs meaningful new capability), or **vision — hardest** (deep, high-stakes, to be built later once it can be proven safe), so the ambition stays honest rather than hand-wavy.*

---

## 1. The thesis

AI made *writing code* cheap and fast. It did not make *shipping trustworthy software* cheap — and it broke the tools every role used to trust delivery. A ticket marked "done" no longer means what it used to. Velocity counts work that may all need redoing. QA can't review the volume. Ops runs systems assembled by agents they never watched. And nobody has a principled way to give an agent *just enough* access to do the work without handing it the keys to production.

Fieldcraft's answer has two load-bearing halves:

- **Measure** — how effectively was AI-assisted work actually done? Read honest signals (iterations, effectiveness, operator/steering quality, cost, gate outcomes) from the delivery loop itself.
- **Govern** — what are agents allowed to do, and can we prove it? Enforce a standard code must meet before it ships, and broker least-privilege, audited access to the tools and data agents touch.

One measurement-and-governance engine, served through **many role lenses** at different altitudes — individual, team, assurance, and production. That "one engine, many lenses" structure is what makes Fieldcraft a product rather than a pile of dashboards: each lens is a different *view and aggregation* of the same substrate, so new audiences cost little new engineering.

**A principle that runs through everything: the metrics must resist gaming.** The moment a delivery metric becomes a management KPI, people optimize the metric instead of the work — including by weakening the very tests that verify it. Fieldcraft's credibility depends on measures that are hard to cheat (verification-integrity checks, and ultimately production reality, which cannot be gamed). "An accountability layer you can't cheat" is the moat, not a footnote.

---

## 2. The lenses

Fieldcraft serves six role lenses, spanning the delivery org: the person *doing* the work, the person *planning and tracking* it, the person *assuring* it, the people *running and governing* it in production, and — across all of them — the accumulated memory of everyone who has ever worked the board. Each lens is a different view and aggregation of one shared measurement-and-governance substrate.

### 2.1 The FDE lens — individual accountability

**Protagonist:** the forward-deployed engineer. **Accountable to:** their manager.
**Mode:** both **preventive** (a gate — code doesn't ship below standard) and **retrospective** (a scorecard — how well they used AI).

AI made it trivial to ship code fast. This lens makes the FDE accountable for whether it's *good*, and coaches them to use AI *well*. Accountability is framed as evidence in the FDE's favor — demonstrable proof of quality that protects them when a customer questions the delivery — not merely a stick.

Two axes, seven accountabilities:

**The artifact — what the AI shipped:**
- **Robustness under the trap** — not just "tests pass" but "does it handle the edge case the FDE didn't think to test?" The signature original idea. *(reach — the trap is by definition the unknown; approaches include a library of known trap-classes per domain such as idempotence/null-handling/unicode/concurrency, mutation testing, or an adversarial second agent that tries to break the first agent's code.)*
- **Security of AI-generated code** — did the AI introduce a hardcoded secret, an injection, an unsafe eval? *(core — governance/policy layer exists.)*
- **Verification integrity** — did the FDE or the AI weaken or delete tests to make it pass? *(core — integrity gate exists.)*

**The practitioner — how they operated:**
- **Cost discipline** — did they burn disproportionate token spend on the task? *(core — durable ledger exists.)*
- **Quality of steering** — did they give the AI *good* direction, or rubber-stamp? Did the human comment carry information the agent didn't already have? The metric no competitor can easily copy, because it requires the loop + the three-mode comparison mechanism. This is the heart of the lens. *(core — operator-quality is measured today.)*
- **Appropriate autonomy** — did they let the agent run unsupervised on something that needed a human, or babysit something trivial? *(reach — calibrated trust; may need outcome data.)*
- **Escalation judgment** — did they know when to stop and ask a human vs push the agent harder? *(reach — closely related to autonomy; may fold into one "calibration" measure.)*

**Strategic note:** because the FDE is accountable *to* their manager, this is structurally a management tool — a real, fundable category (the AI-native equivalent of LinearB/DX for human teams), with the known failure mode that KPIs get gamed. The anti-gaming principle is therefore load-bearing here specifically.

### 2.2 The PM / scrum-master lens — team delivery-truth

**Protagonist:** the project manager / scrum master. **Core anxiety:** "'Done' and estimation and velocity all stopped meaning anything the moment AI started writing the code."

This lens is the same substrate as the FDE lens, **aggregated from individual → team / sprint / release.** Same engine, different altitude, different (and possibly better first) buyer: the FDE has accountability *pushed* on them; the PM has pain the tool *pulls* to solve. Six themes, seventeen capabilities:

**Delivery truth** *(core)*
- Trustworthy "done" — closed *and verified*, with a confidence level, not just a Jira status.
- Quality-adjusted velocity — throughput that counts only work that actually met standard.
- Visible rework — the sprint waste spent redoing AI work that shipped bad the first time.
- Risk concentration — where the release is fragile (which tickets went autonomous, most AI / least steering).

**Planning & forecasting**
- Re-baselined estimation — what work *really* costs in the AI era, from actual iteration/cost data. *(core)*
- Sprint-commitment confidence — before the sprint, can this team truly deliver these tickets given how AI-assisted work actually flows here? *(reach)*
- AI-suitability triage — which backlog tickets AI will breeze vs flail on, so the PM triages *before* committing. Moves Fieldcraft upstream into planning, where PMs have most power and least tooling. *(reach — needs prediction.)*

**In-flight visibility**
- AI-honest standup — the board shows *actual* state (this ticket went 4 iterations and still fails the gate), not self-reported "80% done." *(core)*
- Stuck / thrashing detection — an FDE burning iterations/cost with no convergence is the AI-era "blocked," invisible today; surfaced in real time. A scrum-master favorite. *(core)*
- Silent scope creep — the agent quietly touched 15 files for a "small" ticket. *(core)*

**Quality & release**
- Release-readiness gate — roll per-ticket confidence up into an evidence-backed go/no-go for the whole release. *(core)*
- Rework root-cause — not just *that* there was rework but *why* (bad steering? missing context? over-ambitious autonomy?), so the PM fixes the process. *(reach)*

**Team health & coaching**
- Over / under-trusting AI — a team-level calibration pattern ("your team defaults to autonomous on risky tickets"). *(reach)*
- Onboarding / ramp visibility — is a newcomer's AI-assisted work converging like a veteran's? Ramp measured objectively. *(reach)*
- Knowledge concentration — bus-factor risk when only one person can steer the agent well on a module. *(reach — ties to the codebase "brain.")*

**Cost & budget**
- Sprint AI-spend forecast & burn — tokens as a first-class sprint metric ("60% through the sprint, 90% through the AI budget"). *(core)*
- Cost-per-outcome trends — getting more efficient with AI over time, or just spending more? *(reach — needs longitudinal data.)*

### 2.3 The QA lens — targeted assurance and standard-setting

**Protagonist:** the QA team. **Core crisis:** AI ships more code than any team can humanly review. The old economics of QA are broken.

Fieldcraft's distinctive value here: it tells QA **where to look.** And QA is not just a consumer — it is a **co-author of the standard.** Four themes plus a two-way loop:

**Triage & focus** *(the killer group)*
- Risk-based review routing — review the risky ~10% (autonomous, high-iteration, weak steering, fragile areas) rather than everything (impossible) or a random sample (useless). *(core)*
- "This one's probably fine" signals — deprioritize clean, fast-converging, well-steered changes *with evidence*. *(core)*

**Trust & provenance**
- How was this built? — QA reviews a diff today blind to whether a human guided it or an agent one-shot it; Fieldcraft supplies iterations, steering quality, autonomy, gate outcome. Review *with context.* *(core)*
- Was verification real or gamed? — surface weakened or deleted tests. *(core)*

**Coverage of the unknowns**
- Trap / edge-case coverage — point QA at thin coverage, not the happy path — QA's actual value-add. *(reach)*
- Regression blast radius — scope creep defines what to regression-test. *(core)*

**Workflow & feedback**
- Findings become gate checks — a defect QA catches teaches the standard so it's never caught twice (the flywheel). *(reach)*
- QA effectiveness on AI work — is QA catching AI-era defects, or applying human-era methods that miss them? *(reach)*

**The two-way loop (what makes QA central, not peripheral):** QA both *uses* the risk signals to review smarter **and** *feeds findings back* to harden the gate — shifting QA from "review everything" to "direct where scrutiny goes." QA becomes a risk-targeting function, not a bottleneck.

### 2.4 The Platform / Ops lens — living with what shipped

**Protagonist:** Platform + Software Operations (SRE / DevOps / on-call). **Core crisis:** every other lens stops at "shipped." Ops is the only one that *lives with* what was shipped — at 3am, when it breaks — yet inherited zero new visibility into how AI-built code came to be.

This lens closes the loop: **build → run → incident → back into the standard.** Production is the ultimate ground truth — the one signal that *cannot* be gamed, because prod doesn't lie — which makes Ops the source of the most credible feedback in the entire system, and the anti-gaming principle's ultimate backstop.

**Incident response (the 3am problem)**
- Incident-to-provenance trace — when prod breaks, instantly answer "was this AI-built? autonomous? un-reviewed? did it pass the gate?" The killer capability; that context is gone today the moment the PR merges. *(core — provenance substrate exists.)*
- Faster root-cause — a high-iteration, weakly-steered, autonomous change narrows the hunt. Provenance as a debugging accelerant. *(core)*
- "What changed and how" at a glance — AI-context of recent deploys during an incident, not just the git log. *(core)*

**Pre-production risk**
- Deploy-time change-risk score — before it ships, how risky is this AI-built change to *operate*? *(reach)*
- Blast-radius / scope-creep awareness — the real surface area to know what to monitor. *(core)*
- AI-change canary targeting — high-risk AI changes get careful rollout; clean ones ride the normal path. *(reach)*

**Operational reality of AI-built systems**
- Fragility mapping — a heat-map of where AI-built, weakly-verified code concentrates in production. *(reach)*
- Operational-debt visibility — AI tech debt as *pages you'll get*, seen before it becomes incidents. *(reach)*
- Reliability by provenance — do autonomous AI changes actually fail in prod more than human-steered ones? Data that validates or challenges the thesis. *(reach)*

**The feedback loop**
- Incidents become gate checks — a production failure hardens the gate so that class of bug is caught before the next deploy. The flywheel's most valuable loop. *(reach)*
- Post-incident → accountability — an incident traced to a weakly-steered autonomous change flows back into the FDE scorecard and the PM's risk view, connecting production reality to individual/team accountability. *(reach)*

### 2.5 Agent access control — the least-privilege control plane

**The deepest, highest-stakes pillar. A distinct pillar, not a sub-item — arguably a peer of "measure" as a core half of the product ("govern").**

**The control problem:** an agent needs access to *do* the work, but every grant of access is attack surface. Too little → the agent can't finish, or a human hands it broad credentials "just to unblock it" (the real-world failure). Too much → a badly-steered, prompt-injected, or simply wrong agent drops a table, racks up a cloud bill, or leaks data. Ops holds this line today with no principled tool — either give agents a human's credentials (terrifying) or block them (useless). Fieldcraft is the control plane that brokers **just enough** access to any tool or system the software-engineering discipline uses — version control, CI/CD, cloud, databases and warehouses, container and package registries, secrets stores, message queues, observability, ticketing, and the rest. The principle is tool-agnostic; the tools are just instances of it.

**Scope — just enough**
- Least-privilege grants per task — access scoped to the ticket, not standing credentials.
- Capability granularity — read vs write vs DDL vs delete, per resource.
- Resource scoping — this schema / bucket / warehouse; staging, not prod.

**Time & lifecycle**
- Ephemeral, expiring grants — minted for the run, revoked when it ends; no standing agent credentials to steal.
- Just-in-time issuance — the token appears only when the step needs it.

**Guardrails on dangerous operations**
- Destructive-op approval gates — DROP, DELETE-without-WHERE, prod write, resource deletion → human approval *at grant time*, enforced at the broker, not hoped for in the prompt. The thing that stops the 3am horror story.
- Environment segregation — sandbox by default; prod is a deliberate, gated, audited exception.
- Cost / rate guards on infra — no 50-instance spin-up, no 10TB scan; resource caps, not just spend caps.

**Provenance & audit**
- Every access logged, attributed, tamper-evident — which agent, task, FDE; what it could reach and did reach.
- Access-to-incident correlation — trace a prod incident to exactly what the agent was granted.

**The customer control plane (the original platform vision)**
- The customer defines the boundaries — per connection, exactly what agents may create / edit / delete on any system they connect.
- Per-connection, per-role policies — the platform enforces the intersection of *what the task needs* and *what the customer allows*.

**Scoped by engineering role** (access differs by domain — every discipline gets what its work requires and nothing more): **Data** — warehouses, transformation, and pipeline tooling · **Backend** — databases, APIs, and queues · **Infra / platform** — cloud, provisioning, and deployment tooling · **Frontend** — minimal, scoped. The point is the pattern, not any particular vendor.

> **Honesty flag — the hardest thing to build safely.** Brokering least-privilege, ephemeral credentials to AI agents touching *production* infrastructure, with destructive-op gates that actually hold, is the deepest and highest-stakes capability in the whole vision. Everything else is measurement (reading signals about work); this is control (an agent, on real keys, with write access to a customer's production data). The gap between a diagram of scoped access and a system that safely enforces it is enormous. Marked deliberately as build-later, prove-safe-first — the same honesty discipline applied to every claim.

### 2.6 The team brain — compounding organizational memory

**What it is:** cross-team, cross-repo, cross-task organizational memory that makes experience *compound* instead of evaporate. This goes beyond a per-repo knowledge base (the conventions and traps of one codebase). It is the accumulated *problem-solving experience* of everyone who has ever worked the board — made retrievable so the next person solving a similar problem gets a recommendation instead of starting from scratch.

**Why it is uniquely a Fieldcraft capability:** every other team-memory attempt (wikis, docs, tribal chat) captures only what people bothered to write down — almost nothing, and it rots. Fieldcraft already records *every task on the board as a run with full provenance*: the problem, the approach, the iterations, what steered it, the trap, the gate outcome, what QA caught, what shipped. The team brain is therefore not a new data source — it is a **retrieval layer over the substrate that already exists.** That recorded corpus pays a second dividend.

**Retrieval — "someone solved this before" (the killer)**
- Similar-problem recommendation — pick up a ticket and Fieldcraft surfaces "N people solved something like this — here's how, here's the trap they hit, here's the steering that worked." Proactive, at the moment of work. *(reach)*
- Cross-repo pattern matching — the same *shape* of problem (pagination, idempotency, an auth edge case) recurs across different repos; the brain matches on the problem, not the code. *(reach)*
- "Who knows this" routing — surface the *person* who solved the closest version. Expertise location. *(reach)*

**Two altitudes (high and low)**
- High-level map — the shape of problems the org solves, the recurring themes, where knowledge concentrates. An architect/leader view. *(reach)*
- Low-level map — the specific solved instance: this exact function, this exact trap, this exact fix. The retrieval a developer needs mid-task. *(reach)*

**Compounding lessons (the anti-repeat engine)**
- Trap memory — a trap someone already hit becomes a *warning* the next person gets before they hit it. The flywheel, org-wide and cross-repo. *(reach)*
- Solution reuse — a validated approach becomes a suggestible starting point, not a blank page. *(reach)*
- Anti-pattern memory — "this was tried and failed / caused an incident" — so people don't re-walk dead ends. *(reach)*

**Cross-team — DEV ↔ QA**
- QA memory feeding DEV — a class of bug QA caught on similar work warns the *builder* up front, not after. QA's findings become DEV's foresight. *(reach)*
- Shared board memory — both teams' tasks on one board means the brain sees the *whole* lifecycle of a problem (built → tested → what QA found → shipped), so a recommendation carries the full story. *(reach)*

**Onboarding & continuity**
- Ramp acceleration — a newcomer inherits the team's solved-problem memory instead of starting cold. *(reach)*
- Bus-factor dissolution — knowledge that lived in one person's head is now in the brain; the person leaving doesn't take it with them. Directly answers the knowledge-concentration risk flagged in the PM lens. *(reach)*

**Visibility is first-class — the right access, no more.** A team brain is only safe if it enforces *who can see whose experience*:
- **Within a team** — full sharing; members see each other's solved problems and traps.
- **Between teams** — controlled, permissioned recommendations; shared where it helps, scoped where it shouldn't be.
- **Across customers / tenants** — a hard boundary; one customer's memory can *never* surface to another. Within one org this is a feature; across customers it would be a breach, so the boundary is explicit and enforced.

> **Reach flag.** This is the most technically ambitious measurement-side lens. It needs genuine retrieval and similarity — embedding tasks, matching problem-shapes across repos, ranking relevance — real RAG / agentic-retrieval engineering, not just aggregation. A substantial build. But it is the lens that turns Fieldcraft from a *measurement* tool into a *compounding-intelligence* tool: the org gets measurably better over time because experience accumulates instead of evaporating.

---

## 3. The spine — one engine, many lenses

The lenses are not separate products. They are views of a single substrate:

- **The measurement substrate** — iterations, effectiveness, operator/steering quality, cost, and gate outcomes, captured from the governed delivery loop and recorded as an auditable event log.
- **The governance substrate** — the standard code must meet to ship (the gate), the policy/integrity checks, and the access-control broker.

Every lens is a **different aggregation and view** of these:

- **FDE** — the substrate at the *individual* altitude, framed as accountability.
- **PM** — the substrate *aggregated to team / sprint / release*, framed as delivery-truth.
- **QA** — the substrate as *risk-routing* signals, plus a feedback path that shapes the standard.
- **Ops** — the substrate followed *into production*, framed as provenance and incident-tracing, feeding ground truth back.
- **Access control** — the *governance* half, framed as a customer-configured least-privilege control plane.
- **Team brain** — the substrate as a *retrieval layer*, turning recorded runs into cross-team, cross-repo recommendations, under strict visibility controls.

Two properties make the whole thing cohere:

1. **New audiences are cheap.** A new lens is mostly a new view, not a new engine — which is why the PM, QA, and Ops lenses are largely aggregations of what the FDE substrate already produces.
2. **The loop closes.** FDE builds → PM tracks → QA assures → it ships → Ops runs it → when production reality disagrees with the gate, that truth flows *back* and hardens the standard for everyone. Production incidents — ungameable ground truth — are the most credible input in the system.

---

## 4. Cross-cutting principles

- **Metrics must resist gaming.** The product's credibility is that its measures can't be cheated — verification-integrity checks, and ultimately production reality. This is the moat.
- **Accountability as evidence, not just a stick.** The framing that makes a manager-facing tool survive with the people it measures is "this makes you demonstrably good and protects you when questioned," not surveillance.
- **Honesty about what's real.** Every capability is marked core / reach / vision-hardest. The hardest, highest-stakes capability (the access-control plane) is flagged as build-later, prove-safe-first. This honesty is what makes the vision credible rather than hand-wavy — and it mirrors the honest, tested discipline of what is already built.
- **One engine, many lenses.** Resist building per-audience products; build one substrate and serve many roles as views.
- **The loop closes in production.** Ground truth from Ops is what keeps the whole standard honest over time.

---

## 5. Where this stands today (grounding note)

A working, deployed, honestly-scoped version of the core already exists: a governed develop→verify→iterate loop; a calibrated LLM-as-judge (measured across live runs); a governance/policy layer with verification-integrity and a policy gate; graph orchestration; a durable spend ledger with per-user and global caps; invite-gated multi-user access with an operator admin view; a three-mode comparison (reviews-only vs reviews-plus-comments vs autonomous) that already measures operator/steering quality; and a "Try it" playground that teaches the steering-quality thesis on curated tasks. The measurement substrate the lenses ride is therefore partly real, not hypothetical.

What is *not* yet built is most of what turns that substrate into the multi-role, multi-lens platform above — the per-role dashboards and aggregations, the production/Ops provenance loop, and above all the agent access-control plane, which remains the hardest and highest-stakes piece.

This document is the map. The build follows it deliberately, core before reach, and never ships control it hasn't proven safe.
