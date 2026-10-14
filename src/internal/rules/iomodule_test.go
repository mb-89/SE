package rules_test

import (
	"strings"
	"testing"
)

func TestOnlyIOModulesReachTheOutside(t *testing.T) {
	t.Parallel()
	found := check(t, "io-module", map[string]string{
		"src/a/proc.go":                 "package a\n\nimport \"os/exec\"\n\nvar _ = exec.Command\n",
		"src/a/net.go":                  "package a\n\nimport _ \"net/http\"\n",
		"src/a/clock.go":                "package a\n\nimport tm \"time\"\n\nvar now = tm.Now\n\nfunc f() { tm.Sleep(tm.Second); <-tm.After(0) }\n",
		"src/a/disk.go":                 "package a\n\nimport \"os\"\n\nfunc f() { _, _ = os.ReadFile(\"x\"); _ = os.Getenv(\"HOME\") }\n",
		"src/a/pure.go":                 "package a\n\nimport (\n\t\"os\"\n\t\"time\"\n)\n\nvar d = time.Second\nvar e = os.PathSeparator\n",
		"src/a/a_test.go":               "package a_test\n\nimport \"os/exec\"\n\nvar _ = exec.Command\n",
		"src/a/kept.go":                 "package a\n\nimport \"os/exec\"\n\nvar _ = exec.Command\n",
		"src/a/hub.go":                  "package a\n\nimport run \"os/exec\"\n\nvar _ = run.Command(\"gh\", \"api\")\nvar _ = run.Command(\"git\")\n",
		"src/modules/io/github/gh.go":   "package github\n\nimport \"os/exec\"\n\nvar _ = exec.Command(\"gh\")\n",
		"src/modules/io/clock/clock.go": "package clock\n\nimport \"time\"\n\nvar now = time.Now\n",
		"src/a/env.go":                  "package a\n\nimport sys \"os\"\n\nfunc f() { _, _ = sys.LookupEnv(\"A\"); _ = sys.Setenv(\"A\", \"b\")\n\t_ = sys.Environ() }\n",
		"src/modules/io/env/env.go":     "package env\n\nimport \"os\"\n\nvar get = os.Getenv\n",
		"src/modules/io/allowlist.txt":  "# kept until proc lands\nsrc/a/kept.go os/exec\nsrc/a/hub.go os/exec\n",
		"src/a/broken.go":               "not go",
	})
	want := []string{
		"src/a/clock.go:5: io-module: time.Now reaches the outside",
		"src/a/clock.go:7: io-module: time.Sleep reaches the outside",
		"src/a/clock.go:7: io-module: time.After reaches the outside",
		"src/a/disk.go:5: io-module: os.Getenv reaches the outside",
		"src/a/disk.go:5: io-module: os.ReadFile reaches the outside",
		"src/a/env.go:5: io-module: os.LookupEnv reaches the outside",
		"src/a/env.go:5: io-module: os.Setenv reaches the outside",
		"src/a/env.go:6: io-module: os.Environ reaches the outside",
		// Its os/exec is allowed for now; gh is GitHub's I/O module's alone.
		"src/a/hub.go:5: io-module: gh reaches the outside",
		"src/a/net.go:3: io-module: net/http reaches the outside",
		"src/a/proc.go:3: io-module: os/exec reaches the outside",
	}
	same(t, found, want)
}

func TestAWalkOrGlobOutsideTheDiskModuleIsRefused(t *testing.T) {
	t.Parallel()
	found := check(t, "io-module", map[string]string{
		"src/a/walk.go":            "package a\n\nimport \"path/filepath\"\n\nfunc f() { _ = filepath.WalkDir(\".\", nil) }\n",
		"src/a/both.go":            "package a\n\nimport fp \"path/filepath\"\n\nfunc f() { _ = fp.Walk(\".\", nil); _, _ = fp.Glob(\"*\") }\n",
		"src/a/pure.go":            "package a\n\nimport \"path/filepath\"\n\nvar p = filepath.Join(\"a\", \"b\")\n",
		"src/modules/io/disk/d.go": "package disk\n\nimport \"path/filepath\"\n\nfunc f() { _ = filepath.WalkDir(\".\", nil) }\n",
	})
	want := []string{
		"src/a/both.go:5: io-module: path/filepath.Glob reaches the outside",
		"src/a/both.go:5: io-module: path/filepath.Walk reaches the outside",
		"src/a/walk.go:5: io-module: path/filepath.WalkDir reaches the outside",
	}
	same(t, found, want)
}

func TestTheIOAllowlistOnlyShrinks(t *testing.T) {
	t.Parallel()
	found := check(t, "io-module", map[string]string{
		"src/a/kept.go":                "package a\n\nimport \"os/exec\"\n\nvar _ = exec.Command\n",
		"src/a/done.go":                "package a\n\nimport \"time\"\n\nvar d = time.Second\n",
		"src/modules/io/allowlist.txt": "# a comment\n\nsrc/a/kept.go os/exec\nsrc/a/kept.go os/exec\nsrc/a/done.go time.Now\nsrc/a/gone.go os/exec\njust-one-word\n",
	})
	want := []string{
		"src/modules/io/allowlist.txt:4: io-module: the entry is named twice",
		"src/modules/io/allowlist.txt:5: io-module: the entry matches nothing: src/a/done.go no longer reaches time.Now",
		"src/modules/io/allowlist.txt:6: io-module: the entry names no such file: src/a/gone.go",
		"src/modules/io/allowlist.txt:7: io-module: an entry is a Go file and what it reaches",
	}
	same(t, found, want)
}

// same fails unless found holds exactly one finding starting with each of want.
func same(t *testing.T, found, want []string) {
	t.Helper()
	if len(found) != len(want) {
		t.Fatalf("found:\n%s", strings.Join(found, "\n"))
	}
	for _, w := range want {
		hit := false
		for _, f := range found {
			hit = hit || strings.HasPrefix(f, w)
		}
		if !hit {
			t.Errorf("missing %q in:\n%s", w, strings.Join(found, "\n"))
		}
	}
}
