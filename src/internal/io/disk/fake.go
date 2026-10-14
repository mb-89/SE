package disk

import (
	"errors"
	"fmt"
	"io"
	"io/fs"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"sync"
	"syscall"
)

// Fake is a filesystem held in memory that behaves as the real one does,
// errors included: a file's folder must exist before it is written, a path
// that names nothing fails with fs.ErrNotExist, a folder that holds anything
// is not removed, and a held lock is refused. It starts empty but for the
// root and the temporary folder; a relative path stands under the root.
type Fake struct {
	mu    sync.Mutex
	files map[string]*node
	dirs  map[string]bool
	locks map[string]bool
	temp  string
	seq   int
}

// node is one file's content; an open file keeps writing to it after a rename.
type node struct{ data []byte }

// The fake fails with the errors the real disk fails with, so their text is
// the same too: syscall.ENOENT is fs.ErrNotExist.
var (
	errNotExist = syscall.ENOENT
	errIsDir    = syscall.EISDIR
	errNotDir   = syscall.ENOTDIR
	errNotEmpty = syscall.ENOTEMPTY
)

// NewFake answers an empty fake disk.
func NewFake() *Fake {
	f := &Fake{files: map[string]*node{}, dirs: map[string]bool{}, locks: map[string]bool{}}
	f.temp = f.clean(os.TempDir())
	_ = f.mkdirAll(f.temp) // below the root, a folder is always made
	return f
}

func (f *Fake) clean(p string) string {
	if !filepath.IsAbs(p) {
		p = string(filepath.Separator) + p
	}
	return filepath.Clean(p)
}

func fail(op, path string, err error) error { return &fs.PathError{Op: op, Path: path, Err: err} }

func root(p string) bool { return filepath.Dir(p) == p }

func (f *Fake) isDir(p string) bool { return root(p) || f.dirs[p] }

// under says whether p stands below dir.
func under(p, dir string) bool {
	if root(dir) {
		return p != dir && strings.HasPrefix(p, dir)
	}
	return strings.HasPrefix(p, dir+string(filepath.Separator))
}

// folderOf checks that p's folder exists, answering the error the real disk would.
func (f *Fake) folderOf(op, p string) error {
	dir := filepath.Dir(p)
	if f.isDir(dir) {
		return nil
	}
	if _, ok := f.files[dir]; ok {
		return fail(op, p, errNotDir)
	}
	return fail(op, p, errNotExist)
}

// file answers the file at p for writing, made empty where truncate is set.
func (f *Fake) file(op, p string, truncate bool) (*node, error) {
	if f.isDir(p) {
		return nil, fail(op, p, errIsDir)
	}
	if err := f.folderOf(op, p); err != nil {
		return nil, err
	}
	n, ok := f.files[p]
	if !ok {
		n = &node{}
		f.files[p] = n
	}
	if truncate {
		n.data = nil
	}
	return n, nil
}

func (f *Fake) ReadFile(path string) ([]byte, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	p := f.clean(path)
	if f.isDir(p) {
		return nil, fail("read", path, errIsDir)
	}
	n, ok := f.files[p]
	if !ok {
		return nil, fail("open", path, errNotExist)
	}
	// Never nil, as the real disk answers: an empty file is no missing one.
	data := make([]byte, len(n.data))
	copy(data, n.data)
	return data, nil
}

func (f *Fake) WriteFile(path string, data []byte) error {
	f.mu.Lock()
	defer f.mu.Unlock()
	n, err := f.file("open", f.clean(path), true)
	if err != nil {
		return err
	}
	n.data = append([]byte(nil), data...)
	return nil
}

func (f *Fake) Replace(path string, data []byte) error {
	f.mu.Lock()
	defer f.mu.Unlock()
	p := f.clean(path)
	if f.isDir(p) {
		return fail("rename", path, errIsDir)
	}
	if err := f.folderOf("replace", p); err != nil {
		return err
	}
	// A new node: a file opened before keeps the old content, as after a rename.
	f.files[p] = &node{data: append([]byte(nil), data...)}
	return nil
}

func (f *Fake) Create(path string) (io.WriteCloser, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	n, err := f.file("open", f.clean(path), true)
	if err != nil {
		return nil, err
	}
	return &writer{f: f, n: n}, nil
}

func (f *Fake) Append(path string) (io.WriteCloser, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	n, err := f.file("open", f.clean(path), false)
	if err != nil {
		return nil, err
	}
	return &writer{f: f, n: n}, nil
}

// writer writes at the end of its file until it is closed.
type writer struct {
	f      *Fake
	n      *node
	closed bool
}

func (w *writer) Write(b []byte) (int, error) {
	w.f.mu.Lock()
	defer w.f.mu.Unlock()
	if w.closed {
		return 0, fs.ErrClosed
	}
	w.n.data = append(w.n.data, b...)
	return len(b), nil
}

func (w *writer) Close() error {
	w.f.mu.Lock()
	defer w.f.mu.Unlock()
	if w.closed {
		return fs.ErrClosed
	}
	w.closed = true
	return nil
}

func (f *Fake) Exists(path string) (bool, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	p := f.clean(path)
	_, file := f.files[p]
	return file || f.isDir(p), nil
}

func (f *Fake) List(dir string) ([]string, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	d := f.clean(dir)
	if !f.isDir(d) {
		if _, ok := f.files[d]; ok {
			return nil, fail("readdirent", dir, errNotDir)
		}
		return nil, fail("open", dir, errNotExist)
	}
	names := []string{}
	add := func(p string) {
		if filepath.Dir(p) == d {
			names = append(names, filepath.Base(p))
		}
	}
	for p := range f.files {
		add(p)
	}
	for p := range f.dirs {
		add(p)
	}
	sort.Strings(names)
	return names, nil
}

