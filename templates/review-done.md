---
# The one message a cold reviewer sends SE's session once `review.py file` has posted its comment
# (src/agents/reviewer.md step 10). Its schema is generated into scripts/interfaces/; no code sends
# it, as kern's door offers no command that does. scripts/templates.py's docstring owns this note's
# format.
name: review-done
version: 1.0.0
kind: interface
reader: fleet
says: "A cold review's end: the reviewed pull request, the verdict and the review comment's link."
tags: ["message", "review"]
message: "review of PR #{pr}: {verdict}, {url}"
applies:
  actions: ["message.send"]
  marker_pattern: "review of PR #.+: .+, .+"
rules:
  required: refuse
  choice: refuse
fields:
  - name: pr
    kind: line
    required: true
    says: "The number of the reviewed pull request, digits alone."
  - name: verdict
    kind: choice
    required: true
    says: "The review's verdict: pass, pass with open points or decline."
    choices:
      - review:VERDICTS
  - name: url
    kind: line
    required: true
    says: "The link of the review comment `review.py file` posted."
example:
  fields:
    pr: "5"
    verdict: pass with open points
    url: "https://example.com/pull/5#issuecomment-1"
---
