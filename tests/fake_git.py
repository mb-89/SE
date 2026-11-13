"""A fake git behind the git door (scripts/git_door.py): repositories, commits, branches, tags and
remotes in memory, the working tree on disk, so code under test reads and writes its files as with
real git. It answers the commands SE's tests use, with git's exit codes and the refusal texts SE's
code reads; anything else exits 129, naming what the fake lacks.

tests/test_git_door.py holds it to real git's contract: the same cases run against both. Install it
with `git_door.use(FakeGit())` (the `fake_git_door` fixture in tests/conftest.py). Like CI's bare runner
it knows no identity of its own: a commit or merge needs one from `-c`, the environment or the
repository's config.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

ZERO_IDENTITY = "Author identity unknown\n\n*** Please tell me who you are.\n"


class Refusal(Exception):
    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code, self.message = code, message


@dataclass(frozen=True)
class Commit:
    tree: str
    parents: tuple[str, ...]
    message: str
    author: tuple[str, str]
    committer: tuple[str, str]


@dataclass
class Repository:
    path: Path
    bare: bool
    head: str = "refs/heads/main"  # a ref name, or a commit for a detached HEAD
    refs: dict[str, str] = field(default_factory=dict)
    config: dict[str, str] = field(default_factory=dict)
    index: dict[str, bytes] = field(default_factory=dict)

    @property
    def git_dir(self) -> Path:
        return self.path if self.bare else self.path / ".git"


class FakeGit:
    """The git door's backend for tests (git_door.Backend)."""

    def __init__(self) -> None:
        self.repositories: dict[Path, Repository] = {}
        self.trees: dict[str, dict[str, bytes]] = {}
        self.commits: dict[str, Commit] = {}
        self.calls: list[list[str]] = []

    # The door's call

    def run(self, argv: list[str], *, cwd: Path | None, env: dict[str, str] | None,
            stdin: bytes | None, timeout: float | None) -> subprocess.CompletedProcess[bytes]:
        self.calls.append(list(argv))
        where, options, arguments = Path(cwd or Path.cwd()), {}, list(argv)
        while arguments and arguments[0] in ("-C", "-c"):
            flag, value = arguments[0], arguments[1]
            arguments = arguments[2:]
            if flag == "-C":
                where = where / value
            else:
                key, _, setting = value.partition("=")
                options[key.lower()] = setting
        command, *rest = arguments or ["help"]
        try:
            handler = getattr(self, "git_" + command.replace("-", "_"), None)
            if handler is None:
                raise Refusal(129, f"fake git: no `{command}` (tests/fake_git.py answers only what the tests use)")
            out = handler(Call(where, options, dict(os.environ if env is None else env), rest))
            return subprocess.CompletedProcess(["git", *argv], 0, _bytes(out), b"")
        except Refusal as refusal:
            return subprocess.CompletedProcess(["git", *argv], refusal.code, b"", _bytes(refusal.message + "\n"))

    # Repositories

    def find(self, where: Path) -> Repository:
        place = where.resolve()
        for candidate in (place, *place.parents):
            if candidate in self.repositories:
                return self.repositories[candidate]
        raise Refusal(128, "fatal: not a git repository (or any of the parent directories): .git")

    def remote(self, repository: Repository, name: str) -> Repository:
        url = repository.config.get(f"remote.{name}.url", name)
        if url.startswith("file:"):
            url = urllib.request.url2pathname(urllib.parse.urlparse(url).path)
        return self.find(Path(url))

    # Objects

    def store_tree(self, files: dict[str, bytes]) -> str:
        digest = hashlib.sha1()
        for path in sorted(files):
            digest.update(path.encode() + b"\0" + hashlib.sha1(files[path]).digest())
        tree = digest.hexdigest()
        self.trees[tree] = dict(files)
        return tree

    def store_commit(self, commit: Commit) -> str:
        sha = hashlib.sha1(repr((commit, len(self.commits))).encode()).hexdigest()
        self.commits[sha] = commit
        return sha

    def ancestors(self, sha: str) -> set[str]:
        seen, todo = set(), [sha]
        while todo:
            current = todo.pop()
            if current not in seen:
                seen.add(current)
                todo.extend(self.commits[current].parents)
        return seen

    def first_parents(self, sha: str) -> list[str]:
        line = [sha]
        while self.commits[line[-1]].parents:
            line.append(self.commits[line[-1]].parents[0])
        return line

    def resolve(self, repository: Repository, rev: str) -> str:
        """The object `rev` names: a commit, or a tree for `<rev>^{tree}`."""
        if rev.endswith("^{tree}"):
            return self.commits[self.resolve(repository, rev[:-7])].tree
        if rev.endswith("^{commit}"):
            rev = rev[:-9]
        steps = 0
        if "~" in rev:
            rev, _, count = rev.partition("~")
            steps = int(count or 1)
        while rev.endswith("^"):
            rev, steps = rev[:-1], steps + 1
        sha = self.commit_of(repository, rev)
        for _ in range(steps):
            parents = self.commits[sha].parents
            if not parents:
                raise Refusal(128, f"fatal: ambiguous argument '{rev}': unknown revision")
            sha = parents[0]
        return sha

    def commit_of(self, repository: Repository, rev: str) -> str:
        if rev == "HEAD":
            rev = repository.head
        for name in (rev, f"refs/heads/{rev}", f"refs/tags/{rev}", f"refs/remotes/{rev}"):
            if name in repository.refs:
                return repository.refs[name]
        if len(rev) >= 4 and all(c in "0123456789abcdef" for c in rev):
            found = [sha for sha in self.commits if sha.startswith(rev)]
            if len(found) == 1:
                return found[0]
        raise Refusal(128, f"fatal: ambiguous argument '{rev}': unknown revision or path not in the working tree.")

    def head_commit(self, repository: Repository) -> str | None:
        try:
            return self.commit_of(repository, "HEAD")
        except Refusal:
            return None

    def identity(self, call: Call, repository: Repository, role: str) -> tuple[str, str]:
        name = (call.env.get(f"GIT_{role}_NAME") or call.options.get("user.name")
                or repository.config.get("user.name"))
        email = (call.env.get(f"GIT_{role}_EMAIL") or call.options.get("user.email")
                 or repository.config.get("user.email"))
        if not name or not email:
            raise Refusal(128, ZERO_IDENTITY + "fatal: unable to auto-detect email address")
        return name, email

    def commit_tree(self, call: Call, repository: Repository, tree: str, parents: tuple[str, ...],
                    message: str) -> str:
        author = self.identity(call, repository, "AUTHOR")
        committer = self.identity(call, repository, "COMMITTER")
        sha = self.store_commit(Commit(tree, parents, message.strip() + "\n", author, committer))
        if repository.head.startswith("refs/"):
            repository.refs[repository.head] = sha
        else:
            repository.head = sha
        return sha

    def check_out(self, repository: Repository, tree: str) -> None:
        """Make the working tree and the index `tree`'s files."""
        for path in repository.index:
            (repository.path / path).unlink(missing_ok=True)
        files = self.trees[tree]
        for path, data in files.items():
            target = repository.path / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        repository.index = dict(files)

    # The commands

    def git_init(self, call: Call) -> str:
        args = call.args
        bare = "--bare" in args
        branch = args[args.index("-b") + 1] if "-b" in args else "main"
        path = (call.where / [a for a in args if not a.startswith("-") and a != branch][-1]).resolve()
        path.mkdir(parents=True, exist_ok=True)
        repository = Repository(path, bare, head=f"refs/heads/{branch}")
        repository.git_dir.mkdir(exist_ok=True)
        self.repositories[path] = repository
        return ""

    def git_config(self, call: Call) -> str:
        repository = self.find(call.where)
        args = [a for a in call.args if a not in ("--local", "--get")]
        if len(args) == 1:
            value = repository.config.get(args[0].lower())
            if value is None:
                raise Refusal(1, "")
            return value + "\n"
        repository.config[args[0].lower()] = args[1]
        return ""

    def git_remote(self, call: Call) -> str:
        repository = self.find(call.where)
        verb, name, *url = call.args
        if verb == "add":
            repository.config[f"remote.{name}.url"] = url[0]
            return ""
        if verb == "get-url":
            if f"remote.{name}.url" not in repository.config:
                raise Refusal(2, f"error: No such remote '{name}'")
            return repository.config[f"remote.{name}.url"] + "\n"
        raise Refusal(129, f"fake git: no `remote {verb}`")

    def git_add(self, call: Call) -> str:
        repository = self.find(call.where)
        root = repository.path
        repository.index = {path.relative_to(root).as_posix(): path.read_bytes()
                            for path in sorted(root.rglob("*"))
                            if path.is_file() and ".git" not in path.relative_to(root).parts}
        return ""

    def git_commit(self, call: Call) -> str:
        repository = self.find(call.where)
        message = call.args[call.args.index("-m") + 1]
        head = self.head_commit(repository)
        tree = self.store_tree(repository.index)
        if head is not None and self.commits[head].tree == tree and "--allow-empty" not in call.args:
            raise Refusal(1, "nothing to commit, working tree clean")
        self.commit_tree(call, repository, tree, (head,) if head else (), message)
        return ""

    def git_rev_parse(self, call: Call) -> str:
        repository = self.find(call.where)
        args = list(call.args)
        if "--git-common-dir" in args:
            return f"{repository.git_dir}\n"
        if "--absolute-git-dir" in args:
            return f"{repository.git_dir}\n"
        verify = "--verify" in args
        quiet = "--quiet" in args or "-q" in args
        short = next((a for a in args if a.startswith("--short")), None)
        revs = [a for a in args if not a.startswith("-")]
        if "--abbrev-ref" in args:
            head = repository.head
            return (head.removeprefix("refs/heads/") if head.startswith("refs/") else "HEAD") + "\n"
        try:
            sha = self.resolve(repository, revs[0])
        except (Refusal, KeyError):
            if verify and quiet:
                raise Refusal(1, "")
            raise Refusal(128, f"fatal: Needed a single revision" if verify else
                          f"fatal: ambiguous argument '{revs[0]}': unknown revision or path not in the working tree.")
        if short:
            sha = sha[:int(short.partition("=")[2] or 7)]
        return sha + "\n"

    def git_update_ref(self, call: Call) -> str:
        repository = self.find(call.where)
        name, rev = call.args[:2]
        repository.refs[name] = self.resolve(repository, rev)
        return ""

    def git_tag(self, call: Call) -> str:
        repository = self.find(call.where)
        name, *rev = [a for a in call.args if not a.startswith("-")]
        repository.refs[f"refs/tags/{name}"] = self.resolve(repository, rev[0] if rev else "HEAD")
        return ""

    def git_switch(self, call: Call) -> str:
        repository = self.find(call.where)
        args = [a for a in call.args if a not in ("-q", "--quiet", "--discard-changes")]
        if args[0] == "-c":
            head = self.head_commit(repository)
            if head is not None:
                repository.refs[f"refs/heads/{args[1]}"] = head
            repository.head = f"refs/heads/{args[1]}"
            return ""
        name = f"refs/heads/{args[0]}"
        if name not in repository.refs:
            raise Refusal(128, f"fatal: invalid reference: {args[0]}")
        repository.head = name
        self.check_out(repository, self.commits[repository.refs[name]].tree)
        return ""

    def git_merge(self, call: Call) -> str:
        repository = self.find(call.where)
        if "--abort" in call.args:
            return ""
        message = call.args[call.args.index("-m") + 1] if "-m" in call.args else "Merge"
        theirs_rev = [a for i, a in enumerate(call.args)
                      if not a.startswith("-") and (i == 0 or call.args[i - 1] != "-m")][-1]
        ours, theirs = self.commit_of(repository, "HEAD"), self.resolve(repository, theirs_rev)
        if theirs in self.ancestors(ours):
            return "Already up to date.\n"
        common = self.ancestors(ours) & self.ancestors(theirs)
        base = next((sha for sha in self.first_parents(ours) if sha in common), None)
        trees = [self.trees[self.commits[sha].tree] if sha else {} for sha in (base, ours, theirs)]
        merged, conflicts = {}, []
        for path in sorted(set().union(*trees)):
            old, mine, other = (tree.get(path) for tree in trees)
            result = mine if mine == other or other == old else other if mine == old else None
            if result is None and mine != other:
                conflicts.append(path)
            elif result is not None:
                merged[path] = result
        if conflicts:
            raise Refusal(1, "\n".join(f"CONFLICT (content): Merge conflict in {path}" for path in conflicts)
                          + "\nAutomatic merge failed; fix conflicts and then commit the result.")
        if "--no-ff" not in call.args and base == ours:
            repository.refs[repository.head] = theirs
        else:
            self.commit_tree(call, repository, self.store_tree(merged), (ours, theirs), message)
        self.check_out(repository, self.commits[self.commit_of(repository, "HEAD")].tree)
        return ""

    def git_rev_list(self, call: Call) -> str:
        repository = self.find(call.where)
        args = list(call.args)
        excluded: set[str] = set()
        if "--not" in args:
            args, negated = args[:args.index("--not")], args[args.index("--not") + 1:]
            names = [name for name in repository.refs
                     if ("--remotes" in negated and name.startswith("refs/remotes/"))
                     or ("--tags" in negated and name.startswith("refs/tags/"))]
            for name in names:
                excluded |= self.ancestors(repository.refs[name])
        rev = self.resolve(repository, [a for a in args if not a.startswith("-")][0])
        if "--first-parent" in args:
            line = self.first_parents(rev)
        else:  # newest first, as the commits were made
            reachable = self.ancestors(rev)
            line = [sha for sha in reversed(self.commits) if sha in reachable]
        line = [sha for sha in line if sha not in excluded]
        limit = next((int(a.partition("=")[2]) for a in args if a.startswith("--max-count=")), None)
        line = line[:limit] if limit is not None else line
        return f"{len(line)}\n" if "--count" in args else "".join(f"{sha}\n" for sha in line)

    def git_show(self, call: Call) -> str | bytes:
        repository = self.find(call.where)
        spec = [a for a in call.args if not a.startswith("-")][0]
        rev, _, path = spec.partition(":")
        files = self.trees[self.commits[self.resolve(repository, rev)].tree]
        if path not in files:
            raise Refusal(128, f"fatal: path '{path}' does not exist in '{rev}'")
        return files[path]

    def git_log(self, call: Call) -> str:
        repository = self.find(call.where)
        form = next(a.partition("=")[2] for a in call.args if a.startswith("--format="))
        commit = self.commits[self.commit_of(repository, "HEAD")]
        return (form.replace("%an", commit.author[0]).replace("%ae", commit.author[1])
                .replace("%cn", commit.committer[0]).replace("%ce", commit.committer[1])
                .replace("%s", commit.message.splitlines()[0])) + "\n"

    def git_ls_remote(self, call: Call) -> str:
        url = [a for a in call.args if not a.startswith("-")][0]
        try:
            remote = self.remote(Repository(Path(), False), url)
        except Refusal:
            raise Refusal(128, f"fatal: '{url}' does not appear to be a git repository")
        refs = sorted(name for name in remote.refs if "--tags" not in call.args or name.startswith("refs/tags/"))
        return "".join(f"{remote.refs[name]}\t{name}\n" for name in refs)

    def git_push(self, call: Call) -> str:
        repository = self.find(call.where)
        name, *specs = [a for a in call.args if not a.startswith("-")]
        remote = self.remote(repository, name)
        for spec in specs:
            source, _, destination = spec.partition(":")
            destination = destination or source
            if not destination.startswith("refs/"):
                destination = f"refs/heads/{destination}"
            sha = self.resolve(repository, source)
            old = remote.refs.get(destination)
            if old is not None and old not in self.ancestors(sha) and "--force" not in call.args:
                short = destination.removeprefix("refs/heads/")
                raise Refusal(1, f"To {name}\n ! [rejected]        {source} -> {short} (non-fast-forward)\n"
                                 f"error: failed to push some refs to '{name}'")
            remote.refs[destination] = sha
        return ""

    def git_fetch(self, call: Call) -> str:
        repository = self.find(call.where)
        name, *specs = [a for a in call.args if not a.startswith("-")]
        remote = self.remote(repository, name)
        if not specs:
            for ref, sha in remote.refs.items():
                if ref.startswith("refs/heads/"):
                    repository.refs[f"refs/remotes/{name}/{ref.removeprefix('refs/heads/')}"] = sha
                elif ref.startswith("refs/tags/"):
                    repository.refs[ref] = sha
        for spec in specs:
            source, _, destination = spec.partition(":")
            if source not in remote.refs:
                raise Refusal(128, f"fatal: couldn't find remote ref {source}")
            repository.refs[destination or source] = remote.refs[source]
        return ""


@dataclass(frozen=True)
class Call:
    where: Path
    options: dict[str, str]
    env: dict[str, str]
    args: list[str]


def _bytes(data: str | bytes) -> bytes:
    return data if isinstance(data, bytes) else data.encode("utf-8")
