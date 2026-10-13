package issues

func init() {
	RegisterPending(PendingSource{
		Name: "report waiting",
		List: func(o Open) ([]Pending, error) {
			var out []Pending
			for _, w := range o.Waiting {
				if report(o, w.Number) {
					out = append(out, Pending{Number: w.Number, Title: w.Title, URL: w.URL,
						Reason: "its report waits for the owner: " + w.Reason, Holds: w.Blocks})
				}
			}
			return out, nil
		},
	})
}
