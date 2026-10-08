import { useMemo, useState } from 'react';

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
};

const liveTargetsEnabled = import.meta.env.VITE_USE_LIVE_TARGETS === 'true';

// Compose uses service hostnames; Cloud Run injects public revision URLs at build time.
const TARGET_URLS = {
  stableLatency: import.meta.env.VITE_STABLE_LATENCY_URL || 'http://stable-latency:8080',
  candidateLatency: import.meta.env.VITE_CANDIDATE_LATENCY_URL || 'http://candidate-latency:8080',
  stableContract: import.meta.env.VITE_STABLE_CONTRACT_URL || 'http://stable-contract:8080',
  candidateContract: import.meta.env.VITE_CANDIDATE_CONTRACT_URL || 'http://candidate-contract:8080',
};

function analysisPayload(scenario) {
  if (!liveTargetsEnabled) return scenario.apiPayload;
  const contract = scenario.id === 'contract';
  return {
    ...scenario.apiPayload,
    scenario_id: undefined,
    request_path: '/api/v1/quote',
    stable_url: contract ? TARGET_URLS.stableContract : TARGET_URLS.stableLatency,
    candidate_url: contract ? TARGET_URLS.candidateContract : TARGET_URLS.candidateLatency,
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

function PlanPanel({ scenario }) {
  return (
    <section className="panel plan-panel">
      <div className="section-kicker"><Icon name="spark" /><span>Gemini risk analysis</span><span className="ai-pill">AI planned</span></div>
      <h2>A test plan built for this change</h2>
      <div className="plan-grid">
        <div className="plan-block wide">
          <span className="label">Risk hypothesis</span>
          <p>{scenario.hypothesis}</p>
        </div>
        <div className="plan-block">
          <span className="label">Selected experiment</span>
          <strong>{scenario.experiment}</strong>
          <code>{scenario.experimentKey}</code>
        </div>
        <div className="plan-block">
          <span className="label">Execution budget</span>
          <strong>{scenario.budget}</strong>
          <span>Bounded and pre-authorized</span>
        </div>
        <div className="plan-block wide policy">
          <span className="label">Deterministic policy</span>
          <p>{scenario.threshold}</p>
        </div>
      </div>
    </section>
  );
}

function LoadingState({ scenario }) {
  const steps = ['Inspecting deployment diff', `Planning ${scenario.experiment.toLowerCase()}`, 'Running paired experiment', 'Evaluating policy'];
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

function ResultPanel({ scenario, result, isDemo }) {
  const verdict = result?.verdict || scenario.verdict;
  const metrics = result?.metrics || scenario.metrics;
  const evidence = result?.evidence || scenario.evidence;
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
    const selected = [...evidence].reverse().find((item) => !['health_check', 'api_smoke'].includes(item.experiment_id)) || evidence.at(-1);
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

export default function App() {
  const [scenarioId, setScenarioId] = useState('concurrency');
  const [phase, setPhase] = useState('ready');
  const [result, setResult] = useState(null);
  const [isDemo, setIsDemo] = useState(false);
  const [error, setError] = useState('');
  const scenario = useMemo(() => scenarios[scenarioId], [scenarioId]);

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
      const timeout = setTimeout(() => controller.abort(), 6000);
      const response = await fetch('/api/analyze', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(analysisPayload(scenario)),
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

          <div className="comparison-wrap">
            <div className="comparison-line"><span>Paired Cloud Run revisions</span></div>
            <div className="revision-grid">
              <RevisionCard type="stable" revision={scenario.stable}/>
              <div className="versus">VS</div>
              <RevisionCard type="candidate" revision={scenario.candidate}/>
            </div>
          </div>

          <PlanPanel scenario={scenario}/>

          <div className="run-bar">
            <div><Icon name="branch"/><span><strong>Ready to verify</strong><small>Both revisions are reachable; candidate receives 0% traffic.</small></span></div>
            <button className="run-button" onClick={runAnalysis} disabled={phase === 'loading'}>
              {phase === 'loading' ? <><span className="button-spinner"/>Analyzing…</> : <><Icon name="run"/>Run release proof</>}
            </button>
          </div>

          {phase === 'loading' && <LoadingState scenario={scenario}/>} 
          {phase === 'result' && <ResultPanel scenario={scenario} result={result} isDemo={isDemo} error={error}/>} 
        </section>
      </main>

      <footer><div className="brand mini"><span className="brand-mark"><Icon name="shield" size={17}/></span><span>ReleaseProof</span></div><p>AI plans the investigation. Evidence makes the decision.</p><span>Prototype · 2026</span></footer>
    </div>
  );
}
