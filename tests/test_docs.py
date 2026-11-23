"""The documentation builds from docs.md with obs, and any obs warning fails it (README "Documentation")."""

from __future__ import annotations

import base64
import gzip
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "build_docs.py"
# The decision skill's worked example, the one note that asks for a verdict (its decks build from it).
WORKED_EXAMPLE = ROOT / "src" / "skills" / "decision" / "references" / "decision-deck.md"
NOTES = "src/skills/work-model/references/"
BOOK = ROOT / NOTES / "rules.md"
sys.path.insert(0, str(ROOT / "scripts"))
import build_docs  # noqa: E402
# Every build syncs the obs module into the checkout; the fixture `obs` (conftest.py) prepares it first,
# once at a time.


def build(*arguments: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(SCRIPT), *arguments], capture_output=True, text=True, env=env)


# The fake se's help, as the build's command-line chapter must show it; no tracked file outside
# tests/ holds its first line.
FAKE_HELP = "fake se help, the stand-in of the suite for the help of se\nusage: fake\n"
RUNTIME = ROOT / ".se" / ".runtime" / "runme-se"
CONF = ROOT / "RUNME.conf"


def fakes(folder: Path, log: Path) -> Path:
    """Fill ``folder``, put first on PATH, with a fake for every need of SE's RUNME.conf, so the build's
    RUNME installs nothing and reaches no network: ``se`` prints FAKE_HELP; each other command need
    that PATH lacks exits 0. Returns the file to set as BASH_ENV, which every non-interactive bash
    reads first: where bash runs RUNME's ``get se`` line, it writes RUNME's se need in its working
    folder, records that folder in ``log`` and ends that bash; every other bash goes on. Not a fake
    ``bash`` on PATH: Git for Windows' sh puts its own /usr/bin before PATH."""
    folder.mkdir()
    conf = CONF.read_text(encoding="utf-8")
    home = Path(os.environ.get("HOME", str(Path.home())))
    extra = [str(home / line.split()[1][2:]) for line in conf.splitlines() if line.startswith("path ~/")]
    lookup = os.pathsep.join([os.environ.get("PATH", ""), *extra])
    assert shutil.which("bash", path=lookup), "the build's RUNME needs a bash on PATH"

    def write(name: str, body: str) -> None:
        (folder / name).write_text(f"#!/bin/sh\n{body}", encoding="utf-8", newline="\n")
        (folder / name).chmod(0o755)

    write("se", f"printf '%s' '{FAKE_HELP}'\n")
    for name in sorted({line.split()[3] for line in conf.splitlines()
                        if line.startswith("need ") and line.split()[2] == "command"} - {"se", "bash"}):
        if not shutil.which(name, path=lookup):
            write(name, "exit 0\n")
    bash_env = folder.parent / "bash-env.sh"
    bash_env.write_text('if [ "$0 $*" = "scripts/bootstrap.sh --binary" ]; then\n'
                        f'  pwd >>"{log.as_posix()}"\n'
                        '  mkdir -p .se/.runtime && echo fake >.se/.runtime/runme-se\n'
                        '  exit 0\nfi\n', encoding="utf-8", newline="\n")
    return bash_env


@pytest.fixture(scope="module")
def built(tmp_path_factory, obs):
    """The suite's one build of SE's manifest, with the fakes first on PATH: its result, its folder (the
    page index.html, the Document docs.json, the fake bash's log bash.log), and the checkout's notes
    and RUNME need as they were before it."""
    folder = tmp_path_factory.mktemp("docs")
    log = folder / "bash.log"
    bash_env = fakes(folder / "bin", log)
    env = dict(os.environ, PATH=os.pathsep.join([str(folder / "bin"), os.environ.get("PATH", "")]),
               BASH_ENV=str(bash_env))
    before = snapshot()
    runtime = RUNTIME.read_bytes() if RUNTIME.exists() else None
    result = build("--destination", str(folder / "index.html"), "--document", str(folder / "docs.json"), env=env)
    return result, folder, before, runtime


def artifact_text(page: str) -> str:
    """The text of obs-html's artifact data island, decoded from its gzip and base64."""
    found = re.search(r'<script id="artifact-data"[^>]*data-encoding="gzip"[^>]*>([^<]*)</script>', page)
    return gzip.decompress(base64.b64decode(found[1])).decode("utf-8") if found else page


