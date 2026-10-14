package session_test

import (
	"encoding/json"
	"strings"
	"testing"

	"github.com/mb-89/SE/src/index/indextest"
	"github.com/mb-89/SE/src/modules/io/session"
)

func TestTheLogModuleWritesEachEventItReads(t *testing.T) {
	t.Parallel()
	l := session.NewFake()
	f, err := indextest.New(session.LogModule(l))
	if err != nil {
		t.Fatal(err)
	}
	if err := f.Derive("written"); err != nil {
		t.Fatal(err)
	}
	if got, _ := l.Read("s1"); len(got) != 0 {
		t.Fatalf("the built-in event was written: %q", got)
	}
	ev := session.Event{Seq: 3, Session: "s1", Event: "tool.call", At: "t", E: json.RawMessage(`{"x":1}`)}
	if err := f.Seed("events", ev); err != nil {
		t.Fatal(err)
	}
	if err := f.Derive("written"); err != nil {
		t.Fatal(err)
	}
	got, _ := l.Read("s1")
	if string(got) != `{"at":"t","e":{"x":1},"event":"tool.call"}`+"\n" {
		t.Fatalf("the log reads %q", got)
	}
	if w, _ := f.Out("written"); w.V != uint64(3) {
		t.Fatalf("written = %+v", w)
	}
}

func TestALongPayloadLandsCut(t *testing.T) {
	t.Parallel()
	long, _ := json.Marshal(strings.Repeat("a", session.PayloadCap*2))
	row, err := session.Row(session.Event{Session: "s1", Event: "x", E: long})
	if err != nil {
		t.Fatal(err)
	}
	var got struct {
		E struct {
			Cut    bool   `json:"cut"`
			Length int    `json:"length"`
			Head   string `json:"head"`
		} `json:"e"`
	}
	if err := json.Unmarshal(row, &got); err != nil || !got.E.Cut || got.E.Length != len(long) || len(got.E.Head) != session.PayloadCap {
		t.Fatalf("row %s: %+v, %v", row[:80], got, err)
	}
}
