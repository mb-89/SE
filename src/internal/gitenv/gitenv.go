// Package gitenv keeps a test's git commands in the repository they name. A
// pre-push hook runs in git's environment, and from a worktree that holds
// GIT_DIR: a test that runs git in a temp folder would act on the repository
// being pushed instead.
package gitenv

import "os"

// Vars are git's repository variables: each points git at a repository other
// than the one its working folder is in.
var Vars = []string{
	"GIT_DIR",
	"GIT_WORK_TREE",
	"GIT_INDEX_FILE",
	"GIT_PREFIX",
	"GIT_COMMON_DIR",
	"GIT_OBJECT_DIRECTORY",
	"GIT_ALTERNATE_OBJECT_DIRECTORIES",
}

// Clear unsets Vars in this process, so every git it runs, and every process
// those start, finds its repository from its working folder. A package whose
// tests run git calls it in TestMain.
func Clear() {
	for _, v := range Vars {
		_ = os.Unsetenv(v) // fails only on a name with "=" or NUL, which Vars hold none of
	}
}
