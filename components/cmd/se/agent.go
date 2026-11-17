package main

import (
	"bytes"
	"encoding/json"
	"flag"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"runtime"
	"strings"

	"kern/cli"
)

// marketplaceFile is what makes a folder an SE to load: Claude Code's
// marketplace of the clone, whose name is the marketplace se.
var marketplaceFile = filepath.Join(".claude-plugin", "marketplace.json")

// agentVerb is `se agent`: it starts the SE agent in the caller's working
// directory with SE loaded from its clone, the home. It starts no core: the
// plugin's start hook does.
var agentVerb = cli.Verb{
	Name: "agent",
	Args: "[--host claude|copilot] [--home DIR] [-- <arguments>]",
	Doc: "start the SE agent in this folder with SE loaded from its clone: Claude Code reads the clone as its marketplace se; " +
		"Copilot CLI loads it for this run only, so a later `copilot --agent se` finds no SE",
	Exit: "the host's exit code; 1 where it cannot start the host",
	Flags: func(fs *flag.FlagSet) {
		fs.String("host", "claude", "the host to start: claude (Claude Code) or copilot (Copilot CLI)")
		fs.String("home", "", "SE's clone to load; by default $RUNME_ROOT, else the folder of Claude Code's directory marketplace se")
	},
	Run: runAgent,
}

// bareVerb is a bare `se`: the agent at a terminal, the help elsewhere
// (bareHelps).
var bareVerb = cli.Verb{
	Doc: "se agent at a terminal; prints this help with no terminal, inside Claude Code (CLAUDECODE) or on a cloud box",
	Run: runBare,
}

// market is one entry of `claude plugin marketplace list --json`.
type market struct {
	Name   string `json:"name"`
	Source string `json:"source"`
	Path   string `json:"path"`
	Repo   string `json:"repo"`
	URL    string `json:"url"`
}

// where is the market's source as a person reads it: its path, its
// repository or its URL, else its kind.
func (m market) where() string {
	for _, s := range []string{m.Path, m.Repo, m.URL, m.Source} {
		if s != "" {
			return s
		}
	}
	return "an unknown source"
}

// plugin is one entry of `claude plugin list --json`.
type plugin struct {
	ID             string `json:"id"`
	Enabled        bool   `json:"enabled"`
	ReadFromFolder string `json:"readFromFolder"`
	InstallPath    string `json:"installPath"`
}

// claudeJSON runs `claude <args>` and decodes its stdout into v; its stderr
// goes to stderr.
func claudeJSON(claude string, stderr io.Writer, v any, args ...string) error {
	cmd := exec.Command(claude, args...)
	cmd.Stderr = stderr
	out, err := cmd.Output()
	if err != nil {
		return fmt.Errorf("claude %s: %v", strings.Join(args, " "), err)
	}
	if err := json.Unmarshal(bytes.TrimSpace(out), v); err != nil {
		return fmt.Errorf("claude %s: %v", strings.Join(args, " "), err)
	}
	return nil
}

// markets reads Claude Code's marketplaces once; none where claude is not
// found or does not answer.
type markets struct {
	claude string
	stderr io.Writer
	read   bool
	list   []market
	err    error
}

func (m *markets) get() ([]market, error) {
	if !m.read {
		m.read = true
		if m.claude == "" {
			m.err = fmt.Errorf("no claude on PATH")
		} else {
			m.err = claudeJSON(m.claude, m.stderr, &m.list, "plugin", "marketplace", "list", "--json")
		}
	}
	return m.list, m.err
}

// named is the market of that name.
func named(list []market, name string) (market, bool) {
	for _, m := range list {
		if m.Name == name {
			return m, true
		}
	}
	return market{}, false
}

// isSE reports whether dir holds an SE to load.
func isSE(dir string) bool {
	_, err := os.Stat(filepath.Join(dir, marketplaceFile))
	return err == nil
}

func absClean(dir string) string {
	if abs, err := filepath.Abs(dir); err == nil {
		return filepath.Clean(abs)
	}
	return filepath.Clean(dir)
}

