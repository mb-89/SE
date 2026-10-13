# How work lands

1. Work on your own branch. main takes merged PRs alone.
2. Run `sh ./check.sh` before every push. The pre-push hook runs it too, and a push that skips the hook is refused.
3. Once check.sh passes, open one PR against main and turn on auto-merge (squash).
4. A red CI run on your PR is yours: fix it on the same branch and push.
5. Create no other branches: no backups, no heartbeats, no rescue branches.
