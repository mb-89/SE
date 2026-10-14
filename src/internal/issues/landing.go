package issues

import (
	"errors"
	"fmt"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
	"time"

	"github.com/mb-89/SE/src/internal/battery"
	"github.com/mb-89/SE/src/internal/io/disk"
	"gopkg.in/yaml.v3"

	"github.com/mb-89/SE/src/internal/io/github"
)

// QuestionsFile is where the landing questions are written, relative to the
// checkout: the one list both se issue land and the retro read.
const QuestionsFile = "spec/landing.yaml"

// Question is one landing question.
type Question struct {
	Key      string `yaml:"key"`
	Question string `yaml:"question"`
	Hint     string `yaml:"hint"`
}

// Questions reads the landing questions from the checkout dir on d.
func Questions(d disk.Disk, dir string) ([]Question, error) {
	path := filepath.Join(dir, QuestionsFile)
	data, err := d.ReadFile(path)
	if err != nil {
		return nil, fmt.Errorf("the landing questions: %w", err)
	}
	var qs []Question
	if err := yaml.Unmarshal(data, &qs); err != nil {
		return nil, fmt.Errorf("%s: %v", path, err)
	}
	seen := map[string]bool{}
	for _, q := range qs {
		if q.Key == "" || q.Question == "" || seen[q.Key] {
			return nil, fmt.Errorf("%s: each question needs a key of its own and its question; %q does not", path, q.Key)
		}
		seen[q.Key] = true
	}
	if len(qs) == 0 {
		return nil, fmt.Errorf("%s holds no questions", path)
	}
	return qs, nil
}

// ReadAnswers reads an answers file on d: YAML, one answer per question key.
func ReadAnswers(d disk.Disk, path string) (map[string]string, error) {
	data, err := d.ReadFile(path)
	if err != nil {
		return nil, fmt.Errorf("the landing answers: %w", err)
	}
	var a map[string]string
	if err := yaml.Unmarshal(data, &a); err != nil {
		return nil, fmt.Errorf("%s: each key takes its answer as text: %v", path, err)
	}
	return a, nil
}

// answered refuses answers that miss a question, leave one empty, or answer
// one the list does not know; it names every key at fault.
func answered(qs []Question, a map[string]string) error {
	known := map[string]bool{}
	var missing, empty, unknown []string
	for _, q := range qs {
		known[q.Key] = true
		if got, ok := a[q.Key]; !ok {
			missing = append(missing, q.Key)
		} else if strings.TrimSpace(got) == "" {
			empty = append(empty, q.Key)
		}
	}
	for k := range a {
		if !known[k] {
			unknown = append(unknown, k)
		}
	}
	sort.Strings(unknown)
	var why []string
	if len(missing) > 0 {
		why = append(why, "missing: "+strings.Join(missing, ", "))
	}
	if len(empty) > 0 {
		why = append(why, "empty: "+strings.Join(empty, ", "))
	}
	if len(unknown) > 0 {
		why = append(why, "not in "+QuestionsFile+": "+strings.Join(unknown, ", "))
	}
	if why == nil {
		return nil
	}
	return fmt.Errorf("land takes an answer to every question in %s (\"none\" is an answer), so nothing was pushed; %s", QuestionsFile, strings.Join(why, "; "))
}

// Facts are what land knows of an issue's work without asking.
type Facts struct {
	// Claimed is when the issue's branch was created; zero where GitHub keeps
	// no record of it. Minutes is the time from it to Landed.
	Claimed time.Time `yaml:"claimed,omitempty"`
	Landed  time.Time `yaml:"landed"`
	Minutes int       `yaml:"minutes,omitempty"`
	// Into is the branch a leaf landed into, its manifest's issue-<m>;
	// empty where it landed as a PR into main.
	Into string `yaml:"into,omitempty"`
	// Commits counts the branch's own commits, MainMerges its merges of main.
	Commits    int `yaml:"commits"`
	Takeovers  int `yaml:"takeovers"`
	MainMerges int `yaml:"main_merges"`
	// Requests counts the GitHub requests the se commands run in the
	// checkout made (RequestsFile), this land's so far included.
	Requests int `yaml:"requests,omitempty"`
	// RateLimits counts the requests GitHub refused those commands for a
	// rate limit (RateLimitsFile), this land's so far included, and
	// RateLimitWaitS the seconds se waited for the resets all told.
	RateLimits     int `yaml:"rate_limits,omitempty"`
	RateLimitWaitS int `yaml:"rate_limit_wait_s,omitempty"`
	// BatteryMs is how long the battery this land ran took, Slowest its
	// slowest Go tests, SlowestPlugin its slowest plugin tests, Overruns each
	// budget it went over, and Unbudgeted each step it ran with no budget;
	// empty where the check left no profile.
	BatteryMs     int64    `yaml:"battery_ms,omitempty"`
	Slowest       []string `yaml:"slowest_tests,omitempty"`
	SlowestPlugin []string `yaml:"slowest_plugin_tests,omitempty"`
	Overruns      []string `yaml:"budget_overruns,omitempty"`
	Unbudgeted    []string `yaml:"budget_missing,omitempty"`
}

