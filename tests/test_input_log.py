"""Input log (scripts/input_log.py): the adapter's person rule, the plan's names, texts and index,
that nothing is rewritten, images only on request, writing only into an ignored folder, the
privacy of the output, its parity with the transcript reader, and that nothing calls the module."""

import ast
import base64
import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest

import fake_git
import git_door

PROJECT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "transcripts"
STAMP = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")
PNG = b"\x89PNG\r\n\x1a\n" + bytes(range(32))


def load(name: str):
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, PROJECT / "scripts" / f"{name}.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return sys.modules[name]


log = load("input_log")


def user(text, time="2026-01-01T10:00:00Z", **extra):
    record = {"type": "user", "message": {"role": "user", "content": text}, **extra}
    if time is not None:
        record["timestamp"] = time
    return json.dumps(record)


def queued(prompt, time="2026-01-01T10:00:40Z", mode="prompt", origin="human"):
    attachment = {"type": "queued_command", "commandMode": mode, "prompt": prompt}
    if origin is not None:
        attachment["origin"] = {"kind": origin}
    return json.dumps({"type": "attachment", "timestamp": time, "attachment": attachment})


def image(data: bytes = PNG, media_type="image/png"):
    return {"type": "image", "source": {"type": "base64", "media_type": media_type,
                                        "data": base64.b64encode(data).decode("ascii")}}


MIXED = [
    user("Please list the files for alice.", "2026-01-01T10:00:00Z"),
    user("<command-name>/clear</command-name>", "2026-01-01T10:00:01Z"),
    user("A meta note.", "2026-01-01T10:00:02Z", isMeta=True),
    json.dumps({"type": "user", "timestamp": "2026-01-01T10:00:03Z", "message": {
        "role": "user", "content": [{"type": "tool_result", "tool_use_id": "c1", "content": "ok"}]}}),
    user("Prompt for a sub-agent.", "2026-01-01T10:00:04Z", isSidechain=True),
    user("This session is being continued.", "2026-01-01T10:00:05Z", isCompactSummary=True,
         isVisibleInTranscriptOnly=True),
    user([{"type": "text", "text": "[Request interrupted by user]"}], "2026-01-01T10:00:06Z"),
    queued("A peer's message.", "2026-01-01T10:00:07Z", origin="peer"),
    queued("<task-notification>done</task-notification>", "2026-01-01T10:00:08Z",
           mode="task-notification"),
    "not json at all",
    "[1, 2]",
    user("Thanks, see example.com for the rest.", "2026-01-02T09:30:00.123456Z"),
]


def write_transcript(folder: Path, lines, name="session.jsonl") -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    path.write_bytes(("\n".join(lines) + "\n").encode("utf-8"))
    return path


def ignoring_checkout(path: Path) -> Path:
    fake_git.init(path)
    (path / ".gitignore").write_bytes(b".se/\n")
    return path


def folder_of(repo: Path) -> Path:
    return repo / ".se" / "input"


def snapshot(repo: Path) -> dict[str, bytes]:
    folder = folder_of(repo)
    return {p.name: p.read_bytes() for p in sorted(folder.iterdir())} if folder.is_dir() else {}


def index_lines(repo: Path) -> list[str]:
    return (folder_of(repo) / "index.md").read_bytes().decode("utf-8").splitlines()


# The adapter and the person rule.


def test_a_mixed_transcript_gives_two_files_dated_by_their_times(tmp_path, fake_git_door, capsys):
    repo = ignoring_checkout(tmp_path / "repo")
    assert log.main([str(write_transcript(tmp_path / "t", MIXED)), "--repo", str(repo)]) == 0
    assert sorted(snapshot(repo)) == ["2026-01-01-0001.md", "2026-01-02-0002.md", "index.md"]
    first = (folder_of(repo) / "2026-01-01-0001.md").read_bytes().decode("utf-8")
    assert first == "Said 2026-01-01T10:00:00Z in session.jsonl, line 1\n\nPlease list the files for alice.\n"
    second = (folder_of(repo) / "2026-01-02-0002.md").read_bytes().decode("utf-8")
    assert second.startswith("Said 2026-01-02T09:30:00Z in session.jsonl, line 12\n\n")
    assert index_lines(repo) == [
        "2026-01-01-0001.md | 2026-01-01T10:00:00Z | session.jsonl:1 | Please list the files for alice.",
        "2026-01-02-0002.md | 2026-01-02T09:30:00Z | session.jsonl:12 | Thanks, see example.com for the rest."]


