---
name: readme-is-one-page
description: 'A README is one A4 page: the one command that installs the software and runs its showcase first, then the documentation link, the pitch in five sentences and links. Read it before you write or change a README.'
tags: [work]
---

The person's rule of 23 Nov, for all software SE builds:

> The README is a one-pager, so not more than would fit on one A4 page. How do you install it? How
> do you get it? Like the showcase command on how you run it. Usually there would be one command
> that that's actually also the smoke test on the fact that everything works

And of 24 Nov, on what it holds: a landing page, the three-minute elevator pitch. What is the idea,
who is it for, what are its big value propositions, how do I install it, where is the full
documentation. Never feature, command or mechanism detail: that is the documentation's.

## The shape

1. **One page.** At most 60 lines and 3,500 characters, headings included.
2. **The command first.** Within the first 10 lines, a code block of one command that gets the
   software, installs it and runs its showcase. It is the smoke test: it exits non-zero when
   anything is broken. Beside it, in the same lines, a link whose text names the full
   documentation.
3. **What it is.** Then the idea, who it is for and its big value propositions, in at most five
   sentences.
4. **Links to the rest.** Then a list of links: the documentation's chapters, the license, the
   agent guide.

Everything else the README held moves to the documentation, and every reference to a moved
section names its new page (`docs/<page>.md "<section>"`), never `README "<section>"`.

## The check

`uv run python <se>/scripts/readme.py check --root <checkout>` refuses a README that breaks the
shape, naming each finding. Run it at commit, as one of the project's
[commit checks](../docs/settings.md#commit-checks) (se.toml `[commit_checks]`), and in CI.
`readme.py showcase --url <clone address> --branch <branch>` prints the README's command with the
clone address CI fetches, for a job on a fresh runner to run as a person would. SE's own README is
held to it by its hygiene check `readme`.

Not picked: raising the size limit, which keeps the manual in the README.
