package rules

import (
	"fmt"
	"path"
	"slices"
	"sort"
	"strings"

	"gopkg.in/yaml.v3"

	"github.com/mb-89/SE/src/internal/index"
	"github.com/mb-89/SE/src/internal/reuse"
)

// The plugin's agents, one file per role, and the one config of the models
// they run. An agent's front matter names its model, which this rule holds to
// ModelsConfig, so the model is set in one place and checked in the other.
const (
	// AgentsDir holds the plugin's agents, one file each.
	AgentsDir = "src/plugin/agents"
	// ModelsConfig sets the model each agent runs.
	ModelsConfig = "spec/models.yaml"
	skillsDir    = "src/plugin/skills"
	// WiringFile holds the reuse config, whose tier lists bound what an agent preloads.
	WiringFile = "src/internal/index/wiring.yaml"
)

func init() {
	register(Rule{
		Name: "agents",
		Doc: "every agent in " + AgentsDir + " is one the registry of kinds names, its front matter's name its file's and its model the one " +
			ModelsConfig + " sets for it, and what its front matter's skills preload is on its tier's list in the reuse config of " + WiringFile +
			"; every agent there has its file, and no skill holds an agent's role",
		Applies: func(p string) bool {
			return p == ModelsConfig || (path.Dir(p) == AgentsDir && path.Ext(p) == ".md")
		},
		Check: agents,
	})
}

func agents(repo *Repo, p string, text []byte) []Finding {
	if p == ModelsConfig {
		return modelsConfig(repo, text)
	}
	name := strings.TrimSuffix(path.Base(p), ".md")
	at := func(msg string, args ...any) Finding {
		return Finding{Path: p, Line: 1, Rule: "agents", Message: fmt.Sprintf(msg, args...)}
	}
	var found []Finding
	role, known := repo.Agents[name]
	if !known {
		found = append(found, at("no kind in the registry of kinds names the agent %s", name))
	}
	front := frontOf(text)
	if front["name"] != name {
		found = append(found, at("its front matter's name is %q, not its file's, %q", front["name"], name))
	}
	models, err := readModels(repo)
	switch {
	case err != nil:
		found = append(found, at("%s cannot be read: %v", ModelsConfig, err))
	case models[name] == "":
		found = append(found, at("%s sets no model for %s", ModelsConfig, name))
	case front["model"] != models[name]:
		found = append(found, at("its model is %q, but %s sets %q", front["model"], ModelsConfig, models[name]))
	}
	if list, ok := front["skills"]; ok {
		found = append(found, preloads(repo, name, list, at)...)
	}
	skills := []string{name}
	if role != "" && role != name {
		skills = append(skills, role)
	}
	for _, skill := range skills {
		if repo.Exists(skillsDir + "/" + skill) {
			found = append(found, at("the skill %s/%s holds the role this agent holds: one role, one file", skillsDir, skill))
		}
	}
	return found
}

// preloads finds each skill the agent name preloads (its front matter's
// skills, as list) that its tier's list in the reuse config does not name,
// so the tier's list stays the one place that says what a tier runs.
func preloads(repo *Repo, name, list string, at func(string, ...any) Finding) []Finding {
	var names []string
	if err := yaml.Unmarshal([]byte(list), &names); err != nil {
		return []Finding{at("its front matter's skills is no list of names: %v", err)}
	}
	text, ok, err := repo.Read(WiringFile)
	if err != nil || !ok {
		return []Finding{at("%s, whose reuse config bounds what it preloads, cannot be read", WiringFile)}
	}
	w, err := index.ParseWiring(text)
	if err != nil {
		return []Finding{at("%s cannot be read: %v", WiringFile, err)}
	}
	cfg, err := reuse.From(w)
	if err != nil {
		return []Finding{at("%s cannot be read: %v", WiringFile, err)}
	}
	tier, isTier := cfg.Tier[name]
	if !isTier {
		return []Finding{at("it preloads skills, but the reuse config of %s has no tier %s", WiringFile, name)}
	}
	var found []Finding
	for _, n := range names {
		if !slices.Contains(tier, n) {
			found = append(found, at("it preloads %s, which the reuse config's %s list in %s does not name: preload only what the tier runs", n, name, WiringFile))
		}
	}
	return found
}

// modelsConfig finds each agent of the registry the config sets no model for,
// and each model it sets for no agent's file.
func modelsConfig(repo *Repo, text []byte) []Finding {
	var models map[string]string
	if err := yaml.Unmarshal(text, &models); err != nil {
		return []Finding{{Path: ModelsConfig, Line: 1, Rule: "agents", Message: err.Error()}}
	}
	var found []Finding
	var names []string
	for n := range repo.Agents {
		names = append(names, n)
	}
	sort.Strings(names)
	for _, n := range names {
		if models[n] == "" {
			found = append(found, Finding{Path: ModelsConfig, Line: 1, Rule: "agents", Message: fmt.Sprintf("it sets no model for the agent %s", n)})
		}
		if !repo.Exists(AgentsDir + "/" + n + ".md") {
			found = append(found, Finding{Path: ModelsConfig, Line: 1, Rule: "agents", Message: fmt.Sprintf("the agent %s has no file %s/%s.md", n, AgentsDir, n)})
		}
	}
	var keys []string
	for k := range models {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	for _, k := range keys {
		if _, ok := repo.Agents[k]; !ok {
			found = append(found, Finding{Path: ModelsConfig, Line: 1, Rule: "agents", Message: fmt.Sprintf("it sets a model for %s, which is no agent of the registry of kinds", k)})
		}
	}
	return found
}

func readModels(repo *Repo) (map[string]string, error) {
	text, ok, err := repo.Read(ModelsConfig)
	if err != nil || !ok {
		return nil, fmt.Errorf("no such file")
	}
	var models map[string]string
	return models, yaml.Unmarshal(text, &models)
}

// frontOf answers the keys of a file's front matter, each with its value as written.
func frontOf(text []byte) map[string]string {
	out := map[string]string{}
	lines := strings.Split(string(text), "\n")
	if len(lines) == 0 || strings.TrimSpace(lines[0]) != "---" {
		return out
	}
	for _, l := range lines[1:] {
		if strings.TrimSpace(l) == "---" {
			break
		}
		if k, v, ok := strings.Cut(l, ":"); ok && !strings.HasPrefix(l, " ") {
			out[strings.TrimSpace(k)] = strings.TrimSpace(v)
		}
	}
	return out
}
