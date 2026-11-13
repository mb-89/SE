// Package bus is kern's bus: an embedded NATS server on loopback, with one
// user per component instance whose permissions let it publish only on its
// own subjects, so the server itself refuses a second writer to a name.
//
// It comes from quackitect v5's src/index/bus.go: the server options are v5's
// (loopback, a port the system picks, no log, no signals, no JetStream, no
// disk); v5's one shared token becomes one user and password per peer
// (SE's docs/go-core.md, "Single writer, enforced by the bus").
package bus

import (
	"crypto/rand"
	"encoding/hex"
	"errors"
	"fmt"
	"net"
	"sort"
	"strings"
	"time"

	"github.com/nats-io/nats-server/v2/server"
	"github.com/nats-io/nats.go"
)

// The users every bus has beside one per component instance.
const (
	// Core is the core's own user: it may publish and subscribe everything.
	Core = "core"
	// Client is the user of commands and hooks: it asks, it never commits.
	Client = "client"
)

// The verbs in front of a subject (docs/go-core.md, "Subjects").
const (
	Get    = "get."
	Val    = "val."
	Run    = "run."
	In     = "in."
	Commit = "commit."
	Cmd    = "cmd."
	Call   = "call."
	IOVerb = "io."
	Hook   = "hook."
	Lease  = "lease."
)

// The environment a placed component process reads its bus, user and password from.
const (
	EnvBus   = "CORE_BUS"
	EnvUser  = "CORE_USER"
	EnvToken = "CORE_TOKEN"
)

const (
	host          = "127.0.0.1"
	passwordBytes = 24
	// readyWithin is the longest the bus takes to stand before its start fails.
	readyWithin = 10 * time.Second
	// readyLook is each look at the listener: the server's own wait sleeps
	// 25 ms between looks for any wait longer than 25 ms, and not for shorter ones.
	readyLook = 20 * time.Millisecond
	// maxPayload is v5's largest message.
	maxPayload = 64 << 20
)

// Instance is one component instance the bus gives a user to.
type Instance struct {
	// Name is the instance's name in the wiring, plain or nested as <group>/<name>.
	Name string
	// IO is set on an instance of an I/O component: it alone answers io.<i>.>.
	IO bool
}

// Bus is a running embedded NATS server.
type Bus struct {
	server *server.Server
	users  map[string]string
}

// Start runs the server on loopback, on a port the system picks, with a user
// for the core, one for clients and one for each instance, and waits until it
// accepts connections.
func Start(instances []Instance) (*Bus, error) {
	users := map[string]string{}
	var accounts []*server.User
	add := func(name string, perms *server.Permissions) error {
		if _, dup := users[name]; dup {
			return fmt.Errorf("bus: two users named %q: an instance takes neither the name %q nor %q, nor another's", name, Core, Client)
		}
		pw, err := password()
		if err != nil {
			return err
		}
		users[name] = pw
		accounts = append(accounts, &server.User{Username: name, Password: pw, Permissions: perms})
		return nil
	}
	if err := add(Core, nil); err != nil {
		return nil, err
	}
	if err := add(Client, clientPermissions()); err != nil {
		return nil, err
	}
	for _, in := range instances {
		if err := add(in.Name, instancePermissions(in)); err != nil {
			return nil, err
		}
	}
	s, err := server.NewServer(&server.Options{
		Host: host, Port: server.RANDOM_PORT, Users: accounts,
		NoLog: true, NoSigs: true, MaxPayload: maxPayload,
	})
	if err != nil {
		return nil, fmt.Errorf("bus: %w", err)
	}
	go s.Start()
	if !ready(s) {
		s.Shutdown()
		return nil, fmt.Errorf("bus: the server does not accept connections within %v", readyWithin)
	}
	return &Bus{server: s, users: users}, nil
}

