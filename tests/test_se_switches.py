"""SE's switch table and its read-only view (scripts/se_switches.py): every file of the table holds
to the format, `in_effect` follows each row's layers, each first row's default is what its real
reader does with nothing set, and the command prints no value and writes nothing."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

import se_switches  # scripts/ is on the path (tests/conftest.py)

ROOT = Path(__file__).resolve().parents[1]
FIRST_ROWS = ("SE_KERN", "SE_GIT_DOOR", "enabled", "builtin", "off:<label>",
              "[project] public_check", "[overhaul] due_after", "[tests] trust_integrator")

FIXTURE = """
[[switch]]
name = "SE_X"
kind = "environment"
reader = "scripts/se_switches.py"
default = "off"
layers = ["environment", "local", "se.toml"]
key = "x.on"
on = ["1"]
off = ["0"]
help = "README.md"

[[switch]]
name = "count"
kind = "se.toml"
reader = "scripts/se_switches.py"
default = "off"
layers = ["se.toml"]
key = "x.count"
off = [0]
other = "on"
help = "README.md"

[[switch]]
name = "enabled"
kind = "wiring-instance"
reader = "kern/index/wiring.go"
default = "on"
layers = ["wiring", "wiring-overlay"]
key = "enabled"
help = "README.md"

[[switch]]
name = "off:<label>"
kind = "local-file"
reader = "scripts/public_check.py"
default = "off"
layers = ["public-check-local"]
help = "README.md"

