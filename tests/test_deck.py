"""The decision deck command (scripts/deck.py) and its Claude-app answers bundle (scripts/deck_answers.js).

The warning refusal, the answers summary and the bundle's ways out run on fakes; one end-to-end test
builds a deck with the real obs, serves it with `deck serve --wait`, sends from a browser and reads the
answers, and one opens a real deck on a fake of the Claude app's runtime that appears late, for the drafts
obs-html keeps over a reload (a comment with no verdict among them) and the notice beside Send.
Every deck the tests build with the real obs is built once per session, all at once (`decks`), and the
browser tests share one page per worker (`page`).
"""

from __future__ import annotations

import base64
import gzip
import json
import re
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

NOTE = ("---\nobs: {bless: pending}\n---\n# %s\n\n## Current situation\n\nThis is one case of how %s is chosen.\n"
        "\n## The problem\n\nIt is chosen by hand.\n")


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


EXAMPLE = ROOT / "src" / "skills" / "decision" / "references" / "decision-deck.md"
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
    "no-situation": ({"bare": NOTE.replace("## Current situation\n\n", "") % ("Bare", "a bare") + PUGH}, None),
    "no-problem": ({"bare": NOTE.replace("\n## The problem\n\n", "\n") % ("Bare", "a bare") + PUGH}, None),
    "after-the-fence": ({"late": (NOTE % ("Late", "a late")).split("\n## Current")[0] + PUGH
                         + "\n## Current situation\n\nToday.\n\n## The problem\n\nIt hurts.\n"}, None),
    "worked-example": ({"decision-deck": EXAMPLE.read_text(encoding="utf-8")}, None),
    # Option A names neither its success nor the reason for its mark; B, the datum, needs no reasons.
    "unargued": ({"bare": NOTE % ("Bare", "a bare") + PUGH.replace("wins: Known.,", "wins: Known., success: Kept.,")},
                 None),
}


def _deck(folder: Path, destination: Path) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(SCRIPTS / "deck.py"), "build", str(folder),
                           "--destination", str(destination)], capture_output=True, text=True)


@pytest.fixture(scope="session")
def decks(tmp_path_factory, obs) -> dict[str, tuple[subprocess.CompletedProcess, Path]]:
    """Each of DECKS built once with `deck.py build`, all at once: its build and its destination."""
    def built(name: str) -> tuple[subprocess.CompletedProcess, Path]:
        directory = directories[name]
        notes, manifest = DECKS[name]
        destination = directory / "deck.html"
        return _deck(_folder(directory, notes, manifest), destination), destination

    directories = {name: tmp_path_factory.mktemp(name) for name in DECKS}  # mktemp is not thread-safe.
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


@pytest.mark.parametrize("name", ["no-situation", "no-problem", "after-the-fence"])
def test_build_refuses_a_decision_that_does_not_explain_the_problem_before_its_options(decks, name):
    result, destination = decks[name]
    assert result.returncode == 1, result.stderr
    note = "late" if name == "after-the-fence" else "bare"
    assert f"decision(s) {note} do not explain" in result.stderr
    assert "`## Current situation` and `## The problem` before the `pugh` fence" in result.stderr
    assert not destination.exists()


def test_the_worked_example_builds_without_a_warning(decks):
    result, destination = decks["worked-example"]
    assert result.returncode == 0, result.stderr
    assert destination.exists()
    assert "warning" not in result.stderr


def test_build_warns_of_an_option_without_success_or_a_mark_without_its_reason(decks):
    result, destination = decks["unargued"]
    assert result.returncode == 0, result.stderr
    assert destination.exists()
    assert result.stderr.splitlines() == [
        "deck: warning: bare, option A: no `success`, its success criterion",
        "deck: warning: bare, option A: the mark on `cost` has no `because`, its reason",
    ]


