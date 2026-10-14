package rules

import "bytes"

// executables are the magic numbers that open a compiled program: ELF, and
// Mach-O in its 32- and 64-bit forms, either byte order, and fat.
var executables = [][]byte{
	{0x7f, 'E', 'L', 'F'},
	{0xfe, 0xed, 0xfa, 0xce}, {0xce, 0xfa, 0xed, 0xfe},
	{0xfe, 0xed, 0xfa, 0xcf}, {0xcf, 0xfa, 0xed, 0xfe},
	{0xca, 0xfe, 0xba, 0xbe},
}

func init() {
	register(Rule{
		Name:    "no-binary",
		Doc:     "the tree tracks no compiled program (ELF or Mach-O): a build output is ignored, not committed",
		Applies: func(string) bool { return true },
		Check:   noBinary,
	})
}

func noBinary(_ *Repo, p string, text []byte) []Finding {
	for _, magic := range executables {
		if bytes.HasPrefix(text, magic) {
			return []Finding{{Path: p, Line: 1, Rule: "no-binary", Message: "a compiled program is a build output: git rm --cached it and add it to .gitignore"}}
		}
	}
	return nil
}
