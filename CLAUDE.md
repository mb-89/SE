# How work lands

Reader: an agent working in this repository.

In an interactive session with a person, talk design; work that is clear
becomes an issue (`se issue new`) for the cloud fleet, not work you do
yourself ([principle 20](spec/principles.md)).

SE's design principles, which the retro and the overhaul measure against, are in [spec/principles.md](spec/principles.md).

1. Work on your own branch. main takes merged PRs alone.
2. Land with `se issue land`, which checks, pushes and opens the PR ([spec/issues.md](spec/issues.md#the-commands)); green is `sh ./tests/check.sh` ([spec/development.md](spec/development.md#checks)), and what refuses a change whose check failed is CI's required check ([the gate](spec/development.md#the-gate)).
3. A red CI run on your PR is yours: fix it on the same branch and push.
4. Create no other branches: no backups, no heartbeats, no rescue branches.
5. Create SE issues and their dependencies only as [spec/issues.md](spec/issues.md#the-rules) says.
6. Mechanize first, as [principle 1](spec/principles.md) says: what can be a tested `se` command is one, not a step an agent remembers.
7. An ad hoc script you write while working goes to `src/scripts/`, in the same PR, as [its README](src/scripts/README.md) says.
8. A new skill goes to `src/plugin/skills/<name>/SKILL.md`, never into this repository's `.claude` folder. Plugin skills appear as `se:<name>`.
