#!/usr/bin/env bash
# Platform and tool-ownership evidence shared by setup.sh and update.sh (which source this file) and
# doctor.py (which runs: bash platform.sh detect | lazy COMMAND... | probes DIRECTORY COMMAND...). Everything here
# only reads local evidence (probes also writes its private directory): nothing installs, updates, or runs the tools
# it inspects.

# Isolated tests point this at a synthetic system root; it is empty (the real /) otherwise.
mf_root="${MINI_FACTORY_TEST_ROOT:-}"
# OS, package, and Omarchy runtime evidence come from these system paths, not from PATH, which a user can shadow.
mf_os_release="$mf_root/etc/os-release"
mf_pacman="$mf_root/usr/bin/pacman"
mf_mise="$mf_root/usr/bin/mise"
mf_omarchy="$mf_root/usr/share/omarchy/bin/omarchy"

# Prints macos, ubuntu, arch, or omarchy and succeeds; otherwise prints why the platform is unsupported and
# fails. Arch means ID=arch itself, not every ID_LIKE=arch derivative. Omarchy is that Arch with both its
# official package (omarchy or omarchy-dev) and its packaged runtime; either one alone is an incomplete
# Omarchy installation, which is refused rather than provisioned as ordinary Arch.
mf_detect_platform() (
	kernel="$(uname -s)"
	architecture="$(uname -m)"
	case "$architecture" in
	x86_64 | amd64 | arm64 | aarch64) ;;
	*)
		printf 'unsupported architecture: %s (supported: x86_64 and arm64; Arch Linux and Omarchy: x86_64)\n' "$architecture"
		exit 1
		;;
	esac
	case "$kernel" in
	Darwin)
		printf 'macos\n'
		exit 0
		;;
	Linux) ;;
	*)
		printf 'unsupported operating system: %s (supported: macOS, native Ubuntu Server, Arch Linux, and Omarchy)\n' "$kernel"
		exit 1
		;;
	esac
	if [ ! -r "$mf_os_release" ]; then
		printf 'cannot identify Linux distribution; native Ubuntu Server 22.04+, Arch Linux, and Omarchy are supported\n'
		exit 1
	fi
	if grep -qi microsoft "$mf_root/proc/sys/kernel/osrelease" 2>/dev/null; then
		printf 'WSL is outside this distribution; use native Ubuntu Server, Arch Linux, Omarchy, or macOS\n'
		exit 1
	fi
	ID=''
	VERSION_ID=''
	# This file is host-owned OS metadata, not a user-provided configuration; this subshell keeps its variables.
	# shellcheck disable=SC1090
	. "$mf_os_release"
	case "$ID" in
	ubuntu)
		case "$VERSION_ID" in
		[2-9][0-9].*) [ "${VERSION_ID%%.*}" -ge 22 ] || {
			printf 'Ubuntu 22.04 or later is required\n'
			exit 1
		} ;;
		*)
			printf 'Ubuntu 22.04 or later is required\n'
			exit 1
			;;
		esac
		printf 'ubuntu\n'
		;;
	arch)
		case "$architecture" in
		x86_64 | amd64) ;;
		*)
			printf 'Arch Linux and Omarchy are supported on x86_64 only (found %s; Arch Linux ARM is outside this distribution)\n' "$architecture"
			exit 1
			;;
		esac
		package=0
		runtime=0
		if [ -x "$mf_pacman" ] && { [ "$("$mf_pacman" -Qq omarchy 2>/dev/null)" = omarchy ] ||
			[ "$("$mf_pacman" -Qq omarchy-dev 2>/dev/null)" = omarchy-dev ]; }; then
			package=1
		fi
		if [ -f "$mf_omarchy" ] && [ -x "$mf_omarchy" ]; then
			runtime=1
		fi
		case "$package$runtime" in
		11) printf 'omarchy\n' ;;
		00) printf 'arch\n' ;;
		10)
			printf 'incomplete Omarchy installation: the omarchy package is installed but its runtime %s is missing; repair Omarchy itself (for example reinstall its package with sudo pacman -S omarchy), then rerun make setup\n' "$mf_omarchy"
			exit 1
			;;
		*)
			printf 'incomplete Omarchy installation: %s exists but no omarchy or omarchy-dev package is installed; repair Omarchy itself, then rerun make setup\n' "$mf_omarchy"
			exit 1
			;;
		esac
		;;
	*)
		printf 'unsupported Linux distribution%s; native Ubuntu Server 22.04+, Arch Linux (ID=arch, not its derivatives), and Omarchy are supported\n' "${ID:+ ($ID)}"
		exit 1
		;;
	esac
)

