import { useEffect, useMemo, useState } from 'react';

const scenarios = {
  concurrency: {
    id: 'concurrency',
    eyebrow: 'Infrastructure change',
    title: 'Concurrency 4 → 32',
    summary: 'Candidate raises per-instance concurrency to improve throughput.',
    file: 'service.yaml',
    additions: '+1',
    removals: '−1',
    stable: { name: 'checkout-api-00041', tag: 'stable', commit: 'a92f81c', traffic: '100%' },
    candidate: { name: 'checkout-api-00042', tag: 'candidate', commit: 'd104be7', traffic: '0%' },
    hypothesis:
      'Higher concurrency may create CPU contention and degrade tail latency before the service reports unhealthy.',
    experiment: 'Paired bounded-concurrency test',
    experimentKey: 'load_test',
    apiPayload: {
      service_name: 'checkout-api',
      summary: 'Increase Cloud Run concurrency from 4 to 32',
      diff: '- containerConcurrency: 4\n+ containerConcurrency: 32',
      scenario_id: 'concurrency-regression',
      request_path: '/checkout',
    },
    budget: '600 requests · 60 seconds',
    threshold: 'Block if candidate p95 regresses > 30% or errors exceed 2%',
    smokeMiss: 'The smoke test sends one request at a time. Contention only appears when requests overlap.',
    verdict: 'BLOCK',
    confidence: 96,
    metrics: [
      { label: 'p95 latency', stable: '182 ms', candidate: '587 ms', delta: '+223%', bad: true },
      { label: 'Error rate', stable: '0.2%', candidate: '3.8%', delta: '+3.6 pp', bad: true },
      { label: 'Throughput', stable: '47 rps', candidate: '53 rps', delta: '+13%', bad: false },
    ],
    evidence: [
      { time: '00:00', title: 'Baseline smoke passed', detail: 'Stable and candidate returned HTTP 200.', tone: 'neutral' },
      { time: '00:08', title: 'Gemini formed a risk hypothesis', detail: 'Concurrency change mapped to contention and tail-latency risk.', tone: 'ai' },
      { time: '00:14', title: 'Paired load experiment started', detail: 'Identical 50-client workload sent to both revisions.', tone: 'neutral' },
      { time: '00:48', title: 'Regression threshold crossed', detail: 'Candidate p95 exceeded the 30% policy by 193 points.', tone: 'danger' },
      { time: '00:51', title: 'Release blocked', detail: 'Verdict derived by policy engine; Gemini cannot override it.', tone: 'danger' },
    ],
  },
  contract: {
    id: 'contract',
    eyebrow: 'Application change',
    title: 'Response schema changed',
    summary: 'Candidate renames total to amount and serializes it as text.',
    file: 'src/checkout.js',
    additions: '+2',
    removals: '−2',
    stable: { name: 'checkout-api-00041', tag: 'stable', commit: 'a92f81c', traffic: '100%' },
    candidate: { name: 'checkout-api-00043', tag: 'candidate', commit: 'e73ca10', traffic: '0%' },
    hypothesis:
      'Existing consumers may fail because a required response field was renamed and its type changed.',
    experiment: 'API contract compatibility',
    experimentKey: 'contract_test',
    apiPayload: {
      service_name: 'pricing-api',
      summary: 'Rename total to amount in the checkout response',
      diff: '- "total": 499\n+ "amount": "499"',
      scenario_id: 'api-contract-break',
      request_path: '/price',
      expected_contract: { required_fields: { total: 'number', currency: 'string' } },
    },
    budget: '12 contract cases · 30 seconds',
    threshold: 'Block on any breaking change to the published response contract',
    smokeMiss: 'The smoke test checks only the HTTP status. It never validates response field names or types.',
    verdict: 'BLOCK',
    confidence: 99,
    metrics: [
      { label: 'HTTP status', stable: '200', candidate: '200', delta: 'Same', bad: false },
      { label: 'Contract checks', stable: '12 / 12', candidate: '10 / 12', delta: '−2', bad: true },
      { label: 'Breaking changes', stable: '0', candidate: '2', delta: '+2', bad: true },
    ],
    evidence: [
      { time: '00:00', title: 'Baseline smoke passed', detail: 'Stable and candidate returned HTTP 200.', tone: 'neutral' },
      { time: '00:05', title: 'Gemini inspected the diff', detail: 'Detected a renamed field and number-to-string type change.', tone: 'ai' },
      { time: '00:09', title: 'Contract experiment started', detail: 'Published schema replayed against both revisions.', tone: 'neutral' },
      { time: '00:16', title: 'Two incompatibilities found', detail: 'Required field “total” missing; “amount” returned as string.', tone: 'danger' },
      { time: '00:18', title: 'Release blocked', detail: 'Breaking-change policy produced a deterministic verdict.', tone: 'danger' },
    ],
  },
  sideeffect: {
    id: 'sideeffect',
    eyebrow: 'Undeclared behaviour',
    title: 'Change did more than it said',
    summary: 'Candidate applies the declared tax — and an undeclared 15% discount.',
    file: 'src/pricing.py',
    additions: '+2',
    removals: '−1',
    stable: { name: 'pricing-api-00071', tag: 'stable', commit: 'b41d7e2', traffic: '100%' },
    candidate: { name: 'pricing-api-00072', tag: 'candidate', commit: 'f920ac5', traffic: '0%' },
    hypothesis:
      'The response keeps its exact shape, so the risk is not malformedness — it is behaviour the change never declared.',
    experiment: 'Intent reconciliation on the paired response',
    experimentKey: 'adjudication',
    apiPayload: {
      service_name: 'pricing-api',
      summary: 'Apply 18% GST to the quote total',
      diff: '-    total = subtotal\n+    tax_rate = 0.18\n+    total = subtotal * (1 + tax_rate)',
      scenario_id: 'undeclared-side-effect',
      request_path: '/api/v1/quote',
    },
    budget: '6 paired requests · 20 seconds',
    threshold: 'Block on any observed behaviour the change does not account for',
    smokeMiss:
      'Every field, type and status code is unchanged and latency is flat, so availability, smoke, contract and latency checks all pass.',
    verdict: 'BLOCK',
    confidence: 94,
    metrics: [
      { label: 'Response shape', stable: '6 fields', candidate: '6 fields', delta: 'Identical', bad: false },
      { label: 'p95 latency', stable: '70 ms', candidate: '71 ms', delta: '+1%', bad: false },
      { label: 'Unexplained deltas', stable: '—', candidate: '1', delta: 'discount_applied', bad: true },
    ],
    evidence: [
      { time: '00:00', title: 'Baseline smoke passed', detail: 'Both revisions returned HTTP 200 with identical field names and types.', tone: 'neutral' },
      { time: '00:04', title: 'Deterministic delta extraction', detail: 'Five field-level differences measured between the paired responses.', tone: 'neutral' },
      { time: '00:07', title: 'Gemini reconciled intent', detail: 'total and tax_rate traced to the diff; quote_id and issued_at ruled non-deterministic.', tone: 'ai' },
      { time: '00:11', title: 'Undeclared behaviour found', detail: 'discount_applied moved 0.0 → 0.15 with no supporting diff evidence.', tone: 'danger' },
      { time: '00:13', title: 'Release blocked', detail: 'Fixed policy: unexplained behavioural change blocks. Gemini classified; it did not decide.', tone: 'danger' },
    ],
  },
  currency: {
    id: 'currency',
    eyebrow: 'Only a generated input finds it',
    title: 'Rounding centralised',
    summary: 'Candidate rounds every currency to two decimals. Correct for INR. Wrong for JPY.',
    file: 'src/money.py',
    additions: '+2',
    removals: '−2',
    stable: { name: 'pricing-api-00088', tag: 'stable', commit: 'c7e1a40', traffic: '100%' },
    candidate: { name: 'pricing-api-00089', tag: 'candidate', commit: '31bd9f6', traffic: '0%' },
    hypothesis:
      'Every catalog experiment sends the default currency, so the fixed suite compares INR against INR and sees nothing.',
    experiment: 'AI-authored zero-decimal currency probe',
    experimentKey: 'ai_explorer',
    apiPayload: {
      service_name: 'pricing-api',
      summary: 'Centralise money rounding and drop the per-currency decimal table',
      diff:
        '-    exponent = CURRENCY_DECIMALS[code]\n-    total = round(charged, exponent)\n+    # one rounding helper for every currency\n+    total = round(charged, 2)',
      scenario_id: 'currency-rounding',
      request_path: '/api/v1/quote',
    },
    budget: '6 generated requests · 20 seconds',
    threshold: 'Generated findings are recorded for review and never set the verdict',
    smokeMiss:
      'Smoke, contract and load all send the default currency, and the edge and payload probes vary their own reserved parameters. No fixed experiment ever asks for a different currency.',
    verdict: 'PASS',
    confidence: 88,
    metrics: [
      { label: 'Guarded mode', stable: '3 experiments', candidate: 'all passed', delta: 'No finding', bad: false },
      { label: 'Default currency', stable: '536.42', candidate: '536.42', delta: 'Identical', bad: false },
      { label: 'Generated JPY probe', stable: '536', candidate: '536.42', delta: 'Differs', bad: true },
    ],
    evidence: [
      { time: '00:00', title: 'Guarded mode found nothing', detail: 'Health, smoke and contract all compared identical responses.', tone: 'neutral' },
      { time: '00:05', title: 'Gemini read the rounding change', detail: 'Identified currency as the input dimension the diff actually affects.', tone: 'ai' },
      { time: '00:09', title: 'Probe authored as data, not code', detail: 'currency=JPY with a compare-paths assertion on total, inside the fixed DSL.', tone: 'ai' },
      { time: '00:14', title: 'Difference surfaced for review', detail: 'Stable rounded to 536 whole yen; candidate returned 536.42.', tone: 'danger' },
      { time: '00:16', title: 'Verdict unchanged', detail: 'Generated findings are review-only and cannot block a release.', tone: 'neutral' },
    ],
  },
};

