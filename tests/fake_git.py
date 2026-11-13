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

import difflib
import fnmatch
import hashlib
import io
import os
import shutil
import subprocess
import tarfile
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
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
    author_date: datetime
    committer_date: datetime


@dataclass
class Repository:
    path: Path
    bare: bool
    head: str = "refs/heads/main"  # a ref name, or a commit for a detached HEAD
    refs: dict[str, str] = field(default_factory=dict)
    config: dict[str, str] = field(default_factory=dict)
    index: dict[str, bytes] = field(default_factory=dict)
    conflicts: list[str] = field(default_factory=list)  # what a failed merge left conflicted
    main: Repository | None = None  # a linked worktree's repository; its refs and config are main's

    @property
    def git_dir(self) -> Path:
        if self.main is not None:
            return self.main.git_dir / "worktrees" / self.path.name
        return self.path if self.bare else self.path / ".git"

    @property
    def common_dir(self) -> Path:
        return (self.main or self).git_dir


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
        sha = self.store_commit(Commit(tree, parents, message.strip() + "\n", author, committer,
                                       date(call, "AUTHOR"), date(call, "COMMITTER")))
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
        named = [a for a in args if not a.startswith("-") and a != branch]
        path = (call.where / named[-1] if named else call.where).resolve()
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
        if not call.args:
            return "".join(f"{key.split('.')[1]}\n" for key in repository.config
                           if key.startswith("remote.") and key.endswith(".url"))
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
        """`add -A`, `add .` or `add <path>...`: the paths' files as they are on disk, a missing one
        leaving the index; an ignored file stays out unless it is tracked already."""
        repository = self.find(call.where)
        present = self.on_disk(repository)
        paths = [a for a in call.args if not a.startswith("-")]
        if not paths or "." in paths or "-A" in call.args or "--all" in call.args:
            repository.index = present
            return ""
        for path in paths:
            name = (call.where / path).resolve().relative_to(repository.path).as_posix()
            inside = [known for known in {*present, *repository.index}
                      if known == name or known.startswith(name + "/")]
            if not inside:
                raise Refusal(128, f"fatal: pathspec '{path}' did not match any files")
            for known in inside:
                if known in present:
                    repository.index[known] = present[known]
                else:
                    repository.index.pop(known, None)
        return ""

    def on_disk(self, repository: Repository) -> dict[str, bytes]:
        """The working tree's files git sees: without .git, other worktrees nested in it and the
        untracked files its .gitignore ignores."""
        root = repository.path
        nested = [other.path for other in self.repositories.values()
                  if other.path != root and other.path.is_relative_to(root)]
        patterns = ignore_patterns(root)
        files = {}
        for path in sorted(root.rglob("*")):
            name = path.relative_to(root).as_posix()
            if not path.is_file() or ".git" in path.relative_to(root).parts \
                    or any(path.is_relative_to(other) for other in nested):
                continue
            if name in repository.index or not ignored(name, patterns):
                files[name] = path.read_bytes()
        return files

    def git_check_ignore(self, call: Call) -> str:
        """`check-ignore [-q] <path>...`: the paths the root .gitignore ignores; exit 1 for none."""
        repository = self.find(call.where)
        patterns = ignore_patterns(repository.path)
        found = [path for path in call.args if not path.startswith("-")
                 if ignored((call.where / path).resolve().relative_to(repository.path).as_posix(), patterns)]
        if not found:
            raise Refusal(1, "")
        return "" if "-q" in call.args else "".join(f"{path}\n" for path in found)

    def git_commit(self, call: Call) -> str:
        """`commit [-q] [-a] [--allow-empty] -m <message>`, short flags combined as git takes them (`-qam`)."""
        repository = self.find(call.where)
        flags = "".join(a[1:] for a in call.args if a.startswith("-") and not a.startswith("--"))
        message = next(call.args[i + 1] for i, a in enumerate(call.args)
                       if a.startswith("-") and not a.startswith("--") and a.endswith("m"))
        if "a" in flags:  # every tracked file as it is now; new files stay untracked
            repository.index = {path: (repository.path / path).read_bytes() for path in repository.index
                                if (repository.path / path).is_file()}
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
            return f"{repository.common_dir}\n"
        if "--show-toplevel" in args:
            if repository.bare:
                raise Refusal(128, "fatal: this operation must be run in a work tree")
            return f"{repository.path}\n"
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

    def git_branch(self, call: Call) -> str:
        """`branch --show-current`, `branch -D <name>` (refused for a branch a worktree has out)."""
        repository = self.find(call.where)
        if call.args == ["--show-current"]:
            return repository.head.removeprefix("refs/heads/") + "\n" if repository.head.startswith("refs/") else ""
        if len(call.args) == 2 and call.args[0] in ("-D", "-d"):
            name = f"refs/heads/{call.args[1]}"
            if name not in repository.refs:
                raise Refusal(1, f"error: branch '{call.args[1]}' not found")
            if any(other.head == name for other in self.worktrees(repository)):
                raise Refusal(1, f"error: cannot delete branch '{call.args[1]}' used by worktree")
            del repository.refs[name]
            return ""
        raise Refusal(129, f"fake git: no `branch {' '.join(call.args)}`")

    def git_update_ref(self, call: Call) -> str:
        """`update-ref <ref> <new> [<old>]` and `update-ref -d <ref> [<old>]`: all zeros as `new`
        deletes the ref, as `old` requires that it does not exist; a ref not at `old` is refused."""
        repository = self.find(call.where)
        args = [a for a in call.args if a != "-d"]
        name, rest = args[0], args[1:]
        new, old = (None, rest[0] if rest else None) if "-d" in call.args else \
            (rest[0], rest[1] if len(rest) > 1 else None)
        if old is not None:
            current = repository.refs.get(name)
            expected = None if set(old) == {"0"} else self.resolve(repository, old)
            if current != expected:
                raise Refusal(128, f"fatal: update_ref failed for ref '{name}': cannot lock ref '{name}': "
                                   f"is at {current or '0' * 40} but expected {old}")
        if new is None or set(new) == {"0"}:
            repository.refs.pop(name, None)
        else:
            repository.refs[name] = self.resolve(repository, new)
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
            name = f"refs/heads/{args[1]}"
            if name in repository.refs:
                raise Refusal(128, f"fatal: a branch named '{args[1]}' already exists")
            start = self.resolve(repository, args[2]) if len(args) > 2 else self.head_commit(repository)
            if start is not None:
                repository.refs[name] = start
            repository.head = name
            if len(args) > 2:
                self.check_out(repository, self.commits[start].tree)
            return ""
        name = f"refs/heads/{args[0]}"
        if name not in repository.refs:
            raise Refusal(128, f"fatal: invalid reference: {args[0]}")
        repository.head = name
        self.check_out(repository, self.commits[repository.refs[name]].tree)
        return ""

    def git_checkout(self, call: Call) -> str:
        """`checkout [-q] -b <branch> [<start>]` and `checkout [-q] <branch>`, as `switch` does."""
        args = [a for a in call.args if a not in ("-q", "--quiet")]
        if args and args[0] == "-b":
            return self.git_switch(Call(call.where, call.options, call.env, ["-c", *args[1:]]))
        if len(args) == 1 and not args[0].startswith("-"):
            return self.git_switch(Call(call.where, call.options, call.env, args))
        raise Refusal(129, f"fake git: no `checkout {' '.join(call.args)}`")

    def git_rm(self, call: Call) -> str:
        """`rm [-q] [--cached] <path>...`: the paths leave the index, and without --cached the disk."""
        repository = self.find(call.where)
        for path in (a for a in call.args if not a.startswith("-")):
            name = (call.where / path).resolve().relative_to(repository.path).as_posix()
            if name not in repository.index:
                raise Refusal(128, f"fatal: pathspec '{path}' did not match any files")
            del repository.index[name]
            if "--cached" not in call.args:
                (repository.path / name).unlink(missing_ok=True)
        return ""

    def worktrees(self, repository: Repository) -> list[Repository]:
        """The main repository of `repository` and its linked worktrees, the main one first."""
        main = repository.main or repository
        return [main, *(other for other in self.repositories.values() if other.main is main)]

    def git_worktree(self, call: Call) -> str:
        """`worktree add [-b <branch>|--detach] <path> [<commit>]`, `worktree list --porcelain`,
        `worktree remove [--force] <path>`: a linked worktree shares its repository's refs."""
        repository = self.find(call.where)
        verb, *args = call.args
        if verb == "list" and args == ["--porcelain"]:
            out = []
            for tree in self.worktrees(repository):
                out.append(f"worktree {tree.path.as_posix()}\n")
                if tree.bare:
                    out.append("bare\n\n")
                    continue
                head = self.head_commit(tree)
                out.append(f"HEAD {head or '0' * 40}\n")
                out.append(f"branch {tree.head}\n\n" if tree.head.startswith("refs/") else "detached\n\n")
            return "".join(out)
        if verb == "add":
            branch, detach, positional, index = None, "--detach" in args, [], 0
            while index < len(args):
                if args[index] in ("-b", "-B"):
                    branch, index = args[index + 1], index + 2
                    continue
                if not args[index].startswith("-"):
                    positional.append(args[index])
                index += 1
            path = (call.where / positional[0]).resolve()
            if path.exists() and any(path.iterdir()):
                raise Refusal(128, f"fatal: '{positional[0]}' already exists")
            main = repository.main or repository
            start = positional[1] if len(positional) > 1 else "HEAD"
            if branch is None and not detach and len(positional) > 1 and f"refs/heads/{start}" in main.refs:
                head = f"refs/heads/{start}"
            elif branch is None and not detach:
                head = f"refs/heads/{path.name}"
            else:
                head = None if detach else f"refs/heads/{branch}"
            sha = self.resolve(repository, start)
            if head is not None and head != f"refs/heads/{start}":
                if head in main.refs:
                    raise Refusal(128, f"fatal: a branch named '{head.removeprefix('refs/heads/')}' already exists")
                main.refs[head] = sha
            if head is not None and any(tree.head == head for tree in self.worktrees(main)):
                raise Refusal(128, f"fatal: '{head.removeprefix('refs/heads/')}' is already used by worktree")
            path.mkdir(parents=True, exist_ok=True)
            tree = Repository(path, False, head=head or sha, refs=main.refs, config=main.config, main=main)
            tree.git_dir.mkdir(parents=True, exist_ok=True)
            (path / ".git").write_text(f"gitdir: {tree.git_dir.as_posix()}\n", encoding="utf-8")
            self.repositories[path] = tree
            self.check_out(tree, self.commits[sha].tree)
            return ""
        if verb == "remove":
            named = [a for a in args if not a.startswith("-")][0]
            path = (call.where / named).resolve()
            tree = self.repositories.get(path)
            if tree is None or tree.main is None:
                raise Refusal(128, f"fatal: '{named}' is not a working tree")
            if "--force" not in args and self.git_status(Call(path, {}, call.env, ["--porcelain"])):
                raise Refusal(128, f"fatal: '{named}' contains modified or untracked files, use --force to delete it")
            del self.repositories[path]
            shutil.rmtree(tree.git_dir, ignore_errors=True)
            shutil.rmtree(path)
            return ""
        raise Refusal(129, f"fake git: no `worktree {' '.join(call.args)}`")

    def git_merge(self, call: Call) -> str:
        repository = self.find(call.where)
        if "--abort" in call.args:
            repository.conflicts = []
            return ""
        messages = [call.args[i + 1] for i, a in enumerate(call.args) if a == "-m"]
        message = "\n\n".join(messages) if messages else "Merge"
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
            result = mine if mine == other or other == old else other if mine == old else \
                merged_lines(old, mine, other)
            if result is None:
                conflicts.append(path)
            else:
                merged[path] = result
        if conflicts:
            repository.conflicts = conflicts
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
        """`log [--first-parent] [--name-only] [-<n>|-n <n>|--max-count=<n>] --format=<f> [<rev>]`."""
        repository = self.find(call.where)
        args, limit, revs = list(call.args), None, []
        form = next(a.split("=", 1)[1] for a in args if a.startswith(("--format=", "--pretty=")))
        form = form.removeprefix("format:").removeprefix("tformat:")
        for index, argument in enumerate(args):
            if argument.startswith("--max-count="):
                limit = int(argument.partition("=")[2])
            elif argument == "-n":
                limit = int(args[index + 1])
            elif argument[1:].isdigit() and argument.startswith("-"):
                limit = int(argument[1:])
            elif not argument.startswith("-") and (index == 0 or args[index - 1] != "-n"):
                revs.append(argument)
        rev = self.resolve(repository, revs[0] if revs else "HEAD")
        if "--first-parent" in args:
            line = self.first_parents(rev)
        else:
            reachable = self.ancestors(rev)
            line = [sha for sha in reversed(self.commits) if sha in reachable]
        out = []
        for sha in line[:limit]:
            out.append(self.formatted(sha, form) + "\n")
            if "--name-only" in args:
                out.append("\n" + "".join(f"{path}\n" for path in self.changed(sha)))
        return "".join(out)

    def formatted(self, sha: str, form: str) -> str:
        commit = self.commits[sha]
        fields = {"H": sha, "h": sha[:7], "T": commit.tree, "P": " ".join(commit.parents),
                  "an": commit.author[0], "ae": commit.author[1],
                  "cn": commit.committer[0], "ce": commit.committer[1],
                  "aI": commit.author_date.isoformat(), "cI": commit.committer_date.isoformat(),
                  "at": str(int(commit.author_date.timestamp())),
                  "ct": str(int(commit.committer_date.timestamp())),
                  "s": commit.message.splitlines()[0], "B": commit.message,
                  "x00": "\0", "x09": "\t", "n": "\n"}
        out, index = [], 0
        while index < len(form):
            if form[index] == "%":
                key = next((k for k in sorted(fields, key=len, reverse=True) if form.startswith(k, index + 1)), None)
                if key is None:
                    raise Refusal(129, f"fake git: no log placeholder at {form[index:]!r}")
                out.append(fields[key])
                index += 1 + len(key)
            else:
                out.append(form[index])
                index += 1
        return "".join(out)

    def changed(self, sha: str) -> list[str]:
        """The paths commit `sha` changes against its first parent."""
        commit = self.commits[sha]
        new = self.trees[commit.tree]
        old = self.trees[self.commits[commit.parents[0]].tree] if commit.parents else {}
        return sorted(path for path in set(old) | set(new) if old.get(path) != new.get(path))

    def git_cat_file(self, call: Call) -> str:
        repository = self.find(call.where)
        if call.args[0] != "-e":
            raise Refusal(129, f"fake git: no `cat-file {call.args[0]}`")
        try:
            self.resolve(repository, call.args[1])
        except (Refusal, KeyError):
            raise Refusal(1, "")
        return ""

    def git_merge_base(self, call: Call) -> str:
        """`merge-base <a> <b>`, and `merge-base --is-ancestor <a> <b>`: exit 0 or 1."""
        repository = self.find(call.where)
        revs = [a for a in call.args if not a.startswith("-")]
        ours, theirs = (self.resolve(repository, rev) for rev in revs[:2])
        if "--is-ancestor" in call.args:
            if ours not in self.ancestors(theirs):
                raise Refusal(1, "")
            return ""
        base = self.merge_base(ours, theirs)
        if base is None:
            raise Refusal(1, "")
        return base + "\n"

    def merge_base(self, ours: str, theirs: str) -> str | None:
        common = self.ancestors(theirs)
        return next((sha for sha in self.first_parents(ours) if sha in common), None)

    def git_diff(self, call: Call) -> str:
        """`diff [--unified=<n>|-U<n>] <a>..<b>` (or `<a>...<b>`, from their merge base): git's
        unified diff of the two commits' files; `--name-status [-z]` the changed paths, a file moved
        unchanged as `R100`; `--name-only --diff-filter=U` the paths a failed merge left conflicted."""
        repository = self.find(call.where)
        if "--diff-filter=U" in call.args:
            return "".join(f"{path}\n" for path in repository.conflicts)
        spec = [a for a in call.args if not a.startswith("-")][0]
        old_rev, dots, new_rev = spec.partition("...")
        if not dots:
            old_rev, _, new_rev = spec.partition("..")
        old_sha, new_sha = (self.resolve(repository, rev) for rev in (old_rev, new_rev))
        if dots:
            old_sha = self.merge_base(new_sha, old_sha) or old_sha
        old, new = (self.trees[self.commits[sha].tree] for sha in (old_sha, new_sha))
        changed = [path for path in sorted(set(old) | set(new)) if old.get(path) != new.get(path)]
        if "--name-status" in call.args:
            return self.name_status(old, new, changed, "\0" if "-z" in call.args else "\n")
        context = next((int(a.split("=")[1]) for a in call.args if a.startswith("--unified=")),
                       next((int(a[2:]) for a in call.args if a.startswith("-U") and a[2:].isdigit()), 3))
        out = []
        for path in changed:
            before = old.get(path, b"").decode("utf-8", "replace").splitlines(keepends=True)
            after = new.get(path, b"").decode("utf-8", "replace").splitlines(keepends=True)
            out.append(f"diff --git a/{path} b/{path}\n")
            if path not in old:
                out.append("new file mode 100644\n")
            elif path not in new:
                out.append("deleted file mode 100644\n")
            out.extend(difflib.unified_diff(before, after, "/dev/null" if path not in old else f"a/{path}",
                                            "/dev/null" if path not in new else f"b/{path}", n=context))
        return "".join(out)

    def name_status(self, old: dict[str, bytes], new: dict[str, bytes], changed: list[str], end: str) -> str:
        """`--name-status` lines (`-z`: status and paths each ended by NUL); a deleted file whose
        content an added file has unchanged is a rename, `R100`. Git also finds renames of similar
        content; the fake only exact ones."""
        added = [path for path in changed if path not in old]
        deleted = [path for path in changed if path not in new]
        renamed = {}
        for gone in deleted:
            twin = next((path for path in added if new[path] == old[gone] and path not in renamed.values()), None)
            if twin is not None:
                renamed[gone] = twin
        out = []
        for path in changed:
            if path in renamed.values():
                continue
            if path in renamed:
                fields = ["R100", path, renamed[path]]
            else:
                fields = ["A" if path in added else "D" if path in deleted else "M", path]
            out.append(end.join(fields) + end if end == "\0" else "\t".join(fields) + end)
        return "".join(out)

    def git_ls_files(self, call: Call) -> str:
        repository = self.find(call.where)
        end = "\0" if "-z" in call.args else "\n"
        return "".join(f"{path}{end}" for path in sorted(repository.index))

    def git_status(self, call: Call) -> str:
        """`status --porcelain`: the working tree's changes against the index and HEAD."""
        repository = self.find(call.where)
        head = self.head_commit(repository)
        committed = self.trees[self.commits[head].tree] if head else {}
        present = self.on_disk(repository)
        end = "\0" if "-z" in call.args else "\n"
        untracked = "--untracked-files=no" not in call.args and "-uno" not in call.args
        out = []
        for path in sorted(set(committed) | set(repository.index) | set(present)):
            staged, work = repository.index.get(path), present.get(path)
            if path not in repository.index and path not in committed:
                if untracked:
                    out.append(f"?? {path}{end}")
                continue
            x = " " if staged == committed.get(path) else "A" if path not in committed else \
                "D" if staged is None else "M"
            y = " " if work == staged else "D" if work is None else "M"
            if x + y != "  ":
                out.append(f"{x}{y} {path}{end}")
        return "".join(out)

    def git_archive(self, call: Call) -> bytes:
        """`archive --format=tar <rev> [<path>...]`: the commit's files as a tar."""
        repository = self.find(call.where)
        rev, *paths = [a for a in call.args if not a.startswith("-")]
        files = self.trees[self.commits[self.resolve(repository, rev)].tree]
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode="w") as tar:
            for path in sorted(files):
                if paths and not any(path == p or path.startswith(p.rstrip("/") + "/") for p in paths):
                    continue
                member = tarfile.TarInfo(path)
                member.size, member.mode = len(files[path]), 0o644
                tar.addfile(member, io.BytesIO(files[path]))
        return buffer.getvalue()

    def git_clone(self, call: Call) -> str:
        """`clone [-b <branch>] [--depth <n>] [--no-local] <source> <destination>`: origin's branches
        as remote-tracking refs, its tags, and the branch (`-b`, else origin's HEAD) checked out."""
        args, branch, positional = list(call.args), None, []
        index = 0
        while index < len(args):
            argument = args[index]
            if argument in ("-b", "--branch", "--depth"):
                branch = args[index + 1] if argument != "--depth" else branch
                index += 2
                continue
            if not argument.startswith("-"):
                positional.append(argument)
            index += 1
        source, destination = positional
        try:
            origin = self.remote(Repository(Path(), False), str(call.where / source)
                                 if not source.startswith("file:") else source)
        except Refusal:
            raise Refusal(128, f"fatal: repository '{source}' does not exist")
        path = (call.where / destination).resolve()
        path.mkdir(parents=True, exist_ok=True)
        head = f"refs/heads/{branch}" if branch else origin.head
        if branch and head not in origin.refs:
            raise Refusal(128, f"fatal: Remote branch {branch} not found in upstream origin")
        repository = Repository(path, False, head=head)
        repository.git_dir.mkdir(exist_ok=True)
        repository.config["remote.origin.url"] = str(origin.path)
        self.repositories[path] = repository
        for ref, sha in origin.refs.items():
            if ref.startswith("refs/heads/"):
                repository.refs[f"refs/remotes/origin/{ref.removeprefix('refs/heads/')}"] = sha
            elif ref.startswith("refs/tags/"):
                repository.refs[ref] = sha
        if head in origin.refs:
            repository.refs[head] = origin.refs[head]
            self.check_out(repository, self.commits[origin.refs[head]].tree)
        return ""

    def git_ls_remote(self, call: Call) -> str:
        """`ls-remote [--heads] [--tags] [--refs] <remote> [<pattern>...]`: a remote's refs, the
        remote a URL, a path or a remote of the repository in the working directory; a pattern
        matches a ref's name whole or its last components."""
        url, *patterns = [a for a in call.args if not a.startswith("-")]
        try:
            try:
                remote = self.remote(self.find(call.where), url)
            except Refusal:
                remote = self.remote(Repository(Path(), False), url)
        except Refusal:
            raise Refusal(128, f"fatal: '{url}' does not appear to be a git repository")
        kinds = [prefix for flag, prefix in (("--heads", "refs/heads/"), ("--tags", "refs/tags/"))
                 if flag in call.args]
        refs = sorted(name for name in remote.refs if not kinds or name.startswith(tuple(kinds)))
        if patterns:
            refs = [name for name in refs if any(name == p or name.endswith("/" + p) for p in patterns)]
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
            if f"remote.{name}.url" in repository.config and destination.startswith("refs/heads/"):
                repository.refs[f"refs/remotes/{name}/{destination.removeprefix('refs/heads/')}"] = sha
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
            source, _, destination = spec.removeprefix("+").partition(":")
            if source not in remote.refs:
                raise Refusal(128, f"fatal: couldn't find remote ref {source}")
            repository.refs[destination or source] = remote.refs[source]
        return ""


