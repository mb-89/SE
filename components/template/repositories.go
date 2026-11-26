package template

import (
	"context"
	"fmt"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strconv"
	"strings"

	"github.com/pelletier/go-toml/v2"
	"kern/git"
)

// Template repositories (docs/templates.md "Template repositories") and the read at origin's
// integration branch: the catalog a name resolves from for the checkout at root, as templates.py
// `catalog` reads it. The project's own templates/ first, at origin/<integration branch> where that
// holds a template note, else from the working tree; then each repository se.toml
// `[templates] repositories` lists, each a component pinned and placed as se_modules.py
// `template_repositories` requires; then SE's own. The first layer that holds a name is its
// template's.

// CatalogAt is the catalog of the checkout at root, whose own templates' marker names repository,
// beside SE's checkout at se.
func CatalogAt(root, repository, se string) (Catalog, error) {
	own := repository == SERepository
	files, err := templateFiles(root)
	if err != nil {
		if own {
			return nil, err
		}
		files = map[string]string{} // a project without templates/ of its own
	}
	layers := []Layer{{repository, files, func(name string) string { return TemplatesFolder + "/" + name }}}
	listed, err := templateRepositories(root)
	if err != nil {
		return nil, fail("templates: %s", err)
	}
	for _, r := range listed {
		files, err := folderFiles(r.folder)
		if err != nil {
			return nil, err
		}
		name := r.name
		layers = append(layers, Layer{name, files, func(file string) string { return name + ":" + TemplatesFolder + "/" + file }})
	}
	if !own {
		files, err := templateFiles(se)
		if err != nil {
			return nil, err
		}
		layers = append(layers, Layer{SERepository, files, func(name string) string { return SERepository + ":" + TemplatesFolder + "/" + name }})
	}
	return Load(layers...)
}

func templateFile(name string) bool {
	return strings.HasSuffix(name, templateSuffix) || name == TermsFile
}

// templateFiles is templates.py `_template_files`: templates/ at origin's integration branch where
// that holds a template note, else the working tree's.
func templateFiles(root string) (map[string]string, error) {
	if files := gitFiles(root); len(files) > 0 {
		return files, nil
	}
	folder := filepath.Join(root, TemplatesFolder)
	if info, err := os.Stat(folder); err != nil || !info.IsDir() {
		return nil, fail("templates: %s does not exist; run from an SE checkout", folder)
	}
	return folderFiles(folder)
}

func folderFiles(folder string) (map[string]string, error) {
	entries, err := os.ReadDir(folder)
	if err != nil {
		return map[string]string{}, nil
	}
	files := map[string]string{}
	for _, entry := range entries {
		name := entry.Name()
		if !templateFile(name) {
			continue
		}
		info, err := os.Stat(filepath.Join(folder, name))
		if err != nil || !info.Mode().IsRegular() {
			continue
		}
		data, err := os.ReadFile(filepath.Join(folder, name))
		if err != nil {
			return nil, err
		}
		files[name] = normalizeNewlines(string(data))
	}
	for _, entry := range entries { // each template manifest's notes, as <folder>/<note>
		sub := filepath.Join(folder, entry.Name())
		if info, err := os.Stat(filepath.Join(sub, manifestFile)); !entry.IsDir() || err != nil || !info.Mode().IsRegular() {
			continue
		}
		notes, err := os.ReadDir(sub)
		if err != nil {
			continue
		}
		for _, note := range notes {
			info, err := os.Stat(filepath.Join(sub, note.Name()))
			if !strings.HasSuffix(note.Name(), templateSuffix) || err != nil || !info.Mode().IsRegular() {
				continue
			}
			data, err := os.ReadFile(filepath.Join(sub, note.Name()))
			if err != nil {
				return nil, err
			}
			files[entry.Name()+"/"+note.Name()] = normalizeNewlines(string(data))
		}
	}
	return files, nil
}

