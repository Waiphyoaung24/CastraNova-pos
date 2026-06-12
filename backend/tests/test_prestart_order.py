"""Regression guard for the prestart bootstrap ordering.

`backend_pre_start.py` probes the database through the runtime engine, which
connects as POSTGRES_APP_USER — the least-privilege ``castranova_app`` role.
That role is created by `ensure_app_role.py`. So on a fresh database the
role-creation step MUST run before the readiness probe, otherwise prestart dies
with ``password authentication failed for user "castranova_app"`` before the
role is ever created. This test fails on the reversed (pre-fix) order.
"""

from pathlib import Path

PRESTART = Path(__file__).resolve().parent.parent / "scripts" / "prestart.sh"


def _step_line(lines: list[str], script: str) -> int:
    """Return the index of the first non-comment line invoking ``script``."""
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        if script in stripped:
            return i
    raise AssertionError(f"{script} is not invoked in prestart.sh")


def test_ensure_app_role_runs_before_backend_pre_start() -> None:
    lines = PRESTART.read_text(encoding="utf-8").splitlines()

    ensure_role = _step_line(lines, "app/ensure_app_role.py")
    db_probe = _step_line(lines, "app/backend_pre_start.py")

    assert ensure_role < db_probe, (
        "ensure_app_role.py must run before backend_pre_start.py: the readiness "
        "probe connects as the least-privilege app role, which ensure_app_role.py "
        "creates. Reversing them breaks a fresh `docker compose up`."
    )
