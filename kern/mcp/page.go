package mcp

import (
	"fmt"
	"strings"
	"unicode/utf8"

	sdk "github.com/modelcontextprotocol/go-sdk/mcp"
)

// PageLimit is the most bytes of text one tool answer carries: a host cuts
// an answer at about 50,000 bytes, so a longer one comes in pages below it,
// each asked by the tool's "page" argument.
const PageLimit = 45000

// pages splits text into pages of at most limit bytes, at line ends where a
// line fits, else at a rune's boundary; one page for text that fits.
func pages(text string, limit int) []string {
	if len(text) <= limit {
		return []string{text}
	}
	var out []string
	var b strings.Builder
	flush := func() {
		if b.Len() > 0 {
			out = append(out, b.String())
			b.Reset()
		}
	}
	for _, line := range strings.SplitAfter(text, "\n") {
		for len(line) > limit {
			flush()
			cut := limit
			for cut > 0 && !utf8.RuneStart(line[cut]) {
				cut--
			}
			out = append(out, line[:cut])
			line = line[cut:]
		}
		if b.Len()+len(line) > limit {
			flush()
		}
		b.WriteString(line)
	}
	flush()
	return out
}

// paged answers page (1 for the first) of the answer: it keeps the pages of
// an answer that needs more than one under key, the tool and its arguments,
// so a later page is read from them, not run again; page 1 always runs.
func (d *door) paged(key string, page int, run func() (string, *sdk.CallToolResult)) *sdk.CallToolResult {
	if page < 1 {
		page = 1
	}
	d.mu.Lock()
	kept, ok := d.pages[key]
	d.mu.Unlock()
	if page == 1 || !ok {
		full, failed := run()
		if failed != nil {
			return failed
		}
		kept = pages(full, d.o.PageLimit)
		d.mu.Lock()
		if len(kept) > 1 {
			d.pages[key] = kept
		} else {
			delete(d.pages, key)
		}
		d.mu.Unlock()
	}
	if len(kept) == 1 {
		return text(kept[0], nil)
	}
	if page > len(kept) {
		return failure(CommandFailed, fmt.Sprintf("the answer has %d pages, not %d", len(kept), page), "ask a page it has")
	}
	body := kept[page-1]
	if page < len(kept) {
		body += fmt.Sprintf("\n\n[page %d of %d: call again with the same arguments and \"page\": %d for the rest]", page, len(kept), page+1)
	} else {
		body += fmt.Sprintf("\n\n[page %d of %d, the last]", page, len(kept))
	}
	return text(body, map[string]any{"page": page, "pages": len(kept)})
}
