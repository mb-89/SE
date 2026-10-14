package issues

// The registry of kinds: what an issue is, by its structure and its labels,
// and the plugin's agent that works it. A take names the agent from here,
// and nothing else maps a kind to an agent; the agent's file,
// src/plugin/agents/<agent>.md, holds the role's whole procedure.

// Plugin is the plugin whose agents work the issues: an agent's type in a
// session is Plugin:<agent>.
const Plugin = "se"

// AgentsDir holds the plugin's agents, one file each, under a checkout.
const AgentsDir = "src/plugin/agents"

// Kind is one kind of issue and the agent that works it.
type Kind struct {
	// Name is the kind: leaf, parent, gate, retro or overhaul.
	Name string
	// Agent is the agent's name, its file's name without .md.
	Agent string
	// Role is the word the role went by as a skill, which no skill may
	// take again: one role, one file.
	Role string
	// What says which issues are of the kind.
	What string
}

// IssueKinds is every kind, each with its agent.
var IssueKinds = []Kind{
	{Name: "leaf", Agent: "worker", Role: "work", What: "an issue with no sub-issues: work, landed into its manifest's branch"},
	{Name: "parent", Agent: "coordinator", Role: "coordination", What: "an issue with sub-issues, a manifest at the top: the box coordinates its tree and lands it as one PR, as it runs the queue and checks the fleet when nothing is ready"},
	{Name: "gate", Agent: "reviewer", Role: "review", What: "an se-review parent ready for review: reviewed cold"},
	{Name: "retro", Agent: "retro", Role: "retro", What: "an issue labelled se-retro"},
	{Name: "overhaul", Agent: "overhaul", Role: "overhaul", What: "an issue labelled se-overhaul"},
}

// KindNamed answers the kind of that name; an unknown name is a leaf's.
func KindNamed(name string) Kind {
	for _, k := range IssueKinds {
		if k.Name == name {
			return k
		}
	}
	return IssueKinds[0]
}

// KindOf answers the kind of an issue a take took. A gate is never taken:
// it is named apart, as a review (KindNamed("gate")).
func KindOf(i Issue) Kind {
	switch {
	case i.Retro:
		return KindNamed("retro")
	case i.Overhaul:
		return KindNamed("overhaul")
	case i.Parent:
		return KindNamed("parent")
	}
	return KindNamed("leaf")
}

// Type is the agent's type in a session: se:worker.
func (k Kind) Type() string { return Plugin + ":" + k.Agent }

// File is the agent's file, relative to a checkout.
func (k Kind) File() string { return AgentsDir + "/" + k.Agent + ".md" }

// Agents answers every agent of the registry by name, with the role it holds.
func Agents() map[string]string {
	out := map[string]string{}
	for _, k := range IssueKinds {
		out[k.Agent] = k.Role
	}
	return out
}

// RoleNamed answers the kind whose agent owns the skill name: its role, as
// the skill went by before the agent held it, or the agent's own name. A
// skills line naming one names no skill: the take's agent carries it.
func RoleNamed(name string) (Kind, bool) {
	for _, k := range IssueKinds {
		if name == k.Role || name == k.Agent {
			return k, true
		}
	}
	return Kind{}, false
}

// Skills answers the names that are skills, each a role's dropped: an agent
// holds that role, and no skill file does.
func Skills(names []string) []string {
	var out []string
	for _, n := range names {
		if _, ok := RoleNamed(n); !ok {
			out = append(out, n)
		}
	}
	return out
}
