package rules

import (
	"fmt"
	"go/parser"
	"go/token"
	"path"
	"strconv"
)

func init() {
	register(Rule{
		Name:    "library-users",
		Doc:     "a package under " + libDir + " is imported by at least two modules under " + modulesDir + "; code one module alone uses stays in that module",
		Applies: func(p string) bool { return goSource(p) && under(p, libDir) },
		Check:   libraryUsers,
	})
}

// libraryUsers refuses a library imported by fewer than two modules, once,
// on the first Go file of its package.
func libraryUsers(repo *Repo, p string, _ []byte) []Finding {
	dir := path.Dir(p)
	if files := packageFiles(repo, dir); len(files) == 0 || files[0] != p {
		return nil
	}
	lib := "github.com/mb-89/SE/" + dir
	users := map[string]bool{}
	for _, q := range repo.Paths {
		if !goSource(q) || !under(q, modulesDir) || users[path.Dir(q)] {
			continue
		}
		text, ok, err := repo.Read(q)
		if err != nil || !ok {
			continue
		}
		f, err := parser.ParseFile(token.NewFileSet(), q, text, parser.ImportsOnly)
		if err != nil {
			continue
		}
		for _, im := range f.Imports {
			if ip, _ := strconv.Unquote(im.Path.Value); ip == lib {
				users[path.Dir(q)] = true
			}
		}
	}
	if len(users) >= 2 {
		return nil
	}
	used := "no module"
	for u := range users {
		used = "one module alone, " + u
	}
	return []Finding{{
		Path: p, Line: 1, Rule: "library-users",
		Message: fmt.Sprintf("the library %s is imported by %s; a library has at least two module users: move it into the module that uses it (spec/index.md)", dir, used),
	}}
}
