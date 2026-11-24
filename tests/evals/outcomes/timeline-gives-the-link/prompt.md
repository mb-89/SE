---
schema_version: "1.0"
name: timeline-gives-the-link
description: Asked for the Timeline from a phone, SE gives the published page's link at once instead of rebuilding the page in the session.
tags: [timeline]
runs: 3
max_turns: 20
timeout_seconds: 600
allowed_tools: [Skill, Read]
expected_outcome: One short reply whose first line gives the Timeline's link, the documentation's address with timeline.html appended, and no table or page built in the session.
---

SE's start report for this session ended with these lines:

```text
[5 skills](https://docs.example.com/project/#docs-skills)
[Documentation](https://docs.example.com/project/)
```

Can you create the timeline for the repo so I can see it? I'm on my phone, so I can see it in this
chat. It should tell me what is done and what is waiting for the integrator.

This run has no shell and no GitHub tools.