func (f *Fake) Walk(rootDir string) ([]string, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	r := f.clean(rootDir)
	if _, ok := f.files[r]; ok {
		return []string{rootDir}, nil
	}
	if !f.isDir(r) {
		return nil, fail("lstat", rootDir, errNotExist)
	}
	var out []string
	for p := range f.files {
		if under(p, r) {
			// Answered as the caller named the root, as filepath.WalkDir does.
			rel, _ := filepath.Rel(r, p)
			out = append(out, filepath.Join(rootDir, rel))
		}
	}
	sort.Strings(out)
	return out, nil
}

func (f *Fake) mkdirAll(p string) error {
	if f.isDir(p) {
		return nil
	}
	if _, ok := f.files[p]; ok {
		return fail("mkdir", p, errNotDir)
	}
	if err := f.mkdirAll(filepath.Dir(p)); err != nil {
		return err
	}
	f.dirs[p] = true
	return nil
}

func (f *Fake) MkdirAll(dir string) error {
	f.mu.Lock()
	defer f.mu.Unlock()
	return f.mkdirAll(f.clean(dir))
}

func (f *Fake) MkdirTemp(dir, pattern string) (string, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	if strings.ContainsRune(pattern, filepath.Separator) || strings.ContainsRune(pattern, '/') {
		return "", fail("mkdirtemp", pattern, errors.New("pattern contains path separator"))
	}
	d := f.temp
	if dir != "" {
		d = f.clean(dir)
	}
	if !f.isDir(d) {
		return "", fail("mkdirtemp", filepath.Join(dir, pattern), errNotExist)
	}
	for {
		f.seq++
		name := pattern + fmt.Sprint(f.seq)
		if i := strings.LastIndex(pattern, "*"); i >= 0 {
			name = pattern[:i] + fmt.Sprint(f.seq) + pattern[i+1:]
		}
		p := filepath.Join(d, name)
		if _, taken := f.files[p]; !taken && !f.dirs[p] {
			f.dirs[p] = true
			if dir == "" {
				return p, nil
			}
			return filepath.Join(dir, name), nil
		}
	}
}

func (f *Fake) Rename(from, to string) error {
	f.mu.Lock()
	defer f.mu.Unlock()
	src, dst := f.clean(from), f.clean(to)
	_, file := f.files[src]
	if !file && !f.dirs[src] {
		return &os.LinkError{Op: "rename", Old: from, New: to, Err: errNotExist}
	}
	if err := f.folderOf("rename", dst); err != nil {
		return &os.LinkError{Op: "rename", Old: from, New: to, Err: errors.Unwrap(err)}
	}
	if src == dst {
		return nil
	}
	if f.isDir(dst) {
		return &os.LinkError{Op: "rename", Old: from, New: to, Err: errIsDir}
	}
	if file {
		f.files[dst] = f.files[src]
		delete(f.files, src)
		return nil
	}
	if _, ok := f.files[dst]; ok {
		return &os.LinkError{Op: "rename", Old: from, New: to, Err: errNotDir}
	}
	if under(dst, src) {
		return &os.LinkError{Op: "rename", Old: from, New: to, Err: errors.New("a folder cannot move into itself")}
	}
	moved := func(p string) string { return dst + strings.TrimPrefix(p, src) }
	for p, n := range f.files {
		if under(p, src) {
			delete(f.files, p)
			f.files[moved(p)] = n
		}
	}
	for p := range f.dirs {
		if under(p, src) {
			delete(f.dirs, p)
			f.dirs[moved(p)] = true
		}
	}
	delete(f.dirs, src)
	f.dirs[dst] = true
	return nil
}

func (f *Fake) Remove(path string) error {
	f.mu.Lock()
	defer f.mu.Unlock()
	p := f.clean(path)
	if _, ok := f.files[p]; ok {
		delete(f.files, p)
		return nil
	}
	if !f.dirs[p] {
		if root(p) {
			return fail("remove", path, errNotEmpty)
		}
		return fail("remove", path, errNotExist)
	}
	for q := range f.files {
		if under(q, p) {
			return fail("remove", path, errNotEmpty)
		}
	}
	for q := range f.dirs {
		if under(q, p) {
			return fail("remove", path, errNotEmpty)
		}
	}
	delete(f.dirs, p)
	return nil
}

func (f *Fake) RemoveAll(path string) error {
	f.mu.Lock()
	defer f.mu.Unlock()
	p := f.clean(path)
	if root(p) {
		return fail("removeall", path, errors.New("the root is not removed"))
	}
	delete(f.files, p)
	delete(f.dirs, p)
	for q := range f.files {
		if under(q, p) {
			delete(f.files, q)
		}
	}
	for q := range f.dirs {
		if under(q, p) {
			delete(f.dirs, q)
		}
	}
	return nil
}

func (f *Fake) Lock(path string) (io.Closer, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	p := f.clean(path)
	if _, err := f.file("open", p, false); err != nil {
		return nil, err
	}
	if f.locks[p] {
		return nil, ErrLocked
	}
	f.locks[p] = true
	return &held{f: f, p: p}, nil
}

// held is a lock the fake has given out, until it is closed.
type held struct {
	f      *Fake
	p      string
	closed bool
}

func (h *held) Close() error {
	h.f.mu.Lock()
	defer h.f.mu.Unlock()
	if h.closed {
		return fs.ErrClosed
	}
	h.closed = true
	delete(h.f.locks, h.p)
	return nil
}