def test_an_interrupt_marker_is_dropped_and_the_rest_of_the_turn_kept():
    lines = [user([{"type": "text", "text": "[Request interrupted by user for tool use]"},
                   {"type": "text", "text": "Stop, use the other branch."}])]
    turns = log.claude_code_turns(lines, "s.jsonl")
    assert [t.parts for t in turns] == [("Stop, use the other branch.",)]


def test_the_id_is_the_uuid_else_the_transcript_and_line():
    lines = [user("one", uuid="u-1"), user("two")]
    assert [t.id for t in log.claude_code_turns(lines, "s.jsonl")] == ["u-1", "s.jsonl:2"]


def test_a_turn_without_a_time_gives_no_file(tmp_path, fake_git_door, capsys):
    repo = ignoring_checkout(tmp_path / "repo")
    transcript = write_transcript(tmp_path / "t", [user("no time", time=None), user("timed")])
    assert log.main([str(transcript), "--repo", str(repo)]) == 0
    assert sorted(snapshot(repo)) == ["2026-01-01-0001.md", "index.md"]
    assert index_lines(repo)[0].endswith("| timed")


def test_turns_of_two_transcripts_are_numbered_in_time_order(tmp_path, fake_git_door, capsys):
    repo = ignoring_checkout(tmp_path / "repo")
    a = write_transcript(tmp_path / "t", [user("a1", "2026-01-01T10:00:00Z"),
                                          user("a2", "2026-01-01T10:00:20Z")], "a.jsonl")
    b = write_transcript(tmp_path / "t", [user("b1", "2026-01-01T10:00:10Z"),
                                          user("b2", "2026-01-01T10:00:30Z")], "b.jsonl")
    assert log.main([str(b), str(a), "--repo", str(repo)]) == 0
    assert [line.rsplit(" | ", 1)[1] for line in index_lines(repo)] == ["a1", "b1", "a2", "b2"]
    assert [line.split(" | ")[0] for line in index_lines(repo)] == [
        f"2026-01-01-000{n}.md" for n in range(1, 5)]


def test_an_adapter_added_to_the_table_is_written_with_no_other_change(
        tmp_path, fake_git_door, capsys, monkeypatch):
    def plain_lines(lines, transcript):
        return [log.Turn(f"{transcript}:{n}", transcript, n,
                         log._time(line.split(" ", 1)[0]), (line.split(" ", 1)[1],))
                for n, line in enumerate(lines, 1) if " " in line]

    monkeypatch.setitem(log.ADAPTERS, "plain", plain_lines)
    repo = ignoring_checkout(tmp_path / "repo")
    transcript = write_transcript(tmp_path / "t", ["2026-03-04T05:06:07Z hello from alice"], "p.log")
    assert log.main([str(transcript), "--repo", str(repo), "--adapter", "plain"]) == 0
    assert (folder_of(repo) / "2026-03-04-0001.md").read_bytes() == \
        b"Said 2026-03-04T05:06:07Z in p.log, line 1\n\nhello from alice\n"


# A message typed while the agent works.


def test_a_queued_message_is_a_turn_typed_while_the_agent_worked():
    lines = [json.dumps({"type": "queue-operation", "operation": "enqueue",
                         "timestamp": "2026-01-01T10:00:30Z", "content": "typed while busy"}),
             queued("typed while busy"),
             queued("from a peer", origin="peer"),
             queued("<task-notification>x</task-notification>", mode="task-notification"),
             queued("no origin", origin=None)]
    turns = log.claude_code_turns(lines, "s.jsonl")
    assert [(t.line, t.parts, t.queued) for t in turns] == [
        (2, ("typed while busy",), True), (5, ("no origin",), True)]
    assert log.render(turns[0]).split("\n", 1)[0] == \
        "Said 2026-01-01T10:00:40Z in s.jsonl, line 2, typed while the agent worked"


def test_a_queued_prompt_of_an_image_and_a_text_part():
    turns = log.claude_code_turns([queued([image(), {"type": "text", "text": "see this"}])], "s.jsonl")
    assert log.render(turns[0]).split("\n\n", 1)[1] == "[image 1]\nsee this\n"


# The files and the index.


