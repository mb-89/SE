package issues

import (
	"fmt"
	"regexp"
	"strings"
)

// MaxFollowups is the built-in value of issues/config/max-followups: how many
// issues a box files with se issue new. A box writes to GitHub once, at its
// end, so se issue new queues them and its land, supersede or close files
// them; what is left beyond goes into them, or into one for a person.
const MaxFollowups = 1

// FollowupShare is the built-in value of issues/config/followup-share: the
// percent of the issues a box closed that may have filed a follow-up before
// the retro finds the followups rule check broken.
const FollowupShare = 5

// followupMark is in the body of every issue a box filed as its follow-up,
// naming the issue the box took, so the retro counts them.
var followupMark = regexp.MustCompile(`<!-- se:followup #(\d+) -->`)

// AsFollowup is body as a box files it: its text, then the mark that names
// n, the issue the box took and closed by a land, a supersede or a close.
func AsFollowup(body string, n int) string {
	return strings.TrimRight(body, " \n") + fmt.Sprintf("\n\n<!-- se:followup #%d -->", n)
}

// followupsOf names the issue each mark in body follows up.
func followupsOf(body string) []int {
	var out []int
	for _, m := range followupMark.FindAllStringSubmatch(body, -1) {
		out = append(out, atoi(m[1]))
	}
	return out
}
