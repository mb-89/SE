// Package gitfake is the fake behind kern's git door (package git): an
// in-memory git whose working trees are on disk, answering the commands kern
// and SE's Go components run and those their tests build repositories with.
// Nothing of a repository is on disk but its files. The door's contract
// (git/contract_test.go) runs the same cases against it and against real
// git; a command it does not know fails with exit code 129, naming itself,
// so a new caller extends the fake and the contract together.
package gitfake

import (
	"context"
	"crypto/sha1"
	"encoding/hex"
	"errors"
	"fmt"
	"io/fs"
	"os"
	"path"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/mb-89/kern/git"
)

// Fake is a git door backend (git.Backend); one serves any number of
// repositories, from any number of goroutines.
type Fake struct {
	mu      sync.Mutex
	repos   map[string]*repository
	commits map[string]*commit
	calls   [][]string
}

// New answers a fake with no repositories.
func New() *Fake {
	return &Fake{repos: map[string]*repository{}, commits: map[string]*commit{}}
}

// Calls answers the arguments of every command run so far, in order.
func (f *Fake) Calls() [][]string {
	f.mu.Lock()
	defer f.mu.Unlock()
	return append([][]string{}, f.calls...)
}

type repository struct {
	root   string
	head   string            // refs/heads/<branch>
	refs   map[string]string // full ref name -> commit
	sym    map[string]string // full ref name -> the ref it names
	index  map[string]string // tracked path -> content
	config map[string]string
}

type commit struct {
	tree      map[string]string
	parent    string
	message   string
	author    [2]string
	committer [2]string
	when      time.Time
}

// refusal is git's refusal of a command: its exit code and what it says.
type refusal struct {
	code    int
	message string
}

func refuse(code int, format string, args ...any) *refusal {
	return &refusal{code, fmt.Sprintf(format, args...)}
}

// call is one command as the fake reads it.
type call struct {
	dir     string
	options map[string]string // -c key=value, keys lowercased
	env     map[string]string
	args    []string
}

// Run answers c as git would.
func (f *Fake) Run(_ context.Context, c git.Command) (string, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.calls = append(f.calls, append([]string{}, c.Args...))
	dir := c.Dir
	if dir == "" {
		dir, _ = os.Getwd()
	}
	cl := call{dir: dir, options: map[string]string{}, env: map[string]string{}}
	for _, entry := range os.Environ() {
		name, value, _ := strings.Cut(entry, "=")
		cl.env[name] = value
	}
	for _, entry := range c.Env {
		name, value, _ := strings.Cut(entry, "=")
		cl.env[name] = value
	}
	args := c.Args
	for len(args) >= 2 && (args[0] == "-C" || args[0] == "-c") {
		if args[0] == "-C" {
			cl.dir = join(cl.dir, args[1])
		} else {
			key, value, _ := strings.Cut(args[1], "=")
			cl.options[strings.ToLower(key)] = value
		}
		args = args[2:]
	}
	if len(args) == 0 {
		args = []string{"help"}
	}
	cl.args = args[1:]
	commands := map[string]func(call) (string, *refusal){
		"init": f.initRepo, "config": f.config, "add": f.add, "commit": f.commit, "tag": f.tag,
		"update-ref": f.updateRef, "symbolic-ref": f.symbolicRef, "rev-parse": f.revParse,
		"diff": f.diff, "ls-files": f.lsFiles, "for-each-ref": f.forEachRef,
	}
	handler, ok := commands[args[0]]
	if !ok {
		return "", f.fail(c, refuse(129, "fake git: no `%s` (kern/git/gitfake answers only what kern's callers and their tests use)", args[0]))
	}
	out, r := handler(cl)
	if r != nil {
		return "", f.fail(c, r)
	}
	return out, nil
}

func (f *Fake) fail(c git.Command, r *refusal) error {
	return &git.Error{Command: c, Code: r.code, Stderr: r.message + "\n", Err: fmt.Errorf("exit status %d", r.code)}
}

func join(dir, p string) string {
	if filepath.IsAbs(p) {
		return p
	}
	return filepath.Join(dir, p)
}

