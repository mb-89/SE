---
name: timeline
description: 'Where SE''s Timeline is and what it shows: the published page of the issues and releases of every repository SE serves, by place (Today, Waiting for integrator, Needs you, Next, Backlog, Done). Use when the person asks for the Timeline, the status, what is done, what is in progress, or what waits for the integrator or for them: give its link at once, never rebuild the page in the session.'
---

# Timeline (SE)

The Timeline already exists. SE's docs workflow builds it and publishes it beside the
documentation as `timeline.html`, hourly and on each issue event
([Documentation](../../../docs/documentation.md)). When it opens, the page asks GitHub
itself for what changed since, so it is current without anyone rebuilding it.

## Give the link

1. Its address is the documentation's with `timeline.html` appended: the start report's
   Documentation link, or what `uv run python <se>/scripts/se_home.py --repo <se> docs` prints.
2. Answer with that link first, in one line, and say that the page reads GitHub when it opens.
   It works on a phone as it is.
3. Then, only where the person asked, name what the question needs from it, such as how many rows
   wait for the integrator, read from the issues and pull requests themselves.

## What it shows

One table of the repositories in SE's `se.toml` `[timeline]`, newest first in each place:

| Place | What is in it |
|---|---|
| Today | open issues labelled `in-progress` |
| Waiting for integrator | open issues named by an open pull request to the integration branch that carries a field report |
| Needs you | open issues labelled `se-person` |
| Next | open issues labelled `ready` |
| Backlog | ideas labelled `backlogged`, not yet work |
| Done | closed issues and releases |

[`<se>/scripts/timeline.py`](../../../scripts/timeline.py) owns the places, the read and the live read.

## Never rebuild it

- Never build the page, or a copy of it, in a session: no run of `timeline.py`, no snapshot read
  from GitHub, no table, artifact or page put together from issues to stand in for it.
- A page that shows something wrong or misses something is a work issue for
  `<se>/scripts/timeline.py`, filed as the work model's issues are
  ([work-model](../work-model/SKILL.md)), never a page made by hand.
