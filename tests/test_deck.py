"""The decision deck command (scripts/deck.py) and its Claude-app answers bundle (scripts/deck_answers.js).

The warning refusal, the answers summary and the bundle's ways out run on fakes; one end-to-end test
builds a deck with the real obs, serves it with `deck serve --wait`, sends from a browser and reads the
answers, and one opens a real deck on a fake of the Claude app's runtime that appears late, at phone width,
for the drafts obs-html keeps over a reload (a comment with no verdict among them) and how obs's notice
center tells the reader what Send did: its passing line under the top band, the bundle's entry for a
partial send, and obs's entry with the answers to copy where nothing was sent.
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
        if "--destination" in command:
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
    // A deck's chapters as obs-html opened them (no home page, no records): each slug and its bless
    // request's version.
    chapters: async (page, {path}) => {
        await page.goto(`file://${path}`);
        await page.waitForFunction(() => document.documentElement.dataset.artifactStatus === "ready");
        return await page.evaluate(() => JSON.parse(document.querySelector("[data-artifact-data]").textContent)
            .notes.filter(note => obsArtifact.isDocument(note) && note.slug !== "home")
            .map(note => [note.slug, note.bless?.version ?? null]));
    },
    // A served deck whose `chapters` are blessed one by one (a verdict never walks on), then sent: the
    // passing line it shows.
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
        return await page.locator("[data-brief-notice]:not([hidden])").innerText({timeout: 3000});
    },
    // A deck opened in a fresh tab of its own, where the Claude app's runtime is a fake that appears
    // only after the page loaded (`claude` is set on load): `files` and `comment` are what
    // artifact.publish and comments.sendToClaude do, ok or a rejection code. The page's own title
    // reads "Fallback", so a comment that names the deck's title took it from the deck.
    claude: async (page, {path, files, comment}) => {
        const context = await page.context().browser().newContext({viewport: {width: 390, height: 844}});
        try {
            const tab = await context.newPage();
            const warnings = [], obsWarnings = [];
            tab.on("console", message => {
                if (message.text().startsWith("se-answers:")) warnings.push(message.text());
                if (message.text().startsWith("obsHtml.answers: ")) obsWarnings.push(message.text());
            });
            await tab.addInitScript(({files, comment}) => {
                Object.defineProperty(Document.prototype, "title", {get: () => "Fallback", configurable: true});
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
            const after = () => document.querySelector("[data-bless-send]").nextElementSibling?.outerHTML ?? null;
            const beforeSend = await tab.evaluate(after);
            await tab.locator("[data-bless-send]").click();
            // Read while the passing line shows (it fades after seconds), or once obs's error entry is there.
            await tab.waitForFunction(() => document.querySelector("[data-brief-notice]:not([hidden])") ||
                document.querySelector('[data-notice="answers"]'), null, {timeout: 10000});
            const shown = await tab.evaluate(after => {
                const line = document.querySelector("[data-brief-notice]:not([hidden])");
                const box = line?.getBoundingClientRect(), band = document.querySelector("[data-top-band]").getBoundingClientRect();
                const entry = id => {
                    const item = document.querySelector(`[data-notice="${id}"]`);
                    return item && {severity: item.dataset.noticeSeverity, text: item.textContent};
                };
                return {line: line && {text: line.textContent, under: box.top >= band.bottom - 0.5,
                                       inside: box.left >= 0 && box.right <= innerWidth},
                        afterSend: eval(after)(), sideways: document.documentElement.scrollWidth > innerWidth,
                        seNotice: document.querySelector("[data-se-answers-notice]") !== null,
                        partly: entry("se-answers-partly"), answers: entry("answers"), send: entry("bless-send")};
            }, after.toString());
            return {restored, warnings, obsWarnings, beforeSend, shown, pill: await tab.locator("[data-bless-pill]").innerText(),
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


@pytest.mark.parametrize(("text", "settings"), [
    (None, {"artifact": {"reading": {"briefNoticeMilliseconds": deck.BRIEF_NOTICE_MILLISECONDS}}}),
    ('{"input": {"manifestFilename": "index.md"}, "artifact": {"reading": {"other": 1}}}',
     {"input": {"manifestFilename": "index.md"},
      "artifact": {"reading": {"other": 1, "briefNoticeMilliseconds": deck.BRIEF_NOTICE_MILLISECONDS}}}),
    ('{"artifact": {"reading": {"briefNoticeMilliseconds": 0}}, "x": true}',
     {"artifact": {"reading": {"briefNoticeMilliseconds": 0}}, "x": True}),
], ids=["no-file", "other-keys", "turned-off"])
def test_the_passing_line_merges_into_the_folders_settings_and_its_own_value_wins(text, settings):
    assert deck.BRIEF_NOTICE_MILLISECONDS == 4000
    assert json.loads(deck.brief_notice(text)) == settings


@pytest.mark.parametrize("text", ["{not json", "[]", '{"artifact": 1}', '{"artifact": {"reading": []}}'],
                         ids=["not-json", "no-object", "artifact", "reading"])
def test_settings_obs_would_refuse_are_left_for_obs_to_name(text):
    assert deck.brief_notice(text) == text


def test_the_send_decks_document_turns_the_passing_line_on(decks):
    built, artifact = decks["send"]
    assert built.returncode == 0, built.stderr
    document = json.loads(deck.document_path(artifact).read_text(encoding="utf-8"))
    assert document["projectConfig"]["settings"]["artifact"]["reading"]["briefNoticeMilliseconds"] == 4000


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


def test_a_veto_a_lift_and_a_datum_the_owner_changed_print_beside_the_old_fields():
    # The three fields obs v3.2.0's answers.schema.json added to figureChanges.
    figure = {"weights": {"places": 1}, "vetoes": ["C", "A"], "lifts": {"B": ["given", "gate1"]}, "datum": "B",
              "winner": "B"}
    payload = {"verdicts": [{"chapter": "record", "version": "0" * 64, "verdict": "decline",
                             "comment": "A and C break the budget.", "figures": {"record--figure-1": figure}}]}
    assert deck.summary(payload) == (
        "record: decline\n"
        "  comment: A and C break the budget.\n"
        "  record--figure-1 weights: places 1\n"
        "  record--figure-1 vetoes: A, C\n"
        "  record--figure-1 lifted vetoes of B: given, gate1\n"
        "  record--figure-1 datum: B\n"
        "  record--figure-1 winner with these changes: B")


@pytest.mark.parametrize("entry", [{"version": "0" * 64, "verdict": "bless"}, {"chapter": "one", "version": "0" * 64},
                                   {"chapter": "one", "version": "0" * 64, "comment": " "}],
                         ids=["no-chapter", "neither-verdict-nor-comment", "blank-comment"])
def test_an_entry_without_a_chapter_or_without_both_a_verdict_and_a_comment_is_malformed(entry):
    with pytest.raises(ValueError, match="verdict 1 has no chapter, or neither a verdict nor a comment"):
        deck.summary({"verdicts": [entry]})


def _chapters(chapters: list[dict]) -> list[dict]:
    """The chapters of a Document and their children, in order."""
    return [item for chapter in chapters for item in [chapter, *_chapters(chapter.get("children", []))]]


def _requests(artifact: Path) -> dict[str, dict]:
    """The bless request of each asking chapter in a built deck, from the Document `deck.py build` wrote beside it."""
    document = json.loads(deck.document_path(artifact).read_text(encoding="utf-8"))
    return {chapter["id"]: chapter["bless"] for chapter in _chapters(document["chapters"]) if chapter.get("bless")}


def test_build_writes_the_document_beside_the_deck_and_it_matches_the_built_chapters(decks, page):
    built, artifact = decks["send"]
    assert built.returncode == 0, built.stderr
    written = deck.document_path(artifact)
    assert written == artifact.parent / "deck.document.json"
    assert f"its Document {written}" in built.stdout
    document = json.loads(written.read_text(encoding="utf-8"))
    assert document["manifest"]["title"] == "Decisions"
    expected = [[chapter["id"], chapter.get("bless", {}).get("version")] for chapter in _chapters(document["chapters"])]
    assert [slug for slug, _ in expected] == ["cache", "queue"]
    assert all(version for _, version in expected)
    # The built deck's chapters as obs-html opens them, against the Document.
    assert page("chapters", path=str(artifact)) == expected


def test_a_refused_deck_leaves_no_document(decks):
    result, destination = decks["only-records"]
    assert result.returncode == 1, result.stderr
    assert not deck.document_path(destination).exists()


def test_the_bundle_data_is_the_decks_title_and_decisions_and_cannot_end_its_script():
    document = {"manifest": {"title": "A </script><!-- deck"}, "chapters": [
        {"id": "pick", "content": [{"type": "pugh", "children": []}], "children": []},
        {"id": "done", "content": [{"type": "paragraph", "children": []}], "children": []}]}
    text = deck._bundle(document)
    head, rest = text.split("\n", 1)
    assert rest == deck.BUNDLE.read_text(encoding="utf-8")
    assert "<" not in head
    data = json.loads(head.removeprefix("globalThis.seDeck = Object.freeze(").removesuffix(");"))
    assert data == {"title": "A </script><!-- deck", "decisions": ["pick"]}


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
const calls = {application: null, sink: null, published: [], comments: [], warnings: [], notices: [], created: 0};
globalThis.console = {...console, warn: message => calls.warnings.push(message)};
if (mode.deck) globalThis.seDeck = mode.deck;
globalThis.document = {body, title: "Deck", querySelector: () => null, addEventListener() {},
                       createElement: () => { calls.created += 1; return element(); }};
if (!mode.noNotices) globalThis.obsNotices = {post: entry => calls.notices.push(["post", entry]),
                                              reveal: id => calls.notices.push(["reveal", id]),
                                              remove: id => calls.notices.push(["remove", id])};
if (mode.served) globalThis.ObsHtmlAnswers = {server: () => "http://127.0.0.1:1/answers"};
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
    console.log(JSON.stringify({registered, application: calls.application, namespace: calls.sink.namespace,
                                id: calls.sink.id, name: calls.sink.name ?? null, result, error,
                                elements: calls.created + body.children.length, notices: calls.notices,
                                published: calls.published,
                                comments: calls.comments, warnings: calls.warnings}));
})();
"""


