package disk_test

import (
	"errors"
	"io/fs"
	"path/filepath"
	"slices"
	"testing"

	"github.com/mb-89/SE/src/modules/io/disk"
)

// contract is the one suite every Disk keeps, the fake as the real one.
// fresh answers a disk and an empty folder on it for each case.
func contract(t *testing.T, fresh func(t *testing.T) (disk.Disk, string)) {
	t.Run("a file reads back what was written", func(t *testing.T) {
		d, dir := fresh(t)
		p := filepath.Join(dir, "a.txt")
		must(t, d.WriteFile(p, []byte("one")))
		must(t, d.WriteFile(p, []byte("two")))
		if got := read(t, d, p); got != "two" {
			t.Fatalf("read %q", got)
		}
	})
	t.Run("an empty file reads as empty, not as nothing", func(t *testing.T) {
		d, dir := fresh(t)
		p := filepath.Join(dir, "empty")
		must(t, d.WriteFile(p, nil))
		if b, err := d.ReadFile(p); err != nil || b == nil || len(b) != 0 {
			t.Fatalf("read %v, %v", b, err)
		}
	})
	t.Run("a path that names nothing does not exist", func(t *testing.T) {
		d, dir := fresh(t)
		p := filepath.Join(dir, "gone")
		if _, err := d.ReadFile(p); !errors.Is(err, fs.ErrNotExist) {
			t.Fatalf("read: %v", err)
		}
		if ok, err := d.Exists(p); ok || err != nil {
			t.Fatalf("exists: %v %v", ok, err)
		}
		if err := d.Remove(p); !errors.Is(err, fs.ErrNotExist) {
			t.Fatalf("remove: %v", err)
		}
		if err := d.Rename(p, p+".old"); !errors.Is(err, fs.ErrNotExist) {
			t.Fatalf("rename: %v", err)
		}
		if _, err := d.List(p); !errors.Is(err, fs.ErrNotExist) {
			t.Fatalf("list: %v", err)
		}
		if _, err := d.Walk(p); !errors.Is(err, fs.ErrNotExist) {
			t.Fatalf("walk: %v", err)
		}
		if err := d.RemoveAll(p); err != nil {
			t.Fatalf("remove all of nothing: %v", err)
		}
	})
	t.Run("a file needs its folder", func(t *testing.T) {
		d, dir := fresh(t)
		p := filepath.Join(dir, "no", "a.txt")
		if err := d.WriteFile(p, nil); !errors.Is(err, fs.ErrNotExist) {
			t.Fatalf("write: %v", err)
		}
		if err := d.Replace(p, nil); !errors.Is(err, fs.ErrNotExist) {
			t.Fatalf("replace: %v", err)
		}
		if _, err := d.Append(p); !errors.Is(err, fs.ErrNotExist) {
			t.Fatalf("append: %v", err)
		}
		if _, err := d.Lock(p); !errors.Is(err, fs.ErrNotExist) {
			t.Fatalf("lock: %v", err)
		}
		must(t, d.MkdirAll(filepath.Dir(p)))
		must(t, d.WriteFile(p, []byte("x")))
	})
	t.Run("a folder is no file", func(t *testing.T) {
		d, dir := fresh(t)
		sub := filepath.Join(dir, "sub")
		must(t, d.MkdirAll(sub))
		must(t, d.MkdirAll(sub))
		if ok, err := d.Exists(sub); !ok || err != nil {
			t.Fatalf("exists: %v %v", ok, err)
		}
		if _, err := d.ReadFile(sub); err == nil {
			t.Fatal("read a folder")
		}
		if err := d.WriteFile(sub, nil); err == nil {
			t.Fatal("wrote over a folder")
		}
		f := filepath.Join(dir, "f")
		must(t, d.WriteFile(f, nil))
		if err := d.MkdirAll(filepath.Join(f, "below")); err == nil {
			t.Fatal("made a folder below a file")
		}
		if err := d.WriteFile(filepath.Join(f, "below"), nil); err == nil {
			t.Fatal("wrote a file below a file")
		}
	})
	t.Run("append adds at the end and creates", func(t *testing.T) {
		d, dir := fresh(t)
		p := filepath.Join(dir, "log")
		for _, line := range []string{"a\n", "b\n"} {
			w, err := d.Append(p)
			must(t, err)
			if _, err := w.Write([]byte(line)); err != nil {
				t.Fatal(err)
			}
			must(t, w.Close())
		}
		if got := read(t, d, p); got != "a\nb\n" {
			t.Fatalf("read %q", got)
		}
	})
	t.Run("create truncates and writes", func(t *testing.T) {
		d, dir := fresh(t)
		p := filepath.Join(dir, "out")
		must(t, d.WriteFile(p, []byte("old content")))
		w, err := d.Create(p)
		must(t, err)
		if got := read(t, d, p); got != "" {
			t.Fatalf("not truncated: %q", got)
		}
		_, err = w.Write([]byte("new"))
		must(t, err)
		must(t, w.Close())
		if _, err := w.Write([]byte("late")); err == nil {
			t.Fatal("wrote after close")
		}
		if got := read(t, d, p); got != "new" {
			t.Fatalf("read %q", got)
		}
	})
	t.Run("replace puts the whole file and leaves nothing beside it", func(t *testing.T) {
		d, dir := fresh(t)
		p := filepath.Join(dir, "daemon.json")
		must(t, d.Replace(p, []byte("first")))
		must(t, d.Replace(p, []byte("second")))
		if got := read(t, d, p); got != "second" {
			t.Fatalf("read %q", got)
		}
		names, err := d.List(dir)
		must(t, err)
		if !slices.Equal(names, []string{"daemon.json"}) {
			t.Fatalf("the folder holds %v", names)
		}
	})
	t.Run("list names a folder's entries, sorted", func(t *testing.T) {
		d, dir := fresh(t)
		must(t, d.MkdirAll(filepath.Join(dir, "b", "deep")))
		must(t, d.WriteFile(filepath.Join(dir, "c"), nil))
		must(t, d.WriteFile(filepath.Join(dir, "a"), nil))
		must(t, d.WriteFile(filepath.Join(dir, "b", "deep", "x"), nil))
		names, err := d.List(dir)
		must(t, err)
		if !slices.Equal(names, []string{"a", "b", "c"}) {
			t.Fatalf("listed %v", names)
		}
		if _, err := d.List(filepath.Join(dir, "a")); err == nil {
			t.Fatal("listed a file")
		}
	})
	t.Run("walk names every file below, sorted", func(t *testing.T) {
		d, dir := fresh(t)
		must(t, d.MkdirAll(filepath.Join(dir, "a", "b")))
		must(t, d.MkdirAll(filepath.Join(dir, "empty")))
		for _, p := range []string{"z", "a.txt", "a/b/c", "a/one"} {
			must(t, d.WriteFile(filepath.Join(dir, filepath.FromSlash(p)), nil))
		}
		got, err := d.Walk(dir)
		must(t, err)
		var want []string
		for _, p := range []string{"a.txt", "a/b/c", "a/one", "z"} {
			want = append(want, filepath.Join(dir, filepath.FromSlash(p)))
		}
		slices.Sort(want)
		if !slices.Equal(got, want) {
			t.Fatalf("walked %v, want %v", got, want)
		}
	})
	t.Run("rename moves a file and replaces one", func(t *testing.T) {
		d, dir := fresh(t)
		a, b := filepath.Join(dir, "a"), filepath.Join(dir, "b")
		must(t, d.WriteFile(a, []byte("A")))
		must(t, d.WriteFile(b, []byte("B")))
		must(t, d.Rename(a, b))
		if ok, _ := d.Exists(a); ok {
			t.Fatal("the old name stays")
		}
		if got := read(t, d, b); got != "A" {
			t.Fatalf("read %q", got)
		}
		if err := d.Rename(b, filepath.Join(dir, "no", "b")); !errors.Is(err, fs.ErrNotExist) {
			t.Fatalf("rename into nothing: %v", err)
		}
	})
	t.Run("rename moves a folder with all it holds", func(t *testing.T) {
		d, dir := fresh(t)
		from, to := filepath.Join(dir, "from"), filepath.Join(dir, "to")
		must(t, d.MkdirAll(filepath.Join(from, "in")))
		must(t, d.WriteFile(filepath.Join(from, "in", "f"), []byte("f")))
		must(t, d.Rename(from, to))
		if got := read(t, d, filepath.Join(to, "in", "f")); got != "f" {
			t.Fatalf("read %q", got)
		}
		if ok, _ := d.Exists(from); ok {
			t.Fatal("the old folder stays")
		}
	})
	t.Run("an open file keeps writing after a rename", func(t *testing.T) {
		d, dir := fresh(t)
		a, b := filepath.Join(dir, "a"), filepath.Join(dir, "b")
		w, err := d.Append(a)
		must(t, err)
		must(t, d.Rename(a, b))
		_, err = w.Write([]byte("x"))
		must(t, err)
		must(t, w.Close())
		if got := read(t, d, b); got != "x" {
			t.Fatalf("read %q", got)
		}
	})
	t.Run("remove takes a file or an empty folder, remove all takes everything", func(t *testing.T) {
		d, dir := fresh(t)
		sub := filepath.Join(dir, "sub")
		must(t, d.MkdirAll(filepath.Join(sub, "in")))
		must(t, d.WriteFile(filepath.Join(sub, "in", "f"), nil))
		if err := d.Remove(sub); err == nil {
			t.Fatal("removed a folder that holds a file")
		}
		must(t, d.Remove(filepath.Join(sub, "in", "f")))
		must(t, d.Remove(filepath.Join(sub, "in")))
		must(t, d.WriteFile(filepath.Join(sub, "g"), nil))
		must(t, d.RemoveAll(sub))
		if ok, _ := d.Exists(sub); ok {
			t.Fatal("the folder stays")
		}
		if ok, _ := d.Exists(filepath.Join(sub, "g")); ok {
			t.Fatal("its file stays")
		}
	})
	t.Run("a temp folder is new and empty each time", func(t *testing.T) {
		d, dir := fresh(t)
		a, err := d.MkdirTemp(dir, "decoy-*")
		must(t, err)
		b, err := d.MkdirTemp(dir, "decoy-*")
		must(t, err)
		if a == b || filepath.Dir(a) != dir {
			t.Fatalf("made %s and %s", a, b)
		}
		if names, err := d.List(a); err != nil || len(names) != 0 {
			t.Fatalf("listed %v %v", names, err)
		}
		c, err := d.MkdirTemp("", "decoy-*")
		must(t, err)
		defer func() { _ = d.RemoveAll(c) }()
		if ok, _ := d.Exists(c); !ok {
			t.Fatalf("%s was not made", c)
		}
		if _, err := d.MkdirTemp(filepath.Join(dir, "no"), "x-*"); !errors.Is(err, fs.ErrNotExist) {
			t.Fatalf("made a temp folder in nothing: %v", err)
		}
	})
	t.Run("a lock is held until it is let go", func(t *testing.T) {
		d, dir := fresh(t)
		p := filepath.Join(dir, "daemon.lock")
		first, err := d.Lock(p)
		must(t, err)
		if ok, _ := d.Exists(p); !ok {
			t.Fatal("the lock file was not made")
		}
		if _, err := d.Lock(p); !errors.Is(err, disk.ErrLocked) {
			t.Fatalf("a held lock was given again: %v", err)
		}
		must(t, first.Close())
		again, err := d.Lock(p)
		must(t, err)
		must(t, again.Close())
	})
}

func must(t *testing.T, err error) {
	t.Helper()
	if err != nil {
		t.Fatal(err)
	}
}

func read(t *testing.T, d disk.Disk, p string) string {
	t.Helper()
	b, err := d.ReadFile(p)
	must(t, err)
	return string(b)
}
