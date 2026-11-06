"""The decision deck command (scripts/deck.py) and its Claude-app answers bundle (scripts/deck_answers.js).

The warning refusal, the answers summary and the bundle run on fakes; one end-to-end test builds a
deck with the real obs, serves it with `deck serve --wait`, sends from a browser and reads the answers.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
import build_docs  # noqa: E402
import deck  # noqa: E402

NOTE = "---\nobs: {bless: pending}\n---\n# %s\n\nThis is one case of how %s is chosen.\n"


def _folder(tmp_path: Path, notes: dict[str, str]) -> Path:
    folder = tmp_path / "decisions"
    folder.mkdir()
    (folder / "manifest.md").write_text("---\ntitle: Decisions\n---\n\n" + "".join(
        f"- [[{name}|{name.title()}]]\n" for name in notes), encoding="utf-8")
    for name, text in notes.items():
        (folder / f"{name}.md").write_text(text, encoding="utf-8")
    return folder


def test_build_refuses_on_an_obs_warning(tmp_path, monkeypatch, capsys):
    # A fake obs-document that builds and warns.
    def fake_run(command, **_):
        Path(command[command.index("--destination") + 1]).write_text("<html>", encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, "", "obs-document: warning: one: long paragraph\n")

    monkeypatch.setattr(deck, "obs_dir", lambda: tmp_path)
    monkeypatch.setattr(build_docs.subprocess, "run", fake_run)
    folder = _folder(tmp_path, {"one": NOTE % ("One", "one")})
    assert deck.build(folder, tmp_path / "deck.html") == 1
    err = capsys.readouterr().err
    assert "long paragraph" in err and "deck: 1 obs warning(s)" in err


def test_build_refuses_a_chapter_that_asks_for_no_bless(tmp_path, obs):
    folder = _folder(tmp_path, {"one": NOTE % ("One", "one"), "two": "# Two\n\nA record only.\n"})
    result = subprocess.run([sys.executable, str(SCRIPTS / "deck.py"), "build", str(folder),
                             "--destination", str(tmp_path / "deck.html")], capture_output=True, text=True)
    assert result.returncode == 1, result.stderr
    assert "chapter(s) two ask for no bless" in result.stderr
    assert not (tmp_path / "deck.html").exists()


PAYLOAD = {"verdicts": [
    {"chapter": "record", "version": "0" * 64, "verdict": "pick", "comment": "C needs no second place.",
     "pick": {"figure": "record--figure-1", "option": "C"},
     "figures": {"record--figure-1": {"weights": {"places": 1}, "marks": {"B": {"places": -1}},
                                      "rulings": {"A": {"ruling": "could", "tripwire": "a second place"}},
                                      "winner": "B"}}},
    {"chapter": "swipe", "version": "1" * 64, "verdict": "bless"}]}


def test_answers_parse_into_the_summary():
    assert deck.summary(PAYLOAD) == (
        "record: pick C (figure record--figure-1)\n"
        "  comment: C needs no second place.\n"
        "  record--figure-1 weights: places 1\n"
        "  record--figure-1 marks of B: places -1\n"
        "  record--figure-1 ruling on A: could, tripwire: a second place\n"
        "  record--figure-1 winner with these changes: B\n"
        "swipe: bless")
    with pytest.raises(ValueError, match="verdicts list"):
        deck.summary({"answers": []})


BUNDLE_DOUBLE = """
const bundle = require("fs").readFileSync(process.argv[1], "utf8");
const calls = {application: null, sink: null, published: []};
const run = (claude) => {
    calls.sink = null;
    globalThis.obsArtifact = {
        registerApplication: application => { calls.application = application.id; },
        trustedExtension: namespace => ({register: sink => { calls.sink = {namespace, ...sink}; }}),
    };
    globalThis.claude = claude;
    eval(bundle);
};
(async () => {
    run(undefined);
    const local = {application: calls.application, sink: calls.sink};
    run({use: async name => name === "artifact"
        ? {publish: async files => { calls.published.push(files); return {version: "v2"}; }} : null});
    const result = await calls.sink.send(JSON.parse(process.argv[2]));
    console.log(JSON.stringify({local, namespace: calls.sink.namespace, id: calls.sink.id, result,
                                published: calls.published}));
})();
"""


def test_the_bundle_saves_the_payload_through_the_files_form():
    if shutil.which("node") is None:
        pytest.skip("node is not installed")
    result = subprocess.run(["node", "-e", BUNDLE_DOUBLE, str(SCRIPTS / "deck_answers.js"), json.dumps(PAYLOAD)],
                            capture_output=True, text=True, check=True)
    calls = json.loads(result.stdout)
    # Outside the Claude app it registers no sink, so obs-html serve takes the answers.
    assert calls["local"] == {"application": deck.BUNDLE_ID, "sink": None}
    assert (calls["namespace"], calls["id"]) == ("obsHtml.answers", "claude-artifact")
    assert calls["result"] == {"written": "answers.json", "version": "v2"}
    assert [list(files) for files in calls["published"]] == [["answers.json"]]
    assert json.loads(calls["published"][0]["answers.json"]) == PAYLOAD


SEND = """
const {chromium} = require("playwright");
(async () => {
    const [url, first] = process.argv.slice(1);
    const browser = await chromium.launch();
    try {
        const page = await browser.newPage();
        await page.goto(`${url}#${first}`);
        await page.waitForFunction(() => document.documentElement.dataset.artifactStatus === "ready");
        const send = page.locator("[data-bless-send]");
        while (!/^Send (\\d+)\\/\\1$/.test(await send.textContent())) {
            await page.locator('[data-bless-key="bless"]:visible').click();
        }
        await send.click();
        await page.locator("[data-bless-pill]", {hasText: "sent"}).waitFor({timeout: 10000});
    } finally {
        await browser.close();
    }
})();
"""


def test_build_serve_wait_and_send_from_the_browser_print_the_answers(tmp_path, obs):
    browser = subprocess.run(["node", "-e", "require('playwright')"], capture_output=True) \
        if shutil.which("node") else None
    if browser is None or browser.returncode:
        pytest.skip("node with playwright is not installed")
    folder = _folder(tmp_path, {"cache": NOTE % ("Cache", "a cache"), "queue": NOTE % ("Queue", "a queue")})
    artifact = tmp_path / "deck.html"
    built = subprocess.run([sys.executable, str(SCRIPTS / "deck.py"), "build", str(folder), "--destination",
                            str(artifact)], capture_output=True, text=True)
    assert built.returncode == 0, built.stderr
    served = subprocess.Popen([sys.executable, str(SCRIPTS / "deck.py"), "serve", str(artifact), "--wait",
                               "--timeout", "60"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        url = served.stdout.readline().strip()
        assert url.startswith("http://127.0.0.1:"), served.stderr.read()
        subprocess.run(["node", "-e", SEND, url, "cache"], check=True, timeout=60)
        out, err = served.communicate(timeout=30)
    finally:
        served.kill()
    assert served.returncode == 0, err
    printed = json.loads(out.strip().splitlines()[-1])
    assert [(item["chapter"], item["verdict"]) for item in printed["verdicts"]] == [("cache", "bless"), ("queue", "bless")]
    assert json.loads((tmp_path / "answers.json").read_text(encoding="utf-8")) == printed
    shown = subprocess.run([sys.executable, str(SCRIPTS / "deck.py"), "answers", str(tmp_path / "answers.json")],
                           capture_output=True, text=True)
    assert shown.stdout == "cache: bless\nqueue: bless\n", shown.stderr
