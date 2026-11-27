# Getting SE

A process plugin for AI agents. Its main agent, **SE**, is the one a person talks to; its other
agents are the integrator, the worker and the reviewer, each in a session of its own. With them come their skills, issue templates and the scripts they
call. It is project-neutral; a project describes its own commands in its `AGENTS.md` and
pulls se in as a module.

Status: being bootstrapped. Everything in this repository must be publishable; see `AGENTS.md`.

License: MIT, see [LICENSE](../LICENSE).

## Getting it running

On a machine with only its package manager: install Git, clone SE, run RUNME once. RUNME installs
what is missing (Claude Code, uv, SE's binary) and starts the SE agent in the folder it runs from;
a second run installs nothing. `<owner>/<repository>` is explained under [Install](#install).

- Windows: `winget install --id Git.Git -e --source winget`, then in a new terminal `git clone
  https://github.com/<owner>/<repository>`, then right-click `RUNME.ps1` > Run with PowerShell, or
  `powershell -ExecutionPolicy Bypass -File RUNME.ps1` in the clone. PowerShell drops a bare `--`
  before the script sees it, so a PowerShell line writes it as '--'.
- Linux: `sudo apt-get install -y git` (Debian, Ubuntu) or `sudo dnf install -y git` (Fedora), the
  same clone, then `./RUNME.sh`.
- macOS: `brew install git`, the same clone, then `./RUNME.sh`.

`./RUNME.sh --help` prints SE's command line; afterwards `claude --agent se:se` starts the agent in
any folder. A failed run from Explorer closes its window: run the second Windows line in a terminal
to read why. Where Claude Code already has SE from GitHub, RUNME stops with the one command to run;
read it the same way.

- **The Claude app:** a cloud session started in an environment set up for SE starts as the SE
  agent. Its repositories are the ones the session works on (SE needs none); its network access
  the default, Limited with Allow package managers ticked, which reaches `github.com` and
  `release-assets.githubusercontent.com` (SE's clone and its binary's release).
  - Its setup script is the one under [Claude Code cloud](#claude-code-cloud), which clones SE into
    `~/.claude/skills/se`, and its variable `SE_DEFAULT_AGENT=se`.
  - Elsewhere, the first message picks the agent: `Act as the se agent defined in
    <se>/agents/se.md.`, which works in Copilot too.
- **Cowork, untested:** give the Cowork session the folder that holds SE's clone, and send the
  first message above with that folder as `<se>`. Nobody has tried it yet.

## Install

One step per place. What each agent does is in its own file in [src/agents/](../src/agents/).
`<owner>/<repository>` is the owner and repository of the SE you install from, on GitHub (`uv run
python scripts/se_home.py tracker` prints it in a clone); no file of SE names it.

| Place | Install | Choose SE | Check that it loaded |
| --- | --- | --- | --- |
| Claude Code | from the clone: [RUNME](#getting-it-running), whose agent start runs `claude plugin install se --marketplace <clone>`; a copy from the GitHub marketplace (`<owner>/<repository>`) has no `.git`, so it gets no core release without `go`, no refresh at start and no documentation URL | `claude --agent se:se`, or `"agent": "se:se"` in a project's `.claude/settings.json` | `claude plugin list` shows `se@se`; `/agents` lists `se:se`, `se:integrator`, `se:retro`, `se:reviewer` and `se:worker` |
| Claude Code cloud (claude.ai/code) | the environment's [setup script](#claude-code-cloud); an environment may cache its output, so a session can start with an older clone, which SE [refreshes at start](start.md#start-and-refresh) | each session's first prompt, or SE_DEFAULT_AGENT=se on the environment ([below](#claude-code-cloud)) | `claude plugin list` shows `se@skills-dir`; ask the session which `se:` agents and skills it has: `se:se`, `se:integrator`, `se:retro`, `se:reviewer`, `se:worker`, `se:catch-up`, `se:decision`, `se:fill-templates`, `se:timeline`, `se:update`, `se:work-model` |
| GitHub Copilot in VS Code, in se's own checkout | `git clone https://github.com/<owner>/<repository>`, open it, and install the plugin from the clone: **Chat: Install Plugin from Source** with the clone's folder (agent plugins, `chat.plugins.enabled`); VS Code reads the plugin through `.claude-plugin/plugin.json`, its agents from `agents/` and its skills from `skills/`, and the checkout's `.github/hooks/se.json` and `.github/mcp.json` | in the Chat view pick the session target **Copilot** and the agent `se` (where `se` is missing, turn on `github.copilot.chat.cli.customAgents.enabled`) | the agent list holds `se`, `integrator`, `retro`, `reviewer` and `worker`, each once: both hosts read the one `agents/<name>.md` ([VS Code](copilot.md#vs-code)), and **Configure Skills** `catch-up`, `decision`, `update` and `work-model`; the first answer opens with the start report, its first line `SE <version> started`; asked `status`, the tool `se/status` answers `se: running in <checkout>, pid <n>, ...` |
| GitHub Copilot in VS Code, another repository | **Chat: Install Plugin from Source** with `https://github.com/<owner>/<repository>` (agent plugins, `chat.plugins.enabled`), which VS Code reads through `.claude-plugin/plugin.json`; a repository that opts in also runs `scripts/setup.sh <repo> --copilot` ([docs/copilot.md](copilot.md#another-repository)) | as above | as above, `se/status` naming that repository |
| GitHub Copilot CLI | `copilot plugin marketplace add <owner>/<repository>`, then `copilot plugin install se@se` (or `copilot plugin install <owner>/<repository>`, which the CLI calls deprecated) | `copilot --agent se` in a folder the CLI trusts (it asks once; `--trust-folder` for one run) | `copilot plugin list` shows `se@se`; `copilot skill list` shows `catch-up`, `decision`, `update` and `work-model` from the plugin's `skills/`, which its manifest `.github/plugin/plugin.json` names with the one `agents/`; in the session, the greeting as above and `se-status` answering `se: running in <project>, ...` |
| GitHub Copilot cloud agent (github.com), in se's own checkout | nothing: it reads the repository's `.github/hooks/se.json`; it reads agents only from the repository's own `.github` folder, where SE ships none, so it offers no `se` agent; untested ([docs/copilot.md](copilot.md#cloud-agent-optional-and-untested)) | the repository's **Agents** tab: start a task whose first line is `Act as the se agent defined in agents/se.md.` | its `sessionStart` hook hands the session SE's greeting, as above |

Copilot's details are in [docs/copilot.md](copilot.md): what a token-less Copilot CLI already
showed, the opt-in for another repository, the self-test and smoke test, and the owner's checklist
for the first run with Copilot.

**From an older SE**, follow the [upgrade guide](upgrading.md).

SE's skills read files in the plugin's folder and run its scripts with `uv run python`, and that
folder is outside your project. Claude Code asks you to allow this the first time. A headless
`claude -p` session cannot ask, so it refuses them unless you allow them in advance, for example
`--allowedTools Read Glob Grep Write Edit "Bash(uv run python:*)"`.

Commits carry no co-author lines: in VS Code, set `git.addAICoAuthor` to `off`
([VS Code 1.110 release notes](https://code.visualstudio.com/updates/v1_110)), as the
[public check](../AGENTS.md#public-safety) refuses a `Co-authored-by` line in every pushed commit.

**Everything else arrives by itself.** At the first start SE runs
[scripts/bootstrap.sh](../scripts/bootstrap.sh): it installs `uv` into the user's home, Python 3.11 or
newer through `uv`, and the project's [components](modules.md#modules); in a session it fetches and starts
[kern](start.md#kern). It is quiet when nothing is missing.

Claude Code runs it at every session start from the plugin's hooks, Copilot from
`.github/hooks/se.json`, a fail-open observer: SE works under Copilot with its hooks never firing.

The one tool it cannot install without admin rights is `git`; it then names the one line to run. An
interrupted first start finishes when run again.

### Claude Code cloud

Marketplace plugins do not load in a cloud session; a plugin cloned into `~/.claude/skills/` does
(it shows as `se@skills-dir`). Remove the environment's own SE plugin, if it has one (a
`CLAUDE_CODE_PLUGIN_DIRS` naming another plugin `se`), so the two do not collide: while it is set,
the other plugin wins and `claude --agent se:se` stops with `--agent 'se:se' not found`.

The environment's setup script, all of it; it runs before Claude starts, each time a container is
built, touches no repository and holds no secret:

```bash
rm -rf ~/.claude/skills/se
git clone --depth 1 https://github.com/<owner>/<repository> ~/.claude/skills/se || echo "SE: clone failed, this session starts without SE" >&2
```

It replaces any older SE line (a clone into `/opt/se` that runs `/opt/se/src/build.sh`). A failed
clone starts the session without SE instead of stopping it.

A cloud session takes no `--agent` flag, `create_session` takes no agent, and an `agent` key in the
repository's `.claude/settings.json` gives every session of that repository SE's instructions,
workers included. So each session's first prompt names its role's file, `<se>` being
`~/.claude/skills/se`:

- SE: `Act as the se agent defined in <se>/agents/se.md.`
- Worker and integrator: the session prompt the work model's
  [Without gh](../src/skills/work-model/SKILL.md#without-gh) names.
- Reviewer, started by SE on "review PR #n": the line
  `Act as the reviewer agent defined in <se>/agents/reviewer.md.`, then the pull
  request, its repository and SE's session, one per line.

An environment made for SE can set `SE_DEFAULT_AGENT=se` beside its setup script, in its
environment variables; a session started there then needs no first line: SE's start hands it the
se agent. Sessions that SE or an integrator starts keep naming their role in their first message,
which wins. Any other value hands over nothing and the greeting names it.

A running fleet shows in the sidebar as one section, the tag `SE`: SE's own session `SE`, each
project's integrator `SE/<project>/integrator` with its workers `SE/<project>/worker/<number>/<ticket name>`
under it, and SE's reviewers `SE/<project>/reviewer/<number>/<pr-branch-name>` beside it, each title
printed by `work_tickets.py session-title` ([Visible sessions](../src/skills/work-model/SKILL.md#visible-sessions)).

The greeting needs no permission rule: the plugin's start hook hands it over, and SE opens its
first message with it. A session whose permission mode asks before commands, and that no one
watches, needs SE's scripts and files allowed in the repository's `.claude/settings.json`:
`"permissions": {"allow": ["Bash(uv run python:*)", "Read(~/.claude/skills/se/**)"]}`.

A release runs in such a session too, on SE's message alone: run
`uv run python <se>/scripts/claude_settings.py allow --repo <repo>` once per repository and commit
`.claude/settings.json`. [scripts/claude_settings.py](../scripts/claude_settings.py) owns the rules,
why no setup step runs it, and the rules SE starts each integrator with.

### Cloud sessions

What a cloud session meets, whatever state its container comes up in.

- **One cached snapshot per set of sources.** The cloud keeps a container snapshot for each set
  of sources a session starts with, and rebuilds it only when the environment's setup script is
  edited. A session with SE's repository among its sources can so come up with an older SE plugin,
  an older `se` binary and the standing file of a core that ended with the snapshot.
  - The greeting names an SE older than the checkout the session works on, in one line under its
    first: `SE <plugin> runs, older than this checkout's SE <checkout>: ...`; editing the
    environment's setup script rebuilds the snapshots.
  - A plugin from before SE [refreshes at start](start.md#start-and-refresh) (5.47.4 was one) cannot move
    itself, and one from before that line cannot say so.
  - A standing file that names no running core stops no start: kern takes it over
    (kern's README, "The standing file").
- **A late checkout gets a core.** In a session without sources that clones a repository with an
  `se.toml` after its start, SessionStart ran before the clone existed. The first hook whose working
  directory is inside the clone starts its core in the background, as SessionStart would have, and
  the hooks there then post to it ([scripts/se_hook.sh](../scripts/se_hook.sh)).
  - A session whose folder is inside no git checkout, as one started without sources is, starts
    the core for SE's root, as kern is one of SE's
    [required components](boot.md#required-components); its hooks find no binary named for that
    folder and pass, and a checkout with an se.toml cloned into it gets its own core from its first
    hook there.
- **`setup.sh` in a spawned session.** Claude Code's auto-mode permission check judges `bash
  scripts/setup.sh` as one command, before any of its steps runs.
  - In a session another session started without sources, which then cloned SE by hand, it refused
    the command twice: with the clone in one command ("Undermining Oversight"), then alone
    ("Unauthorized Access"). Reading the script, the clone and `git log` passed.
  - The same command ran in a session started with SE's repository as its source.
  - So a spawned session that commits to a repository is started with it as its source
    (`create_session` with `source_url`); one that clones by hand can read and test, and stops at
    `setup.sh` with its report. Nothing is worded to get around the check.