[[not_switch]]
name = "SE_ROOT"
why = "a path"
"""


def table() -> se_switches.Table:
    return se_switches.parse({"fixture.toml": FIXTURE})


def effects(environment=None, local=None, project=None, wiring=None, overlay=None, public=()):
    found = se_switches.in_effect(table(), environment or {}, local or {}, project or {},
                                  wiring or {}, overlay or {}, public)
    return {(effect.name, effect.member): (effect.state, effect.layer) for effect in found}


# The table: every file of the folder.

def anchors(path: Path) -> set[str]:
    """The heading anchors of a Markdown file, as GitHub writes them."""
    heads = re.findall(r"^#+ (.+)$", path.read_text(encoding="utf-8"), re.MULTILINE)
    return {re.sub(r"[^\w\- ]", "", head.lower()).replace(" ", "-") for head in heads}


def test_every_table_file_parses_names_real_readers_and_no_name_twice():
    assert "core.toml" in {path.name for path in se_switches.TABLE.glob("*.toml")}
    loaded = se_switches.load()  # parse refuses a name used twice, across files too
    names = [switch.name for switch in loaded.switches] + list(loaded.not_switches)
    assert len(names) == len(set(names))
    for switch in loaded.switches:
        assert (ROOT / switch.reader).is_file(), f"{switch.name}: no reader {switch.reader}"
        target, _, anchor = switch.help.partition("#")
        assert (ROOT / target).is_file(), f"{switch.name}: no help file {target}"
        if anchor and target.endswith(".md"):
            assert anchor in anchors(ROOT / target), f"{switch.name}: no section {switch.help}"


def test_the_first_rows_are_in_core():
    core = se_switches.parse({"core.toml": (se_switches.TABLE / "core.toml").read_text(encoding="utf-8")})
    assert [switch.name for switch in core.switches] == list(FIRST_ROWS)
    assert "SE_ROOT" in core.not_switches


def test_a_name_in_two_files_is_refused():
    with pytest.raises(se_switches.TableError, match="named in a.toml already"):
        se_switches.parse({"a.toml": FIXTURE, "b.toml": FIXTURE})


@pytest.mark.parametrize("change", [
    ('kind = "environment"', 'kind = "rumour"'),
    ('default = "off"', 'default = "maybe"'),
    ('layers = ["environment", "local", "se.toml"]', 'layers = ["moon"]'),
    ('key = "x.on"\n', ''),
    ('help = "README.md"', 'helps = "README.md"'),
])
def test_a_row_that_breaks_the_format_is_refused(change):
    with pytest.raises(se_switches.TableError):
        se_switches.parse({"bad.toml": FIXTURE.replace(*change, 1)})


# in_effect: each layer answers in turn.

def test_with_nothing_set_every_row_gives_its_default():
    found = se_switches.in_effect(se_switches.load(), {}, {}, {}, {}, {}, ())
    defaults = {switch.name: switch.default for switch in se_switches.load().switches}
    assert {effect.name for effect in found} == set(defaults)
    for effect in found:
        assert (effect.state, effect.layer) == (defaults[effect.name], "default")


def test_the_first_layer_of_the_row_answers():
    local, project = {"x": {"on": True}}, {"x": {"on": False}}
    assert effects({"SE_X": "1"}, local, project)[("SE_X", "")] == ("on", "environment")
    assert effects({"SE_X": "0"}, local, project)[("SE_X", "")] == ("off", "environment")
    assert effects({}, local, project)[("SE_X", "")] == ("on", "local")
    assert effects({}, {}, project)[("SE_X", "")] == ("off", "se.toml")
    assert effects({"SE_X": "weird"})[("SE_X", "")] == ("set", "environment")
    assert effects({"SE_OTHER": None})[("SE_X", "")] == ("off", "default")


def test_a_value_outside_the_lists_takes_the_rows_other_state():
    assert effects(project={"x": {"count": 0}})[("count", "")] == ("off", "se.toml")
    assert effects(project={"x": {"count": 3}})[("count", "")] == ("on", "se.toml")
    assert effects(project={"x": {"count": False}})[("count", "")] == ("off", "se.toml")


def test_wiring_instances_answer_from_their_file_or_the_default():
    wiring = {"instances": {"a": {"component": "c"}, "b": {"component": "c", "enabled": False}}}
    overlay = {"instances": {"ad-hoc": {"component": "c", "enabled": True}}}
    found = effects(wiring=wiring, overlay=overlay)
    assert found[("enabled", "a")] == ("on", "default")
    assert found[("enabled", "b")] == ("off", "wiring")
    assert found[("enabled", "ad-hoc")] == ("on", "wiring-overlay")


def test_wires_answer_from_their_table_or_the_default():
    wiring = {"wires": {"a.x": "b.y", "c.x": {"to": "d.y", "builtin": True}}}
    found = se_switches.in_effect(se_switches.load(), {}, {}, {}, wiring, {}, ())
    wires = {effect.member: (effect.state, effect.layer) for effect in found if effect.name == "builtin"}
    assert wires == {"a.x": ("off", "default"), "c.x": ("on", "wiring")}


def test_the_local_public_check_list_switches_each_label():
    found = effects(public={"user-path", "email"})
    assert found[("off:<label>", "email")] == ("on", "public-check-local")
    assert found[("off:<label>", "user-path")] == ("on", "public-check-local")
    assert ("off:<label>", "") not in found


def test_in_effect_reads_no_file_or_environment(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SE_X", "1")
    (tmp_path / "se.toml").write_text('[x]\non = true\n', encoding="utf-8")
    assert effects()[("SE_X", "")] == ("off", "default")


# Each first row's default is what its real reader does with nothing set.

def default_of(name: str) -> se_switches.Switch:
    return next(switch for switch in se_switches.load().switches if switch.name == name)


def test_se_kern_default_routes_through_kern_where_it_serves(monkeypatch, tmp_path):
    import se_components

    asked: list[Path] = []
    monkeypatch.setattr(se_components, "kern_root", lambda start: asked.append(start))
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("SE_KERN", raising=False)
    assert se_components.routed(tmp_path / "x.py", ["status"], [], interactive=True) is None
    assert asked, "with SE_KERN unset, routed looks for a kern to answer"
    monkeypatch.setenv("SE_KERN", "off")
    asked.clear()
    se_components.routed(tmp_path / "x.py", ["status"], [], interactive=True)
    assert not asked
    switch = default_of("SE_KERN")
    assert switch.default == "on" and se_switches.state(switch, "OFF") == "off"


def test_se_git_door_default_is_the_real_git():
    import git_door

    switch = default_of("SE_GIT_DOOR")
    assert type(git_door.from_environment({})) is git_door.RealGit
    assert type(git_door.from_environment({"SE_GIT_DOOR": "real"})) is git_door.RealGit
    assert switch.default == "off" and se_switches.state(switch, "real") == "off"
    assert se_switches.state(switch, "refused") == "set"


WIRING_GO = ROOT / "kern" / "index" / "wiring.go"


def test_an_instance_is_enabled_unless_it_says_otherwise():
    """kern's Go reader (kern/index/wiring_test.go holds it) starts each instance enabled."""
    source = WIRING_GO.read_text(encoding="utf-8")
    assert "in := Instance{Name: name, Enabled: true," in source
    assert default_of("enabled").default == "on"


def test_a_wire_is_builtin_only_where_it_says_so():
    """kern's Go reader sets Builtin only from a wire's own `builtin` key; its zero is false."""
    source = WIRING_GO.read_text(encoding="utf-8")
    assert re.findall(r"\bwr\.Builtin = \w+", source) == ["wr.Builtin = b"]
    assert 'case "builtin":' in source
    assert default_of("builtin").default == "off"


def test_no_local_list_switches_no_public_entry_off(tmp_path):
    import public_check

    assert public_check.load_local(tmp_path) is None
    (tmp_path / public_check.LOCAL_FILE).write_text("# nothing off\n", encoding="utf-8")
    assert public_check.load_local(tmp_path).off == set()
    assert default_of("off:<label>").default == "off"


def test_public_check_is_on_without_se_toml(tmp_path):
    import work_tickets

    assert work_tickets.public_check_enabled(tmp_path) is True
    assert default_of("[project] public_check").default == "on"


def test_the_overhaul_countdown_is_off_without_se_toml(tmp_path):
    import overhaul

    switch = default_of("[overhaul] due_after")
    assert overhaul.due_after(tmp_path) == 0
    assert switch.default == "off" and se_switches.state(switch, 0) == "off"


