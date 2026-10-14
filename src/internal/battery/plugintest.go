package battery

import (
	"bufio"
	"io"
	"regexp"
	"strconv"
	"strings"
)

// PluginTestFile is what `claude plugin test` printed for the battery, whole.
const PluginTestFile = "plugintest.txt"

var (
	// ansi is a terminal's colour code, which a coloured run puts around its words.
	ansi = regexp.MustCompile("\x1b\\[[0-9;]*m")
	// pluginTest is bun's line for one test: `(pass) name [12.34ms]`.
	pluginTest = regexp.MustCompile(`^\((pass|fail)\) (.+) \[([0-9.]+)(ms|s)\]$`)
	// testFile is bun's line before a file's tests: `tests/se.test.ts:`.
	testFile = regexp.MustCompile(`^(\S+\.test\.[cm]?[jt]sx?):$`)
)

// ParsePluginTest reads what `claude plugin test` printed: every plugin test
// that passed or failed, under the file it is in, and how long it took. A
// line that is no test is skipped; `claude plugin test` has no reporter
// option, so its lines for a person are all there is.
func ParsePluginTest(r io.Reader) ([]Test, error) {
	var tests []Test
	file := ""
	lines := bufio.NewScanner(r)
	lines.Buffer(make([]byte, 0, 64<<10), 16<<20)
	for lines.Scan() {
		line := strings.TrimSpace(ansi.ReplaceAllString(lines.Text(), ""))
		if m := testFile.FindStringSubmatch(line); m != nil {
			file = m[1]
			continue
		}
		m := pluginTest.FindStringSubmatch(line)
		if m == nil {
			continue
		}
		took, err := strconv.ParseFloat(m[3], 64)
		if err != nil {
			continue
		}
		if m[4] == "s" {
			took *= 1000
		}
		tests = append(tests, Test{Package: file, Name: m[2], Ms: int64(took + 0.5)})
	}
	return tests, lines.Err()
}
