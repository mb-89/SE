"""scripts/rewrite_history.py: the one-time history rewrite before se replaces main.

Its parts run here on the git door's fake: the message and stream filter, and the reads and
refusals of a clone. The fake streams nothing, so the rewrite end to end (`fast-export` through the
filter into `fast-import`) is a case of the door's contract suite, held against real git
(tests/test_git_door.py, the history rewrite).
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest

import fake_git
import git_door
import rewrite_history

OWNER = ("mb", "mb")
WEB_FLOW = "GitHub <noreply" + "@github.com>"


@pytest.fixture
def clone(tmp_path: Path, fake_git_door) -> Path:
    """A fresh clone of an origin with a main line, a side branch and a tag, on the fake."""
    origin = fake_git.init(tmp_path / "origin", "-b", "main")
    assert git_door.set_identity(origin, OWNER) is None
    (origin / "se.toml").write_text('[project]\nidentity = "mb <mb>"\n', encoding="utf-8")
    commit(origin, "se.toml", "Start")
    git(origin, "tag", "v0.1.0")
    commit(origin, "a.txt", "More")
    fresh = fake_git.clone(origin, tmp_path / "clone")
    assert git_door.set_identity(fresh, OWNER) is None
    git(fresh, "branch", "-q", "feature", "origin/main")
    return fresh


def git(repo: Path, *arguments: str) -> str:
    result = git_door.run(*arguments, root=repo)
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def commit(repo: Path, name: str, message: str) -> str:
    if not (repo / name).exists():
        (repo / name).write_text(f"{name}\n", encoding="utf-8")
    git(repo, "add", name)
    git(repo, "commit", "-q", "-m", message)
    return git(repo, "rev-parse", "HEAD")


@pytest.mark.parametrize(("message", "cleaned"), [
    ("Fix it\n", "Fix it\n"),
    ("Fix it\n\nCo-Authored-By: A <a@example.com>\nClaude-Session: https://example.com/s\n",
     "Fix it\n"),
    ("Fix it\n\nBody.\n\nco-authored-by: A\n\nMore.\n", "Fix it\n\nBody.\n\nMore.\n"),
    ("Fix (#593, requirement 2)\n", "Fix (requirement 2)\n"),
    ("Fix (#593)\n", "Fix\n"),
    ("Fix it, as GH-4 asked, #5\n", "Fix it, as asked\n"),
    ("C# 5 and &#39; stay\n", "C# 5 and &#39; stay\n"),
])
def test_a_message_loses_only_its_trailers_and_tracker_references(message, cleaned):
    assert rewrite_history.clean_message(message)[0] == cleaned


def data(text: bytes) -> bytes:
    return b"data %d\n%s" % (len(text), text)


def stream_commit(mark: int, original: str, author: str, committer: str, message: bytes) -> bytes:
    return (b"commit refs/heads/main\nmark :%d\noriginal-oid %s\nauthor %s 1700000000 +0000\n"
            b"committer %s 1700000000 +0000\n" % (mark, original.encode(), author.encode(), committer.encode())
            + data(message) + b"M 100644 :1 a.txt\n\n")


def test_the_stream_filter_cleans_each_commit_and_copies_everything_else_as_it_is():
    """A `fast-export` stream: a blob whose content looks like a message, a clean commit, one by
    another author with a trailer and a reference, a merge GitHub committed, an annotated tag."""
    blob = b"blob\nmark :1\n" + data(b"Co-Authored-By: kept in a file (#5)\n")
    clean = stream_commit(2, "a" * 40, "mb <mb>", "mb <mb>", b"Start\n")
    foreign = stream_commit(3, "b" * 40, "Claude <c@example.com>", "Claude <c@example.com>",
                            b"Fix (#593)\n\nCo-Authored-By: A <a@example.com>\n")
    merged = stream_commit(4, "c" * 40, "mb <mb>", WEB_FLOW, b"Merge it\n")
    tag = b"tag v1\nmark :5\nfrom :4\ntagger mb <mb> 1700000000 +0000\n" + data(b"Release (#7)\n")
    source = blob + clean + foreign + merged + tag
    sink, counts = io.BytesIO(), rewrite_history.Counts()

    rewrite_history.filter_stream(io.BytesIO(source), sink, OWNER, counts)

    expected = (blob + clean + stream_commit(3, "b" * 40, "mb <mb>", "mb <mb>", b"Fix\n") + merged + tag)
    assert sink.getvalue() == expected
    assert (counts.commits, counts.trailers, counts.trailer_commits, counts.references,
            counts.reference_commits, counts.identity_commits) == (3, 1, 1, 1, 1, 1)
    assert counts.originals == {":2": "a" * 40, ":3": "b" * 40, ":4": "c" * 40}


def test_web_flow_passes_as_committer_never_as_author():
    committer = b"committer " + WEB_FLOW.encode() + b" 1700000000 +0000\n"
    author = b"author " + WEB_FLOW.encode() + b" 1700000000 +0000\n"
    assert rewrite_history.fix_identity(committer, OWNER) == committer
    assert rewrite_history.fix_identity(author, OWNER) == b"author mb <mb> 1700000000 +0000\n"
    with pytest.raises(rewrite_history.SetupError, match="cannot read the identity line"):
        rewrite_history.fix_identity(b"author nobody\n", OWNER)


def test_refs_names_each_local_branch_and_tag_with_its_commit(clone):
    head = git(clone, "rev-parse", "main")
    assert rewrite_history.refs(clone) == {
        "refs/heads/feature": head, "refs/heads/main": head,
        "refs/tags/v0.1.0": git(clone, "rev-parse", "v0.1.0^{commit}")}


def test_the_allow_entries_naming_commits_are_listed_at_a_branch_tip(clone):
    assert rewrite_history.stale_allow_entries(clone, "refs/heads/main") == []
    (clone / ".public-check-allow").write_text(
        "# reasons\nREADME.md:3  # a sample\ncommit:abc1234 author  # published\n", encoding="utf-8")
    commit(clone, ".public-check-allow", "Allow")
    assert rewrite_history.stale_allow_entries(clone, "refs/heads/main") == ["3: commit:abc1234 author"]


def test_the_identity_comes_from_the_project_or_the_option(clone):
    assert rewrite_history.project_identity(clone, None) == OWNER
    assert rewrite_history.project_identity(clone, "alice <alice@example.com>") == ("alice", "alice@example.com")
    with pytest.raises(rewrite_history.SetupError, match="no project identity"):
        rewrite_history.project_identity(clone, "alice")


def test_a_shallow_clone_is_refused_naming_the_fetch(clone, tmp_path, capsys):
    shallow = fake_git.clone(clone.as_uri(), tmp_path / "shallow", "--depth", "1")
    assert rewrite_history.main(["--repo", str(shallow)]) == 2
    assert "fetch --unshallow" in capsys.readouterr().err


def test_a_bare_repository_is_refused(clone, tmp_path, capsys):
    bare = fake_git.init(tmp_path / "bare.git", "--bare")
    assert rewrite_history.main(["--repo", str(bare)]) == 2
    assert "is a bare repository" in capsys.readouterr().err


def test_local_changes_are_refused_and_nothing_moves(clone, capsys):
    (clone / "se.toml").write_text("changed\n", encoding="utf-8")
    head = git(clone, "rev-parse", "main")
    assert rewrite_history.main(["--repo", str(clone)]) == 2
    assert "has local changes" in capsys.readouterr().err
    assert git(clone, "rev-parse", "main") == head
