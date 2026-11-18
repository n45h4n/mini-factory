#!/usr/bin/env bash
# Platform and tool-ownership evidence shared by setup.sh and update.sh (which source this file) and
# doctor.py (which runs: bash platform.sh detect | lazy COMMAND...). Everything here only reads local
# evidence: nothing installs, updates, or runs the tools it inspects.

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

# A mise launcher installs its tool first whenever it runs (Omarchy's lazy tools): a mise shim (a link to mise),
# a mise command wrapper, or an omarchy-mise-install script that runs mise use or mise x. Only read, never run.
mf_is_mise_launcher() {
	local path="$1" data target count=0
	mf_is_mise_wrapper "$path" && return 0
	while IFS= read -r data; do
		case "$path" in "$data/shims/"*) return 0 ;; esac
	done < <(mf_mise_data_directories)
	if [ -L "$path" ]; then
		# Any other link is the user's own command unless it ends at mise itself.
		while [ -L "$path" ] && [ "$count" -lt 40 ]; do
			target="$(readlink "$path")" || return 1
			case "$target" in
			/*) path="$target" ;;
			*) path="$(dirname "$path")/$target" ;;
			esac
			count=$((count + 1))
		done
		[ "$(basename "$path")" = mise ]
		return
	fi
	# Process substitution, not a pipe: grep -q may stop reading early, which pipefail would report as failure.
	[ -f "$path" ] && LC_ALL=C grep -aqE 'mise (use|x) ' < <(head -c 4096 -- "$path" 2>/dev/null)
}

# The installed executable behind a mise launcher, resolved offline in the current directory and environment, as
# a launcher run from here selects its version: mise which prints only an already installed binary, so this
# fails while the selected version is not installed (even if another directory's version is).
mf_mise_installed() {
	local mise resolved
	mise="$(mf_mise_command)" || return 1
	resolved="$(MISE_OFFLINE=1 "$mise" which "$1" 2>/dev/null)" || return 1
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

# The installed tool behind a launcher script that runs mise use (as omarchy-mise-install does), read without
# running it. Such a script writes your global mise configuration (mise use -g) every time it runs, even once its
# tool is installed and offline, so read-only checks run the tool it would run instead. Fails for any other command
# (such as mise's shims, which only run their tool) or while the tool is not installed yet.
mf_configuring_launcher_tool() {
	local path
	path="$(command -v "$1" 2>/dev/null)" || return 1
	[ -f "$path" ] && [ ! -L "$path" ] && ! mf_is_mise_wrapper "$path" || return 1
	LC_ALL=C grep -aqE 'mise use ' < <(head -c 4096 -- "$path" 2>/dev/null) || return 1
	mf_mise_installed "$1"
}

# Prints NAME<TAB>TOOL for each named command whose launcher writes mise configuration (see above).
mf_configuring_launchers() {
	local name tool
	for name in "$@"; do
		tool="$(mf_configuring_launcher_tool "$name")" || continue
		printf '%s\t%s\n' "$name" "$tool"
	done
	return 0
}

# Prints each named command that PATH resolves to a mise launcher whose tool is not installed yet, so running
# it, even for --version or --help, would install it first.
mf_lazy_pending() {
	local name path
	for name in "$@"; do
		path="$(command -v "$name" 2>/dev/null)" || continue
		mf_is_mise_launcher "$path" || continue
		mf_mise_installed "$name" >/dev/null && continue
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
	*)
		printf 'usage: platform.sh detect | lazy COMMAND... | configuring COMMAND...\n' >&2
		exit 2
		;;
	esac
fi
