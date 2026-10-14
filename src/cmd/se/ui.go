package main

func init() {
	register(Command{
		Name:    "ui",
		Class:   interactive,
		Usage:   "ui",
		Group:   "Session",
		Summary: "open SE's control panel: the on/off toggle and the commands",
		Details: "open SE's control panel, a pane of buttons every surface draws, the phone included: the on/off toggle top left, then a button for each command registered as one (a command that takes no typed words). A press runs what typing /se <name> runs.",
		Session: true,
		Run: func(c *Call) (Reply, error) {
			if err := c.Parse(c.Flags("ui")); err != nil {
				return Reply{}, err
			}
			return Reply{Text: "SE's control panel is open.", Panel: &Panel{Buttons: buttons()}}, nil
		},
	})
}

// buttons names the commands /se ui offers as buttons, as the index's catalog holds them.
func buttons() []string {
	out := []string{}
	for _, c := range catalog().Buttons() {
		out = append(out, c.Name)
	}
	return out
}
