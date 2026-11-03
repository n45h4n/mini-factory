#!/usr/bin/env bash
# make update: fast-forward the retained clone on main, offer consented native
# upgrades for the installed tools this installation uses, then rerun make setup,
# which refreshes the managed runtime and ends with the doctor checks.
set -euo pipefail

bundle="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
runtime="${XDG_DATA_HOME:-$HOME/.local/share}/mini-factory"
bin_directory="$HOME/.local/bin"
nm_config="${NM_HOME:-$HOME/.no-mistakes}/config.yaml"
home=''
codex_home=''
upstream=''
remote=''
clone_status=''
apt_refreshed=0
plan_kind=''
plan_text=''
plan_detail=''
plan_manual=''
plan_path=''
upgraded=()
declined=()
skipped=()
manual=()
failed=()

die() {
	printf 'ERROR: %s\n' "$1" >&2
	shift
	[ "$#" -eq 0 ] || printf '%s\n' "$@" >&2
	exit 1
}

notice() {
	printf '%s\n' "$*"
}

clone_git() {
	git -C "$bundle" "$@"
}

physical_path() {
	python3 -I -B -c 'import os, sys; print(os.path.realpath(sys.argv[1]))' "$1" 2>/dev/null
}

check_clone() {
	local top branch
	[ "$(id -u)" != 0 ] || die 'run make update as your regular user, never with sudo or as root'
	if [ -e "$bundle/.mini-factory-install" ] || [ "$bundle" = "$(cd "$runtime" 2>/dev/null && pwd -P)" ]; then
		die 'run make update from your retained mini-factory clone, not the installed runtime copy'
	fi
	if ! top="$(clone_git rev-parse --show-toplevel 2>/dev/null)" || [ "$(cd "$top" && pwd -P)" != "$bundle" ]; then
		die "$bundle is not a Git clone; make update needs your retained mini-factory clone"
	fi
	branch="$(clone_git symbolic-ref --quiet --short HEAD)" ||
		die 'detached HEAD: make update runs only on main and never switches branches.' \
			'Switch yourself (git switch main), then rerun make update.'
	[ "$branch" = main ] ||
		die "on branch $branch: make update runs only on main and never switches branches." \
			'Switch yourself (git switch main), then rerun make update.'
	if ! upstream="$(clone_git rev-parse --abbrev-ref --symbolic-full-name '@{upstream}' 2>/dev/null)" ||
		! remote="$(clone_git config --get branch.main.remote)"; then
		die 'main has no upstream branch to fast-forward from.' \
			'Set it yourself (for example git branch --set-upstream-to=origin/main main), then rerun make update.'
	fi
}

# Tracked edits, staged changes, and untracked files that the incoming commits also touch.
local_files_changed_upstream() {
	local incoming
	incoming="$(clone_git diff --no-renames --name-only HEAD '@{upstream}')"
	[ -n "$incoming" ] || return 0
	{
		clone_git diff --no-renames --name-only HEAD
		clone_git diff --no-renames --name-only --cached HEAD
		clone_git ls-files --others --exclude-standard
	} | awk 'NR == FNR { incoming[$0]; next } ($0 in incoming) && !seen[$0]++' <(printf '%s\n' "$incoming") -
}

# A fast-forward never needs a clean worktree: Git carries unrelated local edits
# (such as the tracked no-mistakes/config.yaml) forward and refuses to overwrite others.
fast_forward() {
	local counts ahead behind before after overlap path stash_command=''
	notice "Fetching $upstream into $bundle"
	clone_git fetch "$remote" ||
		die "git fetch $remote failed; nothing was changed. Check your network and Git access, then rerun make update."
	counts="$(clone_git rev-list --left-right --count 'HEAD...@{upstream}')"
	read -r ahead behind <<<"$counts"
	before="$(clone_git rev-parse --short HEAD)"
	if [ "$behind" -eq 0 ]; then
		clone_status="already up to date with $upstream at $before"
		[ "$ahead" -eq 0 ] || clone_status="$clone_status; $ahead local commit(s) kept"
		notice "Clone: $clone_status."
		return 0
	fi
	[ "$ahead" -eq 0 ] ||
		die "main and $upstream have diverged ($ahead local, $behind upstream commit(s)); a fast-forward is impossible." \
			'Nothing was changed. Integrate them yourself, for example:' \
			"  git rebase $upstream    # or: git merge $upstream" \
			'then resolve any conflicts and rerun make update.'
	overlap="$(local_files_changed_upstream)"
	if [ -n "$overlap" ]; then
		while IFS= read -r path; do
			stash_command="$stash_command $(printf '%q' "$path")"
		done <<<"$overlap"
		die "$upstream changes files that you edited or created locally: ${overlap//$'\n'/, }" \
			'Nothing was changed; your local files are intact. Set them aside yourself, for example:' \
			"  git stash push --include-untracked --$stash_command" \
			'  make update' \
			'  git stash pop    # then resolve any conflict, keeping your settings'
	fi
	# Git overwrites ignored files by default; --no-overwrite-ignore keeps them and stops instead.
	clone_git merge --ff-only --no-autostash --no-overwrite-ignore '@{upstream}' ||
		die "git merge --ff-only $upstream did not complete (see Git's message above); nothing was overwritten." \
			'Resolve it yourself, then rerun make update.'
	after="$(clone_git rev-parse --short HEAD)"
	clone_status="fast-forwarded main $before..$after ($behind commit(s) from $upstream)"
	notice "Clone: $clone_status."
}