PAGE = """
const {chromium} = require("playwright");
const readline = require("readline");
const actions = {
    // A deck opened at its pick chapter: its layout and the pugh figure's option rows.
    look: async (page, {path}) => {
        await page.setViewportSize({width: 1200, height: 900});
        await page.goto(`file://${path}#pick`);
        await page.waitForSelector('.figure-pugh-ready [data-pugh-part="options"]');
        return {layout: await page.evaluate(() => document.documentElement.dataset.layout),
                options: await page.locator('.figure-pugh-ready [data-pugh-option] summary').allInnerTexts()};
    },
    // A served deck whose `chapters` are blessed one by one (a verdict never walks on), then sent.
    send: async (page, {url, chapters}) => {
        await page.setViewportSize({width: 1280, height: 720});
        await page.goto(url);
        await page.waitForFunction(() => document.documentElement.dataset.artifactStatus === "ready");
        for (const chapter of chapters) {
            await page.evaluate(name => obsArtifact.activateChapter(name), chapter);
            await page.locator('[data-bless-key="bless"]:visible').click();
        }
        const send = page.locator("[data-bless-send]");
        await page.waitForFunction(() => /^Send (\\d+)\\/\\1$/.test(document.querySelector("[data-bless-send]").textContent));
        await send.click();
        await page.locator("[data-bless-pill]", {hasText: "sent"}).waitFor({timeout: 10000});
        return null;
    },
    // A deck opened in a fresh tab of its own, where the Claude app's runtime is a fake that appears
    // only after the page loaded (`claude` is set on load): `files` and `comment` are what
    // artifact.publish and comments.sendToClaude do, ok or a rejection code.
    claude: async (page, {path, files, comment}) => {
        const context = await page.context().browser().newContext();
        try {
            const tab = await context.newPage();
            await tab.addInitScript(({files, comment}) => {
                const refusal = code => Object.assign(new Error(code), {code});
                globalThis.seCalls = {published: [], comments: []};
                addEventListener("load", () => { globalThis.claude = {use: async name => (name === "artifact" ? {
                    publish: async written => { if (files !== "ok") throw refusal(files); seCalls.published.push(written); return {version: "v2"}; },
                } : name === "comments" ? {
                    anchorFor: async () => ({kind: "element"}),
                    sendToClaude: async target => { if (comment !== "ok") throw refusal(comment); seCalls.comments.push(target); return {threadId: "t1"}; },
                } : null)}; });
            }, {files, comment});
            await tab.goto(`file://${path}#cache`);
            await tab.waitForFunction(() => document.documentElement.dataset.artifactStatus === "ready");
            await tab.locator('[data-bless-key="decline"]:visible').click();
            await tab.locator("[data-bless-comment]").fill("Too slow.");
            await tab.locator("[data-bless-comment]").press("Enter");
            // A comment with no verdict, through obs-html's Comment key.
            await tab.evaluate(() => obsArtifact.activateChapter("queue"));
            await tab.locator("[data-bless-comment-key]:visible").click();
            await tab.locator("[data-bless-comment]").fill("Later.");
            await tab.locator("[data-bless-comment]").press("Escape");
            // Reload: obs-html brings every chapter's draft back by itself (se's bundle restores none).
            await tab.reload();
            await tab.waitForFunction(() => document.documentElement.dataset.artifactStatus === "ready");
            await tab.evaluate(() => obsArtifact.activateChapter("cache"));
            await tab.waitForFunction(() => obsBless.verdicts().cache?.comment === "Too slow." &&
                obsBless.verdicts().queue?.comment === "Later.", null, {timeout: 10000});
            const restored = await tab.evaluate(() => obsBless.verdicts());
            await tab.locator("[data-bless-send]").click();
            await tab.locator("[data-se-answers-notice]").waitFor();
            return {restored, pill: await tab.locator("[data-bless-pill]").innerText(),
                    notice: await tab.evaluate(() => {
                        const box = document.querySelector("[data-se-answers-notice]");
                        return {state: box.dataset.seAnswersNotice, besideSend: box.previousElementSibling?.matches("[data-bless-send]"),
                                message: box.querySelector("p").textContent, text: box.querySelector("textarea")?.value ?? null};
                    }),
                    calls: await tab.evaluate(() => seCalls)};
        } finally {
            await context.close();
        }
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

    def run(action: str, **request: object) -> object:
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
    assert any(option.startswith("B · Short") for option in shown["options"]), shown["options"]


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
    {"chapter": "swipe", "version": "1" * 64, "verdict": "bless"},
    # obs 2.1: a Bless may carry a comment, and a comment may stand with no verdict.
    {"chapter": "keep", "version": "2" * 64, "verdict": "bless", "comment": "Fine as it is."},
    {"chapter": "later", "version": "3" * 64, "comment": "Only a thought."}]}


def test_answers_parse_into_the_summary():
    assert deck.summary(PAYLOAD) == (
        "record: pick C (figure record--figure-1)\n"
        "  comment: C needs no second place.\n"
        "  record--figure-1 weights: places 1\n"
        "  record--figure-1 marks of B: places -1\n"
        "  record--figure-1 ruling on A: could, tripwire: a second place\n"
        "  record--figure-1 winner with these changes: B\n"
        "swipe: bless\n"
        "keep: bless\n"
        "  comment: Fine as it is.\n"
        "later: comment\n"
        "  comment: Only a thought.")
    with pytest.raises(ValueError, match="verdicts list"):
        deck.summary({"answers": []})


@pytest.mark.parametrize("entry", [{"version": "0" * 64, "verdict": "bless"}, {"chapter": "one", "version": "0" * 64},
                                   {"chapter": "one", "version": "0" * 64, "comment": " "}],
                         ids=["no-chapter", "neither-verdict-nor-comment", "blank-comment"])
def test_an_entry_without_a_chapter_or_without_both_a_verdict_and_a_comment_is_malformed(entry):
    with pytest.raises(ValueError, match="verdict 1 has no chapter, or neither a verdict nor a comment"):
        deck.summary({"verdicts": [entry]})


def _requests(artifact: Path) -> dict[str, dict]:
    """The bless request of each asking chapter in a built deck, from its embedded data (base64 of gzip)."""
    embedded = re.search(r"<[^<>]*\bdata-artifact-data\b[^<>]*>([^<]*)<", artifact.read_text(encoding="utf-8"))
    data = json.loads(gzip.decompress(base64.b64decode("".join(embedded[1].split()))))
    return {note["slug"]: note["bless"] for note in data["notes"] if note.get("bless")}


def test_answers_in_the_obs_2_1_shape_print_and_record_through_deck_answers(decks, tmp_path):
    # A Bless with a comment and a comment with no verdict, at the built deck's own chapter versions.
    built, artifact = decks["send"]
    assert built.returncode == 0, built.stderr
    version = {slug: request["version"] for slug, request in _requests(artifact).items()}
    answers = tmp_path / "answers.json"
    answers.write_text(json.dumps({"verdicts": [
        {"chapter": "cache", "version": version["cache"], "verdict": "bless", "comment": "Fine as it is."},
        {"chapter": "queue", "version": version["queue"], "comment": "Only a thought."}]}), encoding="utf-8")
    record = tmp_path / "record.html"
    shown = subprocess.run([sys.executable, str(SCRIPTS / "deck.py"), "answers", str(answers),
                            "--record", str(artifact.parent / "decisions"), "--destination", str(record)],
                           capture_output=True, text=True)
    assert shown.returncode == 0, shown.stderr
    assert shown.stdout.splitlines()[:4] == ["cache: bless", "  comment: Fine as it is.", "queue: comment",
                                             "  comment: Only a thought."]
    recorded = _requests(record)
    assert recorded["cache"]["answer"]["comment"] == "Fine as it is."
    assert "answer" not in recorded["queue"] and recorded["queue"]["comment"]["comment"] == "Only a thought."


# The answers bundle on a fake of obs-html and of the Claude app's runtime, one case per run: the
# runtime's modes are what `artifact.publish` and `comments.sendToClaude` do (ok, or a rejection code).
BUNDLE_DOUBLE = """
const bundle = require("fs").readFileSync(process.argv[1], "utf8");
const [payload, mode] = [JSON.parse(process.argv[2]), JSON.parse(process.argv[3])];
const element = () => {
    const node = {dataset: {}, style: {}, children: [], setAttribute() {}, addEventListener() {},
                  after() {}, prepend: child => node.children.unshift(child),
                  replaceChildren: (...children) => { node.children = children; }};
    return node;
};
const body = element();
const calls = {application: null, sink: null, published: [], comments: []};
globalThis.document = {body, title: "Deck", querySelector: () => null, addEventListener() {},
                       createElement: element};
