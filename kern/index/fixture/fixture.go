// Package fixture holds the components the index and the fake core are
// tested with. They are no real components: nothing but tests imports them.
package fixture

import (
	"fmt"
	"strings"

	"github.com/mb-89/kern/index"
)

type totalIn struct {
	Numbers []int `index:"numbers"`
	Scale   int   `index:"config/scale"`
}

type noteIn struct {
	Numbers []int `index:"numbers"`
}

// Note is the last note the note command took.
var Note = index.Output("note", "", "The last note taken.")

// Tally sums the numbers it reads, scaled, and takes notes.
var Tally = index.Declare("tally", "Sums numbers and takes notes.",
	index.Config("scale", 1, "What the sum is multiplied by."),
	index.Derived("total", 0, "The sum of the numbers, scaled.", func(in totalIn) (int, error) {
		sum := 0
		for _, n := range in.Numbers {
			sum += n
		}
		return sum * in.Scale, nil
	}),
	Note,
	index.Command(index.CommandDecl{
		Name:    "tally note",
		Usage:   "tally note WORDS...",
		Summary: "Take a note.",
		Help:    "Keeps the words as the last note, and says how many numbers stand.",
		Group:   "Fixtures",
		Session: true,
		Class:   index.Batch,
	}, func(in noteIn, args []string) (index.Result, error) {
		if len(args) == 0 {
			return index.Result{}, fmt.Errorf("tally note takes the words to keep")
		}
		note := strings.Join(args, " ")
		return index.Result{
			Text:   fmt.Sprintf("noted %q beside %d numbers", note, len(in.Numbers)),
			Writes: []index.Write{Note.Set(note)},
		}, nil
	}),
)

func init() { index.Register(Tally) }

// Ledger is an I/O component whose outside thing is the list of lines it is
// handed: its verb append adds a line and answers how many lines stand, and
// refuses an empty one.
func Ledger(lines *[]string) *index.Component {
	return index.Declare("ledger", "Keeps the lines it is asked to append.",
		index.IO(),
		index.Verb("append", "Appends a line and answers how many lines stand.", func(line string) (int, error) {
			if line == "" {
				return 0, fmt.Errorf("the ledger takes no empty line")
			}
			*lines = append(*lines, line)
			return len(*lines), nil
		}),
	)
}

// Post is the clerk's request port to a ledger's append.
var Post = index.Request[string, int]("post", "Appends a line to a ledger.")

// Filed is the clerk's last entry and where it stands.
var Filed = index.Output("filed", "", "The last entry filed, with its number.")

// Clerk is a compute component that acts on the outside through its request
// port: clerk file posts each word as its own line, then commits where the last one stands.
var Clerk = index.Declare("clerk", "Files words in a ledger.",
	Post, Filed,
	index.Command(index.CommandDecl{
		Name:    "clerk file",
		Usage:   "clerk file WORDS...",
		Summary: "File each word as a line.",
		Help:    "Posts each word to the ledger in order; a refused post stops the rest.",
		Group:   "Fixtures",
		Class:   index.Batch,
	}, func(_ struct{}, args []string) (index.Result, error) {
		asks := make([]index.Ask, len(args))
		for i, a := range args {
			asks[i] = Post.Ask(a)
		}
		return index.Result{
			Text:     fmt.Sprintf("filing %d words", len(args)),
			Requests: asks,
			Then: func(answers []any) (index.Result, error) {
				if len(answers) == 0 {
					return index.Result{Text: "nothing filed"}, nil
				}
				entry := fmt.Sprintf("%s as line %d", args[len(args)-1], Post.Answer(answers[len(answers)-1]))
				return index.Result{Text: "filed " + entry, Writes: []index.Write{Filed.Set(entry)}}, nil
			},
		}, nil
	}),
)
