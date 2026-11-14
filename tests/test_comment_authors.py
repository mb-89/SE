"""Who wrote a work issue's comment (scripts/comment_authors.py): the owner account's flag and the
mark that ends a line naming a comment the owner did not write."""
import importlib.util
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "comment_authors", Path(__file__).resolve().parents[1] / "scripts" / "comment_authors.py")
comment_authors = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(comment_authors)


@pytest.mark.parametrize(("author", "repo", "owner"), [
    ("alice", "alice/se", True),
    ("Alice", "github.com/alice/se", True),
    ("bob", "github.com/alice/se", False),
    ("", "alice/se", False),
    ("alice", "se", False),
])
def test_a_comment_is_the_owners_only_where_its_login_is_the_repository_owner(author, repo, owner):
    assert comment_authors.by_owner(author, repo) is owner


@pytest.mark.parametrize(("comment", "mark"), [
    ({"author": "bob", "byOwner": False}, " [not the repository owner]"),
    ({"author": "alice", "byOwner": True}, ""),
    ({"author": "alice"}, ""),  # recorded before the flag existed: as before
])
def test_only_a_comment_known_not_to_be_the_owners_is_marked(comment, mark):
    assert comment_authors.mark(comment) == mark
