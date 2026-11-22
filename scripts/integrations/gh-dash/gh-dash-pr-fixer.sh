#!/usr/bin/env bash
set -euo pipefail

# Entry point of the optional PR Fixer safeguards: the implementer's handoff and the fixer's evidence,
# budgeted push, and final verdict. The helper is resolved from this bundle, never from the environment.
helper="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd -P)/pr_fixer.py"
[ -f "$helper" ] && [ ! -L "$helper" ] || {
	printf 'ERROR: %s: missing helper: %s\n' "${0##*/}" "$helper" >&2
	exit 1
}
command -v python3 >/dev/null 2>&1 || {
	printf 'ERROR: %s: python3 >= 3.9 is required; run make setup\n' "${0##*/}" >&2
	exit 1
}
exec python3 -I -B "$helper" "$@"
