package proc

import (
	"crypto/sha1"
	"encoding/hex"
	"fmt"
	"io"
	"path"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
	"sync"

	"github.com/mb-89/SE/src/internal/io/disk"
)

// Git is a fake git, the program a Fake runs as "git" once InstallGit put it
// there. It keeps every repository it makes in memory, its commits, refs,
// remotes and upstreams, and each checkout's files on a disk, so a test
// writes a file there and git sees it, as the real one would. It does the
// verbs SE and its tests run, each a function of its own, and fails as the
// real git fails at what it does not hold. A shallow clone is a whole one.
type Git struct {
	mu      sync.Mutex
	disk    disk.Disk
	commits map[string]*gitCommit
	places  map[string]*gitPlace
	made    int
}

// gitCommit is one commit: its parents, every file it holds and its message.
// seq orders commits by when they were made, as git's dates would.
type gitCommit struct {
	parents []string
	files   map[string]string
	message string
	seq     int
}

// gitRepo is what a repository's work trees share: its refs and config.
type gitRepo struct {
	refs      map[string]string // full ref name to commit
	upstream  map[string]string // branch to the remote-tracking branch it follows, such as origin/main
	remotes   map[string]string // remote name to URL
	fetchHead string
	bare      bool
}

// gitPlace is a folder git answers in: a bare repository, or one work tree
// of a repository with its HEAD and index.
type gitPlace struct {
	repo      *gitRepo
	dir       string
	head      string            // refs/heads/<branch>, or a commit where HEAD is detached
	index     map[string]string // nil in a bare repository
	merging   string            // MERGE_HEAD while a merge waits
	conflicts map[string]bool
}

// NewGit answers a fake git holding no repository, its work trees on d.
func NewGit(d disk.Disk) *Git {
	return &Git{disk: d, commits: map[string]*gitCommit{}, places: map[string]*gitPlace{}}
}

// InstallGit puts a fake git keeping its work trees on d on the machine, and
// answers it.
func (f *Fake) InstallGit(d disk.Disk) *Git {
	g := NewGit(d)
	f.Install("git", g.Run)
	return g
}

// gitRun is one run of git: the command and the folder it acts in.
type gitRun struct {
	g   *Git
	c   Cmd
	dir string
	p   *gitPlace
}

func (r *gitRun) fail(code int, format string, a ...any) int {
	fmt.Fprintf(r.c.Stderr, format+"\n", a...)
	return code
}

func (r *gitRun) say(format string, a ...any) { fmt.Fprintf(r.c.Stdout, format+"\n", a...) }

// Run runs git as c asks, and answers its exit code: it is the Program.
func (g *Git) Run(c Cmd) int {
	g.mu.Lock()
	defer g.mu.Unlock()
	dir, args := c.Dir, c.Args
	for len(args) > 1 && (args[0] == "-C" || args[0] == "-c") {
		if args[0] == "-C" {
			dir = abs(dir, args[1])
		}
		args = args[2:]
	}
	r := &gitRun{g: g, c: c, dir: dir}
	if len(args) == 0 {
		return r.fail(1, "usage: git <command> [<args>]")
	}
	verb, rest := args[0], args[1:]
	switch verb {
	case "init":
		return r.init(rest)
	case "clone":
		return r.clone(rest)
	}
	if r.p = g.find(dir); r.p == nil {
		return r.fail(128, "fatal: not a git repository (or any of the parent directories): .git")
	}
	verbs := map[string]func([]string) int{
		"add": r.add, "branch": r.branch, "check-ignore": r.checkIgnore, "checkout": r.checkout,
		"commit": r.commit, "config": r.config, "fetch": r.fetch, "log": r.log, "ls-files": r.lsFiles,
		"ls-remote": r.lsRemote, "merge": r.merge, "pull": r.pull, "push": r.push, "remote": r.remote,
		"rev-list": r.revList, "rev-parse": r.revParse, "status": r.status, "worktree": r.worktree,
	}
	if do, ok := verbs[verb]; ok {
		return do(rest)
	}
	return r.fail(1, "git: '%s' is not a git command this fake holds", verb)
}

// abs is p, named from the folder base.
func abs(base, p string) string {
	p = strings.TrimPrefix(p, "file://")
	if filepath.IsAbs(p) || base == "" {
		return filepath.Clean(p)
	}
	return filepath.Join(base, p)
}

// find answers the place dir is in, looking up from dir as git does.
func (g *Git) find(dir string) *gitPlace {
	for d := filepath.Clean(dir); ; d = filepath.Dir(d) {
		if p, ok := g.places[d]; ok {
			// A repository whose folder is gone is gone.
			if there, _ := g.disk.Exists(d); there {
				return p
			}
			delete(g.places, d)
		}
		if filepath.Dir(d) == d {
			return nil
		}
	}
}

// flags splits args into the flags named in takes (a flag that takes a value
// is named with a trailing "="; its value is the next word or follows "=")
// and the rest, in order.
func flags(args []string, takes ...string) (map[string]string, []string, error) {
	got, rest := map[string]string{}, []string{}
	known := map[string]bool{}
	for _, t := range takes {
		known[t] = true
	}
	for i := 0; i < len(args); i++ {
		a := args[i]
		if !strings.HasPrefix(a, "-") || a == "-" {
			rest = append(rest, a)
			continue
		}
		if name, value, ok := strings.Cut(a, "="); ok && known[name+"="] {
			got[name] = value
			continue
		}
		switch {
		case known[a]:
			got[a] = ""
		case known[a+"="] && i+1 < len(args):
			i++
			got[a] = args[i]
		default:
			return nil, nil, fmt.Errorf("error: unknown option `%s'", strings.TrimLeft(a, "-"))
		}
	}
	return got, rest, nil
}

func has(f map[string]string, names ...string) bool {
	for _, n := range names {
		if _, ok := f[n]; ok {
			return true
		}
	}
	return false
}

// commit records a new commit and answers its id.
func (g *Git) commit(parents []string, files map[string]string, message string) string {
	g.made++
	h := sha1.New()
	fmt.Fprintf(h, "%d\x00%s\x00%s", g.made, strings.Join(parents, " "), message)
	id := hex.EncodeToString(h.Sum(nil))
	g.commits[id] = &gitCommit{parents: parents, files: files, message: message, seq: g.made}
	return id
}

// tree answers the files of commit id; none for no commit.
func (g *Git) tree(id string) map[string]string {
	if c, ok := g.commits[id]; ok {
		return c.files
	}
	return map[string]string{}
}

// reachable answers every commit id reaches, id among them.
func (g *Git) reachable(id string) map[string]bool {
	seen := map[string]bool{}
	todo := []string{id}
	for len(todo) > 0 {
		c := todo[len(todo)-1]
		todo = todo[:len(todo)-1]
		if c == "" || seen[c] {
			continue
		}
		seen[c] = true
		todo = append(todo, g.commits[c].parents...)
	}
	return seen
}

