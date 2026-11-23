"""The command tree of every script of SE's checkout, as scripts/references.py `command_tree` reads
it (the parser its `main` first parses): one JSON object, script name to tree. The agreement test
(commands_test.go) holds the Go reading, components/template CommandTree, to it."""

import json
import sys
from pathlib import Path

root = Path(sys.argv[1])
sys.path.insert(0, str(root / "scripts"))

import references  # noqa: E402

print(json.dumps({path.name: references.command_tree(path.resolve())
                  for path in sorted((root / "scripts").glob("*.py"))}))
