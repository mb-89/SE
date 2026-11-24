# se:template se/python-module 1.0.0
"""Component versions assigned at the landing (docs/settings.md "Component versions").

A work branch that changes the `se` binary states its release kind in its field report,
`**Component kinds:** se patch`, and leaves its `release.toml` version alone;
`work_tickets.py integrate` writes the next version of that kind, from the integration branch's
versions at that moment, into the landing's merge. A branch that still claims a number in its
`release.toml` is landed too: the claim gives the kind, and the number is replaced by the next free
one of that kind. The binary's folder is its inputs: for SE `components/`, where `go.mod`'s
`require kern` is the kern it is built on (se.toml [components.kern]), so a move of that pin is a
change of `se`. kern releases from kern's own repository.

Every other file that pins a component's release tag, `PINS`, moves with its number in the same
merge, so the landing never leaves a pin at the old tag. None does today.

The logic is pure, `claimed_kind`, `assigned_versions` and `moved_pins`: versions, kinds and file
texts in, versions and file texts out; `assign` is the wiring that reads them through git's door
and writes the files.
"""

from __future__ import annotations

import re
import tomllib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import git_door

KINDS = ("patch", "minor", "major")
# The field report's header line; optional, as a branch that changes no component states none.
KINDS_PATTERN = re.compile(r"\*\*Component kinds:\*\*[ \t]*([^\n<]*)")
COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)  # the template's own example is no statement
# What kern's release guard reads on a work branch (kern/tools/release, KindsVariable).
ENVIRONMENT = "SE_COMPONENT_KINDS"
VERSION_LINE = re.compile(r"""^(\s*version\s*=\s*)(["'])[^"'\n]*\2""", re.MULTILINE)

Version = tuple[int, int, int]

# The one list of files that pin a component's release tag as `@<tag>`, by component, relative to
# the checkout root: the landing moves each pin with the number it assigns (`moved_pins`), and
# tests/test_component_versions.py fails where another file pins a current tag (`unlisted_pins`).
PINS: dict[str, tuple[str, ...]] = {
    "se": (),
}


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
    """`se patch, app minor` as {component: kind}; refused naming an entry it cannot read."""
    kinds: dict[str, str] = {}
    for entry in filter(None, (part.strip() for part in value.split(" — ")[0].split(","))):
        parts = entry.split()
        if len(parts) != 2 or parts[1] not in KINDS:
            raise VersionError(f"Component kinds entry {entry!r} is no <component> patch|minor|major")
        kinds[parts[0]] = parts[1]
    return kinds


def stated_kinds(report_body: str | None) -> dict[str, str]:
    """The kinds a field report's header (above its first section) states; none where it has no
    Component kinds line."""
    header = re.split(r"^## ", COMMENT.sub("", report_body or ""), maxsplit=1, flags=re.MULTILINE)[0]
    match = KINDS_PATTERN.search(header)
    return parse_kinds(match[1]) if match else {}


def kinds_problems(report_body: str) -> list[str]:
    """Where the field report's Component kinds line cannot be read, for field-report --check."""
    try:
        stated_kinds(report_body)
    except VersionError as error:
        return [f"header (above the first section): {error}; write **Component kinds:** "
                "<component> patch|minor|major, comma-separated, as se patch"]
    return []


def environment_value(kinds: dict[str, str]) -> str:
    """The kinds as the release guard reads them: `app=minor,se=patch`."""
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
    name: str     # the binary, the release.toml's `binary` (kern where it names none)
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


def pin_pattern(component: Component, version: Version | None = None) -> re.Pattern[str]:
    """The component's release tag as a pin, `@kern-v<version>`: of `version`, or of any version."""
    number = re.escape(text(version)) if version else r"\d+\.\d+\.\d+"
    tag = re.escape(component.tag).replace(re.escape("{version}"), number)
    return re.compile(rf"@{tag}(?![\w-]|\.\d)")


def moved_pins(component: Component, texts: dict[str, str], version: Version) -> dict[str, str]:
    """The listed files of `texts` ({path: text}) that pin the component at another version than
    `version`, with every such pin moved to it; the rest of each text byte for byte."""
    pin = f"@{tag_of(component, version)}"
    moved = {path: pin_pattern(component).sub(pin, content) for path, content in texts.items()
             if path in PINS.get(component.name, ())}
    return {path: content for path, content in moved.items() if content != texts[path]}


