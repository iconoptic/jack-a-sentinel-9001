from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from sentinel_recorder.config import ScheduleSettings, load_config
from sentinel_recorder.schedule import is_allowed
from sentinel_recorder.__main__ import main

UTC = timezone.utc
ROOT_CONFIG = Path(__file__).resolve().parents[1] / "config.toml"


def _at(year: int, month: int, day: int, hour: int, minute: int, tz=UTC) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=tz)


@pytest.mark.parametrize(
    ("moment", "allowed"),
    [
        (_at(2026, 10, 19, 5, 59), True),
        (_at(2026, 10, 19, 6, 0), False),
        (_at(2026, 10, 21, 12, 0), False),
        (_at(2026, 10, 23, 15, 59), False),
        (_at(2026, 10, 23, 16, 0), True),
        (_at(2026, 10, 24, 12, 0), True),
        (_at(2026, 10, 25, 23, 59), True),
        (_at(2026, 10, 19, 0, 30), True),
    ],
)
def test_quiet_window(moment: datetime, allowed: bool) -> None:
    assert is_allowed(moment, ScheduleSettings()) is allowed


def test_dst_chicago_2026() -> None:
    schedule = ScheduleSettings(timezone="America/Chicago")
    # Both transition days are Sundays, so the quiet window does not apply.
    # 08:30 UTC on 8 March is inside the spring-forward gap (02:30 local never exists).
    assert is_allowed(datetime(2026, 3, 8, 8, 30, tzinfo=UTC), schedule)
    assert is_allowed(datetime(2026, 3, 8, 18, 0, tzinfo=UTC), schedule)
    # 06:30 UTC is 01:30 CDT; 07:30 UTC is 01:30 CST after the fold.
    assert is_allowed(datetime(2026, 11, 1, 6, 30, tzinfo=UTC), schedule)
    assert is_allowed(datetime(2026, 11, 1, 7, 30, tzinfo=UTC), schedule)
    zone = ZoneInfo("America/Chicago")
    assert is_allowed(datetime(2026, 11, 1, 1, 30, tzinfo=zone, fold=0), schedule)
    assert is_allowed(datetime(2026, 11, 1, 1, 30, tzinfo=zone, fold=1), schedule)

    # Monday after the spring-forward uses CDT (UTC-5). 11:30 UTC is 06:30 local.
    assert is_allowed(datetime(2026, 3, 9, 10, 30, tzinfo=UTC), schedule)
    assert not is_allowed(datetime(2026, 3, 9, 11, 30, tzinfo=UTC), schedule)
    # Monday after the fall-back uses CST (UTC-6). 11:30 UTC is 05:30 local.
    assert is_allowed(datetime(2026, 11, 2, 11, 30, tzinfo=UTC), schedule)
    assert not is_allowed(datetime(2026, 11, 2, 12, 30, tzinfo=UTC), schedule)


def test_utc_instant_converted_to_local() -> None:
    instant = datetime(2026, 10, 19, 20, 30, tzinfo=UTC)
    assert is_allowed(instant, ScheduleSettings(timezone="UTC"))
    assert not is_allowed(instant, ScheduleSettings(timezone="America/Chicago"))


def test_schedule_disabled() -> None:
    noon = _at(2026, 10, 19, 12, 0)
    assert is_allowed(noon, ScheduleSettings(enabled=False))


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "recorder.toml"
    path.write_text(text, encoding="utf-8")
    return path


_BASE = """
[recorder]
[schedule]
enabled = true
timezone = "UTC"
quiet_days = ["mon", "tue", "wed", "thu", "fri"]
quiet_start = "06:00"
quiet_end = "16:00"
[motion]
[[cameras]]
frigate_name = "sentinel_a"
id = "a"
static_ip = "10.77.0.11"
"""


@pytest.mark.parametrize(
    "text",
    [
        _BASE.replace('quiet_start = "06:00"', 'quiet_start = "6am"'),
        _BASE.replace('"fri"', '"fri", "fun"'),
        _BASE.replace('timezone = "UTC"', 'timezone = "Mars/Base"'),
    ],
)
def test_bad_config_raises(tmp_path: Path, text: str) -> None:
    with pytest.raises(ValueError):
        load_config(_write(tmp_path, text))


def test_shipped_config_monday_evening_is_allowed() -> None:
    cfg = load_config(ROOT_CONFIG)
    moment = datetime(2026, 10, 19, 17, 0, tzinfo=ZoneInfo(cfg.schedule.timezone))
    assert is_allowed(moment, cfg.schedule)


def test_check_schedule_cli(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = _write(tmp_path, _BASE)
    with pytest.raises(SystemExit) as allowed:
        main(["check-schedule", str(path), "--at", "2026-10-19T05:30"])
    assert allowed.value.code == 0
    assert capsys.readouterr().out.strip() == "allowed"

    with pytest.raises(SystemExit) as quiet:
        main(["check-schedule", str(path), "--at", "2026-10-19T06:00"])
    assert quiet.value.code == 1
    assert capsys.readouterr().out.strip() == "quiet"
