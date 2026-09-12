from pathlib import Path
import re


WORKFLOW = Path(__file__).parents[1] / ".github" / "workflows" / "data.yml"
PUBLIC_WORKFLOW = Path(__file__).parents[1] / ".github" / "workflows" / "public-data.yml"
CI_WORKFLOW = Path(__file__).parents[1] / ".github" / "workflows" / "ci.yml"
SUPPLEMENTAL_PUBLIC_SCHEDULE = "22,52 * * * *"
PUBLIC_DAILY_RECOVERY_SCHEDULE = "47 13 * * *"


def _schedules(source: str) -> set[str]:
    return set(re.findall(r"^\s+- cron: '([^']+)'$", source, re.MULTILINE))


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
