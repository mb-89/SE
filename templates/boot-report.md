---
# SE's start report, the first text a session shows the person (docs/boot.md "The start report"):
# a snippet, which scripts/se_start.py fills and scripts/interfaces.py writes through the schema
# generated into scripts/interfaces/. scripts/templates.py's docstring owns this note's format.
name: boot-report
version: 1.1.0
kind: interface
reader: owner
says: "SE's start report: its version, what it loaded with links into the documentation, each component's loaded and newest version, and the one update command."
tags: ["message", "start"]
message: "SE {version} started\n[{skills} skills]({skills_page})\n[{rules} rules]({rules_page})\n[{subagents} sub-agents]({subagents_page})\n[Documentation]({docs})\n\n| component | loaded | newest |\n|---|---|---|\n{components}\n\n{update}"
applies:
  actions: ["message.send"]
  marker_pattern: "SE \\S+ started"
rules:
  required: refuse
  choice: refuse
fields:
  - name: version
    kind: line
    required: true
    says: "The version of the SE that runs, as its se.toml names it."
  - name: skills
    kind: line
    required: true
    says: "How many skills loaded, guidance notes aside."
  - name: skills_page
    kind: line
    required: true
    says: "The documentation's page that lists the skills."
  - name: rules
    kind: line
    required: true
    says: "How many rules are in force: the rule book's and every guidance note."
  - name: rules_page
    kind: line
    required: true
    says: "The documentation's page that lists the rules."
  - name: subagents
    kind: line
    required: true
    says: "How many sub-agents loaded: every agent but SE."
  - name: subagents_page
    kind: line
    required: true
    says: "The documentation's page that lists the sub-agents."
  - name: docs
    kind: line
    required: true
    says: "The documentation's home."
  - name: components
    kind: rows
    required: true
    row: "| {name} | {loaded} | {newest} |"
    says: "SE first, then SE's required components with the version that answered at this start (none where one did not load), then every component of the project's tree, nested ones included, but one a required row shows: its name, the version loaded and the newest release."
  - name: update
    kind: case
    required: true
    cases:
      due: "To update: /se:update"
      next: "The next SE release brings {names}."
      due_next: "To update: /se:update. The next SE release brings {names}."
      stopped: "Not loaded: {names}. SE cannot start."
      current: "Everything is current."
      unknown: "Newest versions not read yet; the next start shows them."
    says: "From the table's rows alone (docs/boot.md \"The start report\"): stopped where a required row did not load; else next where a row SE locks is behind its newest release, due where another row is, due_next where both are; else unknown where a newest version is not read; else current."
  - name: names
    kind: line
    says: "What the case names: the required components that did not load, or each row SE locks that is behind, with its newest release (`kern 2.2.0 and obs 10.4.0`); empty for the other cases."
example:
  fields:
    version: "12.0.1"
    skills: "3"
    skills_page: "https://example.com/se/#docs-skills"
    rules: "69"
    rules_page: "https://example.com/se/#docs-rules"
    subagents: "4"
    subagents_page: "https://example.com/se/#docs-sub-agents"
    docs: "https://example.com/se/"
    components:
      - name: SE
        loaded: "12.0.1"
        newest: "13.0.0"
      - name: kern
        loaded: "2.1.0"
        newest: "2.2.0"
      - name: obs
        loaded: "10.3.2"
        newest: "10.3.2"
      - name: obs-html
        loaded: "0.5.2"
        newest: "0.5.2"
    update: due_next
    names: "kern 2.2.0"
---
