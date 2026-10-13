# How work lands

1. Work on your own branch. main takes merged PRs alone.
2. Run `sh ./tests/check.sh` before every push. The pre-push hook runs it too, and a push that skips the hook is refused.
3. Once check.sh passes, open one PR against main and turn on auto-merge (squash).
4. A red CI run on your PR is yours: fix it on the same branch and push.
5. Create no other branches: no backups, no heartbeats, no rescue branches.
6. Agents create SE issues only through `se issue new`, and set their dependencies only with its `--blocked-by`.
7. As much as possible is mechanized; as little as possible relies on agent judgment. Every step that can be a deterministic `se` command, with tests, is one. A box keeps only what needs judgment: doing the issue's work and fixing a red CI run.
