package reuse

import (
	"encoding/json"
	"fmt"
	"path/filepath"
	"strings"

	"github.com/mb-89/SE/src/internal/io/disk"
	"github.com/mb-89/SE/src/internal/io/proc"
)

// Repos is the folder under a fetch's target that keeps the repositories it
// fetched from; Claude Code skips it, as it holds no plugin manifest.
const Repos = ".repos"

// Fetch puts every source at its pinned commit into the folder into, as a
// folder of plugins that one entry of DirsVar loads: each plugin as
// into/<name>, each lone skill as into/adopted/skills/<name> beside the
// adopted plugin's manifest. A folder there that no source names any more is
// removed. It answers one line per source.
func Fetch(p proc.Procs, d disk.Disk, into string, sources []Source) ([]string, error) {
	repos := filepath.Join(into, Repos)
	if err := d.MkdirAll(repos); err != nil {
		return nil, err
	}
	git := func(dir string, args ...string) error {
		out, err := proc.Combined(p, proc.Cmd{Name: "git", Args: append([]string{"-C", dir}, args...)})
		if err != nil {
			return fmt.Errorf("git %s: %v %s", strings.Join(args, " "), err, strings.TrimSpace(string(out)))
		}
		return nil
	}
	// The adopted plugin is made anew, so a skill no source names leaves it.
	if err := d.RemoveAll(filepath.Join(into, Adopted)); err != nil {
		return nil, err
	}
	var lines []string
	keep := map[string]bool{Repos: true}
	skills := false
	for _, s := range sources {
		repo := filepath.Join(repos, strings.ReplaceAll(s.Repo, "/", "-"))
		if ok, err := d.Exists(filepath.Join(repo, ".git")); err != nil {
			return lines, err
		} else if !ok {
			if err := d.MkdirAll(repo); err != nil {
				return lines, err
			}
			if err := git(repo, "init", "-q"); err != nil {
				return lines, err
			}
		}
		if err := git(repo, "fetch", "-q", "--depth", "1", "https://github.com/"+s.Repo, s.Commit); err != nil {
			return lines, fmt.Errorf("%s: %w", s.Name, err)
		}
		target := filepath.Join(into, s.Name)
		keep[s.Name] = true
		if s.Skill {
			target, skills = filepath.Join(into, Adopted, "skills", s.Name), true
			keep[Adopted] = true
		}
		if err := d.RemoveAll(target); err != nil {
			return lines, err
		}
		if err := d.MkdirAll(target); err != nil {
			return lines, err
		}
		tree := s.Commit
		if clean := filepath.ToSlash(filepath.Clean(s.Path)); clean != "." {
			tree += ":" + clean
		}
		tarball := filepath.Join(repos, s.Name+".tar")
		if err := git(repo, "archive", "--format=tar", "-o", tarball, tree); err != nil {
			return lines, fmt.Errorf("%s: %w", s.Name, err)
		}
		out, err := proc.Combined(p, proc.Cmd{Name: "tar", Args: []string{"-xf", tarball, "-C", target}})
		if err != nil {
			return lines, fmt.Errorf("%s: tar: %v %s", s.Name, err, strings.TrimSpace(string(out)))
		}
		if err := d.Remove(tarball); err != nil {
			return lines, err
		}
		lines = append(lines, fmt.Sprintf("%s: %s %s at %s (%s), as the plugin %s", s.Name, s.Repo, s.Path, s.Commit[:12], s.Licence, s.Plugin()))
	}
	if skills {
		manifest, _ := json.MarshalIndent(map[string]string{
			"name":        Adopted,
			"description": "The lone skills SE adopted, each pinned in the reuse config of SE's wiring.",
		}, "", "  ")
		dir := filepath.Join(into, Adopted, ".claude-plugin")
		if err := d.MkdirAll(dir); err != nil {
			return lines, err
		}
		if err := d.Replace(filepath.Join(dir, "plugin.json"), append(manifest, '\n')); err != nil {
			return lines, err
		}
	}
	there, err := d.List(into)
	if err != nil {
		return lines, err
	}
	for _, name := range there {
		if !keep[name] {
			if err := d.RemoveAll(filepath.Join(into, name)); err != nil {
				return lines, err
			}
			lines = append(lines, name+": removed, as no source names it")
		}
	}
	return lines, nil
}
