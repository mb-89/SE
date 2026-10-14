package main

func init() {
	register(Command{
		Name:    "off",
		Class:   interactive,
		Usage:   "off",
		Group:   "Session",
		Summary: "switch SE off for this session; the daemon runs on",
		Details: []string{
			"switch SE off for this session.",
			"The daemon runs on for other sessions.",
		},
		Session: true,
		Run: func(c *Call) (Reply, error) {
			if err := c.Parse(c.Flags("off")); err != nil {
				return Reply{}, err
			}
			return Reply{Text: "SE is off.", Active: switched(false)}, nil
		},
	})
}