// canonical answers dir as the fake keys repositories: absolute, its links
// resolved where it exists (a temporary folder on macOS lies behind one).
func canonical(dir string) string {
	if abs, err := filepath.Abs(dir); err == nil {
		dir = abs
	}
	if real, err := filepath.EvalSymlinks(dir); err == nil {
		dir = real
	}
	return filepath.Clean(dir)
}

// find answers the repository dir lies in.
func (f *Fake) find(dir string) (*repository, *refusal) {
	for place := canonical(dir); ; {
		if r, ok := f.repos[place]; ok {
			return r, nil
		}
		parent := filepath.Dir(place)
		if parent == place {
			return nil, refuse(128, "fatal: not a git repository (or any of the parent directories): .git")
		}
		place = parent
	}
}

// rel answers dir's path under the repository's root, slash-separated ("" for the root).
func (r *repository) rel(dir string) string {
	rel, err := filepath.Rel(r.root, canonical(dir))
	if err != nil || rel == "." {
		return ""
	}
	return filepath.ToSlash(rel)
}

// The commands

func (f *Fake) initRepo(c call) (string, *refusal) {
	branch, named := "main", []string{}
	for i := 0; i < len(c.args); i++ {
		switch a := c.args[i]; {
		case a == "-b" && i+1 < len(c.args):
			branch = c.args[i+1]
			i++
		case !strings.HasPrefix(a, "-"):
			named = append(named, a)
		}
	}
	dir := c.dir
	if len(named) > 0 {
		dir = join(dir, named[len(named)-1])
	}
	// No .git on disk: the repository is in memory, and a tool that finds a
	// .git folder (go list's VCS stamp) would run its own git on it.
	if err := os.MkdirAll(dir, 0o755); err != nil {
		return "", refuse(128, "fatal: %v", err)
	}
	root := canonical(dir)
	if _, ok := f.repos[root]; !ok {
		f.repos[root] = &repository{root: root, head: "refs/heads/" + branch, refs: map[string]string{},
			sym: map[string]string{}, index: map[string]string{}, config: map[string]string{}}
	}
	return "", nil
}

// config: `config <key> <value>` sets, `config [--get] <key>` reads (exit 1 for a key not set).
func (f *Fake) config(c call) (string, *refusal) {
	r, bad := f.find(c.dir)
	if bad != nil {
		return "", bad
	}
	var plain []string
	for _, a := range c.args {
		if !strings.HasPrefix(a, "--") {
			plain = append(plain, a)
		}
	}
	switch len(plain) {
	case 1:
		value, ok := r.config[strings.ToLower(plain[0])]
		if !ok {
			return "", refuse(1, "")
		}
		return value + "\n", nil
	case 2:
		r.config[strings.ToLower(plain[0])] = plain[1]
		return "", nil
	}
	return "", refuse(129, "fake git: config takes a key and an optional value")
}

// onDisk answers the working tree's files git sees under the root: without
// .git, nested repositories and the untracked files the root .gitignore ignores.
func (f *Fake) onDisk(r *repository) (map[string]string, *refusal) {
	patterns, bad := ignorePatterns(r.root)
	if bad != nil {
		return nil, bad
	}
	files := map[string]string{}
	err := filepath.WalkDir(r.root, func(p string, d fs.DirEntry, err error) error {
		if err != nil {
			return err
		}
		if p == r.root {
			return nil
		}
		if d.IsDir() {
			if d.Name() == ".git" {
				return filepath.SkipDir
			}
			if _, nested := f.repos[canonical(p)]; nested {
				return filepath.SkipDir
			}
			return nil
		}
		if !d.Type().IsRegular() {
			return nil
		}
		rel, _ := filepath.Rel(r.root, p)
		name := filepath.ToSlash(rel)
		if _, tracked := r.index[name]; !tracked && ignored(name, patterns) {
			return nil
		}
		data, err := os.ReadFile(p)
		if err != nil {
			return err
		}
		files[name] = string(data)
		return nil
	})
	if err != nil {
		return nil, refuse(128, "fatal: %v", err)
	}
	return files, nil
}