// integrationBranch is se.toml [project] integration_branch, main where it names none.
func integrationBranch(root string) string {
	data, err := readTOML(filepath.Join(root, "se.toml"))
	if err != nil {
		return "main"
	}
	project, ok := data["project"].(map[string]any)
	if !ok {
		return "main"
	}
	if branch, ok := project["integration_branch"].(string); ok && strip(branch) != "" {
		return strip(branch)
	}
	return "main"
}

// gitFiles is templates.py `_git_files`: templates/<file> at origin's integration branch, through
// kern's git door; none where that ref holds no template note.
func gitFiles(root string) map[string]string {
	ref := "origin/" + integrationBranch(root)
	ctx := context.Background()
	listed, err := git.Run(ctx, "", "-C", root, "ls-tree", "-r", "--name-only", ref, "--", TemplatesFolder)
	if err != nil {
		return nil
	}
	files := map[string]string{}
	note := false
	paths := splitLines(listed, false)
	manifests := map[string]bool{}
	for _, path := range paths {
		if name, found := strings.CutPrefix(path, TemplatesFolder+"/"); found && strings.Count(path, "/") == 2 && strings.HasSuffix(path, "/"+manifestFile) {
			manifests[strings.SplitN(name, "/", 2)[0]] = true
		}
	}
	for _, path := range paths {
		name, found := strings.CutPrefix(path, TemplatesFolder+"/")
		top := strings.Count(path, "/") == 1 && templateFile(name)
		nested := strings.Count(path, "/") == 2 && manifests[strings.SplitN(name, "/", 2)[0]] && strings.HasSuffix(name, templateSuffix)
		if !found || !(top || nested) {
			continue
		}
		shown, err := git.Run(ctx, "", "-C", root, "show", ref+":"+path)
		if err != nil {
			continue
		}
		files[name] = normalizeNewlines(strings.ToValidUTF8(shown, "�"))
		note = note || strings.HasSuffix(name, templateSuffix)
	}
	if !note {
		return nil
	}
	return files
}

// se_modules.py's reading of the components: se.toml [components], se.lock and the machine's
// ~/.se/local.toml [paths].

type component struct {
	name, ref, path, version, gomod string
}

// pin is how the host's list states a component's pin.
func (c component) pin() string {
	switch {
	case c.gomod != "":
		return c.gomod + " v" + c.version
	case c.version != "":
		return c.version
	}
	return "ref " + prefix(c.ref, 12)
}

func prefix(text string, n int) string {
	if len(text) > n {
		return text[:n]
	}
	return text
}

// moduleError is se_modules.py's ModuleError.
type moduleError struct{ msg string }

func (e *moduleError) Error() string { return e.msg }

func moduleFail(format string, args ...any) error { return &moduleError{fmt.Sprintf(format, args...)} }

var (
	componentName = regexp.MustCompile(`^[A-Za-z0-9][A-Za-z0-9-]{0,31}$`)
	shaPattern    = regexp.MustCompile(`^[0-9a-fA-F]{40}$`)
	versionText   = regexp.MustCompile(`^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$`)
	rangeText     = regexp.MustCompile(`^([\^~=]?)(0|[1-9][0-9]*)(?:\.(0|[1-9][0-9]*))?(?:\.(0|[1-9][0-9]*))?$`)
	goRequire     = regexp.MustCompile(`^(?:require` + pyS + `+)?(` + pyNotS + `+)` + pyS + `+v(` + pyNotS + `+)(?:` + pyS + `*//.*)?$`)
	tableHeader   = regexp.MustCompile(`(?m)^[ \t]*\[[ \t]*components[ \t]*\.[ \t]*("?)([^\]"\s]+)("?)[ \t]*\]`)
	componentKeys = []string{"ref", "version", "path", "go", "optional"}
	localKeys     = []string{"paths", "urls", "integrator_session", "trackers", "worktree_roots", "repos", "mirrors", "public_identity", "hooks"}
)

const renamed = `[modules] is [components] since se 8: rename each [modules.<name>] to [components.<name>] and drop its url, as a component is found by its name (docs/modules.md "Modules")`

// localConfig is where the machine's settings are: ~/.se/local.toml.
var localConfig = func() string {
	home, err := os.UserHomeDir()
	if err != nil {
		return ""
	}
	return filepath.Join(home, ".se", "local.toml")
}

