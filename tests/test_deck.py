"""The decision deck command (scripts/deck.py) and its Claude-app answers bundle (scripts/deck_answers.js).

The warning refusal, the answers summary and the bundle run on fakes; one end-to-end test builds a
deck with the real obs, serves it with `deck serve --wait`, sends from a browser and reads the answers.
Every deck the tests build with the real obs is built once per session, all at once (`decks`), and the
browser tests share one page per worker (`page`).
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
import build_docs  # noqa: E402
import deck  # noqa: E402

NOTE = "---\nobs: {bless: pending}\n---\n# %s\n\nThis is one case of how %s is chosen.\n"


def _folder(tmp_path: Path, notes: dict[str, str], manifest: str | None = None) -> Path:
    folder = tmp_path / "decisions"
    folder.mkdir(parents=True)
    (folder / "manifest.md").write_text(manifest or "---\ntitle: Decisions\n---\n\n" + "".join(
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


RECORD = "# %s\n\nThis was decided without the person.\n"
PUGH = ("\n```pugh\ncriteria:\n  - {key: cost, label: Cost, weight: 1, better: higher, kind: judged}\n"
        "datum: {prefer: [b]}\ncandidates:\n"
        "  - {key: a, label: A, what: One way., marks: {cost: 1}, wins: Cheap., losses: New.}\n"
        "  - {key: b, label: B, what: The other., marks: {cost: 0}, wins: Known., losses: Dear.}\n```\n")


SHORT = PUGH.replace("label: B,", "label: B, short: Short,")
SCREENS = "- [[pick|Pick]]\n- [[done|Done]]\n"
PROFILES = {
    "no-profile": "---\ntitle: Decisions\n---\n\n",
    "block-profile": "---\ntitle: Decisions\nobsHtml:\n  heading: compact\n---\n\n",
    "flow-profile": "---\nobsHtml: {heading: compact}\n---\n\n",
}
# Every deck a test builds with the real obs: its notes and, where it sets one, its manifest.
DECKS = {
    "record": ({"one": NOTE % ("One", "one"), "two": NOTE % ("Two", "two"), "done": RECORD % "Done"}, None),
    "only-records": ({"done": RECORD % "Done", "tasks": RECORD % "Tasks"}, None),
    "decision-without-bless": ({"one": NOTE % ("One", "one"), "silent": RECORD % "Silent" + PUGH}, None),
    # A record chapter beside the decision: obs alone would open such a deck paged.
    **{f"screens-{profile}": ({"pick": NOTE % ("Pick", "a pick") + SHORT, "done": RECORD % "Done"},
                              manifest + SCREENS) for profile, manifest in PROFILES.items()},
    "scrolling": ({"one": NOTE % ("One", "one"), "done": RECORD % "Done"},
                  "---\nobsHtml:\n  layout: scrolling\n---\n\n- [[one|One]]\n- [[done|Done]]\n"),
    "send": ({"cache": NOTE % ("Cache", "a cache"), "queue": NOTE % ("Queue", "a queue")}, None),
}


def _deck(folder: Path, destination: Path) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(SCRIPTS / "deck.py"), "build", str(folder),
                           "--destination", str(destination)], capture_output=True, text=True)


@pytest.fixture(scope="session")
def decks(tmp_path_factory, obs) -> dict[str, tuple[subprocess.CompletedProcess, Path]]:
    """Each of DECKS built once with `deck.py build`, all at once: its build and its destination."""
    def built(name: str) -> tuple[subprocess.CompletedProcess, Path]:
        directory = tmp_path_factory.mktemp(name)
        notes, manifest = DECKS[name]
        destination = directory / "deck.html"
        return _deck(_folder(directory, notes, manifest), destination), destination

    with ThreadPoolExecutor(len(DECKS)) as pool:
        return dict(zip(DECKS, pool.map(built, DECKS)))


def test_build_takes_record_chapters_beside_the_decisions(decks):
    result, destination = decks["record"]
    assert result.returncode == 0, result.stderr
    assert destination.exists()


@pytest.mark.parametrize(("name", "refusal"), [
    ("only-records", "no chapter asks for a bless"),
    ("decision-without-bless", "decision(s) silent ask for no bless"),
], ids=["only-records", "decision-without-bless"])
def test_build_refuses_a_deck_that_asks_nothing_or_a_silent_decision(decks, name, refusal):
    result, destination = decks[name]
    assert result.returncode == 1, result.stderr
    assert refusal in result.stderr and "`obs: {bless: pending}`" in result.stderr
    assert not destination.exists()


PAGE = """
const {chromium} = require("playwright");
const readline = require("readline");
const actions = {
    // A deck opened at its pick chapter: its layout and the pugh figure's bottom line.
    look: async (page, {path}) => {
        await page.setViewportSize({width: 1200, height: 900});
        await page.goto(`file://${path}#pick`);
        await page.waitForSelector(".figure-pugh-ready .pugh-bottom");
        return {layout: await page.evaluate(() => document.documentElement.dataset.layout),
                bottom: await page.locator(".pugh-bottom").first().innerText()};
    },
    // A served deck blessed chapter by chapter from `first`, then sent.
    send: async (page, {url, first}) => {
        await page.setViewportSize({width: 1280, height: 720});
        await page.goto(`${url}#${first}`);
        await page.waitForFunction(() => document.documentElement.dataset.artifactStatus === "ready");
        const send = page.locator("[data-bless-send]");
        while (!/^Send (\\d+)\\/\\1$/.test(await send.textContent())) {
            await page.locator('[data-bless-key="bless"]:visible').click();
        }
        await send.click();
        await page.locator("[data-bless-pill]", {hasText: "sent"}).waitFor({timeout: 10000});
        return null;
    },
};
(async () => {
    const browser = await chromium.launch();
    try {
        const page = await browser.newPage();
        for await (const line of readline.createInterface({input: process.stdin})) {
            const request = JSON.parse(line);
            let reply;
            try {
                reply = {result: await actions[request.action](page, request)};
            } catch (error) {
                reply = {error: String((error && error.stack) || error)};
            }
            console.log(JSON.stringify(reply));
        }
    } finally {
        await browser.close();
    }
})();
"""


def _playwright() -> bool:
    return shutil.which("node") is not None and not subprocess.run(
        ["node", "-e", "require('playwright')"], capture_output=True).returncode


@pytest.fixture(scope="session")
def page():
    """One browser page for the worker's session: `page(action, **request)` runs one of PAGE's actions."""
    if not _playwright():
        pytest.skip("node with playwright is not installed")
    browser = subprocess.Popen(["node", "-e", PAGE], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               stderr=subprocess.DEVNULL, text=True)
    reader = ThreadPoolExecutor(1)

    def run(action: str, **request: str) -> object:
        browser.stdin.write(json.dumps({"action": action, **request}) + "\n")
        browser.stdin.flush()
        line = reader.submit(browser.stdout.readline).result(timeout=60)
        assert line, f"the browser exited with {browser.poll()}"
        reply = json.loads(line)
        assert "error" not in reply, reply["error"]
        return reply["result"]

    try:
        yield run
    finally:
        browser.stdin.close()
        try:
            browser.wait(timeout=30)
        finally:
            browser.kill()
            reader.shutdown(wait=False)


@pytest.mark.parametrize("profile", PROFILES)
def test_a_built_deck_opens_in_screens_and_names_options_by_letter_and_short_name(decks, page, profile):
    result, destination = decks[f"screens-{profile}"]
    assert result.returncode == 0, result.stderr
    shown = page("look", path=str(destination))
    assert shown["layout"] == "screens"
    assert "B · Short" in shown["bottom"]


def test_a_layout_the_notes_set_is_kept(decks):
    result, destination = decks["scrolling"]
    assert result.returncode == 0, result.stderr
    assert 'data-layout="scrolling"' in destination.read_text(encoding="utf-8")


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
        registerApplication: application => { calls.application = [application.id, application.actions]; },
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
    assert calls["local"] == {"application": [deck.BUNDLE_ID, []], "sink": None}
    assert (calls["namespace"], calls["id"]) == ("obsHtml.answers", "claude-artifact")
    assert calls["result"] == {"written": "answers.json", "version": "v2"}
    assert [list(files) for files in calls["published"]] == [["answers.json"]]
    assert json.loads(calls["published"][0]["answers.json"]) == PAYLOAD


def test_build_serve_wait_and_send_from_the_browser_print_the_answers(decks, page):
    built, artifact = decks["send"]
    assert built.returncode == 0, built.stderr
    served = subprocess.Popen([sys.executable, str(SCRIPTS / "deck.py"), "serve", str(artifact), "--wait",
                               "--timeout", "60"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        url = served.stdout.readline().strip()
        assert url.startswith("http://127.0.0.1:"), served.stderr.read()
        page("send", url=url, first="cache")
        out, err = served.communicate(timeout=30)
    finally:
        served.kill()
    assert served.returncode == 0, err
    printed = json.loads(out.strip().splitlines()[-1])
    assert [(item["chapter"], item["verdict"]) for item in printed["verdicts"]] == [("cache", "bless"), ("queue", "bless")]
    answers = artifact.parent / "answers.json"
    assert json.loads(answers.read_text(encoding="utf-8")) == printed
    shown = subprocess.run([sys.executable, str(SCRIPTS / "deck.py"), "answers", str(answers)],
                           capture_output=True, text=True)
    assert shown.stdout == "cache: bless\nqueue: bless\n", shown.stderr