// Landed is the record a landing leaves on its issue.
type Landed struct {
	Issue   int
	Answers map[string]string
	Facts   Facts
}

// landingMark opens the landing comment; landingBlock stands above its
// machine-readable block.
const (
	landingMark  = "<!-- se:landing -->"
	landingBlock = "<!-- se:landing-yaml -->"
)

// record is the machine-readable block's shape; answers keep the order of
// the questions.
type record struct {
	Issue   int       `yaml:"issue"`
	Answers yaml.Node `yaml:"answers"`
	Facts   Facts     `yaml:"facts"`
}

// Comment is the landing's comment: the answers under their questions, the
// facts, and the same in a fenced YAML block under a fixed marker.
func (l Landed) Comment(qs []Question) (string, error) {
	var b strings.Builder
	fmt.Fprintf(&b, "%s\n## Landing answers\n", landingMark)
	answers := yaml.Node{Kind: yaml.MappingNode}
	for _, q := range qs {
		got := strings.TrimSpace(l.Answers[q.Key])
		fmt.Fprintf(&b, "\n**%s** (`%s`)\n%s\n", q.Question, q.Key, got)
		answers.Content = append(answers.Content,
			&yaml.Node{Kind: yaml.ScalarNode, Value: q.Key},
			&yaml.Node{Kind: yaml.ScalarNode, Tag: "!!str", Value: got})
	}
	f := l.Facts
	took := "unknown: GitHub keeps no record of the claim"
	if !f.Claimed.IsZero() {
		took = fmt.Sprintf("%s (claimed %s)", span(f.Minutes), f.Claimed.UTC().Format(time.RFC3339))
	}
	fmt.Fprintf(&b, "\n### Facts\n- claim to landing: %s\n- landed: %s\n", took, f.Landed.UTC().Format(time.RFC3339))
	if f.Into != "" {
		fmt.Fprintf(&b, "- landed into: %s\n", f.Into)
	}
	fmt.Fprintf(&b, "- commits: %d\n- takeovers: %d\n- main merges: %d\n", f.Commits, f.Takeovers, f.MainMerges)
	if f.Requests > 0 {
		fmt.Fprintf(&b, "- GitHub requests: %d\n", f.Requests)
	}
	if f.RateLimits > 0 {
		fmt.Fprintf(&b, "- GitHub rate-limit refusals: %d, waited %s for the reset\n", f.RateLimits, time.Duration(f.RateLimitWaitS)*time.Second)
	}
	if f.BatteryMs > 0 {
		fmt.Fprintf(&b, "- battery: %dms\n", f.BatteryMs)
		for _, o := range f.Overruns {
			fmt.Fprintf(&b, "- **over budget:** %s\n", o)
		}
		for _, u := range f.Unbudgeted {
			fmt.Fprintf(&b, "- **no budget:** %s\n", u)
		}
	}
	data, err := yaml.Marshal(record{Issue: l.Issue, Answers: answers, Facts: f})
	if err != nil {
		return "", err
	}
	fmt.Fprintf(&b, "\n%s\n```yaml\n%s```\n", landingBlock, data)
	return b.String(), nil
}

// span reads minutes the way a person counts them: 45m, 2h05m, 3d 4h.
func span(minutes int) string {
	switch {
	case minutes < 60:
		return fmt.Sprintf("%dm", minutes)
	case minutes < 24*60:
		return fmt.Sprintf("%dh%02dm", minutes/60, minutes%60)
	}
	return fmt.Sprintf("%dd %dh", minutes/(24*60), minutes%(24*60)/60)
}