# The agents mf-config resolves for issue i/I plus the No-Mistakes pipeline agent and any
# review_agents role harnesses selected in the same YAML.
selected_agents() {
	local role output file="$bundle/no-mistakes/config.yaml"
	selected=''
	for role in issue-prepare issue-implement; do
		if ! output="$(python3 -I -B "$bundle/scripts/mf_config.py" agent "$role" 2>/dev/null)"; then
			notice 'NOTE: the mf-config agent profiles are unreadable, so Claude Code/Cursor were not checked; make setup reports the problem.'
			return 0
		fi
		selected="$selected ${output%%$'\n'*}"
	done
	[ ! -r "$nm_config" ] || file="$nm_config"
	# Reads scalar, flow-list, and block-list (agent: then "- name" lines) values.
	selected="$selected $(awk '/^[ \t]*(#|$)/ { next }
		list && /^[ \t]*-/ { sub(/^[ \t]*-[ \t]*/, ""); sub(/[ \t]*#.*$/, ""); gsub(/["\047]/, ""); print; next }
		{ list = 0 }
		/^[^ \t#]/ { review = /^review_agents:/ }
		/^agent:/ || (review && /^[ \t]+agent:/) { sub(/^[ \t]*agent:[ \t]*/, ""); sub(/[ \t]*#.*$/, ""); list = ($0 == "")
			gsub(/[][,"\047]/, " "); print }' "$file" | tr '\n' ' ') "
}

tool_version() {
	local text=''
	if [ "$1" = gh-dash ]; then
		text="$(gh extension list 2>/dev/null | awk -F '\t' '$2 == "dlvhdr/gh-dash" { print $3 }')" || true
	else
		text="$(NO_MISTAKES_NO_UPDATE_CHECK=1 NO_MISTAKES_TELEMETRY=0 "$1" --version 2>/dev/null)" || true
	fi
	printf '%s\n' "${text%%$'\n'*}"
}

# Gum and GitHub CLI come from Homebrew or apt (as setup installs them); upgrade only the owning package.
plan_package() {
	local tool="$1" real="$2" cellar owner
	if command -v brew >/dev/null 2>&1 && cellar="$(brew --cellar 2>/dev/null)" && cellar="$(physical_path "$cellar")"; then
		case "$real" in
		"$cellar/$tool/"*)
			plan_kind=brew
			plan_text="brew upgrade $tool"
			plan_detail="Homebrew formula $tool; Homebrew may refresh its formula index first, no general brew upgrade"
			return 0
			;;
		esac
	fi
	if [ "$(uname -s)" = Linux ] && command -v dpkg >/dev/null 2>&1 && owner="$(dpkg -S "$real" 2>/dev/null)"; then
		owner="${owner%%: *}"
		case ", $owner," in
		*", $tool,"* | *", $tool:"*)
			if ! command -v sudo >/dev/null 2>&1; then
				plan_manual="apt package $tool, but sudo is unavailable; ask the host administrator to upgrade it"
				return 0
			fi
			plan_kind=apt
			plan_text="sudo apt-get update, then sudo apt-get install --only-upgrade $tool"
			plan_detail="apt package $tool; changes only that system package"
			return 0
			;;
		esac
	fi
	plan_manual="$real is neither a Homebrew formula nor an apt package; update it with the tool that installed it"
}

plan_gh_dash() {
	local list=''
	if ! command -v gh >/dev/null 2>&1; then
		plan_manual='GitHub CLI is missing; make setup installs it and then offers the extension'
		return 0
	fi
	list="$(gh extension list 2>/dev/null)" || true
	if grep -Eq "[[:space:]]dlvhdr/gh-dash([[:space:]]|\$)" <<<"$list"; then
		plan_kind=extension
		plan_text='gh extension upgrade dash'
		plan_detail='the dlvhdr/gh-dash GitHub CLI extension; never --force'
	elif gh dash --version >/dev/null 2>&1; then
		plan_manual='gh dash is not the dlvhdr/gh-dash extension; update it the way you installed it'
	else
		plan_manual='not installed; make setup offers gh extension install dlvhdr/gh-dash'
	fi
}

# Cursor's updater unlinks and relinks agent and cursor-agent, and rewrites its cursor
# shim through any symlink there; each must be absent or Cursor's own.
cursor_commands_owned() {
	local name target versions="$home/.local/share/cursor-agent/versions/" shim="$bin_directory/cursor"
	for name in agent cursor-agent; do
		[ -e "$bin_directory/$name" ] || [ -L "$bin_directory/$name" ] || continue
		[ -L "$bin_directory/$name" ] && target="$(physical_path "$bin_directory/$name")" || return 1
		[ "${target#"$versions"}" != "$target" ] || return 1
	done
	[ -e "$shim" ] || [ -L "$shim" ] || return 0
	[ ! -L "$shim" ] && [ -f "$shim" ] && grep -Fq 'Find cursor executable in PATH, excluding the current shim' "$shim"
}

# Each native updater is offered only for the layout its own installer creates
# (see install_native_tool in setup.sh) and only when the installed CLI lists it.
plan_upgrade() {
	local tool="$1" path real help
	plan_kind='' plan_text='' plan_detail='' plan_manual='' plan_path=''
	if [ "$tool" = gh-dash ]; then
		plan_gh_dash
		return 0
	fi
	if ! path="$(command -v "$tool" 2>/dev/null)"; then
		plan_manual='not installed; make setup offers its installer'
		return 0
	fi
	if ! real="$(physical_path "$path")"; then
		plan_manual="cannot resolve $path; update it with the tool that installed it"
		return 0
	fi
	case "$tool" in
	gh | gum)
		plan_package "$tool" "$real"
		return 0
		;;
	herdr)
		if [ "$real" = "$home/.local/bin/herdr" ]; then
			plan_detail="native installer at $real; no live --handoff is requested"
		fi
		;;
	codex)
		case "$real" in "$codex_home/packages/standalone/"*) plan_detail="standalone installer under $codex_home/packages/standalone" ;; esac
		;;
	no-mistakes)
		if [ "$real" = "$home/.no-mistakes/bin/no-mistakes" ]; then
			plan_detail="native install script at $real; stable releases only, never --beta or --force; it restarts the daemon and refuses while pipeline runs are active"
		fi
		;;
	claude)
		case "$real" in "$home/.local/share/claude/versions/"*) plan_detail="native installer under $home/.local/share/claude" ;; esac
		;;
	cursor-agent)
		case "$real" in "$home/.local/share/cursor-agent/versions/"*)
			if ! cursor_commands_owned; then
				plan_manual="its updater also replaces $bin_directory/agent, $bin_directory/cursor-agent, and $bin_directory/cursor, and one of them is not Cursor's own; resolve that, then update Cursor yourself"
				return 0
			fi
			plan_detail="native installer under $home/.local/share/cursor-agent; also updates its agent command"
			;;
		esac
		;;
	esac
	if [ -z "$plan_detail" ]; then
		plan_manual="$real is not the native installation that '$tool update' manages; update it with the tool that installed it"
		return 0
	fi
	help="$(NO_MISTAKES_NO_UPDATE_CHECK=1 NO_MISTAKES_TELEMETRY=0 "$path" --help 2>&1)" || true
	if ! grep -Eq "^[[:space:]]*(${tool}[[:space:]]+)?update([[:space:]|]|\$)" <<<"$help"; then
		plan_detail=''
		plan_manual="the installed $tool does not list an update command; update it with its native installer"
		return 0
	fi
	plan_kind=native
	plan_path="$path"
	plan_text="$tool update"
}