// samePath compares two folders absolute and cleaned, without case on
// Windows.
func samePath(a, b string) bool {
	a, b = absClean(a), absClean(b)
	if runtime.GOOS == "windows" {
		return strings.EqualFold(a, b)
	}
	if a == b {
		return true
	}
	ra, errA := filepath.EvalSymlinks(a)
	rb, errB := filepath.EvalSymlinks(b)
	return errA == nil && errB == nil && ra == rb
}

// findHome is the SE to load: given (--home), else RUNME_ROOT where it holds
// an SE, else the path of the directory marketplace se. It answers "" where
// none is found, and a refusal where given holds no SE.
func findHome(given string, lookup func(string) (string, bool), ms *markets) (home, refusal string) {
	if given != "" {
		if !isSE(given) {
			return "", fmt.Sprintf("--home %s holds no SE (no %s): name SE's clone, or run SE's RUNME", given, filepath.ToSlash(marketplaceFile))
		}
		return absClean(given), ""
	}
	if root, ok := lookup("RUNME_ROOT"); ok && root != "" && isSE(root) {
		return absClean(root), ""
	}
	list, err := ms.get()
	if err != nil {
		return "", ""
	}
	if m, ok := named(list, "se"); ok && m.Source == "directory" && m.Path != "" {
		if !isSE(m.Path) {
			return "", fmt.Sprintf("Claude Code's marketplace se, %s, holds no SE (no %s): run SE's RUNME, or pass --home DIR", m.Path, filepath.ToSlash(marketplaceFile))
		}
		return absClean(m.Path), ""
	}
	return "", ""
}

func runAgent(c *cli.Call) int {
	host := c.String("host")
	if host != "claude" && host != "copilot" {
		fmt.Fprintf(c.Stderr, "se agent: --host %q is neither claude nor copilot\n", host)
		return 2
	}
	claude, _ := exec.LookPath("claude")
	if host == "claude" && claude == "" {
		fmt.Fprintln(c.Stderr, "se agent: Claude Code (claude) is not on PATH: run SE's RUNME, which installs it")
		return 1
	}
	copilot := ""
	if host == "copilot" {
		var err error
		if copilot, err = exec.LookPath("copilot"); err != nil {
			fmt.Fprintln(c.Stderr, "se agent: Copilot CLI (copilot) is not on PATH: install it, or start Claude Code with se agent")
			return 1
		}
	}
	ms := &markets{claude: claude, stderr: c.Stderr}
	home, refusal := findHome(c.String("home"), os.LookupEnv, ms)
	if refusal != "" {
		fmt.Fprintln(c.Stderr, "se agent: "+refusal)
		return 2
	}
	if home == "" {
		fmt.Fprintln(c.Stderr, "se agent: found no SE to load: run SE's RUNME, or name SE's clone with --home DIR")
		return 2
	}
	if host == "copilot" {
		return start(copilot, append([]string{"--plugin-dir=" + home, "--agent", "se"}, c.Args()...), c.Stderr)
	}
	if code := register(claude, home, ms, c.Stderr); code >= 0 {
		return code
	}
	return start(claude, append([]string{"--agent", "se:se"}, c.Args()...), c.Stderr)
}

