package rules

import (
	"path"
	"strings"
)

func init() {
	register(Rule{
		Name:    "repo-path",
		Doc:     "every repository path prose names in its code, and every relative link, exists",
		Applies: isProse,
		Check:   repoPath,
	})
}

func repoPath(repo *Repo, p string, text []byte) []Finding {
	var found []Finding
	for _, c := range codeOf(text) {
		if c.fenced {
			continue
		}
		if q, ok := pathIn(repo, c.text); ok && !repo.Exists(q) {
			found = append(found, Finding{Path: p, Line: c.line, Rule: "repo-path", Message: "no such path: " + q})
		}
	}
	for _, l := range linksOf(text) {
		t := l.target
		if strings.Contains(t, "://") || strings.HasPrefix(t, "#") || strings.HasPrefix(t, "mailto:") {
			continue
		}
		t, _, _ = strings.Cut(t, "#")
		t, _, _ = strings.Cut(t, "?")
		q := path.Join(path.Dir(p), t)
		if strings.HasPrefix(q, "../") || q == ".." || strings.HasPrefix(t, "/") {
			found = append(found, Finding{Path: p, Line: l.line, Rule: "repo-path", Message: "the link leaves the repository: " + l.target})
			continue
		}
		if !repo.Exists(q) {
			found = append(found, Finding{Path: p, Line: l.line, Rule: "repo-path", Message: "the link names no such path: " + l.target})
		}
	}
	return found
}

// pathIn answers the repository path a code span names, if it names one: a
// single token with a slash whose first folder is one at the checkout's top.
// A placeholder, a pattern or a variable in it makes it no path.
func pathIn(repo *Repo, span string) (string, bool) {
	s := strings.TrimPrefix(span, "./")
	s = strings.TrimRight(s, "/:,.")
	if s == "" || strings.ContainsAny(s, " \t<>*?$`{}[]()|\"'…") || strings.Contains(s, "://") || strings.HasPrefix(s, "/") {
		return "", false
	}
	first, _, slash := strings.Cut(s, "/")
	if !slash || !repo.Top(first) {
		return "", false
	}
	return s, true
}
