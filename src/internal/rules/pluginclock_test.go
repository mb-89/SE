package rules_test

import "testing"

func TestPluginCodeReadsTheClockThroughItsModule(t *testing.T) {
	t.Parallel()
	found := check(t, "plugin-clock", map[string]string{
		"src/plugin/hooks/register.tsx": "const a = Date.now()\nconst b = await $.clock.now()\nconst c = new Date(ms).toISOString()\n" +
			"const d = new Date()\nconst e = new Date\nconst f = Date.now\nconst g = new DateTime()\n// Date.now() in a comment\n * new Date() in a doc\n",
		"src/plugin/hooks/helper.js":   "export const t = () => new  Date( )\n",
		"src/plugin/tests/se.test.ts":  "const t = Date.now()\n",
		"src/plugin/hooks/x.test.ts":   "const t = new Date()\n",
		"src/plugin/skills/a/SKILL.md": "Date.now()\n",
		"src/cmd/se/web.ts":            "const t = Date.now()\n",
	})
	same(t, found, []string{
		"src/plugin/hooks/helper.js:1: plugin-clock",
		"src/plugin/hooks/register.tsx:1: plugin-clock",
		"src/plugin/hooks/register.tsx:4: plugin-clock",
		"src/plugin/hooks/register.tsx:5: plugin-clock",
		"src/plugin/hooks/register.tsx:6: plugin-clock",
	})
}