func readTOML(path string) (map[string]any, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	found := map[string]any{}
	if err := toml.Unmarshal(data, &found); err != nil {
		return nil, moduleFail("%s: %v", path, err)
	}
	return found, nil
}

func isFile(path string) bool {
	info, err := os.Stat(path)
	return err == nil && info.Mode().IsRegular()
}

func isDir(path string) bool {
	info, err := os.Stat(path)
	return err == nil && info.IsDir()
}

type version [3]int

func parseVersion(v any) (version, bool) {
	text, ok := v.(string)
	if !ok {
		return version{}, false
	}
	m := versionText.FindStringSubmatch(text)
	if m == nil {
		return version{}, false
	}
	var found version
	for i := range found {
		found[i], _ = strconv.Atoi(m[i+1])
	}
	return found, true
}

func less(a, b version) bool {
	for i := range a {
		if a[i] != b[i] {
			return a[i] < b[i]
		}
	}
	return false
}

// versionBounds is se_modules.py `version_bounds`: the versions [low, high) a range admits.
func versionBounds(name, text string) (version, version, error) {
	m := rangeText.FindStringSubmatch(text)
	if m == nil {
		return version{}, version{}, moduleFail("module %s: version must be a semver range such as ^1.4, ~1.4.2 or 1.4.2, got %s", name, repr(text))
	}
	operator := m[1]
	major, _ := strconv.Atoi(m[2])
	minor, _ := strconv.Atoi(m[3])
	patch, _ := strconv.Atoi(m[4])
	hasMinor, hasPatch := m[3] != "", m[4] != ""
	low := version{major, minor, patch}
	if operator == "=" && !hasPatch {
		return low, low, moduleFail("module %s: =%s needs MAJOR.MINOR.PATCH", name, text[1:])
	}
	if operator == "^" {
		switch {
		case major != 0 || !hasMinor:
			return low, version{major + 1, 0, 0}, nil
		case low[1] != 0 || !hasPatch:
			return low, version{0, low[1] + 1, 0}, nil
		}
		return low, version{0, 0, low[2] + 1}, nil
	}
	if hasPatch && operator != "~" {
		return low, version{low[0], low[1], low[2] + 1}, nil
	}
	if hasMinor {
		return low, version{major, low[1] + 1, 0}, nil
	}
	return low, version{major + 1, 0, 0}, nil
}

// subpath is se_modules.py `_check_subpath`.
func subpath(name string, value any) (string, error) {
	text, ok := value.(string)
	if !ok || text == "" {
		return "", moduleFail("module %s: path must be a non-empty string", name)
	}
	windows := len(text) >= 3 && text[1] == ':' && (text[2] == '\\' || text[2] == '/') ||
		strings.HasPrefix(text, `\\`) || strings.HasPrefix(text, "//")
	parent := false
	for _, part := range strings.Split(text, "/") {
		parent = parent || part == ".."
	}
	if strings.HasPrefix(text, "/") || windows || parent {
		return "", moduleFail("module %s: path must be relative inside the module: %s", name, text)
	}
	return text, nil
}

// goRequireIn is se_modules.py `go_require_in`: the go.mod a `go` pin names and the exact version
// it requires of the module.
func goRequireIn(root, where, name string, value any) (string, string, error) {
	relative := ""
	switch v := value.(type) {
	case bool:
		if !v {
			return "", "", moduleFail("module %s: go must be true or a relative path to a go.mod", name)
		}
		relative = "go.mod"
	case string:
		if v == "" {
			return "", "", moduleFail("module %s: go must be true or a relative path to a go.mod", name)
		}
		var err error
		if relative, err = subpath(name, v); err != nil {
			return "", "", err
		}
	default:
		return "", "", moduleFail("module %s: go must be true or a relative path to a go.mod", name)
	}
	data, err := os.ReadFile(filepath.Join(root, filepath.FromSlash(relative)))
	if err != nil {
		return "", "", moduleFail("module %s: no %s in %s, which go names", name, relative, where)
	}
	block := false
	for _, line := range splitLines(string(data), false) {
		bare := strip(line)
		if strings.HasPrefix(bare, "require (") {
			block = true
			continue
		}
		if block && bare == ")" {
			block = false
			continue
		}
		if !(block || strings.HasPrefix(bare, "require ")) {
			continue
		}
		if block {
			bare = "require " + bare
		}
		if m := goRequire.FindStringSubmatch(bare); m != nil && m[1] == name {
			if _, ok := parseVersion(m[2]); !ok {
				return "", "", moduleFail("module %s: %s requires %s v%s, not vMAJOR.MINOR.PATCH", name, relative, name, m[2])
			}
			return relative, m[2], nil
		}
	}
	return "", "", moduleFail("module %s: %s has no require %s v<version>; add one", name, relative, name)
}