def merged_lines(base: bytes | None, mine: bytes | None, theirs: bytes | None) -> bytes | None:
    """Both sides' line changes to one file, or None where they overlap or touch (git conflicts on
    adjacent changes too), or where one side deleted the file."""
    if base is None or mine is None or theirs is None:
        return None
    old = base.splitlines(keepends=True)
    changes = []
    for side in (mine, theirs):
        lines = side.splitlines(keepends=True)
        matcher = difflib.SequenceMatcher(None, old, lines, autojunk=False)
        changes += [(i1, i2, lines[j1:j2]) for tag, i1, i2, j1, j2 in matcher.get_opcodes() if tag != "equal"]
    changes.sort(key=lambda change: (change[0], change[1]))
    out, at = [], 0
    for index, (start, end, lines) in enumerate(changes):
        if index and start <= changes[index - 1][1]:
            return None
        out += old[at:start] + lines
        at = end
    return b"".join(out + old[at:])


def ignore_patterns(root: Path) -> list[str]:
    """The patterns of the repository's root .gitignore (the fake reads no other ignore file)."""
    ignore = root / ".gitignore"
    lines = ignore.read_text(encoding="utf-8").splitlines() if ignore.is_file() else []
    patterns = [line.strip() for line in lines if line.strip() and not line.startswith("#")]
    if any(pattern.startswith("!") for pattern in patterns):
        raise Refusal(129, "fake git: no negated .gitignore patterns")
    return patterns