run_plan() {
	local tool="$1"
	case "$plan_kind" in
	brew) HOMEBREW_NO_INSTALL_CLEANUP=1 brew upgrade "$tool" ;;
	apt)
		if [ "$apt_refreshed" -eq 0 ]; then
			sudo apt-get update || return
			apt_refreshed=1
		fi
		sudo apt-get install -y --only-upgrade --no-install-recommends "$tool"
		;;
	extension) gh extension upgrade dash ;;
	# Keeping the bin directory on PATH avoids the native installers' profile-editing branches, as in setup.
	native) PATH="$bin_directory:$PATH" "$plan_path" update ;;
	esac
}

offer_upgrade() {
	local tool="$1" label="$2" before after status=0 answer
	plan_upgrade "$tool"
	if [ -n "$plan_manual" ]; then
		notice "$label: manual update only: $plan_manual."
		manual+=("$tool")
		return 0
	fi
	before="$(tool_version "$tool")"
	notice "$label (${before:-version unknown}): $plan_detail."
	if [ ! -t 0 ] || [ ! -t 1 ]; then
		notice "  Skipped without an interactive terminal; no approval was assumed. Run $plan_text yourself, or rerun make update in a terminal."
		skipped+=("$tool")
		return 0
	fi
	printf '  Run %s now? It decides itself whether a newer release exists. [y/N] ' "$plan_text"
	IFS= read -r answer || answer=''
	case "$answer" in
	y | Y | yes | YES) ;;
	*)
		notice "  Declined; $label was left unchanged."
		declined+=("$tool")
		return 0
		;;
	esac
	run_plan "$tool" || status=$?
	if [ "$status" -ne 0 ]; then
		notice "  FAILED: $plan_text exited with status $status. It may have changed $label before failing; nothing was rolled back. Setup and doctor below check whether $label still works."
		if [ "$tool" = no-mistakes ]; then
			notice '  If it refused because pipeline runs are active, they were left running: make update never passes --force or --beta. Rerun make update after they finish.'
		fi
		failed+=("$tool")
		return 0
	fi
	after="$(tool_version "$tool")"
	if [ -n "$after" ] && [ "$after" = "$before" ]; then
		notice "  Finished; $label is still $after (already current)."
	else
		notice "  Updated $label: ${before:-unknown} -> ${after:-unknown}."
	fi
	upgraded+=("$tool")
}