def test_files_and_index_are_utf8_with_lf_only_and_one_index_line_per_file(
        tmp_path, fake_git_door, capsys):
    repo = ignoring_checkout(tmp_path / "repo")
    lines = MIXED + [user("Zeile mit Umlaut äöü\r\nund zweite Zeile", "2026-01-03T00:00:00Z"),
                     user("x" * 200, "2026-01-03T00:00:01Z")]
    assert log.main([str(write_transcript(tmp_path / "t", lines)), "--repo", str(repo)]) == 0
    files = snapshot(repo)
    for data in files.values():
        text = data.decode("utf-8")
        assert "\r" not in text and text.endswith("\n")
    turn_files = sorted(name for name in files if name != "index.md")
    index = index_lines(repo)
    assert [line.split(" | ")[0] for line in index] == turn_files
    for line in index:
        assert STAMP.fullmatch(line.split(" | ")[1])
        assert len(line.split(" | ", 3)[3]) <= 80
    for name in turn_files:
        assert STAMP.fullmatch(files[name].decode("utf-8").split(" ")[1])
    assert "Zeile mit Umlaut äöü\nund zweite Zeile\n" in files[turn_files[-2]].decode("utf-8")


def test_the_same_transcript_in_two_fresh_folders_gives_the_same_bytes(
        tmp_path, fake_git_door, capsys):
    transcript = write_transcript(tmp_path / "t", MIXED)
    one, two = ignoring_checkout(tmp_path / "one"), ignoring_checkout(tmp_path / "two")
    assert log.main([str(transcript), "--repo", str(one)]) == 0
    assert log.main([str(transcript), "--repo", str(two)]) == 0
    assert snapshot(one) == snapshot(two) != {}


def test_the_plan_is_pure_and_numbers_after_the_index():
    turn = log.claude_code_turns([user("hello", uuid="u-9")], "s.jsonl")
    index = "2026-01-01-0007.md | 2026-01-01T10:00:00Z | u-1 | old\n"
    result = log.plan(turn, index)
    assert [name for name, _ in result.files] == ["2026-01-01-0008.md"]
    assert result.index == b"2026-01-01-0008.md | 2026-01-01T10:00:00Z | u-9 | hello\n"
    assert log.plan(turn, index + result.index.decode()).files == ()


# Never rewritten.


def test_a_second_run_writes_nothing_and_new_turns_get_the_next_numbers(
        tmp_path, fake_git_door, capsys):
    repo = ignoring_checkout(tmp_path / "repo")
    folder = tmp_path / "projects" / "example"
    transcript = write_transcript(folder, MIXED)
    assert log.main([str(transcript), "--repo", str(repo)]) == 0
    first = snapshot(repo)
    assert log.main([str(transcript), "--repo", str(repo)]) == 0
    assert snapshot(repo) == first
    assert log.main([str(tmp_path / "projects"), "--repo", str(repo)]) == 0
    assert snapshot(repo) == first
    write_transcript(folder, MIXED + [user("third", "2026-01-04T00:00:00Z"),
                                      user("fourth", "2026-01-04T00:00:01Z")])
    assert log.main([str(transcript), "--repo", str(repo)]) == 0
    after = snapshot(repo)
    assert sorted(set(after) - set(first)) == ["2026-01-04-0003.md", "2026-01-04-0004.md"]
    assert all(after[name] == data for name, data in first.items() if name != "index.md")
    assert after["index.md"].startswith(first["index.md"])
    assert len(index_lines(repo)) == 4


def test_a_planted_file_under_a_name_the_run_would_write_stops_it(tmp_path, fake_git_door, capsys):
    repo = ignoring_checkout(tmp_path / "repo")
    folder_of(repo).mkdir(parents=True)
    (folder_of(repo) / "2026-01-02-0002.md").write_bytes(b"planted\n")
    assert log.main([str(write_transcript(tmp_path / "t", MIXED)), "--repo", str(repo)]) == 1
    assert snapshot(repo) == {"2026-01-02-0002.md": b"planted\n"}


# Images only on request.


