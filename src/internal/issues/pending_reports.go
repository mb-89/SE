package issues

func init() {
	RegisterPending(PendingSource{
		Name: "report waiting",
		List: func(o Open) ([]Pending, error) {
			var out []Pending
			for _, w := range o.Waiting {
				if report(o, w.Number) {
					reason := "its report waits for the owner: " + w.Reason
					out = append(out, Pending{Number: w.Number, Title: w.Title, URL: w.URL, Reason: reason, Holds: w.Blocks})
				}
			}
			return out, nil
		},
	})
}
