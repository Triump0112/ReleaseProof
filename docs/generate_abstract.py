from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.colors import HexColor
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import HRFlowable, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "output" / "pdf" / "ReleaseProof_Abstract.pdf"

INK = HexColor("#13233A")
MUTED = HexColor("#52657B")
BLUE = HexColor("#245FC7")
BLUE_DARK = HexColor("#173E84")
CYAN = HexColor("#1BA8BA")
GREEN = HexColor("#167D62")
RED = HexColor("#B83C4A")
PALE_BLUE = HexColor("#EDF4FF")
PALE_CYAN = HexColor("#EEF9FA")
PALE_GRAY = HexColor("#F5F7FA")
PALE_RED = HexColor("#FFF1F2")
LINE = HexColor("#D8E1EC")
WHITE = colors.white


styles = getSampleStyleSheet()
TITLE = ParagraphStyle("Title", parent=styles["Title"], fontName="Helvetica-Bold", fontSize=27, leading=31, textColor=INK, alignment=TA_LEFT, spaceAfter=3 * mm)
SUBTITLE = ParagraphStyle("Subtitle", parent=styles["Normal"], fontName="Helvetica", fontSize=11, leading=15, textColor=MUTED, spaceAfter=5 * mm)
H1 = ParagraphStyle("H1", parent=styles["Heading1"], fontName="Helvetica-Bold", fontSize=14, leading=16.5, textColor=BLUE_DARK, spaceBefore=2.2 * mm, spaceAfter=1.2 * mm, keepWithNext=True)
BODY = ParagraphStyle("Body", parent=styles["BodyText"], fontName="Helvetica", fontSize=8.15, leading=10.7, textColor=INK, spaceAfter=1.4 * mm)
SMALL = ParagraphStyle("Small", parent=BODY, fontSize=7.15, leading=8.9, textColor=MUTED, spaceAfter=0)
SMALL_DARK = ParagraphStyle("SmallDark", parent=SMALL, textColor=INK)
LABEL = ParagraphStyle("Label", parent=SMALL, fontName="Helvetica-Bold", fontSize=7.2, leading=8.8, textColor=BLUE, spaceAfter=1 * mm)
CALLOUT = ParagraphStyle("Callout", parent=BODY, fontName="Helvetica-Bold", fontSize=9.2, leading=12.4, textColor=BLUE_DARK, alignment=TA_CENTER, spaceAfter=0)
FOOT = ParagraphStyle("Foot", parent=SMALL, fontSize=6.8, leading=8.4)


def p(text: str, style: ParagraphStyle = BODY) -> Paragraph:
    return Paragraph(text, style)


def section(title: str) -> list:
    return [p(title, H1), HRFlowable(width="100%", thickness=0.7, color=LINE, spaceAfter=2.2 * mm)]


def info_table(items: list[tuple[str, str]], widths: list[float]) -> Table:
    cells = [p(f"<font color='#245FC7'><b>{label}</b></font><br/>{value}", SMALL_DARK) for label, value in items]
    table = Table([cells], colWidths=widths, hAlign="LEFT")
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), PALE_BLUE),
        ("BOX", (0, 0), (-1, -1), 0.7, LINE),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, LINE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 5.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5.5),
    ]))
    return table


def matrix(headers: list[str], rows: list[list[str]], widths: list[float]) -> Table:
    data = [[p(item, LABEL) for item in headers]] + [[p(item, SMALL_DARK) for item in row] for row in rows]
    table = Table(data, colWidths=widths, repeatRows=1, hAlign="LEFT")
    commands = [
        ("BACKGROUND", (0, 0), (-1, 0), PALE_BLUE),
        ("BOX", (0, 0), (-1, -1), 0.7, LINE),
        ("INNERGRID", (0, 0), (-1, -1), 0.45, LINE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 3.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5),
    ]
    for index in range(1, len(data)):
        if index % 2 == 0:
            commands.append(("BACKGROUND", (0, index), (-1, index), PALE_GRAY))
    table.setStyle(TableStyle(commands))
    return table


def callout(text: str, fill=PALE_CYAN, border=CYAN) -> Table:
    table = Table([[p(text, CALLOUT)]], colWidths=[175 * mm])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), fill),
        ("BOX", (0, 0), (-1, -1), 0.9, border),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    return table