// readLock is se_modules.py `read_lock`: se.lock's (version, commit) per component.
func readLock(root string) (map[string][2]string, error) {
	path := filepath.Join(root, "se.lock")
	entries := map[string][2]string{}
	if !isFile(path) {
		return entries, nil
	}
	data, err := readTOML(path)
	if err != nil {
		return nil, err
	}
	tables, _ := data["components"].(map[string]any)
	for _, name := range sortedKeys(tables) {
		table, _ := tables[name].(map[string]any)
		ref, isText := table["ref"].(string)
		if _, ok := parseVersion(table["version"]); !ok || !isText || !shaPattern.MatchString(ref) {
			return nil, moduleFail("%s: [components.%s] needs version and a full commit ref; delete it and run sync", path, name)
		}
		entries[name] = [2]string{table["version"].(string), strings.ToLower(ref)}
	}
	return entries, nil
}

// manifestOrder is the order se.toml names its components in: Python's tomllib keeps the file's.
func manifestOrder(text string, tables map[string]any) []string {
	var order []string
	for _, m := range tableHeader.FindAllStringSubmatch(text, -1) {
		if _, ok := tables[m[2]]; ok && !in(m[2], order) {
			order = append(order, m[2])
		}
	}
	for _, name := range sortedKeys(tables) {
		if !in(name, order) {
			order = append(order, name)
		}
	}
	return order
}

// loadManifest is se_modules.py `load_manifest`: the components se.toml lists, checked, each
// range's lock applied.
func loadManifest(root string) ([]component, error) {
	path := filepath.Join(root, "se.toml")
	text, err := os.ReadFile(path)
	if err != nil {
		return nil, moduleFail("no se.toml in %s", root)
	}
	data, err := readTOML(path)
	if err != nil {
		return nil, err
	}
	if _, ok := data["modules"]; ok {
		return nil, moduleFail("%s: %s", path, renamed)
	}
	locked, err := readLock(root)
	if err != nil {
		return nil, err
	}
	raw, has := data["components"]
	tables, ok := raw.(map[string]any)
	if has && !ok {
		return nil, moduleFail("se.toml: [components] must be a table")
	}
	var found []component
	for _, name := range manifestOrder(string(text), tables) {
		if !componentName.MatchString(name) {
			return nil, moduleFail("component name %s in se.toml: 1 to 32 letters, digits and '-', starting with a letter or digit, as its repository is named", repr(name))
		}
		table, ok := tables[name].(map[string]any)
		if !ok {
			return nil, moduleFail("component %s: [components.%s] must be a table", name, name)
		}
		if _, ok := table["url"]; ok {
			return nil, moduleFail(`component %s: url is refused in se.toml: a component is found by its name under the owners of the checkout's remotes (docs/components.md "Finding a component"); a machine that needs another place sets [paths] or [urls] in ~/.se/local.toml`, name)
		}
		var unknown []string
		for key := range table {
			if !in(key, componentKeys) {
				unknown = append(unknown, key)
			}
		}
		if len(unknown) > 0 {
			sort.Strings(unknown)
			return nil, moduleFail("component %s: unknown key(s) %s", name, joinStrings(unknown))
		}
		if optional, ok := table["optional"]; ok {
			if _, isBool := optional.(bool); !isBool {
				return nil, moduleFail("component %s: optional must be true or false", name)
			}
		}
		ref, hasRef := table["ref"]
		ver, hasVersion := table["version"]
		c := component{name: name}
		if p, ok := table["path"]; ok {
			if c.path, err = subpath(name, p); err != nil {
				return nil, err
			}
		}
		lock := locked[name]
		if pin, ok := table["go"]; ok {
			if hasRef || hasVersion {
				return nil, moduleFail("component %s: go pins the version; drop ref and version", name)
			}
			gomod, exact, err := goRequireIn(root, "se.toml", name, pin)
			if err != nil {
				return nil, err
			}
			c.gomod, c.version = gomod, exact
			if lock[0] == exact {
				c.ref = lock[1]
			}
			found = append(found, c)
			continue
		}
		if hasVersion {
			if hasRef {
				return nil, moduleFail("component %s: pin either ref or version, not both", name)
			}
			text, isText := ver.(string)
			if !isText {
				return nil, moduleFail(`component %s: version must be a semver range string such as "^1.4"`, name)
			}
			low, high, err := versionBounds(name, text)
			if err != nil {
				return nil, err
			}
			c.version = text
			if v, ok := parseVersion(lock[0]); ok && !less(v, low) && less(v, high) {
				c.ref = lock[1]
			}
			found = append(found, c)
			continue
		}
		text, isText := ref.(string)
		if !isText || text == "" {
			return nil, moduleFail("component %s: ref or version is required", name)
		}
		if !shaPattern.MatchString(text) {
			return nil, moduleFail("component %s: ref must be a full commit SHA, got %s", name, repr(text))
		}
		c.ref = strings.ToLower(text)
		found = append(found, c)
	}
	return found, nil
}

