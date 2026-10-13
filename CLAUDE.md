# How work lands

SE's design principles, which the retro and the overhaul measure against, are in [spec/principles.md](spec/principles.md).

1. Work on your own branch. main takes merged PRs alone.
2. Run `sh ./tests/check.sh` before every push. The pre-push hook runs it too, and a push that skips the hook is refused.
3. Once check.sh passes, open one PR against main and turn on auto-merge (squash).
4. A red CI run on your PR is yours: fix it on the same branch and push.
5. Create no other branches: no backups, no heartbeats, no rescue branches.
6. Agents create SE issues only through `se issue new`, and set their dependencies only with its `--blocked-by`.
7. As much as possible is mechanized; as little as possible relies on agent judgment. Every step that can be a deterministic `se` command, with tests, is one. A box keeps only what needs judgment: doing the issue's work and fixing a red CI run.
8. An ad hoc script you write while working (a check, a query, a one-off helper) is committed under `src/scripts/` in the same PR, named for what it does, with one comment line at the top saying why it was needed. Nothing else in the repository depends on `src/scripts/`.
9. A new skill goes to `src/plugin/skills/<name>/SKILL.md`, never to `.claude/skills/`. Plugin skills appear as `se:<name>`.
