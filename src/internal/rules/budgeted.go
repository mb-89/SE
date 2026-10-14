package rules

import (
	"bytes"
	"fmt"
	"regexp"
	"sort"

	"gopkg.in/yaml.v3"

	"github.com/mb-89/SE/src/internal/battery"
)

// HooksFile is the plugin's hooks, each timing itself through took with its name.
const HooksFile = "src/plugin/hooks/register.tsx"

// hookName finds each hook register.tsx times: took($, '<name>', …).
var hookName = regexp.MustCompile(`took\(\$, '([^']+)'`)

func init() {
	register(Rule{
		Name:    "budgeted",
		Doc:     "every se command and plugin hook has a class in " + battery.BudgetsFile + ", and every class it names exists",
		Applies: func(p string) bool { return p == battery.BudgetsFile || p == HooksFile },
		Check:   budgeted,
	})
}

func budgeted(repo *Repo, p string, text []byte) []Finding {
	if p == HooksFile {
		return hooksBudgeted(repo, text)
	}
	var doc yaml.Node
	var b battery.Budgets
	if err := yaml.Unmarshal(text, &doc); err != nil {
		return []Finding{{Path: p, Line: 1, Rule: "budgeted", Message: err.Error()}}
	}
	if err := doc.Decode(&b); err != nil {
		return []Finding{{Path: p, Line: 1, Rule: "budgeted", Message: err.Error()}}
	}
	var found []Finding
	at := func(section, key string) int { return lineOf(&doc, section, key) }
	for _, section := range []struct {
		name  string
		names map[string]string
	}{{"command_classes", b.CommandClasses}, {"hook_classes", b.HookClasses}} {
		for _, name := range sortedKeys(section.names) {
			if class := section.names[name]; !hasKey(b.Classes, class) {
				found = append(found, Finding{
					Path: p, Line: at(section.name, name), Rule: "budgeted",
					Message: fmt.Sprintf("%s names the class %q, which classes does not hold", name, class),
				})
			}
		}
	}
	if repo.Commands == nil {
		return found
	}
	for _, name := range sortedKeys(repo.Commands) {
		if _, ok := b.CommandClasses[name]; !ok {
			found = append(found, Finding{
				Path: p, Line: at("command_classes", ""), Rule: "budgeted",
				Message: fmt.Sprintf("the se command %q has no class under command_classes", name),
			})
		}
	}
	for _, name := range sortedKeys(b.CommandClasses) {
		if _, ok := repo.Commands[name]; !ok {
			found = append(found, Finding{
				Path: p, Line: at("command_classes", name), Rule: "budgeted",
				Message: fmt.Sprintf("%q is no se command", name),
			})
		}
	}
	return found
}

// hooksBudgeted checks each hook the plugin times against the hook_classes of budgets.yaml.
func hooksBudgeted(repo *Repo, text []byte) []Finding {
	data, ok, err := repo.Read(battery.BudgetsFile)
	if err != nil || !ok {
		return []Finding{{Path: HooksFile, Line: 1, Rule: "budgeted", Message: battery.BudgetsFile + " is missing"}}
	}
	var b battery.Budgets
	if err := yaml.Unmarshal(data, &b); err != nil {
		return nil // the check of budgets.yaml itself names this
	}
	var found []Finding
	for i, line := range bytes.Split(text, []byte("\n")) {
		for _, m := range hookName.FindAllSubmatch(line, -1) {
			if _, ok := b.HookClasses[string(m[1])]; !ok {
				found = append(found, Finding{
					Path: HooksFile, Line: i + 1, Rule: "budgeted",
					Message: fmt.Sprintf("the hook %q has no class under hook_classes in %s", m[1], battery.BudgetsFile),
				})
			}
		}
	}
	return found
}

// lineOf answers the line of key under the top-level section of doc; with
// key "", or where key is not there, the section's own line; 1 where neither is.
func lineOf(doc *yaml.Node, section, key string) int {
	if len(doc.Content) == 0 {
		return 1
	}
	top := doc.Content[0]
	for i := 0; i+1 < len(top.Content); i += 2 {
		if top.Content[i].Value != section {
			continue
		}
		body := top.Content[i+1]
		for j := 0; key != "" && j+1 < len(body.Content); j += 2 {
			if body.Content[j].Value == key {
				return body.Content[j].Line
			}
		}
		return top.Content[i].Line
	}
	return 1
}

func hasKey[V any](m map[string]V, k string) bool {
	_, ok := m[k]
	return ok
}

func sortedKeys[V any](m map[string]V) []string {
	keys := make([]string, 0, len(m))
	for k := range m {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	return keys
}