def files(pattern: str) -> list[Path]:
    """The checkout's files matching ``pattern``, outside .git and .se."""
    return [path for path in ROOT.rglob(pattern) if path.is_file()
            and path.relative_to(ROOT).parts[0] not in (".git", ".se")]


def nodes(items):
    for item in items:
        if isinstance(item, dict):
            yield item
            yield from nodes(item.get("children") or [])


def snapshot() -> dict[Path, bytes]:
    """The notes a build reads and could write: the manifest, the top-level notes and ``src``."""
    return {path: path.read_bytes() for path in [*ROOT.glob("*.md"), *(ROOT / "src").rglob("*")]
            if path.is_file()}


def test_documentation_builds_without_warnings(built):
    result, tmp_path, before, _ = built
    destination = tmp_path / "index.html"
    assert result.returncode == 0, result.stderr + result.stdout
    assert snapshot() == before
    assert destination.stat().st_size > 0
    # The page asks for no verdict: obs ships neither its bless nor its answers feature, whose canary
    # it writes only for an included feature (obs's adapters/html/spec/artifact-ui.md).
    page = destination.read_text(encoding="utf-8")
    assert 'id="canary-bless"' not in page
    assert 'id="canary-answers"' not in page
    # It opens in the reader's system theme: System is obs's default, so docs.md declares none.
    assert '<html lang="en" data-theme="system"' in page
    # It was the copy that changed: the worked example still asks, for the decks built from it.
    assert WORKED_EXAMPLE.read_text(encoding="utf-8").startswith("---\nobs: {bless: pending}\n---\n")
    # The rule book shows as one table of its rules, each rule its own note that rule links open.
    text = BOOK.read_text(encoding="utf-8")
    rules = re.findall(r"^### (\S+) (.+?)\s*$", text, re.MULTILINE)
    sections = re.findall(r"^## ([a-z0-9-]+: .+?)\s*$", text, re.MULTILINE)
    document = json.loads((tmp_path / "docs.json").read_text(encoding="utf-8"))
    titles = {chapter["title"] for chapter in document["chapters"]}
    assert {f"{rule} {name}" for rule, name in rules} <= titles
    chapter = next(chapter for chapter in document["chapters"] if chapter["title"] == "Rule book")
    tables = [node for node in nodes(chapter["content"]) if node["type"] == "bases"]
    assert len(tables) == 1
    view = tables[0]["attrs"]["spec"]["views"][0]
    assert view["groupBy"]["property"] == "section"
    assert view["obsHtml"]["groupOrder"] == sections
    assert view["obsHtml"]["detailFields"] == []
    headings = ["".join(text.get("text", "") for text in node["children"])
                for node in nodes(chapter["content"]) if node["type"] == "section"]
    assert not [heading for heading in headings if re.match(r"\S+-\d{3,} ", heading)]
    ids = {rule for rule, _ in rules}
    named = [link["href"] for link in document["links"]
             if re.search(r"rules\.md#[a-z0-9-]+-\d{3}|(?:^|/)[a-z0-9-]+-\d{3,}\.md$", link["href"])]
    assert named
    assert [href for href in named if href.removeprefix(NOTES).removesuffix(".md") not in ids
            or not href.startswith(NOTES)] == []


def test_a_destination_inside_the_manifest_folder_is_refused_before_any_copy(tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "docs.md").write_text("---\ntitle: t\n---\n", encoding="utf-8")
    inside = vault / "site" / "index.html"
    result = build("--source", str(vault / "docs.md"), "--destination", str(inside))
    assert result.returncode == 2, result.stderr + result.stdout
    assert str(inside) in result.stderr and str(vault) in result.stderr
    assert sorted(path.name for path in vault.iterdir()) == ["docs.md"]


def test_a_rule_note_that_would_overwrite_a_file_fails_the_build_naming_it(tmp_path, obs):
    vault = tmp_path / "vault"
    references = vault / NOTES
    references.mkdir(parents=True)
    (references / "rules.md").write_text(
        "# Rules\n\n## gen: everything\n\n### gen-001 A rule\n\nOne sentence.\n", encoding="utf-8")
    (references / "gen-001.md").write_text("mine\n", encoding="utf-8")
    (vault / "docs.md").write_text("---\ntitle: t\n---\n", encoding="utf-8")
    before = {path: path.read_bytes() for path in vault.rglob("*") if path.is_file()}
    result = build("--source", str(vault / "docs.md"), "--destination", str(tmp_path / "out.html"))
    assert result.returncode == 1, result.stderr + result.stdout
    assert f"{NOTES}gen-001.md" in result.stderr
    assert {path: path.read_bytes() for path in vault.rglob("*") if path.is_file()} == before


