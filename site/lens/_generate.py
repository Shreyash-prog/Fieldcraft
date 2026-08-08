#!/usr/bin/env python3
"""Emit the six lens pages from one template so they stay pixel-identical in
structure. Only the copy and the diagram body differ per page."""
import os, textwrap

OUT = "site/lens"

GH = "https://github.com/Shreyash-prog/Fieldcraft/tree/main"
LI = "https://www.linkedin.com/in/shreyash-k-a89823174/"
DEMO = "https://fieldcraft-shreyash.fly.dev"

GH_SVG = ('<svg viewBox="0 0 16 16" width="17" height="17" fill="currentColor" aria-hidden="true">'
 '<path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82a7.42 7.42 0 0 1 2-.27c.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.01 8.01 0 0 0 16 8c0-4.42-3.58-8-8-8Z"/></svg>')
LI_SVG = ('<svg viewBox="0 0 16 16" width="17" height="17" fill="currentColor" aria-hidden="true">'
 '<path d="M3.6 5.3H.9V15h2.7V5.3ZM2.25 1A1.55 1.55 0 1 0 2.25 4.1 1.55 1.55 0 0 0 2.25 1ZM15 9.5c0-2.6-1.4-3.8-3.25-3.8-1.5 0-2.17.82-2.54 1.4V5.3H6.5c.04.76 0 9.7 0 9.7h2.71V9.6c0-.24.02-.49.09-.66.19-.49.63-1 1.38-1 .97 0 1.36.74 1.36 1.83V15H15V9.5Z"/></svg>')

FAVICON = ("data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'>"
 "<rect width='32' height='32' rx='9' fill='%2314e0b0'/><text x='16' y='23' font-size='19' "
 "font-weight='700' font-family='sans-serif' text-anchor='middle' fill='%2303130f'>F</text></svg>")

# ── shared SVG scaffolding ────────────────────────────────────────────────────
DEFS = '''<defs>
      <marker id="ah" viewBox="0 0 9 9" refX="7.6" refY="4.5" markerWidth="6.4" markerHeight="6.4" orient="auto-start-reverse">
        <path d="M0.8 1 L7.4 4.5 L0.8 8" fill="none" stroke="rgba(255,255,255,.3)" stroke-width="1.25" stroke-linecap="round" stroke-linejoin="round"/>
      </marker>
      <marker id="aha" viewBox="0 0 9 9" refX="7.6" refY="4.5" markerWidth="6.4" markerHeight="6.4" orient="auto-start-reverse">
        <path d="M0.8 1 L7.4 4.5 L0.8 8" fill="none" stroke="#14e0b0" stroke-width="1.35" stroke-linecap="round" stroke-linejoin="round"/>
      </marker>
      <marker id="ahw" viewBox="0 0 9 9" refX="7.6" refY="4.5" markerWidth="6.4" markerHeight="6.4" orient="auto-start-reverse">
        <path d="M0.8 1 L7.4 4.5 L0.8 8" fill="none" stroke="#f2b544" stroke-width="1.35" stroke-linecap="round" stroke-linejoin="round"/>
      </marker>
    </defs>'''

def box(x, y, w, h, cls="d-node", r=11):
    return f'<rect class="{cls}" x="{x}" y="{y}" width="{w}" height="{h}" rx="{r}"/>'

def t(x, y, s, cls="d-t", anchor=None):
    a = f' text-anchor="{anchor}"' if anchor else ""
    return f'<text class="{cls}" x="{x}" y="{y}"{a}>{s}</text>'

def line(d, cls="d-l", marker="ah", extra=""):
    return f'<path class="{cls}{extra}" d="{d}" marker-end="url(#{marker})"/>'

def dot(x, y, fill="#14e0b0", r=3.2):
    return f'<circle cx="{x}" cy="{y}" r="{r}" fill="{fill}"/>'


