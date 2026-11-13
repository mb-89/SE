"""The Python fake leg of kern's contract suite (kern/contract/README.md).

Each case of ``contract/cases.json`` runs tally, the fixture component in Python,
against :class:`kern.fake.Fake`, as ``contract/fake_test.go`` runs it in Go against
kerntest and ``contract/real_test.go`` against the real core. The subject tokens and
the declarations' refusals are held to the same files as Go's.
"""

from __future__ import annotations

import json
import sys
import threading
from pathlib import Path

import pytest

KERN = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(KERN / "python"))

from kern import declaration, runner, subjects  # noqa: E402
from kern.component import KernError  # noqa: E402
from kern.fake import Fake  # noqa: E402

CONTRACT = KERN / "contract"
TALLY = CONTRACT / "fixture" / "tally"
CASES = json.loads((CONTRACT / "cases.json").read_text(encoding="utf-8"))["cases"]


@pytest.fixture(scope="module")
def tally():
    return runner.load(TALLY)


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_the_python_fake_keeps_the_contract(tally, case: dict) -> None:
    fake = Fake(tally)
    fake.seed(case.get("seed", {}))
    fake.config(case.get("config", {}))
    for port, answers in case.get("answers", {}).items():
        queue = list(answers)

        def answer(_req, queue=queue):
            if not queue:
                raise KernError("the case gives no more answers")
            a = queue.pop(0)
            if a.get("error"):
                raise KernError(a["error"])
            return a["answer"]

        fake.answer(port, answer)
    text, error = "", None
    if "overlap" in case:
        assert overlapping(fake, case["overlap"]) == case["want"]["calls"]
        return
    try:
        if "derive" in case:
            fake.derive(case["derive"])
        if "run" in case:
            text = fake.run(*case["run"])
    except KernError as e:
        error = e
    want = case["want"]
    if "text" in want:
        assert text == want["text"]
    if "lines" in want:
        assert fake.lines == want["lines"]
    if want.get("error"):
        assert error is not None, f"it passes, and wants an error holding {want['error']}"
        for s in want["error"]:
            assert s in str(error)
    else:
        assert error is None, str(error)
    if "requests" in want:
        assert [{"port": a.port, "value": a.value} for a in fake.requests] == want["requests"]
    for port, w in want.get("outputs", {}).items():
        v = fake.out(port)
        assert (v.value, v.provided) == (w["value"], w["provided"]), port


def overlapping(fake: Fake, runs: list[list[str]]) -> list[dict]:
    """Run each call at once, each in its own thread with its own caller: its text and its lines."""
    got: list[dict] = [{} for _ in runs]

    def call(i: int, run: list[str]) -> None:
        lines: list[str] = []
        try:
            got[i] = {"text": fake.run(*run, say=lines.append), "lines": lines}
        except KernError as e:
            got[i] = {"error": str(e), "lines": lines}

    threads = [threading.Thread(target=call, args=(i, run)) for i, run in enumerate(runs)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return got


def test_subject_tokens() -> None:
    v = json.loads((CONTRACT / "subjects.json").read_text(encoding="utf-8"))
    for n in v["names"]:
        assert subjects.subject(n["name"]) == n["subject"]
        assert subjects.name(n["subject"]) == n["name"]
    for w in v["tokens"]:
        assert subjects.token(w["word"]) == w["token"]
        assert subjects.word(w["token"]) == w["word"]


def test_declarations_are_refused_as_go_refuses_them() -> None:
    v = json.loads((CONTRACT / "declarations.json").read_text(encoding="utf-8"))
    for r in v["refused"]:
        with pytest.raises(declaration.DeclarationError) as e:
            declaration.parse(r["text"].encode())
        for s in r["error"]:
            assert s in str(e.value), r["name"]
    h = v["hash"]
    assert declaration.digest(h["text"].encode()) == declaration.digest(h["same_as"].encode())
    assert declaration.digest(b"").startswith("sha256:")


def test_a_component_without_a_function_for_its_declaration_is_refused(tmp_path: Path) -> None:
    (tmp_path / "component.toml").write_bytes((TALLY / "component.toml").read_bytes())
    (tmp_path / "__init__.py").write_text("from kern import component\ntally = component('tally')\n", encoding="utf-8")
    with pytest.raises(KernError, match="declares derivation total, command 'tally file'"):
        runner.load(tmp_path)
