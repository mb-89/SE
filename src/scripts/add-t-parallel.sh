#!/bin/sh
# Inserts t.Parallel() as the first statement of every Go test in the files named that lacks it (#137, the fast-test rule).
for f in "$@"; do
  perl -0pi -e 's/^(func Test\w*\((\w+) \*testing\.T\) \{\n)(?!\t\2\.Parallel\(\)\n)/$1\t$2.Parallel()\n/mg' "$f"
done
