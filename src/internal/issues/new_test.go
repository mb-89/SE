package issues

import (
	"errors"
	"reflect"
	"strings"
	"testing"
)

func TestBlockedByIsANumberListOrNone(t *testing.T) {
	for in, want := range map[string][]int{"none": nil, "5": {5}, "5,8": {5, 8}, " #8, 5 ,8": {5, 8}} {
		if got, err := ParseBlockedBy(in); err != nil || !reflect.DeepEqual(got, want) {
			t.Errorf("%q: %v %v, want %v", in, got, err, want)
		}
	}
	for _, in := range []string{"", " ", "5,", "x", "0", "-1", "None", "5;8"} {
		if got, err := ParseBlockedBy(in); err == nil {
			t.Errorf("%q: %v, want refused", in, got)
		}
	}
}

// writes answers gh api calls by path and keeps every call it was asked.
func writes(t *testing.T, answers map[string]string) (GH, *[][]string) {
	t.Helper()
	var calls [][]string
	return func(args ...string) ([]byte, error) {
		calls = append(calls, args)
		path := args[len(args)-1]
		a, ok := answers[path]
		if !ok {
			return nil, errors.New("gh: Not Found (HTTP 404)")
		}
		return []byte(a), nil
	}, &calls
}

func TestBlockWritesNativeLinksByIssueID(t *testing.T) {
	gh, calls := writes(t, map[string]string{
		"repos/o/r/issues/8":                         `{"id":808,"number":8}`,
		"repos/o/r/issues/6/dependencies/blocked_by": `{"id":606}`,
	})
	if err := (Source{Repo: repo, GH: gh}).Block(6, []int{8}); err != nil {
		t.Fatal(err)
	}
	want := [][]string{
		{"api", "repos/o/r/issues/8"},
		{"api", "-X", "POST", "-F", "issue_id=808", "repos/o/r/issues/6/dependencies/blocked_by"},
	}
	if !reflect.DeepEqual(*calls, want) {
		t.Fatalf("%q", *calls)
	}
}

func TestBlockRefusesAMissingBlockerBeforeWriting(t *testing.T) {
	gh, calls := writes(t, map[string]string{"repos/o/r/issues/8": `{"id":808,"number":8}`})
	err := (Source{Repo: repo, GH: gh}).Block(6, []int{8, 99})
	if err == nil || !strings.Contains(err.Error(), "#99 does not exist") {
		t.Fatalf("%v", err)
	}
	for _, c := range *calls {
		if c[1] == "-X" {
			t.Fatalf("wrote %v", c)
		}
	}
	if err := (Source{Repo: repo, GH: gh}).Block(8, []int{8}); err == nil || !strings.Contains(err.Error(), "block itself") {
		t.Fatalf("%v", err)
	}
}

func TestCreateNamesTheIssueWhoseLinkFailed(t *testing.T) {
	gh, _ := writes(t, map[string]string{
		"repos/o/r/issues/8": `{"id":808,"number":8}`,
		"repos/o/r/issues":   `{"number":11,"title":"t","html_url":"u11"}`,
	})
	made, _, err := Source{Repo: repo, GH: gh}.Create("t", "b", 0, []int{8}, false)
	if made.Number != 11 || err == nil || !strings.Contains(err.Error(), "created #11 (u11), but linking #11 as blocked by #8") {
		t.Fatalf("%+v %v", made, err)
	}
}

func TestCreateMakesASubIssueOfItsParent(t *testing.T) {
	gh, calls := writes(t, map[string]string{
		"repos/o/r/issues/1":            `{"id":101,"number":1}`,
		"repos/o/r/issues":              `{"id":1100,"number":11,"title":"t","html_url":"u11"}`,
		"repos/o/r/issues/1/sub_issues": `{}`,
	})
	if _, _, err := (Source{Repo: repo, GH: gh}).Create("t", "b", 1, nil, false); err != nil {
		t.Fatal(err)
	}
	want := [][]string{
		{"api", "repos/o/r/issues/1"},
		{"api", "-X", "POST", "-f", "title=t", "-f", "body=b\n\n<!-- se:new -->", "-f", "labels[]=se", "repos/o/r/issues"},
		{"api", "-X", "POST", "-F", "sub_issue_id=1100", "repos/o/r/issues/1/sub_issues"},
	}
	if !reflect.DeepEqual(*calls, want) {
		t.Fatalf("%q", *calls)
	}
	// A parent that does not exist creates nothing.
	*calls = nil
	if _, _, err := (Source{Repo: repo, GH: gh}).Create("t", "b", 9, nil, false); err == nil || !strings.Contains(err.Error(), "#9 does not exist") {
		t.Fatalf("%v", err)
	}
	for _, c := range *calls {
		if c[1] == "-X" {
			t.Fatalf("wrote %v", c)
		}
	}
}