globalThis.obsArtifact = {
    registerApplication: application => { calls.application = [application.id, application.actions]; },
    trustedExtension: namespace => ({register: sink => { calls.sink = {namespace, ...sink}; }}),
};
const refusal = code => Object.assign(new Error(`refused: ${code}`), {code});
const claude = {use: async name => {
    if (name === "artifact") return {publish: async files => {
        if (mode.files !== "ok") throw refusal(mode.files);
        calls.published.push(files);
        return {version: "v2"};
    }};
    if (name === "comments") return {
        anchorFor: async node => ({element: node === body ? "body" : "other"}),
        sendToClaude: async target => {
            if (mode.comment !== "ok") throw refusal(mode.comment);
            calls.comments.push(target);
            return {threadId: "t1", commentId: "c1"};
        },
    };
    return null;
}};
if (!mode.late) globalThis.claude = claude;
eval(bundle);
(async () => {
    const registered = calls.sink !== null;  // Registered at the first run, with or without claude.
    if (mode.late && !mode.never) globalThis.claude = claude;
    let result = null, error = null;
    try { result = await calls.sink.send(payload); }
    catch (failure) { error = {message: failure.message, code: failure.code, failed: failure.failed}; }
    const shown = body.children.map(box => ({state: box.dataset.seAnswersNotice,
        text: box.children.map(child => child.textContent ?? child.value)}));
    console.log(JSON.stringify({registered, application: calls.application, namespace: calls.sink.namespace,
                                id: calls.sink.id, result, error, shown, published: calls.published,
                                comments: calls.comments}));
})();
"""


def _bundle(**mode: object) -> dict:
    if shutil.which("node") is None:
        pytest.skip("node is not installed")
    result = subprocess.run(["node", "-e", BUNDLE_DOUBLE, str(SCRIPTS / "deck_answers.js"), json.dumps(PAYLOAD),
                             json.dumps(mode)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_the_bundle_saves_answers_json_and_sends_the_comment_to_claude():
    calls = _bundle(files="ok", comment="ok")
    assert calls["application"] == [deck.BUNDLE_ID, []]
    assert (calls["namespace"], calls["id"]) == ("obsHtml.answers", "claude-artifact")
    assert calls["result"] == {"ways": ["answers.json", "comment"], "failed": {}, "written": "answers.json",
                               "version": "v2", "comment": {"threadId": "t1"}}
    assert [list(files) for files in calls["published"]] == [["answers.json"]]
    assert json.loads(calls["published"][0]["answers.json"]) == PAYLOAD
    [comment] = calls["comments"]
    assert comment["anchor"] == {"element": "body"}
    assert comment["text"].splitlines()[1:5] == ["- record: pick C: C needs no second place.", "- swipe: bless",
                                                 "- keep: bless: Fine as it is.", "- later: comment: Only a thought."]
    assert json.loads(comment["text"].split("answers.json:\n", 1)[1]) == PAYLOAD
    assert len(comment["text"].encode()) <= 4096
    assert calls["shown"] == [{"state": "sent", "text": ["Sent: answers.json saved and comment sent to Claude."]}]


def test_a_refused_files_form_still_reaches_claude_through_the_comment():
    calls = _bundle(files="capability_disabled", comment="ok")
    assert calls["error"] is None
    assert calls["result"] == {"ways": ["comment"], "failed": {"answers.json": "capability_disabled"},
                               "comment": {"threadId": "t1"}}
    assert calls["shown"][0]["text"] == ["Sent: comment sent to Claude. Not saved as answers.json (capability_disabled)."]


def test_when_both_ways_fail_the_notice_says_so_with_the_codes_and_the_answers_to_copy():
    calls = _bundle(files="capability_disabled", comment="claude_unavailable")
    assert calls["result"] is None
    assert calls["error"]["code"] == "not_sent"
    assert calls["error"]["failed"] == {"answers.json": "capability_disabled", "comment": "claude_unavailable"}
    [shown] = calls["shown"]
    message, text = shown["text"]
    assert shown["state"] == "failed"
    assert message.startswith("Not sent: saving answers.json failed with capability_disabled")
    assert "claude_unavailable" in message and "Sent:" not in message
    assert json.loads(text) == PAYLOAD


def test_a_claude_runtime_that_appears_after_the_first_run_takes_the_answers():
    calls = _bundle(files="ok", comment="ok", late=True)
    assert calls["registered"]
    assert calls["result"]["ways"] == ["answers.json", "comment"]


def test_without_claude_or_a_server_send_rejects_so_the_text_to_copy_shows():
    calls = _bundle(files="ok", comment="ok", late=True, never=True)
    assert calls["registered"] and calls["result"] is None
    assert "sending is not available here" in calls["error"]["message"]


@pytest.mark.parametrize("files, comment", [("capability_disabled", "ok"), ("capability_disabled", "claude_unavailable")])
def test_a_deck_keeps_the_draft_over_a_reload_and_sends_through_a_late_claude(decks, page, files, comment):
    built, artifact = decks["send"]
    assert built.returncode == 0, built.stderr
    shown = page("claude", path=str(artifact), files=files, comment=comment)
    assert shown["restored"] == {"cache": {"verdict": "decline", "comment": "Too slow."}, "queue": {"comment": "Later."}}
    if comment == "ok":
        assert shown["notice"] == {"state": "sent", "besideSend": True, "text": None,
                                   "message": "Sent: comment sent to Claude. Not saved as answers.json (capability_disabled)."}
        assert "sent" in shown["pill"].lower()
        [sent] = shown["calls"]["comments"]
        assert {"- cache: decline: Too slow.", "- queue: comment: Later."} <= set(sent["text"].splitlines())
    else:
        notice = shown["notice"]
        assert (notice["state"], notice["besideSend"]) == ("failed", True)
        assert "capability_disabled" in notice["message"] and "claude_unavailable" in notice["message"]
        version = {slug: request["version"] for slug, request in _requests(artifact).items()}
        assert json.loads(notice["text"])["verdicts"] == [
            {"chapter": "cache", "version": version["cache"], "verdict": "decline", "comment": "Too slow."},
            {"chapter": "queue", "version": version["queue"], "comment": "Later."}]
        assert "sent" not in shown["pill"].lower()


def test_build_serve_wait_and_send_from_the_browser_print_the_answers(decks, page):
    built, artifact = decks["send"]
    assert built.returncode == 0, built.stderr
    served = subprocess.Popen([sys.executable, str(SCRIPTS / "deck.py"), "serve", str(artifact), "--wait",
                               "--timeout", "60"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        url = served.stdout.readline().strip()
        assert url.startswith("http://127.0.0.1:"), served.stderr.read()
        page("send", url=url, chapters=["cache", "queue"])
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