// register makes Claude Code read the plugin se@se from home, as its
// directory marketplace se, and answers -1 where it does, else the exit
// code: it changes nothing where Claude Code reads another se.
func register(claude, home string, ms *markets, stderr io.Writer) int {
	list, err := ms.get()
	if err != nil {
		fmt.Fprintf(stderr, "se agent: %v\n", err)
		return 1
	}
	var plugins []plugin
	if err := claudeJSON(claude, stderr, &plugins, "plugin", "list", "--json"); err != nil {
		fmt.Fprintf(stderr, "se agent: %v\n", err)
		return 1
	}
	m, has := named(list, "se")
	if has && !(m.Source == "directory" && samePath(m.Path, home)) {
		fmt.Fprintf(stderr, "se: Claude Code already reads the marketplace se from %s; to load SE from %s, run: "+
			"claude plugin marketplace remove se (it also uninstalls se@se), then run RUNME again\n", m.where(), home)
		return 1
	}
	var mine *plugin
	for i, p := range plugins {
		if p.ID == "se@se" {
			mine = &plugins[i]
		} else if strings.HasPrefix(p.ID, "se@") {
			at := p.ReadFromFolder
			if at == "" {
				at = p.InstallPath
			}
			if at == "" {
				at = p.ID
			}
			fmt.Fprintf(stderr, "se: Claude Code also loads a plugin se from %s; remove it, then run RUNME again\n", at)
			return 1
		}
	}
	var args []string
	switch {
	case !has:
		args = []string{"plugin", "install", "se", "--marketplace", home}
	case mine == nil:
		args = []string{"plugin", "install", "se@se"}
	case !mine.Enabled:
		args = []string{"plugin", "enable", "se@se"}
	default:
		return -1
	}
	cmd := exec.Command(claude, args...)
	cmd.Stdout, cmd.Stderr = stderr, stderr
	if err := cmd.Run(); err != nil {
		if ee, ok := err.(*exec.ExitError); ok && ee.ExitCode() > 0 {
			return ee.ExitCode()
		}
		fmt.Fprintf(stderr, "se agent: claude %s: %v\n", strings.Join(args, " "), err)
		return 1
	}
	return -1
}

// mark is one cloud mark of the host table's SE_CLOUD_MARKS line: a
// variable set and not empty, or equal to value in any case.
type mark struct {
	variable string
	value    *string
}

var cloudMarksLine = regexp.MustCompile(`(?m)^SE_CLOUD_MARKS=\(([^)]*)\)\r?$`)

// cloudMarks reads the cloud marks of the SE at home, from the
// SE_CLOUD_MARKS line of its scripts/hosts.sh, as scripts/hosts.py reads it:
// each entry `<cloud>:<variable>` or `<cloud>:<variable>=<value>`.
func cloudMarks(home string) []mark {
	data, err := os.ReadFile(filepath.Join(home, "scripts", "hosts.sh"))
	if err != nil {
		return nil
	}
	found := cloudMarksLine.FindSubmatch(data)
	if found == nil {
		return nil
	}
	var marks []mark
	for _, entry := range strings.Fields(string(found[1])) {
		_, m, _ := strings.Cut(entry, ":")
		variable, value, equals := strings.Cut(m, "=")
		mk := mark{variable: variable}
		if equals {
			mk.value = &value
		}
		marks = append(marks, mk)
	}
	return marks
}

// clouded reports whether lookup carries one of marks.
func clouded(marks []mark, lookup func(string) (string, bool)) bool {
	for _, m := range marks {
		given, _ := lookup(m.variable)
		if m.value != nil && strings.EqualFold(given, *m.value) || m.value == nil && given != "" {
			return true
		}
	}
	return false
}

// bareHelps reports whether a bare se prints the help rather than start the
// agent, the first check that holds winning: stdin or stdout is no terminal;
// CLAUDECODE is set; the SE it would load is found (home, only called now)
// and one of its cloud marks is set.
func bareHelps(lookup func(string) (string, bool), terminal bool, home func() string) bool {
	if !terminal {
		return true
	}
	if _, ok := lookup("CLAUDECODE"); ok {
		return true
	}
	h := home()
	return h != "" && clouded(cloudMarks(h), lookup)
}

func runBare(c *cli.Call) int {
	home := func() string {
		claude, _ := exec.LookPath("claude")
		h, _ := findHome("", os.LookupEnv, &markets{claude: claude, stderr: io.Discard})
		return h
	}
	if bareHelps(os.LookupEnv, terminal(os.Stdin) && terminal(os.Stdout), home) {
		cli.Help(c.Name, c.Stdout)
		return 0
	}
	return cli.Run(c.Name, []string{"agent"}, c.Stdout, c.Stderr)
}