// ParseLanding reads a landing comment's machine-readable block back; ok is
// false for a comment that is no landing.
func ParseLanding(body string) (l Landed, ok bool, err error) {
	block, ok, err := landingYAML(body)
	if !ok || err != nil {
		return Landed{}, ok, err
	}
	var r struct {
		Issue   int               `yaml:"issue"`
		Answers map[string]string `yaml:"answers"`
		Facts   Facts             `yaml:"facts"`
	}
	if err := yaml.Unmarshal([]byte(block), &r); err != nil {
		return Landed{}, true, fmt.Errorf("the landing comment's block: %v", err)
	}
	return Landed{Issue: r.Issue, Answers: r.Answers, Facts: r.Facts}, true, nil
}

// landingYAML is a landing comment's machine-readable block; ok is false for
// a comment that is no landing.
func landingYAML(body string) (block string, ok bool, err error) {
	if !strings.Contains(body, landingMark) {
		return "", false, nil
	}
	_, rest, found := strings.Cut(body, landingBlock+"\n```yaml\n")
	if !found {
		return "", true, errors.New("the landing comment carries no machine-readable block")
	}
	// The block's lines are YAML at the top level or indented below it, so
	// the fence that closes it is the first line that is only a fence.
	block, _, found = strings.Cut("\n"+rest, "\n```")
	if !found {
		return "", true, errors.New("the landing comment's block is not closed")
	}
	return block, true, nil
}

// AnswersFile is where the landing answers of issue n stand while it is
// worked, beside the checkout dir and outside it, as the work skill writes
// them: next to the leaf's own worktree (see Worktree), or, where the take
// checked the branch out in dir itself, next to dir.
func AnswersFile(dir string, n int, worktree bool) string {
	if worktree {
		dir = filepath.Join(filepath.Dir(dir), Branch(n))
	}
	return dir + "-landing.yaml"
}

// RestoreAnswers writes the answers the last land of issue n posted on it
// back to the answers file at path, so a takeover brings them up to date
// rather than writing them anew: the box that wrote them first kept them
// outside its checkout, where no other box sees them. A file at path is kept
// as it is. restored is false where it kept one, or no land posted answers.
func (s Source) RestoreAnswers(n int, path string) (restored bool, err error) {
	if there, err := s.Disk.Exists(path); err != nil || there {
		return false, err
	}
	comments, err := api[comment](s, fmt.Sprintf("repos/%s/issues/%d/comments?per_page=100", s.Repo, n), true)
	if err != nil {
		return false, err
	}
	block := ""
	for _, c := range comments {
		got, ok, err := landingYAML(c.Body)
		if err != nil {
			return false, fmt.Errorf("#%d's landing answers: %w", n, err)
		}
		if ok {
			block = got
		}
	}
	if block == "" {
		return false, nil
	}
	text, err := answersFile(n, block)
	if err != nil {
		return false, fmt.Errorf("#%d's landing answers: %w", n, err)
	}
	if err := s.Disk.WriteFile(path, text); err != nil {
		return false, fmt.Errorf("restoring #%d's landing answers: %w", n, err)
	}
	return true, nil
}

// answersFile turns a landing comment's block back into an answers file for
// --answers: its answers in their order, each a block of text.
func answersFile(n int, block string) ([]byte, error) {
	var r struct {
		Answers yaml.Node `yaml:"answers"`
	}
	if err := yaml.Unmarshal([]byte(block), &r); err != nil {
		return nil, fmt.Errorf("the landing comment's block: %v", err)
	}
	a := r.Answers
	if a.Kind != yaml.MappingNode {
		return nil, errors.New("the landing comment's block holds no answers")
	}
	for k := 1; k < len(a.Content); k += 2 {
		a.Content[k].Style = yaml.LiteralStyle
	}
	a.HeadComment = fmt.Sprintf("The answers the last land of #%d posted on it: bring them up to date.", n)
	return yaml.Marshal(&a)
}

