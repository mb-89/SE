package template

import "path/filepath"

// componentFolder is where the component name is used from for the checkout at root.
func componentFolder(root, name string) string {
	return filepath.Join(root, ".se", "modules", name)
}