def ignored(path: str, patterns: list[str]) -> bool:
    """Whether `path` (slash-separated, from the root) matches one of `patterns` as git matches
    them: `dir/` only directories, a pattern with an inner or leading slash only from the root,
    any other at any depth; `*` and `?` stay within one name."""
    parts = path.split("/")
    for pattern in patterns:
        directory = pattern.endswith("/")
        body = pattern.rstrip("/")
        anchored = "/" in body
        body = body.lstrip("/")
        for depth in range(1, len(parts) + 1):
            if directory and depth == len(parts):
                continue  # the file itself is no directory
            candidate = "/".join(parts[:depth]) if anchored else parts[depth - 1]
            if fnmatch.fnmatchcase(candidate, body):
                return True
    return False


def date(call: Call, role: str) -> datetime:
    """The commit's author or committer date: GIT_<role>_DATE (ISO 8601), else now."""
    given = call.env.get(f"GIT_{role}_DATE")
    if not given:
        return datetime.now(timezone.utc).astimezone().replace(microsecond=0)
    when = datetime.fromisoformat(given.replace("Z", "+00:00"))
    return when if when.tzinfo else when.astimezone()


@dataclass(frozen=True)
class Call:
    where: Path
    options: dict[str, str]
    env: dict[str, str]
    args: list[str]


def _bytes(data: str | bytes) -> bytes:
    return data if isinstance(data, bytes) else data.encode("utf-8")