// add: `add -A`, `add .` or `add <path>...` stages the working tree's files under them, deletions among them.
func (f *Fake) add(c call) (string, *refusal) {
	r, bad := f.find(c.dir)
	if bad != nil {
		return "", bad
	}
	disk, bad := f.onDisk(r)
	if bad != nil {
		return "", bad
	}
	var specs []string
	for _, a := range c.args {
		switch {
		case a == "-A" || a == "--all":
			specs = append(specs, "")
		case !strings.HasPrefix(a, "-"):
			specs = append(specs, path.Join(r.rel(c.dir), filepath.ToSlash(a)))
		}
	}
	if len(specs) == 0 {
		return "", refuse(128, "Nothing specified, nothing added.")
	}
	for _, spec := range specs {
		spec = strings.TrimPrefix(path.Clean("/"+spec), "/")
		for name := range r.index {
			if within(name, spec) {
				delete(r.index, name)
			}
		}
		for name, data := range disk {
			if within(name, spec) {
				r.index[name] = data
			}
		}
	}
	return "", nil
}

// within says whether name lies at or under spec ("" is the root).
func within(name, spec string) bool {
	return spec == "" || name == spec || strings.HasPrefix(name, spec+"/")
}

// identity answers the author's or committer's name and email: its GIT_<role>_ variables, else -c user.*, else the repository's config.
func identity(c call, r *repository, role string) ([2]string, *refusal) {
	pick := func(key string) string {
		if v := c.env["GIT_"+role+"_"+strings.ToUpper(key)]; v != "" {
			return v
		}
		if v := c.options["user."+key]; v != "" {
			return v
		}
		return r.config["user."+key]
	}
	name, email := pick("name"), pick("email")
	if name == "" || email == "" {
		return [2]string{}, refuse(128, "Author identity unknown\n\n*** Please tell me who you are.\n\nfatal: unable to auto-detect email address")
	}
	return [2]string{name, email}, nil
}

// commit: `commit [-q] [--allow-empty] -m <message>` commits the index on the current branch.
func (f *Fake) commit(c call) (string, *refusal) {
	r, bad := f.find(c.dir)
	if bad != nil {
		return "", bad
	}
	message, empty := "", false
	for i := 0; i < len(c.args); i++ {
		switch c.args[i] {
		case "-m":
			if i+1 < len(c.args) {
				message = c.args[i+1]
				i++
			}
		case "--allow-empty":
			empty = true
		}
	}
	if message == "" {
		return "", refuse(1, "Aborting commit due to empty commit message.")
	}
	parent := r.refs[r.head]
	if parent != "" && !empty && same(f.commits[parent].tree, r.index) {
		return "", refuse(1, "nothing to commit, working tree clean")
	}
	author, bad := identity(c, r, "AUTHOR")
	if bad != nil {
		return "", bad
	}
	committer, bad := identity(c, r, "COMMITTER")
	if bad != nil {
		return "", bad
	}
	when := time.Now()
	if given := c.env["GIT_COMMITTER_DATE"]; given != "" {
		t, err := time.Parse(time.RFC3339, given)
		if err != nil {
			return "", refuse(128, "fake git: GIT_COMMITTER_DATE %q is not RFC 3339", given)
		}
		when = t
	}
	tree := map[string]string{}
	for name, data := range r.index {
		tree[name] = data
	}
	cm := &commit{tree: tree, parent: parent, message: message, author: author, committer: committer, when: when.Truncate(time.Second)}
	sum := sha1.Sum([]byte(fmt.Sprintf("%v|%s|%s|%v|%v|%d|%d", sortedTree(tree), parent, message, author, committer, cm.when.Unix(), len(f.commits))))
	id := hex.EncodeToString(sum[:])
	f.commits[id] = cm
	r.refs[r.head] = id
	return "", nil
}

func same(a, b map[string]string) bool {
	if len(a) != len(b) {
		return false
	}
	for k, v := range a {
		if w, ok := b[k]; !ok || w != v {
			return false
		}
	}
	return true
}

