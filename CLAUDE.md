# How work lands

Reader: an agent working in this repository.

SE's design principles, which the retro and the overhaul measure against, are in [spec/principles.md](spec/principles.md).

1. Work on your own branch. main takes merged PRs alone.
2. Run `sh ./tests/check.sh` before every push. The pre-push hook runs it too, and a push that skips the hook is refused.
3. Once check.sh passes, open one PR against main and turn on auto-merge (squash).
4. A red CI run on your PR is yours: fix it on the same branch and push.
5. Create no other branches: no backups, no heartbeats, no rescue branches.
6. Create SE issues and their dependencies only as [spec/issues.md](spec/issues.md#the-rules) says.
7. Mechanize first, as [principle 1](spec/principles.md) says: what can be a tested `se` command is one, not a step an agent remembers.
8. An ad hoc script you write while working goes to `src/scripts/`, in the same PR, as [its README](src/scripts/README.md) says.
9. A new skill goes to `src/plugin/skills/<name>/SKILL.md`, never into this repository's `.claude` folder. Plugin skills appear as `se:<name>`.
