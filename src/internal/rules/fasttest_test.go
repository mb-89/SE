package rules_test

import "testing"

func TestEveryTestRunsInParallelOffTheWallClock(t *testing.T) {
	t.Parallel()
	found := check(t, "fast-test", map[string]string{
		"src/a/a_test.go": "package a_test\n\nimport \"testing\"\n\nfunc TestFast(t *testing.T) {\n\tt.Parallel()\n}\n\n" +
			"func TestSerial(t *testing.T) {\n\tt.Log()\n\tt.Parallel()\n}\n\nfunc TestEmpty(t *testing.T) {}\n\n" +
			"func TestMain(m *testing.M) {}\n\nfunc Testing(t *testing.T) {}\n\nfunc helper(t *testing.T) {}\n\nfunc BenchmarkX(b *testing.B) {}\n",
		"src/a/clock_test.go": "package a_test\n\nimport (\n\t\"testing\"\n\ttm \"time\"\n\n\t\"github.com/mb-89/SE/src/internal/io/clock\"\n)\n\n" +
			"func TestClock(q *testing.T) {\n\tq.Parallel()\n\t_ = tm.Now()\n\ttm.Sleep(tm.Second)\n\t_ = clock.Real()\n\t_ = tm.Now()\n}\n",
		"src/internal/io/clock/real_test.go": "package clock_test\n\nimport (\n\t\"testing\"\n\t\"time\"\n)\n\n" +
			"func TestReal(t *testing.T) {\n\tt.Parallel()\n\t_ = time.Now()\n}\n\nfunc TestSlow(t *testing.T) {}\n",
		"src/a/kept_test.go":            "package a_test\n\nimport \"testing\"\n\nfunc TestKept(t *testing.T) {}\n",
		"src/a/a.go":                    "package a\n\nimport \"testing\"\n\nfunc TestNotATestFile(t *testing.T) {}\n",
		"src/a/broken_test.go":          "not go",
		"src/internal/rules/serial.txt": "# kept until it can run in parallel\nsrc/a/kept_test.go TestKept\n",
	})
	same(t, found, []string{
		"src/a/a_test.go:9: fast-test: TestSerial does not call t.Parallel first",
		"src/a/a_test.go:14: fast-test: TestEmpty does not call t.Parallel first",
		"src/a/clock_test.go:12: fast-test: time.Now reaches the wall clock in a test",
		"src/a/clock_test.go:13: fast-test: time.Sleep reaches the wall clock in a test",
		"src/a/clock_test.go:14: fast-test: clock.Real reaches the wall clock in a test",
		"src/internal/io/clock/real_test.go:13: fast-test: TestSlow does not call t.Parallel first",
	})
}

func TestTheSerialListOnlyShrinks(t *testing.T) {
	t.Parallel()
	found := check(t, "fast-test", map[string]string{
		"src/a/kept_test.go": "package a_test\n\nimport (\n\t\"testing\"\n\t\"time\"\n)\n\nfunc TestKept(t *testing.T) { _ = time.Now() }\n",
		"src/a/done_test.go": "package a_test\n\nimport \"testing\"\n\nfunc TestDone(t *testing.T) {\n\tt.Parallel()\n}\n",
		"src/internal/rules/serial.txt": "# a comment\n\nsrc/a/kept_test.go TestKept\nsrc/a/kept_test.go time.Now\nsrc/a/kept_test.go TestKept\n" +
			"src/a/done_test.go TestDone\nsrc/a/gone_test.go TestGone\njust-one-word\n",
	})
	same(t, found, []string{
		"src/internal/rules/serial.txt:5: fast-test: the entry is named twice",
		"src/internal/rules/serial.txt:6: fast-test: the entry matches nothing: src/a/done_test.go no longer breaks TestDone",
		"src/internal/rules/serial.txt:7: fast-test: the entry names no such file: src/a/gone_test.go",
		"src/internal/rules/serial.txt:8: fast-test: an entry is a test file and what it breaks",
	})
}