// localPaths is ~/.se/local.toml [paths], each resolved from the file's folder, as se_modules.py
// `load_local` reads it.
func localPaths() (map[string]string, error) {
	config := localConfig()
	paths := map[string]string{}
	if config == "" || !isFile(config) {
		return paths, nil
	}
	data, err := readTOML(config)
	if err != nil {
		return nil, err
	}
	var unknown []string
	for key := range data {
		if !in(key, localKeys) {
			unknown = append(unknown, key)
		}
	}
	if len(unknown) > 0 {
		sort.Strings(unknown)
		return nil, moduleFail("%s: unknown section(s) %s", config, joinStrings(unknown))
	}
	for _, key := range []string{"paths", "urls"} {
		table, has := data[key]
		values, ok := table.(map[string]any)
		if has && !ok {
			return nil, moduleFail("%s: [%s] must map names to strings", config, key)
		}
		for _, v := range values {
			if _, ok := v.(string); !ok {
				return nil, moduleFail("%s: [%s] must map names to strings", config, key)
			}
		}
	}
	if table, has := data["hooks"]; has {
		hooks, ok := table.(map[string]any)
		good := ok
		for key, v := range hooks {
			switch v.(type) {
			case string, bool:
			default:
				good = false
			}
			good = good && key == "core"
		}
		if !good {
			return nil, moduleFail(`%s: [hooks] holds only core, as a string or a boolean (core = "off")`, config)
		}
	}
	values, _ := data["paths"].(map[string]any)
	for name, v := range values {
		path := v.(string)
		if path == "~" || strings.HasPrefix(path, "~/") {
			if home, err := os.UserHomeDir(); err == nil {
				path = filepath.Join(home, strings.TrimPrefix(path, "~"))
			}
		}
		if !filepath.IsAbs(path) {
			path = filepath.Join(filepath.Dir(config), path)
		}
		path = filepath.Clean(path)
		if resolved, err := filepath.EvalSymlinks(path); err == nil {
			path = resolved
		}
		paths[name] = path
	}
	return paths, nil
}

type templateRepository struct{ name, folder string }

