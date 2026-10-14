package main

import (
	"encoding/json"
	"fmt"
	"path/filepath"
	"regexp"
	"slices"
	"strconv"
	"strings"

	"gopkg.in/yaml.v3"
)

// The owner's rule: a box that takes an issue closes it, always, with a PR
// (auto-merge on) or a supersede. The plugin hands every Stop and SubagentStop
// to se hook stop, which refuses a box's stop while any issue it took is open
// with neither; se issue pull --take records each issue a box takes.

// isBox says whether this session is a box: a cloud session that no person
// attends, as a routine starts it. Every other session is interactive.
func (c *Call) isBox() bool {
	return c.Getenv("CLAUDE_CODE_REMOTE") == "true" && c.Getenv("CLAUDE_CODE_SESSION_ATTENDED") == "0"
}

// StopPath is the file in the repository that sets how often in a row the
// Stop hook refuses before it lets the turn end.
const StopPath = "spec/stop.yaml"

// defaultRefusals is the cap where spec/stop.yaml does not set one.
const defaultRefusals = 5

// boxState is what the workspace keeps for the Stop hook: every issue the box
// took, and how often in a row the hook refused, by issue.
type boxState struct {
	Issues  []int       `json:"issues,omitempty"`
	Refused map[int]int `json:"refused,omitempty"`
}

func boxPath(c *Call) string { return filepath.Join(c.Paths().Runtime(), "box.json") }

// readBox answers the workspace's state; one missing or unreadable is empty.
func readBox(c *Call) boxState {
	var b boxState
	if data, err := c.Disk.ReadFile(boxPath(c)); err == nil {
		_ = json.Unmarshal(data, &b)
	}
	if b.Refused == nil {
		b.Refused = map[int]int{}
	}
	return b
}

func writeBox(c *Call, b boxState) error {
	if err := c.Disk.MkdirAll(c.Paths().Runtime()); err != nil {
		return err
	}
	data, err := json.Marshal(b)
	if err != nil {
		return err
	}
	return c.Disk.Replace(boxPath(c), data)
}

// recordTake adds the issue a take claimed to those the box took, its
// refusals none yet.
func recordTake(c *Call, n int) error {
	b := readBox(c)
	delete(b.Refused, n)
	if !slices.Contains(b.Issues, n) {
		b.Issues = append(b.Issues, n)
	}
	return writeBox(c, b)
}

// refusals reads the cap from spec/stop.yaml in the workspace.
func refusals(c *Call) int {
	data, err := c.Disk.ReadFile(filepath.Join(c.Workspace, StopPath))
	if err != nil {
		return defaultRefusals
	}
	var cfg struct {
		Refusals int `yaml:"refusals"`
	}
	if yaml.Unmarshal(data, &cfg) != nil || cfg.Refusals <= 0 {
		return defaultRefusals
	}
	return cfg.Refusals
}

// stopLog appends why the hook let a turn end that it could not judge.
func stopLog(c *Call, line string) {
	if c.Disk.MkdirAll(c.Paths().Logs()) != nil {
		return
	}
	f, err := c.Disk.Append(filepath.Join(c.Paths().Logs(), "stop.log"))
	if err != nil {
		return
	}
	defer f.Close()
	fmt.Fprintf(f, "%s %s\n", c.Clock.Now().UTC().Format("2006-01-02T15:04:05Z"), line)
}

// leafPrompt is how the work skill starts a leaf's sub-agent.
var leafPrompt = regexp.MustCompile(`Work on se issue #(\d+) in the worktree`)

// verdict is what se hook stop answers the plugin: block, with the reason the
// agent reads, or pass, with why.
type verdict struct {
	Block string `json:"block,omitempty"`
	Pass  string `json:"pass,omitempty"`
}

func (v verdict) reply() (Reply, error) {
	data, err := json.Marshal(v)
	return Reply{Text: string(data)}, err
}

