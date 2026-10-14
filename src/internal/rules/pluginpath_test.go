package rules_test

import "testing"

func TestAPluginPathNamesAFileOfTheCheckout(t *testing.T) {
	t.Parallel()
	gone := "src/plugin/skills/work/SKILL.md"
	found := check(t, "plugin-path", map[string]string{
		"src/plugin/skills/briefing/SKILL.md": "# B\n\nRead src/plugin/agents/worker.md, then src/plugin/skills/.\n",
		"src/plugin/agents/worker.md":         "# W\n\nNot src/plugin/agents/gone.md, but src/plugin/agents/<name>.md.\n",
		"spec/models.yaml":                    "# src/plugin/agents/retro.md\n",
		"src/a/a.go": "package a\n\n// " + gone + " in a comment is history.\n" +
			"var a = \"" + gone + "\"\nvar b = fmt.Sprintf(\"src/plugin/skills/%s/SKILL.md\", n)\n" +
			"var c = `x\nsrc/plugin/agents/worker.md\nsrc/plugin/agents/old.md`\n",
		"src/a/a_test.go":     "package a\n\nvar a = \"" + gone + "\"\n",
		"src/a/testdata/x.go": "package x\n\nvar a = \"" + gone + "\"\n",
		"README.md":           gone + " is repo-path's to read, not this rule's.\n",
	})
	same(t, found, []string{
		"src/plugin/agents/worker.md:3: plugin-path: no such file: src/plugin/agents/gone.md",
		"spec/models.yaml:1: plugin-path: no such file: src/plugin/agents/retro.md",
		"src/a/a.go:4: plugin-path: no such file: " + gone,
		"src/a/a.go:8: plugin-path: no such file: src/plugin/agents/old.md",
	})
}
