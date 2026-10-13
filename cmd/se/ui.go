package main

func init() {
	register(Command{
		Name:    "ui",
		Usage:   "ui",
		Summary: "open SE's control panel: the on/off toggle and a button for each command that takes no words",
		Session: true,
		Run: func(c *Call) (Reply, error) {
			if err := c.Parse(c.Flags("ui")); err != nil {
				return Reply{}, err
			}
			return Reply{Text: "SE's control panel is open.", Panel: &Panel{Buttons: buttons()}}, nil
		},
	})
}

// buttons names the commands /se ui offers as buttons, made from the registry.
func buttons() []string {
	out := []string{}
	for _, c := range offered(true) {
		if c.Button {
			out = append(out, c.Name)
		}
	}
	return out
}
