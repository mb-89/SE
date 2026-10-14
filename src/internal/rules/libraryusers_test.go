package rules_test

import "testing"

func TestALibraryNeedsTwoModuleUsers(t *testing.T) {
	t.Parallel()
	lib := map[string]string{
		"src/lib/text/text.go":   "package text\n\nfunc Trim(s string) string { return s }\n",
		"src/lib/text/more.go":   "package text\n",
		"src/lib/text/t_test.go": "package text_test\n",
		"src/lib/lone/lone.go":   "package lone\n",
	}
	user := func(name string) string {
		return "package " + name + "\n\nimport (\n" + libImport + ")\n\nvar _ = text.Trim\n"
	}
	one := map[string]string{"src/modules/issues/pull/pull.go": user("pull"), "src/modules/issues/pull/also.go": user("pull")}
	for p, s := range lib {
		one[p] = s
	}
	same(t, check(t, "library-users", one), []string{
		"src/lib/lone/lone.go:1: library-users: the library src/lib/lone is imported by no module;",
		"src/lib/text/more.go:1: library-users: the library src/lib/text is imported by one module alone, src/modules/issues/pull;",
	})

	two := map[string]string{"src/modules/issues/pull/pull.go": user("pull"), "src/modules/qa/review/review.go": user("review")}
	for p, s := range lib {
		two[p] = s
	}
	same(t, check(t, "library-users", two), []string{
		"src/lib/lone/lone.go:1: library-users: the library src/lib/lone is imported by no module;",
	})
}