def test_a_link_to_a_rule_heading_opens_the_rule_note_and_others_stay(tmp_path):
    vault = tmp_path / "vault"
    references = vault / NOTES
    references.mkdir(parents=True)
    (references / "rules.md").write_text(
        "# Rules\n\n## gen: everything\n\nAbout it.\n\n### gen-001 A rule\n\nOne sentence.\n",
        encoding="utf-8")
    (vault / "README.md").write_text(
        f"[a]({NOTES}rules.md#gen-001-a-rule) [b]({NOTES}rules.md#gen-everything) [c]({NOTES}rules.md)\n",
        encoding="utf-8")
    build_docs.rule_table(vault)
    assert (vault / "README.md").read_text(encoding="utf-8") == (
        f"[a]({NOTES}gen-001.md) [b]({NOTES}rules.md#gen-everything) [c]({NOTES}rules.md)\n")
    assert (references / "gen-001.md").read_text(encoding="utf-8").endswith("\nOne sentence.\n")
    assert "```base" in (references / "rules.md").read_text(encoding="utf-8")


def test_no_note_of_the_copy_asks_for_a_verdict():
    assert build_docs.without_verdict("---\nobs: {bless: pending}\n---\n\n# T\n") == "\n# T\n"
    assert build_docs.without_verdict("---\ntitle: t\nobs: {bless: pending, k: 1}\n---\n") == (
        "---\ntitle: t\nobs: {k: 1}\n---\n")
    assert build_docs.without_verdict("---\nobs:\n  bless:\n    a: 1\n  k: 2\ntitle: t\n---\nb") == (
        "---\nobs:\n  k: 2\ntitle: t\n---\nb")
    assert build_docs.without_verdict("---\nobs:\n  bless: pending\n---\nb") == "b"
    unchanged = "---\ntitle: t\nobs: {other: 1}\n---\nb"
    assert build_docs.without_verdict(unchanged) == unchanged


def test_a_missing_note_fails_the_build(tmp_path, obs):
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "chapter.md").write_text("# Chapter\n\nSee [[no-such-note]].\n", encoding="utf-8")
    (vault / "docs.md").write_text("---\ntitle: t\n---\n\n- [[chapter|Chapter]]\n", encoding="utf-8")
    result = build("--source", str(vault / "docs.md"), "--destination", str(tmp_path / "out.html"))
    assert result.returncode == 1, result.stderr + result.stdout
    assert "no-such-note" in result.stderr


def test_a_paragraph_over_obs_default_limit_fails_the_build(tmp_path, obs):
    vault = tmp_path / "vault"
    vault.mkdir()
    long_paragraph = " ".join(["word"] * 100)  # six lines at 80 characters, over obs's default of five
    (vault / "chapter.md").write_text(f"# Chapter\n\n{long_paragraph}\n", encoding="utf-8")
    (vault / "docs.md").write_text("---\ntitle: t\n---\n\n- [[chapter|Chapter]]\n", encoding="utf-8")
    result = build("--source", str(vault / "docs.md"), "--destination", str(tmp_path / "out.html"))
    assert result.returncode == 1, result.stderr + result.stdout
    assert "long paragraph" in result.stderr


def test_the_command_line_chapter_is_runmes_help_at_build_time(built):
    result, folder, _, runtime = built
    assert result.returncode == 0, result.stderr + result.stdout
    first = FAKE_HELP.splitlines()[0]
    assert first in artifact_text((folder / "index.html").read_text(encoding="utf-8"))
    holders = []
    for path in files("*"):
        if path.relative_to(ROOT).parts[0] == "tests":
            continue
        try:
            if first in path.read_text(encoding="utf-8"):
                holders.append(path)
        except (UnicodeDecodeError, OSError):
            continue
    assert holders == []
    # RUNME ran its get se line once, in the build's copy, never in the checkout.
    ran = (folder / "bash.log").read_text(encoding="utf-8").splitlines()
    assert len(ran) == 1
    assert not Path(ran[0]).resolve().is_relative_to(ROOT.resolve())
    assert (RUNTIME.read_bytes() if RUNTIME.exists() else None) == runtime