# The pacman package that owns a file, read from the system package database; fails for unowned files.
mf_pacman_owner() {
	local owner
	[ -x "$mf_pacman" ] || return 1
	owner="$("$mf_pacman" -Qqo -- "$1" 2>/dev/null)" || return 1
	owner="${owner%%$'\n'*}"
	[ -n "$owner" ] || return 1
	printf '%s\n' "$owner"
}

# Omarchy's own mise (its mise-bin package) when present; elsewhere whichever mise PATH finds.
mf_mise_command() {
	if [ -f "$mf_mise" ] && [ -x "$mf_mise" ]; then
		printf '%s\n' "$mf_mise"
	else
		command -v mise
	fi
}

# The mise data directories whose shims and command wrappers are mise launchers.
mf_mise_data_directories() {
	printf '%s\n' "${MISE_DATA_DIR:-${XDG_DATA_HOME:-$HOME/.local/share}/mise}" "$HOME/.local/share/mise"
}

# A mise command wrapper, such as Omarchy's agent-account wrappers for Claude and Codex.
mf_is_mise_wrapper() {
	local data
	while IFS= read -r data; do
		case "$1" in "$data/command-wrappers/"*) return 0 ;; esac
	done < <(mf_mise_data_directories)
	return 1
}

# The file a path ends at once its symbolic links are followed (portably: no readlink -f). Only read, never run.
mf_link_target() {
	local path="$1" target count=0
	while [ -L "$path" ] && [ "$count" -lt 40 ]; do
		target="$(readlink "$path")" || return 1
		case "$target" in
		/*) path="$target" ;;
		*) path="$(dirname "$path")/$target" ;;
		esac
		count=$((count + 1))
	done
	printf '%s\n' "$path"
}

# Whether a script runs mise with one of the given subcommands (an extended regular expression, such as use|x) as
# a statement, as omarchy-mise-install's launchers do (mise use -g ..., exec mise x ...); a comment or text that only
# mentions one does not count. Only read, never run.
mf_runs_mise() {
	# Process substitution, not a pipe: grep -q may stop reading early, which pipefail would report as failure.
	LC_ALL=C grep -aqE "^[[:space:]]*(exec[[:space:]]+)?mise[[:space:]]+($2)[[:space:]]" < <(head -c 4096 -- "$1" 2>/dev/null)
}

# A mise launcher installs its tool first whenever it runs (Omarchy's lazy tools): a mise shim (a link to mise),
# a mise command wrapper, or an omarchy-mise-install script that runs mise use or mise x, also through your own link
# to that script. Only read, never run.
mf_is_mise_launcher() {
	local path="$1" data
	mf_is_mise_wrapper "$path" && return 0
	while IFS= read -r data; do
		case "$path" in "$data/shims/"*) return 0 ;; esac
	done < <(mf_mise_data_directories)
	if [ -L "$path" ]; then
		# A link that ends at mise itself is a shim; any other is read as the file it ends at, so a link to a native
		# executable stays your own command.
		path="$(mf_link_target "$path")" || return 1
		[ "$(basename "$path")" != mise ] || return 0
	fi
	[ -f "$path" ] && mf_runs_mise "$path" 'use|x'
}

# The tool request and executable of a launcher script's mise x statement as omarchy-mise-install writes it,
# exec mise x "PACKAGE" -- "BIN" "$@" (PACKAGE may pin a version, such as gh@2.46.0), printed as REQUEST<TAB>BIN;
# fails for a script without one. Only read, never run.
mf_launcher_request() {
	local line pattern='^[[:space:]]*(exec[[:space:]]+)?mise[[:space:]]+x[[:space:]]+"?([^"[:space:]]+)"?[[:space:]]+--[[:space:]]+"?([^"[:space:]]+)"?([[:space:]]|$)'
	mf_runs_mise "$1" x || return 1
	while IFS= read -r line || [ -n "$line" ]; do
		[[ "$line" =~ $pattern ]] || continue
		printf '%s\t%s\n' "${BASH_REMATCH[2]}" "${BASH_REMATCH[3]}"
		return 0
	done < <(head -c 4096 -- "$1" 2>/dev/null)
	return 1
}

# The installed executable that the mise launcher at the second argument's path runs for the named command, resolved
# as mf_mise_installed resolves it. A launcher script's own mise x statement decides it (its explicit gh@2.46.0 runs
# that version, whichever one mise selects here); any other launcher runs the version mise selects for the command.
mf_launcher_installed() {
	local path request
	path="$(mf_link_target "$2")" || return 1
	if ! mf_is_mise_wrapper "$2" && [ "$(basename "$path")" != mise ] && [ -f "$path" ] &&
		request="$(mf_launcher_request "$path")"; then
		mf_mise_installed "${request#*$'\t'}" "${request%%$'\t'*}"
	else
		mf_mise_installed "${1##*/}"
	fi
}