func sortedTree(tree map[string]string) []string {
	var lines []string
	for name, data := range tree {
		lines = append(lines, name+"\x00"+data)
	}
	sort.Strings(lines)
	return lines
}

// resolve answers the commit a revision names: a commit id, HEAD, a ref by
// its full or short name, each with an optional ^{commit}.
func (f *Fake) resolve(r *repository, rev string) (string, bool) {
	rev = strings.TrimSuffix(rev, "^{commit}")
	if _, ok := f.commits[rev]; ok {
		return rev, true
	}
	name := rev
	if rev == "HEAD" {
		name = r.head
	}
	for _, full := range []string{name, "refs/" + name, "refs/tags/" + name, "refs/heads/" + name, "refs/remotes/" + name} {
		if id, ok := r.ref(full); ok {
			return id, true
		}
	}
	return "", false
}

// ref answers the commit a full ref name holds, following a symbolic one.
func (r *repository) ref(name string) (string, bool) {
	for i := 0; i < 5; i++ {
		if target, ok := r.sym[name]; ok {
			name = target
			continue
		}
		id, ok := r.refs[name]
		return id, ok
	}
	return "", false
}

// tag: `tag <name> [<commit>]` makes a lightweight tag.
func (f *Fake) tag(c call) (string, *refusal) {
	r, bad := f.find(c.dir)
	if bad != nil {
		return "", bad
	}
	if len(c.args) == 0 || len(c.args) > 2 {
		return "", refuse(129, "fake git: tag takes a name and an optional commit")
	}
	at := "HEAD"
	if len(c.args) == 2 {
		at = c.args[1]
	}
	id, ok := f.resolve(r, at)
	if !ok {
		return "", refuse(128, "fatal: Failed to resolve '%s' as a valid ref.", at)
	}
	if _, exists := r.refs["refs/tags/"+c.args[0]]; exists {
		return "", refuse(128, "fatal: tag '%s' already exists", c.args[0])
	}
	r.refs["refs/tags/"+c.args[0]] = id
	return "", nil
}

// update-ref: `update-ref <ref> <revision>`.
func (f *Fake) updateRef(c call) (string, *refusal) {
	r, bad := f.find(c.dir)
	if bad != nil {
		return "", bad
	}
	if len(c.args) != 2 {
		return "", refuse(129, "fake git: update-ref takes a ref and a revision")
	}
	id, ok := f.resolve(r, c.args[1])
	if !ok {
		return "", refuse(128, "fatal: %s: not a valid SHA1", c.args[1])
	}
	delete(r.sym, c.args[0])
	r.refs[c.args[0]] = id
	return "", nil
}

// symbolic-ref: `symbolic-ref <ref> <target>`.
func (f *Fake) symbolicRef(c call) (string, *refusal) {
	r, bad := f.find(c.dir)
	if bad != nil {
		return "", bad
	}
	if len(c.args) != 2 {
		return "", refuse(129, "fake git: symbolic-ref takes a ref and its target")
	}
	delete(r.refs, c.args[0])
	r.sym[c.args[0]] = c.args[1]
	return "", nil
}

// rev-parse: `--show-prefix`, or the commit of each revision, `-q --verify` failing quietly for a missing one.
func (f *Fake) revParse(c call) (string, *refusal) {
	r, bad := f.find(c.dir)
	if bad != nil {
		return "", bad
	}
	var out strings.Builder
	quiet := false
	for _, a := range c.args {
		switch a {
		case "--show-prefix":
			if p := r.rel(c.dir); p != "" {
				out.WriteString(p + "/")
			}
			out.WriteString("\n")
		case "-q", "--quiet":
			quiet = true
		case "--verify":
		default:
			id, ok := f.resolve(r, a)
			if !ok {
				if quiet {
					return "", refuse(1, "")
				}
				return "", refuse(128, "fatal: Needed a single revision")
			}
			out.WriteString(id + "\n")
		}
	}
	return out.String(), nil
}