# The rule book's chapter at 390 × 844, shown as pages as the documentation opens, then in the
# continuous view: per view its table's header labels, its scroller's widths, each rule row's and
# section caption's height with its one-line bound, and the text gen-001's row opens to.
RULE_BOOK_AT_PHONE = r"""
const {chromium} = require("playwright");
const measure = async (page, expected) => {
    await page.waitForFunction(count => {
        const rows = document.querySelectorAll("table tbody tr[data-row-key]");
        return rows.length === count && [...rows].every(row => row.getClientRects().length);
    }, expected);
    await page.evaluate(() => new Promise(done => requestAnimationFrame(() => requestAnimationFrame(done))));
    return await page.evaluate(() => {
        const table = document.querySelector("table:has(tbody tr[data-row-key])");
        const scroller = table.closest(".data-table-scroll");
        // One line: the larger of the first cell's line height and its disclosure's height, plus that
        // cell's vertical padding and borders, plus 1 px.
        const line = row => {
            const cell = row.cells[0], style = getComputedStyle(cell);
            const toggle = cell.querySelector(".disclosure-toggle");
            const px = name => parseFloat(style[name]) || 0;
            return {key: row.dataset.rowKey || row.innerText.trim(), height: row.getBoundingClientRect().height,
                    bound: Math.max(px("lineHeight"), toggle ? toggle.getBoundingClientRect().height : 0) +
                        px("paddingTop") + px("paddingBottom") + px("borderTopWidth") + px("borderBottomWidth") + 1};
        };
        return {labels: [...table.querySelectorAll("thead th")].map(th => th.querySelector("span").textContent.trim()),
                scrollWidth: scroller.scrollWidth, clientWidth: scroller.clientWidth,
                rows: [...table.querySelectorAll("tbody tr[data-row-key]")].map(line),
                captions: [...table.querySelectorAll("tr.data-table-group-row")].map(line)};
    });
};
const opened = async (page, rule) => {
    const row = page.locator("table tbody tr[data-row-key]").filter({hasText: rule}).first();
    await row.locator(".disclosure-toggle").first().click();
    const key = await row.getAttribute("data-row-key");
    const detail = page.locator(`tr.data-table-detail-row[data-detail-owner="${key}"]`);
    await detail.waitFor();
    const text = await detail.innerText();
    await row.locator(".disclosure-toggle").first().click();
    await detail.waitFor({state: "detached"});
    return text;
};
(async () => {
    const [path, title, rule, expected] = process.argv.slice(1);
    const browser = await chromium.launch();
    try {
        const page = await browser.newPage({viewport: {width: 390, height: 844}});
        await page.goto(`file://${path}`);
        await page.waitForFunction(() => document.documentElement.dataset.artifactStatus === "ready");
        const slug = await page.evaluate(title => JSON.parse(document.querySelector("[data-artifact-data]").textContent)
            .notes.find(note => note.title === title).slug, title);
        await page.evaluate(slug => obsArtifact.activateChapter(slug), slug);
        const views = {};
        views.pages = {paged: await page.evaluate(() => document.documentElement.classList.contains("paged-mode")),
                       ...await measure(page, +expected), opened: await opened(page, rule)};
        await page.locator("[data-pages-toggle]").evaluate(toggle => toggle.click());
        await page.waitForFunction(() => !document.documentElement.classList.contains("paged-mode"));
        views.continuous = {paged: false, ...await measure(page, +expected), opened: await opened(page, rule)};
        console.log(JSON.stringify(views));
    } finally {
        await browser.close();
    }
})();
"""


def test_each_rule_book_row_is_one_line_on_a_phone_in_both_views(built):
    """doc-004: at 390 px the rule book's table shows Rule and Name only, never scrolls sideways, keeps
    every rule row and section caption to one line, and opens a rule's row to its sentence."""
    if shutil.which("node") is None or subprocess.run(["node", "-e", "require('playwright')"],
                                                      capture_output=True).returncode:
        pytest.skip("node with playwright is not installed")
    result, folder, _, _ = built
    assert result.returncode == 0, result.stderr + result.stdout
    text = BOOK.read_text(encoding="utf-8")
    rules = re.findall(r"^### (\S+) ", text, re.MULTILINE)
    sentence = " ".join(text.split("\n### gen-001 ", 1)[1].split("\n\n", 2)[1].split())
    shown = subprocess.run(["node", "-e", RULE_BOOK_AT_PHONE, str(folder / "index.html"), "Rule book", "gen-001",
                            str(len(rules))], capture_output=True, text=True, timeout=120)
    assert shown.returncode == 0, shown.stderr
    views = json.loads(shown.stdout)
    assert views["pages"]["paged"] is True
    for name, view in views.items():
        assert view["labels"] == ["Rule", "Name"], name
        assert view["scrollWidth"] <= view["clientWidth"], name
        assert len(view["rows"]) == len(rules), name
        assert [row for row in view["rows"] + view["captions"] if row["height"] > row["bound"]] == [], name
        assert sentence in " ".join(view["opened"].split()), name


