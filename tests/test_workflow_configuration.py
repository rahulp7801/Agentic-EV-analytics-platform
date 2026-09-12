from pathlib import Path
import re


WORKFLOW = Path(__file__).parents[1] / ".github" / "workflows" / "data.yml"
SUPPLEMENTAL_PUBLIC_SCHEDULE = "22,52 * * * *"


def test_supplemental_monitor_slots_are_public_only() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")
    schedules = set(re.findall(r"^\s+- cron: '([^']+)'$", source, re.MULTILINE))
    assert schedules == {
        "17 13 * * *",
        "7,37 * * * *",
        SUPPLEMENTAL_PUBLIC_SCHEDULE,
    }
    guard = f"github.event.schedule != '{SUPPLEMENTAL_PUBLIC_SCHEDULE}'"
    for prefix in ("    if:", "      ODDS_API_KEY:", "      OPERATION:"):
        line = next(line for line in source.splitlines() if line.startswith(prefix))
        assert line.count(guard) == 1
