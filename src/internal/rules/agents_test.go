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
		rules.WiringFile:                      noReuse,
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
		rules.WiringFile:   noReuse,
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

// noReuse is a reuse config whose tiers run nothing, so no agent preloads.
const noReuse = "instances:\n  reuse: {module: reuse}\n"

// reuseWiring is a reuse config with a plugin of one skill and one agent, a
// worker's and an author's list, and a reviewer's that names the agent.
const reuseWiring = "instances:\n  reuse:\n    module: reuse\n    config:\n" +
	"      sources: [{name: kit, repo: o/r, path: ., commit: 8bd00f08f0b04705e610cf132fbe2cf5ec44cfe3, licence: MIT, agents: [hunter]}]\n" +
	"      worker: [simplify]\n      author: [kit:writer, simplify]\n      reviewer: [kit:hunter, security-review]\n"

func TestAnAgentPreloadsItsTiersListsLessTheirAgents(t *testing.T) {
	t.Parallel()
	preloading := func(name, skills string) string {
		return "---\nname: " + name + "\ndescription: d\nmodel: opus\n" + skills + "---\n\n# A\n\nReader: r.\n"
	}
	agents := map[string]string{"worker": "work", "reviewer": "review", "overhaul": "overhaul", "boxer": "box"}
	models := "worker: opus\nreviewer: opus\noverhaul: opus\nboxer: opus\n"
	// The worker preloads its list and the author's, once each, as a flow
	// or a block list; the reviewer its list less the agent; the overhaul,
	// whose list is empty, and the boxer, of no tier, nothing.
	found := checkIn(t, &rules.Repo{Agents: agents}, "agents", map[string]string{
		rules.ModelsConfig:               models,
		rules.WiringFile:                 reuseWiring,
		rules.AgentsDir + "/worker.md":   preloading("worker", "skills: [simplify, kit:writer]\n"),
		rules.AgentsDir + "/reviewer.md": preloading("reviewer", "skills:\n  - security-review\n"),
		rules.AgentsDir + "/overhaul.md": preloading("overhaul", ""),
		rules.AgentsDir + "/boxer.md":    preloading("boxer", "skills: []\n"),
	})
	same(t, found, nil)
	// A field that differs from its tiers' lists either way is found: one
	// that leaves a skill out, one that preloads an agent, one out of order,
	// and one on an agent of no tier.
	found = checkIn(t, &rules.Repo{Agents: agents}, "agents", map[string]string{
		rules.ModelsConfig:               models,
		rules.WiringFile:                 reuseWiring,
		rules.AgentsDir + "/worker.md":   preloading("worker", "skills: [simplify]\n"),
		rules.AgentsDir + "/reviewer.md": preloading("reviewer", "skills: [kit:hunter, security-review]\n"),
		rules.AgentsDir + "/overhaul.md": preloading("overhaul", ""),
		rules.AgentsDir + "/boxer.md":    preloading("boxer", "skills: [simplify]\n"),
	})
	at := func(agent, got, tiers, want string) string {
		return rules.AgentsDir + "/" + agent + ".md:1: agents: its front matter's skills are " + got + ", but " + tiers + " in the reuse config of " +
			rules.WiringFile + ", less its agents, is " + want + ": preload what the tier runs, as its list says"
	}
	same(t, found, []string{
		at("worker", "[simplify]", "the worker and the author list", "[simplify, kit:writer]"),
		at("reviewer", "[kit:hunter, security-review]", "the reviewer list", "[security-review]"),
		at("boxer", "[simplify]", "no tier's list", "[]"),
	})
}
