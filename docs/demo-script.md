# Demo video script — 3 minutes

Submission requires a demo under three minutes. Two live analyses take roughly
a minute of that, so the script is built so narration fills the waiting rather
than cutting away from it — a visible wait is evidence the run is real.

**The one idea to land:** a release can pass every test you wrote and still be
wrong, and ReleaseProof can find that before any user is exposed.

Record the deployed Cloud Run URL. Showing `localhost` invites the question of
whether it is really deployed.

---

## What to run, and what to leave out

Four scenarios exist; only two go in the video. The concurrency and contract
cases are the most conventional — a judge already believes a load test can find
a slow candidate. Spend the time on the two that are hard to dismiss.

| Scenario | In the video | Why |
|---|---|---|
| Undeclared side effect | **Yes** | Nothing shape-based can reach it |
| Rounding centralised | **Yes** | Guarded mode cannot reach it *at all* — the argument for explorer mode |
| Concurrency 4 → 32 | Mention only | Conventional; costs 30s to prove something expected |
| Response schema changed | Mention only | Contract testing already exists |

---

## 0:00–0:18 — The gap

Screen: the dashboard, candidate revision showing **0% traffic**.

> "Every automated deployment gate in production use — canary analysis,
> progressive delivery, telemetry rollback — starts working *after* real users
> reach your new revision. They're good at noticing damage. They can't stop the
> first users absorbing it.
>
> ReleaseProof decides before a single real request arrives. Same probes, sent
> to your stable revision and a candidate holding zero traffic."

---

## 0:18–1:10 — The change that did more than it said

Select **Change did more than it said**. Click Run immediately, then talk over
the wait.

> "The change says: apply eighteen percent GST to the quote total. The candidate
> does that, correctly.
>
> Watch what every conventional check reports."

As results land, point at each:

> "Health: 200. Smoke: 200. Response contract: every field present, every type
> correct, nothing removed. Latency: flat. A canary sees nothing here. A schema
> differ sees nothing. The test suite is green."

Scroll to the reconciliation panel and slow down — this is the first payoff.

> "ReleaseProof extracted five differences deterministically, then asked Gemini
> to account for each one against the diff.
>
> `total` changed — declared, the diff adds the tax rate. `tax_rate` — declared.
> `quote_id` and `issued_at` changed, but those differ between any two calls to
> the *same* revision, so they're noise, not regression.
>
> And `discount_applied` moved from zero to fifteen percent. Nothing in the
> change mentions a discount."

Hover the red row.

> "Blocked — on a fifteen percent revenue leak. And look at the total: 499 to
> 500.50. The declared tax pushed it up, the undeclared discount pulled it back
> down. It lands within two rupees. That's exactly why review misses this."

---

## 1:10–2:25 — The regression no pre-written test can reach

This is the strongest section. Do not rush it.

Select **Rounding centralised**, leave the mode on **Guarded**, click Run.

> "Different change. A team centralises money rounding and deletes the
> per-currency decimal table.
>
> This is guarded mode: Gemini reads the diff and picks experiments from a fixed,
> allowlisted catalog. Everything it can run is something a human wrote in
> advance."

Result lands — **PASS**, clean.

> "It finds nothing. And it's right to. Every catalog experiment sends the
> endpoint's default currency, so it compares identical responses. The gate isn't
> misconfigured — the regression is genuinely unreachable with tests written
> before this change existed."

Now switch the mode toggle to **Explorer** and run the *same* change again.

> "Same change. Same revisions. Same evidence rules. The only difference is that
> Gemini is now allowed to author a probe instead of only choosing one."

While it runs:

> "It reads the diff, works out that rounding is the behaviour that changed, and
> picks the input where old and new logic must disagree — a currency with no
> minor unit."

Result lands. Point at the generated probe.

> "It asked for Japanese yen. Stable rounds to 536 whole yen. The candidate
> returns 536.42 — because it now assumes two decimal places for every currency.
>
> No test covered this. No human wrote it down. The catalog could not have
> reached it."

Then immediately pre-empt the obvious worry:

> "And notice the verdict didn't change. Generated findings are recorded for
> review and cannot block a release. The mode that lets a model invent inputs is
> exactly the mode that must not be able to decide a release."

---

## 2:25–2:50 — The trust boundary

> "One rule holds this together. Gemini plans the investigation, classifies what
> it observes, and authors probes — as *data*, never code. A probe is query
> parameters and operators from a fixed set, interpreted by our runner.
>
> It cannot invent a measurement, set a threshold, reach a different host,
> suppress a failed result, or override the verdict. To call a difference
> declared, it has to quote the diff line that justifies it — no citation, and we
> downgrade it to undeclared and block.
>
> The failure direction is a blocked release, never a shipped regression."

---

## 2:50–3:00 — Close

> "Running on Cloud Run, with Gemini on Vertex AI, against a candidate holding
> zero percent of traffic. Every verdict replayable from its evidence record."

---

## Recording checklist

- [ ] Deployed Cloud Run URL in the address bar, not localhost
- [ ] Opened once in incognito first, to confirm it is publicly reachable
- [ ] Reconciliation badge reads **Gemini classified**, not *Local classifier* —
      if it says local, Vertex is not being reached and the narration is false
- [ ] `MIN_INSTANCES=1 ./scripts/deploy_cloud_run.sh` run shortly before, so cold
      starts do not add dead air
- [ ] Browser zoom 110–125% so field names survive compression
- [ ] No cuts across a verdict landing
- [ ] Under 3:00 — hard requirement
- [ ] Audio levels checked; a silent demo scores as no demo
- [ ] Afterwards: redeploy at `MIN_INSTANCES=0` so the stack costs nothing

---

## Questions a judge is likely to ask

- **"Isn't this Diffy?"** Diffy is a traffic proxy and needs real requests
  flowing. This generates synthetic probes, so it works on a candidate holding
  zero traffic. That is the whole point.
- **"Isn't this canary analysis?"** Kayenta and Flagger compare metrics after
  traffic shifts. By then users have absorbed the regression.
- **"Why does this need an LLM?"** Two jobs that are not expressible as
  thresholds: deciding whether a difference is intended by a change, and choosing
  an input nobody wrote a test for. Everything that *is* expressible as a
  threshold is deliberately kept in code.
- **"What if the model is wrong?"** It cannot set a threshold or issue a verdict.
  An unsupported claim is downgraded to undeclared, which blocks. A generated
  probe's finding is review-only. Being wrong costs a false alarm, never a
  shipped regression.
- **"Is the AI actually doing anything?"** The generated-probe tests fail if the
  runner ignores the model's authored input — verified by mutation. And on the
  deployed stack Gemini selected an experiment the offline fallback never picks.
