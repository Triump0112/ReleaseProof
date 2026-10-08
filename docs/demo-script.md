# Demo video script — 3 minutes

Submission requires a demo under three minutes. This is built to land one idea:
**a release can pass every check you have and still be wrong, and ReleaseProof
catches that before any user is exposed.**

Record the deployed Cloud Run URL, not localhost. Judges are told the prototype
must be deployed; showing `localhost:3000` invites the question of whether it is.

---

## 0:00–0:20 — The gap (no slides, screen already on the dashboard)

> "Every automated deployment gate in production use today — canary analysis,
> progressive delivery, telemetry rollback — starts working *after* real users
> reach your new revision. They are good at noticing damage. They are not able
> to prevent the first users from absorbing it.
>
> ReleaseProof decides before a single real request arrives."

On screen: the dashboard header, candidate revision showing **0% traffic**.

---

## 0:20–1:05 — Scenario 1, establish the mechanism

Select **Concurrency 4 → 32**. Click Run.

> "A config change raises concurrency. Health check passes. Smoke test passes —
> single requests are fast and return 200.
>
> Gemini reads the diff, forms a hypothesis — contention under overlap — and
> selects a bounded load experiment from an allowlisted catalog. The same probes
> go to the stable revision and the zero-traffic candidate."

Let the verdict land. Point at the p95 delta.

> "Candidate p95 regressed over ten times. BLOCK. And note what decided that:
> not Gemini. Gemini chose the experiment. A fixed threshold in code produced
> the verdict."

**Timing note:** the live run takes ~20–30 seconds. Do not cut away; the wait is
evidence it is real. Narrate the loading steps while it runs.

---

## 1:05–2:25 — Scenario 2, the reason this exists

Select **Change did more than it said**. Click Run.

> "This one is different. The change says: apply 18% GST to the quote total.
> The candidate does that correctly.
>
> Watch what every conventional check reports."

Point at each as it resolves:

> "Health: 200. Smoke: 200. Response contract: every field present, every type
> correct, nothing removed. Latency: flat. A canary would see nothing. A schema
> differ would see nothing. The test suite is green."

Now scroll to the reconciliation panel and slow down. This is the moment.

> "ReleaseProof extracted five differences deterministically, then asked Gemini
> to account for each one against the diff.
>
> `total` changed — declared, the diff adds the tax rate. `tax_rate` changed —
> declared. `quote_id` and `issued_at` changed — but those differ between any
> two calls to the *same* revision, so they are noise, not regression.
>
> And `discount_applied` moved from zero to fifteen percent. Nothing in the
> change mentions a discount. No test covers it. No human predicted it."

Hover the red row.

> "BLOCK — on a fifteen percent revenue leak that would have shipped.
>
> And look at the total: 499 to 500.50. The declared tax pushed it up, the
> undeclared discount pulled it back down. It lands within two rupees. That is
> exactly why code review misses this."

---

## 2:25–2:50 — The trust boundary

> "One design rule holds the whole thing together. Gemini plans the
> investigation and classifies what it observes. It cannot invent a measurement,
> set a threshold, suppress a failed result, or override the verdict.
>
> To call a difference 'declared', it has to quote the diff line that justifies
> it. No citation, and the system downgrades it to undeclared and blocks. The
> failure direction is a blocked release, never a shipped regression."

On screen: the evidence ledger entry with the run ID.

---

## 2:50–3:00 — Close

> "Everything you just saw ran on Cloud Run against a candidate holding zero
> percent of traffic, with Gemini on Vertex AI doing the reasoning and
> deterministic policy owning the decision. Every verdict is replayable from its
> evidence record."

---

## Recording checklist

- [ ] Deployed Cloud Run URL in the address bar, not localhost
- [ ] Planner badge reads **Gemini classified**, not *Local classifier* — if it
      says local, Vertex credentials are not reaching the service
- [ ] Browser zoom at 110–125% so field names are legible after compression
- [ ] Both runs genuinely executed on camera; no cuts across the verdict
- [ ] Under 3:00 (hard requirement)
- [ ] Audio levels checked — a muted demo scores as no demo

## Points worth making if a judge asks

- **"Isn't this Diffy?"** Diffy is a traffic proxy; it needs real requests
  flowing. This generates synthetic probes, so it works on a candidate holding
  zero traffic, which is the whole point.
- **"Isn't this canary analysis?"** Kayenta and Flagger compare metrics after
  traffic shifts. By then users have absorbed the regression.
- **"Why does this need an LLM?"** Deciding whether a given difference is
  intended by a change, or is ordinary non-determinism, requires reading the
  change description. That is not expressible as a threshold. Everything that
  *is* expressible as a threshold is deliberately kept in code.
