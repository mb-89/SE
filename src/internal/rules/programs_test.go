package rules_test

import "testing"

func TestOnlyTheListedProgramsAreStarted(t *testing.T) {
	t.Parallel()
	found := check(t, "programs", map[string]string{
		"src/a/git.go":                    "package a\n\nimport \"github.com/mb-89/SE/src/internal/io/proc\"\n\nvar _ = proc.Cmd{Name: \"git\", Args: []string{\"status\"}}\n",
		"src/a/gh.go":                     "package a\n\nimport p \"github.com/mb-89/SE/src/internal/io/proc\"\n\nvar _ = p.Cmd{Name: \"gh\"}\nvar _ = p.Cmd{Name: \"/usr/bin/jq\"}\n",
		"src/a/self.go":                   "package a\n\nimport \"github.com/mb-89/SE/src/internal/io/proc\"\n\nfunc f(bin string) proc.Cmd { return proc.Cmd{Name: bin} }\n",
		"src/a/a_test.go":                 "package a_test\n\nimport \"github.com/mb-89/SE/src/internal/io/proc\"\n\nvar _ = proc.Cmd{Name: \"gh\"}\n",
		"src/internal/io/hub/hub.go":      "package hub\n\nimport \"os/exec\"\n\nvar _ = exec.Command(\"gh\", \"api\")\n",
		"src/internal/io/net/net.go":      "package net\n\nimport \"os/exec\"\n\nfunc f(name string) { _ = exec.Command(name) }\n",
		"src/internal/io/kept/kept.go":    "package kept\n\nimport \"os/exec\"\n\nvar _ = exec.Command(\"curl\")\n",
		"src/internal/io/proc/real.go":    "package proc\n\nimport \"os/exec\"\n\nfunc f(c Cmd) { _ = exec.Command(c.Name) }\n",
		"src/internal/io/proc/sh.go":      "package proc\n\nvar _ = Cmd{Name: \"awk\"}\n",
		"src/internal/rules/programs.txt": "# shrinks\nsrc/internal/io/kept/kept.go curl\n",
	})
	want := []string{
		"src/a/gh.go:5: programs: starts gh, which proc.Programs does not list",
		"src/a/gh.go:6: programs: starts /usr/bin/jq, which proc.Programs does not list",
		"src/internal/io/hub/hub.go:5: programs: starts gh, which proc.Programs does not list",
		"src/internal/io/net/net.go:5: programs: starts a program past the proc I/O module",
		"src/internal/io/proc/sh.go:3: programs: starts awk, which proc.Programs does not list",
	}
	same(t, found, want)
}

func TestTheProgramsAllowlistOnlyShrinks(t *testing.T) {
	t.Parallel()
	found := check(t, "programs", map[string]string{
		"src/internal/io/hub/hub.go":      "package hub\n\nimport \"net/http\"\n\nvar _ = http.Get\n",
		"src/internal/rules/programs.txt": "src/internal/io/hub/hub.go gh\n",
	})
	same(t, found, []string{"src/internal/rules/programs.txt:1: programs: the entry matches nothing: src/internal/io/hub/hub.go no longer reaches gh"})
}
