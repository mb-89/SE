package disk

import (
	"io"
	"io/fs"
	"os"
	"path/filepath"
	"sort"
)

// Real answers the machine's filesystem.
func Real() Disk { return machine{} }

type machine struct{}

func (machine) ReadFile(path string) ([]byte, error) { return os.ReadFile(path) }

func (machine) WriteFile(path string, data []byte) error { return os.WriteFile(path, data, 0o644) }

func (machine) Replace(path string, data []byte) error {
	tmp, err := os.CreateTemp(filepath.Dir(path), "."+filepath.Base(path)+"-*")
	if err != nil {
		return err
	}
	defer os.Remove(tmp.Name())
	if _, err := tmp.Write(data); err != nil {
		tmp.Close()
		return err
	}
	if err := tmp.Chmod(0o644); err != nil {
		tmp.Close()
		return err
	}
	if err := tmp.Close(); err != nil {
		return err
	}
	return os.Rename(tmp.Name(), path)
}

func (machine) Create(path string) (io.WriteCloser, error) { return os.Create(path) }

func (machine) Append(path string) (io.WriteCloser, error) {
	return os.OpenFile(path, os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0o644)
}

func (machine) Exists(path string) (bool, error) {
	_, err := os.Stat(path)
	if err == nil {
		return true, nil
	}
	if os.IsNotExist(err) {
		return false, nil
	}
	return false, err
}

func (machine) List(dir string) ([]string, error) {
	entries, err := os.ReadDir(dir)
	if err != nil {
		return nil, err
	}
	names := make([]string, len(entries))
	for i, e := range entries {
		names[i] = e.Name()
	}
	sort.Strings(names)
	return names, nil
}

func (machine) Walk(root string) ([]string, error) {
	var files []string
	err := filepath.WalkDir(root, func(path string, e fs.DirEntry, err error) error {
		if err != nil || e.IsDir() {
			return err
		}
		files = append(files, path)
		return nil
	})
	sort.Strings(files)
	return files, err
}

func (machine) MkdirAll(dir string) error { return os.MkdirAll(dir, 0o755) }

func (machine) MkdirTemp(dir, pattern string) (string, error) { return os.MkdirTemp(dir, pattern) }

func (machine) Rename(from, to string) error { return os.Rename(from, to) }

func (machine) Remove(path string) error { return os.Remove(path) }

func (machine) RemoveAll(path string) error { return os.RemoveAll(path) }

func (machine) Lock(path string) (io.Closer, error) { return lock(path) }