// facts reads what land knows of issue n's work in dir, from its comments,
// its branch's history against origin's base (main, or the manifest's branch
// a leaf lands into) and GitHub's record of the branch's creation.
func (s Source) facts(dir string, n int, comments []comment, base string) (Facts, error) {
	f := Facts{Landed: s.now().UTC().Truncate(time.Second), Takeovers: marksOf(comments).takeovers}
	recorded, err := Requests(s.Disk, dir)
	if err != nil {
		return Facts{}, err
	}
	running, _ := github.Metered(s.GitHub)
	f.Requests = recorded + running
	waits, err := RateLimitWaits(s.Disk, dir)
	if err != nil {
		return Facts{}, err
	}
	waits = waits.add(github.RefusedBy(s.GitHub))
	f.RateLimits, f.RateLimitWaitS = waits.Refusals, int(waits.Wait/time.Second)
	profile, profiled, err := battery.Load(s.Disk, dir)
	if err != nil {
		return Facts{}, err
	}
	if profiled {
		f.BatteryMs, f.Overruns, f.Unbudgeted = profile.TotalMs, profile.Overruns, profile.Unbudgeted
		for _, t := range profile.Slowest {
			f.Slowest = append(f.Slowest, t.String())
		}
		for _, t := range profile.SlowestPlugin {
			f.SlowestPlugin = append(f.SlowestPlugin, t.String())
		}
	}
	// The commits of the battery's stamp are no work of the branch's.
	count := func(args ...string) (int, error) {
		out, err := s.git(dir, append([]string{"rev-list", "--count", "--invert-grep", "--fixed-strings", "--grep=" + stampCommit}, args...)...)
		if err != nil {
			return 0, err
		}
		return strconv.Atoi(out)
	}
	// The branch's own work is what its base does not hold yet.
	if base == "main" {
		if _, err := s.git(dir, "fetch", "-q", "origin", "main"); err != nil {
			return Facts{}, err
		}
	} else {
		f.Into = base
	}
	if f.Commits, err = count("--no-merges", "origin/"+base+"..HEAD"); err != nil {
		return Facts{}, err
	}
	if f.MainMerges, err = count("--merges", "origin/"+base+"..HEAD"); err != nil {
		return Facts{}, err
	}
	created, err := api[[]struct {
		Timestamp time.Time `json:"timestamp"`
	}](s, fmt.Sprintf("repos/%s/activity?ref=refs/heads/%s&activity_type=branch_creation&per_page=100", s.Repo, Branch(n)), false)
	if err != nil {
		return Facts{}, err
	}
	for _, a := range created[0] {
		if f.Claimed.IsZero() || a.Timestamp.Before(f.Claimed) {
			f.Claimed = a.Timestamp.UTC()
		}
	}
	if !f.Claimed.IsZero() {
		f.Minutes = int(f.Landed.Sub(f.Claimed).Round(time.Minute) / time.Minute)
	}
	return f, nil
}

// postLanding writes issue n's landing comment, or updates the one an
// earlier land wrote.
func (s Source) postLanding(dir string, n int, qs []Question, answers map[string]string) error {
	comments, f, err := s.factsOf(dir, n, "main")
	if err != nil {
		return err
	}
	return s.post(n, comments, qs, Landed{Issue: n, Answers: answers, Facts: f})
}

// factsOf reads issue n's comments and the facts of its work in dir against
// origin's base.
func (s Source) factsOf(dir string, n int, base string) ([]comment, Facts, error) {
	comments, err := api[comment](s, fmt.Sprintf("repos/%s/issues/%d/comments?per_page=100", s.Repo, n), true)
	if err != nil {
		return nil, Facts{}, err
	}
	f, err := s.facts(dir, n, comments, base)
	return comments, f, err
}

// post writes the landing l on issue n, whose comments are comments, or
// updates the one an earlier land wrote.
func (s Source) post(n int, comments []comment, qs []Question, l Landed) error {
	body, err := l.Comment(qs)
	if err != nil {
		return err
	}
	for _, c := range comments {
		if strings.Contains(c.Body, landingMark) {
			_, err := s.GitHub.Send("PATCH", fmt.Sprintf("repos/%s/issues/comments/%d", s.Repo, c.ID), github.F("body", body))
			if err != nil {
				return fmt.Errorf("updating #%d's landing answers: %w", n, err)
			}
			return nil
		}
	}
	if _, err := s.GitHub.Send("POST", fmt.Sprintf("repos/%s/issues/%d/comments", s.Repo, n), github.F("body", body)); err != nil {
		return fmt.Errorf("posting #%d's landing answers: %w", n, err)
	}
	return nil
}