// templateRepositories is se_modules.py `template_repositories`: each repository se.toml
// `[templates] repositories` lists, in its order, with its templates/ on this machine; a name that
// is no component, a clone not placed at its pin or one without templates/ refuses.
func templateRepositories(root string) ([]templateRepository, error) {
	manifest := filepath.Join(root, "se.toml")
	if !isFile(manifest) {
		return nil, nil
	}
	data, err := readTOML(manifest)
	if err != nil {
		return nil, err
	}
	const where = "se.toml [templates] repositories"
	table, _ := data["templates"].(map[string]any)
	raw, has := table["repositories"]
	if !has {
		return nil, nil
	}
	list, ok := raw.([]any)
	var listed []string
	for _, v := range list {
		name, isText := v.(string)
		ok = ok && isText && name != ""
		listed = append(listed, name)
	}
	if !ok {
		return nil, moduleFail(`%s must be a list of component names, such as ["templates"]`, where)
	}
	seen := map[string]bool{}
	for _, name := range listed {
		seen[strings.ToLower(name)] = true
	}
	if len(seen) != len(listed) {
		return nil, moduleFail("%s names a repository twice; list each once, in the order names resolve", where)
	}
	if len(listed) == 0 {
		return nil, nil
	}
	paths, err := localPaths()
	if err != nil {
		return nil, err
	}
	components, err := loadManifest(root)
	if err != nil {
		return nil, err
	}
	byName := map[string]component{}
	for _, c := range components {
		byName[strings.ToLower(c.name)] = c
	}
	var found []templateRepository
	for _, name := range listed {
		c, ok := byName[strings.ToLower(name)]
		if !ok {
			return nil, moduleFail(`template repository %s: %s lists it, but se.toml declares no [components.%s]; pin it there with ref or version as any component (docs/modules.md "Modules")`, name, where, name)
		}
		checkout, local := paths[c.name], true
		if !isDir(checkout) {
			checkout, local = filepath.Join(root, ".se", "modules", c.name), false
		}
		sync := fmt.Sprintf("run `se_modules.py sync %s`", c.name)
		if !local {
			if c.ref == "" {
				return nil, moduleFail("template repository %s: version %s is not locked; %s, which locks and places it", c.name, c.version, sync)
			}
			if !isFile(filepath.Join(checkout, ".git", "index")) && !isDir(filepath.Join(checkout, ".git", "index")) {
				return nil, moduleFail("template repository %s: its pin %s is not fetched into %s; %s. Where sync cannot fetch it, no remote offers the pin: a private repository needs this machine's access to it, or the pin names a commit no owner holds and moves with `se_modules.py update %s`",
					c.name, c.pin(), checkout, sync, c.name)
			}
			out, err := git.RunEnv(context.Background(), checkout, []string{"GIT_TERMINAL_PROMPT=0"}, "rev-parse", "HEAD")
			if err != nil {
				detail := strip(out)
				if e, ok := err.(*git.Error); ok && strip(e.Stderr) != "" {
					detail = strip(e.Stderr)
				}
				return nil, moduleFail("git rev-parse HEAD failed in %s: %s", checkout, detail)
			}
			if head := strip(out); strings.ToLower(head) != c.ref {
				return nil, moduleFail("template repository %s: its clone is at %s, its pin at %s; %s", c.name, prefix(head, 12), prefix(c.ref, 12), sync)
			}
		}
		dir := checkout
		if c.path != "" {
			dir = filepath.Join(checkout, filepath.FromSlash(c.path))
		}
		folder := filepath.Join(dir, TemplatesFolder)
		if !isDir(folder) {
			return nil, moduleFail("template repository %s: %s holds no %s/ at its pin; pin a release that has one, or take %s out of %s", c.name, dir, TemplatesFolder, c.name, where)
		}
		found = append(found, templateRepository{c.name, folder})
	}
	return found, nil
}

// componentFolder is where the component name is used from for the checkout at root: the machine's
// [paths] checkout where it has one, else its pinned clone .se/modules/<name>.
func componentFolder(root, name string) string {
	if paths, err := localPaths(); err == nil && isDir(paths[name]) {
		return paths[name]
	}
	return filepath.Join(root, ".se", "modules", name)
}
