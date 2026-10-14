package main

import (
	"encoding/json"
	"fmt"
	"os"
	"strings"
	"sync/atomic"
	"time"

	"github.com/mb-89/SE/src/internal/daemon"
	"github.com/mb-89/SE/src/internal/io/github"
	"github.com/mb-89/SE/src/internal/issues"
)

// noting is GitHub that notes whether a command wrote to it, so se tells
// the daemon its snapshot went stale once the command is done.
type noting struct {
	github.GitHub
	wrote atomic.Bool
}

func (n *noting) Send(method, path string, fields ...github.Field) ([]byte, error) {
	n.wrote.Store(true)
	return n.GitHub.Send(method, path, fields...)
}

func (n *noting) GraphQL(query string, vars ...github.Field) ([]byte, error) {
	n.wrote.Store(true)
	return n.GitHub.GraphQL(query, vars...)
}

// wrote marks the command as one that changed GitHub without a write through
// it, such as a claim's push of its branch.
func (c *Call) wrote() {
	if n, ok := c.GitHub.(*noting); ok {
		n.wrote.Store(true)
	}
}

// snapshotName is the name the daemon keeps its GitHub snapshot under: the
// snapshot output of the wiring's github instance.
func snapshotName() string {
	for _, in := range catalog().Instances {
		if in.Module == github.Module.Name() {
			return in.Name + "/snapshot"
		}
	}
	return ""
}

// stale tells the workspace's daemon, where one answers, that its GitHub
// snapshot no longer matches GitHub, so it reads it again at once. It never
// starts a daemon, and a daemon that cannot hear it is left as it is.
func (c *Call) stale() {
	ep, ok := daemon.Healthy(c.Paths(), c.Net)
	if !ok {
		return
	}
	_ = c.Net.Stale(ep.Address, ep.Token, snapshotName())
}

// warm answers the snapshot of repo the workspace's daemon keeps, where a
// daemon answers with one. It never starts a daemon: without one the
// command reads GitHub itself.
func (c *Call) warm(repo string) (github.Snapshot, bool) {
	ep, ok := daemon.Healthy(c.Paths(), c.Net)
	if !ok {
		return github.Snapshot{}, false
	}
	v, err := c.Net.Value(ep.Address, ep.Token, snapshotName())
	if err != nil || !v.Provided {
		return github.Snapshot{}, false
	}
	data, err := json.Marshal(v.Value)
	if err != nil {
		return github.Snapshot{}, false
	}
	var snap github.Snapshot
	if err := json.Unmarshal(data, &snap); err != nil || snap.Repo != repo || !snap.Taken() {
		return github.Snapshot{}, false
	}
	return snap, true
}

// fromSnapshot points s at the daemon's snapshot of its repository, where
// one is warm, and keeps GitHub itself as s.Live for what a claim must be
// sure of. It answers how old the snapshot is where that is older than its
// refresh, else "".
func (c *Call) fromSnapshot(s *issues.Source, set github.Settings) string {
	snap, ok := c.warm(s.Repo)
	if !ok {
		return ""
	}
	s.Live, s.GitHub = s.GitHub, github.Replay(snap, s.GitHub)
	if age := c.Clock.Now().Sub(snap.At); age > set.Refresh {
		return age.Round(time.Second).String()
	}
	return ""
}

// agedReply says, below a reply of issue pull, how old the snapshot it was
// answered from is, where that is older than its refresh.
func agedReply(r Reply, err error, asJSON bool, age string) (Reply, error) {
	if err != nil || age == "" {
		return r, err
	}
	note := fmt.Sprintf("Answered from the daemon's snapshot of GitHub, %s old.", age)
	if !asJSON {
		r.Text = strings.TrimRight(r.Text, "\n") + "\n\n" + note
		return r, nil
	}
	var answer map[string]any
	if err := json.Unmarshal([]byte(r.Text), &answer); err != nil {
		return Reply{}, err
	}
	answer["snapshot_age"] = age
	data, err := json.Marshal(answer)
	return Reply{Text: string(data)}, err
}

// keepers are what the workspace's daemon keeps in step with the outside:
// the GitHub snapshot of the workspace's repository, read as se issue pull
// reads it. A workspace with no repository on GitHub keeps none.
func (c *Call) keepers() []daemon.Keeper {
	repo, err := issues.Repo(c.Proc, c.Workspace)
	if err != nil {
		fmt.Fprintf(os.Stderr, "se: keeping no GitHub snapshot: %v\n", err)
		return nil
	}
	read := func(set github.Settings) (github.Snapshot, error) {
		return issues.Warm(issues.Source{Repo: repo, GitHub: c.GitHub, Clock: c.Clock, Disk: c.Disk, Proc: c.Proc, Settle: set.Settle})
	}
	log := func(s string) { fmt.Fprintln(os.Stderr, "se:", s) }
	return []daemon.Keeper{github.NewKeeper(read, c.Clock, log)}
}
