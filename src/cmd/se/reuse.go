package main

import (
	"fmt"
	"path/filepath"
	"strings"

	"github.com/mb-89/SE/src/internal/issues"
	"github.com/mb-89/SE/src/internal/reuse"
)

func init() {
	register(Command{
		Name:    "fleet plugins",
		Usage:   "fleet plugins --into DIR",
		Group:   "Fleet",
		Class:   batch,
		Summary: "fetch the outside plugins and skills SE runs, pinned",
		Details: []string{
			fmt.Sprintf("fetch every source of the reuse config (src/index/wiring.yaml) at its pinned commit into DIR, as a folder of plugins that one entry of %v loads: each plugin as DIR/<name>, each lone skill inside DIR/%v.", reuse.DirsVar, reuse.Adopted),
			"A folder there that no source names any more is removed.",
			"A cloud environment's setup script runs it (spec/cloud.md).",
		},
		Run: func(c *Call) (Reply, error) {
			fs := c.Flags("fleet plugins")
			into := fs.String("into", "", "the `DIR` to fetch them into")
			if err := c.Parse(fs); err != nil {
				return Reply{}, err
			}
			if *into == "" {
				return Reply{}, fmt.Errorf("fleet plugins needs --into: the folder to fetch the plugins into")
			}
			dir, err := filepath.Abs(*into)
			if err != nil {
				return Reply{}, err
			}
			cfg, err := reuse.Configured()
			if err != nil {
				return Reply{}, err
			}
			lines, err := reuse.Fetch(c.Proc, c.Disk, dir, cfg.Sources)
			if err != nil {
				return Reply{}, err
			}
			lines = append(lines, fmt.Sprintf("Load them with %s=<the se plugin>%c%s", reuse.DirsVar, filepath.ListSeparator, dir))
			return Reply{Text: strings.Join(lines, "\n")}, nil
		},
	})
}

// The intros the tiers are handed with: when each runs, and over what.
const (
	workerIntro   = "Before you commit, run each of these on your own diff, once and briefly; it adds nothing to the landing, whose battery is the guarantee (reuse config, src/index/wiring.yaml):"
	authorIntro   = "Where your change writes or changes an SE agent or skill, also run each of these on it:"
	reviewerIntro = "## What you run on the delta\n\nRun each of these on the delta, the merged code of the tree against its base, as a finder: what one reports is a candidate finding for your step 5, to verify like any other; change no code. The report's `ran` names each, with what it found or why it did not run (reuse config, src/index/wiring.yaml):"
	overhaulIntro = "Run each of these over the whole of SE's code, taking as long as they need; what they find goes into `looked_at.removal` and the findings, like any other (reuse config, src/index/wiring.yaml):"
)

// reused answers what tier is handed, with intro, resolved against the
// plugins this session loaded; a config that cannot be read is said.
func (c *Call) reused(tier, intro string) string {
	cfg, err := reuse.Configured()
	if err != nil {
		return fmt.Sprintf("What the %s runs could not be read: %v", tier, err)
	}
	return c.resolved(cfg, tier, intro)
}

// resolved is reused on a config already read.
func (c *Call) resolved(cfg reuse.Config, tier, intro string) string {
	return reuse.Text(intro, cfg.Resolve(c.Disk, tier, reuse.Dirs(c.Getenv(reuse.DirsVar))))
}

// tierText is what a take hands over beside the issue's skills: the worker's
// and the author's lists for a leaf, the overhaul's list and places for an
// overhaul, nothing for a parent or a retro.
func (c *Call) tierText(i issues.Issue) string {
	if i.Parent || i.Retro {
		return ""
	}
	cfg, err := reuse.Configured()
	if err != nil {
		return fmt.Sprintf("What its tier runs could not be read: %v", err)
	}
	if i.Overhaul {
		text := c.resolved(cfg, reuse.Overhaul, overhaulIntro)
		if len(cfg.Places) > 0 {
			text += "\n\nThe `outside` look also searches these places for what SE could adopt instead of keeping its own (read it, check its licence, pin it to a commit; adopt it only where it beats what SE has):\n- " + strings.Join(cfg.Places, "\n- ")
		}
		return text
	}
	parts := []string{}
	for _, t := range []struct{ tier, intro string }{{reuse.Worker, workerIntro}, {reuse.Author, authorIntro}} {
		if text := c.resolved(cfg, t.tier, t.intro); text != "" {
			parts = append(parts, text)
		}
	}
	return strings.Join(parts, "\n\n")
}

// checkRan refuses a review report that does not name, in ran, each entry of
// the reviewer's list, with what it found or why it did not run.
func checkRan(rep issues.Report) error {
	cfg, err := reuse.Configured()
	if err != nil {
		return err
	}
	return rep.CheckRan(cfg.Tier[reuse.Reviewer])
}
