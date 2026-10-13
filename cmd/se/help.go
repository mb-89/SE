package main

func init() {
	register(Command{
		Name:    "help",
		Usage:   "help",
		Summary: "list the commands",
		Session: true,
		Run: func(c *Call) (Reply, error) {
			return Reply{Text: help(c.Session)}, nil
		},
	})
}