// ready looks at the listener in waits short enough that the server does not
// sleep between looks, so the bus stands as soon as it listens.
func ready(s *server.Server) bool {
	end := time.Now().Add(readyWithin)
	for time.Now().Before(end) {
		if s.ReadyForConnections(readyLook) {
			return true
		}
	}
	return false
}

func password() (string, error) {
	b := make([]byte, passwordBytes)
	if _, err := rand.Read(b); err != nil {
		return "", fmt.Errorf("bus: no random password: %w", err)
	}
	return hex.EncodeToString(b), nil
}

// instancePermissions are an instance's: it publishes its own commits, leases
// and input asks, and asks any name and command; it hears its own runs,
// commands and, for an I/O instance, requests, every value, and its own inbox.
func instancePermissions(in Instance) *server.Permissions {
	i := Subject(in.Name)
	sub := []string{Run + i, Cmd + i + ".>", Val + ">", Inbox(in.Name) + ".>"}
	if in.IO {
		sub = append(sub, IOVerb+i+".>")
	}
	return &server.Permissions{
		Publish:   &server.SubjectPermission{Allow: []string{Commit + i, Lease + i, In + i, Get + ">", Call + ">"}},
		Subscribe: &server.SubjectPermission{Allow: sub},
		// An instance answers the core's cmd and io requests on the reply subject each names.
		Response: &server.ResponsePermission{MaxMsgs: 1},
	}
}

// clientPermissions are a command's or a hook's: it asks, it hears values and its own inbox.
func clientPermissions() *server.Permissions {
	return &server.Permissions{
		Publish:   &server.SubjectPermission{Allow: []string{Call + ">", Get + ">", Hook + ">"}},
		Subscribe: &server.SubjectPermission{Allow: []string{Val + ">", Inbox(Client) + ".>"}},
	}
}

// URL is the address a peer dials.
func (b *Bus) URL() string { return b.server.ClientURL() }

// Port is the port the system picked.
func (b *Bus) Port() int { return b.server.Addr().(*net.TCPAddr).Port }

// Users answers each user and its password.
func (b *Bus) Users() map[string]string {
	out := make(map[string]string, len(b.users))
	for k, v := range b.users {
		out[k] = v
	}
	return out
}

// Names answers the users, sorted.
func (b *Bus) Names() []string {
	out := make([]string, 0, len(b.users))
	for k := range b.users {
		out = append(out, k)
	}
	sort.Strings(out)
	return out
}

// Close ends the server and waits until it is down.
func (b *Bus) Close() {
	b.server.Shutdown()
	b.server.WaitForShutdown()
}

// Subject is a name's subject tokens: fleet/findings rides as fleet.findings.
func Subject(name string) string { return strings.ReplaceAll(name, "/", ".") }

// Name is the name a subject's tokens stand for: fleet.findings is fleet/findings.
func Name(subject string) string { return strings.ReplaceAll(subject, ".", "/") }

// Inbox is the prefix of a user's reply subjects. It is one token, so no
// user's inbox lies inside another's, nested instances included.
func Inbox(user string) string {
	if user == Core {
		return "_INBOX"
	}
	return "_INBOX." + hex.EncodeToString([]byte(user))
}

// ErrNoBus is what Dial answers where nothing listens at the address.
var ErrNoBus = errors.New("bus: no bus answers")

// Dial connects as user, with its own inbox and no reconnect: a new core
// stands a new bus.
func Dial(url, user, password string, opts ...nats.Option) (*nats.Conn, error) {
	all := append([]nats.Option{
		nats.UserInfo(user, password), nats.NoReconnect(), nats.CustomInboxPrefix(Inbox(user)),
		nats.Timeout(2 * time.Second),
	}, opts...)
	nc, err := nats.Connect(url, all...)
	if err != nil {
		if errors.Is(err, nats.ErrNoServers) {
			return nil, fmt.Errorf("%w at %s: %v", ErrNoBus, url, err)
		}
		return nil, fmt.Errorf("bus: dial %s as %s: %w", url, user, err)
	}
	return nc, nil
}
