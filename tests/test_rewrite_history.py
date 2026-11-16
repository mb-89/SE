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
CORP = "@" + "corp.org"  # a personal address's domain, built so the public check reads no address


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
    ("Fix it\n\nSigned-off-by: A <a@example.com>\nAsk bob@corp.example.org.\nKept.\n", "Fix it\n\nKept.\n"),
    (f"Thank alice <alice{CORP}> for it\n", "Thank alice for it\n"),
    ("Merge from 1+alice@users.noreply.github.com, (#5)\n", "Merge from,\n"),
])
def test_a_message_loses_only_its_trailers_tracker_references_and_address_lines(message, cleaned):
    assert rewrite_history.clean_message(message)[0] == cleaned


def test_an_address_is_sorted_by_the_public_check_s_own_filter():
    text = (f"alice{CORP} 1+alice@users.noreply.github.com noreply" + "@github.com "
            "bob@example.com git@host.example:o/r")
    assert rewrite_history.addresses(text) == ["personal", "github-noreply", "other", "other", "other"]


def data(text: bytes) -> bytes:
    return b"data %d\n%s" % (len(text), text)


def stream_commit(mark: int, original: str, author: str, committer: str, message: bytes) -> bytes:
    return (b"commit refs/heads/main\nmark :%d\noriginal-oid %s\nauthor %s 1700000000 +0000\n"
            b"committer %s 1700000000 +0000\n" % (mark, original.encode(), author.encode(), committer.encode())
            + data(message) + b"M 100644 :1 a.txt\n\n")


GITHUB_ACCOUNT = "alice <1+alice@users.noreply.github.com>"


def stream(*, cleaned: bool) -> bytes:
    """A `fast-export` stream: a blob whose content looks like a message, a clean commit, one by
    another author with a trailer, a reference and an address line, a squash merge GitHub committed
    for an account, an annotated tag by another tagger; as exported or as the filter writes it."""
    blob = b"blob\nmark :1\n" + data(b"Co-Authored-By: kept in a file (#5) a@example.com\n")
    clean = stream_commit(2, "a" * 40, "mb <mb>", "mb <mb>", b"Start\n")
    if cleaned:
        foreign = stream_commit(3, "b" * 40, "mb <mb>", "mb <mb>", b"Fix\n")
        merged = stream_commit(4, "c" * 40, "mb <mb>", "mb <mb>", b"Merge it\n")
        tag = b"tag v1\nmark :5\nfrom :4\ntagger mb <mb> 1700000000 +0000\n" + data(b"Release\n")
    else:
        foreign = stream_commit(3, "b" * 40, "Claude <c@example.com>", "Claude <c@example.com>",
                                f"Fix (#593)\n\nSigned-off-by: B <b{CORP}>\n\nCo-Authored-By: A <a@example.com>\n".encode())
        merged = stream_commit(4, "c" * 40, GITHUB_ACCOUNT, WEB_FLOW, b"Merge it\n")
        tag = (f"tag v1\nmark :5\nfrom :4\ntagger alice <alice{CORP}> 1700000000 +0000\n".encode()
               + data(b"Release (#7)\n"))
    return blob + clean + foreign + merged + tag


def test_the_stream_filter_cleans_each_commit_and_tag_and_copies_everything_else_as_it_is():
    sink, counts = io.BytesIO(), rewrite_history.Counts()

    rewrite_history.filter_stream(io.BytesIO(stream(cleaned=False)), sink, OWNER, counts)

    assert sink.getvalue() == stream(cleaned=True)
    assert (counts.commits, counts.tags, counts.trailers, counts.trailer_commits, counts.references,
            counts.reference_commits, counts.addresses, counts.address_commits,
            counts.identity_commits) == (3, 1, 1, 1, 2, 2, 2, 1, 3)
    assert counts.originals == {":2": "a" * 40, ":3": "b" * 40, ":4": "c" * 40}


def test_the_census_counts_addresses_by_place_and_kind_and_the_foreign_identities():
    before = rewrite_history.census_stream(io.BytesIO(stream(cleaned=False)), OWNER)
    after = rewrite_history.census_stream(io.BytesIO(stream(cleaned=True)), OWNER)

    assert (before.commits, before.tags, before.carriers, before.foreign) == (3, 1, 3, 5)
    assert dict(before.found) == {
        ("author", "other"): 1, ("committer", "other"): 2, ("author", "github-noreply"): 1,
        ("tagger", "personal"): 1, ("commit-message", "personal"): 1, ("commit-message", "other"): 1}
    assert (after.commits, after.tags, after.total(), after.carriers, after.foreign) == (3, 1, 0, 0, 0)
    printed = "\n".join(before.lines("before"))
    assert "3 commits, 1 annotated tags; 7 addresses in 3 of them; 5 identities" in printed
    assert "tagger personal 1" in printed and "@" not in printed
    assert after.lines("after")[1].endswith("addresses by place and kind: none")


def test_every_identity_becomes_the_project_identity_web_flow_and_taggers_included():
    for role in (b"author", b"committer", b"tagger"):
        for found in (WEB_FLOW.encode(), GITHUB_ACCOUNT.encode(), b"mb <other>"):
            assert rewrite_history.fix_identity(b"%s %s 1700000000 +0000\n" % (role, found), OWNER) \
                == b"%s mb <mb> 1700000000 +0000\n" % role
    kept = b"committer mb <mb> 1700000000 +0000\n"
    assert rewrite_history.fix_identity(kept, OWNER) is kept
    with pytest.raises(rewrite_history.SetupError, match="cannot read the identity line"):
        rewrite_history.fix_identity(b"author nobody\n", OWNER)


def test_every_branch_of_origin_gets_a_local_branch_once(clone, tmp_path):
    origin = tmp_path / "origin"
    git(origin, "branch", "-q", "side")
    git(clone, "fetch", "-q", "origin")
    assert rewrite_history.track_origin_branches(clone) == ["side"]
    assert git(clone, "rev-parse", "side") == git(clone, "rev-parse", "origin/side")
    assert rewrite_history.track_origin_branches(clone) == []


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
