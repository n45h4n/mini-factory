#!/usr/bin/env bash
# Platform and tool-ownership evidence shared by setup.sh and update.sh (which source this file) and doctor.py
# (which runs: bash platform.sh detect). Everything here only reads local evidence: nothing installs, updates, or runs
# the tools it inspects.

# Isolated tests point this at a synthetic system root; it is empty (the real /) otherwise.
mf_root="${MINI_FACTORY_TEST_ROOT:-}"
# OS, package, and Omarchy runtime evidence come from these system paths, not from PATH, which a user can shadow.
mf_os_release="$mf_root/etc/os-release"
mf_pacman="$mf_root/usr/bin/pacman"
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
		# name keeps the installed package, which a repair reinstalls.
		for name in omarchy omarchy-dev; do
			if [ -x "$mf_pacman" ] && [ "$("$mf_pacman" -Qq "$name" 2>/dev/null)" = "$name" ]; then
				package=1
				break
			fi
		done
		if [ -f "$mf_omarchy" ] && [ -x "$mf_omarchy" ]; then
			runtime=1
		fi
		case "$package$runtime" in
		11) printf 'omarchy\n' ;;
		00)
			# Omarchy before 4.0 ran from a git checkout in your home directory, before it was packaged.
			if [ -f "$HOME/.local/share/omarchy/bin/omarchy" ]; then
				printf 'legacy Omarchy installation: %s predates the packaged Omarchy that setup supports; update Omarchy to its current release (omarchy update), then rerun make setup\n' "$HOME/.local/share/omarchy"
				exit 1
			fi
			printf 'arch\n'
			;;
		10)
			printf 'incomplete Omarchy installation: the %s package is installed but its runtime %s is missing; repair Omarchy itself (for example reinstall its package with sudo pacman -S %s), then rerun make setup\n' "$name" "$mf_omarchy" "$name"
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

# mise's data directory: its shims (how mise, and so Omarchy, provides lazy tools that install on first run), its
# installs, and the command wrappers Omarchy uses for agent account switching.
mf_mise_data() {
	printf '%s\n' "${MISE_DATA_DIR:-${XDG_DATA_HOME:-$HOME/.local/share}/mise}"
}

# The named command PATH finds past Omarchy's agent account wrappers, which lead PATH and run the command found past
# them (Omarchy's own resolution): the installation whose owner decides its updates.
mf_past_wrappers() {
	local entry wrappers
	local entries=()
	wrappers="$(mf_mise_data)/command-wrappers/bin"
	IFS=: read -r -a entries <<<"$PATH"
	for entry in "${entries[@]+"${entries[@]}"}"; do
		case "$entry" in "$wrappers" | "$HOME/.local/share/omarchy/agent-accounts/bin") continue ;; esac
		[ -f "${entry:-.}/$1" ] && [ -x "${entry:-.}/$1" ] || continue
		printf '%s\n' "${entry:-.}/$1"
		return 0
	done
	return 1
}

# The manager of an installed command, judged from its path and the file that path ends at (never by running it):
# mise for its shims (also Omarchy's system_shims_dir, ~/.local/share/mise/shims) and installs, or pacman:PACKAGE for a
# packaged file. Fails for any other installation.
mf_tool_manager() {
	local path="$1" real="$2" owner
	case "$path" in "$(mf_mise_data)/shims/"* | "$HOME/.local/share/mise/shims/"*)
		printf 'mise\n'
		return 0
		;;
	esac
	case "$real" in "$(mf_mise_data)/installs/"* | */mise/installs/*)
		printf 'mise\n'
		return 0
		;;
	esac
	owner="$(mf_pacman_owner "$real")" || owner="$(mf_pacman_owner "$path")" || return 1
	printf 'pacman:%s\n' "$owner"
}

# How make update reports a command its manager owns (on the named platform); fails for any other installation. Their
# native updaters would install a copy the manager does not track, and make update never upgrades system packages.
mf_update_hint() {
	local path="$1" real="$2" platform="$3" manager
	manager="$(mf_tool_manager "$path" "$real")" || return 1
	case "$platform:$manager" in
	omarchy:mise) printf '%s is managed by mise for Omarchy: omarchy update updates it' "$path" ;;
	*:mise) printf '%s is managed by mise: update it with mise (for example mise upgrade)' "$path" ;;
	omarchy:pacman:*) printf '%s belongs to pacman package %s, which omarchy update updates' "$real" "${manager#pacman:}" ;;
	*) printf '%s belongs to pacman package %s: update it with a full system upgrade (sudo pacman -Syu), or for an AUR package the way you installed it' "$real" "${manager#pacman:}" ;;
	esac
}

if [ "${BASH_SOURCE[0]}" = "$0" ]; then
	if [ "$*" != detect ]; then
		printf 'usage: platform.sh detect\n' >&2
		exit 2
	fi
	mf_detect_platform
fi