def _bundle(**mode: object) -> dict:
    if shutil.which("node") is None:
        pytest.skip("node is not installed")
    result = subprocess.run(["node", "-e", BUNDLE_DOUBLE, str(SCRIPTS / "deck_answers.js"), json.dumps(PAYLOAD),
                             json.dumps(mode)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def _send_warnings(calls: dict) -> list[str]:
    """The console warnings of the send itself, without the one of a double that carries no deck data."""
    return [warning for warning in calls["warnings"] if "readable deck data" not in warning]


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
    assert calls["name"] == "Claude"
    assert (calls["elements"], calls["notices"], _send_warnings(calls)) == (0, [["remove", "se-answers-partly"]], [])


def test_where_obs_html_serve_served_the_page_the_sink_names_no_reader():
    calls = _bundle(files="ok", comment="ok", served=True)
    assert calls["id"] == "claude-artifact" and calls["name"] is None


def test_the_bundle_takes_the_title_and_the_open_decisions_from_the_decks_data():
    calls = _bundle(files="ok", comment="ok", deck={"title": "Storage", "decisions": ["record", "open"]})
    assert calls["warnings"] == []
    [comment] = calls["comments"]
    lines = comment["text"].splitlines()
    assert lines[0] == 'Answers from the decision deck "Storage" (se-answers):'
    assert lines[5] == "- open: no answer"
    assert "- record: no answer" not in lines


@pytest.mark.parametrize("data", [None, {"title": "Storage"}, {"title": 1, "decisions": []}],
                         ids=["none", "no-decisions", "no-title"])
def test_without_readable_deck_data_the_bundle_says_so_once_and_still_sends(data):
    calls = _bundle(files="ok", comment="ok", **({"deck": data} if data else {}))
    [warning] = calls["warnings"]
    assert warning.startswith("se-answers: this deck carries no readable deck data (globalThis.seDeck)")
    assert calls["result"]["ways"] == ["answers.json", "comment"]
    [comment] = calls["comments"]
    assert comment["text"].splitlines()[0] == 'Answers from the decision deck "Deck" (se-answers):'
    assert "no answer" not in comment["text"]


PARTLY = {
    "comment": {"id": "se-answers-partly", "severity": "warning", "title": "No message to Claude",
                "details": ["Your answers are saved with this page, where Claude reads them, but the message to "
                            "Claude did not go through. If Claude does not answer, say in the chat that you sent them."]},
    "answers.json": {"id": "se-answers-partly", "severity": "warning", "title": "Not saved with the page",
                     "details": ["Claude got your answers as a message, but they could not be saved with this page."]},
}


@pytest.mark.parametrize(("files", "comment", "failed"), [("capability_disabled", "ok", "answers.json"),
                                                          ("ok", "claude_unavailable", "comment")])
def test_a_send_where_one_way_failed_posts_one_plain_warning(files, comment, failed):
    calls = _bundle(files=files, comment=comment)
    assert calls["error"] is None
    code = files if failed == "answers.json" else comment
    assert calls["result"]["failed"] == {failed: code}
    assert calls["result"]["ways"] == [way for way in ("answers.json", "comment") if way != failed]
    revealed = [["reveal", "se-answers-partly"]] if failed == "comment" else []
    assert calls["notices"] == [["post", PARTLY[failed]], *revealed]
    text = json.dumps(PARTLY[failed])
    assert "answers.json" not in text and code not in text
    [warning] = _send_warnings(calls)
    assert warning.startswith("se-answers: ") and code in warning
    assert calls["elements"] == 0


def test_a_partial_send_without_a_notice_center_still_resolves():
    calls = _bundle(files="ok", comment="claude_unavailable", noNotices=True)
    assert calls["error"] is None and calls["result"]["ways"] == ["answers.json"]


def test_when_both_ways_fail_it_rejects_in_plain_words_and_the_codes_go_to_the_console():
    calls = _bundle(files="capability_disabled", comment="claude_unavailable")
    assert calls["result"] is None
    assert calls["error"]["code"] == "not_sent"
    assert calls["error"]["failed"] == {"answers.json": "capability_disabled", "comment": "claude_unavailable"}
    message = calls["error"]["message"]
    assert message == "nothing reached Claude; copy your answers and paste them into the chat"
    [warning] = _send_warnings(calls)
    assert warning.startswith("se-answers: ") and "capability_disabled" in warning and "claude_unavailable" in warning
    assert calls["notices"] == [["remove", "se-answers-partly"]]
    assert calls["elements"] == 0


def test_a_claude_runtime_that_appears_after_the_first_run_takes_the_answers():
    calls = _bundle(files="ok", comment="ok", late=True)
    assert calls["registered"]
    assert calls["result"]["ways"] == ["answers.json", "comment"]


def test_without_claude_or_a_server_send_rejects_so_the_text_to_copy_shows():
    calls = _bundle(files="ok", comment="ok", late=True, never=True)
    assert calls["registered"] and calls["result"] is None
    assert "sending is not available here" in calls["error"]["message"]


@pytest.mark.parametrize("files, comment", [("ok", "ok"), ("ok", "claude_unavailable"), ("capability_disabled", "ok"),
                                           ("capability_disabled", "claude_unavailable")])
def test_a_deck_keeps_the_draft_over_a_reload_and_sends_through_a_late_claude(decks, page, files, comment):
    built, artifact = decks["send"]
    assert built.returncode == 0, built.stderr
    result = page("claude", path=str(artifact), files=files, comment=comment)
    # The bundle read the deck's data; a partial or failed send warns of its own.
    assert not [warning for warning in result["warnings"] if "readable deck data" in warning]
    assert result["restored"] == {"cache": {"verdict": "decline", "comment": "Too slow."}, "queue": {"comment": "Later."}}
    shown = result["shown"]
    # The bundle draws nothing on the page: nothing after Send, before or after it, and no page scrolls sideways.
    assert (shown["afterSend"], shown["seNotice"], shown["sideways"]) == (result["beforeSend"], False, False)
    if "ok" in (files, comment):
        assert shown["line"] == {"text": "Sent to Claude.", "under": True, "inside": True}
        assert "sent" in result["pill"].lower()
        if (files, comment) == ("ok", "ok"):
            assert shown["partly"] is None
        else:
            assert shown["partly"]["severity"] == "warning"
            assert "answers.json" not in shown["partly"]["text"]
    else:
        assert shown["line"] is None and shown["partly"] is None
        version = {slug: request["version"] for slug, request in _requests(artifact).items()}
        assert "They did not reach Claude. Copy the answers and give them to Claude." in shown["answers"]["text"]
        assert shown["send"]["severity"] == "error"
        assert ("1 verdict and 2 comments were not sent. Your verdicts and comments are kept in the deck; send again."
                in shown["send"]["text"])
        for text in (shown["answers"]["text"], shown["send"]["text"]):
            assert not [word for word in ("claude-artifact", "obsHtml", "sink", "paste them into the chat") if word in text]
        # The add-on's own message reaches the console, in obs's one warning.
        [warning] = result["obsWarnings"]
        assert warning.startswith("obsHtml.answers: registered sink claude-artifact: send failed (nothing reached "
                                  "Claude; copy your answers and paste them into the chat)")
        assert json.dumps({"chapter": "cache", "version": version["cache"], "verdict": "decline",
                           "comment": "Too slow."}, indent=2).splitlines()[1] in shown["answers"]["text"]
        assert "sent" not in result["pill"].lower()
    if "ok" in (files, comment):
        assert result["obsWarnings"] == []
    if comment == "ok":
        [sent] = result["calls"]["comments"]
        assert sent["text"].splitlines()[0] == 'Answers from the decision deck "Decisions" (se-answers):'
        assert {"- cache: decline: Too slow.", "- queue: comment: Later."} <= set(sent["text"].splitlines())


def test_build_serve_wait_and_send_from_the_browser_print_the_answers(decks, page):
    built, artifact = decks["send"]
    assert built.returncode == 0, built.stderr
    served = subprocess.Popen([sys.executable, str(SCRIPTS / "deck.py"), "serve", str(artifact), "--wait",
                               "--timeout", "60"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        url = served.stdout.readline().strip()
        assert url.startswith("http://127.0.0.1:"), served.stderr.read()
        assert page("send", url=url, chapters=["cache", "queue"]) == "Sent."
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