# The mise tool request that mise install installs for the launcher at the second argument's path, as
# mf_launcher_installed resolves it: a launcher script's own mise x request (its explicit gh@2.88.1 is exactly that
# version), any other launcher's command tool (npm's is node), the version mise selects here. Only read, never run.
mf_launcher_install_request() {
	local path request
	path="$(mf_link_target "$2")" || return 1
	if ! mf_is_mise_wrapper "$2" && [ "$(basename "$path")" != mise ] && [ -f "$path" ] &&
		request="$(mf_launcher_request "$path")"; then
		printf '%s\n' "${request%%$'\t'*}"
	elif [ "${1##*/}" = npm ]; then
		printf 'node\n'
	else
		printf '%s\n' "${1##*/}"
	fi
}

# The installed executable behind a mise launcher, resolved offline in the current directory and environment, as
# a launcher run from here selects its version: mise which prints only an already installed binary, so this
# fails while the selected version is not installed (even if another directory's version is). An optional tool
# request (the second argument, such as gh@2.46.0) selects that version instead, as mise x runs it.
mf_mise_installed() {
	local mise resolved
	mise="$(mf_mise_command)" || return 1
	resolved="$(MISE_OFFLINE=1 "$mise" which ${2:+"--tool=$2"} "$1" 2>/dev/null)" || return 1
	case "$resolved" in
	/*) ;;
	*) return 1 ;;
	esac
	case "$resolved" in *$'\n'*) return 1 ;; esac
	[ -f "$resolved" ] && [ -x "$resolved" ] && ! mf_is_mise_launcher "$resolved" || return 1
	printf '%s\n' "$resolved"
}

# The native installation a mise command wrapper runs, read without running it. A wrapper runs the tool mise
# selects here (installing it first if needed); when mise selects none (you disabled its tool), it runs the next
# command of that name on PATH, such as your own native installation, a compatible override this prints. Fails
# when mise selects the tool, or no such installation exists.
mf_wrapper_provider() {
	local name="$1" mise selected directory candidate
	local directories=()
	mise="$(mf_mise_command)" || return 1
	selected="$(MISE_OFFLINE=1 "$mise" current "$name" 2>/dev/null)" || return 1
	[ -z "$selected" ] || return 1
	IFS=: read -r -a directories <<<"$PATH"
	for directory in "${directories[@]}"; do
		candidate="${directory:-.}/$name"
		[ -f "$candidate" ] && [ -x "$candidate" ] || continue
		mf_is_mise_launcher "$candidate" && continue
		printf '%s\n' "$candidate"
		return 0
	done
	return 1
}

# The installed tool behind a launcher script that runs mise use (as omarchy-mise-install does), also through your
# own link to that script, read without running it. Such a script writes your global mise configuration (mise use -g)
# every time it runs, even once its tool is installed and offline, so read-only checks run the tool it would run
# instead. Fails (1) for any other command (such as mise's shims, links to mise that only run their tool), and (2)
# for such a launcher whose tool cannot be resolved, as while it is not installed yet: running it is never safe.
mf_configuring_launcher_tool() {
	local path
	path="$(command -v "$1" 2>/dev/null)" || return 1
	! mf_is_mise_wrapper "$path" || return 1
	if [ -L "$path" ]; then
		path="$(mf_link_target "$path")" || return 1
		[ "$(basename "$path")" != mise ] || return 1
	fi
	[ -f "$path" ] && mf_runs_mise "$path" use || return 1
	mf_launcher_installed "$1" "$path" || return 2
}

# REQUEST<TAB>BIN of the mise x statement in the launcher that writes mise configuration (see above) a command runs,
# once its tool is installed, so the approved npm actions can run that statement without the launcher's mise use;
# fails for any other command. Only read, never run.
mf_configuring_launcher_request() {
	local path
	mf_configuring_launcher_tool "$1" >/dev/null && path="$(command -v "$1")" && path="$(mf_link_target "$path")" &&
		mf_launcher_request "$path"
}

# Prints NAME<TAB>TOOL for each named command whose launcher writes mise configuration (see above), and NAME alone
# for such a launcher whose tool cannot be resolved, which no check may run.
mf_configuring_launchers() {
	local name tool
	for name in "$@"; do
		if tool="$(mf_configuring_launcher_tool "$name")"; then
			printf '%s\t%s\n' "$name" "$tool"
		elif [ "$?" -eq 2 ]; then
			printf '%s\n' "$name"
		fi
	done
	return 0
}

# Prints what mf_configuring_launchers prints and places in the directory (the first argument) a probe for each such
# command name whose tool resolves, so checks and approved actions run that tool behind the directory on PATH. A probe
# runs the launcher's own mise x statement, offline and without its mise use, on the installed tool: the version the
# launcher selects, with the environment mise gives it (such as GH_CONFIG_DIR or a registry from mise's [env]), as the
# launcher (and so ghd) runs it, while mise installs, updates, and configures nothing. A mise x of your own records
# trust for the project configurations it loads, so where mise env (which records none) finds one you have not
# trusted, the probe runs in mise's safe mode, which records no trust and ignores project configuration. A launcher
# without such a statement, or a directory where scripts cannot run (such as a noexec TMPDIR, where command lookup
# would skip the probe), gets a link to the installed tool. A configured path (such as an absolute acpx_path) gets no
# probe. Fails when a probe cannot be placed, so no caller runs that launcher instead.
mf_link_configuring_launchers() {
	local directory="$1" name tool request mise
	shift
	while IFS=$'\t' read -r name tool; do
		printf '%s\n' "$name${tool:+$'\t'$tool}"
		[ -n "$tool" ] || continue
		case "$name" in */*) continue ;; esac
		if request="$(mf_configuring_launcher_request "$name")" && mise="$(mf_mise_command)"; then
			printf '#!/bin/sh\nMISE_OFFLINE=1 %q env </dev/null >/dev/null 2>&1 || { MISE_SAFE=1; export MISE_SAFE; }\nMISE_OFFLINE=1 exec %q x %q -- %q "$@"\n' \
				"$mise" "$mise" "${request%%$'\t'*}" "$tool" >"$directory/$name" && chmod 755 "$directory/$name" || return 1
			[ -x "$directory/$name" ] && continue
			rm -f -- "$directory/$name" || return 1
		fi
		ln -s -- "$tool" "$directory/$name" || return 1
	done < <(mf_configuring_launchers "$@")
	return 0
}

# Prints each named command that PATH resolves to a mise launcher whose tool is not installed yet, so running
# it, even for --version or --help, would install it first.
mf_lazy_pending() {
	local name path
	for name in "$@"; do
		path="$(command -v "$name" 2>/dev/null)" || continue
		mf_is_mise_launcher "$path" || continue
		mf_launcher_installed "$name" "$path" >/dev/null && continue
		mf_is_mise_wrapper "$path" && mf_wrapper_provider "$name" >/dev/null && continue
		printf '%s\n' "$name"
	done
	return 0
}

if [ "${BASH_SOURCE[0]}" = "$0" ]; then
	case "${1-}" in
	detect)
		[ "$#" -eq 1 ] || exit 2
		mf_detect_platform
		;;
	lazy)
		shift
		mf_lazy_pending "$@"
		;;
	configuring)
		shift
		mf_configuring_launchers "$@"
		;;
	probes)
		[ "$#" -ge 2 ] && [ -d "$2" ] || exit 2
		shift
		mf_link_configuring_launchers "$@"
		;;
	*)
		printf 'usage: platform.sh detect | lazy COMMAND... | configuring COMMAND... | probes DIRECTORY COMMAND...\n' >&2
		exit 2
		;;
	esac
fi
