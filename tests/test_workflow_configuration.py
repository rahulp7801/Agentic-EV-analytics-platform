from pathlib import Path
import re


WORKFLOW = Path(__file__).parents[1] / ".github" / "workflows" / "data.yml"
CI_WORKFLOW = Path(__file__).parents[1] / ".github" / "workflows" / "ci.yml"
SUPPLEMENTAL_PUBLIC_SCHEDULE = "22,52 * * * *"
PUBLIC_DAILY_RECOVERY_SCHEDULE = "47 13 * * *"


def test_public_recovery_slots_are_public_only() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")
    schedules = set(re.findall(r"^\s+- cron: '([^']+)'$", source, re.MULTILINE))
    assert schedules == {
        "17 13 * * *",
        "7,37 * * * *",
        SUPPLEMENTAL_PUBLIC_SCHEDULE,
        PUBLIC_DAILY_RECOVERY_SCHEDULE,
    }
    for prefix in ("    if:", "      ODDS_API_KEY:", "      OPERATION:"):
        line = next(line for line in source.splitlines() if line.startswith(prefix))
        for schedule in (SUPPLEMENTAL_PUBLIC_SCHEDULE, PUBLIC_DAILY_RECOVERY_SCHEDULE):
            assert line.count(f"github.event.schedule != '{schedule}'") == 1

    operation = next(line for line in source.splitlines() if line.startswith("      OPERATION:"))
    public_daily = (
        "(github.event.schedule == '17 13 * * *' || "
        f"github.event.schedule == '{PUBLIC_DAILY_RECOVERY_SCHEDULE}') && 'public_daily'"
    )
    assert public_daily in operation


def test_hosted_schema_must_match_before_collection_and_deploy() -> None:
    data = WORKFLOW.read_text(encoding="utf-8")
    ci = CI_WORKFLOW.read_text(encoding="utf-8")
    check = "uv run --locked alembic current --check-heads"
    assert data.index(check) < data.index("name: Update market data")
    assert ci.count(check) == 1
    assert "needs: [secrets, backend, frontend, postgres, worker-image, production-schema]" in ci