def unlisted_pins(component: Component, version: Version, texts: dict[str, str]) -> list[str]:
    """The files of `texts` ({path: text}) that pin the component's current `version` but are
    not in `PINS`, so the landing would leave them at the old tag: sorted."""
    listed = {component.path, *PINS.get(component.name, ())}
    pattern = pin_pattern(component, version)
    return sorted(path for path, content in texts.items()
                  if path not in listed and pattern.search(content))


def release_tag(content: str) -> str:
    """The tag a release.toml's download names, `{version}` unfilled: its URL's last part."""
    download = tomllib.loads(content).get("download")
    return download.rsplit("/", 1)[-1] if isinstance(download, str) else "{version}"


def components(root: Path, ref: str) -> list[Component]:
    """The binary the checkout releases at `ref`: the one se.toml `[binary] release` names (SE's
    `se`), its folder its inputs."""
    found: list[Component] = []
    manifest = show(root, ref, "se.toml")
    binary = tomllib.loads(manifest).get("binary", {}) if manifest else {}
    release = binary.get("release") if isinstance(binary, dict) else None
    content = show(root, ref, release) if isinstance(release, str) else None
    if content is not None:
        name = tomllib.loads(content).get("binary") or "kern"
        folder = Path(release).parent.as_posix()
        found.append(Component(str(name), release, (folder,), release_tag(content)))
    return found


def changed(root: Path, base: str, component: Component) -> bool:
    """Whether the checkout's index differs from `base` under the component's folders."""
    return git_door.run("diff", "--cached", "--quiet", base, "--", *component.folders,
                        root=root).returncode != 0


def merge_past_claims(root: Path, conflicted: list[str], base: str, head: str, landing: str,
                      message: str, regenerated: Callable[[str], bool] = lambda path: False) -> bool:
    """Merge `head` onto `base` on `landing` where the only conflicts are component release.tomls,
    and the files that pin them (`PINS`), as where the branch claimed another number than the
    integration branch moved to, and generated files the merge regenerates (`regenerated`, those
    generated.yaml gives a `regenerate`): the failed merge is aborted, `head` gets a commit on
    `landing` that takes the integration branch's version in each such file (`assign` replaces a
    version next, the merge's regeneration a generated file), and that commit is merged. False,
    the failed merge aborted, where a conflict remains or another file conflicts."""
    owners = {path: component for component in components(root, base)
              for path in (component.path, *PINS.get(component.name, ()))}
    generated = [path for path in conflicted if path not in owners and regenerated(path)]
    if not conflicted or not set(conflicted) <= set(owners) | set(generated):
        return False
    git_door.run("merge", "--abort", root=root)
    if git_door.run("switch", "-q", "-C", landing, head, root=root).returncode != 0:
        return False
    for path in conflicted:
        if path in generated:
            taken = show(root, base, path)
            if taken is None:
                return False
        else:
            component = owners[path]
            version = read_version(show(root, base, component.path), f"{component.path} at {base[:12]}")
            theirs = show(root, head, path)
            if version is None or theirs is None:
                return False
            taken = (with_version(theirs, version) if path == component.path
                     else moved_pins(component, {path: theirs}, version).get(path, theirs))
        (root / path).write_bytes(taken.encode("utf-8"))
        git_door.run("add", "--", path, root=root)
    what = [*(["component versions; the landing assigns the next"] if set(conflicted) - set(generated) else []),
            *(["generated files; the merge regenerates them"] if generated else [])]
    taken = git_door.run("commit", "-q", "-m", "Take the integration branch's " + ", and its ".join(what),
                         root=root)
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
    states, else of the kind the branch claims by its own raised number, and move the files that
    pin it (`PINS`) to the new tag. A component the merge leaves unchanged gets none. The
    assignments, in the order of `components`."""
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
        pinned = {name: (root / name).read_bytes().decode("utf-8")
                  for name in PINS.get(component.name, ()) if (root / name).is_file()}
        for name, content in moved_pins(component, pinned, versions[component.name]).items():
            (root / name).write_bytes(content.encode("utf-8"))
            git_door.run("add", "--", name, root=root)
        assignments.append(Assignment(component, kinds[component.name], main[component.name],
                                      versions[component.name], claims.get(component.name)))
    return assignments
