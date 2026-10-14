package guidance_test

import (
	"reflect"
	"strings"
	"testing"

	"github.com/mb-89/SE/src/index"
	"github.com/mb-89/SE/src/internal/guidance"
	"github.com/mb-89/SE/src/modules/io/disk"
)

func TestABodyNamesItsSkillsInOneMarkedLine(t *testing.T) {
	t.Parallel()
	names, err := guidance.Parse(" work, retro ,work")
	if err != nil || !reflect.DeepEqual(names, []string{"work", "retro"}) {
		t.Fatalf("%v %v", names, err)
	}
	if _, err := guidance.Parse("work,../x"); err == nil {
		t.Fatal("a name that is no skill name was taken")
	}
	body := guidance.With("do it\n", names)
	if body != "do it\n\nSkills: work, retro "+guidance.Mark {
		t.Fatalf("%q", body)
	}
	if got := guidance.Named(body + "\n\n<!-- se:new -->"); !reflect.DeepEqual(got, names) {
		t.Fatalf("%v", got)
	}
	if guidance.Named("Skills: work") != nil || guidance.With("b", nil) != "b" {
		t.Fatal("an unmarked line named skills, or no skills changed the body")
	}
}

func TestSkillsAreHandedInFullOrByName(t *testing.T) {
	t.Parallel()
	d := disk.NewFake()
	for name, text := range map[string]string{"work": "Do the work.\n", "retro": "Run the retro.\n"} {
		if err := d.MkdirAll("/ws/src/plugin/skills/" + name); err != nil {
			t.Fatal(err)
		}
		if err := d.WriteFile("/ws/"+guidance.PathOf(name), []byte(text)); err != nil {
			t.Fatal(err)
		}
	}
	skills, err := guidance.Read(d, "/ws", []string{"work", "retro"})
	if err != nil || len(skills) != 2 || len(skills[0].Hash) != 64 || skills[0].Hash == skills[1].Hash {
		t.Fatalf("%+v %v", skills, err)
	}
	full := guidance.Text(skills, true)
	for _, want := range []string{"Do the work.", "Run the retro.", `path="src/plugin/skills/retro/SKILL.md"`} {
		if !strings.Contains(full, want) {
			t.Errorf("in full, %q is missing: %q", want, full)
		}
	}
	named := guidance.Text(skills, false)
	if strings.Contains(named, "Do the work.") || !strings.Contains(named, "- work: src/plugin/skills/work/SKILL.md") {
		t.Errorf("by name: %q", named)
	}
	if _, err := guidance.Read(d, "/ws", []string{"none"}); err == nil {
		t.Error("a skill that does not exist was read")
	}
}

func TestTheSwitchesAreConfigValues(t *testing.T) {
	t.Parallel()
	s, err := guidance.Configured()
	if err != nil || !s.Inline || !s.Principles {
		t.Fatalf("the wiring se carries: %+v %v", s, err)
	}
	w, err := index.ParseWiring([]byte("instances:\n  guidance: { module: guidance, config: { inline: false } }\n"))
	if err != nil {
		t.Fatal(err)
	}
	if s, err = guidance.From(w); err != nil || s.Inline || !s.Principles {
		t.Fatalf("inline off: %+v %v", s, err)
	}
}