def test_the_readme_and_the_command_line_are_the_first_chapters():
    entries = re.findall(r"^- \[\[([^|\]]+)", (ROOT / "docs.md").read_text(encoding="utf-8"), re.MULTILINE)
    assert entries[:2] == ["README", "docs/command-line"]


def test_the_command_line_note_holds_the_one_command_fence():
    fence = re.compile(r"^\s*(`{3,}|~{3,})\s*cmd(\s+silent)?\s*$", re.MULTILINE)
    holders = sorted(path.relative_to(ROOT).as_posix() for path in files("*.md")
                     if fence.search(path.read_text(encoding="utf-8")))
    assert holders == ["docs/command-line.md"]


def test_the_docs_workflow_places_se_from_its_checkout_before_the_build():
    workflow = (ROOT / ".github" / "workflows" / "docs.yml").read_text(encoding="utf-8")
    job = re.search(r"(?ms)^  build:\n(.*?)(?=^  \w|\Z)", workflow)[1]
    steps = re.split(r"(?m)^      - ", job)[1:]

    def first(text: str) -> int:
        return next(index for index, step in enumerate(steps) if text in step)

    place = first("bash scripts/bootstrap.sh --binary")
    assert "working-directory" not in steps[place]
    assert first("actions/setup-go") < place and first("actions/cache") < place
    assert place < first("scripts/build_docs.py")


def test_no_script_passes_adapter_config():
    passing = sorted(path.relative_to(ROOT).as_posix() for path in (ROOT / "scripts").rglob("*.py")
                     if "--adapter-config" in path.read_text(encoding="utf-8"))
    assert passing == []


def test_obs_finds_the_installed_obs_html_component_and_its_serve_command(obs):
    adapter, refusal = build_docs.installed_adapter(obs)
    assert refusal == ""
    assert adapter["name"] == build_docs.ADAPTER == "obs-html" and adapter["serve"]
    assert Path(adapter["folder"]) != obs  # obs 10 holds no adapter in its own tree


def test_an_obs_html_installed_as_another_kind_is_refused_by_obs(obs, tmp_path, monkeypatch):
    monkeypatch.setenv("OBS_LOCAL_FOLDER", str(tmp_path))
    (tmp_path / "components.json").write_text(json.dumps({"components": [
        {"name": "obs-html", "kind": "style", "version": "1.0.0", "commit": "0" * 40}]}), encoding="utf-8")
    adapter, refusal = build_docs.installed_adapter(obs)
    assert adapter is None
    assert "--adapter: obs-html" in refusal and "not an adapter" in refusal


STYLE = "obs-html-style-generic"


def fake_components(monkeypatch, listing: list[str], installs: list[str]) -> list[str]:
    """Fake obs's machine folder as its listing ``listing``, the names of the installed components,
    with no process started: obs's finder reads obs-html from it, with the components obs-html
    requires (its default style) that the listing lacks; obs's install appends ``installs`` to it,
    as obs 10.3.2 installs obs-html with the components it requires. The returned list records each
    read and install."""
    calls: list[str] = []

    def installed(folder):
        calls.append("read")
        if "obs-html" not in listing:
            return None, "--adapter: obs-html: no adapter component 'obs-html' is installed"
        return {"name": "obs-html", "serve": ["serve"], "folder": "/components/obs-html",
                "missing": [name for name in (STYLE,) if name not in listing]}, ""

    def install(folder):
        calls.append("install")
        listing.extend(name for name in installs if name not in listing)
        return (0, f"installed {', '.join(installs)}") if installs else (1, "no release offers obs-html")

    monkeypatch.setattr(build_docs, "_READY", {})
    monkeypatch.setattr(build_docs, "installed_adapter", installed)
    monkeypatch.setattr(build_docs, "install_adapter", install)
    return calls


