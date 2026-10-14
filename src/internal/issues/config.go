package issues

import (
	"fmt"
	"slices"
	"strings"

	"github.com/mb-89/SE/src/internal/io/github"
	"gopkg.in/yaml.v3"
)

// FleetConfigPath is the fleet's configuration, which se fleet check compares
// with the live one (principle 21).
const FleetConfigPath = "spec/fleet.yaml"

// driftMark marks the issue a configuration drift went to, so it is reported
// once while that issue is open.
const driftMark = "<!-- se:fleet configuration-drift -->"

// fleetConfig is what se fleet check reads of spec/fleet.yaml. The routine
// is written there too, but no API the fleet has reads it.
type fleetConfig struct {
	Ruleset struct {
		Branch         string   `yaml:"branch"`
		RequiredChecks []string `yaml:"required_checks"`
		Strict         bool     `yaml:"strict"`
	} `yaml:"ruleset"`
}

// rule is one rule GitHub applies to a branch.
type rule struct {
	Type       string `json:"type"`
	Parameters struct {
		Strict bool `json:"strict_required_status_checks_policy"`
		Checks []struct {
			Context string `json:"context"`
		} `json:"required_status_checks"`
	} `json:"parameters"`
}

// drift compares spec/fleet.yaml at main with main's live ruleset: each
// difference is one configuration drift, which goes to a person, since only
// a person decides which side is right. Without the file there is nothing to
// compare. reported is the open issue a drift went to already, or 0.
func (s Source) drift(t tree) ([]Finding, error) {
	text, err := s.file(FleetConfigPath, "main")
	if err != nil || text == "" {
		return nil, err
	}
	var want fleetConfig
	if err := yaml.Unmarshal([]byte(text), &want); err != nil {
		return nil, fmt.Errorf("reading %s at main: %w", FleetConfigPath, err)
	}
	b := want.Ruleset.Branch
	if b == "" {
		return nil, fmt.Errorf("%s at main names no ruleset branch", FleetConfigPath)
	}
	rules, err := api[rule](s, fmt.Sprintf("repos/%s/rules/branches/%s", s.Repo, b), true)
	if err != nil && github.Status(err) != 404 {
		return nil, err
	}
	var live []string
	strict := false
	for _, r := range rules {
		if r.Type != "required_status_checks" {
			continue
		}
		strict = strict || r.Parameters.Strict
		for _, c := range r.Parameters.Checks {
			live = append(live, c.Context)
		}
	}
	var differs []string
	if missing := minus(want.Ruleset.RequiredChecks, live); len(missing) > 0 {
		differs = append(differs, fmt.Sprintf("%s requires %s, which %s's live ruleset does not", FleetConfigPath, strings.Join(missing, ", "), b))
	}
	if extra := minus(live, want.Ruleset.RequiredChecks); len(extra) > 0 {
		differs = append(differs, fmt.Sprintf("%s's live ruleset requires %s, which %s does not", b, strings.Join(extra, ", "), FleetConfigPath))
	}
	if strict != want.Ruleset.Strict && len(want.Ruleset.RequiredChecks) > 0 {
		differs = append(differs, fmt.Sprintf("%s sets strict: %t, %s's live ruleset %t", FleetConfigPath, want.Ruleset.Strict, b, strict))
	}
	if len(differs) == 0 {
		return nil, nil
	}
	f := Finding{Kind: ConfigDrift, judgment: true, What: strings.Join(differs, "; ")}
	for _, n := range t.numbers() {
		if strings.Contains(t.byNum[n].Body, driftMark) {
			f.reported = n
		}
	}
	return []Finding{f}, nil
}

// minus is what of a b lacks, in a's order.
func minus(a, b []string) []string {
	var out []string
	for _, x := range a {
		if !slices.Contains(b, x) {
			out = append(out, x)
		}
	}
	return out
}

// reportDrift sends a configuration drift to a person, once while their
// issue is open.
func (s Source) reportDrift(x *Fixed) error {
	if x.reported > 0 {
		x.Did, x.Made = fmt.Sprintf("reported already as #%d, still open", x.reported), x.reported
		return nil
	}
	title := "Configuration drift: " + x.What
	body := fmt.Sprintf("Decide which side is right: set the live setting as %s says, or change %s to the live one.\n\nse fleet check found: %s.\n\n%s", FleetConfigPath, FleetConfigPath, x.What, driftMark)
	made, err := s.ForPerson(title, body, 0, nil)
	if err != nil {
		return err
	}
	x.Made, x.Did = made.Number, fmt.Sprintf("reported it to a person as #%d", made.Number)
	return nil
}
