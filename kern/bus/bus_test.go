package bus_test

import (
	"errors"
	"strings"
	"testing"
	"time"

	"github.com/mb-89/kern/bus"
	"github.com/nats-io/nats.go"
)

// wait is how long a case waits on an event that comes within milliseconds.
const wait = 5 * time.Second

func started(t *testing.T, instances ...bus.Instance) *bus.Bus {
	t.Helper()
	b, err := bus.Start(instances)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(b.Close)
	return b
}

// dial connects as user, and hands every asynchronous error, such as a
// permissions violation, to the channel it answers.
func dial(t *testing.T, b *bus.Bus, user string) (*nats.Conn, <-chan error) {
	t.Helper()
	errs := make(chan error, 16)
	nc, err := bus.Dial(b.URL(), user, b.Users()[user], nats.ErrorHandler(func(_ *nats.Conn, _ *nats.Subscription, err error) {
		errs <- err
	}))
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(nc.Close)
	return nc, errs
}

// hear subscribes as the core and hands each message on subject to the channel it answers.
func hear(t *testing.T, core *nats.Conn, subject string) <-chan *nats.Msg {
	t.Helper()
	got := make(chan *nats.Msg, 16)
	if _, err := core.ChanSubscribe(subject, got); err != nil {
		t.Fatal(err)
	}
	if err := core.Flush(); err != nil {
		t.Fatal(err)
	}
	return got
}

func violation(t *testing.T, errs <-chan error, subject string) {
	t.Helper()
	select {
	case err := <-errs:
		if !errors.Is(err, nats.ErrPermissionViolation) || !strings.Contains(err.Error(), subject) {
			t.Fatalf("the bus answers %v, and wants a permissions violation naming %s", err, subject)
		}
	case <-time.After(wait):
		t.Fatalf("the bus lets the publish on %s through without a permissions violation", subject)
	}
}

// The single writer, enforced by the bus: an instance commits on its own
// subject, and the server refuses its commit on another instance's.
func TestASecondWriterIsRefusedByTheBus(t *testing.T) {
	b := started(t, bus.Instance{Name: "counter"}, bus.Instance{Name: "report"})
	core, _ := dial(t, b, bus.Core)
	commits := hear(t, core, bus.Commit+">")
	report, errs := dial(t, b, "report")

	if err := report.Publish(bus.Commit+"counter", []byte(`{"writes":[]}`)); err != nil {
		t.Fatal(err)
	}
	_ = report.Flush()
	violation(t, errs, bus.Commit+"counter")

	if err := report.Publish(bus.Commit+"report", []byte(`{"writes":[]}`)); err != nil {
		t.Fatal(err)
	}
	if err := report.Flush(); err != nil {
		t.Fatal(err)
	}
	select {
	case m := <-commits:
		if m.Subject != bus.Commit+"report" {
			t.Fatalf("the core hears a commit on %s, and wants only report's own, commit.report", m.Subject)
		}
	case <-time.After(wait):
		t.Fatal("the core hears no commit on report's own subject")
	}
}

// A nested instance's subjects are its own: issues may not commit as issues/pull.
func TestANestedInstanceIsAWriterOfItsOwn(t *testing.T) {
	b := started(t, bus.Instance{Name: "issues"}, bus.Instance{Name: "issues/pull"})
	issues, errs := dial(t, b, "issues")
	if err := issues.Publish(bus.Commit+bus.Subject("issues/pull"), nil); err != nil {
		t.Fatal(err)
	}
	_ = issues.Flush()
	violation(t, errs, "commit.issues.pull")
}

// A client asks and hooks, and never commits, leases or answers runs.
func TestAClientAsksAndNeverCommits(t *testing.T) {
	b := started(t, bus.Instance{Name: "counter"})
	core, _ := dial(t, b, bus.Core)
	if _, err := core.Subscribe(bus.Get+"counter.count", func(m *nats.Msg) { _ = m.Respond([]byte("3")) }); err != nil {
		t.Fatal(err)
	}
	_ = core.Flush()
	client, errs := dial(t, b, bus.Client)
	answer, err := client.Request(bus.Get+"counter.count", nil, wait)
	if err != nil || string(answer.Data) != "3" {
		t.Fatalf("a client's get answers %v, %v, and wants 3", answer, err)
	}
	for _, subject := range []string{bus.Commit + "counter", bus.Lease + "counter"} {
		if err := client.Publish(subject, nil); err != nil {
			t.Fatal(err)
		}
		_ = client.Flush()
		violation(t, errs, subject)
	}
	if _, err := client.Subscribe(bus.Run+"counter", func(*nats.Msg) {}); err != nil {
		t.Fatal(err)
	}
	_ = client.Flush()
	violation(t, errs, bus.Run+"counter")
}

// One user's replies are no other's to hear: an instance may not subscribe to
// the client's inbox.
func TestAnInboxIsItsOwnersAlone(t *testing.T) {
	b := started(t, bus.Instance{Name: "counter"})
	counter, errs := dial(t, b, "counter")
	if _, err := counter.Subscribe(bus.Inbox(bus.Client)+".>", func(*nats.Msg) {}); err != nil {
		t.Fatal(err)
	}
	_ = counter.Flush()
	violation(t, errs, bus.Inbox(bus.Client))
}

// Only an I/O instance hears io requests; each instance answers its own commands.
func TestAnIOInstanceAloneHearsItsVerbs(t *testing.T) {
	b := started(t, bus.Instance{Name: "ledger", IO: true}, bus.Instance{Name: "clerk"})
	core, _ := dial(t, b, bus.Core)
	ledger, _ := dial(t, b, "ledger")
	if _, err := ledger.Subscribe(bus.IOVerb+"ledger.append", func(m *nats.Msg) { _ = m.Respond([]byte("1")) }); err != nil {
		t.Fatal(err)
	}
	_ = ledger.Flush()
	answer, err := core.Request(bus.IOVerb+"ledger.append", []byte(`"a line"`), wait)
	if err != nil || string(answer.Data) != "1" {
		t.Fatalf("the ledger answers its verb with %v, %v, and wants 1", answer, err)
	}
	clerk, errs := dial(t, b, "clerk")
	if _, err := clerk.Subscribe(bus.IOVerb+"clerk.append", func(*nats.Msg) {}); err != nil {
		t.Fatal(err)
	}
	_ = clerk.Flush()
	violation(t, errs, bus.IOVerb+"clerk.append")
}

// A wrong password is refused, and an instance takes no name the bus keeps for itself.
func TestTheBusRefusesStrangers(t *testing.T) {
	b := started(t, bus.Instance{Name: "counter"})
	if _, err := bus.Dial(b.URL(), "counter", "wrong"); err == nil {
		t.Fatal("the bus lets a wrong password in")
	}
	if _, err := bus.Start([]bus.Instance{{Name: bus.Client}}); err == nil || !strings.Contains(err.Error(), "two users") {
		t.Fatalf("a bus with an instance named client starts with %v, and wants a refusal", err)
	}
}

func TestSubjectsAndNames(t *testing.T) {
	if got := bus.Subject("fleet/findings"); got != "fleet.findings" {
		t.Fatalf("fleet/findings rides as %s", got)
	}
	if got := bus.Name("fleet.findings"); got != "fleet/findings" {
		t.Fatalf("fleet.findings stands for %s", got)
	}
	if strings.HasPrefix(bus.Inbox("issues/pull"), bus.Inbox("issues")+".") {
		t.Fatal("a nested instance's inbox lies inside its group's")
	}
}