// diff: `diff --name-only [--no-renames] <revision> [--]`, the tracked paths
// whose working tree differs from the revision, from the root, sorted.
func (f *Fake) diff(c call) (string, *refusal) {
	r, bad := f.find(c.dir)
	if bad != nil {
		return "", bad
	}
	var revs []string
	nameOnly := false
	for _, a := range c.args {
		switch {
		case a == "--name-only":
			nameOnly = true
		case a == "--no-renames" || a == "--":
		case strings.HasPrefix(a, "-"):
			return "", refuse(129, "fake git: diff has no %s", a)
		default:
			revs = append(revs, a)
		}
	}
	if !nameOnly || len(revs) != 1 {
		return "", refuse(129, "fake git: diff answers only --name-only against one revision")
	}
	id, ok := f.resolve(r, revs[0])
	if !ok {
		return "", refuse(128, "fatal: bad revision '%s'", revs[0])
	}
	tree := f.commits[id].tree
	worktree := map[string]string{}
	for name := range r.index {
		if data, err := os.ReadFile(filepath.Join(r.root, filepath.FromSlash(name))); err == nil {
			worktree[name] = string(data)
		}
	}
	changed := map[string]bool{}
	for name, data := range tree {
		if w, ok := worktree[name]; !ok || w != data {
			changed[name] = true
		}
	}
	for name := range worktree {
		if _, ok := tree[name]; !ok {
			changed[name] = true
		}
	}
	return lines(changed), nil
}

func lines(set map[string]bool) string {
	var names []string
	for name := range set {
		names = append(names, name)
	}
	sort.Strings(names)
	var out strings.Builder
	for _, name := range names {
		out.WriteString(name + "\n")
	}
	return out.String()
}

// ls-files: `ls-files --others --exclude-standard [--full-name] [-- <path>...]`,
// the files under the folder that git neither tracks nor ignores, sorted.
func (f *Fake) lsFiles(c call) (string, *refusal) {
	r, bad := f.find(c.dir)
	if bad != nil {
		return "", bad
	}
	others, exclude, full := false, false, false
	var specs []string
	for _, a := range c.args {
		switch {
		case a == "--others" || a == "-o":
			others = true
		case a == "--exclude-standard":
			exclude = true
		case a == "--full-name":
			full = true
		case a == "--":
		case strings.HasPrefix(a, "-"):
			return "", refuse(129, "fake git: ls-files has no %s", a)
		default:
			specs = append(specs, a)
		}
	}
	if !others || !exclude {
		return "", refuse(129, "fake git: ls-files answers only --others --exclude-standard")
	}
	disk, bad := f.onDisk(r)
	if bad != nil {
		return "", bad
	}
	prefix := r.rel(c.dir)
	if len(specs) == 0 {
		specs = []string{"."}
	}
	found := map[string]bool{}
	for name := range disk {
		if _, tracked := r.index[name]; tracked {
			continue
		}
		for _, spec := range specs {
			spec = strings.TrimPrefix(path.Clean("/"+path.Join(prefix, filepath.ToSlash(spec))), "/")
			if !within(name, spec) {
				continue
			}
			shown := name
			if !full && prefix != "" {
				shown = strings.TrimPrefix(name, prefix+"/")
			}
			found[shown] = true
		}
	}
	return lines(found), nil
}

// for-each-ref: `for-each-ref [--format=<format>] [<prefix>...]`, the refs
// under the prefixes, sorted by name; the format knows %(refname),
// %(refname:lstrip=<n>), %(objectname), %(committerdate:iso-strict) and
// %xx escapes.
func (f *Fake) forEachRef(c call) (string, *refusal) {
	r, bad := f.find(c.dir)
	if bad != nil {
		return "", bad
	}
	format := "%(objectname) commit\t%(refname)"
	var prefixes []string
	for _, a := range c.args {
		switch {
		case strings.HasPrefix(a, "--format="):
			format = strings.TrimPrefix(a, "--format=")
		case strings.HasPrefix(a, "-"):
			return "", refuse(129, "fake git: for-each-ref has no %s", a)
		default:
			prefixes = append(prefixes, a)
		}
	}
	var names []string
	for name := range r.refs {
		names = append(names, name)
	}
	for name := range r.sym {
		names = append(names, name)
	}
	sort.Strings(names)
	var out strings.Builder
	for _, name := range names {
		if !matches(name, prefixes) {
			continue
		}
		id, ok := r.ref(name)
		if !ok {
			continue
		}
		line, bad := expand(format, name, id, f.commits[id])
		if bad != nil {
			return "", bad
		}
		out.WriteString(line + "\n")
	}
	return out.String(), nil
}