def test_trust_integrator_is_off_without_se_toml(tmp_path):
    import ci_trust

    assert ci_trust.trust_settings(tmp_path).on is False
    assert default_of("[tests] trust_integrator").default == "off"


# The command: read-only, prints no value.

SECRET = "tok-3f9c-not-to-be-printed"


def tree(path: Path) -> dict[str, bytes]:
    return {p.relative_to(path).as_posix(): p.read_bytes() for p in sorted(path.rglob("*")) if p.is_file()}


@pytest.mark.parametrize("arguments", [[], ["--json"], ["--drift"], ["--json", "--drift"]])
def test_the_command_prints_no_value_and_writes_nothing(monkeypatch, tmp_path, capsys, arguments):
    root, home = tmp_path / "repo", tmp_path / "home"
    (root / ".se").mkdir(parents=True)
    (home / ".se").mkdir(parents=True)
    (root / "se.toml").write_text(f'[project]\npublic_check = false\nidentity = "{SECRET}"\n',
                                  encoding="utf-8")
    (root / "wiring.toml").write_text('[instances.a]\ncomponent = "c"\nenabled = false\n',
                                      encoding="utf-8")
    (root / ".se" / "wiring.toml").write_text('[wires]\n"a.x" = { to = "b.y", builtin = true }\n',
                                              encoding="utf-8")
    (root / ".public-check.local").write_text(f"{SECRET}\noff:user-profile-path  # a reason\n",
                                              encoding="utf-8")
    (home / ".se" / "local.toml").write_text(f'token = "{SECRET}"\n', encoding="utf-8")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("SE_GIT_DOOR", f"fake:{SECRET}")
    monkeypatch.setenv("SE_KERN", "off")
    monkeypatch.setenv("SE_UNLISTED", SECRET)
    before = tree(tmp_path)
    assert se_switches.main([*arguments, "--root", str(root)]) == 0
    out = capsys.readouterr()
    printed = out.out + out.err
    assert tree(tmp_path) == before
    assert SECRET not in printed
    assert str(tmp_path) not in printed and tmp_path.as_posix() not in printed
    if "--json" in arguments:
        found = {(effect["name"], effect["member"]): (effect["state"], effect["layer"])
                 for effect in json.loads(out.out)["switches"]}
        assert found[("SE_KERN", "")] == ("off", "environment")
        assert found[("SE_GIT_DOOR", "")] == ("set", "environment")
        assert found[("enabled", "a")] == ("off", "wiring")
        assert found[("builtin", "a.x")] == ("on", "wiring-overlay")
        assert found[("off:<label>", "user-profile-path")] == ("on", "public-check-local")
        assert found[("[project] public_check", "")] == ("off", "se.toml")


DRIFT_FIXTURE = FIXTURE + """
[[not_switch]]
name = "[modules]"
why = "values"

[[not_switch]]
name = "[tests] beside"
why = "suites"

[[not_switch]]
name = "[outside]"
why = "values"
"""


def test_the_drift_list_names_what_no_table_file_names():
    texts = ['x = "SE_X"', 'x = "SE_NEW_THING"', 'echo "${SE_SHELL:-}"', "$env:SE_PS",
             'SE_ROOT = Path(".")', 'y = "SE_ROOT"']
    found = se_switches.drift(se_switches.parse({"fixture.toml": DRIFT_FIXTURE}), texts,
                              {"x": {"count": 1, "name": "x"}, "tests": {"command": []}})
    assert found == {"environment": ["SE_NEW_THING", "SE_PS", "SE_SHELL"],
                     "se.toml": ["tests.command", "x.name"]}


def test_the_key_notation_parses():
    loaded = se_switches.parse({"fixture.toml": DRIFT_FIXTURE})
    assert {"[modules]", "[tests] beside", "[outside]"} <= set(loaded.not_switches)
    assert set(loaded.covers()) == {"modules", "tests.beside", "outside"}


def test_drift_leaves_out_covered_keys_and_keeps_a_sibling():
    project = {"modules": {"obs": {"url": "u", "version": "^1"}},
               "tests": {"beside": {"kern": {"command": []}}, "beside_x": 1, "shards": 2},
               "outside": {"SE": 1}, "outside-text": {"envelope": True}}
    found = se_switches.drift(se_switches.parse({"fixture.toml": DRIFT_FIXTURE}), [], project)
    assert found["se.toml"] == ["outside-text.envelope", "tests.beside_x", "tests.shards"]


@pytest.mark.parametrize("name", ["tests.command", "[tests", "[tests] ", "SE_lower", "[] key"])
def test_a_bad_not_switch_name_is_refused_naming_its_file_and_number(name):
    text = FIXTURE + f'\n[[not_switch]]\nname = "{name}"\nwhy = "x"\n'
    with pytest.raises(se_switches.TableError, match=r"^bad\.toml: not_switch 2 "):
        se_switches.parse({"bad.toml": text})