offer_upgrades() {
	local selected
	home="$(physical_path "$HOME")" || home="$HOME"
	codex_home="$(physical_path "${CODEX_HOME:-$HOME/.codex}")" || codex_home="${CODEX_HOME:-$HOME/.codex}"
	notice ''
	notice '== Optional native tool upgrades (each needs your consent) =='
	offer_upgrade gh 'GitHub CLI'
	offer_upgrade gh-dash 'gh-dash extension'
	offer_upgrade gum 'Gum'
	offer_upgrade herdr 'Herdr'
	offer_upgrade codex 'Codex'
	offer_upgrade no-mistakes 'No-Mistakes'
	# Unselected agents are never inspected or installed.
	selected_agents
	case "$selected" in *" claude "*) offer_upgrade claude 'Claude Code' ;; esac
	case "$selected" in *" cursor "*) offer_upgrade cursor-agent 'Cursor CLI' ;; esac
}

summary_line() {
	local label="$1"
	shift
	[ "$#" -eq 0 ] || notice "$label: $*"
}

main() {
	local setup_status=0
	[ "$#" -eq 0 ] || die 'usage: scripts/update.sh (run make update)'
	check_clone
	notice '== Mini-Factory clone =='
	fast_forward
	offer_upgrades
	notice ''
	notice '== Refreshing the managed runtime: make setup (ends with the doctor checks) =='
	make --no-print-directory -C "$bundle" setup || setup_status=$?
	notice ''
	notice '== Update summary =='
	notice "Clone: $clone_status."
	summary_line 'Updater completed (updated or already current)' "${upgraded[@]+"${upgraded[@]}"}"
	summary_line 'Declined (left unchanged)' "${declined[@]+"${declined[@]}"}"
	summary_line 'Skipped without a terminal' "${skipped[@]+"${skipped[@]}"}"
	summary_line 'Manual update only (see above)' "${manual[@]+"${manual[@]}"}"
	summary_line 'FAILED optional upgrade (may be partly changed; see setup/doctor above)' "${failed[@]+"${failed[@]}"}"
	if [ "$setup_status" -ne 0 ]; then
		notice "Runtime: make setup did not pass (status $setup_status). Resolve the actions above, then rerun make update or make doctor."
		exit 1
	fi
	notice 'Runtime: make setup passed, including the doctor checks.'
	[ "${#failed[@]}" -eq 0 ] || exit 1
}

# Parse everything before running: the fast-forward may replace this file.
main "$@"
