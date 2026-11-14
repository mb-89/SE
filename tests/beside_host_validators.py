"""The hosts' own validators against the layouts the build wrote (scripts/host_validate.py), beside
the suite and outside its default collection. Off by default: se.toml declares no beside suite for
it; adding `[tests.beside.host-validators]` is the owner's step. Each installed validator runs once
over this checkout's built layouts and must pass; an absent one is skipped, naming the tool."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import host_validate  # noqa: E402

RUNNABLE = [validator for validator in host_validate.VALIDATORS if validator.tool is not None]


@pytest.mark.parametrize("validator", RUNNABLE, ids=[validator.tool for validator in RUNNABLE])
def test_the_host_accepts_the_built_layouts(validator):
    version = host_validate.run_process([validator.tool, *validator.version_args], ROOT, 30)
    if version.absent:
        pytest.skip(f"{validator.tool} not installed")
    lines, code = host_validate.report(host_validate.collect(ROOT, host_validate.run_process, [validator]))
    assert code == 0, "\n".join(lines)