func init() {
	register(Command{
		Name:    "hook stop",
		Class:   batch,
		Usage:   "hook stop [--agent-transcript PATH] [--waiting] [--repo OWNER/NAME]",
		Group:   "Hooks",
		Summary: "hold a box to a PR or supersede for each issue it took",
		Details: "answer the plugin's Stop (or, with --agent-transcript, SubagentStop) as JSON: block, naming each, while any issue this box took is open with neither an open PR from its branch with auto-merge on nor a supersede; else pass, with why. The issues are every one se issue pull --take recorded, or for a sub-agent the leaf its prompt names. An interactive session, and a box waiting on background work (--waiting), always pass. It refuses at most refusals times in a row (spec/stop.yaml); a prompt from a person resets the count (se hook prompt). A check that cannot judge lets the turn end and logs why in .se/.runtime/logs/stop.log.",
		Run: func(c *Call) (Reply, error) {
			fs, src, _ := issueFlags(c, "hook stop")
			transcript := fs.String("agent-transcript", "", "the sub-agent's transcript `PATH`: the stop is a SubagentStop")
			waiting := fs.Bool("waiting", false, "the session has background work or a wake-up that brings it back")
			if err := c.Parse(fs); err != nil {
				return Reply{}, err
			}
			if !c.isBox() {
				return verdict{Pass: "an interactive session is never refused"}.reply()
			}
			if *waiting {
				return verdict{Pass: "the box waits on background work, which wakes it again"}.reply()
			}
			b := readBox(c)
			taken := b.Issues
			if *transcript != "" {
				taken = nil
				data, err := c.Disk.ReadFile(*transcript)
				if err != nil {
					stopLog(c, fmt.Sprintf("let a sub-agent end unjudged: reading its transcript: %v", err))
					return verdict{Pass: "the check is broken: " + oneLine(err)}.reply()
				}
				if m := leafPrompt.FindSubmatch(data); m != nil {
					n, _ := strconv.Atoi(string(m[1]))
					taken = []int{n}
				}
			}
			if len(taken) == 0 {
				return verdict{Pass: "no se issue was taken here"}.reply()
			}
			// An issue refused up to the cap is let go; the rest are judged.
			limit := refusals(c)
			var judge []int
			for _, n := range taken {
				if b.Refused[n] >= limit {
					stopLog(c, fmt.Sprintf("let the box end with #%d unclosed: refused %d times in a row, the cap in %s", n, b.Refused[n], StopPath))
					continue
				}
				judge = append(judge, n)
			}
			if len(judge) == 0 {
				return verdict{Pass: fmt.Sprintf("refused %d times in a row, the cap", limit)}.reply()
			}
			s, err := src()
			if err != nil {
				stopLog(c, fmt.Sprintf("let the box end unjudged on %s: %s", numbers(judge), oneLine(err)))
				return verdict{Pass: "the check is broken: " + oneLine(err)}.reply()
			}
			var whys []string
			var open []int
			for _, n := range judge {
				why, err := s.Unclosed(n)
				if err != nil {
					stopLog(c, fmt.Sprintf("let the box end unjudged on #%d: %s", n, oneLine(err)))
					return verdict{Pass: "the check is broken: " + oneLine(err)}.reply()
				}
				if why == "" {
					delete(b.Refused, n)
					continue
				}
				b.Refused[n]++
				whys = append(whys, why)
				open = append(open, n)
			}
			if len(open) == 0 {
				_ = writeBox(c, b)
				return verdict{Pass: fmt.Sprintf("%s: each is closed, or its PR has auto-merge on", numbers(judge))}.reply()
			}
			if err := writeBox(c, b); err != nil {
				// A count that cannot be kept would refuse without end.
				stopLog(c, fmt.Sprintf("let the box end on %s: keeping the count: %s", numbers(open), oneLine(err)))
				return verdict{Pass: "the check is broken: " + oneLine(err)}.reply()
			}
			most := 0
			for _, n := range open {
				most = max(most, b.Refused[n])
			}
			return verdict{Block: fmt.Sprintf("A box that takes an issue closes it. %s (Refusal %d of %d in a row.)", strings.Join(whys, " "), most, limit)}.reply()
		},
	})
	register(Command{
		Name:    "hook prompt",
		Class:   interactive,
		Usage:   "hook prompt",
		Group:   "Hooks",
		Summary: "a person prompted: reset the Stop hook's refusals",
		Details: "a prompt from a person: reset how often in a row se hook stop has refused, so the cap counts afresh.",
		Run: func(c *Call) (Reply, error) {
			if err := c.Parse(c.Flags("hook prompt")); err != nil {
				return Reply{}, err
			}
			b := readBox(c)
			if len(b.Refused) == 0 {
				return Reply{}, nil
			}
			b.Refused = nil
			return Reply{}, writeBox(c, b)
		},
	})
}