func matches(name string, prefixes []string) bool {
	if len(prefixes) == 0 {
		return true
	}
	for _, p := range prefixes {
		if name == p || strings.HasPrefix(name, strings.TrimSuffix(p, "/")+"/") {
			return true
		}
	}
	return false
}

func expand(format, name, id string, cm *commit) (string, *refusal) {
	var out strings.Builder
	for i := 0; i < len(format); i++ {
		if format[i] != '%' || i+1 >= len(format) {
			out.WriteByte(format[i])
			continue
		}
		if format[i+1] == '(' {
			end := strings.IndexByte(format[i:], ')')
			if end < 0 {
				return "", refuse(128, "fatal: malformed format string %s", format)
			}
			atom := format[i+2 : i+end]
			switch {
			case atom == "refname":
				out.WriteString(name)
			case strings.HasPrefix(atom, "refname:lstrip="):
				n, err := strconv.Atoi(strings.TrimPrefix(atom, "refname:lstrip="))
				if err != nil {
					return "", refuse(128, "fatal: bad %%(%s)", atom)
				}
				parts := strings.Split(name, "/")
				if n > len(parts) {
					n = len(parts)
				}
				out.WriteString(strings.Join(parts[n:], "/"))
			case atom == "objectname":
				out.WriteString(id)
			case atom == "committerdate:iso-strict":
				out.WriteString(cm.when.Format(time.RFC3339))
			default:
				return "", refuse(129, "fake git: for-each-ref knows no %%(%s)", atom)
			}
			i += end
			continue
		}
		if i+2 < len(format) {
			if b, err := hex.DecodeString(format[i+1 : i+3]); err == nil {
				out.Write(b)
				i += 2
				continue
			}
		}
		out.WriteByte(format[i])
	}
	return out.String(), nil
}

// The root .gitignore

// ignorePatterns answers the root .gitignore's patterns (the fake reads no other ignore file).
func ignorePatterns(root string) ([]string, *refusal) {
	data, err := os.ReadFile(filepath.Join(root, ".gitignore"))
	if errors.Is(err, fs.ErrNotExist) {
		return nil, nil
	}
	if err != nil {
		return nil, refuse(128, "fatal: %v", err)
	}
	var patterns []string
	for _, line := range strings.Split(strings.ReplaceAll(string(data), "\r\n", "\n"), "\n") {
		line = strings.TrimSpace(line)
		if line == "" || strings.HasPrefix(line, "#") {
			continue
		}
		if strings.HasPrefix(line, "!") {
			return nil, refuse(129, "fake git: no negated .gitignore patterns")
		}
		patterns = append(patterns, line)
	}
	return patterns, nil
}

// ignored says whether name (slash-separated, from the root) matches one of
// patterns as git matches them: `dir/` only folders, a pattern with an inner
// or leading slash only from the root, any other at any depth; `*` and `?`
// stay within one name.
func ignored(name string, patterns []string) bool {
	parts := strings.Split(name, "/")
	for _, pattern := range patterns {
		folder := strings.HasSuffix(pattern, "/")
		body := strings.TrimSuffix(pattern, "/")
		anchored := strings.Contains(body, "/")
		body = strings.TrimPrefix(body, "/")
		for depth := 1; depth <= len(parts); depth++ {
			if folder && depth == len(parts) {
				continue // the file itself is no folder
			}
			candidate := parts[depth-1]
			if anchored {
				candidate = strings.Join(parts[:depth], "/")
			}
			if ok, _ := path.Match(body, candidate); ok {
				return true
			}
		}
	}
	return false
}
