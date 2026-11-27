# Fleet and delivery checks

## Fleet check

```toml
[fleet]
lease_hours = 3
restart_after_limit = false
```

`work_tickets.py fleet-check` lists what is stuck or stray, each with its remedy (its `--help`
names the kinds), and says `healthy` otherwise; it only reads.

`lease_hours` is how long in-progress work may go without a push to its branch, built in 3. The
time of a push is the committer time of the branch's tip, as git fetches it.

An in-progress issue whose branch origin does not have yet is listed as `starting`, which is
healthy, until the lease has passed since its newest `Started:` comment; then it is `no branch`.
Where the issue has no such comment, or its comments were not read, the lease cannot be counted:
it is `no branch` at once, saying why.

Blocks are the `## Blocked by` section of each open issue's body, where `work_tickets.py block`
writes them.

Where the core running in the checkout carries SE's fleet component and has read the open issues
and the open pull requests each as a whole list, it answers from the core's `fleet/findings`
instead, live, naming how many issues and pull requests the core has read and since when
([components/README.md](../components/README.md#who-reads-them)); the Python check stays the path
everywhere else.

A partial view is no verdict: where the core holds only some issues or pull requests, the check
says how many it has seen and since when, and reads the fleet itself.

Where `gh` reaches GitHub, signed in or over REST, it reads the fleet itself in one call.
Without gh it prints its GitHub plan; the session runs it with its GitHub tools, saves the three
lists as JSON (each in-progress issue with its comments) and passes them as `--open-issues`,
`--closed-issues` and `--pulls`.

`work_tickets.py turn-start` prints the findings together with everything else SE reads at a
turn's start ([se agent "Turn-start check"](../src/agents/se.md)).

With `--sessions <file>` it also reports each worker session stopped on a usage limit before it
delivered: the session tools' answers, the sessions `list_sessions` lists, each with the
`list_events` answer of its `result` and `rate_limit_event` events as `"events"`. The core holds no
sessions, so the check then reads the fleet itself.

`restart_after_limit` is off, built in: the report is all that happens. On, the remedy is to
resume the session once the limit lifts and comment on its issue the line it quotes, which
`templates/limit-restart.md` writes, at most once per issue. [scripts/limit_restart.py](../scripts/limit_restart.py) owns what counts.

## Dispatcher

`work_tickets.py dispatch` starts a fleet that stopped, with no model: an hour with nothing to start
costs no model tokens. It reads from GitHub alone:

- the startable work issues, as `ready` lists them: labelled `work` and `ready`, not waiting on a
  person (labelled `se-person` or `escalated`, or assigned to someone), with no open blocker;
- whether an integrator runs: an open landing pull request (`land/<branch>`), or in-progress work
  whose issue or branch moved within the [fleet lease](#fleet-check).

- Where startable work waits, no integrator runs, the [worker limit](settings.md#workers) leaves room and the
  fleet is not [paused](../src/skills/work-model/SKILL.md#pause), `--fire`
  fires the scheduled task whose session is a fresh integrator, once, and names its session;
  `--dry-run` prints that fire and makes none. Anything else fires nothing and says why.
- The workflow [.github/workflows/dispatch.yml](../.github/workflows/dispatch.yml) runs it every four
  hours. The integrator starts the next startable issue itself after each landing
  ([integrator](../src/agents/integrator.md)); the dispatcher only restarts a fleet where none runs.
- Two repository secrets configure it, so no committed file names the task, its token or the
  service's host: `SE_DISPATCH_TRIGGER`, the fire URL of the scheduled task's API trigger as it
  shows it (an https URL ending in `/trig_<id>/fire`, which names the task's id), and
  `SE_DISPATCH_TOKEN`, that trigger's token. While either is unset, the workflow runs `--dry-run`.
- Setting them, and creating the scheduled task, are steps only the person takes
  ([Steps only the person approves](../src/skills/work-model/SKILL.md#steps-only-the-person-approves)).
- Switch it off by disabling the workflow (the Actions tab, or `gh workflow disable dispatch.yml`)
  or by deleting either secret; an open `pause` issue holds it with the rest of the fleet.

## Settings check

`fleet/settings.toml` records settings the fleet runs on outside the repository: main's ruleset,
the scheduled tasks and the cloud environment. `scripts/fleet_settings.py` owns its format and
the doors.

`work_tickets.py settings-check` compares it with what the live doors read and prints each
difference in one line. It is advisory: it exits 0 unless `--strict` is given, and nothing runs it
on its own.

## Source parity

The same tree may be held by more than one remote or checkout
([More than one remote](../src/skills/work-model/SKILL.md#more-than-one-remote)).
`work_tickets.py parity` compares two commits' trees, such as `origin/main` and
`mirror/main`, path by path, by mode and object id, and only reads (`git ls-tree`).

- **The lockfile rule:** a tracked file named `se.lock` or `uv.lock` is a dependency lockfile at any
  depth (`kern/template/uv.lock` too), since it records what resolved, which may differ where the
  source does not. Its content, presence and absence pass, and the command names it on one line,
  `lockfiles excluded:`. `work_tickets.py` `PARITY_LOCKFILES` owns the list; nothing else is excluded.
- **Every other path fails:** a path that differs is listed as `changed:`, or `only in <ref>:` for
  the side that holds it. Generated outputs (the layout, `components/*/component.toml`) compare
  like source, and no text is normalized, whitespace included. Exit code 1 with any such path, 0
  without (`tests/test_parity.py`).

## Retro due

```toml
[retro]
due_after = 20      # what came back, weighed: a landing 1, a failure failure_weight
failure_weight = 5  # an escalated work issue: an escalation or a refused landing
days = 7            # or this many days after the last retro started, with anything come back; 0: off
```

A retro falls due by what comes back to the project, never by what is opened: filing 20 issues in
one session makes none due. Each work issue that landed since the newest retro started adds 1, each
work issue labelled `escalated` (an escalation, a refused landing) updated since then adds
`failure_weight`. At `due_after`, or `days` days after that start with anything counted, one is due.

- **Filed first.** `work_tickets.py file` and `backlog file` run the filing check before they file
  anything: a due retro or overhaul is filed first, from its issue template (labelled `retro` or
  `discovery`, not `ready`), and the filing asked for is refused, naming it.
- **Blocking.** While a retro is running, filing is refused with its number. Once its report is in,
  `file --finding <retro>:<finding>` may file only that finding's work issue; every other filing is
  refused.

  A finding may instead be recorded as declined or merged into another finding with `retro.py
  outcome`. The retro is done and closes when every finding has an outcome. An open overhaul still
  refuses every filing. Running work goes on, and issues keep coming back; they count towards the
  next run.
- **Scope and reset.** A retro covers everything up to its start, what came back after it fell
  due included, and a first retro, where none has closed, the whole history from the project's
  first issue; its counters reset when it starts (its issue's creation), so a late retro never
  makes the next one due at once.
- **Own session.** A [retro agent](../src/agents/retro.md) runs each retro and overhaul in its own
  session; SE presents the completed report deck to the person.
- **One owner.** `scripts/retro.py` owns the count (`retro_countdown`) and the settings;
  `retro.py due` prints both countdowns. It reads back to the newest run's start, all with no
  retro yet (`recent_reads`). The [start greeting](start.md#start-and-refresh) names a run due or
  open; SE's retro-due component counts the same from kern's GitHub names, for the greeting to
  read live ([components/README.md](../components/README.md)).
- **Not counted yet.** A red `main` and a worker stopped by the usage limit leave no mark on an
  issue, so they add nothing until one does.

## Overhaul due

```toml
[overhaul]
due_after = 3  # retros closed since the last overhaul started; 0: off
days = 30      # or this many days after it started, with a retro closed; 0: off
```

An overhaul falls due after `due_after` retros closed since the newest overhaul started, or `days`
days after that start with a retro closed; a retro closed as a duplicate or as not planned does
not count. It is filed first and holds filing back like a retro ([Retro due](#retro-due)).

- **On unless both are 0.** With `due_after` and `days` both 0 the countdown is off: the greeting
  names no overhaul, and the retro and the overhaul score earlier findings as they did before it.
- **Too early to score.** With it on, an earlier finding that an issue still open takes is listed
  as `too early to score`, by `retro.py collect` and `overhaul.py read`, not scored as a failure.
- **One store.** `scripts/overhaul.py` owns the count (`overhaul_countdown`, a pure function of the
  runs it is given); the retro-due component counts the same into its name, `retro-due/due`, by its
  configs `overhaul-after` and `overhaul-days`.

## Stop hook

```toml
[stop]
refusals = 5
```

The plugin hands every `Stop` and `SubagentStop` to `work_tickets.py stop-check`, so a worker's turn
ends only with its work issue delivered; Copilot hands its `Stop` the same way
(`.github/hooks/se.json`), a check that fails open.

The hook scripts read both hosts' payloads alike: [scripts/hosts.sh](../scripts/hosts.sh), the host
table, names the project variable, the host and cloud marks, the hook file's host selector and
Copilot's camelCase fields.

- kern answers it within the hook: `wiring.toml` binds both events to the delivery component's
  `stop-check`, which judges in its own warm process ([Kern](start.md#kern)).
- Where no command of kern's answers (no binary, no core, the component's process not attached
  yet, or it failed), [scripts/se_hook.sh](../scripts/se_hook.sh) runs `stop-check` as a process of
  its own, with the same verdict.
- The warm process asks `gh auth status` once: a gh found unusable is held 60 s, a usable one for
  the process.

| measured on 13 Nov in a Claude Code cloud container, Linux amd64, gh not signed in, 6 runs | wall time |
|---|---|
| a Stop through `se_hook.sh`, answered by kern's delivery component: the first; the later ones | 319 ms; 24 to 57 ms |
| a Stop through `se_hook.sh`, answered by `stop-check` directly through `uv` | 434 to 586 ms |

What it judges:

- Where it refuses: a checkout whose ticket queue (`.se/work/`) is for a work issue (intake's
  snapshot, or what was recorded as read of it), on a branch other than the integration branch.
- What it refuses: the stop, while the branch has no open pull request whose description carries a
  field report that passes `field-report --check` at the branch tip. The refusal names what is
  missing and the commands that deliver.
- `refusals` is how often in a row it refuses, built in 5; then it lets the turn end and says so,
  and counts afresh. A passing stop resets the count.
- Under Copilot it never refuses unless `[copilot] refuse_stop` is true: it names what is
  undelivered as Copilot's hook warning, as each refusal costs the person a model turn
  ([docs/copilot.md "What a session costs"](copilot.md#what-a-session-costs)).
- A `SubagentStop` is judged only for a worker sub-agent (`worker`, `se:worker`), in the checkout
  it works in, one whose queue is for a work issue:
  - one its prompt names, else the one whose ticket queue its transcript (the event's
    `agent_transcript_path`) last touched, a path into `.se/work/` or a `--worktree`;
  - only where neither names one, the hook's `cwd`; where that holds none either, it lets the
    sub-agent end and says why.
- It also refuses in any checkout it judges, worker or not, while a changed file a template claims
  breaks it ([Templates](templating.md#templates)).
- Anywhere else (SE's own session, a person's session) it never refuses. Where it cannot judge it
  lets the turn end and says why: advice fails open.
- Without gh it judges by the answer file `.se/work/pull-request.json`, which
  `stop-check --pull <number> --pr-description <file>` writes from the pull request the session's
  GitHub tools opened; without either, it cannot judge.

## Work publication

A work branch is published only to the repository its work issue is for, never to whatever
origin happens to be. `work_tickets.py push`, and `deliver` through it, check origin before
anything is pushed or a pull request opened; the integration branch and landing branches keep
their own guards.

- The work issue is the one the checkout records (`intake`), titled like the branch.
- The repository it is for is its one `repo:<name>` label, which every work issue SE files
  carries. Without one, it is the repository holding the issue, or the checkout's own where that
  repository is the tracker the checkout routes its issues to.
- Origin passes where its repository name is that name, in any case: a name, not a host or an
  owner, so the rule holds wherever the project lives.
- Refused, naming the remedy, with nothing pushed: no recorded work issue, a recorded one titled
  like another branch, more than one `repo:` label, no origin, and an origin of another name.

## Late push

```toml
[deliver]
late_push = "warn"
```

A push of the work branch after its delivery makes the field report's Branch tip stale, and the
integrator refuses it at the landing. The pre-push hook names it at the push instead
([scripts/late_push.py](../scripts/late_push.py)).

- `deliver` records the tip it delivers in the checkout, `.se/work/delivered-tip.json`; without
  gh, `stop-check --pull` records the Branch tip of the description it is given.
- The hook's guard, `work_tickets.py verified`, prints one line for a push of that branch at
  another commit: the delivery is now stale, the integrator will refuse it, and `deliver` must run
  again after the push. Before any delivery it says nothing.
- `late_push` is `"warn"`, built in: the push goes through. `"refuse"` refuses it; then the
  redelivery pushes through `deliver`, which records its tip first, or without gh through
  `work_tickets.py push --redeliver`.

## Review gate

```toml
[integrate]
review_gate = false
review_gate_risky = ["major", "rule-book", "role-file", "history"]
```

`review_gate` is off, built in: `integrate` reads no review. On, `integrate` refuses a risky change
whose work pull request has no reviewer's `pass` or `pass with open points` of the head that lands
(`review.py file`'s comment), before anything is pushed, naming the risks and this setting.

`review_gate_risky` lists the kinds that count as risky, all four built in: a major release, a
change to the rule book (AGENTS.md, the work model's rules.md), to an agent's role file
(`src/agents/`), or one that rewrites history. [scripts/review_gate.py](../scripts/review_gate.py)
owns each kind and the decision.

Without gh the comments are read only for a risky change: the session saves them with its GitHub
tools (`issue_read get_comments`) and passes them as `--pr-comments <file>`.