# ══ DIAGRAM 1 — FDE ══════════════════════════════════════════════════════════
def dia_fde():
    p = []
    # inputs
    p += [box(16, 26, 286, 152), t(38, 56, "THE ARTIFACT", "d-k")]
    for i, s in enumerate(["Robustness under the trap",
                           "Security of AI-written code",
                           "Verification integrity"]):
        p += [dot(40, 84 + i*30 - 4, "rgba(255,255,255,.28)", 2.6), t(56, 88 + i*30, s, "d-s")]
    p += [box(16, 202, 286, 196), t(38, 232, "THE PRACTITIONER", "d-k")]
    # the accented row carries a second line, so the rows below it get extra room
    prac = [(256, "Cost discipline", False), (286, "Quality of steering", True),
            (328, "Appropriate autonomy", False), (358, "Escalation judgment", False)]
    for y, s, hot in prac:
        p += [dot(40, y - 4, "#14e0b0" if hot else "rgba(255,255,255,.28)", 3.2 if hot else 2.6),
              t(56, y + 4, s, "d-ta" if hot else "d-s")]
    p += [t(56, 308, "the signature metric", "d-ka")]
    # spine
    p += [box(376, 168, 132, 96, "d-node"), t(398, 198, "ONE RUN", "d-k"),
          t(398, 224, "Recorded", "d-t"), t(398, 246, "every turn", "d-f")]
    p += [line("M302 102 C 342 102 342 192 376 192"),
          line("M302 300 C 342 300 342 240 376 240")]
    # outputs
    p += [box(574, 58, 290, 136, "d-node-a"), t(598, 90, "PREVENTIVE", "d-ka"),
          t(598, 120, "The gate", "d-t"),
          t(598, 146, "Work below the standard", "d-s"),
          t(598, 168, "does not ship.", "d-s")]
    p += [box(574, 250, 290, 136, "d-node-a"), t(598, 282, "RETROSPECTIVE", "d-ka"),
          t(598, 312, "The scorecard", "d-t"),
          t(598, 338, "How well this engineer", "d-s"),
          t(598, 360, "actually used AI.", "d-s")]
    p += [line("M508 194 C 542 194 542 126 574 126", "d-la", "aha"),
          line("M508 238 C 542 238 542 318 574 318", "d-la", "aha")]
    p += [t(541, 108, "gate", "d-ka", "middle"), t(541, 372, "score", "d-ka", "middle")]
    return 430, "".join(p)


# ══ DIAGRAM 2 — PM ═══════════════════════════════════════════════════════════
def dia_pm():
    p = [t(16, 42, "EVERY RECORDED RUN", "d-k")]
    runs = ["TCK-19548d56", "TCK-77a6ed03", "TCK-9160d7ea", "and every one after"]
    for i, s in enumerate(runs):
        y = 62 + i*62
        faint = i == 3
        p += [box(16, y, 186, 52, "d-node-q" if faint else "d-node", 9),
              dot(38, y + 26, "rgba(255,255,255,.22)" if faint else "#14e0b0", 3),
              t(54, y + 31, s, "d-f" if faint else "d-s")]
        p += [line(f"M202 {y+26} C 236 {y+26} 236 206 268 206")]
    p += [box(268, 146, 180, 120, "d-node-a"), t(292, 178, "AGGREGATE", "d-ka"),
          t(292, 208, "Sprint / release", "d-t"),
          t(292, 234, "same records,", "d-f"), t(292, 252, "team altitude", "d-f")]
    outs = [("Trustworthy “done”", "a closed ticket you can bank on"),
            ("Quality-adjusted velocity", "speed measured at constant outcome"),
            ("Visible rework", "what got re-opened, and what caused it"),
            ("Risk concentration", "where the fragility actually clusters")]
    for i, (a, b) in enumerate(outs):
        y = 50 + i*86
        p += [box(520, y, 344, 74, "d-node"), t(542, y + 32, a, "d-t"), t(542, y + 56, b, "d-f")]
        p += [line(f"M486 206 C 502 206 502 {y+37} 520 {y+37}", "d-la", "aha")]
    p += [line("M448 206 H 486", "d-la", "aha")]
    return 430, "".join(p)


