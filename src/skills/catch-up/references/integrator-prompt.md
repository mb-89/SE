# Integrator prompt template

Fill every `<...>`; the [integrator definition](../../../agents/integrator.md) holds the
rules. Start it as an independent session with the main checkout as `workspace` and
`worktree: false`.

```text
Act as the integrator agent defined in <se>/.github/agents/integrator.agent.md (read it first, plus
the project's AGENTS.md).
Main checkout: <path>
SE session for escalations: <SE session>
```
