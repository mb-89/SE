package template

import (
	"reflect"
	"strings"
	"testing"
)

// The Go reading of a script's subcommands (CommandTree), on each way SE's scripts lay out their
// parsers; the agreement test holds it to Python's on SE's own scripts.
func TestTheReadingFollowsEachWayAScriptBuildsItsParser(t *testing.T) {
	cases := []struct {
		name, source string
		want         Tree
	}{
		{"no argparse", "def main(argv=None):\n    return 0\n", Tree{}},
		{"no main", "import argparse\nparser = argparse.ArgumentParser()\nparser.add_subparsers().add_parser('x')\n", Tree{}},
		{"subparsers, nested", `import argparse

def main(argv=None):
    top = argparse.ArgumentParser(description="x")  # a comment ( with a bracket
    commands = top.add_subparsers(dest="command", required=True)
    new = commands.add_parser("new", help="create").add_subparsers(dest="what")
    new.add_parser("app", help='an "app"')
    commands.add_parser(
        "list",
        help="""a list""",
    )
    args = top.parse_args(argv)
    return 0
`, Tree{"new": Tree{"app": Tree{}}, "list": Tree{}}},
		{"a parser a function makes", `import argparse

NAMES = {"key": "write the key", "decide": "decide"}


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    for name, text in NAMES.items():
        commands.add_parser(name, help=text).add_argument("--worktree")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = make_parser().parse_args(argv)
    return 0
`, Tree{"key": Tree{}, "decide": Tree{}}},
		{"a positional's choices", `import argparse
KINDS = ("build", "check")
def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", choices=("a", "b"))
    parser.add_argument("command", choices=sorted(KINDS))
    parser.add_argument("other", choices=("x",))
    if True:
        args = parser.parse_args(argv)
`, Tree{"build": Tree{}, "check": Tree{}}},
		{"the registry", `import argparse
ROLES = {"se": "x", "worker": "y"}
COMMANDS = Command("tool.py", "")
def command(name, help, *arguments, parent=COMMANDS):
    pass
def command_group(name, help, dest):
    pass
@command("init", "start", arg("--worktree"))
def run_init(root, args):
    return 0
GROUP = command_group("backlog", "the backlog", "action")
@command("file", "file one", parent=GROUP)
def run_file(root, args):
    return 0
@command("title", "a title", arg("role", choices=tuple(ROLES)), arg("topic", nargs="?"))
def run_title(root, args):
    return 0
def main(argv=None):
    args = make_parser().parse_args(argv)
`, Tree{"init": Tree{}, "backlog": Tree{"file": Tree{}}, "title": Tree{"se": Tree{}, "worker": Tree{}}}},
	}
	for _, c := range cases {
		if got := ScriptTree(c.source); !reflect.DeepEqual(got, c.want) {
			t.Errorf("%s: read %v, want %v", c.name, got, c.want)
		}
	}
}

// A Go fill refuses a text that names a subcommand SE's scripts do not define, as the Python
// engine's rule dangling does, and passes the one a Requirement creates.
func TestAGoFillRefusesADanglingCommand(t *testing.T) {
	work, fields, title := workFields(t)
	fields.Set("goal", "Every issue title says in plain words what changes; run `review.py nope` after.")
	_, err := Fill(work, fields, raw, title, "")
	if err == nil || !strings.Contains(err.Error(), "dangling") || !strings.Contains(err.Error(), "`review.py nope` names a subcommand review.py's parser does not define; it defines brief, file") {
		t.Fatalf("a fill naming review.py nope was not refused for it: %v", err)
	}
	fields.Set("goal", "Every issue title says in plain words what changes; run `review.py brief` after.")
	if _, err := Fill(work, fields, raw, title, ""); err != nil {
		t.Fatalf("a fill naming review.py brief was refused: %v", err)
	}
}
