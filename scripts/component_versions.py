"""Component versions assigned at the landing (README "Component versions").

A work branch that changes kern or the `se` binary states the release kind of each in its field
report, `**Component kinds:** se patch, kern minor`, and leaves their `release.toml` versions alone;
`work_tickets.py integrate` writes the next version of that kind, from the integration branch's
versions at that moment, into the landing's merge. A branch that still claims a number in its
`release.toml` is landed too: the claim gives the kind, and the number is replaced by the next free
one of that kind.

The logic is pure, `claimed_kind` and `assigned_versions`: versions and kinds in, versions out;
`assign` is the wiring that reads them through git's door and writes the files.
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

import git_door

KINDS = ("patch", "minor", "major")
# The field report's header line; optional, as a branch that changes no component states none.
KINDS_PATTERN = re.compile(r"\*\*Component kinds:\*\*[ \t]*([^\n<]*)")
COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)  # the template's own example is no statement
# What kern's release guard reads on a work branch (kern/tools/release, KindsVariable).
ENVIRONMENT = "SE_COMPONENT_KINDS"
KERN_RELEASE = "kern/release.toml"
VERSION_LINE = re.compile(r"""^(\s*version\s*=\s*)(["'])[^"'\n]*\2""", re.MULTILINE)

Version = tuple[int, int, int]


class VersionError(Exception):
    """A stated kind, a release.toml or a claim the landing cannot assign from."""


def bumped(version: Version, kind: str) -> Version:
    major, minor, patch = version
    return {
        "major": (major + 1, 0, 0), "minor": (major, minor + 1, 0), "patch": (major, minor, patch + 1),
    }[kind]


def text(version: Version) -> str:
    return ".".join(map(str, version))


def parse_kinds(value: str) -> dict[str, str]:
    """`se patch, kern minor` as {component: kind}; refused naming an entry it cannot read."""
    kinds: dict[str, str] = {}
    for entry in filter(None, (part.strip() for part in value.split(" — ")[0].split(","))):
        parts = entry.split()
        if len(parts) != 2 or parts[1] not in KINDS:
            raise VersionError(f"Component kinds entry {entry!r} is no <component> patch|minor|major")
        kinds[parts[0]] = parts[1]
    return kinds


def stated_kinds(report_body: str | None) -> dict[str, str]:
    """The kinds a field report's header states; none where it has no Component kinds line."""
    match = KINDS_PATTERN.search(COMMENT.sub("", report_body or ""))
    return parse_kinds(match[1]) if match else {}


def kinds_problems(report_body: str) -> list[str]:
    """Where the field report's Component kinds line cannot be read, for field-report --check."""
    try:
        stated_kinds(report_body)
    except VersionError as error:
        return [f"header (above the first section): {error}; write **Component kinds:** "
                "<component> patch|minor|major, comma-separated, as se patch, kern minor"]
    return []


def environment_value(kinds: dict[str, str]) -> str:
    """The kinds as the release guard reads them: `se=patch,kern=minor`."""
    return ",".join(f"{name}={kind}" for name, kind in sorted(kinds.items()))


def claimed_kind(base: Version, claimed: Version) -> str | None:
    """The kind a branch claims by raising `base` to `claimed` in its release.toml: the highest part
    it changed; None where it raised nothing."""
    if claimed <= base:
        return None
    return "major" if claimed[0] != base[0] else "minor" if claimed[1] != base[1] else "patch"


def assigned_versions(main: dict[str, Version], kinds: dict[str, str]) -> dict[str, Version]:
    """The version each component gets at the landing: the next one of its kind after the
    integration branch's `main` version. A kind for a component `main` has no version of is
    refused, naming the components there are."""
    unknown = sorted(set(kinds) - set(main))
    if unknown:
        raise VersionError(
            f"Component kinds name {', '.join(unknown)}, which the integration branch has no "
            f"release.toml of; its components are {', '.join(sorted(main)) or 'none'}")
    return {name: bumped(main[name], kind) for name, kind in kinds.items()}


@dataclass(frozen=True)
class Component:
    name: str     # the binary: kern, or the release.toml's `binary`
    path: str     # its release.toml, relative to the checkout root
    folders: tuple[str, ...]  # what a change to marks the component changed
    tag: str = "{version}"  # its release tag, `{version}` unfilled: the download URL's last part


@dataclass(frozen=True)
class Assignment:
    component: Component
    kind: str
    old: Version          # the integration branch's
    new: Version
    claimed: Version | None  # the number the branch wrote, where it wrote one

    def line(self) -> str:
        name, tag = self.component.name, tag_of(self.component, self.new)
        how = "stated" if self.claimed is None else f"claimed {text(self.claimed)}"
        if self.claimed is not None and self.claimed != self.new:
            how += f", replaced by the next free {self.kind} version"
        return (f"Component version: {name} {text(self.old)} -> {text(self.new)} ({self.kind}, "
                f"{how}); the push to the integration branch cuts {tag}")


def show(root: Path, ref: str, path: str) -> str | None:
    """The file `path` at `ref` (a stage `:2` among them), or None where it has none."""
    result = git_door.run("show", f"{ref}:{path}", root=root)
    return result.stdout if result.returncode == 0 else None


def read_version(content: str | None, where: str) -> Version | None:
    if content is None:
        return None
    try:
        version = tomllib.loads(content).get("version")
    except tomllib.TOMLDecodeError as error:
        raise VersionError(f"{where}: {error}") from error
    match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", version) if isinstance(version, str) else None
    if match is None:
        raise VersionError(f"{where}: version {version!r} is no MAJOR.MINOR.PATCH")
    return int(match[1]), int(match[2]), int(match[3])


def with_version(content: str, version: Version) -> str:
    """`content` with only its version line's value replaced, the rest byte for byte."""
    return VERSION_LINE.sub(lambda match: f"{match[1]}{match[2]}{text(version)}{match[2]}",
                            content, count=1)


def tag_of(component: Component, version: Version) -> str:
    """The tag the component's release.toml download names for `version`: its URL's last part."""
    return component.tag.replace("{version}", text(version))


def components(root: Path, ref: str) -> list[Component]:
    """The binaries the checkout releases at `ref`: kern where it incubates it
    (`kern/release.toml`) and the binary se.toml `[binary] release` names (SE's `se`)."""
    found: list[Component] = []

    def tag(content: str) -> str:
        download = tomllib.loads(content).get("download")
        return download.rsplit("/", 1)[-1] if isinstance(download, str) else "{version}"

    kern = show(root, ref, KERN_RELEASE)
    core = ("kern",) if kern is not None else ()
    if kern is not None:
        found.append(Component("kern", KERN_RELEASE, core, tag(kern)))
    manifest = show(root, ref, "se.toml")
    binary = tomllib.loads(manifest).get("binary", {}) if manifest else {}
    release = binary.get("release") if isinstance(binary, dict) else None
    content = show(root, ref, release) if isinstance(release, str) else None
    if content is not None:
        name = tomllib.loads(content).get("binary") or "kern"
        folder = Path(release).parent.as_posix()
        found.append(Component(str(name), release, (folder, *core), tag(content)))
    return found


def changed(root: Path, base: str, component: Component) -> bool:
    """Whether the checkout's index differs from `base` under the component's folders."""
    return git_door.run("diff", "--cached", "--quiet", base, "--", *component.folders,
                        root=root).returncode != 0


def merge_past_claims(root: Path, conflicted: list[str], base: str, head: str, landing: str,
                      message: str) -> bool:
    """Merge `head` onto `base` on `landing` where the only conflicts are component release.tomls,
    as where the branch claimed another number than the integration branch moved to: the failed
    merge is aborted, `head` gets a commit on `landing` that takes the integration branch's
    version in each such file (`assign` replaces it next), and that commit is merged. False, the
    failed merge aborted, where a conflict remains or another file conflicts."""
    paths = {component.path for component in components(root, base)}
    if not conflicted or not set(conflicted) <= paths:
        return False
    git_door.run("merge", "--abort", root=root)
    if git_door.run("switch", "-q", "-C", landing, head, root=root).returncode != 0:
        return False
    for path in conflicted:
        version = read_version(show(root, base, path), f"{path} at {base[:12]}")
        theirs = show(root, head, path)
        if version is None or theirs is None:
            return False
        (root / path).write_bytes(with_version(theirs, version).encode("utf-8"))
        git_door.run("add", "--", path, root=root)
    taken = git_door.run("commit", "-q", "-m", "Take the integration branch's component versions; "
                         "the landing assigns the next", root=root)
    adjusted = git_door.run("rev-parse", "HEAD", root=root).stdout.strip()
    git_door.run("switch", "-q", "-C", landing, base, root=root)
    if taken.returncode != 0:
        return False
    merged = git_door.run("merge", "--no-ff", "-m", message, adjusted, root=root)
    if merged.returncode != 0:
        git_door.run("merge", "--abort", root=root)
        return False
    return True


def assign(root: Path, base: str, head: str, report_body: str | None) -> list[Assignment]:
    """Write the next version of each changed component into the checkout's index, a merge of
    the branch at `head` onto the integration branch at `base`: of the kind the field report
    states, else of the kind the branch claims by its own raised number. A component the merge
    leaves unchanged gets none. The assignments, in the order of `components`."""
    stated = stated_kinds(report_body)
    found = components(root, base)
    main = {component.name: read_version(show(root, base, component.path),
                                         f"{component.path} at {base[:12]}")
            for component in found}
    main = {name: version for name, version in main.items() if version is not None}
    assigned_versions(main, stated)  # refuses a stated kind for no component
    fork = git_door.run("merge-base", base, head, root=root).stdout.strip()
    kinds, claims = {}, {}
    for component in found:
        if component.name not in main or not changed(root, base, component):
            continue
        claimed = read_version(show(root, head, component.path), f"{component.path} at {head[:12]}")
        before = read_version(show(root, fork, component.path), component.path) if fork else None
        claim = claimed_kind(before, claimed) if before and claimed else None
        kind = stated.get(component.name) or claim
        if kind is None:
            continue
        kinds[component.name] = kind
        if claim is not None:
            claims[component.name] = claimed
    versions = assigned_versions(main, kinds)
    assignments = []
    for component in found:
        if component.name not in versions:
            continue
        path = root / component.path
        path.write_bytes(with_version(path.read_bytes().decode("utf-8"),
                                      versions[component.name]).encode("utf-8"))
        git_door.run("add", "--", component.path, root=root)
        assignments.append(Assignment(component, kinds[component.name], main[component.name],
                                      versions[component.name], claims.get(component.name)))
    return assignments