# ══ DIAGRAM 3 — QA ═══════════════════════════════════════════════════════════
def dia_qa():
    p = []
    p += [box(16, 176, 168, 80), t(38, 208, "AI output", "d-t"),
          t(38, 232, "more than QA", "d-f"), t(38, 250, "can ever read", "d-f")]
    p += [box(240, 176, 190, 80, "d-node-a"), t(262, 202, "RISK ROUTING", "d-ka"),
          t(262, 228, "Scores every change", "d-s"), t(262, 248, "before a human looks", "d-f")]
    p += [box(520, 48, 250, 100, "d-node-a"), t(544, 82, "Review the risky 10%", "d-t"),
          t(544, 108, "human attention, spent", "d-f"), t(544, 126, "where it actually pays", "d-f")]
    p += [box(520, 292, 250, 100, "d-node-a"), t(544, 326, "Findings feed the gate", "d-t"),
          t(544, 352, "what QA catches becomes", "d-f"), t(544, 370, "an automatic check", "d-f")]
    p += [box(240, 296, 190, 84, "d-node-q", 9), t(262, 326, "The other 90%", "d-s"),
          t(262, 348, "probably fine —", "d-f"), t(262, 366, "and evidenced", "d-f")]
    p += [line("M184 216 H 240")]
    p += [line("M430 200 C 476 200 476 98 520 98", "d-la", "aha"), t(474, 148, "escalate", "d-ka", "middle")]
    p += [line("M770 98 C 826 98 826 342 770 342", "d-l", "ah"), t(846, 226, "review", "d-k", "middle")]
    p += [line("M520 342 C 470 342 470 244 430 236", "d-la", "aha"),
          t(470, 300, "harden", "d-ka", "middle")]
    p += [line("M334 256 V 296", "d-l", "ah", " d-dash")]
    return 430, "".join(p)


# ══ DIAGRAM 4 — OPS ══════════════════════════════════════════════════════════
def dia_ops():
    p = []
    nodes = [(20, "Build", "the agent writes it", "d-node", "d-t", None),
             (236, "Ship", "gate cleared, merged", "d-node", "d-t", None),
             (452, "Production", "what actually happens", "d-node-a", "d-ta", "GROUND TRUTH"),
             (668, "Incident", "3am, something broke", "d-node-w", "d-tw", None)]
    for x, title, sub, cls, tc, kick in nodes:
        p += [box(x, 44, 176, 96, cls)]
        if kick:
            p += [t(x + 22, 74, kick, "d-ka"), t(x + 22, 102, title, tc), t(x + 22, 124, sub, "d-f")]
        else:
            p += [t(x + 22, 86, title, tc), t(x + 22, 112, sub, "d-f")]
    p += [line("M196 92 H 236"), line("M412 92 H 452"), line("M628 92 H 668", "d-lw", "ahw")]
    p += [t(236, 166, "← every other lens stops here", "d-k")]
    p += [box(340, 216, 300, 100, "d-node-a"), t(364, 248, "PROVENANCE TRACE", "d-ka"),
          t(364, 276, "How the AI built it", "d-t"),
          t(364, 298, "policy · steering · cost · approvals", "d-f")]
    p += [line("M756 140 C 756 200 700 266 640 266", "d-lw", "ahw")]
    p += [box(20, 330, 290, 92, "d-node-a"), t(44, 362, "THE STANDARD HARDENS", "d-ka"),
          t(44, 392, "Incidents become gate checks", "d-t")]
    p += [line("M340 300 C 336 348 332 376 310 376", "d-la", "aha")]
    p += [line("M110 330 V 144", "d-la", "aha", " d-dash")]
    p += [t(122, 244, "the loop closes", "d-ka")]
    return 440, "".join(p)


