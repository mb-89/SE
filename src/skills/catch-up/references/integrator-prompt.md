# Integrator prompt template

Fill every `<...>`; the [integrator definition](../../../agents/integrator.md) holds the
rules. Start it as an independent session with the main checkout as `workspace` and
`worktree: false`, titled `work_tickets.py session-title integrator <project>`
(`SE/<project>/integrator`) and tagged `SE`, no other tag
([Visible sessions](../../work-model/SKILL.md#visible-sessions)).

```text
Act as the integrator agent defined in <se>/.github/agents/integrator.agent.md (read it first, plus
the project's AGENTS.md).
Main checkout: <path>
SE session for escalations: <SE session>
```
