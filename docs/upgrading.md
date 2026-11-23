# Upgrading across breaking releases

This guide brings a checkout that ran an older SE, and the projects it serves, to the current
release. It holds one section per breaking release of SE, headed `SE <major>`, and, until each
component keeps its own, one per breaking release of the components SE ships with. Every step is
mechanical, and every check is a command or a grep whose output says whether the step is done.

Placeholders, used throughout:

- `<se>`: the SE the session runs, the folder SE's start greeting names as `SE root:`.
- `<obs>`: obs's placed clone, `uv run python <se>/scripts/se_modules.py path obs`.
- `<machine>`: obs's machine folder: `$OBS_LOCAL_FOLDER` where set, else `obs` in the user's
  configuration folder (`~/.config/obs` on Linux, `~/Library/Application Support/obs` on macOS,
  `%APPDATA%\obs` on Windows); installed components live in `<machine>/components/<name>/`.
- `<go.mod>`: the `go.mod` that `[components.kern] go` names (`go = true`: the root's).

## Following the guide

1. **Install the newest SE.** The start's refresh moves SE only within its major, so a newer major
   is an install again, as README [Install](../README.md#install) says: for a clone,
   `git -C <se> fetch --tags` and `git -C <se> checkout v<newest>`; for the cloud, the
   environment's setup script ([README "Cloud sessions"](../README.md#cloud-sessions)).
   - Then run `bash <se>/scripts/setup.sh <project>` once, so the project's hooks are the new SE's.
   - Check: `grep -m1 '^version' <se>/se.toml` prints the newest version, and
     `git -C <project> config core.hooksPath` names `<se>/.githooks`.
2. **List the sections to follow.** The start greeting names them on the line
   `SE: <newest> is outside SE's major <n>`. They print, oldest first, with
   `uv run python <se>/scripts/upgrade_guide.py show --name SE --from <in use> --to <newest>`.
   - `<in use>` is the `[project] version` of the old SE, or the project's locked `se` in
     `se.lock`.
3. **Follow each section in order**, every step and then its check, in the project's checkout.
   Commit after each section. A section points to the component sections at the step where SE
   moved a component, so each component moves only once SE can read it.
4. **Finish.** Each of these prints what it names:
   - `uv run python <se>/scripts/se_modules.py sync` exits 0;
   - `uv run python <se>/scripts/se_modules.py breaking` prints `no breaking release beyond a pin`;
   - `uv run python <se>/scripts/public_check.py --repo .; echo $?` prints `0` or `1`, never `2`;
   - `uv run python <se>/scripts/se_start.py --root . status --greeting` prints no line with
     `is outside` and none opening `SE cannot start`.

For a component, the same reader prints its sections from the guide it keeps, `show --guide
<clone>/docs/upgrading.md --name <component> --from <locked> --to <newest>`, where `<clone>` is
`uv run python <se>/scripts/se_modules.py path <component>`.

## How the guide is kept

- **One section per breaking release.** Headed `## <name> <version>`: the repository's name and
  the release's major, below 1.0 its major and minor (`obs-html 0.5`). A minor whose consumers
  must act may add its own section (`kern 2.1`). [scripts/upgrade_guide.py](../scripts/upgrade_guide.py)
  owns the shape and reads it.
- **In the landing that makes the change.** A landing whose release kind is major adds its change
  to the section of the next major, with its steps and its check. `work_tickets.py release`
  refuses a major release, below 1.0 a breaking minor, while `docs/upgrading.md` has no section for
  it, naming the heading to add.
- **Each component keeps its own.** obs, obs-html and kern each keep a `docs/upgrading.md` in this
  shape, and this guide links it rather than copying it. Until a component's own guide lands, its
  sections stand at the end of this guide under its name, and move out when it does.
- **Any two versions.** The boot reads the sections between the running and the newest version of
  SE and of every component, through `upgrade_guide.py show`. The sections from SE 6 to SE 12 were
  the first entries.

## SE 6

The forms engine is the template engine, with no alias: nothing reads the old names, and most are
ignored without a word, so the checks catch them.

### `[forms]` is `[templates]`

- **Change:** the `se.toml` table `[forms]` (`enforce`, `gate`, `files`) is `[templates]`; a
  `[forms]` table is ignored, so the filing commands and the gate run with their defaults.
- **Steps:** rename the header `[forms]` to `[templates]`, keeping its keys.
- **Check:** `grep -nE '^\[forms\]' se.toml` prints nothing.

### `forms/` is `templates/`

- **Change:** a project's own definitions live in `templates/`.
- **Steps:** `git mv forms templates`; SE 9 converts the files.
- **Check:** `test ! -e forms && echo done` prints `done`.

### `form:` is `template:`

- **Change:** a claimed file's front matter `form: <name>` is `template: <name>`; the old key
  selects nothing.
- **Steps:** in every file a project template claims, replace the line `form: <name>` by
  `template: <name>`.
- **Check:** `git grep -nE '^form: ' -- '*.md'` prints nothing.

### Commands, tool, switch and label

- **Change:** `scripts/forms.py` is `scripts/templates.py`, `scripts/se_forms.py` is
  `scripts/se_templates.py`, `--forms` is `--templates`, the MCP tool `forms` is `templates`
  (`mcp__plugin_se_se__templates`), `SE_FORMS_GATE` is `SE_TEMPLATES_GATE`, the label `off-form`
  is `off-template`, and the marker `<!-- se:form <name> -->` selects nothing.
- **Steps:** rewrite these names wherever the project's files name them (`AGENTS.md`, docs,
  scripts, `.claude/settings*.json`); relabel each open issue `off-form` as `off-template`.
- **Check:** `git grep -nE 'se_forms\.py|(^|[^_a-z])forms\.py|--forms\b|plugin_se_se__forms\b|SE_FORMS_GATE|off-form\b|se:form '`
  prints nothing.

### Runtime leftovers

- **Change:** `.se/.runtime/forms-files`, `.se/.runtime/forms-gate.log` and `~/.se/forms/` are
  `templates-files`, `templates-gate.log` and `~/.se/templates/`.
- **Steps:** `rm -rf .se/.runtime/forms-files .se/.runtime/forms-gate.log ~/.se/forms`.
- **Check:** `ls -d .se/.runtime/forms-* ~/.se/forms 2>/dev/null | wc -l` prints `0`.

## SE 7

### Every decision note says what others do

- **Change:** `deck.py build` refuses a decision note (a note with a `pugh` fence) unless it has
  `## Current situation`, `## The problem` and `## What others do`, in that order, before the
  fence ([decision skill](../src/skills/decision/SKILL.md)).
- **Steps:** in each decision note, add `## What others do` between `## The problem` and the
  fence: at least two outside tools or conventions, each with what it does and an example.
- **Check:** this prints nothing:

  ```sh
  git grep -l '^```pugh' -- '*.md' | while read -r f; do
    awk '/^```pugh/{exit} /^## What others do$/{o=1} END{exit !o}' "$f" || echo "$f"; done
  ```

## SE 8

Components are found by name under the owners of the checkout's remotes
([docs/components.md](components.md#finding-a-component)).

### `[modules]` is `[components]`, without `url`

- **Change:** a `[modules]` table is refused (`[modules] is [components] since se 8`), and so is a
  `url` key: a machine that needs another place sets `[paths]` or `[urls]` in `~/.se/local.toml`.
  The keys are `ref`, `version`, `go`, `optional` and `path`.
- **Steps:** rename every `[modules.<name>]` to `[components.<name>]`, delete each `url = ...`
  line, and set `[components.se] version` to the newest SE's major, `"^<major>.0"`, where the
  project pins se.
  - One version per name holds over the tree: where the project also pins a component the newest
    SE pins (`grep -A2 '^\[components\.' <se>/se.toml`), set its range to admit SE's now, such as
    obs `"^10.3"`; its content steps follow at [SE 11](#se-11).
  - Then `uv run python <se>/scripts/se_modules.py sync`, and commit `se.toml` and `se.lock`.
- **Check:** `grep -nE '^\[modules(\.|\])|^url *=' se.toml` and `grep -c '^\[modules\.' se.lock`
  print nothing and `0`.

### Component names

- **Change:** a component's name is its repository's: 1 to 32 letters, digits and `-`.
- **Steps:** rename each entry to its repository's name.
- **Check:** this prints nothing:
  `grep -oE '^\[components\.[^]]+\]' se.toml | grep -vE '^\[components\.[A-Za-z0-9][A-Za-z0-9-]{0,31}\]$'`.

### Where a component is found

- **Change:** each name is found under the owners of the checkout's remotes, origin first; on
  GitHub only a repository with the topic `component` is offered. A required component missing
  anywhere in the tree stops the session's start, opening `SE cannot start:`.
- **Steps:** give each component the project's owner publishes the topic `component`; for a
  component of another owner, `git remote add <name> <any repository of that owner>`; mark a
  component the project works without `optional = true`.
  - Where the repository SE lives in lacks the topic, `sync` names `marks no repository se as a
    component`: until its owner adds it, a machine sets `se = "<se>"` under `[paths]` in
    `~/.se/local.toml`.
- **Check:** `uv run python <se>/scripts/se_start.py --root . start-components 2>&1 | grep -c 'SE cannot start'`
  prints `0`.

### Project prose

- **Steps:** replace `[modules` in the project's `AGENTS.md` and docs.
- **Check:** `git grep -n '\[modules' -- ':!se.lock'` prints nothing.

## SE 9

### A template is one Markdown note

- **Change:** `templates/<name>.toml` no longer loads; a template is `templates/<name>.md`, front
  matter plus a skeleton of one `## <heading>` per field. Only `templates/terms.toml` stays TOML.
  `version`, `kind` and `tags` are required in every template. No converter ships.
- **Steps:** for each `templates/<name>.toml` but `terms.toml`, write `templates/<name>.md` in the
  shape [scripts/templates.py](../scripts/templates.py) "Template files" owns, with
  `<se>/templates/ticket.md` as the model, `version: 1.0.0`; then delete the TOML file.
- **Check:** `ls templates/*.toml 2>/dev/null | grep -v '/terms\.toml$'` prints nothing, and
  `uv run python <se>/scripts/templates.py check --tree --root . --path se.toml; echo $?` prints
  `0` last (`2` names a note that does not load).

## SE 10

### Only the fill writes a claimed path

- **Change:** `[templates] files` is gone, and the file gate is always on: a path a template
  claims (`applies.paths`) is written only by `templates.py fill`; a direct write of it is denied,
  naming the fill command.
- **Steps:** delete the `files = ...` line from `[templates]`; write each claimed file through
  `uv run python <se>/scripts/templates.py fill <template> --path <file> --root .`; change any
  project script that writes a claimed file to call the fill.
- **Check:** `awk '/^\[templates\]/{t=1;next} /^\[/{t=0} t&&/^files[[:space:]]*=/' se.toml`
  prints nothing, and `uv run python <se>/scripts/se_templates.py check-files --root . $(git ls-files); echo $?`
  prints `0` last.

### The project's templates win over SE's

- **Change:** from 10.8 a template name resolves from the project's own `templates/` first, then
  its template repositories, then SE's, so a project file named like an SE template replaces it.
- **Steps:** delete each copy of an SE template the project does not mean to override.
- **Check:** with each override the project keeps named as `templates/<file>` in its `AGENTS.md`,
  this prints nothing:
  `comm -12 <(ls templates | sort) <(ls <se>/templates | sort) | grep -vxF terms.toml | while read -r f; do grep -qF "templates/$f" AGENTS.md || echo "$f"; done`.

### `[workers]` admits three keys

- **Change:** from 10.7 `[workers]` holds `local` (default 4), `cloud` and `claim_timeout_hours`;
  another key is refused.
- **Check:** this prints nothing:
  `awk '/^\[workers\]/{t=1;next} /^\[/{t=0} t&&NF&&!/^#/&&!/^(local|cloud|claim_timeout_hours)[[:space:]]*=/' se.toml`.

## SE 11

### A release only when SE asks

- **Change:** `work_tickets.py push` and `integrate` no longer raise `[project] version` or push a
  tag; `integrate` records the release kind, and `work_tickets.py release` raises the version when
  SE asks ([README "Project settings"](../README.md#project-settings)).
- **Steps:** remove any project automation or instruction that expects a tag per landing.
- **Check:** `git grep -nE 'tag (per|each) landing|push(es)? (the|a) tag'` prints nothing.

### SE's own pins moved: obs 10, kern 1

- **Change:** 11.1 moved SE's obs to `^10.0` and kern to 1.5.0. One version per name holds over the
  tree, so a project that pins se and also obs or kern must admit a release both accept; else
  `sync` fails, naming both pins. A project that pins se moved such a pin at [SE 8](#se-8).
- **Steps:** follow the component sections [obs 6](#obs-6) to [obs 10.3](#obs-103), then
  [obs-html 0.2](#obs-html-02) to [obs-html 0.5](#obs-html-05), then [kern 1](#kern-1).
- **Check:** `uv run python <se>/scripts/se_modules.py sync 2>&1 | grep -c 'admits both'` prints `0`.

## SE 12

### Copies of SE's workflows carry the generated marker

- **Change:** `se_workflows.py write` marks its copies `# Code generated by se_workflows.py write
  ...`; a copy with the old header `# se-workflows:` is no longer held, so nothing regenerates it.
- **Steps:** `uv run python <se>/scripts/se_workflows.py write $(git grep -l '^# se-workflows:')`,
  then commit.
- **Check:** `git grep -l '^# se-workflows:'` prints nothing, and
  `uv run python <se>/scripts/se_workflows.py check` exits 0.

### Field reports answer the 13 standing questions

- **Change:** a field report's `## Retro` holds the 13 questions of `<se>/templates/standing-questions.md`,
  one `### <question>` each, every one answered ("None" where it does not apply), in place of the
  bullets `**Went well:**`, `**Cost time:**` and `**Proposed improvement:**`. `templates/retro.md`
  and `templates/overhaul.md` are 2.0.0.
- **Steps:** in each open work pull request's description, replace the three bullets by the 13
  questions and their answers; collect an open retro draft again with `retro.py collect`.
- **Check:** for each open pull request's description saved to a file, `uv run python
  <se>/scripts/work_tickets.py field-report --check <file>` exits 0.

### One plugin layout

- **Change:** SE ships no `.github/agents/<name>.agent.md` and no `.github/skills/`; both hosts
  read `agents/<name>.md` and `skills/`.
- **Steps:** rewrite every prompt that names `<se>/.github/agents/<name>.agent.md`, in the project's
  files, its scheduled tasks and its cloud environments, to `<se>/agents/<name>.md`; update each
  host's install as README [Install](../README.md#install) says.
- **Check:** `git grep -nE '\.github/agents/[a-z-]+\.agent\.md|\.github/skills/'` prints nothing.

### The guidance comes first; `fill` is a writing tool

- **Change:** `se_templates.py draft` prints the template's guidance before the JSON, which follows
  the line `## The template <name>`. The MCP door's `fill` moved from the tool `templates` to
  `templates_write` (`mcp__plugin_se_se__templates_write`).
- **Steps:** a project script that reads `se_templates.py draft` as JSON calls
  `templates.py draft <name> --json` instead; a `.claude/settings*.json` that allows the tool
  `templates` for fills also allows `templates_write`.
- **Check:** `git grep -nE 'se_templates\.py (draft|fill).*\| *(jq|python)'` and
  `git grep -l 'plugin_se_se__templates\b' -- '.claude/*.json' | xargs -r grep -L templates_write`
  print nothing.

### GitHub writes take a filled template; kern 2

- **Change:** the door's `github_write` (`github issue-create`, `github issue-comment`) takes
  `--filled`, the answer of a template fill, in place of `--template` and `--fields`. SE builds on
  kern 2.1.0, written `require kern v2.1.0+incompatible`, which an SE before 12 cannot read.
- **Steps:** replace each call with `--template`/`--fields` by `templates.py fill <template>
  --repo <owner>/<repository> ...`; remove `.se/templates/*.json`; then follow [kern 2](#kern-2)
  and [kern 2.1](#kern-21).
- **Check:** `git grep -nE 'github (issue-create|issue-comment).*--(template|fields)\b'` prints
  nothing, and `ls .se/templates/*.json 2>/dev/null | wc -l` prints `0`.

## SE 13

On main, released as 13.0.0 at the next release.

### The spawn guard has no baseline

- **Change:** a project that loads SE's spawn guard (`<se>/scripts/spawn_guard.py`) gets no
  baseline: `--spawn-baseline`, the `spawn_baseline` setting and `tests/spawn-baseline.yaml` are
  gone, and only `contract: <door>` and `entry: <script>` reasons let a test start a process
  (guidance note [tests-spawn-no-processes](../guidance/pull-request/field-report/tests-spawn-no-processes.md)).
- **Steps:** delete `tests/spawn-baseline.yaml` and every `spawn_baseline` line; set
  `spawn_guard = "warn"` under `[tool.pytest.ini_options]` until every test is converted, then
  `"error"`; mark each test that starts a process with a `contract:` or `entry:` reason only.
- **Check:** `ls tests/spawn-baseline.yaml 2>/dev/null; git grep -nE 'spawn.baseline|spawns\("(tool|shell):'`
  prints nothing.

## obs 6

obs's sections stand here until obs keeps its own guide. A project moves obs once:
`[components.obs] version = "^10.3"`, `uv run python <se>/scripts/se_modules.py update obs`, then
these sections in order. Check: `uv run python <se>/scripts/se_modules.py status obs` ends
`at pin`.

### Every Document records its components

- **Change:** a Document carries a required top-level `components` list, each entry's name, kind,
  version and commit.
- **Steps:** regenerate each Document the project commits as a recorded output, masking each
  entry's `version` and `commit`.
- **Check:** for each committed Document `<f>`, `python3 -c "import json,sys;sys.exit('components' not in json.load(open('<f>')))"`
  exits 0.

## obs 7

### `obs.style` names an installed style component

- **Change:** `obs.style: <name>` names a style component installed on the machine; the address
  form, a mapping `{url, ref, path}`, fails the build, and obs-html no longer fetches styles.
- **Steps:** for each style the project's notes address: make it a component repository with
  `style.css` at its root, release it, install it with
  `uv run --project <obs> obs-components install <name>`, and write `style: <name>` under the
  note's `obs:` front matter.
- **Check:** each `obs-document` build the project runs exits 0, and
  `test -f <machine>/components/<name>/style.css` for each `<name>` the notes declare.

## obs 8

### `key:: value` lines are block fields

- **Change:** a whole paragraph line `key:: value` is a block field, no longer text; one that
  attaches to no block fails the build (`attaches to no block`).
- **Steps:** list the lines with
  `grep -rnE '^[A-Za-z_][A-Za-z0-9_-]*(\.[A-Za-z0-9_-]+)*::( |$)' --include='*.md' <vault>`; put
  each that is prose in a code span, and move each that is a field right after its block.
- **Check:** each `obs-document` build exits 0 and prints no `attaches to no block`.

## obs 9

### Components are found by the topic `component` and `v` tags

- **Change:** `obs-components` finds component repositories by the topic `component` (was
  `obs-component`), names each by its repository's name, and reads releases from `v<x.y.z>` tags
  (was `obs-component/<kind>/<name>/v<version>`). The HTML adapter is `obs-html`.
- **Steps:** for each adapter or style the project publishes: name the repository as the
  component, set the topic `component`, tag each release `v<x.y.z>`, and reinstall it with
  `uv run --project <obs> obs-components install <name>`.
- **Check:** `uv run --project <obs> obs-components 2>&1 | grep -c 'not a component of obs'`
  prints `0`.

## obs 10

### The HTML adapter is the component `obs-html`

- **Change:** obs keeps no adapter in its tree: `--adapter html` and `obs-components install html`
  fail. The adapter is the component `obs-html`, and its specification moved with it.
- **Steps:** replace `--adapter html` by `--adapter obs-html` and `obs-components install html` by
  `obs-components install obs-html` in scripts, workflows and docs; rewrite `adapters/html/spec/`
  references to obs-html's `spec/`; install it on every machine and runner before its first build.
- **Check:** `git grep -nE -- '--adapter[ =]html\b|obs-components install html\b|adapters/html'`
  prints nothing, and `test -f <machine>/components/obs-html/adapter.json`.

## obs 10.2

### Installing a component installs what it requires

- **Change:** `obs-components install <name>` also installs the components `<name>` requires;
  `update` on a newest component installs none. obs-html 0.5 needs it.
- **Steps:** install with `install`, never `update`:
  `uv run --project <obs> obs-components install obs-html`.
- **Check:** `uv run --project <obs> python -c "from obs.components import requirements"` exits 0.

## obs 10.3

### The listing reads each remote's host

- **Change:** the component listing searches each remote's host the same way; a host other than
  the public one takes its own login.
- **Steps:** on a machine whose obs clone has a remote on such a host, sign that host's login in
  (`gh auth login --hostname <host>`).
- **Check:** `uv run --project <obs> obs-components 2>&1 | grep -c 'cannot list owner'` prints `0`.

## obs-html 0.2

obs-html's sections stand here until it keeps its own guide. A machine holds one installed
obs-html, `uv run --project <obs> obs-components install obs-html`; move it after obs 10.2.

### The adapter is named `obs-html`

- **Change:** `adapter.json` names the adapter `obs-html` (0.1 called it `html`).
- **Steps:** as [obs 10](#obs-10).
- **Check:** `grep -c '"name": *"obs-html"' <machine>/components/obs-html/adapter.json` prints `1`.

## obs-html 0.3

### Comment cards in document order

- **Change:** the Comments bar sorts its cards by where each target sits in the Document, and each
  card shows its target's path; nothing else changes.
- **Steps:** update tests that read the cards' order or text.
- **Check:** the project's suite passes.

## obs-html 0.4

### The front matter chevron is gone

- **Change:** front matter shows as a metadata card in the Comments bar; the page drops
  `[data-frontmatter-toggle]`, `[data-frontmatter-panel]`, `[data-frontmatter-body]`,
  `[data-frontmatter-field]` and the classes `.frontmatter-toggle`, `.frontmatter-panel` and
  `.comment-target`.
- **Steps:** rewrite CSS snippets, styles and browser tests that target them.
- **Check:** `git grep -nE 'data-frontmatter-(toggle|panel|body|field)|\.frontmatter-(toggle|panel)|\.comment-target'`
  prints nothing.

## obs-html 0.5

### The default style is the component `obs-html-style-generic`

- **Change:** obs-html builds no style in; its default style is the required component
  `obs-html-style-generic`, and a build without `--style` or `obs.style` fails where it is not
  installed, naming `obs-components install obs-html-style-generic`.
- **Steps:** on obs 10.2 or later, `uv run --project <obs> obs-components install obs-html` on
  every machine and runner; code that checks the adapter is installed also checks its requirements
  (`obs.components.requirements`).
- **Check:** `test -f <machine>/components/obs-html-style-generic/style.css`.

## kern 1

kern's sections stand here until kern keeps its own guide. kern is pinned by `<go.mod>`'s
`require kern` line: change it, then `uv run python <se>/scripts/se_modules.py sync kern`, and
commit `<go.mod>`, `go.sum` and `se.lock`.

### Time is the clock component's

- **Change:** no component keeps a timer: time is the clock component's names, the GitHub
  component counts `github.second`, and `host.AskStop` takes a clock first.
- **Steps:** blank-import `kern/components/clock` in the binary's `main.go`; add
  `[instances.clock] component = "clock"` and the wires `"clock.second" = "clock/second"` and
  `"github.second" = "clock/second"` to `wiring.toml`; write `host.AskStop(host.Wall{}, root)`.
- **Check:** `grep -c '"github.second"' wiring.toml` prints `1`, and `git grep -n 'AskStop(root)'`
  prints nothing.

## kern 2

### GitHub writes take only a filled template

- **Change:** `github issue-create` and `github issue-comment` take `--filled`, the application's
  template component's fill, and refuse `--template` and `--fields`. Before writing they ask the
  port `template-accept`; unbound, every write is refused. The GitHub instance's `templates` key
  and kern's template rendering are gone.
- **Steps:** have a template component that serves `template.accept` and `template.fill`
  (SE's `components/template`); bind `"github.template-accept" = "<template instance>.accept"` in
  `wiring.toml`; remove `templates = ...` from `[instances.github]`; send `filled` in every
  `component.toml` request that files.
- **Check:** `grep -c '"github.template-accept"' wiring.toml` prints `1`, and
  `git grep -nE 'form\.LoadTemplate|github\.(LoadTemplate|ParseTemplate)|--template [^ ]+ --fields'`
  prints nothing.

### The pin reads `+incompatible`

- **Change:** kern's module path stays `kern` at every major, so Go accepts a 2.x pin only as
  `require kern v2.<minor>.<patch>+incompatible`; an SE before 12 cannot read it.
- **Steps:** write `require kern v2.1.0+incompatible` in `<go.mod>`, then `go mod tidy`.
- **Check:** `grep -cE 'kern v2\.[0-9]+\.[0-9]+\+incompatible' <go.mod>` prints `1`.

## kern 2.1

### Generated files are marked

- **Change:** kern's checker adds the rule `generated`: every file a program writes carries the
  marker `Code generated by <generator> from <source>. DO NOT EDIT.` and is declared in
  `generated.yaml`; a finding has a severity, and a notice fails nothing.
- **Steps:** `go mod tidy`; mark each generated file and declare it in `generated.yaml` (guidance
  note [generated-files-are-marked](../guidance/generated-files-are-marked.md));
  tests that assert on all findings assert on `lint.Errors(...)`.
- **Check:** `uv run python <se>/scripts/generated.py --root . check --no-rerun` exits 0, and
  `grep -c 'gopkg.in/yaml.v3' <go.mod>` prints `1`.