# ══ DIAGRAM 5 — ACCESS ═══════════════════════════════════════════════════════
def dia_access():
    p = []
    p += [box(16, 178, 156, 88), t(38, 212, "Agent", "d-t"),
          t(38, 236, "needs access", "d-f"), t(38, 254, "to do the work", "d-f")]
    p += [box(240, 62, 250, 312, "d-node-a"), t(264, 96, "ACCESS BROKER", "d-ka"),
          t(264, 126, "Just enough. No more.", "d-t")]
    rows = [("SCOPE", "only what this task needs"),
            ("TIME-LIMIT", "ephemeral, just-in-time"),
            ("GUARDRAILS", "destructive ops gated"),
            ("AUDIT", "every grant, every call")]
    for i, (k, s) in enumerate(rows):
        y = 150 + i*54
        p += [box(260, y, 210, 46, "d-node", 8), t(276, y + 19, k, "d-ka"), t(276, y + 37, s, "d-f")]
    p += [box(560, 62, 300, 150), t(584, 94, "ANY TOOL ENGINEERING USES", "d-k"),
          t(584, 124, "Repos · Cloud · Databases", "d-t"),
          t(584, 150, "Internal APIs · CI · Secret stores", "d-f"),
          t(584, 180, "tool-agnostic by design", "d-ka")]
    p += [box(560, 262, 300, 112, "d-node-w"), t(584, 294, "DESTRUCTIVE OP", "d-kw"),
          t(584, 324, "Human approval gate", "d-tw"),
          t(584, 350, "drop table · delete bucket · rotate prod", "d-f")]
    p += [line("M172 222 H 240"), line("M490 138 H 560", "d-la", "aha"),
          line("M490 318 H 560", "d-lw", "ahw")]
    p += [t(525, 124, "grant", "d-ka", "middle"), t(525, 304, "stop", "d-kw", "middle")]
    p += [t(240, 408, "Boundaries are configured by the customer — not assumed by us.", "d-f")]
    return 450, "".join(p)


# ══ DIAGRAM 6 — BRAIN ════════════════════════════════════════════════════════
def dia_brain():
    p = [t(16, 40, "EVERY RECORDED RUN", "d-k")]
    runs = [("a trap someone already hit", False), ("a convention this repo wants", False),
            ("a fix that actually worked", False), ("and everything after", True)]
    for i, (s, faint) in enumerate(runs):
        y = 58 + i*54
        p += [box(16, y, 214, 44, "d-node-q" if faint else "d-node", 9),
              dot(38, y + 22, "rgba(255,255,255,.22)" if faint else "#14e0b0", 3),
              t(54, y + 27, s, "d-f")]
        p += [line(f"M230 {y+22} C 248 {y+22} 248 166 264 166")]
    p += [box(264, 96, 182, 140, "d-node-a"), t(288, 128, "RETRIEVAL LAYER", "d-ka"),
          t(288, 158, "Similarity over", "d-t"), t(288, 180, "every run ever", "d-t"),
          t(288, 208, "not a wiki nobody", "d-f"), t(288, 226, "opens", "d-f")]
    p += [line("M446 166 H 510", "d-la", "aha")]
    p += [box(510, 58, 350, 216, "d-node-a"), t(534, 90, "AT THE MOMENT OF WORK", "d-ka")]
    hits = ["Someone solved this before — here",
            "This file has bitten three people",
            "QA→DEV foresight: what breaks next"]
    for i, s in enumerate(hits):
        y = 110 + i*52
        p += [box(532, y, 306, 44, "d-node", 8), dot(556, y + 22, "#14e0b0", 3),
              t(574, y + 27, s, "d-s")]
    p += [box(16, 318, 844, 134, "d-node-q"), t(40, 350, "VISIBILITY IS FIRST-CLASS", "d-k")]
    cells = [(40, "Within a team", "FULL", "d-node-a", "d-ka"),
             (322, "Between teams", "CONTROLLED", "d-node-w", "d-kw"),
             (604, "Across customers", "HARD BOUNDARY", "d-node", "d-k")]
    for x, title, status, cls, kc in cells:
        p += [box(x, 366, 232, 66, cls, 9), t(x + 20, 396, title, "d-t"), t(x + 20, 418, status, kc)]
    return 470, "".join(p)


