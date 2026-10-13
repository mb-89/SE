package issues

// Reports is the labels of the issues whose se-person label means a report
// waits for the owner; the report source lists those, this one the rest.
var Reports = []string{RetroLabel, OverhaulLabel, ReviewLabel}

func init() {
	RegisterPending(PendingSource{
		Name: "waiting on a person",
		List: func(o Open) ([]Pending, error) {
			var out []Pending
			for _, w := range o.Waiting {
				if !report(o, w.Number) {
					out = append(out, Pending{Number: w.Number, Title: w.Title, URL: w.URL, Reason: w.Reason, Holds: w.Blocks})
				}
			}
			return out, nil
		},
	})
}

// report says whether open issue n carries one of the report labels.
func report(o Open, n int) bool {
	for _, l := range Reports {
		if o.Labelled(n, l) {
			return true
		}
	}
	return false
}