def header_footer(canvas, doc):
    canvas.saveState()
    page_width, page_height = A4
    canvas.setFillColor(BLUE_DARK)
    canvas.rect(0, page_height - 7 * mm, page_width, 7 * mm, fill=1, stroke=0)
    canvas.setFillColor(WHITE)
    canvas.setFont("Helvetica-Bold", 7.2)
    canvas.drawString(16 * mm, page_height - 4.7 * mm, "RELEASEPROOF | TECHNICAL ABSTRACT")
    canvas.setFont("Helvetica", 7.2)
    canvas.drawRightString(page_width - 16 * mm, page_height - 4.7 * mm, "AI BUILDER CUP 2026")
    canvas.setStrokeColor(LINE)
    canvas.line(16 * mm, 12 * mm, page_width - 16 * mm, 12 * mm)
    canvas.setFillColor(MUTED)
    canvas.setFont("Helvetica", 6.9)
    canvas.drawString(16 * mm, 8 * mm, "Pre-traffic differential release verification for Cloud Run")
    canvas.drawRightString(page_width - 16 * mm, 8 * mm, f"Page {doc.page}")
    canvas.restoreState()


def build_story() -> list:
    story: list = []

    # PAGE 1 - Executive abstract and differentiation.
    story.extend([
        Spacer(1, 2 * mm),
        p("ReleaseProof", TITLE),
        p("A change-aware, evidence-backed release gate that detects hidden regressions in a Cloud Run candidate before production traffic is shifted.", SUBTITLE),
        info_table([
            ("CATEGORY", "Future of Work and Enterprise Productivity"),
            ("MVP SCOPE", "Cloud Run HTTP services; stable versus tagged candidate"),
            ("DECISION", "PASS, BLOCK, or INCONCLUSIVE"),
            ("AI ROLE", "Hypothesis formation and bounded experiment selection"),
        ], [43.75 * mm] * 4),
        Spacer(1, 3 * mm),
    ])
    story.extend(section("1. Executive abstract"))
    story.append(p("Modern deployment systems can run health checks, smoke tests, canaries, and user-configured verification jobs. The remaining problem is not the absence of tests; it is choosing the most informative test for a particular code or configuration change. A candidate may return HTTP 200 while introducing tail-latency under concurrency, breaking an API response contract, or failing only at input boundaries. Fixed verification often misses these change-specific risks until production traffic is exposed."))
    story.append(p("ReleaseProof adds a bounded investigation layer before traffic migration. Gemini reads a change summary and diff, states a falsifiable regression hypothesis, and selects up to two experiments from an allowlisted catalog. The same experiment is executed against the stable revision and a tagged candidate with zero user traffic. Deterministic code owns measurements, thresholds, and the final release verdict. Every input, plan, measurement, threshold, and outcome is retained as replayable evidence."))
    story.append(callout("Core principle: AI plans the investigation; measured evidence makes the release decision."))
    story.extend(section("2. Problem and target user"))
    story.append(p("The primary user is a small platform or application team deploying HTTP services to Cloud Run without a dedicated site-reliability engineering function. Such teams can configure tests, but they may not anticipate which risk a specific change introduces. ReleaseProof targets the decision point immediately before traffic migration, when a stable and candidate revision both exist and a fast, bounded comparison is possible."))
    story.append(matrix(
        ["Observed gap", "Consequence", "ReleaseProof response"],
        [
            ["Health checks validate availability, not behavioral equivalence.", "A healthy candidate can still be slower or incompatible.", "Always compare the same probe on stable and candidate."],
            ["Fixed suites are broad but not change-aware.", "Relevant tests may be omitted or buried under expensive checks.", "Select experiments from diff-derived, falsifiable risks."],
            ["AI release advice can be persuasive but unverifiable.", "Teams may trust fluent explanations instead of measurements.", "Prevent Gemini from setting thresholds or overriding verdicts."],
            ["Canaries expose some users to the candidate.", "A bad release can affect customers before analysis converges.", "Probe a tagged, zero-traffic candidate before rollout."],
        ], [49 * mm, 55 * mm, 71 * mm]))
    story.extend(section("3. Differentiation from existing deployment verification"))
    story.append(p("ReleaseProof does not claim that Google Cloud lacks verification. Cloud Deploy already supports verification tasks, canary phases, and telemetry analysis. The proposed contribution is a change-specific planning and differential evidence layer that can eventually run as a Cloud Deploy verification task."))
    story.append(matrix(
        ["Capability", "Conventional configured verification", "ReleaseProof"],
        [
            ["Test choice", "Defined in advance by the team", "Selected per change from an allowlisted catalog"],
            ["Comparison", "Often candidate-only or telemetry-based", "Paired stable-versus-candidate experiment"],
            ["Timing", "After deployment or during canary traffic", "Before candidate receives production traffic"],
            ["Decision ownership", "Test exit code or configured analysis", "Fixed policy over preserved raw evidence"],
            ["AI contribution", "Optional", "Risk hypothesis and bounded experiment plan"],
        ], [35 * mm, 65 * mm, 75 * mm]))

    # PAGE 2 - Architecture, workflow, catalog, policy.
    story.extend(section("4. Technical architecture"))
    story.append(callout(
        "Firebase-ready React UI  ->  Cloud Run orchestrator  ->  Vertex AI Gemini planner<br/>"
        "-> paired HTTP experiment runner  ->  deterministic evaluator  ->  Firestore-ready evidence ledger",
        fill=PALE_BLUE, border=BLUE))
    story.append(Spacer(1, 2 * mm))
    story.append(matrix(
        ["Component", "Prototype responsibility", "Production mapping"],
        [
            ["Web application", "Select scenario, display change, plan, measurements, decision timeline, and evidence ID.", "Firebase Hosting or Cloud Run"],
            ["Orchestrator API", "Validate bounded requests, call planner, execute experiments, calculate verdict, expose run records.", "Cloud Run service"],
            ["Gemini planner", "Interpret diff, state risk, choose no more than two catalog experiments using structured output.", "Gemini on Vertex AI"],
            ["Experiment runner", "Issue identical warmups and bounded probes to stable and candidate URLs.", "Private Cloud Run service or orchestrator worker"],
            ["Policy evaluator", "Apply fixed contract, latency, error-rate, and completeness rules.", "Deterministic application code"],
            ["Evidence ledger", "Persist request, plan, thresholds, measurements, verdict, timestamps, and run ID.", "Firestore plus Cloud Storage and Logging"],
        ], [34 * mm, 75 * mm, 66 * mm]))
    story.extend(section("5. End-to-end analysis sequence"))
    story.append(matrix(
        ["Step", "Stage", "What happens"],
        [
            ["1", "Receive change", "Service metadata, diff, stable URL, candidate URL, request path, expected contract, and execution budget."],
            ["2", "Run fixed baseline", "Health and smoke checks execute for every candidate; adaptive planning cannot remove them."],
            ["3", "Form hypothesis", "Gemini turns change evidence into a concrete statement that an experiment can support or refute."],
            ["4", "Select experiment", "Structured output is restricted to the catalog and revalidated server-side; maximum two adaptive tests."],
            ["5", "Execute paired probes", "Stable and candidate receive identical requests, warmups, trials, and request limits."],
            ["6", "Evaluate deterministically", "Fixed policies compare compatibility, errors, p95 latency, and evidence completeness."],
            ["7", "Record decision", "Any blocking failure yields BLOCK; insufficient evidence yields INCONCLUSIVE; otherwise PASS."],
        ], [13 * mm, 38 * mm, 124 * mm]))
    story.extend(section("6. Bounded experiment catalog"))
    story.append(matrix(
        ["Experiment", "Risk addressed", "MVP status"],
        [
            ["Health check", "Revision unavailable or non-responsive", "Implemented; mandatory baseline"],
            ["API smoke", "Primary endpoint fails for a representative request", "Implemented; mandatory baseline"],
            ["Contract compatibility", "Removed fields, changed types, or incompatible response shape", "Implemented and demonstrated"],
            ["Bounded load", "Tail-latency or error regression under concurrent requests", "Implemented and demonstrated"],
            ["Edge inputs", "Empty, Unicode, zero, negative, or boundary input behavior", "Cataloged; basic probe support"],
            ["Payload size", "Near-limit payload failure or disproportionate latency", "Cataloged; basic probe support"],
            ["Retry/idempotency", "Duplicate side effects after repeated request", "Cataloged; future domain-specific adapter"],
            ["Dependency timeout", "Slow upstream causes budget exhaustion or cascading failure", "Cataloged; future fault adapter"],
        ], [38 * mm, 85 * mm, 52 * mm]))
    story.extend(section("7. Decision policy and trust boundary"))
    decision_cells = [
        [p("<b><font color='#167D62'>PASS</font></b>", BODY), p("Every executed blocking experiment passes fixed policy and sufficient repeated evidence exists.", SMALL_DARK)],
        [p("<b><font color='#B83C4A'>BLOCK</font></b>", BODY), p("At least one blocking experiment demonstrates a contract, error-rate, availability, or latency violation.", SMALL_DARK)],
        [p("<b><font color='#A86C12'>INCONCLUSIVE</font></b>", BODY), p("Stable baseline is invalid, trials are incomplete, budget is exhausted, or the selected experiment lacks usable evidence.", SMALL_DARK)],
    ]
    decision_table = Table(decision_cells, colWidths=[35 * mm, 140 * mm])
    decision_table.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.7, LINE), ("INNERGRID", (0, 0), (-1, -1), 0.45, LINE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("BACKGROUND", (0, 0), (-1, 0), PALE_CYAN), ("BACKGROUND", (0, 1), (-1, 1), PALE_RED),
        ("BACKGROUND", (0, 2), (-1, 2), HexColor("#FFF8E8")),
        ("LEFTPADDING", (0, 0), (-1, -1), 7), ("RIGHTPADDING", (0, 0), (-1, -1), 7),
        ("TOPPADDING", (0, 0), (-1, -1), 3.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5),
    ]))
    story.append(decision_table)
    story.append(Spacer(1, 2 * mm))
    story.append(p("<b>Gemini may:</b> interpret the change, choose allowlisted experiments, revise a hypothesis, and explain evidence. <b>Gemini may not:</b> invent measurements, issue arbitrary network requests, select its own threshold, execute shell commands, suppress failed evidence, or override the evaluator."))

    # PAGE 3 - Demonstration, evaluation, limitations, roadmap.
    story.extend(section("8. Demonstration scenarios"))
    story.append(matrix(
        ["", "Scenario A: concurrency regression", "Scenario B: API contract regression"],
        [
            ["Change", "Cloud Run concurrency increases from 4 to 32.", "Response field total is renamed to amount and number becomes string."],
            ["Why smoke passes", "Single requests remain fast and return HTTP 200.", "Endpoint remains available and returns HTTP 200."],
            ["Gemini hypothesis", "CPU/resource contention may increase candidate tail-latency or errors.", "Existing clients may fail because a required field and type changed."],
            ["Selected test", "Bounded paired load experiment.", "Contract compatibility experiment."],
            ["Deterministic evidence", "Stable p95 versus candidate p95 and error-rate delta.", "Required fields and types compared with published contract and stable response."],
            ["Expected verdict", "BLOCK when p95 regression exceeds 30% or error increase exceeds 2 percentage points.", "BLOCK on a missing required field or incompatible type."],
        ], [31 * mm, 72 * mm, 72 * mm]))
    story.append(Spacer(1, 2 * mm))
    story.append(p("The second scenario is essential evidence that the planner is not blindly choosing the same test. A runtime configuration diff selects load; an application schema diff selects contract compatibility. In both cases the fixed baseline passes, so the adaptive experiment provides incremental value."))
    story.extend(section("9. Prototype status and evaluation plan"))
    story.append(info_table([
        ("IMPLEMENTED", "React UI, FastAPI API, planner, catalog, paired runner, evaluator, JSON ledger, and stable/candidate services"),
        ("VERIFIED", "8 backend tests, 8 demo-service tests, frontend build, and live HTTP validation of both scenarios"),
        ("LOCAL MODE", "Deterministic planner supports development without cloud credentials"),
        ("CLOUD MODE", "Vertex AI structured-output planner is implemented and activated by environment configuration"),
    ], [43.75 * mm] * 4))
    story.append(Spacer(1, 2 * mm))
    story.append(matrix(
        ["Evaluation measure", "Question answered", "Target for submission"],
        [
            ["Plan validity", "Does every plan satisfy schema, allowlist, and budget?", "100% of demo and held-out changes"],
            ["Adaptive diversity", "Do meaningfully different changes select different experiments?", "At least two change classes and two plans"],
            ["Baseline blind spot", "Would health and smoke have passed without the adaptive experiment?", "Yes for both principal scenarios"],
            ["Repeatability", "Do repeated paired trials produce the same decision?", "Three repeated runs per scenario"],
            ["Evidence integrity", "Can every verdict be traced to raw measurement and fixed threshold?", "Complete ledger for every run"],
            ["Latency", "Can the result fit a practical pre-traffic check?", "Under 90 seconds within request budget"],
        ], [43 * mm, 82 * mm, 50 * mm]))
    story.extend(section("10. Expected judging alignment"))
    story.append(matrix(
        ["Criterion", "Weight", "Evidence in prototype"],
        [
            ["Technical merit and GenAI", "40%", "Schema-constrained Gemini planning, real paired execution, deterministic policy, and evidence ledger."],
            ["Problem alignment and impact", "25%", "Prevents hidden regressions before user traffic and supports teams without specialist release engineering."],
            ["Innovation and creativity", "25%", "Change-specific, budgeted experiment selection plus pre-traffic stable-versus-candidate comparison."],
            ["User experience and design", "10%", "Two-click workflow, visible hypothesis, measurements, verdict, and decision timeline."],
        ], [47 * mm, 20 * mm, 108 * mm]))
    story.extend(section("11. Limitations and roadmap"))
    two_cols = Table([
        [p("CURRENT LIMITATIONS", LABEL), p("NEXT DEVELOPMENT STEPS", LABEL)],
        [
            p("- Narrow HTTP-only experiment catalog.<br/>- Demo thresholds are generic, not organization-calibrated.<br/>- Local ledger is JSON rather than immutable cloud storage.<br/>- Statistical treatment is intentionally simple.<br/>- Prototype does not automatically control production rollout.", SMALL_DARK),
            p("1. Deploy stable/candidate revisions and orchestrator to Cloud Run.<br/>2. Execute the Vertex AI Gemini planner with real credentials.<br/>3. Persist evidence in Firestore and export metrics to Cloud Monitoring.<br/>4. Add authenticated tagged-revision discovery and project allowlists.<br/>5. Package ReleaseProof as a Cloud Deploy verification task.", SMALL_DARK),
        ],
    ], colWidths=[87.5 * mm, 87.5 * mm])
    two_cols.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), PALE_BLUE), ("BOX", (0, 0), (-1, -1), 0.7, LINE),
        ("INNERGRID", (0, 0), (-1, -1), 0.45, LINE), ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 7), ("RIGHTPADDING", (0, 0), (-1, -1), 7),
        ("TOPPADDING", (0, 0), (-1, -1), 4.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 4.5),
    ]))
    story.append(two_cols)
    story.extend(section("12. Conclusion and references"))
    story.append(p("ReleaseProof is deliberately not an autonomous deployment agent. It is a constrained release investigator that converts an AI-selected hypothesis into paired, reproducible evidence and lets deterministic policy own the outcome. The prototype's success criterion is concrete: demonstrate a candidate that normal fixed verification would accept, but a change-aware experiment blocks before users are exposed."))
    story.append(p(
        "<b>Primary references:</b> "
        "<link href='https://aibuildercup.com/themes.html' color='#245FC7'>AI Builder Cup 2026 judging criteria</link>; "
        "<link href='https://docs.cloud.google.com/deploy/docs/verify-deployment' color='#245FC7'>Cloud Deploy verification</link>; "
        "<link href='https://docs.cloud.google.com/deploy/docs/analysis' color='#245FC7'>Cloud Deploy analysis</link>; "
        "<link href='https://docs.cloud.google.com/run/docs/rollouts-rollbacks-traffic-migration' color='#245FC7'>Cloud Run revision traffic and tags</link>.", FOOT))
    return story


def draw() -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    document = SimpleDocTemplate(
        str(OUTPUT), pagesize=A4,
        rightMargin=17 * mm, leftMargin=17 * mm, topMargin=12 * mm, bottomMargin=15 * mm,
        title="ReleaseProof - Technical Abstract", author="ReleaseProof Team",
        subject="Pre-traffic differential release verification for Cloud Run",
    )
    document.build(build_story(), onFirstPage=header_footer, onLaterPages=header_footer)
    print(OUTPUT)


if __name__ == "__main__":
    draw()
