package rules_test

import (
	"testing"

	"github.com/mb-89/SE/src/internal/rules"
)

// kinds is a registry of kinds with two agents, each with its role.
var kinds = map[string]string{"worker": "work", "reviewer": "review"}

func agent(name, model string) string {
	return "---\nname: " + name + "\ndescription: d\nmodel: " + model + "\n---\n\n# A\n\nReader: r.\n"
}

func TestEveryAgentRunsTheModelTheOneConfigSets(t *testing.T) {
	t.Parallel()
	found := checkIn(t, &rules.Repo{Agents: kinds}, "agents", map[string]string{
		rules.ModelsConfig:                    "# models\nworker: opus\nreviewer: fable\n",
		rules.AgentsDir + "/worker.md":        agent("worker", "opus"),
		rules.AgentsDir + "/reviewer.md":      agent("reviewer", "fable"),
		"src/plugin/skills/briefing/SKILL.md": "x",
	})
	same(t, found, nil)
}

func TestAnAgentOutOfStepWithTheRegistryTheConfigOrTheSkillsIsFound(t *testing.T) {
	t.Parallel()
	found := checkIn(t, &rules.Repo{Agents: kinds}, "agents", map[string]string{
		rules.ModelsConfig: "worker: opus\nreviewer: fable\nboxer: opus\n",
		// A model written twice and out of step, and a skill still holding the role.
		rules.AgentsDir + "/worker.md":    agent("worker", "sonnet"),
		"src/plugin/skills/work/SKILL.md": "x",
		// A file the kinds does not name, under a name that is not its own.
		rules.AgentsDir + "/stray.md": agent("strays", "opus"),
	})
	same(t, found, []string{
		rules.ModelsConfig + ":1: agents: the agent reviewer has no file " + rules.AgentsDir + "/reviewer.md",
		rules.ModelsConfig + ":1: agents: it sets a model for boxer, which is no agent of the registry of kinds",
		rules.AgentsDir + "/worker.md:1: agents: its model is \"sonnet\", but " + rules.ModelsConfig + " sets \"opus\"",
		rules.AgentsDir + "/worker.md:1: agents: the skill src/plugin/skills/work holds the role this agent holds: one role, one file",
		rules.AgentsDir + "/stray.md:1: agents: no kind in the registry of kinds names the agent stray",
		rules.AgentsDir + "/stray.md:1: agents: its front matter's name is \"strays\", not its file's, \"stray\"",
		rules.AgentsDir + "/stray.md:1: agents: " + rules.ModelsConfig + " sets no model for stray",
	})
}