# ── page content ─────────────────────────────────────────────────────────────
PAGES = [
 dict(slug="fde", half="Measure", halfcls="is-measure", n="Lens 01",
   role="Forward-deployed engineer", title="Individual accountability",
   q="“Is this engineer using AI well — and is what they shipped any good?”",
   problem="AI made shipping fast, and then quietly removed the only things that used to hold a "
     "person to account for it. Volume no longer signals effort. A clean diff no longer signals "
     "care. Nobody can tell whether the engineer drove the model well or just accepted whatever "
     "came back first.",
   does="Fieldcraft holds the forward-deployed engineer accountable to their manager on both "
     "halves at once. A <b>preventive gate</b> stops work that falls below the standard from "
     "shipping at all. A <b>retrospective scorecard</b> records how well they actually used AI to "
     "get there — measured from the run, not self-reported.",
   dia=dia_fde,
   cap="<b>Two axes, two outputs.</b> The artifact is judged on what it is; the practitioner on "
     "how they got there. The same run record feeds a gate that acts before the work ships and a "
     "scorecard that reads after it did.",
   caps=["<b>Robustness under the trap</b> — does it survive the case a first attempt misses?",
         "<b>Security of AI-written code</b> — credentials, dynamic execution, network reach.",
         "<b>Verification integrity</b> — was it actually proven, or just asserted?",
         "<b>Cost discipline</b> — what this outcome was worth paying for.",
         "<b>Quality of steering</b> — did their feedback carry information the model didn't have?",
         "<b>Appropriate autonomy</b> — hands-off where it was safe, hands-on where it wasn't.",
         "<b>Escalation judgment</b> — did they stop and ask at the right moment?"],
   hi="<b>Quality of steering is the metric nobody else can copy.</b> It only exists if you "
      "recorded the whole loop — the attempt, the human's response, and what changed because "
      "of it. Tools that watch commits never see it happen."),

 dict(slug="pm", half="Measure", halfcls="is-measure", n="Lens 02",
   role="PM &amp; delivery lead", title="Team delivery-truth",
   q="“Is this work actually on track, and can I trust what ‘done’ means?”",
   problem="AI broke three things at once: <b>done</b>, <b>estimation</b>, and <b>velocity</b>. A "
     "closed ticket may be solid or may be fragile, and the board looks identical either way. "
     "Story points stop meaning anything when an agent closes ten tickets in a day and four of "
     "them come back next sprint.",
   does="Nothing new is collected. The same per-run measurement, aggregated to a sprint or a "
     "release, gives a delivery lead something they have not had since AI arrived: <b>delivery "
     "truth</b>. Velocity adjusted for quality, rework made visible instead of absorbed, and "
     "estimation re-baselined against what runs actually cost.",
   dia=dia_pm,
   cap="<b>Same engine, team altitude.</b> Individual run records aggregate into four surfaces a "
     "delivery lead can act on. Nothing here is a second measurement system — it is the same "
     "data, read from further back.",
   caps=["<b>Trustworthy “done”</b> — a closed ticket carries the evidence that closed it.",
         "<b>Re-baselined estimation</b> — grounded in real iteration counts, not memory of a pre-AI world.",
         "<b>Quality-adjusted velocity</b> — speed only counts when the outcome held.",
         "<b>Visible rework</b> — what came back, how often, and traced to which run.",
         "<b>Risk concentration</b> — which files and which people the fragility clusters around.",
         "<b>Stuck detection</b> — iteration counts climbing with no movement in outcome."],
   hi="<b>The thing a PM loses to AI is calibration.</b> Every heuristic they had for “that "
      "sounds like three days” was trained on humans typing. Fieldcraft rebuilds that "
      "calibration from measured runs instead of asking the team to guess again."),

 dict(slug="qa", half="Measure", halfcls="is-measure", n="Lens 03",
   role="QA", title="Targeted assurance",
   q="“Where do we point scarce review attention?”",
   problem="AI ships more code than any team can humanly review. The economics of QA broke: the "
     "queue grows faster than the reviewers, and reviewing everything a little is worse than "
     "reviewing the right things properly. Sampling at random is what most teams quietly do now.",
   does="Fieldcraft tells QA <b>where to look</b>. Every run carries signals — iterations "
     "burned, criteria graded conservatively, policy near-misses, files with history — that "
     "route attention to the changes that earned it. Then it closes the loop: what QA finds "
     "becomes a gate check that runs automatically from then on.",
   dia=dia_qa,
   cap="<b>A loop, not a funnel.</b> Routing decides what gets human eyes; what those eyes find "
     "goes back into the routing and into the gate. QA stops being a queue at the end and starts "
     "being an input to the standard.",
   caps=["<b>Risk-based routing</b> — rank every change by how likely it is to be wrong.",
         "<b>“Probably fine” signals</b> — and the evidence for why, so skipping is a decision, not a hope.",
         "<b>Build provenance</b> — for anything under review, how it was actually produced.",
         "<b>Coverage of the unknowns</b> — what nobody has looked at yet, made visible.",
         "<b>Findings become gate checks</b> — a bug found once is a rule enforced forever."],
   hi="<b>QA stops reviewing everything and starts directing scrutiny.</b> The role shifts from "
      "last line of defence to co-author of the standard — which is the only version of QA "
      "that survives contact with AI-scale output."),

 dict(slug="ops", half="Measure", halfcls="is-measure", n="Lens 04",
   role="Platform &amp; ops", title="Production provenance",
   q="“When this breaks in production, how did the AI build it?”",
   problem="Every other lens stops at <b>shipped</b>. Ops lives with what shipped — at 3am, "
     "on a pager, with zero visibility into how the thing that broke was actually made. Which "
     "model, under which policy, steered by whom, at which attempt, with what reverted along the "
     "way. All of it gone by the time it matters.",
   does="Fieldcraft traces a production incident back to the run that produced the code, and then "
     "closes the loop the other way. Production is the one signal that cannot be argued with, so "
     "what it proves goes back into the standard: an incident becomes a gate check, and the next "
     "run cannot repeat it.",
   dia=dia_ops,
   cap="<b>The loop that closes.</b> Build → ship → run → incident → provenance "
     "→ back into the standard. Production is highlighted because it is the only node in the "
     "chain that cannot be gamed by anyone, human or model.",
   caps=["<b>Incident-to-provenance trace</b> — from an alert to the exact run that wrote the code.",
         "<b>Faster root cause</b> — the attempts, reverts and steering are already recorded.",
         "<b>Deploy-time risk</b> — how this change was built, surfaced before it goes out.",
         "<b>Fragility mapping</b> — which build patterns keep turning into incidents.",
         "<b>Incidents become gate checks</b> — production truth hardens the standard permanently."],
   hi="<b>Production is the one measurement that can't be gamed.</b> A judge can be optimised "
      "against and a review can be rubber-stamped. An outage is an outage — which makes it the "
      "strongest possible input to the gate."),

 dict(slug="access", half="Govern", halfcls="is-govern", n="Lens 05",
   role="Agent access control", title="The least-privilege control plane",
   q="“How does an agent get <em>just</em> enough access — no more, no less?”",
   problem="An agent cannot work without access, and every grant is attack surface. Too much and "
     "it can drop a table, delete a bucket, or read data it was never meant to see. Too little and "
     "someone quietly hands it broad credentials at 6pm “just to unblock it” — which "
     "is how standing access gets created and never revoked.",
   does="Fieldcraft brokers access to <b>any tool engineering already uses</b>: scoped to the "
     "task, time-limited, issued just-in-time, and fully audited. Destructive operations do not "
     "pass — they stop at a human approval gate. The boundaries are configured by the "
     "customer, because only the customer knows where they are.",
   dia=dia_access,
   cap="<b>Broker, not a credential store.</b> Four attributes govern every grant — scope, "
     "time-limit, guardrails, audit — and anything destructive branches out of the automated "
     "path entirely and waits for a person.",
   caps=["<b>Least-privilege per task</b> — the grant is shaped by the work, not by the role.",
         "<b>Ephemeral, just-in-time grants</b> — nothing standing, nothing to leak later.",
         "<b>Destructive-op approval</b> — a human decides, every time, with context.",
         "<b>Environment segregation</b> — what is reachable from dev is not reachable from prod.",
         "<b>Full audit</b> — every grant, every call, every denial, replayable.",
         "<b>Customer-defined boundaries</b> — configured by the people who own the blast radius."],
   hi="<b>This is the hardest and highest-stakes pillar, so it is deliberately last.</b> Getting "
      "it wrong is worse than not having it. It gets built after the isolation and audit "
      "foundations it depends on are proven — not before."),

 dict(slug="brain", half="Cross-cutting", halfcls="is-cross", n="Lens 06",
   role="Team brain", title="Compounding memory",
   q="“Has someone already solved this?”",
   problem="The same problem gets re-solved by people who never knew it was solved. The same trap "
     "gets hit by the fourth person to touch the file. Someone leaves and their hard-won context "
     "leaves with them. Experience evaporates instead of accumulating — and AI makes this "
     "worse, because it produces more work for the same amount of shared memory.",
   does="Every run Fieldcraft records is retrievable. A retrieval layer over that history surfaces "
     "<b>“someone solved this before”</b> at the moment of work, not in a wiki nobody "
     "opens: similar-problem recommendations, memory of traps this repo has sprung before, and "
     "QA→DEV foresight about what tends to break next. Visibility is a first-class control.",
   dia=dia_brain,
   cap="<b>Retrieval, plus a visibility model.</b> What compounds is bounded on purpose: full "
     "within a team, controlled between teams, and a hard boundary across customers. The last one "
     "is not a setting.",
   caps=["<b>Similar-problem recommendation</b> — surfaced while you work, not after.",
         "<b>Cross-repo pattern matching</b> — the same shape of bug, wherever it lives.",
         "<b>Trap memory</b> — what this file, this API, this migration did to the last person.",
         "<b>QA→DEV foresight</b> — what QA keeps finding, fed forward before it is written.",
         "<b>Ramp acceleration</b> — a new joiner starts with the team's accumulated context."],
   hi="<b>Experience compounds instead of evaporating.</b> Every other lens makes one run better. "
      "This one makes every future run start further along — which is the only thing on this "
      "page that gets more valuable purely by waiting."),
]