// Revision URLs come from the API at runtime rather than from the bundle, so a
// single UI image works in Compose and on Cloud Run. When the API reports no
// configured pair, the prepared fixtures are used instead.
function analysisPayload(scenario, mode, liveTargets) {
  const targets = liveTargets?.[scenario.id];
  if (!targets) return { ...scenario.apiPayload, analysis_mode: mode };
  return {
    ...scenario.apiPayload,
    scenario_id: undefined,
    request_path: '/api/v1/quote',
    stable_url: targets.stable,
    candidate_url: targets.candidate,
    analysis_mode: mode,
  };
}

const Icon = ({ name, size = 18 }) => {
  const common = { width: size, height: size, viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor', strokeWidth: 1.8, strokeLinecap: 'round', strokeLinejoin: 'round', 'aria-hidden': true };
  const paths = {
    shield: <><path d="M12 3l7 3v5c0 4.7-2.8 8-7 10-4.2-2-7-5.3-7-10V6l7-3Z"/><path d="m9 12 2 2 4-4"/></>,
    branch: <><circle cx="6" cy="5" r="2"/><circle cx="18" cy="6" r="2"/><circle cx="6" cy="19" r="2"/><path d="M6 7v10M8 8c5 0 4-2 8-2"/></>,
    spark: <><path d="m12 3 1.35 4.15L17.5 8.5l-4.15 1.35L12 14l-1.35-4.15L6.5 8.5l4.15-1.35L12 3Z"/><path d="m18.5 14 .7 2.3 2.3.7-2.3.7-.7 2.3-.7-2.3-2.3-.7 2.3-.7.7-2.3Z"/></>,
    run: <><path d="m9 7 8 5-8 5V7Z"/></>,
    check: <path d="m5 12 4 4L19 6"/>,
    x: <><path d="m6 6 12 12M18 6 6 18"/></>,
    clock: <><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></>,
    info: <><circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 8h.01"/></>,
    chevron: <path d="m9 18 6-6-6-6"/>,
    cloud: <path d="M7 18h10a4 4 0 0 0 .6-7.96A6 6 0 0 0 6.2 8.4 4.8 4.8 0 0 0 7 18Z"/>,
  };
  return <svg {...common}>{paths[name]}</svg>;
};

function RevisionCard({ type, revision }) {
  const candidate = type === 'candidate';
  return (
    <article className={`revision-card ${candidate ? 'candidate' : ''}`}>
      <div className="revision-head">
        <span className={`status-dot ${candidate ? 'amber' : 'green'}`} />
        <span className="revision-type">{type}</span>
        <span className="traffic">{revision.traffic} traffic</span>
      </div>
      <strong>{revision.name}</strong>
      <div className="revision-meta"><code>{revision.commit}</code><span>•</span><span>{revision.tag}</span></div>
    </article>
  );
}

function ScenarioPicker({ selected, onSelect, disabled }) {
  return (
    <div className="scenario-grid" role="radiogroup" aria-label="Demo change">
      {Object.values(scenarios).map((item) => {
        const active = selected === item.id;
        return (
          <button
            className={`scenario-card ${active ? 'selected' : ''}`}
            key={item.id}
            role="radio"
            aria-checked={active}
            onClick={() => onSelect(item.id)}
            disabled={disabled}
          >
            <span className="radio-mark">{active && <span />}</span>
            <span className="scenario-copy">
              <small>{item.eyebrow}</small>
              <strong>{item.title}</strong>
              <span>{item.summary}</span>
              <code>{item.file} <em>{item.additions}</em> <del>{item.removals}</del></code>
            </span>
          </button>
        );
      })}
    </div>
  );
}

function ModeSelector({ mode, onChange, disabled }) {
  return (
    <section className="mode-selector" aria-labelledby="mode-heading">
      <div className="mode-heading">
        <span className="step-label">02 / CHOOSE INVESTIGATION MODE</span>
        <h2 id="mode-heading">How much freedom should Gemini have?</h2>
      </div>
      <div className="mode-grid" role="radiogroup" aria-label="Investigation mode">
        <button className={`mode-card ${mode === 'guarded' ? 'selected' : ''}`} role="radio" aria-checked={mode === 'guarded'} onClick={() => onChange('guarded')} disabled={disabled}>
          <span className="mode-icon"><Icon name="shield"/></span>
          <span><small>DEFAULT · RELEASE-BLOCKING</small><strong>Guarded Gate</strong><em>Gemini selects only approved experiments. Fixed code executes them and owns the verdict.</em></span>
        </button>
        <button className={`mode-card explorer ${mode === 'explorer' ? 'selected' : ''}`} role="radio" aria-checked={mode === 'explorer'} onClick={() => onChange('explorer')} disabled={disabled}>
          <span className="mode-icon"><Icon name="spark"/></span>
          <span><small>OPTIONAL · REVIEW-ONLY</small><strong>AI Explorer</strong><em>Gemini also authors constrained GET/query probe specs. Findings require human review.</em></span>
        </button>
      </div>
    </section>
  );
}

function PlanPanel({ scenario, mode }) {
  const explorer = mode === 'explorer';
  return (
    <section className="panel plan-panel">
      <div className="section-kicker"><Icon name="spark" /><span>Gemini risk analysis</span><span className="ai-pill">{explorer ? 'AI authored + selected' : 'AI selected'}</span></div>
      <h2>{explorer ? 'Guarded evidence plus a generated probe' : 'A bounded plan built for this change'}</h2>
      <div className="plan-grid">
        <div className="plan-block wide">
          <span className="label">Risk hypothesis</span>
          <p>{scenario.hypothesis}</p>
        </div>
        <div className="plan-block">
          <span className="label">{explorer ? 'Guarded experiment' : 'Selected experiment'}</span>
          <strong>{scenario.experiment}</strong>
          <code>{scenario.experimentKey}</code>
        </div>
        <div className="plan-block">
          <span className="label">Execution budget</span>
          <strong>{scenario.budget}</strong>
          <span>{explorer ? 'Guarded gate + review-only probe' : 'Bounded and pre-authorized'}</span>
        </div>
        <div className="plan-block wide policy">
          <span className="label">{explorer ? 'Decision boundary' : 'Deterministic policy'}</span>
          <p>{explorer ? 'Guarded evidence may block. Generated Explorer findings are visible and auditable, but require human review.' : scenario.threshold}</p>
        </div>
        {explorer && <div className="plan-block wide explorer-boundary"><span className="label">Explorer sandbox contract</span><p>GET only · supplied revision endpoint only · query parameters only · fixed assertion operators · no source code, shell, credentials or arbitrary network targets</p></div>}
      </div>
    </section>
  );
}

function LoadingState({ scenario, mode }) {
  const steps = ['Inspecting deployment diff', `Planning ${scenario.experiment.toLowerCase()}`, mode === 'explorer' ? 'Authoring constrained probe spec' : 'Running paired experiment', 'Evaluating fixed policy'];
  return (
    <section className="panel loading-panel" aria-live="polite">
      <div className="orb"><span /><span /><span /></div>
      <div>
        <span className="label">Release verification in progress</span>
        <h2>Looking for evidence, not reassurance.</h2>
        <div className="loading-steps">
          {steps.map((step, i) => <span key={step} style={{ '--delay': `${i * .5}s` }}><i />{step}</span>)}
        </div>
      </div>
    </section>
  );
}

function ResultPanel({ scenario, result, isDemo, mode }) {
  const verdict = result?.verdict || scenario.verdict;
  const metrics = result?.metrics || scenario.metrics;
  const evidence = result?.evidence || scenario.evidence;
  const adjudication = result?.adjudication;
  const explorerSpecs = result?.explorerExperiments || [];
  const reviewFindings = result?.reviewFindings || [];
  const blocked = verdict === 'BLOCK';
  const inconclusive = verdict === 'INCONCLUSIVE';
  const verdictMessage = blocked
    ? 'Candidate should not receive production traffic.'
    : inconclusive
      ? 'The available evidence is insufficient for a safe release decision.'
      : 'Candidate meets the configured release policy.';
  return (
    <>
      {isDemo && <div className="demo-notice"><Icon name="info" size={16}/><span>Backend unavailable — showing deterministic demo evidence for this scenario.</span></div>}
      <section className={`verdict-card ${verdict.toLowerCase()}`} aria-live="polite">
        <div className="verdict-icon"><Icon name={blocked ? 'x' : inconclusive ? 'info' : 'check'} size={28}/></div>
        <div className="verdict-copy">
          <span className="label">Release decision</span>
          <h2>{verdict}</h2>
          <p>{verdictMessage}</p>
        </div>
        <div className="confidence"><span>{result?.evidenceCount || 3}</span><small>experiments recorded</small></div>
      </section>

      {mode === 'explorer' && (
        <section className="panel explorer-result">
          <div className="section-heading">
            <div><span className="label">AI Explorer · review-only</span><h2>Generated probe, contained execution.</h2></div>
            <span className="ai-pill"><Icon name="spark" size={14}/>Human review boundary</span>
          </div>
          {explorerSpecs.length > 0 ? explorerSpecs.map((spec) => (
            <div className="explorer-spec" key={spec.name}>
              <div><strong>{spec.name}</strong><p>{spec.hypothesis}</p></div>
              <code>GET {scenario.apiPayload.request_path}?{new URLSearchParams(spec.query_parameters || {}).toString()}</code>
              <div className="assertion-list">{(spec.assertions || []).map((assertion) => <span key={assertion}>{assertion.replaceAll('_', ' ')}</span>)}</div>
            </div>
          )) : <p className="explorer-placeholder">The live API will display Gemini’s generated declarative spec here. The fallback demo never executes model-authored source code.</p>}
          <div className={`review-status ${reviewFindings.length ? 'finding' : ''}`}>
            <Icon name={reviewFindings.length ? 'info' : 'check'} size={17}/>
            <span>{reviewFindings.length ? `${reviewFindings.length} exploratory finding(s) need human review. They did not alter the guarded verdict.` : 'No review finding was raised by the generated probe.'}</span>
          </div>
        </section>
      )}

      <section className="panel metrics-panel">
        <div className="section-heading">
          <div><span className="label">Paired comparison</span><h2>Same experiment. Different outcome.</h2></div>
          <span className="evidence-id">Evidence {result?.runId ? result.runId.slice(0, 8) : `RP-${scenario.id === 'concurrency' ? '1042' : '1043'}`}</span>
        </div>
        <div className="metrics-head"><span>Signal</span><span>Stable</span><span>Candidate</span><span>Change</span></div>
        {metrics.map((metric) => (
          <div className="metric-row" key={metric.label}>
            <strong>{metric.label}</strong>
            <span>{metric.stable}</span>
            <span>{metric.candidate}</span>
            <span className={metric.bad ? 'bad-delta' : 'good-delta'}>{metric.delta}</span>
          </div>
        ))}
      </section>

      {adjudication && adjudication.deltas?.length > 0 && (
        <section className="panel adjudication-panel">
          <div className="section-heading">
            <div>
              <span className="label">Intent reconciliation</span>
              <h2>Did the change do only what it said?</h2>
            </div>
            <span className={`ai-pill ${adjudication.classifier === 'vertex_gemini' ? '' : 'muted'}`}>
              <Icon name="spark" size={14}/>
              {adjudication.classifier === 'vertex_gemini' ? 'Gemini classified' : 'Local classifier'}
            </span>
          </div>
          <p className="adjudication-summary">{adjudication.summary}</p>
          <div className="delta-head"><span>Field</span><span>Stable</span><span>Candidate</span><span>Assessment</span></div>
          {adjudication.deltas.map((delta) => {
            const call = adjudication.classifications?.find((item) => item.path === delta.path);
            const label = call?.label || 'unexplained';
            return (
              <div className={`delta-row ${label}`} key={delta.path}>
                <strong>{delta.path}</strong>
                <span className="delta-value">{delta.stable_value ?? '—'}</span>
                <span className="delta-value">{delta.candidate_value ?? '—'}</span>
                <div className="delta-call">
                  <span className={`delta-tag ${label}`}>
                    {label === 'explained' ? 'Declared' : label === 'benign_noise' ? 'Non-deterministic' : 'Undeclared'}
                  </span>
                  <p>{call?.rationale}</p>
                  {call?.diff_evidence && <code>{call.diff_evidence}</code>}
                </div>
              </div>
            );
          })}
          <div className="adjudication-foot">
            <Icon name="shield" size={15}/>
            <span>Gemini labels each difference and must cite the diff. The block/pass rule is fixed in code.</span>
          </div>
        </section>
      )}

      <div className="result-columns">
        <section className="panel timeline-panel">
          <div className="section-heading compact"><div><span className="label">Replayable evidence</span><h2>Decision timeline</h2></div></div>
          <ol className="timeline">
            {evidence.map((item) => (
              <li className={item.tone} key={item.time + item.title}>
                <time>{item.time}</time>
                <div><strong>{item.title}</strong><p>{item.detail}</p></div>
              </li>
            ))}
          </ol>
        </section>
        <section className="panel missed-panel">
          <div className="missed-icon"><Icon name="info" size={22}/></div>
          <span className="label">Why the fixed smoke test missed it</span>
          <h2>Healthy does not mean safe.</h2>
          <p>{scenario.smokeMiss}</p>
          <div className="smoke-result"><Icon name="check"/><span>GET /health</span><strong>200 OK</strong></div>
          <div className="arrow-note"><Icon name="chevron" size={15}/><span>Adaptive testing exposed the hidden risk.</span></div>
        </section>
      </div>
    </>
  );
}

function normalizeApiResult(payload) {
  if (!payload || typeof payload !== 'object') return null;
  const body = payload.result && typeof payload.result === 'object' ? payload.result : payload;
  if (body.ledger && typeof body.ledger === 'object') {
    const ledger = body.ledger;
    const evidence = Array.isArray(ledger.evidence) ? ledger.evidence : [];
    // Surface whatever actually decided the verdict. Without this, a run blocked
    // by the smoke baseline would display the passing adaptive experiment's
    // metrics next to a BLOCK banner.
    const selected = evidence.find((item) => item.blocking && item.passed === false)
      || [...evidence].reverse().find((item) => !['health_check', 'api_smoke'].includes(item.experiment_id))
      || evidence.at(-1);
    const adjudication = evidence.map((item) => item.adjudication).find(Boolean) || null;
    const stableLatency = selected?.stable?.p95_latency_ms;
    const candidateLatency = selected?.candidate?.p95_latency_ms;
    const stableErrors = selected?.stable?.error_rate;
    const candidateErrors = selected?.candidate?.error_rate;
    const latencyDelta = stableLatency > 0 && candidateLatency != null
      ? `${candidateLatency >= stableLatency ? '+' : ''}${Math.round(((candidateLatency - stableLatency) / stableLatency) * 100)}%`
      : 'n/a';
    const errorDelta = stableErrors != null && candidateErrors != null
      ? `${candidateErrors >= stableErrors ? '+' : ''}${((candidateErrors - stableErrors) * 100).toFixed(1)} pp`
      : 'n/a';
    return {
      verdict: ledger.verdict,
      runId: body.id || ledger.run_id,
      evidenceCount: evidence.length,
      adjudication,
      analysisMode: ledger.plan?.analysis_mode || 'guarded',
      explorerExperiments: ledger.plan?.exploratory_experiments || [],
      reviewFindings: ledger.review_findings || [],
      metrics: selected ? [
        {
          label: 'p95 latency',
          stable: stableLatency == null ? 'n/a' : `${Math.round(stableLatency)} ms`,
          candidate: candidateLatency == null ? 'n/a' : `${Math.round(candidateLatency)} ms`,
          delta: latencyDelta,
          bad: selected.passed === false && candidateLatency > stableLatency,
        },
        {
          label: 'Error rate',
          stable: stableErrors == null ? 'n/a' : `${(stableErrors * 100).toFixed(1)}%`,
          candidate: candidateErrors == null ? 'n/a' : `${(candidateErrors * 100).toFixed(1)}%`,
          delta: errorDelta,
          bad: selected.passed === false && candidateErrors > stableErrors,
        },
        {
          label: 'Policy result',
          stable: selected.stable?.success ? 'Valid' : 'Invalid',
          candidate: selected.passed === true ? 'Pass' : selected.passed === false ? 'Fail' : 'Unknown',
          delta: selected.passed === true ? 'Within bounds' : selected.passed === false ? 'Threshold crossed' : 'Inconclusive',
          bad: selected.passed === false,
        },
      ] : undefined,
      evidence: [
        {
          time: 'PLAN',
          title: ledger.plan?.risk_summary || 'Change-specific plan created',
          detail: `${ledger.plan?.planner === 'vertex_gemini' ? 'Gemini' : 'Local fallback'} selected ${ledger.plan?.adaptive_experiments?.length || 0} adaptive experiment(s).`,
          tone: 'ai',
        },
        ...evidence.map((item, index) => ({
          time: String(index + 1).padStart(2, '0'),
          title: item.title,
          detail: item.explanation,
          tone: item.passed === false ? 'danger' : item.passed === true ? 'neutral' : 'ai',
        })),
      ],
    };
  }
  return body;
}

// The backend's own execution budget is 90s; allow for that plus Cloud Run
// cold start rather than racing it. Aborting early would silently downgrade a
// real paired run to the prepared fixtures.
const ANALYSIS_TIMEOUT_MS = 120000;

export default function App() {
  const [scenarioId, setScenarioId] = useState('concurrency');
  const [phase, setPhase] = useState('ready');
  const [result, setResult] = useState(null);
  const [isDemo, setIsDemo] = useState(false);
  const [error, setError] = useState('');
  const [mode, setMode] = useState('guarded');
  const [liveTargets, setLiveTargets] = useState(null);
  const scenario = useMemo(() => scenarios[scenarioId], [scenarioId]);

  useEffect(() => {
    let cancelled = false;
    fetch('/api/demo-targets')
      .then((response) => (response.ok ? response.json() : null))
      .then((config) => { if (!cancelled && config?.live) setLiveTargets(config.targets); })
      .catch(() => { /* No configured revisions: prepared fixtures are used. */ });
    return () => { cancelled = true; };
  }, []);

  const selectScenario = (id) => {
    setScenarioId(id);
    setPhase('ready');
    setResult(null);
    setIsDemo(false);
    setError('');
  };

  const runAnalysis = async () => {
    setPhase('loading');
    setResult(null);
    setError('');
    setIsDemo(false);
    const started = Date.now();
    try {
      const controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(), ANALYSIS_TIMEOUT_MS);
      const response = await fetch('/api/analyze', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(analysisPayload(scenario, mode, liveTargets)),
        signal: controller.signal,
      });
      clearTimeout(timeout);
      if (!response.ok) throw new Error(`Analysis service returned ${response.status}`);
      const data = normalizeApiResult(await response.json());
      const remaining = Math.max(0, 2300 - (Date.now() - started));
      await new Promise((resolve) => setTimeout(resolve, remaining));
      setResult(data);
      setPhase('result');
    } catch (err) {
      const remaining = Math.max(0, 2300 - (Date.now() - started));
      await new Promise((resolve) => setTimeout(resolve, remaining));
      setIsDemo(true);
      setError(err instanceof Error ? err.message : 'Analysis service unavailable');
      setPhase('result');
    }
  };

  return (
    <div className="app-shell">
      <header className="topbar">
        <a className="brand" href="#top" aria-label="ReleaseProof home"><span className="brand-mark"><Icon name="shield" size={21}/></span><span>Release<span>Proof</span></span></a>
        <div className="top-meta"><span className="cloud-pill"><Icon name="cloud" size={16}/>Google Cloud</span><span className="environment"><i/>DEMO ENVIRONMENT</span></div>
      </header>

      <main id="top">
        <section className="hero">
          <div className="hero-kicker"><span>PRE-TRAFFIC RELEASE VERIFICATION</span></div>
          <h1>Ship evidence.<br/><em>Not assumptions.</em></h1>
          <p>Gemini plans the right experiment for each change. ReleaseProof compares your stable and candidate revisions before users see the risk.</p>
          <div className="hero-proof"><span><Icon name="check"/>Zero production traffic</span><span><Icon name="check"/>Bounded experiments</span><span><Icon name="check"/>Deterministic verdicts</span></div>
        </section>

        <section className="workspace" aria-label="Release analysis workspace">
          <div className="workspace-head">
            <div><span className="step-label">01 / SELECT A CHANGE</span><h2>What are we shipping?</h2><p>Choose a prepared release scenario for this prototype.</p></div>
            {phase === 'result' && <button className="text-button" onClick={() => setPhase('ready')}>Clear result</button>}
          </div>
          <ScenarioPicker selected={scenarioId} onSelect={selectScenario} disabled={phase === 'loading'} />

          <ModeSelector mode={mode} onChange={(nextMode) => { setMode(nextMode); setPhase('ready'); setResult(null); setIsDemo(false); setError(''); }} disabled={phase === 'loading'} />

          <div className="comparison-wrap">
            <div className="comparison-line"><span>Paired Cloud Run revisions</span></div>
            <div className="revision-grid">
              <RevisionCard type="stable" revision={scenario.stable}/>
              <div className="versus">VS</div>
              <RevisionCard type="candidate" revision={scenario.candidate}/>
            </div>
          </div>

          <PlanPanel scenario={scenario} mode={mode}/>

          <div className="run-bar">
            <div><Icon name="branch"/><span><strong>Ready to verify</strong><small>Both revisions are reachable; candidate receives 0% traffic.</small></span></div>
            <button className="run-button" onClick={runAnalysis} disabled={phase === 'loading'}>
              {phase === 'loading' ? <><span className="button-spinner"/>Analyzing…</> : <><Icon name="run"/>Run {mode === 'explorer' ? 'with AI Explorer' : 'guarded proof'}</>}
            </button>
          </div>

          {phase === 'loading' && <LoadingState scenario={scenario} mode={mode}/>}
          {phase === 'result' && <ResultPanel scenario={scenario} result={result} isDemo={isDemo} error={error} mode={mode}/>}
        </section>
      </main>

      <footer><div className="brand mini"><span className="brand-mark"><Icon name="shield" size={17}/></span><span>ReleaseProof</span></div><p>AI plans the investigation. Evidence makes the decision.</p><span>Prototype · 2026</span></footer>
    </div>
  );
}
