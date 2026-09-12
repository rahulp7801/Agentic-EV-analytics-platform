from pathlib import Path
import re


WORKFLOW = Path(__file__).parents[1] / ".github" / "workflows" / "data.yml"
PUBLIC_WORKFLOW = Path(__file__).parents[1] / ".github" / "workflows" / "public-data.yml"
CI_WORKFLOW = Path(__file__).parents[1] / ".github" / "workflows" / "ci.yml"
SUPPLEMENTAL_PUBLIC_SCHEDULE = "22,52 * * * *"
PUBLIC_DAILY_RECOVERY_SCHEDULE = "47 13 * * *"


def _schedules(source: str) -> set[str]:
    return set(re.findall(r"^\s+- cron: '([^']+)'$", source, re.MULTILINE))


def _step(source: str, name: str) -> str:
    start = source.index(f"      - name: {name}")
    end = source.find("\n      - ", start + 1)
    return source[start:] if end == -1 else source[start:end]


def test_paid_and_public_schedules_are_isolated() -> None:
    paid = WORKFLOW.read_text(encoding="utf-8")
    public = PUBLIC_WORKFLOW.read_text(encoding="utf-8")

    assert _schedules(paid) == {"17 13 * * *", "7,37 * * * *"}
    assert _schedules(public) == {
        "17 13 * * *",
        "7,37 * * * *",
        SUPPLEMENTAL_PUBLIC_SCHEDULE,
        PUBLIC_DAILY_RECOVERY_SCHEDULE,
    }

    assert "vars.DATA_PIPELINE_ENABLED == 'true'" in paid
    assert "PUBLIC_DATA_PIPELINE_ENABLED" not in paid
    assert "vars.PUBLIC_DATA_PIPELINE_ENABLED == 'true'" in public
    assert "vars.DATA_PIPELINE_ENABLED" not in public
    assert "ODDS_API_KEY" not in public
    assert "group: market-data" in paid
    assert "group: public-market-data" in public

    operation = next(line for line in public.splitlines() if line.startswith("      OPERATION:"))
    public_daily = (
        "(github.event.schedule == '17 13 * * *' || "
        f"github.event.schedule == '{PUBLIC_DAILY_RECOVERY_SCHEDULE}') && 'public_daily'"
    )
    assert public_daily in operation


def test_hosted_schema_must_match_before_collection_and_deploy() -> None:
    data = WORKFLOW.read_text(encoding="utf-8")
    public = PUBLIC_WORKFLOW.read_text(encoding="utf-8")
    ci = CI_WORKFLOW.read_text(encoding="utf-8")
    check = "uv run --locked alembic current --check-heads"
    assert data.index(check) < data.index("name: Update market data")
    assert public.index(check) < public.index("name: Update public market data")
    assert ci.count(check) == 1
    assert "needs: [secrets, backend, frontend, postgres, worker-image, production-schema]" in ci


def test_public_collection_verifies_the_deployed_contract_before_success() -> None:
    public = PUBLIC_WORKFLOW.read_text(encoding="utf-8")
    update = "name: Update public market data"
    readiness = "name: Verify deployed public readiness"
    evidence = "name: Stage public evidence without configured provider credentials"

    assert public.index(update) < public.index(readiness) < public.index(evidence)
    assert '| tee "$RUNNER_TEMP/public-report.json"' in public
    assert "node frontend/scripts/verify-production.mjs" in public
    assert "DATA_PIPELINE_ENABLED: 'false'" in public
    assert "PUBLIC_DATA_PIPELINE_ENABLED: 'true'" in public
    assert "PUBLIC_DATA_REPORT_PATH: ${{ runner.temp }}/public-report.json" in public


def test_provider_credentials_are_scoped_to_the_steps_that_need_them() -> None:
    paid = WORKFLOW.read_text(encoding="utf-8")
    public = PUBLIC_WORKFLOW.read_text(encoding="utf-8")

    assert "secrets." not in paid[:paid.index("    steps:")]
    assert "secrets." not in public[:public.index("    steps:")]

    for source, update, evidence in (
        (paid, "Update market data", "Stage public evidence without configured credentials"),
        (public, "Update public market data", "Stage public evidence without configured provider credentials"),
    ):
        assert "secrets.DATABASE_URL" in _step(source, "Check worker configuration")
        assert "secrets.DATABASE_URL" in _step(source, "Verify hosted schema is at the application head")
        assert "secrets.DATABASE_URL" in _step(source, update)
        assert "secrets.DATABASE_URL" in _step(source, evidence)
        assert "secrets." not in _step(source, "Install checksum-pinned secret scanner")
        assert "secrets." not in _step(source, "Scan public evidence")
        assert "secrets." not in _step(source, "Retain public market evidence for replay")

    assert "secrets." not in _step(public, "Verify deployed public readiness")
    assert "secrets.ODDS_API_KEY" in _step(paid, "Update market data")
    assert "ODDS_API_KEY" not in public