TPL = '''<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title} — Fieldcraft</title>
<meta name="description" content="{meta}">
<meta property="og:title" content="{title} — Fieldcraft">
<meta property="og:description" content="{meta}">
<meta property="og:type" content="article">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Instrument+Sans:wght@400;500;600&family=Instrument+Serif:ital@0;1&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<link rel="stylesheet" href="../style.css">
<script>document.documentElement.classList.add('js')</script>
<link rel="icon" href="{favicon}">
</head>
<body>

<header class="nav" id="nav">
  <a class="brand" href="../index.html">
    <span class="logo">F</span>
    <span class="brand-t"><b>Fieldcraft</b><i>CONTROL ROOM</i></span>
  </a>
  <nav class="nav-links">
    <a href="../index.html#proof">Proof</a>
    <a href="../index.html#product">Product</a>
    <a href="../index.html#vision">Vision</a>
    <a href="../index.html#status">Status</a>
  </nav>
  <div class="nav-right">
    <a class="icn" href="{gh}" target="_blank" rel="noopener" aria-label="GitHub">{ghsvg}</a>
    <a class="icn" href="{li}" target="_blank" rel="noopener" aria-label="LinkedIn">{lisvg}</a>
    <a class="btn btn-sm" href="{demo}" target="_blank" rel="noopener">Live demo</a>
    <button class="burger" id="burger" aria-label="Menu" aria-expanded="false">
      <span></span><span></span>
    </button>
  </div>
</header>
<div class="mobile-menu" id="mobileMenu">
  <a href="../index.html#proof">Proof</a><a href="../index.html#product">Product</a>
  <a href="../index.html#vision">Vision</a><a href="../index.html#status">Status</a>
  <a href="../index.html#try">Try it</a>
</div>

<main class="lp">
  <div class="hero-glow" aria-hidden="true"></div>
  <div class="wrap">
    <a class="backlink" href="../index.html#vision">← All six lenses</a>
    <span class="lp-half {halfcls}">{half} · {n}</span>
    <p class="lp-role">{role}</p>
    <h1>{title}</h1>
    <p class="lp-q">{q}</p>

    <div class="lp-cols">
      <section class="lp-block">
        <h2 class="lp-sh">The problem</h2>
        <p>{problem}</p>
      </section>
      <section class="lp-block is-do">
        <h2 class="lp-sh">What Fieldcraft does</h2>
        <p>{does}</p>
      </section>
    </div>

    <figure class="dia">
      <div class="dia-head">{title}</div>
      <div class="dia-scroll">
        <svg viewBox="0 0 880 {dh}" role="img" aria-labelledby="dt-{slug}">
          <title id="dt-{slug}">{title} — diagram</title>
          {defs}
          {body}
        </svg>
      </div>
      <figcaption>{cap}</figcaption>
    </figure>

    <section>
      <h2 class="lp-sh" style="margin:44px 0 0">Key capabilities</h2>
      <ul class="caps">
        {caps}
      </ul>
    </section>

    <p class="lp-hi">{hi}</p>

    <div class="lp-cta">
      <p>The measurement this lens reads from is running today. Go see it decide something.</p>
      <a class="btn btn-lg" href="{demo}" target="_blank" rel="noopener">Try the live demo →</a>
    </div>

    <nav class="lp-nav">
      <a href="../index.html#vision">← All six lenses</a>
      <a class="nx" href="{nexthref}">Next · {nextname} →</a>
    </nav>
  </div>
</main>

<footer class="foot">
  <div class="wrap foot-in">
    <div class="foot-l">
      <a class="brand" href="../index.html"><span class="logo">F</span>
        <span class="brand-t"><b>Fieldcraft</b><i>CONTROL ROOM</i></span></a>
      <p>Measure how effectively people work with AI. Govern what agents may touch.</p>
    </div>
    <div class="foot-r">
      <a class="icn" href="{gh}" target="_blank" rel="noopener" aria-label="GitHub">{ghsvg}</a>
      <a class="icn" href="{li}" target="_blank" rel="noopener" aria-label="LinkedIn">{lisvg}</a>
    </div>
  </div>
  <div class="wrap foot-b"><span>Built by Shreyash Kalal</span><span>Measure · Govern</span></div>
</footer>

<script src="../main.js"></script>
</body></html>
'''

os.makedirs(OUT, exist_ok=True)
import re
for i, pg in enumerate(PAGES):
    nxt = PAGES[(i + 1) % len(PAGES)]
    dh, body = pg["dia"]()
    plain = re.sub(r"<[^>]+>", "", pg["q"] + " " + pg["does"])
    html = TPL.format(
        slug=pg["slug"], title=pg["title"], role=pg["role"], q=pg["q"],
        half=pg["half"], halfcls=pg["halfcls"], n=pg["n"],
        problem=pg["problem"], does=pg["does"], cap=pg["cap"], hi=pg["hi"],
        caps="\n        ".join(f"<li>{c}</li>" for c in pg["caps"]),
        dh=dh, defs=DEFS, body=body,
        meta=plain.replace('"', "'")[:180].strip(),
        favicon=FAVICON, gh=GH, li=LI, demo=DEMO, ghsvg=GH_SVG, lisvg=LI_SVG,
        nexthref=f'{nxt["slug"]}.html', nextname=nxt["title"],
    )
    with open(f"{OUT}/{pg['slug']}.html", "w") as f:
        f.write(html)
    print(f"  {OUT}/{pg['slug']}.html  ({len(html)//1024}KB, diagram 880x{dh})")
print("6 lens pages written")
