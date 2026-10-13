package battery

import (
	"bufio"
	"encoding/json"
	"io"
)

// output is the part of a go test -json event Relay reads.
type output struct {
	Action     string `json:"Action"`
	Package    string `json:"Package"`
	ImportPath string `json:"ImportPath"`
	Test       string `json:"Test"`
	Output     string `json:"Output"`
}

// Relay copies go test -json's events from r to raw whole, and to out what a
// person reads of go test: each package's lines, build errors, and the output
// of each test that failed. A line that is no event goes to out as it came.
func Relay(r io.Reader, out, raw io.Writer) error {
	held := map[[2]string][]string{}
	lines := bufio.NewScanner(r)
	lines.Buffer(make([]byte, 0, 64<<10), 16<<20)
	for lines.Scan() {
		line := lines.Bytes()
		if _, err := raw.Write(append(append([]byte{}, line...), '\n')); err != nil {
			return err
		}
		var e output
		if json.Unmarshal(line, &e) != nil || e.Action == "" {
			if _, err := out.Write(append(append([]byte{}, line...), '\n')); err != nil {
				return err
			}
			continue
		}
		key := [2]string{e.Package, e.Test}
		var show []string
		switch {
		case e.Action == "build-output", e.Action == "output" && e.Test == "":
			show = []string{e.Output}
		case e.Action == "output":
			held[key] = append(held[key], e.Output)
		case e.Action == "fail" && e.Test != "":
			show = held[key]
			delete(held, key)
		case e.Action == "pass" || e.Action == "skip":
			delete(held, key)
		}
		for _, s := range show {
			if _, err := io.WriteString(out, s); err != nil {
				return err
			}
		}
	}
	return lines.Err()
}
