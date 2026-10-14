// Package fixture is a module the index core and the fake index are tested
// with. It is no real module: nothing but tests imports it.
package fixture

import (
	"fmt"
	"strings"

	"github.com/mb-89/SE/src/internal/index"
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

// Module is the tally: it sums the numbers it reads, scaled, and takes notes.
var Module = index.Declare("tally", "Sums numbers and takes notes.",
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
		Button:  false,
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

func init() { index.Register(Module) }
