from __future__ import annotations

from pathlib import Path

import pytest

from bridgeconf import campaign
from bridgeconf.__main__ import main


def test_demo_and_run(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["demo", "--cases", "5"]) == 0
    out = capsys.readouterr().out
    assert "careful       failing cases   0/5" in out and "synthetic data only" in out
    assert main(["run", "--target", "careful", "--profile", "onchain", "--cases", "5"]) == 0
    capsys.readouterr()
    save = tmp_path / "fail"
    assert main(["run", "--target", "naive", "--cases", "3", "--payments", "5", "--save", str(save)]) == 2
    assert "Smallest case found" in capsys.readouterr().out
    saved = sorted(save.glob("*.json"))
    assert saved
    assert main(["replay", str(saved[0]), "--target", "naive"]) == 2
    assert main(["replay", str(saved[0]), "--target", "careful"]) == 0
    assert main(["run", "--target", "nonsense"]) == 1


def test_companion_receiver() -> None:
    pytest.importorskip("hookverify")
    pytest.importorskip("idemstore")
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from examples.companions import CompanionReceiver

    for profile in ("ach", "instant", "onchain"):
        c = campaign(lambda profile=profile: CompanionReceiver(profile), profile, 20, 10, 0)
        assert c.failing_cases == 0, c.by_rule
