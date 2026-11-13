package index_test

import (
	"os"
	"reflect"
	"regexp"
	"strings"
	"testing"

	"github.com/mb-89/kern/index"
)

// kern/README.md's row for cmd.<i>.<command> names what a process answers a
// step: exactly the fields of index.Answer a process sends, so the row never
// names a field the core no longer reads (a step's lines ride say.<i>.<call>).
func TestTheReadmesStepRowNamesTheFieldsOfAnAnswer(t *testing.T) {
	data, err := os.ReadFile("../README.md")
	if err != nil {
		t.Fatal(err)
	}
	var row string
	for _, line := range strings.Split(strings.ReplaceAll(string(data), "\r\n", "\n"), "\n") {
		if strings.HasPrefix(line, "| `cmd.<i>.<command>` |") {
			row = line
		}
	}
	cells := strings.Split(row, " | ")
	if len(cells) < 3 {
		t.Fatalf("kern/README.md has no row for cmd.<i>.<command>: %q", row)
	}
	process := cells[1]
	answers, _, _ := strings.Cut(strings.TrimPrefix(process, "answers one step: "), ";")
	var named []string
	for _, m := range regexp.MustCompile("`([a-z]+)`").FindAllStringSubmatch(answers, -1) {
		named = append(named, m[1])
	}
	var fields []string
	at := reflect.TypeOf(index.Answer{})
	for i := 0; i < at.NumField(); i++ {
		tag, _, _ := strings.Cut(at.Field(i).Tag.Get("json"), ",")
		if tag != "-" && tag != "" {
			fields = append(fields, tag)
		}
	}
	if !reflect.DeepEqual(named, fields) {
		t.Fatalf("kern/README.md's cmd.<i>.<command> row says a step answers %q, and index.Answer reads %q", named, fields)
	}
}
