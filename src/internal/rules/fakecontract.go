package rules

import (
	"path"
	"strings"
)

func init() {
	register(Rule{
		Name:    "fake-contract",
		Doc:     "an I/O module's fake.go under src/internal/io has its contract suite, contract_test.go, beside it (spec/io.md)",
		Applies: func(p string) bool { return strings.HasPrefix(p, "src/internal/io/") && path.Base(p) == "fake.go" },
		Check:   fakeContract,
	})
}

func fakeContract(repo *Repo, p string, _ []byte) []Finding {
	if repo.Exists(path.Join(path.Dir(p), "contract_test.go")) {
		return nil
	}
	return []Finding{{Path: p, Line: 1, Rule: "fake-contract", Message: "a fake without its contract suite; add contract_test.go beside it, run against the fake and the real thing (spec/io.md)"}}
}
