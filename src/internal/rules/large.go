package rules

import (
	"fmt"
	"strings"
)

// LargeAllowlist names the files the tree may track though they pass
// MaxFileSize, one path per line. An entry that names no such file, or a
// file within the bound, is refused.
const LargeAllowlist = "src/internal/rules/large.txt"

// MaxFileSize is the most bytes a tracked file holds that LargeAllowlist does
// not name: a source file stays well under it, a build output does not.
const MaxFileSize = 1 << 20

func init() {
	register(Rule{
		Name: "large-file",
		Doc: fmt.Sprintf("the tree tracks no file over %d bytes but those %s names: a build output is ignored, not committed; "+
			"an entry there that names no such file is refused", MaxFileSize, LargeAllowlist),
		Applies: func(string) bool { return true },
		Check:   largeFile,
	})
}

func largeFile(repo *Repo, p string, text []byte) []Finding {
	if p == LargeAllowlist {
		return staleLarge(repo, text)
	}
	if len(text) <= MaxFileSize {
		return nil
	}
	if list, _, _ := repo.Read(LargeAllowlist); strings.Contains("\n"+string(list)+"\n", "\n"+p+"\n") {
		return nil
	}
	return []Finding{{Path: p, Line: 1, Rule: "large-file", Message: fmt.Sprintf(
		"%d bytes, over %d: a build output is git rm --cached and ignored in .gitignore; a file the tree must hold goes in %s",
		len(text), MaxFileSize, LargeAllowlist)}}
}

func staleLarge(repo *Repo, list []byte) []Finding {
	var found []Finding
	for i, line := range strings.Split(string(list), "\n") {
		if line == "" || strings.HasPrefix(line, "#") {
			continue
		}
		if t, ok, err := repo.Read(line); err != nil || !ok || len(t) <= MaxFileSize {
			found = append(found, Finding{
				Path: LargeAllowlist, Line: i + 1, Rule: "large-file",
				Message: "the entry names no file over the bound: " + line + "; remove it",
			})
		}
	}
	return found
}
