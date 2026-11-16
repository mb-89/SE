# Clarify against the tree

Before any record, write the open questions as a list. A record written before its questions
are answered restates the request instead of narrowing it.

## The look

Every command, file, flag or setting the request names is one open question. Answer each by
looking it up on the base branch, fetched just before the look, never on a checkout of earlier
that day: what landed an hour ago changes the answer.

Show the look, so the answer can be checked. For example:

```sh
git fetch origin main
git ls-files <path>            # a file: is it tracked on the base branch?
<command> --help               # a command or flag: does its parser define it?
git grep -n <setting>          # a setting: where is it read, where is it written?
```

## The three results

Each question gets exactly one result:

- **There**, with its path: the base branch has it. The record builds on it, naming the path.
- **Missing, to be made**: the base branch lacks it and the request asks for it. It becomes a
  requirement.
- **Asked of the person**: the base branch lacks it and the request assumes it exists. Whether it
  is to be made, or the request is wrong, is the person's call; ask before writing the record.

An ask the base branch already meets is cut from the requirements, naming where it is met.

## Examples

Each example is SE's own, tied to its result.

- **Missing, so asked of the person.** In the retro of 12-13 Nov, issue #748's requirement 1
  listed a paused command that neither work_tickets.py nor se_start.py had on main at 9bade48.
  The command landed an hour later, with feat/pause-stops-the-fleet-20261106. A look on a stale
  checkout would have asked the person about a command that already existed; that is why the look
  runs on the freshly fetched branch.
- **There, with its path.** In the same retro, issue #875's reviewer procedure named
  `review.py brief` and `review.py file`. The look found both in `<se>/scripts/review.py`, with
  their help text: `uv run python <se>/scripts/review.py --help` lists `{brief,file}`.
- **Cut, naming where it is met.** obs#658's field report, from the obs repository: the issue
  asked to add what was already there. The ask is cut, and the record names where it is met.
