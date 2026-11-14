package bus

import (
	"testing"
	"time"
)

// The fast guard of the long step (contract/longstep_test.go, beside the
// suite): a reply permission the bus grants an instance never expires where
// the core sets no reply wait, as kern serves, so NATS's own default of two
// minutes never refuses the answer of a long step; a set wait bounds it.
func TestAnInstancesReplyPermissionNeverExpiresWithoutAReplyWait(t *testing.T) {
	for _, replyWait := range []time.Duration{0, -time.Second} {
		r := instancePermissions(Instance{Name: "gap"}, replyWait).Response
		if r == nil || r.MaxMsgs != 1 || r.Expires >= 0 {
			t.Fatalf("with a reply wait of %v the reply permission is %+v, and wants one answer that never expires (Expires < 0)", replyWait, r)
		}
	}
	if r := instancePermissions(Instance{Name: "gap"}, time.Second).Response; r == nil || r.Expires != time.Second {
		t.Fatalf("with a reply wait of 1s the reply permission is %+v, and wants it to expire after 1s", r)
	}
}
