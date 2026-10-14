#!/bin/sh
# Why: #115 needed the wall time and gh call count of se briefing, before and after, and which calls sit on its critical path.
# Usage: sh src/scripts/profile-gh-calls.sh <se binary> <se arguments...>
# Runs se with gh wrapped, then prints the wall time, the call count, and each
# call's start, end and duration in seconds from the first call, by start.
set -eu
dir=$(mktemp -d)
log="$dir/calls"
real=$(command -v gh)
cat >"$dir/gh" <<WRAP
#!/bin/sh
s=\$(date +%s.%N)
"$real" "\$@"; rc=\$?
echo "\$s \$(date +%s.%N) \$*" >>"$log"
exit \$rc
WRAP
chmod +x "$dir/gh"
: >"$log"
se=$1
shift
start=$(date +%s.%N)
PATH="$dir:$PATH" "$se" "$@" >/dev/null
end=$(date +%s.%N)
echo "wall: $(echo "$end - $start" | bc)s, gh calls: $(wc -l <"$log")"
sort -n "$log" | awk 'NR==1{t0=$1} {printf "%6.2f %6.2f %5.2f %s\n", $1-t0, $2-t0, $2-$1, $NF}'
rm -rf "$dir"
