package issues

func init() {
	RegisterPending(PendingSource{
		Name: "waiting on a person",
		List: func(o Open) ([]Pending, error) {
			var out []Pending
			for _, w := range o.Waiting {
				out = append(out, Pending{Number: w.Number, Title: w.Title, URL: w.URL, Reason: w.Reason, Holds: w.Blocks})
			}
			return out, nil
		},
	})
}
