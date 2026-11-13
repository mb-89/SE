package host

import (
	"encoding/json"
	"os"
	"path/filepath"
	"time"

	"github.com/mb-89/kern/index"
)

// AdHocDir is where an ad hoc component's component.toml lives under the
// checkout: the second of DeclarationDirs (declared.go), SE's docs/go-core.md
// "Scripts are ad hoc, components are long-term". A wiring instance whose
// component has a declaration here is ad hoc, and its calls are counted.
var AdHocDir = filepath.Join(".se", "components")

// UsageLog is the ad hoc components' use log under the checkout, one JSON
// record a line. SE's scripts/se_usage.py owns the record's shape for the
// Python side (retro.py collect reads it); this file writes the same shape, as
// Go and Python agree on the declaration hash.
var UsageLog = filepath.Join(".se", "usage", "adhoc.jsonl")

// adHoc is an ad hoc component the core counts: its instance's component name
// and the component's folder under the checkout.
type adHoc struct {
	component string
	path      string
}

// use is one record of the use log: when the call was answered, the session it
// ran in, the component and its folder.
type use struct {
	At        string `json:"at"`
	Session   string `json:"session"`
	Component string `json:"component"`
	Path      string `json:"path"`
}

// adHocInstances finds, among the wiring's instances, those whose component is
// declared by a component.toml under <root>/.se/components/: the ad hoc ones,
// by instance name. It stats the file, so a compiled or an application
// component of the same name is ad hoc only where that file is there too.
func adHocInstances(root string, instances []instanceName) map[string]adHoc {
	found := map[string]adHoc{}
	for _, in := range instances {
		rel := filepath.Join(AdHocDir, filepath.FromSlash(in.Component))
		if _, err := os.Stat(filepath.Join(root, rel, index.DeclarationFile)); err == nil {
			found[in.Name] = adHoc{component: in.Component, path: filepath.ToSlash(rel)}
		}
	}
	return found
}

// instanceName is the part of a wiring instance adHocInstances reads.
type instanceName struct{ Name, Component string }

// recordUse appends one use of an ad hoc component to the log under root; a
// write that fails is dropped, since counting is advice, never enforcement
// (the rule book's gen-003).
func recordUse(root string, a adHoc, session string, at time.Time) {
	path := filepath.Join(root, UsageLog)
	if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
		return
	}
	data, err := json.Marshal(use{At: at.UTC().Format(time.RFC3339), Session: session,
		Component: a.component, Path: a.path})
	if err != nil {
		return
	}
	f, err := os.OpenFile(path, os.O_CREATE|os.O_WRONLY|os.O_APPEND, 0o600)
	if err != nil {
		return
	}
	defer f.Close()
	_, _ = f.Write(append(data, '\n'))
}