// newestFirst orders ids as git log does, the newest first.
func (g *Git) newestFirst(ids map[string]bool) []string {
	out := make([]string, 0, len(ids))
	for id := range ids {
		out = append(out, id)
	}
	sort.Slice(out, func(i, j int) bool { return g.commits[out[i]].seq > g.commits[out[j]].seq })
	return out
}

func (g *Git) isAncestor(a, b string) bool { return a == "" || g.reachable(b)[a] }

// mergeBase answers the best common ancestor of a and b, "" where they share none.
func (g *Git) mergeBase(a, b string) string {
	inA, common := g.reachable(a), map[string]bool{}
	for c := range g.reachable(b) {
		if inA[c] {
			common[c] = true
		}
	}
	if newest := g.newestFirst(common); len(newest) > 0 {
		return newest[0]
	}
	return ""
}

// blob answers the id git gives a file holding content.
func blob(content string) string {
	h := sha1.New()
	fmt.Fprintf(h, "blob %d\x00%s", len(content), content)
	return hex.EncodeToString(h.Sum(nil))
}

func copyFiles(m map[string]string) map[string]string {
	out := make(map[string]string, len(m))
	for k, v := range m {
		out[k] = v
	}
	return out
}

func sameFiles(a, b map[string]string) bool {
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

// headID answers the commit HEAD is at; "" on a branch yet unborn.
func (p *gitPlace) headID() string {
	if strings.HasPrefix(p.head, "refs/") {
		return p.repo.refs[p.head]
	}
	return p.head
}

// branch answers the branch HEAD is on; "" where it is detached.
func (p *gitPlace) branch() string {
	b, _ := strings.CutPrefix(p.head, "refs/heads/")
	if b == p.head {
		return ""
	}
	return b
}

// setHead moves HEAD's branch, or a detached HEAD, to id.
func (p *gitPlace) setHead(id string) {
	if strings.HasPrefix(p.head, "refs/") {
		p.repo.refs[p.head] = id
		return
	}
	p.head = id
}

// fullRef answers the ref name names in repo, as git looks it up.
func fullRef(repo *gitRepo, name string) (string, bool) {
	candidates := []string{"refs/tags/" + name, "refs/heads/" + name, "refs/remotes/" + name}
	if strings.HasPrefix(name, "refs/") {
		candidates = []string{name}
	}
	for _, ref := range candidates {
		if _, ok := repo.refs[ref]; ok {
			return ref, true
		}
	}
	return "", false
}

// resolve answers the commit rev names in p: HEAD, @{upstream}, FETCH_HEAD, a
// ref, a commit or its prefix, each followed by ~N or ^.
func (r *gitRun) resolve(rev string) (string, bool) {
	cut := strings.IndexAny(rev, "~^")
	base, ops := rev, ""
	if cut >= 0 {
		base, ops = rev[:cut], rev[cut:]
	}
	id := ""
	switch base {
	case "HEAD", "@":
		id = r.p.headID()
	case "@{upstream}", "@{u}":
		up, ok := r.p.repo.upstream[r.p.branch()]
		if !ok {
			return "", false
		}
		id = r.p.repo.refs["refs/remotes/"+up]
	case "FETCH_HEAD":
		id = r.p.repo.fetchHead
	default:
		if ref, ok := fullRef(r.p.repo, base); ok {
			id = r.p.repo.refs[ref]
		} else if len(base) >= 4 {
			for c := range r.g.commits {
				if strings.HasPrefix(c, base) {
					id = c
				}
			}
		}
	}
	for id != "" && ops != "" {
		n, step := 1, ops[0]
		ops = ops[1:]
		digits := len(ops) - len(strings.TrimLeft(ops, "0123456789"))
		if digits > 0 {
			n, _ = strconv.Atoi(ops[:digits])
			ops = ops[digits:]
		}
		for ; n > 0 && id != ""; n-- {
			ps := r.g.commits[id].parents
			id = ""
			if len(ps) > 0 {
				id = ps[0]
			}
			if step == '^' {
				break
			}
		}
	}
	return id, id != ""
}

// work answers the files of p's work tree, each by its slash path, without
// .git or another place's folder.
func (r *gitRun) work(p *gitPlace) map[string]string {
	out := map[string]string{}
	paths, _ := r.g.disk.Walk(p.dir)
	for _, full := range paths {
		rel, err := filepath.Rel(p.dir, full)
		if err != nil || rel == ".git" || strings.HasPrefix(rel, ".git"+string(filepath.Separator)) || r.elsewhere(p, full) {
			continue
		}
		if data, err := r.g.disk.ReadFile(full); err == nil {
			out[filepath.ToSlash(rel)] = string(data)
		}
	}
	return out
}

// elsewhere says whether full stands in another place nested in p's folder.
func (r *gitRun) elsewhere(p *gitPlace, full string) bool {
	for dir := filepath.Dir(full); dir != p.dir && dir != filepath.Dir(dir); dir = filepath.Dir(dir) {
		if _, ok := r.g.places[dir]; ok {
			return true
		}
	}
	return false
}

// ignores answers whether p's .gitignore ignores the slash path rel, a folder
// where dir is set. It reads the top .gitignore alone.
func (r *gitRun) ignores(p *gitPlace, rel string, dir bool) bool {
	data, err := r.g.disk.ReadFile(filepath.Join(p.dir, ".gitignore"))
	if err != nil {
		return false
	}
	parts := strings.Split(strings.Trim(rel, "/"), "/")
	for i := range parts {
		isDir := dir || i < len(parts)-1
		if ignoredBy(string(data), strings.Join(parts[:i+1], "/"), parts[i], isDir) {
			return true
		}
	}
	return false
}

// ignoredBy says whether the patterns in gitignore ignore the path whose last
// part is name, the last pattern that matches deciding.
func ignoredBy(gitignore, rel, name string, dir bool) bool {
	ignored := false
	for _, line := range strings.Split(gitignore, "\n") {
		pat := strings.TrimSpace(line)
		if pat == "" || strings.HasPrefix(pat, "#") {
			continue
		}
		negate := strings.HasPrefix(pat, "!")
		pat = strings.TrimPrefix(pat, "!")
		if strings.HasSuffix(pat, "/") {
			if !dir {
				continue
			}
			pat = strings.TrimSuffix(pat, "/")
		}
		subject := name
		if strings.Contains(pat, "/") {
			pat, subject = strings.TrimPrefix(pat, "/"), rel
		}
		if ok, _ := path.Match(pat, subject); ok {
			ignored = !negate
		}
	}
	return ignored
}

// write puts content at the slash path rel of p's work tree.
func (r *gitRun) write(p *gitPlace, rel, content string) {
	full := filepath.Join(p.dir, filepath.FromSlash(rel))
	_ = r.g.disk.MkdirAll(filepath.Dir(full))
	_ = r.g.disk.WriteFile(full, []byte(content))
}

// remove takes the slash path rel out of p's work tree, and each folder it
// leaves empty.
func (r *gitRun) remove(p *gitPlace, rel string) {
	full := filepath.Join(p.dir, filepath.FromSlash(rel))
	_ = r.g.disk.Remove(full)
	for dir := filepath.Dir(full); dir != p.dir && r.g.disk.Remove(dir) == nil; dir = filepath.Dir(dir) {
	}
}

// overwrites names the files of p that hold changes not committed and that
// moving the work tree to files would change.
func (r *gitRun) overwrites(p *gitPlace, files map[string]string) []string {
	from, work := r.g.tree(p.headID()), r.work(p)
	var lost []string
	for _, f := range union(from, files) {
		if from[f] == files[f] {
			continue
		}
		w, inWork := work[f]
		i, inIndex := p.index[f]
		_, inFrom := from[f]
		if inWork != inFrom || w != from[f] || inIndex != inFrom || i != from[f] {
			if inWork || inIndex || inFrom {
				lost = append(lost, f)
			}
		}
	}
	return lost
}

// moveTo brings p's work tree and index from the commit HEAD is at to files,
// touching only the files that differ between the two.
func (r *gitRun) moveTo(p *gitPlace, files map[string]string) {
	from := r.g.tree(p.headID())
	for _, f := range union(from, files) {
		content, keep := files[f]
		if old, was := from[f]; was == keep && old == content {
			continue
		}
		if keep {
			r.write(p, f, content)
			p.index[f] = content
		} else {
			r.remove(p, f)
			delete(p.index, f)
		}
	}
}

func union(ms ...map[string]string) []string {
	seen := map[string]bool{}
	var out []string
	for _, m := range ms {
		for k := range m {
			if !seen[k] {
				seen[k] = true
				out = append(out, k)
			}
		}
	}
	sort.Strings(out)
	return out
}

// switchTo checks out id in p, HEAD named head after it.
func (r *gitRun) switchTo(id, head string) int {
	files := r.g.tree(id)
	if lost := r.overwrites(r.p, files); len(lost) > 0 {
		return r.fail(1, "error: Your local changes to the following files would be overwritten by checkout:\n\t%s", strings.Join(lost, "\n\t"))
	}
	r.moveTo(r.p, files)
	r.p.head = head
	return 0
}

// checkedOut answers the place where branch is checked out, nil where none is.
func (r *gitRun) checkedOut(repo *gitRepo, branch string) *gitPlace {
	for _, p := range r.g.places {
		if p.repo == repo && p.index != nil && p.head == "refs/heads/"+branch {
			return p
		}
	}
	return nil
}

// tracking answers the remote-tracking branch, such as origin/main, that rev names; "" where it names none.
func tracking(repo *gitRepo, rev string) string {
	if ref, ok := fullRef(repo, rev); ok && strings.HasPrefix(ref, "refs/remotes/") {
		return strings.TrimPrefix(ref, "refs/remotes/")
	}
	return ""
}

func (r *gitRun) init(args []string) int {
	f, rest, err := flags(args, "-q", "--quiet", "--bare", "-b=", "--initial-branch=")
	if err != nil {
		return r.fail(129, "%v", err)
	}
	dir := r.dir
	if len(rest) > 0 {
		dir = abs(r.dir, rest[0])
	}
	if _, ok := r.g.places[dir]; ok {
		return 0
	}
	branch := "master"
	for _, b := range []string{f["-b"], f["--initial-branch"]} {
		if b != "" {
			branch = b
		}
	}
	if err := r.g.disk.MkdirAll(dir); err != nil {
		return r.fail(128, "fatal: cannot mkdir %s: %v", dir, err)
	}
	repo := &gitRepo{refs: map[string]string{}, upstream: map[string]string{}, remotes: map[string]string{}, bare: has(f, "--bare")}
	p := &gitPlace{repo: repo, dir: dir, head: "refs/heads/" + branch}
	if !repo.bare {
		p.index = map[string]string{}
	}
	r.g.places[dir] = p
	return 0
}

func (r *gitRun) clone(args []string) int {
	f, rest, err := flags(args, "-q", "--quiet", "--depth=", "--bare", "--no-local")
	if err != nil || len(rest) == 0 {
		return r.fail(129, "usage: git clone [<options>] [--] <repo> [<dir>]")
	}
	url := rest[0]
	src := r.g.places[abs(r.dir, url)]
	if there, _ := r.g.disk.Exists(abs(r.dir, url)); !there {
		src = nil
	}
	if src == nil {
		return r.fail(128, "fatal: repository '%s' does not exist", url)
	}
	dir := abs(r.dir, strings.TrimSuffix(filepath.Base(abs(r.dir, url)), ".git"))
	if len(rest) > 1 {
		dir = abs(r.dir, rest[1])
	}
	if names, err := r.g.disk.List(dir); err == nil && len(names) > 0 {
		return r.fail(128, "fatal: destination path '%s' already exists and is not an empty directory.", rest[len(rest)-1])
	}
	if !strings.Contains(url, "://") {
		url = abs(r.dir, url)
	}
	made := []string{"-q", dir}
	if has(f, "--bare") {
		made = append(made, "--bare")
	}
	if code := r.init(made); code != 0 {
		return code
	}
	p := r.g.places[dir]
	p.repo.remotes["origin"] = url
	for ref, id := range src.repo.refs {
		if b, ok := strings.CutPrefix(ref, "refs/heads/"); ok {
			p.repo.refs["refs/remotes/origin/"+b] = id
		}
	}
	branch := src.branch()
	p.head = src.head
	if p.index != nil {
		p.repo.upstream[branch] = "origin/" + branch
	}
	id, ok := src.repo.refs["refs/heads/"+branch]
	if !ok {
		fmt.Fprintln(r.c.Stderr, "warning: You appear to have cloned an empty repository.")
		return 0
	}
	p.repo.refs["refs/heads/"+branch] = id
	if p.index == nil {
		return 0
	}
	for name, content := range r.g.tree(id) {
		r.write(p, name, content)
		p.index[name] = content
	}
	return 0
}

func (r *gitRun) config(args []string) int {
	if len(args) == 2 && !strings.HasPrefix(args[0], "-") {
		return 0 // who commits is no part of a fake commit
	}
	return r.fail(1, "error: this git sets config, as config <key> <value>, alone")
}

func (r *gitRun) remote(args []string) int {
	switch {
	case len(args) == 2 && args[0] == "get-url":
		url, ok := r.p.repo.remotes[args[1]]
		if !ok {
			return r.fail(2, "error: No such remote '%s'", args[1])
		}
		r.say("%s", url)
	case len(args) == 3 && args[0] == "add":
		if _, ok := r.p.repo.remotes[args[1]]; ok {
			return r.fail(3, "error: remote %s already exists.", args[1])
		}
		r.p.repo.remotes[args[1]] = args[2]
	default:
		return r.fail(129, "usage: git remote get-url <name> | add <name> <url>")
	}
	return 0
}

func (r *gitRun) revParse(args []string) int {
	f, rest, err := flags(args, "--is-inside-work-tree", "--is-bare-repository", "--show-toplevel", "--abbrev-ref", "--short", "--verify", "-q", "--quiet")
	if err != nil {
		return r.fail(129, "%v", err)
	}
	switch {
	case has(f, "--is-inside-work-tree"):
		r.say("%t", r.p.index != nil)
	case has(f, "--is-bare-repository"):
		r.say("%t", r.p.index == nil)
	case has(f, "--show-toplevel"):
		if r.p.index == nil {
			return r.fail(128, "fatal: this operation must be run in a work tree")
		}
		r.say("%s", r.p.dir)
	}
	for _, rev := range rest {
		id, ok := r.resolve(rev)
		switch {
		case !ok && (rev == "@{upstream}" || rev == "@{u}"):
			return r.fail(128, "fatal: no upstream configured for branch '%s'", r.p.branch())
		case !ok:
			return r.fail(128, "fatal: ambiguous argument '%s': unknown revision or path not in the working tree.", rev)
		case has(f, "--abbrev-ref"):
			r.say("%s", r.abbrev(rev))
		case has(f, "--short"):
			r.say("%s", id[:7])
		default:
			r.say("%s", id)
		}
	}
	return 0
}

// abbrev answers rev's short name, as rev-parse --abbrev-ref does.
func (r *gitRun) abbrev(rev string) string {
	switch rev {
	case "HEAD", "@":
		if b := r.p.branch(); b != "" {
			return b
		}
		return "HEAD"
	case "@{upstream}", "@{u}":
		return r.p.repo.upstream[r.p.branch()]
	}
	if ref, ok := fullRef(r.p.repo, rev); ok {
		for _, prefix := range []string{"refs/heads/", "refs/remotes/", "refs/tags/", "refs/"} {
			if short, ok := strings.CutPrefix(ref, prefix); ok {
				return short
			}
		}
	}
	return rev
}

func (r *gitRun) status(args []string) int {
	f, _, err := flags(args, "--porcelain", "--short", "-s", "--untracked-files=", "-uno")
	if err != nil {
		return r.fail(129, "%v", err)
	}
	if r.p.index == nil {
		return r.fail(128, "fatal: this operation must be run in a work tree")
	}
	untracked := f["--untracked-files"] != "no" && !has(f, "-uno")
	head, work := r.g.tree(r.p.headID()), r.work(r.p)
	shown, others := map[string]bool{}, []string{}
	for _, name := range union(head, r.p.index, work) {
		h, inHead := head[name]
		i, inIndex := r.p.index[name]
		w, inWork := work[name]
		if r.p.conflicts[name] {
			r.say("UU %s", name)
			continue
		}
		if !inIndex && !inHead {
			if line := r.untracked(name); untracked && line != "" && !shown[line] {
				shown[line] = true
				others = append(others, line)
			}
			continue
		}
		x, y := ' ', ' '
		switch {
		case inIndex && !inHead:
			x = 'A'
		case !inIndex && inHead:
			x = 'D'
		case i != h:
			x = 'M'
		}
		switch {
		case inIndex && !inWork:
			y = 'D'
		case inIndex && w != i:
			y = 'M'
		}
		if x != ' ' || y != ' ' {
			r.say("%c%c %s", x, y, name)
		}
	}
	for _, line := range others {
		r.say("?? %s", line)
	}
	return 0
}

// untracked answers how status names the untracked file name: by the
// highest folder holding nothing tracked, or itself; "" where it is ignored.
func (r *gitRun) untracked(name string) string {
	if r.ignores(r.p, name, false) {
		return ""
	}
	parts := strings.Split(name, "/")
	for k := 1; k < len(parts); k++ {
		dir := strings.Join(parts[:k], "/") + "/"
		tracked := false
		for f := range r.p.index {
			tracked = tracked || strings.HasPrefix(f, dir)
		}
		if !tracked {
			return dir
		}
	}
	return name
}

func (r *gitRun) lsFiles(args []string) int {
	f, _, err := flags(args, "-z", "--cached", "-c", "--others", "-o", "--exclude-standard", "--unmerged", "-u")
	if err != nil {
		return r.fail(129, "%v", err)
	}
	if r.p.index == nil {
		return r.fail(128, "fatal: this operation must be run in a work tree")
	}
	if has(f, "--unmerged", "-u") {
		var names []string
		for name := range r.p.conflicts {
			names = append(names, name)
		}
		sort.Strings(names)
		ours, theirs := r.g.tree(r.p.headID()), r.g.tree(r.p.merging)
		for _, name := range names {
			for stage, side := range []map[string]string{ours, theirs} {
				if content, ok := side[name]; ok {
					r.say("100644 %s %d\t%s", blob(content), stage+2, name)
				}
			}
		}
		return 0
	}
	end := "\n"
	if has(f, "-z") {
		end = "\x00"
	}
	// The untracked come first, then the tracked, each sorted, as git lists them.
	var others, cached []string
	if has(f, "--others", "-o") {
		for name := range r.work(r.p) {
			if _, tracked := r.p.index[name]; !tracked && (!has(f, "--exclude-standard") || !r.ignores(r.p, name, false)) {
				others = append(others, name)
			}
		}
	}
	if has(f, "--cached", "-c") || !has(f, "--others", "-o") {
		for name := range r.p.index {
			cached = append(cached, name)
		}
	}
	sort.Strings(others)
	sort.Strings(cached)
	for _, name := range append(others, cached...) {
		_, _ = io.WriteString(r.c.Stdout, name+end)
	}
	return 0
}

func (r *gitRun) checkIgnore(args []string) int {
	_, rest, err := flags(args, "-q", "--quiet", "--no-index")
	if err != nil || len(rest) == 0 {
		return r.fail(128, "fatal: no path specified")
	}
	ignored := false
	for _, a := range rest {
		rel, err := filepath.Rel(r.p.dir, abs(r.dir, a))
		if err != nil {
			continue
		}
		if r.ignores(r.p, filepath.ToSlash(rel), strings.HasSuffix(filepath.ToSlash(a), "/")) {
			ignored = true
		}
	}
	if !ignored {
		return 1
	}
	return 0
}

func (r *gitRun) add(args []string) int {
	f, rest, err := flags(args, "-A", "--all", "-q", "--quiet")
	if err != nil {
		return r.fail(129, "%v", err)
	}
	if r.p.index == nil {
		return r.fail(128, "fatal: this operation must be run in a work tree")
	}
	if has(f, "-A", "--all") && len(rest) == 0 {
		rest = []string{r.p.dir}
	}
	work := r.work(r.p)
	for _, spec := range rest {
		rel, err := filepath.Rel(r.p.dir, abs(r.dir, spec))
		if err != nil || strings.HasPrefix(rel, "..") {
			return r.fail(128, "fatal: %s: '%s' is outside repository", spec, spec)
		}
		prefix := filepath.ToSlash(rel)
		matches := func(name string) bool { return prefix == "." || name == prefix || strings.HasPrefix(name, prefix+"/") }
		matched := false
		for name, content := range work {
			_, tracked := r.p.index[name]
			if matches(name) && (tracked || !r.ignores(r.p, name, false)) {
				r.p.index[name], matched = content, true
				delete(r.p.conflicts, name)
			}
		}
		for name := range r.p.index {
			if _, there := work[name]; matches(name) && !there {
				delete(r.p.index, name)
				matched = true
			}
		}
		if !matched && prefix != "." {
			return r.fail(128, "fatal: pathspec '%s' did not match any files", spec)
		}
	}
	return 0
}

func (r *gitRun) commit(args []string) int {
	f, _, err := flags(args, "-q", "--quiet", "--allow-empty", "-m=", "--no-edit", "-a", "--no-verify")
	if err != nil {
		return r.fail(129, "%v", err)
	}
	if r.p.index == nil {
		return r.fail(128, "fatal: this operation must be run in a work tree")
	}
	if len(r.p.conflicts) > 0 {
		return r.fail(128, "error: Committing is not possible because you have unmerged files.")
	}
	if has(f, "-a") {
		work := r.work(r.p)
		for name := range r.p.index {
			if content, ok := work[name]; ok {
				r.p.index[name] = content
			} else {
				delete(r.p.index, name)
			}
		}
	}
	head := r.p.headID()
	if sameFiles(r.p.index, r.g.tree(head)) && !has(f, "--allow-empty") && r.p.merging == "" {
		r.say("nothing to commit, working tree clean")
		return 1
	}
	message, ok := f["-m"]
	if !ok {
		if r.p.merging == "" {
			return r.fail(1, "error: this git commits with -m alone")
		}
		message = "Merge commit '" + r.p.merging + "'"
	}
	var parents []string
	if head != "" {
		parents = append(parents, head)
	}
	if r.p.merging != "" {
		parents = append(parents, r.p.merging)
		r.p.merging = ""
	}
	r.p.setHead(r.g.commit(parents, copyFiles(r.p.index), message))
	return 0
}

func (r *gitRun) checkout(args []string) int {
	f, rest, err := flags(args, "-q", "--quiet", "-b=", "-B=", "--track", "-t", "--no-track", "--detach")
	if err != nil {
		return r.fail(129, "%v", err)
	}
	if r.p.index == nil {
		return r.fail(128, "fatal: this operation must be run in a work tree")
	}
	start := ""
	if len(rest) > 0 {
		start = rest[0]
	}
	name, made := f["-b"], has(f, "-b")
	if has(f, "-B") {
		name, made = f["-B"], true
	}
	if made {
		return r.newBranch(name, start, has(f, "-B"), !has(f, "--no-track"))
	}
	if start == "" {
		return r.fail(1, "error: this git checks out a branch or a commit, named")
	}
	if _, ok := r.p.repo.refs["refs/heads/"+start]; ok && !has(f, "--detach") {
		if other := r.checkedOut(r.p.repo, start); other != nil && other != r.p {
			return r.fail(128, "fatal: '%s' is already used by worktree at '%s'", start, other.dir)
		}
		return r.switchTo(r.p.repo.refs["refs/heads/"+start], "refs/heads/"+start)
	}
	if _, ok := r.p.repo.refs["refs/remotes/origin/"+start]; ok && !has(f, "--detach") {
		return r.newBranch(start, "origin/"+start, false, true)
	}
	id, ok := r.resolve(start)
	if !ok {
		return r.fail(1, "error: pathspec '%s' did not match any file(s) known to git", start)
	}
	return r.switchTo(id, id)
}

// newBranch makes branch name at start (HEAD where it is "") and checks it
// out; again replaces a branch there already. A start that is a
// remote-tracking branch becomes its upstream where track is set.
func (r *gitRun) newBranch(name, start string, again, track bool) int {
	ref := "refs/heads/" + name
	if _, ok := r.p.repo.refs[ref]; ok && !again {
		return r.fail(128, "fatal: a branch named '%s' already exists", name)
	}
	id := r.p.headID()
	if start != "" {
		var ok bool
		if id, ok = r.resolve(start); !ok {
			return r.fail(128, "fatal: '%s' is not a commit and a branch '%s' cannot be created from it", start, name)
		}
	}
	if id == "" {
		r.p.head = ref // a branch yet unborn
		return 0
	}
	if code := r.switchTo(id, ref); code != 0 {
		return code
	}
	r.p.repo.refs[ref] = id
	delete(r.p.repo.upstream, name)
	if up := tracking(r.p.repo, start); up != "" && track {
		r.p.repo.upstream[name] = up
	}
	return 0
}

func (r *gitRun) branch(args []string) int {
	f, rest, err := flags(args, "-q", "--quiet", "--list", "-l", "-D=", "-d=", "--delete=")
	if err != nil {
		return r.fail(129, "%v", err)
	}
	for _, flag := range []string{"-D", "-d", "--delete"} {
		name, ok := f[flag]
		if !ok {
			continue
		}
		if p := r.checkedOut(r.p.repo, name); p != nil {
			return r.fail(1, "error: cannot delete branch '%s' used by worktree at '%s'", name, p.dir)
		}
		if _, ok := r.p.repo.refs["refs/heads/"+name]; !ok {
			return r.fail(1, "error: branch '%s' not found", name)
		}
		delete(r.p.repo.refs, "refs/heads/"+name)
		delete(r.p.repo.upstream, name)
		return 0
	}
	if len(rest) > 0 && !has(f, "--list", "-l") {
		start := "HEAD"
		if len(rest) > 1 {
			start = rest[1]
		}
		id, ok := r.resolve(start)
		if !ok {
			return r.fail(128, "fatal: not a valid object name: '%s'", start)
		}
		if _, ok := r.p.repo.refs["refs/heads/"+rest[0]]; ok {
			return r.fail(128, "fatal: a branch named '%s' already exists", rest[0])
		}
		r.p.repo.refs["refs/heads/"+rest[0]] = id
		return 0
	}
	pattern := "*"
	if len(rest) > 0 {
		pattern = rest[0]
	}
	var names []string
	for ref := range r.p.repo.refs {
		if b, ok := strings.CutPrefix(ref, "refs/heads/"); ok {
			if ok, _ := path.Match(pattern, b); ok {
				names = append(names, b)
			}
		}
	}
	sort.Strings(names)
	for _, b := range names {
		mark := " "
		if p := r.checkedOut(r.p.repo, b); p == r.p || (r.p.index == nil && r.p.head == "refs/heads/"+b) {
			mark = "*"
		}
		r.say("%s %s", mark, b)
	}
	return 0
}

func (r *gitRun) log(args []string) int {
	limit, format, revs := -1, "%H %s", []string{}
	for i := 0; i < len(args); i++ {
		a := args[i]
		switch {
		case a == "-n" && i+1 < len(args):
			i++
			limit, _ = strconv.Atoi(args[i])
		case strings.HasPrefix(a, "--format="), strings.HasPrefix(a, "--pretty=format:"):
			format = a[strings.IndexAny(a, "=")+1:]
			format = strings.TrimPrefix(format, "format:")
		case strings.HasPrefix(a, "-") && len(a) > 1 && strings.Trim(a[1:], "0123456789") == "":
			limit, _ = strconv.Atoi(a[1:])
		case strings.HasPrefix(a, "-"):
			return r.fail(129, "error: unknown option `%s'", a)
		default:
			revs = append(revs, a)
		}
	}
	if len(revs) == 0 {
		revs = []string{"HEAD"}
	}
	ids, code := r.listed(revs)
	if code != 0 {
		return code
	}
	for k, id := range ids {
		if limit >= 0 && k >= limit {
			break
		}
		c := r.g.commits[id]
		subject, _, _ := strings.Cut(c.message, "\n")
		r.say("%s", strings.NewReplacer("%H", id, "%h", id[:7], "%s", subject, "%B", c.message).Replace(format))
	}
	return 0
}

// listed answers the commits revs name, newest first: those each rev reaches,
// less those a ^rev or the left of a..b reaches.
func (r *gitRun) listed(revs []string) ([]string, int) {
	in, out := map[string]bool{}, map[string]bool{}
	reach := func(rev string, into map[string]bool) bool {
		id, ok := r.resolve(rev)
		for c := range r.g.reachable(id) {
			into[c] = true
		}
		return ok
	}
	for _, rev := range revs {
		var ok bool
		switch left, right, dots := strings.Cut(rev, ".."); {
		case dots:
			ok = reach(or(left, "HEAD"), out) && reach(or(right, "HEAD"), in)
		case strings.HasPrefix(rev, "^"):
			ok = reach(rev[1:], out)
		default:
			ok = reach(rev, in)
		}
		if !ok {
			return nil, r.fail(128, "fatal: ambiguous argument '%s': unknown revision or path not in the working tree.", rev)
		}
	}
	for c := range out {
		delete(in, c)
	}
	return r.g.newestFirst(in), 0
}

func or(s, otherwise string) string {
	if s == "" {
		return otherwise
	}
	return s
}

func (r *gitRun) revList(args []string) int {
	f, revs, err := flags(args, "--count", "--merges", "--no-merges")
	if err != nil {
		return r.fail(129, "%v", err)
	}
	ids, code := r.listed(revs)
	if code != 0 {
		return code
	}
	var kept []string
	for _, id := range ids {
		merge := len(r.g.commits[id].parents) > 1
		if (has(f, "--merges") && !merge) || (has(f, "--no-merges") && merge) {
			continue
		}
		kept = append(kept, id)
	}
	if has(f, "--count") {
		r.say("%d", len(kept))
		return 0
	}
	for _, id := range kept {
		r.say("%s", id)
	}
	return 0
}

// remoteOf answers the place the remote name or URL stands for, and its URL.
func (r *gitRun) remoteOf(name string) (*gitPlace, string, bool) {
	url, ok := r.p.repo.remotes[name]
	if !ok {
		url = name
	}
	p := r.g.places[abs(r.dir, url)]
	if there, _ := r.g.disk.Exists(abs(r.dir, url)); !there {
		p = nil
	}
	if p == nil {
		r.fail(128, "fatal: '%s' does not appear to be a git repository\nfatal: Could not read from remote repository.", url)
	}
	return p, url, p != nil
}

// remoteRef answers the ref of the remote that name names on it.
func remoteRef(remote *gitRepo, name string) (string, bool) {
	if strings.HasPrefix(name, "refs/") {
		_, ok := remote.refs[name]
		return name, ok
	}
	for _, ref := range []string{"refs/heads/" + name, "refs/tags/" + name} {
		if _, ok := remote.refs[ref]; ok {
			return ref, true
		}
	}
	return "refs/heads/" + name, false
}

func (r *gitRun) fetch(args []string) int {
	_, rest, err := flags(args, "-q", "--quiet", "--prune", "-p", "--no-tags", "--depth=")
	if err != nil {
		return r.fail(129, "%v", err)
	}
	if len(rest) == 0 {
		rest = []string{"origin"}
	}
	name, specs := rest[0], rest[1:]
	remote, _, ok := r.remoteOf(name)
	if !ok {
		return 128
	}
	_, named := r.p.repo.remotes[name]
	if len(specs) == 0 && named {
		for ref, id := range remote.repo.refs {
			if b, ok := strings.CutPrefix(ref, "refs/heads/"); ok {
				r.p.repo.refs["refs/remotes/"+name+"/"+b] = id
			}
		}
		return 0
	}
	code := 0
	for _, spec := range specs {
		force := strings.HasPrefix(spec, "+")
		src, dst, _ := strings.Cut(strings.TrimPrefix(spec, "+"), ":")
		ref, ok := remoteRef(remote.repo, src)
		if !ok {
			return r.fail(128, "fatal: couldn't find remote ref %s", src)
		}
		id := remote.repo.refs[ref]
		r.p.repo.fetchHead = id
		if b, ok := strings.CutPrefix(ref, "refs/heads/"); ok && named && dst == "" {
			r.p.repo.refs["refs/remotes/"+name+"/"+b] = id
		}
		if dst == "" {
			continue
		}
		if !strings.HasPrefix(dst, "refs/") {
			dst = "refs/heads/" + dst
		}
		if p := r.checkedOut(r.p.repo, strings.TrimPrefix(dst, "refs/heads/")); p != nil && strings.HasPrefix(dst, "refs/heads/") {
			return r.fail(128, "fatal: refusing to fetch into branch '%s' checked out at '%s'", dst, p.dir)
		}
		old, there := r.p.repo.refs[dst]
		if there && !force && !r.g.isAncestor(old, id) {
			fmt.Fprintf(r.c.Stderr, " ! [rejected]        %s -> %s  (non-fast-forward)\n", src, dst)
			code = 1
			continue
		}
		r.p.repo.refs[dst] = id
	}
	return code
}

func (r *gitRun) pull(args []string) int {
	f, rest, err := flags(args, "-q", "--quiet", "--ff-only", "--no-rebase")
	if err != nil {
		return r.fail(129, "%v", err)
	}
	if r.p.index == nil {
		return r.fail(128, "fatal: this operation must be run in a work tree")
	}
	if len(rest) < 2 {
		up, ok := r.p.repo.upstream[r.p.branch()]
		if !ok {
			return r.fail(1, "There is no tracking information for the current branch.")
		}
		remote, branch, _ := strings.Cut(up, "/")
		rest = []string{remote, branch}
	}
	if code := r.fetch(rest[:2]); code != 0 {
		return code
	}
	id, head := r.p.repo.fetchHead, r.p.headID()
	switch {
	case r.g.isAncestor(id, head) && head != "":
		r.say("Already up to date.")
		return 0
	case r.g.isAncestor(head, id):
		if code := r.switchTo(id, r.p.head); code != 0 {
			return code
		}
		r.p.setHead(id)
		return 0
	case has(f, "--ff-only"):
		return r.fail(128, "fatal: Not possible to fast-forward, aborting.")
	}
	return r.merge([]string{"--no-edit", "FETCH_HEAD"})
}

func (r *gitRun) merge(args []string) int {
	f, rest, err := flags(args, "-q", "--quiet", "--no-edit", "--no-ff", "--ff-only", "--no-commit", "-m=", "--abort")
	if err != nil {
		return r.fail(129, "%v", err)
	}
	if r.p.index == nil {
		return r.fail(128, "fatal: this operation must be run in a work tree")
	}
	if has(f, "--abort") {
		if r.p.merging == "" {
			return r.fail(128, "fatal: There is no merge to abort (MERGE_HEAD missing).")
		}
		head := r.g.tree(r.p.headID())
		for _, name := range union(head, r.p.index) {
			if content, ok := head[name]; ok {
				r.write(r.p, name, content)
			} else {
				r.remove(r.p, name)
			}
		}
		r.p.index, r.p.merging, r.p.conflicts = copyFiles(head), "", nil
		return 0
	}
	if r.p.merging != "" {
		return r.fail(128, "fatal: You have not concluded your merge (MERGE_HEAD exists).")
	}
	if len(rest) != 1 {
		return r.fail(129, "error: this git merges one commit")
	}
	theirs, ok := r.resolve(rest[0])
	if !ok {
		return r.fail(1, "merge: %s - not something we can merge", rest[0])
	}
	ours := r.p.headID()
	switch {
	case ours != "" && r.g.isAncestor(theirs, ours):
		if !has(f, "-q", "--quiet") {
			r.say("Already up to date.")
		}
		return 0
	case r.g.isAncestor(ours, theirs) && !has(f, "--no-ff"):
		if code := r.switchTo(theirs, r.p.head); code != 0 {
			return code
		}
		r.p.setHead(theirs)
		return 0
	case has(f, "--ff-only"):
		return r.fail(128, "fatal: Not possible to fast-forward, aborting.")
	}
	base := r.g.mergeBase(ours, theirs)
	if base == "" {
		return r.fail(128, "fatal: refusing to merge unrelated histories")
	}
	merged, conflicts := threeWay(r.g.tree(base), r.g.tree(ours), r.g.tree(theirs), rest[0])
	if lost := r.overwrites(r.p, merged); len(lost) > 0 {
		return r.fail(2, "error: Your local changes to the following files would be overwritten by merge:\n\t%s", strings.Join(lost, "\n\t"))
	}
	r.moveTo(r.p, merged)
	if len(conflicts) > 0 {
		ourTree := r.g.tree(ours)
		r.p.merging, r.p.conflicts = theirs, map[string]bool{}
		for _, name := range conflicts {
			r.p.conflicts[name] = true
			if content, ok := ourTree[name]; ok {
				r.p.index[name] = content
			} else {
				delete(r.p.index, name)
			}
			r.say("CONFLICT (content): Merge conflict in %s", name)
		}
		r.say("Automatic merge failed; fix conflicts and then commit the result.")
		return 1
	}
	if has(f, "--no-commit") {
		// The merge waits for its commit, as after a conflict.
		r.p.merging = theirs
		return 0
	}
	message := or(f["-m"], "Merge branch '"+r.abbrev(rest[0])+"'")
	r.p.setHead(r.g.commit([]string{ours, theirs}, copyFiles(merged), message))
	return 0
}

// threeWay merges theirs into ours from base, file by file: a file only one
// side changed takes that side; one both changed apart conflicts, and is
// written with both sides marked.
func threeWay(base, ours, theirs map[string]string, name string) (map[string]string, []string) {
	merged, conflicts := map[string]string{}, []string{}
	for _, f := range union(base, ours, theirs) {
		b, inB := base[f]
		o, inO := ours[f]
		t, inT := theirs[f]
		switch {
		case inO == inT && o == t, inT == inB && t == b:
			if inO {
				merged[f] = o
			}
		case inO == inB && o == b:
			if inT {
				merged[f] = t
			}
		default:
			conflicts = append(conflicts, f)
			merged[f] = "<<<<<<< HEAD\n" + o + "=======\n" + t + ">>>>>>> " + name + "\n"
		}
	}
	return merged, conflicts
}

func (r *gitRun) lsRemote(args []string) int {
	f, rest, err := flags(args, "--exit-code", "-q", "--quiet", "--heads")
	if err != nil {
		return r.fail(129, "%v", err)
	}
	if len(rest) == 0 {
		rest = []string{"origin"}
	}
	remote, _, ok := r.remoteOf(rest[0])
	if !ok {
		return 128
	}
	var refs []string
	for ref := range remote.repo.refs {
		match := len(rest) == 1
		for _, pat := range rest[1:] {
			match = match || ref == pat || strings.HasSuffix(ref, "/"+pat)
		}
		if match && (!has(f, "--heads") || strings.HasPrefix(ref, "refs/heads/")) {
			refs = append(refs, ref)
		}
	}
	sort.Strings(refs)
	for _, ref := range refs {
		r.say("%s\t%s", remote.repo.refs[ref], ref)
	}
	if len(refs) == 0 && has(f, "--exit-code") {
		return 2
	}
	return 0
}

// pushed is one ref a push asked for: what it says of it, in porcelain.
type pushed struct{ flag, from, to, summary string }

func (r *gitRun) push(args []string) int {
	f, rest, err := flags(args, "-q", "--quiet", "--porcelain", "-u", "--set-upstream", "-f", "--force", "--delete", "-d", "--force-with-lease=", "--no-verify")
	if err != nil {
		return r.fail(129, "%v", err)
	}
	if len(rest) == 0 {
		rest = []string{"origin"}
	}
	name, specs := rest[0], rest[1:]
	remote, url, ok := r.remoteOf(name)
	if !ok {
		return 128
	}
	if len(specs) == 0 {
		if r.p.branch() == "" {
			return r.fail(128, "fatal: You are not currently on a branch.")
		}
		specs = []string{r.p.branch()}
	}
	_, named := r.p.repo.remotes[name]
	lease, leased := f["--force-with-lease"]
	leaseRef, expect, _ := strings.Cut(lease, ":")
	var said []pushed
	failed := false
	for _, spec := range specs {
		if has(f, "--delete", "-d") {
			ref, there := remoteRef(remote.repo, spec)
			if !there {
				fmt.Fprintf(r.c.Stderr, "error: unable to delete '%s': remote ref does not exist\n", spec)
				failed = true
				continue
			}
			delete(remote.repo.refs, ref)
			if b, ok := strings.CutPrefix(ref, "refs/heads/"); ok && named {
				delete(r.p.repo.refs, "refs/remotes/"+name+"/"+b)
			}
			said = append(said, pushed{"-", "", ref, "[deleted]"})
			continue
		}
		force := strings.HasPrefix(spec, "+") || has(f, "-f", "--force")
		src, dst, colon := strings.Cut(strings.TrimPrefix(spec, "+"), ":")
		if !colon {
			dst = src
		}
		id, ok := r.resolve(src)
		if !ok {
			fmt.Fprintf(r.c.Stderr, "error: src refspec %s does not match any\n", src)
			failed = true
			continue
		}
		from := src
		if ref, ok := fullRef(r.p.repo, src); ok {
			from = ref
		} else if src == "HEAD" && r.p.branch() != "" {
			from = "refs/heads/" + r.p.branch()
		}
		if dst == "HEAD" {
			dst = r.p.branch()
		}
		to, _ := remoteRef(remote.repo, dst)
		if strings.HasPrefix(dst, "refs/") {
			to = dst
		}
		p := pushed{from: from, to: to}
		old, there := remote.repo.refs[to]
		forced := false
		switch {
		case there && old == id:
			p.flag, p.summary = "=", "[up to date]"
		case leased && (leaseRef == to || "refs/heads/"+leaseRef == to):
			if old != expect {
				p.flag, p.summary = "!", "[rejected] (stale info)"
			}
			forced = true
		case there && !force && !r.g.isAncestor(old, id):
			p.flag, p.summary = "!", "[rejected] (non-fast-forward)"
		case there && force:
			forced = true
		}
		if p.flag == "" {
			if c := r.checkedOut(remote.repo, strings.TrimPrefix(to, "refs/heads/")); c != nil && strings.HasPrefix(to, "refs/heads/") {
				p.flag, p.summary = "!", "[remote rejected] (branch is currently checked out)"
			}
		}
		if p.flag == "!" {
			failed = true
			said = append(said, p)
			continue
		}
		if p.flag == "" {
			switch {
			case !there:
				p.flag, p.summary = "*", "[new branch]"
			case forced && !r.g.isAncestor(old, id):
				p.flag, p.summary = "+", old[:7]+"..."+id[:7]+" (forced update)"
			default:
				p.flag, p.summary = " ", old[:7]+".."+id[:7]
			}
			remote.repo.refs[to] = id
		}
		if b, ok := strings.CutPrefix(to, "refs/heads/"); ok && named {
			r.p.repo.refs["refs/remotes/"+name+"/"+b] = id
			if local := strings.TrimPrefix(from, "refs/heads/"); has(f, "-u", "--set-upstream") && local != from {
				r.p.repo.upstream[local] = name + "/" + b
			}
		}
		said = append(said, p)
	}
	if has(f, "--porcelain") {
		r.say("To %s", url)
		for _, p := range said {
			r.say("%s\t%s:%s\t%s", p.flag, p.from, p.to, p.summary)
		}
		r.say("Done")
	} else if !has(f, "-q", "--quiet") || failed {
		fmt.Fprintf(r.c.Stderr, "To %s\n", url)
		for _, p := range said {
			fmt.Fprintf(r.c.Stderr, " %s %s -> %s %s\n", p.flag, p.from, p.to, p.summary)
		}
	}
	if failed {
		return r.fail(1, "error: failed to push some refs to '%s'", url)
	}
	return 0
}

func (r *gitRun) worktree(args []string) int {
	if len(args) > 0 && args[0] == "remove" {
		return r.worktreeRemove(args[1:])
	}
	if len(args) == 0 || args[0] != "add" {
		return r.fail(129, "usage: git worktree add [--track] [-b <branch>] [--detach] <path> [<commit-ish>]")
	}
	f, rest, err := flags(args[1:], "-q", "--quiet", "--track", "--no-track", "-b=", "--detach")
	if err != nil || len(rest) == 0 {
		return r.fail(129, "usage: git worktree add [--track] [-b <branch>] [--detach] <path> [<commit-ish>]")
	}
	dir := abs(r.dir, rest[0])
	if names, err := r.g.disk.List(dir); err == nil && len(names) > 0 {
		return r.fail(128, "fatal: '%s' already exists", rest[0])
	}
	start := "HEAD"
	if len(rest) > 1 {
		start = rest[1]
	}
	id, ok := r.resolve(start)
	if !ok {
		return r.fail(128, "fatal: invalid reference: %s", start)
	}
	head := id
	switch name := f["-b"]; {
	case has(f, "-b"):
		if _, ok := r.p.repo.refs["refs/heads/"+name]; ok {
			return r.fail(128, "fatal: a branch named '%s' already exists", name)
		}
		r.p.repo.refs["refs/heads/"+name] = id
		if up := tracking(r.p.repo, start); up != "" && !has(f, "--no-track") {
			r.p.repo.upstream[name] = up
		}
		head = "refs/heads/" + name
	case !has(f, "--detach"):
		if _, ok := r.p.repo.refs["refs/heads/"+start]; ok {
			if other := r.checkedOut(r.p.repo, start); other != nil {
				return r.fail(128, "fatal: '%s' is already used by worktree at '%s'", start, other.dir)
			}
			head = "refs/heads/" + start
		}
	}
	if err := r.g.disk.MkdirAll(dir); err != nil {
		return r.fail(128, "fatal: could not create directory of '%s'", rest[0])
	}
	p := &gitPlace{repo: r.p.repo, dir: dir, head: head, index: map[string]string{}}
	r.g.places[dir] = p
	for name, content := range r.g.tree(id) {
		r.write(p, name, content)
		p.index[name] = content
	}
	return 0
}

// worktreeRemove takes a work tree of the repository away, its folder with
// it; one with changes not committed only with --force.
func (r *gitRun) worktreeRemove(args []string) int {
	f, rest, err := flags(args, "-f", "--force")
	if err != nil || len(rest) != 1 {
		return r.fail(129, "usage: git worktree remove [--force] <worktree>")
	}
	dir := abs(r.dir, rest[0])
	p, ok := r.g.places[dir]
	if !ok || p.repo != r.p.repo || p.index == nil {
		return r.fail(128, "fatal: '%s' is not a working tree", rest[0])
	}
	if !has(f, "-f", "--force") && (p.merging != "" || !sameFiles(r.work(p), r.g.tree(p.headID())) || !sameFiles(p.index, r.g.tree(p.headID()))) {
		return r.fail(128, "fatal: '%s' contains modified or untracked files, use --force to delete it", rest[0])
	}
	delete(r.g.places, dir)
	if err := r.g.disk.RemoveAll(dir); err != nil {
		return r.fail(128, "fatal: failed to delete '%s': %v", rest[0], err)
	}
	return 0
}
