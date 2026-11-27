package template

import (
	"bytes"
	"context"
	"encoding/json"
	"path/filepath"
	"strings"
	"testing"
)

// The command line's door answers fill as the bus's verb does: SE's retro-deck template filled from
// its example's fields gives its document, and a fill that misses a required field is refused,
// naming it, with nothing made (cli.go, scripts/template_door.py).
func TestAskFillsAndRefusesAsTheVerbDoes(t *testing.T) {
	s.mu.Lock()
	s.root, s.repository, s.se = filepath.Join("..", ".."), SERepository, ""
	s.mu.Unlock()
	request := `{"template": "retro-deck", "raw": "", "fields": {"title": "example: Retro #12", "subtitle": "Retro report", "steps": "### Step\n\nIt ran.", "decisions": "None."}}`
	answer, err := Ask(context.Background(), "fill", strings.NewReader(request))
	if err != nil {
		t.Fatalf("fill of retro-deck's fields answers %v, and wants its document", err)
	}
	out, _ := json.Marshal(answer)
	var filled struct{ Document string }
	if json.Unmarshal(out, &filled) != nil || !strings.Contains(filled.Document, "## Steps\n\n### Step\n\nIt ran.") {
		t.Fatalf("fill answers %s, and wants the document with its steps", out)
	}
	if _, err := Ask(context.Background(), "fill", strings.NewReader(`{"template": "retro-deck", "raw": "", "fields": {"title": "T", "subtitle": "S", "decisions": "None."}}`)); err == nil || !strings.Contains(err.Error(), "refused") {
		t.Fatalf("a fill without the required steps answers %v, and wants its refusal", err)
	}
	if _, err := Ask(context.Background(), "accept", bytes.NewReader(nil)); err == nil || !strings.Contains(err.Error(), "fill or check") {
		t.Fatalf("an unknown verb answers %v, and wants the verbs it takes", err)
	}
}
