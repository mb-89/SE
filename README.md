# se: systematic engineering

```sh
git clone https://github.com/<owner>/<repository> se && cd se && ./RUNME.sh mcp --tools
```

That line gets SE, installs what the machine lacks and lists the tools SE gives its agents; it
exits non-zero when anything is broken. The [full documentation](docs.md) starts at
[Getting SE](docs/install.md); `<owner>/<repository>` is where you got SE from.

## What it is

SE turns AI coding agents into a small engineering team: you talk to one agent, SE, and it plans
the work, files it and starts the agents that do it. Each piece of work comes back as a pull
request whose description proves what was done, and one integrator merges, tests and releases it,
so the main branch stays green while many agents work at once.

It is for people who build software with Claude Code or Copilot and want finished, tested,
publishable work rather than chat. Its process is written down as checked rules, so a weaker model
follows it as a strong one does.

## Read on

- [Getting SE](docs/install.md): Windows, Linux, macOS, the Claude app and cloud sessions.
- [Starting SE](docs/start.md): the start, its core and the MCP door.
- [Components and modules](docs/modules.md) and their [settings](docs/settings.md).
- [Fleet and delivery checks](docs/fleet.md) and [tests and landings](docs/tests.md).
- [Metrics, local settings and workflows](docs/running.md).
- [Applications](docs/applications.md), the [command reference](docs/work-commands.md) and
  [templating](docs/templating.md).
- [The work model](src/skills/work-model/SKILL.md) and [the rule book](src/skills/work-model/references/rules.md).
- [Building the documentation](docs/documentation.md) and [upgrading](docs/upgrading.md).
- [The agent guide](AGENTS.md): everything here stays publishable.

License: MIT, see [LICENSE](LICENSE). Status: being bootstrapped.
