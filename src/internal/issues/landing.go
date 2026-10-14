package issues

import (
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
	"time"

	"github.com/mb-89/SE/src/internal/battery"
	"gopkg.in/yaml.v3"
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

// Questions reads the landing questions from the checkout dir.
func Questions(dir string) ([]Question, error) {
	path := filepath.Join(dir, QuestionsFile)
	data, err := os.ReadFile(path)
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

// ReadAnswers reads an answers file: YAML, one answer per question key.
func ReadAnswers(path string) (map[string]string, error) {
	data, err := os.ReadFile(path)
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
	// Commits counts the branch's own commits, MainMerges its merges of main.
	Commits    int `yaml:"commits"`
	Takeovers  int `yaml:"takeovers"`
	MainMerges int `yaml:"main_merges"`
	// BatteryMs is how long the battery this land ran took, Slowest its
	// slowest tests, and Overruns each budget it went over; empty where the
	// check left no profile.
	BatteryMs int64    `yaml:"battery_ms,omitempty"`
	Slowest   []string `yaml:"slowest_tests,omitempty"`
	Overruns  []string `yaml:"budget_overruns,omitempty"`
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
	fmt.Fprintf(&b, "\n### Facts\n- claim to landing: %s\n- landed: %s\n- commits: %d\n- takeovers: %d\n- main merges: %d\n",
		took, f.Landed.UTC().Format(time.RFC3339), f.Commits, f.Takeovers, f.MainMerges)
	if f.BatteryMs > 0 {
		fmt.Fprintf(&b, "- battery: %dms\n", f.BatteryMs)
		for _, o := range f.Overruns {
			fmt.Fprintf(&b, "- **over budget:** %s\n", o)
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
	if !strings.Contains(body, landingMark) {
		return Landed{}, false, nil
	}
	_, rest, found := strings.Cut(body, landingBlock+"\n```yaml\n")
	if !found {
		return Landed{}, true, errors.New("the landing comment carries no machine-readable block")
	}
	// The block's lines are YAML at the top level or indented below it, so
	// the fence that closes it is the first line that is only a fence.
	block, _, found := strings.Cut("\n"+rest, "\n```")
	if !found {
		return Landed{}, true, errors.New("the landing comment's block is not closed")
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

// facts reads what land knows of issue n's work in dir, from its comments,
// its branch's history and GitHub's record of the branch's creation.
func (s Source) facts(dir string, n int, comments []comment) (Facts, error) {
	f := Facts{Landed: s.now().UTC().Truncate(time.Second), Takeovers: marksOf(comments).takeovers}
	profile, profiled, err := battery.Load(dir)
	if err != nil {
		return Facts{}, err
	}
	if profiled {
		f.BatteryMs, f.Overruns = profile.TotalMs, profile.Overruns
		for _, t := range profile.Slowest {
			f.Slowest = append(f.Slowest, t.String())
		}
	}
	count := func(args ...string) (int, error) {
		out, err := s.git(dir, append([]string{"rev-list", "--count"}, args...)...)
		if err != nil {
			return 0, err
		}
		return strconv.Atoi(out)
	}
	// The branch's own work is what main does not hold yet.
	if _, err := s.git(dir, "fetch", "-q", "origin", "main"); err != nil {
		return Facts{}, err
	}
	if f.Commits, err = count("--no-merges", "origin/main..HEAD"); err != nil {
		return Facts{}, err
	}
	if f.MainMerges, err = count("--merges", "origin/main..HEAD"); err != nil {
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
	comments, err := api[comment](s, fmt.Sprintf("repos/%s/issues/%d/comments?per_page=100", s.Repo, n), true)
	if err != nil {
		return err
	}
	f, err := s.facts(dir, n, comments)
	if err != nil {
		return err
	}
	body, err := Landed{Issue: n, Answers: answers, Facts: f}.Comment(qs)
	if err != nil {
		return err
	}
	for _, c := range comments {
		if strings.Contains(c.Body, landingMark) {
			_, err := s.GH("api", "-X", "PATCH", "-f", "body="+body, fmt.Sprintf("repos/%s/issues/comments/%d", s.Repo, c.ID))
			if err != nil {
				return fmt.Errorf("updating #%d's landing answers: %w", n, err)
			}
			return nil
		}
	}
	if _, err := s.GH("api", "-X", "POST", "-f", "body="+body, fmt.Sprintf("repos/%s/issues/%d/comments", s.Repo, n)); err != nil {
		return fmt.Errorf("posting #%d's landing answers: %w", n, err)
	}
	return nil
}