def test_images_are_written_only_with_the_option(tmp_path, fake_git_door, capsys):
    lines = [user([{"type": "text", "text": "look at this"}, image()], "2026-01-01T10:00:00Z"),
             user([image(b"GIF89a", "image/gif"), image(b"?", "image/tiff")], "2026-01-01T10:00:01Z")]
    transcript = write_transcript(tmp_path / "t", lines)
    plain = ignoring_checkout(tmp_path / "plain")
    assert log.main([str(transcript), "--repo", str(plain)]) == 0
    assert sorted(snapshot(plain)) == ["2026-01-01-0001.md", "2026-01-01-0002.md", "index.md"]
    with_images = ignoring_checkout(tmp_path / "images")
    assert log.main([str(transcript), "--repo", str(with_images), "--images"]) == 0
    files = snapshot(with_images)
    assert files["2026-01-01-0001-1.png"] == PNG
    assert files["2026-01-01-0002-1.gif"] == b"GIF89a"
    assert files["2026-01-01-0002-2.bin"] == b"?"
    assert files["2026-01-01-0001.md"].endswith(b"look at this\n[image 1]\n")
    assert len(index_lines(with_images)) == 2


# Only into the ignored folder.


def test_an_ignoring_checkout_keeps_its_status(tmp_path, fake_git_door, capsys):
    repo = ignoring_checkout(tmp_path / "repo")
    before = git_door.run("status", "--porcelain", root=repo)
    assert log.main([str(write_transcript(tmp_path / "t", MIXED)), "--repo", str(repo)]) == 0
    after = git_door.run("status", "--porcelain", root=repo)
    assert (after.returncode, after.stdout) == (before.returncode, before.stdout)
    assert snapshot(repo)


def test_a_checkout_that_does_not_ignore_the_folder_is_refused(tmp_path, fake_git_door, capsys):
    repo = fake_git.init(tmp_path / "repo")
    assert log.main([str(write_transcript(tmp_path / "t", MIXED)), "--repo", str(repo)]) == 1
    assert not (repo / ".se").exists()


def test_a_folder_that_is_no_checkout_is_written(tmp_path, fake_git_door, capsys):
    repo = tmp_path / "plain"
    repo.mkdir()
    assert log.main([str(write_transcript(tmp_path / "t", MIXED)), "--repo", str(repo)]) == 0
    assert len(index_lines(repo)) == 2
    assert capsys.readouterr().out == "input log: 2 new files in .se/input/\n"


def test_the_output_holds_none_of_the_turns_text(tmp_path, fake_git_door, capsys):
    repo = ignoring_checkout(tmp_path / "repo")
    transcript = write_transcript(tmp_path / "t", MIXED + [queued("typed while busy")])
    assert log.main([str(transcript), "--repo", str(repo)]) == 0
    assert log.main([str(transcript), "--repo", str(repo)]) == 0
    (folder_of(repo) / "index.md").unlink()
    assert log.main([str(transcript), "--repo", str(repo)]) == 1
    captured = capsys.readouterr()
    for words in ("list the files", "alice", "example.com", "typed while busy"):
        assert words not in captured.out + captured.err


# The shape of the module.


def test_only_main_opens_prints_writes_or_runs_git():
    tree = ast.parse((PROJECT / "scripts" / "input_log.py").read_text(encoding="utf-8"))
    main = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "main")
    inside = {id(node) for node in ast.walk(main)}
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or id(node) in inside:
            continue
        func = node.func
        name = func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else ""
        door = isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name) \
            and func.value.id == "git_door"
        if name in ("open", "print") or name.startswith(("write_", "read_")) or door \
                or name in ("mkdir", "rglob", "exists", "is_file", "is_dir", "unlink"):
            found.append(f"{name} at line {node.lineno}")
    assert found == []


def test_the_person_turns_match_the_transcript_reader_on_its_fixtures():
    reader = load("transcript_signals")
    files = sorted(FIXTURES.rglob("*.jsonl"))
    assert files
    for path in files:
        lines = path.read_bytes().decode("utf-8").split("\n")
        ours = sorted({t.line for t in log.claude_code_turns(lines, path.name)})
        theirs = sorted({e.line for e in reader.read_events(lines, path.name)
                         if e.who == "person" and e.kind == "message" and not e.sidechain})
        assert ours == theirs, path.name
        assert ours, path.name


def test_the_module_never_names_the_transcript_reader():
    assert "transcript" + "_signals" not in (PROJECT / "scripts" / "input_log.py").read_text(encoding="utf-8")


def test_nothing_calls_the_module():
    callers = [path.relative_to(PROJECT).as_posix()
               for folder in ("scripts", "components", "kern", "src")
               for path in (PROJECT / folder).rglob("*")
               if path.is_file() and path.suffix in (".py", ".go", ".md", ".sh", ".toml", ".ps1")
               and path.name != "input_log.py"
               and "input_log" in path.read_text(encoding="utf-8", errors="replace")]
    assert callers == []
