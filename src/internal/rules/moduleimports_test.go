package rules_test

import "testing"

const (
	indexImport = "\t\"github.com/mb-89/SE/src/index\"\n"
	libImport   = "\t\"github.com/mb-89/SE/src/lib/text\"\n"
)

func TestAComputeModuleImportsTheContractTheLibrariesAndThePureStandardLibrary(t *testing.T) {
	t.Parallel()
	found := check(t, "module-imports", map[string]string{
		"src/modules/issues/pull/pull.go": "package pull\n\nimport (\n\t\"sort\"\n\t\"strings\"\n\t\"time\"\n" + indexImport + libImport + ")\n\nvar d = time.Second\n",
		"src/modules/issues/pull/bad.go": "package pull\n\nimport (\n\t\"os\"\n\t\"net/http\"\n\ttm \"time\"\n\t\"gopkg.in/yaml.v3\"\n" +
			"\t\"github.com/mb-89/SE/src/internal/issues\"\n)\n\nvar now = tm.Now\n",
		"src/modules/issues/pull/pull_test.go": "package pull_test\n\nimport \"os\"\n",
		"src/modules/io/disk/disk.go":          "package disk\n\nimport (\n\t\"os\"\n" + indexImport + ")\n\nvar Module = index.Declare(\"io/disk\", \"The disk.\", index.IO())\n",
		"src/modules/io/disk/read.go":          "package disk\n\nimport \"os\"\n\nvar _ = os.ReadFile\n",
		"src/lib/text/text.go":                 "package text\n\nimport \"os/exec\"\n",
		"src/internal/a/a.go":                  "package a\n\nimport \"os\"\n",
		"src/internal/io/clock/owns.yaml":      clockDoor,
	})
	same(t, found, []string{
		"src/lib/text/text.go:3: module-imports: a library imports os/exec",
		"src/modules/issues/pull/bad.go:4: module-imports: a compute module imports os:",
		"src/modules/issues/pull/bad.go:5: module-imports: a compute module imports net/http",
		"src/modules/issues/pull/bad.go:7: module-imports: a compute module imports gopkg.in/yaml.v3",
		"src/modules/issues/pull/bad.go:8: module-imports: a compute module imports github.com/mb-89/SE/src/internal/issues",
		"src/modules/issues/pull/bad.go:11: module-imports: a compute module reads the clock or waits through time.Now",
	})
}