def test_a_build_installs_obs_html_with_its_style_on_an_empty_machine_folder(obs, monkeypatch, capsys):
    listing: list[str] = []
    calls = fake_components(monkeypatch, listing, ["obs-html", STYLE])
    adapter, refusal = build_docs.ready_adapter(obs)
    assert refusal == "" and adapter["name"] == "obs-html"
    assert listing == ["obs-html", STYLE]
    assert calls == ["read", "install", "read"]
    assert "installed obs's adapter component obs-html at /components/obs-html" in capsys.readouterr().err
    assert build_docs.ready_adapter(obs) == (adapter, "")
    assert calls == ["read", "install", "read"]  # asked once per process


def test_a_found_obs_html_without_its_style_installs_the_style(obs, monkeypatch, capsys):
    listing = ["obs-html"]
    calls = fake_components(monkeypatch, listing, [STYLE])
    assert build_docs.install_html(obs) == 0
    assert listing == ["obs-html", STYLE] and calls == ["read", "install", "read"]
    assert f"installed the components obs-html requires, {STYLE}" in capsys.readouterr().err


def test_a_found_obs_html_with_its_style_is_not_installed_again(obs, monkeypatch, capsys):
    calls = fake_components(monkeypatch, ["obs-html", STYLE], [])
    assert build_docs.install_html(obs) == 0
    assert calls == ["read"]
    assert capsys.readouterr().out == "build_docs: obs builds with obs-html at /components/obs-html\n"


def test_a_build_that_cannot_install_obs_html_fails_naming_the_command(obs, monkeypatch, capsys):
    fake_components(monkeypatch, [], [])
    assert build_docs.install_html(obs) == 1
    error = capsys.readouterr().err
    assert "`obs-components install obs-html`" in error and "no release offers obs-html" in error
    assert build_docs.obs_document(obs, ["--source", "unread.md"], "deck") == 1
    assert "deck: obs finds no adapter component obs-html" in capsys.readouterr().err


def test_a_missing_default_style_fails_naming_its_install_before_any_build(obs, monkeypatch, capsys):
    calls = fake_components(monkeypatch, ["obs-html"], [])
    assert build_docs.install_html(obs) == 1
    error = capsys.readouterr().err
    assert f"`obs-components install {STYLE}`" in error and f"without the components it requires, {STYLE}" in error
    assert build_docs.obs_document(obs, ["--source", "unread.md"], "deck") == 1
    assert calls == ["read", "install", "read", "read", "install", "read"]  # no build ran


def test_obs_htmls_unnamed_commit_fails_no_build_and_every_other_warning_does():
    output = ("obs-html: Warning: obs-html (src/obs_html/render.py): generation provenance: cannot resolve the "
              "generator commit, target version, or target commit. Build from a Git checkout\n"
              "obs-document: warning: one.md:3: long paragraph\nbuilt one.html\n")
    assert build_docs.obs_warnings(output) == ["obs-document: warning: one.md:3: long paragraph"]


def test_obs_document_runs_on_obs_environments_python_not_through_uv_run(obs):
    """uv run would set VIRTUAL_ENV, which obs hands on to obs-html's own uv run."""
    command = build_docs.obs_document_command(obs)
    assert command[1:] == ["-m", "obs.document"]
    assert Path(command[0]).is_file() and Path(command[0]).name.startswith("python")


def test_every_obs_build_runs_through_the_one_adapter():
    """deck.py and timeline.py build through build_docs's ADAPTER, installed where missing, and no
    script names an adapter of its own."""
    for script in ("deck.py", "timeline.py", "build_docs.py"):
        text = (ROOT / "scripts" / script).read_text(encoding="utf-8")
        assert '"--adapter", "' not in text, script
        assert "ready_adapter(" in text, script


def test_setup_and_ci_install_html_before_they_build():
    workflows = ROOT / ".github" / "workflows"
    for workflow, build_step in (("docs.yml", "scripts/build_docs.py --destination"),
                                 ("check.yml", "work_tickets.py suite")):
        text = (workflows / workflow).read_text(encoding="utf-8")
        assert text.index("build_docs.py --install-html") < text.index(build_step), workflow
    for setup in ("setup.sh", "setup.ps1"):
        assert "build_docs.py --install-html" in (ROOT / "scripts" / setup).read_text(encoding="utf-8")
