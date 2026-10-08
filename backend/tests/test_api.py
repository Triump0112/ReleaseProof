def _scenario_payload(client, scenario_id: str):
    response = client.get("/api/scenarios")
    assert response.status_code == 200
    scenario = next(item for item in response.json() if item["id"] == scenario_id)
    return scenario["suggested_change"]


def test_health_and_catalog(client):
    assert client.get("/health").json()["status"] == "ok"
    catalog = client.get("/api/catalog")
    assert catalog.status_code == 200
    ids = {item["id"] for item in catalog.json()}
    assert {"health_check", "api_smoke", "contract_compatibility", "bounded_load"} <= ids

    risk_classes = client.get("/api/risk-classes")
    assert risk_classes.status_code == 200
    coverage = {item["coverage"] for item in risk_classes.json()}
    assert {"implemented", "partial", "planned"} <= coverage


def test_concurrency_change_selects_load_and_blocks(client):
    response = client.post("/api/analyze", json=_scenario_payload(client, "concurrency-regression"))
    assert response.status_code == 200
    run = response.json()
    assert run["status"] == "COMPLETE"
    assert run["ledger"]["verdict"] == "BLOCK"
    adaptive = run["ledger"]["plan"]["adaptive_experiments"]
    assert adaptive[0]["experiment_id"] == "bounded_load"
    evidence = {item["experiment_id"]: item for item in run["ledger"]["evidence"]}
    assert evidence["health_check"]["passed"] is True
    assert evidence["bounded_load"]["passed"] is False

    stored = client.get(f"/api/runs/{run['id']}")
    assert stored.status_code == 200
    assert stored.json()["ledger"]["verdict"] == "BLOCK"


def test_api_change_selects_contract_and_blocks(client):
    response = client.post("/api/analyze", json=_scenario_payload(client, "api-contract-break"))
    assert response.status_code == 200
    run = response.json()
    assert run["ledger"]["verdict"] == "BLOCK"
    adaptive = run["ledger"]["plan"]["adaptive_experiments"]
    assert adaptive[0]["experiment_id"] == "contract_compatibility"
    contract = next(item for item in run["ledger"]["evidence"] if item["experiment_id"] == "contract_compatibility")
    assert contract["passed"] is False
    assert "total" in contract["explanation"]


def test_healthy_release_passes(client):
    response = client.post("/api/analyze", json=_scenario_payload(client, "healthy-release"))
    assert response.status_code == 200
    run = response.json()
    assert run["status"] == "COMPLETE"
    assert run["ledger"]["verdict"] == "PASS"


def test_unknown_scenario_and_missing_target_are_rejected(client):
    unknown = {
        "service_name": "x",
        "summary": "unknown fixture",
        "scenario_id": "does-not-exist",
    }
    assert client.post("/api/analyze", json=unknown).status_code == 422

    missing = {"service_name": "x", "summary": "no execution target"}
    response = client.post("/api/analyze", json=missing)
    assert response.status_code == 422


def test_malformed_run_id_does_not_escape_ledger(client):
    response = client.get("/api/runs/not-a-uuid")
    assert response.status_code == 404


def test_planner_never_exceeds_adaptive_budget(client):
    payload = _scenario_payload(client, "concurrency-regression")
    payload["summary"] = "Change concurrency, response schema, payload limits, retries and dependency timeouts"
    payload["diff"] = "concurrency schema payload retry dependency"
    payload["budget"]["max_adaptive_experiments"] = 1
    response = client.post("/api/analyze", json=payload)
    assert response.status_code == 200
    adaptive = response.json()["ledger"]["plan"]["adaptive_experiments"]
    assert len(adaptive) == 1


def test_zero_adaptive_budget_runs_baseline_only(client):
    payload = _scenario_payload(client, "concurrency-regression")
    payload["budget"]["max_adaptive_experiments"] = 0
    response = client.post("/api/analyze", json=payload)
    assert response.status_code == 200
    run = response.json()
    assert run["ledger"]["plan"]["adaptive_experiments"] == []
    assert [item["experiment_id"] for item in run["ledger"]["evidence"]] == ["health_check", "api_smoke"]


def test_explorer_mode_authors_bounded_review_only_probe(client):
    payload = _scenario_payload(client, "healthy-release")
    payload["analysis_mode"] = "explorer"
    response = client.post("/api/analyze", json=payload)
    assert response.status_code == 200
    run = response.json()
    plan = run["ledger"]["plan"]
    assert plan["analysis_mode"] == "explorer"
    assert len(plan["exploratory_experiments"]) == 1
    generated = plan["exploratory_experiments"][0]
    assert generated["query_parameters"] == {"releaseproof_explorer": "boundary"}
    assert "source_code" not in generated
    assert "url" not in generated

    explorer = next(
        item for item in run["ledger"]["evidence"] if item["experiment_id"] == "ai_explorer"
    )
    assert explorer["blocking"] is False
    assert explorer["review_only"] is True
    assert explorer["exploratory_spec"]["name"] == "generated-boundary-probe"
    assert run["ledger"]["verdict"] == "PASS"


def test_guarded_mode_never_adds_generated_probe(client):
    payload = _scenario_payload(client, "healthy-release")
    response = client.post("/api/analyze", json=payload)
    assert response.status_code == 200
    run = response.json()
    assert run["ledger"]["plan"]["analysis_mode"] == "guarded"
    assert run["ledger"]["plan"]["exploratory_experiments"] == []
    assert all(item["experiment_id"] != "ai_explorer" for item in run["ledger"]["evidence"])
