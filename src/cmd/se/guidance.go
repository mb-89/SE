package main

import (
	"bufio"
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"io/fs"
	"path/filepath"
	"strings"
	"time"

	"github.com/mb-89/SE/src/internal/daemon"
	"github.com/mb-89/SE/src/internal/guidance"
	sehttp "github.com/mb-89/SE/src/internal/io/http"
	"github.com/mb-89/SE/src/internal/issues"
)

func init() {
	register(Command{
		Name:    "guidance",
		Class:   interactive,
		Usage:   "guidance [--session-id ID]",
		Group:   "Session",
		Summary: "answer the principles and the skills a session holds",
		Details: "answer the guidance a session's context carries: spec/principles.md where the guidance instance's principles switch is on, in a box the whole procedure of its agent, se:coordinator, and each skill a take handed to session ID, as its log records them, in full where the inline switch is on, else by name. Each is read from the SE checkout the plugin was loaded from (SE_PLUGIN_CHECKOUT, else the workspace), so a project holds no SE file. The plugin's SessionStart hook puts it into the context on startup, resume, clear and compact; the hand-again is a row of the session's log.",
		Session: true,
		Run: func(c *Call) (Reply, error) {
			flags := c.Flags("guidance")
			id := flags.String("session-id", "", "the session `ID` whose log names the skills handed to it")
			if err := c.Parse(flags); err != nil {
				return Reply{}, err
			}
			set, err := c.Guided()
			if err != nil {
				return Reply{}, err
			}
			var parts []string
			if set.Principles {
				data, err := c.Disk.ReadFile(filepath.Join(c.seRoot(), guidance.Principles))
				switch {
				case err == nil:
					parts = append(parts, fmt.Sprintf("SE's design principles (%s), which every change is measured against:\n\n%s", guidance.Principles, strings.TrimRight(string(data), "\n")))
				case !errors.Is(err, fs.ErrNotExist):
					return Reply{}, err
				}
			}
			if c.isBox() {
				box, err := c.boxAgent()
				if err != nil {
					return Reply{}, err
				}
				parts = append(parts, box)
			}
			names, err := handedTo(c, *id)
			if err != nil {
				return Reply{}, err
			}
			if len(names) > 0 {
				skills, err := guidance.Read(c.Disk, c.seRoot(), names)
				if err != nil {
					return Reply{}, err
				}
				parts = append(parts, guidance.Text(skills, set.Inline))
				if why := c.logHandOver(*id, skills, true); why != "" {
					parts = append(parts, why)
				}
			}
			return Reply{Text: strings.Join(parts, "\n\n")}, nil
		},
	})
}

// seRoot is the SE checkout the session's plugin was loaded from, which the
// guidance reads: the one the plugin names on every session call, else the
// one this se was built into where it holds the plugin, else the workspace,
// as when se runs in a checkout of SE.
func (c *Call) seRoot() string {
	if r := c.Getenv(pluginRepoEnv); r != "" {
		return r
	}
	if r := pluginCheckout(&c.World); r != "" {
		if ok, _ := c.Disk.Exists(filepath.Join(r, "src", "plugin", ".claude-plugin", "plugin.json")); ok {
			return r
		}
	}
	return c.Workspace
}

// boxAgent answers what a box's session starts with: the box is the parent
// kind's agent, se:coordinator, and runs its procedure in the session itself,
// since an agent cannot start agents of its own.
func (c *Call) boxAgent() (string, error) {
	k := issues.KindNamed("parent")
	data, err := c.Disk.ReadFile(filepath.Join(c.seRoot(), filepath.FromSlash(k.File())))
	if err != nil {
		return "", fmt.Errorf("this box's agent %s cannot be read: %w", k.Type(), err)
	}
	return fmt.Sprintf("This session is an SE box: it is %s, the agent of the box, and follows its procedure, which follows in full (%s).\n\n<agent name=%q>\n%s\n</agent>",
		k.Type(), k.File(), k.Type(), strings.TrimSpace(guidance.Body(data))), nil
}

// handOver reads the skills issue i names, records the hand-over in the
// session's log, and answers them with the text a take adds to its answer,
// followed by what its tier runs that others built (tierText).
// The claim stands either way: a skill that cannot be handed over is said. A
// name that is an agent's role (retro, overhaul) is no skill: the take's
// agent holds that role, so it is neither handed over nor missing.
func (c *Call) handOver(i issues.Issue) handed {
	h := c.handOverSkills(i)
	if tier := c.tierText(i); tier != "" {
		h.Text = strings.TrimLeft(h.Text+"\n\n"+tier, "\n")
	}
	return h
}

// handOverSkills hands over the skills issue i names, as handOver says.
func (c *Call) handOverSkills(i issues.Issue) handed {
	names := issues.Skills(guidance.Named(i.Body))
	if len(names) == 0 {
		return handed{}
	}
	set, err := c.Guided()
	if err != nil {
		return handed{Text: fmt.Sprintf("Its skills, %s, were not handed over: %v", strings.Join(names, ", "), err)}
	}
	skills, err := guidance.Read(c.Disk, c.seRoot(), names)
	if err != nil {
		return handed{Text: fmt.Sprintf("Its skills, %s, were not handed over: %v", strings.Join(names, ", "), err)}
	}
	h := handed{Skills: skills, Text: guidance.Text(skills, set.Inline)}
	if why := c.logHandOver(c.sessionID(), skills, false); why != "" {
		h.Text += "\n\n" + why
	}
	return h
}

// handOverRow is a hand-over's row in the session's log.
type handOverRow struct {
	Skills []guidance.Skill `json:"skills"`
	Again  bool             `json:"again,omitempty"`
}

// logHandOver posts the hand-over to the workspace's daemon, which appends it
// to the session's log; with no session or no daemon (SE off) there is no log
// to keep it. It answers why the log did not take it, or "".
func (c *Call) logHandOver(session string, skills []guidance.Skill, again bool) string {
	if session == "" {
		return ""
	}
	ep, ok := daemon.Healthy(c.Paths(), c.Net)
	if !ok {
		return ""
	}
	e, err := json.Marshal(handOverRow{Skills: skills, Again: again})
	if err == nil {
		err = c.Net.Event(ep.Address, ep.Token, sehttp.Event{Session: session, Event: guidance.Event, At: c.Clock.Now().UTC().Format(time.RFC3339Nano), E: e})
	}
	if err != nil {
		return fmt.Sprintf("The session's log did not take the hand-over: %v", err)
	}
	return ""
}

// handedTo answers the skills the session's log records as handed to it, each once, in order.
func handedTo(c *Call, session string) ([]string, error) {
	if session == "" || strings.ContainsAny(session, `/\`) {
		return nil, nil
	}
	data, err := c.Disk.ReadFile(filepath.Join(c.Paths().Logs(), session+".jsonl"))
	if errors.Is(err, fs.ErrNotExist) {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	var names []string
	seen := map[string]bool{}
	lines := bufio.NewScanner(bytes.NewReader(data))
	lines.Buffer(nil, 1<<20)
	for lines.Scan() {
		var row struct {
			Event string      `json:"event"`
			E     handOverRow `json:"e"`
		}
		if json.Unmarshal(lines.Bytes(), &row) != nil || row.Event != guidance.Event {
			continue
		}
		for _, s := range row.E.Skills {
			if _, role := issues.RoleNamed(s.Name); !role && !seen[s.Name] {
				seen[s.Name] = true
				names = append(names, s.Name)
			}
		}
	}
	return names, lines.Err()
}
