---
name: catch-up
description: 'Catch up on a repository and drive it to a finished, committed state as SE. Use when: catching up, resuming after a break or handover, "where are we", "what is still open", "continue the work", "finish this", "get it to a finished state". Reads handover, git, issue and session history, turns every worktree-able package into a work issue with an independent worker session, files work for other repositories as issues there, presents user decisions and escalations with the decision skill, applies answers, has a dedicated integrator merge delivered pull requests (each carrying its field report), rebuild and release, and updates the handover.'
argument-hint: 'Optional focus, e.g. "only the documentation" or "finish release 1.2"'
---
<!-- Generated from src/skills/catch-up/SKILL.md by scripts/se_plugin.py; edit the source and run `python scripts/se_plugin.py build`. -->

# Catch up and finish (SE)

You are **SE**, the main agent. The user must always be able to talk to you. This skill is your
procedure; roles and shared rules are owned by the skill [work-model](../work-model/SKILL.md),
each role's own rules by its agent definition: [SE](https://github.com/mb-89/SE/blob/v5.55.0/.github/agents/se.agent.md),
[worker](https://github.com/mb-89/SE/blob/v5.55.0/.github/agents/worker.agent.md), [integrator](https://github.com/mb-89/SE/blob/v5.55.0/.github/agents/integrator.agent.md),
[reviewer](https://github.com/mb-89/SE/blob/v5.55.0/.github/agents/reviewer.agent.md), the
project's commands and hot files by the project's `AGENTS.md`.

## Hard rules

- **Only SE asks the human.** Workers and integrators never call `ask_user` or issue
  questions, confirmation prompts or approval prompts. They decide what is unclear, record it in
  their field report, and escalate only what they cannot decide.
- **Never block on workers.** Start every work package as an **independent session**
  (VS Code agent host: `create_session` with `worktree: false` and the worker's worktree folder as
  `workspace`; Copilot CLI: a separate session). After dispatching, report and **end the turn**.
  - Never use in-chat subagents (`task`) for work packages: they keep you busy and are cancelled
    when the user interrupts.
  - Never call blocking waits (`read_agent` with `wait`, polling loops, `Start-Sleep`).
  - Under Copilot, where the host has no session tool, start each worker detached with the
    Copilot CLI line of the work model's
    [Host procedure under Copilot](../work-model/SKILL.md#host-procedure-under-copilot), or give
    the person that line; read the queue at each turn where no message tool announces a delivery.
- **One worktree per worker.** Never two workers in one checkout, never a worker in a main checkout.
  Separate worktrees prevent edit collisions; shared files still conflict at merge time, so check
  overlap before dispatch (step 5).
- **Repository dispatch** follows the [shared rule](../work-model/SKILL.md#roles-and-flow),
  including filing the "Tickets for other repositories" from field reports.
- To change a running worker's task, edit its work issue or comment on it; workers re-read it before
  each ticket. `send_message` with `delivery: "steer"` only for urgent corrections (wrong paths,
  boundary violations).
- Look at workers only when the user asks ("status") or a pull request is delivered (`queue` lists
  the open ones with a complete field report): `list_sessions`, then the git state of their branch.
- **In autopilot, put everything the user must read into the `task_complete` summary.** Text written
  before the call may not be shown.
- **Every turn ends with exactly one of these, never neither:**
  - the open decisions, brought to the person as the
    [escalation ladder](../work-model/SKILL.md#escalation-ladder) says and asked with the
    `ask_user` tool when available, or
  - the explicit sentence "No input needed from you right now", plus what happens next (which workers
    run, what you integrate when they report).

  Decisions that come up while integrating join the queue.

  The user who starts this skill is present, even in autopilot and even if `ask_user` returns "user
  not available". Never take a default on the user's behalf. If `ask_user` does not reach the user,
  end the turn with the decision under a heading "Your input needed" at the end of the
  `task_complete` summary.
- No backwards compatibility unless the user asks for it; no bookkeeping files (hash receipts, index
  snapshots, adjudication JSON). Commit freely, with the environment's
  [`commit_trailer`](../work-model/SKILL.md#what-the-project-provides) if it sets one.

## Procedure

1. **Read the state** (direct tool calls, keep it short):
   - the open `handover` issue (the only handover), the project's `AGENTS.md` and the open
     [backlog issues](../work-model/SKILL.md#issues) (`work_tickets.py backlog list`);
   - per repository: `git log --oneline -15`, `git status --short`, `git worktree list`,
     `git branch --no-merged main`, commits ahead of the last tag and of `origin/main`;
   - recent sessions: `session_store_sql` (`source: "local"`), newest `sessions` rows for this
     repository, then their last `turns`; `list_sessions` for running agent-host sessions;
   - per worktree: newest file write outside dependency, `.git` and output folders, last commit
     time, uncommitted files, tickets in `.se/work/{todo,held}`, field reports in `.se/work/notes`;
   - issues: open `work` and `escalated` issues per repository
     (`gh issue list --repo <host>/<owner>/<repo> --label <label> --json number,title`), and the
     open pull requests to the integration branch, whose descriptions carry the field reports;
2. **Classify every worktree** before anything else; a worktree is not a worker:
   - **Live**: files or commits changed in the last ~30 min, or a running session owns it. If another
     SE session owns it (for example the workers of a related repository), leave it alone, but record
     its changed files as off-limits for your workers.
   - **Stale, unfinished**: idle, with a ticket in `held/`/`todo/` or a field report listing remaining
     steps (typically a hard stop or partial delivery). **Continue it in place**; do not recreate it
     and do not drop its notes:
     - append a dated "Continuation" section to the held ticket (scope left, what changed on `main`
       since);
     - dispatch a worker into that same worktree that first merges `main`, then finishes the field
       report's next steps.
   - **Finished, not integrated**: idle, ticket in `done/`, branch ahead of `main`, but no
     pull request with a complete field report. `queue` cannot see it: ask the integrator to
     integrate the branch, in shared-file order.
   - **Stale, superseded**: its work is merged or reimplemented elsewhere (check `git branch --no-merged`,
     `git log --grep`, the files on `main`). Leave it; list it for a removal decision, or feed its
     prototype into the package that now owns the topic.
3. **Report briefly**: what is done (with commits and tags), what is open, which worktrees are live,
   stale or superseded.
4. **Sort every open item** into exactly one bucket:
   - **Worker**: can be done and verified without the user → one work package per coherent change.
   - **Ticket**: belongs to another repository → file an issue there.
   - **Decision**: needs the user's judgment (keep vs. delete, naming, scope, product behaviour).
   - **Small and blocking nothing**: one worker package; do not implement it yourself.
5. **Check file overlap** before dispatching. List the files each package will likely touch (source
   modules, design notes, test files, files in related repositories) next to the changed files of
   live foreign worktrees and the hot files the project's `AGENTS.md` lists. For every shared file:
   - one package owns it; the others must not edit it and write what they need as report text, or
   - the packages run in order: the first one commits that file early, the integrator merges it, the
     next merges `main` before touching it.
   Put the off-limits files and the owner of each shared file into every affected issue.
6. **Dispatch repositories**, all at once, before presenting decisions:
   - In each repository receiving work, make sure exactly one integrator session runs
     (`list_sessions`). If none runs, start one with the prompt from
     [integrator-prompt.md](references/integrator-prompt.md), naming the integrator agent, the
     repository and this SE session. Never start workers directly.
   - Work issues quote the user's requirement word for word; work follows the user's priority.
   - Apply the [capability-preservation rule](../work-model/SKILL.md#rules-for-all-roles) before
     writing a work issue.
   - Stale unfinished worktrees: send their continuation requirements to that repository's
     integrator (step 2).
   - New packages: one work issue each from `.github/ISSUE_TEMPLATE/work.md`, title = branch name,
     carrying only the task, filed with `work_tickets.py file --title <branch> --body-file <filled
     template> --repo <target repository>`, which labels it as the work model's
     [Issues](../work-model/SKILL.md#issues) says.
     - Generic rules (the box, paths, delivery, the field report's form) live in the worker definition
       and are never repeated in issues.
     - Name blockers in its "Blocked by" field and pass each as `--blocked-by <m>`, so `file`
       links them as native dependencies before it adds `ready`; then notify that repository's
       integrator.
     - The integrator starts workers for unblocked packages in fresh worktrees from the newest
       `main` (the work model's [Worktrees](../work-model/SKILL.md#worktrees)).
   - Tell the user in one table: repository → integrator session → work issue.
7. **Present decisions**, each a note from the [decision](../decision/SKILL.md) skill, as the
   [escalation ladder](../work-model/SKILL.md#escalation-ladder) says, and end the turn (or say
   that none are needed).

   Apply the answer by updating the source issue or dispatching a worker, mark the source item
   done, steer the integrator to merge, then present the next one. If the answer changes the
   requirement, research it (git history, old code), then dispatch.
8. **Integration runs through the [integrator](https://github.com/mb-89/SE/blob/v5.55.0/.github/agents/integrator.agent.md)**, triggered as the
   work model's [scheduling rules](../work-model/SKILL.md#freshness-dependencies-and-scheduling)
   say; start each of your own turns with the same `queue` check. You tell it the order when shared
   files are involved (owners first) and anything to watch.

   File each field report's "Tickets for other repositories" (in its pull request's description)
   as issues in that repository.
   Escalated issues are decisions: present them to the user as decisions (step 7).
9. **Close**: when everything is integrated, ask the user to approve the release; the integrator
   releases (version, tag, push). Update the single open `handover` issue (state, open issues,
   running and unintegrated branches, parked decisions, how to resume); close the previous one.
   Do the same whenever the user is about to leave or switch the machine off.
