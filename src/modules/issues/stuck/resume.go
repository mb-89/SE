package stuck

import (
	"encoding/json"
	"fmt"
	"slices"

	"github.com/mb-89/SE/src/index"
	"github.com/mb-89/SE/src/lib/rest"
)

// ResumeNote is the comment a resume leaves: its mark clears the takeovers
// before it.
const ResumeNote = "<!-- se:resume -->\nResumed by a person: back in the queue, its takeover count reset, no longer final."

// Resumed is what se issue resume answers as data.
type Resumed struct {
	Number  int  `json:"number"`
	Resumed bool `json:"resumed"`
}

// issue is the part of GitHub's issue object a resume reads.
type issue struct {
	Number      int              `json:"number"`
	Title       string           `json:"title"`
	State       string           `json:"state"`
	URL         string           `json:"html_url"`
	PullRequest *json.RawMessage `json:"pull_request"`
	Labels      []label          `json:"labels"`
}

type label struct {
	Name string `json:"name"`
}

func (i issue) labelled(name string) bool { return slices.Contains(i.Labels, label{name}) }

var resumeCommand = index.Command(index.CommandDecl{
	Name:    "issue resume",
	Usage:   "issue resume N [--json] [--repo OWNER/NAME]",
	Summary: "for a person: put issue N back in the queue",
	Help:    "for a person: take issue N off se-person and put it back in the queue, its takeover count reset.",
	Group:   "Issues",
	Session: true,
	Class:   index.Batch,
	Flags:   []index.Flag{{Name: "repo", Default: "", Help: "the repository as `OWNER/NAME` (default: the workspace's origin)"}},
	Words:   index.Number,
	JSON:    true,
}, func(_ struct{}, args index.Args) (index.Result, error) {
	if repo := args.String("repo"); repo != "" {
		return resume(repo, args.Number), nil
	}
	return index.Result{Requests: []index.Request{origin.Of("")}, Then: func(answers []any) (index.Result, error) {
		return resume(origin.Answer(answers[0]), args.Number), nil
	}}, nil
})

// resume gives issue n of repo back to the boxes: it records a resume, which
// resets its takeover count, then takes off the se-final label and the
// se-person one, so it gets one more attempt. A claim that is still stale is
// taken over by the next box. The resume is recorded before the labels go,
// so an issue back in the queue never keeps its old takeover count.
func resume(repo string, n int) index.Result {
	base := fmt.Sprintf("repos/%s/issues/%d", repo, n)
	return index.Result{Requests: []index.Request{get.Of(rest.Get{Path: base})}, Then: func(answers []any) (index.Result, error) {
		var i issue
		if err := json.Unmarshal(get.Answer(answers[0]), &i); err != nil {
			return index.Result{}, fmt.Errorf("reading #%d: %w", n, err)
		}
		if i.PullRequest != nil || i.State != "open" || !i.labelled(PersonLabel) {
			return index.Result{}, fmt.Errorf("#%d is not an open issue waiting on a person (labelled %s)", n, PersonLabel)
		}
		writes := []index.Request{send.Of(rest.Send{Method: "POST", Path: base + "/comments", Fields: []rest.Field{rest.F("body", ResumeNote)}})}
		for _, l := range []string{FinalLabel, PersonLabel} {
			if i.labelled(l) {
				writes = append(writes, send.Of(rest.Send{Method: "DELETE", Path: base + "/labels/" + l}))
			}
		}
		return index.Result{Requests: writes, Then: func([]any) (index.Result, error) {
			return index.Result{
				Text: fmt.Sprintf("Resumed #%d %s: back in the queue, its takeover count reset.\n%s", i.Number, i.Title, i.URL),
				Data: Resumed{i.Number, true},
			}, nil
		}}, nil
	}}
}
