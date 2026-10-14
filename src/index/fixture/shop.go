package fixture

import (
	"fmt"

	"github.com/mb-89/SE/src/index"
)

// Shelf is a fixture I/O module holding stock: its verb take takes one of a
// thing out and answers how many are left, and fails where none is.
func Shelf(stock map[string]int) *index.Module {
	return index.Declare("fixtures/shelf", "Holds things, counted.",
		index.IO(),
		index.Verb("take", "Takes one of a thing out, and answers how many are left.", func(thing string) (int, error) {
			if stock[thing] == 0 {
				return 0, fmt.Errorf("no %s left", thing)
			}
			stock[thing]--
			return stock[thing], nil
		}),
	)
}

// take is the shopper's request port, which the wiring binds to a shelf's take.
var take = index.Ask[string, int]("take", "Takes a thing off the shelf.")

// Took is what the shopper's take command answers as data.
type Took struct {
	Thing string `json:"thing"`
	Left  int    `json:"left"`
}

// Shopper is a fixture compute module whose command takes a thing off the
// shelf through its request port alone, and says how many are left.
var Shopper = index.Declare("fixtures/shopper", "Takes things off a shelf.",
	take,
	index.Command(index.CommandDecl{
		Name: "shop take", Usage: "shop take THING [--json]", Summary: "Take a thing.", Help: "Takes one of the thing off the shelf, and says how many are left.",
		Group: "Fixtures", Class: index.Batch, Words: index.AnyWords, JSON: true,
	}, func(_ struct{}, args index.Args) (index.Result, error) {
		if len(args.Words) != 1 {
			return index.Result{}, fmt.Errorf("shop take takes one thing")
		}
		thing := args.Words[0]
		return index.Result{Requests: []index.Request{take.Of(thing)}, Then: func(answers []any) (index.Result, error) {
			left := take.Answer(answers[0])
			return index.Result{Text: fmt.Sprintf("took a %s, %d left", thing, left), Data: Took{thing, left}}, nil
		}}, nil
	}),
)

// ShopWiring binds the shopper to the shelf.
const ShopWiring = `
instances:
  fixtures/shelf: {module: fixtures/shelf}
  fixtures/shopper: {module: fixtures/shopper}
wires:
  fixtures/shopper.take: fixtures/shelf.take
`
