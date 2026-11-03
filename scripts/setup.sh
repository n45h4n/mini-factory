#!/usr/bin/env bash
set -euo pipefail

bundle="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
runtime="${XDG_DATA_HOME:-$HOME/.local/share}/mini-factory"
bin_directory="$HOME/.local/bin"
launcher="$bin_directory/ghd"
parent_path="$PATH"
install_marker='mini-factory-v1'
agent_setting="${XDG_CONFIG_HOME:-$HOME/.config}/mini-factory/issue-agent"
nm_home="${NM_HOME:-$HOME/.no-mistakes}"
nm_config="$nm_home/config.yaml"
nm_source="$bundle/no-mistakes/config.yaml"
nm_backup="$nm_config.mini-factory-backup"
nm_template_agent='agent: codex # Initialize to the chosen pipeline agent during first setup.'
issue_agent=''
prepare_agent=''
implement_agent=''
review_agent=''
role_agents=()
duty_agents=()
# The No-Mistakes daemon runs as a user service started with this fixed PATH (its
# shellenv.WellKnownBinDirsForHome), then adopts its login shell's PATH with these appended; only these
# remain when that probe fails. acpx (global acpx_path when set, run verbatim) and the node it starts must
# run from the resulting daemon_path, which nm-config daemon-path resolves the same way.
service_path="$bin_directory:$HOME/go/bin:$HOME/.cargo/bin:$HOME/bin:/opt/homebrew/bin:/opt/homebrew/sbin:/usr/local/bin:/usr/local/sbin:/usr/bin:/bin:/usr/sbin:/sbin"
acpx_path=acpx
daemon_path="$service_path"
stage=''
backup=''
launcher_stage=''
replacement_started=0
replacement_complete=0
pending=0

die() {
	printf 'ERROR: %s\n' "$*" >&2
	exit 1
}

notice() {
	printf '%s\n' "$*"
}

consent() {
	local answer
	notice "$1"
	if [ ! -t 0 ] || [ ! -t 1 ]; then
		notice 'Consent pending: rerun make setup in an interactive terminal. No approval was assumed.'
		return 1
	fi
	printf 'Proceed? [y/N] '
	IFS= read -r answer || return 1
	case "$answer" in
	y | Y | yes | YES) return 0 ;;
	*) notice 'Declined; existing configuration was preserved.'; return 1 ;;
	esac
}

cleanup() {
	local status=$?
	trap - EXIT HUP INT TERM
	if [ "$replacement_complete" -eq 0 ] && { [ "$replacement_started" -eq 1 ] || { [ -n "$backup" ] && [ -d "$backup/runtime" ]; }; }; then
		if [ -d "$runtime" ] && [ ! -L "$runtime" ] &&
			[ "$(cat "$runtime/.mini-factory-install" 2>/dev/null || true)" = "$install_marker" ]; then
			rm -rf -- "$runtime"
		fi
		if [ -n "$backup" ] && [ -d "$backup/runtime" ]; then
			mv -- "$backup/runtime" "$runtime" || notice "Recovery required: restore $backup/runtime to $runtime"
		fi
	fi
	[ -z "$stage" ] || rm -rf -- "$stage"
	[ -z "$launcher_stage" ] || rm -f -- "$launcher_stage"
	if [ -n "$backup" ] && [ ! -d "$backup/runtime" ]; then
		rmdir -- "$backup" 2>/dev/null || true
	fi
	exit "$status"
}

trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' HUP TERM

detect_platform() {
	local kernel architecture
	kernel="$(uname -s)"
	architecture="$(uname -m)"
	case "$architecture" in
	x86_64 | amd64 | arm64 | aarch64) ;;
	*) die "unsupported architecture: $architecture (supported: x86_64 and arm64)" ;;
	esac
	case "$kernel" in
	Darwin) platform=macos ;;
	Linux)
		[ -r /etc/os-release ] || die 'cannot identify Linux distribution; native Ubuntu Server 22.04+ is supported'
		# This file is host-owned OS metadata, not a user-provided configuration.
		# shellcheck disable=SC1091
		. /etc/os-release
		[ "${ID:-}" = ubuntu ] || die 'unsupported Linux distribution; native Ubuntu Server 22.04+ is supported'
		case "${VERSION_ID:-}" in
		[2-9][0-9].*) [ "${VERSION_ID%%.*}" -ge 22 ] || die 'Ubuntu 22.04 or later is required' ;;
		*) die 'Ubuntu 22.04 or later is required' ;;
		esac
		if grep -qi microsoft /proc/sys/kernel/osrelease 2>/dev/null; then
			die 'WSL is outside this distribution; use native Ubuntu Server or macOS'
		fi
		platform=ubuntu
		;;
	*) die "unsupported operating system: $kernel (supported: macOS and native Ubuntu Server)" ;;
	esac
}

check_destinations() {
	local existing quoted expected
	case "$HOME:$runtime" in
	/*:/*) ;;
	*) die 'HOME and XDG_DATA_HOME must be absolute paths' ;;
	esac
	[ "$(id -u)" != 0 ] || die 'run make setup as your regular user, never with sudo or as root'
	if [ -e "$runtime" ] || [ -L "$runtime" ]; then
		[ -d "$runtime" ] && [ ! -L "$runtime" ] && [ -O "$runtime" ] ||
			die "refusing unrelated or unsafe installation path: $runtime"
		[ -f "$runtime/.mini-factory-install" ] && [ ! -L "$runtime/.mini-factory-install" ] &&
			[ "$(cat "$runtime/.mini-factory-install")" = "$install_marker" ] ||
			die "refusing unrelated existing installation directory: $runtime"
	fi
	printf -v quoted '%q' "$runtime/bin/ghd"
	expected="$(printf '#!/usr/bin/env bash\n# mini-factory managed launcher v1\nexec %s "$@"\n' "$quoted")"
	if [ -e "$launcher" ] || [ -L "$launcher" ]; then
		[ -f "$launcher" ] && [ ! -L "$launcher" ] && [ -O "$launcher" ] &&
			[ "$(cat "$launcher")" = "$expected" ] || die "refusing unrelated existing launcher: $launcher"
	fi
	existing="$(command -v ghd 2>/dev/null || true)"
	[ -z "$existing" ] || [ "$existing" = "$launcher" ] ||
		die "an unrelated ghd command is already on PATH: $existing; resolve the conflict before setup"
}

check_source_clone() {
	case "$agent_setting:$nm_home" in
	/*:/*) ;;
	*) die 'XDG_CONFIG_HOME and NM_HOME must be absolute paths' ;;
	esac
	# The No-Mistakes config link targets this clone, so setup must not run from the runtime copy.
	[ "$bundle" != "$(cd "$runtime" 2>/dev/null && pwd -P)" ] ||
		die 'run make setup from your retained mini-factory clone, not the installed runtime copy'
	[ -f "$nm_source" ] && [ ! -L "$nm_source" ] ||
		die "missing tracked No-Mistakes config: $nm_source; run make setup from your mini-factory clone"
}

select_issue_agent() {
	local saved=''
	case "${PR_REVIEW_AGENT:-}" in
	'' | claude | codex | cursor) ;;
	*) die 'PR_REVIEW_AGENT must be claude, codex, or cursor' ;;
	esac
	if [ -e "$agent_setting" ] || [ -L "$agent_setting" ]; then
		[ -f "$agent_setting" ] || die "issue agent setting is not a regular file: $agent_setting"
		IFS= read -r saved <"$agent_setting" || true
	fi
	case "${ISSUE_AGENT:-}" in
	'') issue_agent="$saved" ;;
	claude | codex | cursor) issue_agent="$ISSUE_AGENT" ;;
	*) die 'ISSUE_AGENT must be claude, codex, or cursor' ;;
	esac
	case "$issue_agent" in
	claude | codex | cursor) ;;
	'') issue_agent=codex ;;
	*) die "invalid saved issue agent in $agent_setting; rerun make setup ISSUE_AGENT=claude|codex|cursor" ;;
	esac
	if [ "$issue_agent" != "$saved" ]; then
		mkdir -p -- "$(dirname "$agent_setting")"
		printf '%s\n' "$issue_agent" >"$agent_setting.$$"
		mv -f -- "$agent_setting.$$" "$agent_setting"
	fi
	notice "Shared issue agent: $issue_agent (saved in $agent_setting; change it with make setup ISSUE_AGENT=claude|codex|cursor). A per-key mf-config selection takes precedence."
}

contains() {
	local item="$1" existing
	shift
	for existing in "$@"; do
		[ "$existing" != "$item" ] || return 0
	done
	return 1
}

# mf-config resolves each gh-dash role's harness (issue keys: per-key selection, shared agent,
# Codex; PR reviewer: its selection, Codex). PR_REVIEW_AGENT is saved as that selection;
# setup never rewrites an issue key's selection.
select_role_agents() {
	local role output kind
	if [ -n "${PR_REVIEW_AGENT:-}" ]; then
		output="$(python3 -I -B "$bundle/scripts/mf_config.py" set-agent pr-review "$PR_REVIEW_AGENT" 2>&1)" ||
			die "cannot save PR_REVIEW_AGENT in the mf-config agent profiles: $output"
		notice "PR reviewer selection $PR_REVIEW_AGENT ${output%%:*} (mf-config profile; Codex is the default)."
	fi
	for role in issue-prepare issue-implement pr-review; do
		output="$(python3 -I -B "$bundle/scripts/mf_config.py" agent "$role" 2>&1)" ||
			die "cannot read the mf-config agent profiles: $output"
		kind="${output%%$'\n'*}"
		case "$kind" in
		claude | codex | cursor) ;;
		*) die "unexpected mf-config agent for $role: $output" ;;
		esac
		case "$role" in
		issue-prepare) prepare_agent="$kind" ;;
		issue-implement) implement_agent="$kind" ;;
		*) review_agent="$kind" ;;
		esac
		contains "$kind" "${role_agents[@]+"${role_agents[@]}"}" || role_agents+=("$kind")
	done
	notice "Issues i preparer: $prepare_agent; Issues I implementer: $implement_agent; PRs I reviewer: $review_agent (see mf-config show)."
}

# Only first-time linking of an unedited template follows the issue agent. Rewriting the template line
# records initialization, so later relinks (for example after moving the clone) never change the agent.
initialize_pipeline_agent() {
	local content
	grep -qxF "$nm_template_agent" "$nm_source" || return 0
	content="$(awk -v template="$nm_template_agent" -v replacement="agent: $issue_agent # Initialized from the issue agent during first setup." \
		'$0 == template { print replacement; next } { print }' "$nm_source")"
	printf '%s\n' "$content" >"$nm_source"
	notice "Initialized the No-Mistakes pipeline agent in $nm_source to $issue_agent; later setup runs keep your edits."
}

link_no_mistakes_config() {
	if [ -L "$nm_config" ] && [ "$(readlink "$nm_config")" = "$nm_source" ]; then
		return 0
	fi
	if [ -e "$nm_config" ] || [ -L "$nm_config" ]; then
		if [ -e "$nm_backup" ] || [ -L "$nm_backup" ]; then
			notice "Remaining action: $nm_config is not linked to $nm_source and backup $nm_backup already exists. Move one of them aside yourself, then rerun make setup."
			pending=1
			return 0
		fi
		if ! consent "Link $nm_config to $nm_source? The existing entry is first renamed to $nm_backup (a symbolic link is renamed, never followed). Afterwards edit the tracked file and keep this clone in place."; then
			notice "Remaining action: link $nm_config to $nm_source (rerun make setup)"
			pending=1
			return 0
		fi
		mv -- "$nm_config" "$nm_backup"
	else
		if ! consent "Create $nm_config as a link to $nm_source? Edit that tracked file to change No-Mistakes settings, and keep this clone in place."; then
			notice "Remaining action: link $nm_config to $nm_source (rerun make setup)"
			pending=1
			return 0
		fi
		(umask 077; mkdir -p -- "$nm_home")
	fi
	initialize_pipeline_agent
	ln -s -- "$nm_source" "$nm_config"
	notice "Linked: $nm_config -> $nm_source"
}

# No-Mistakes runs its own agents without Herdr: the pipeline agent and any review roles. nm-config
# reads them; setup checks login for those that are Codex, Claude Code, or Cursor (including acp:cursor).
read_duty_agents() {
	local file="$nm_source" output duty agent kind
	[ ! -r "$nm_config" ] || file="$nm_config"
	if ! output="$(python3 -I -B "$bundle/scripts/nm_config.py" duties "$file" 2>&1)"; then
		notice "Remaining action: No-Mistakes agents not checked: ${output#nm-config: }. Write agent and review_agents in block form (as nm-config does) so their login can be checked."
		pending=1
		return 0
	fi
	while IFS=$'\t' read -r duty agent kind; do
		if [ "$kind" = - ]; then
			notice "No-Mistakes $duty: $agent (not provisioned by setup; log in through its native CLI, doctor relies on native no-mistakes doctor for it)."
		elif [ -n "$kind" ]; then
			contains "$kind" "${duty_agents[@]+"${duty_agents[@]}"}" || duty_agents+=("$kind")
		fi
	done <<<"$output"
	[ "${#duty_agents[@]}" -eq 0 ] || notice "No-Mistakes agents needing login: ${duty_agents[*]} (no Herdr integration needed)."
}

# No-Mistakes runs its ACP agents (Cursor) with global acpx_path when set, otherwise acpx from its PATH.
read_acpx_path() {
	local file="$nm_source" output
	[ ! -r "$nm_config" ] || file="$nm_config"
	if ! output="$(python3 -I -B "$bundle/scripts/nm_config.py" acpx-path "$file" 2>&1)"; then
		notice "Remaining action: No-Mistakes acpx_path not checked: ${output#nm-config: }. Write it as one plain value."
		acpx_path=''
		pending=1
	elif [ "$output" != acpx ]; then
		acpx_path="$output"
		notice "No-Mistakes acpx_path: $acpx_path (used instead of acpx from the daemon's PATH; setup never installs over it)."
	fi
}

python_is_suitable() {
	command -v python3 >/dev/null 2>&1 &&
		python3 -I -c 'import sys; raise SystemExit(sys.version_info < (3, 9))' >/dev/null 2>&1
}

git_is_suitable() {
	command -v git >/dev/null 2>&1 || return 1
	git --version | awk 'NR == 1 {split($3,v,"."); exit !(v[1] > 2 || (v[1] == 2 && v[2] >= 29))}'
}

# Gum provides the mf-config and nm-config editors; no version floor, only a runnable command.
gum_is_suitable() {
	command -v gum >/dev/null 2>&1 && gum --version >/dev/null 2>&1
}

gh_is_suitable() {
	command -v gh >/dev/null 2>&1 || return 1
	gh --version | awk 'NR == 1 {split($3,v,"."); exit !(v[1] > 2 || (v[1] == 2 && v[2] >= 47))}'
}

install_dependencies() {
	local command_name package proposal
	local packages=()
	local installs=() upgrades=() reinstalls=()
	for command_name in bash awk sed grep tr mkdir rmdir rm date chmod sleep nohup stat env mktemp cp mv cat dirname uname id; do
		command -v "$command_name" >/dev/null 2>&1 || die "required system utility missing: $command_name; repair OS prerequisites first"
	done
	for command_name in make jq curl tar; do
		if ! command -v "$command_name" >/dev/null 2>&1; then
			packages[${#packages[@]}]="$command_name"
		fi
	done
	git_is_suitable || packages[${#packages[@]}]=git
	python_is_suitable || packages[${#packages[@]}]=python3
	if [ "$platform" = macos ]; then
		gh_is_suitable || packages[${#packages[@]}]=gh
		gum_is_suitable || packages[${#packages[@]}]=gum
		if [ "${#packages[@]}" -gt 0 ]; then
			command -v brew >/dev/null 2>&1 || die 'Homebrew is required for missing dependencies; follow the macOS bootstrap instructions in README.md'
			proposal='Homebrew changes for missing/unsuitable dependencies only:'
			for package in "${packages[@]}"; do
				if [ "$package" = gum ] && brew list --versions gum >/dev/null 2>&1; then
					# An installed but unrunnable Gum is repaired, not merely upgraded.
					reinstalls[${#reinstalls[@]}]=gum
					proposal="$proposal brew reinstall gum (mf-config/nm-config editors);"
				elif brew list --versions "$package" >/dev/null 2>&1; then
					upgrades[${#upgrades[@]}]="$package"
					proposal="$proposal brew upgrade $package;"
				else
					installs[${#installs[@]}]="$package"
					proposal="$proposal brew install $package;"
				fi
			done
			if consent "$proposal No general brew update/upgrade or shell edits."; then
				if [ "${#installs[@]}" -gt 0 ]; then
					HOMEBREW_NO_AUTO_UPDATE=1 HOMEBREW_NO_INSTALL_CLEANUP=1 brew install "${installs[@]}"
				fi
				if [ "${#upgrades[@]}" -gt 0 ]; then
					HOMEBREW_NO_AUTO_UPDATE=1 HOMEBREW_NO_INSTALL_CLEANUP=1 brew upgrade "${upgrades[@]}"
				fi
				if [ "${#reinstalls[@]}" -gt 0 ]; then
					HOMEBREW_NO_AUTO_UPDATE=1 HOMEBREW_NO_INSTALL_CLEANUP=1 brew reinstall "${reinstalls[@]}"
				fi
			else
				die "dependencies pending: ${packages[*]}"
			fi
		fi
	else
		[ -r /etc/ssl/certs/ca-certificates.crt ] || packages[${#packages[@]}]=ca-certificates
		if [ "${#packages[@]}" -gt 0 ]; then
			command -v sudo >/dev/null 2>&1 || die 'sudo is required to install missing Ubuntu packages; ask the host administrator'
			if consent "Use sudo apt-get update, then sudo apt-get install --no-install-recommends ${packages[*]}. This changes system packages."; then
				sudo apt-get update
				sudo apt-get install -y --no-install-recommends "${packages[@]}"
			else
				die "dependencies pending: ${packages[*]}"
			fi
		fi
		if ! gh_is_suitable; then
			command -v sudo >/dev/null 2>&1 || die 'sudo is required for the official GitHub CLI apt repository'
			if consent 'Install GitHub CLI from its official apt repository. This writes /etc/apt/keyrings/githubcli-archive-keyring.gpg and /etc/apt/sources.list.d/github-cli.list, then runs sudo apt-get update and sudo apt-get install gh.'; then
				install_github_cli_ubuntu
			else
				die 'GitHub CLI installation pending'
			fi
		fi
		gum_is_suitable || install_gum_ubuntu
	fi
	python_is_suitable || die 'python3 still resolves to a version below 3.9; fix PATH to use the installed Python and rerun'
	git_is_suitable || die 'git must be version 2.29 or later; fix PATH to the suitable installation and rerun'
	gh_is_suitable || die 'gh must be version 2.47 or later; fix PATH to the suitable installation and rerun'
	gum_is_suitable || die "gum still cannot run; fix PATH (an unrelated gum may shadow it: $(command -v gum || printf 'none found')) and rerun"
	select_role_agents
	# All three agent CLIs are baseline, so any role can switch later without another install;
	# only the agents a role or No-Mistakes duty uses need login.
	install_tools codex claude cursor-agent herdr no-mistakes
	# Any installed release with the stable interface is reused, including a newer prerelease; only an older one is updated.
	if ! no_mistakes_is_suitable; then
		if consent "The installed No-Mistakes lacks the stable no-mistakes axi run --intent/--yes interface used by issue I. Run its native updater, no-mistakes update, to install the latest stable release? It restarts the daemon and refuses while pipeline runs are active."; then
			no-mistakes update || die 'no-mistakes update did not complete; resolve its reported blocker (for example wait for active runs to finish) and rerun make setup'
		else
			die 'No-Mistakes with axi run --intent and --yes is required; rerun make setup to update it natively'
		fi
		no_mistakes_is_suitable || die 'No-Mistakes still lacks axi run --intent and --yes; fix PATH or update it natively and rerun'
	fi
}

install_tools() {
	local command_name installer directory
	for command_name in "$@"; do
		if ! command -v "$command_name" >/dev/null 2>&1; then
			case "$command_name" in
			codex) installer='https://chatgpt.com/codex/install.sh'; directory="${CODEX_HOME:-$HOME/.codex}" ;;
			herdr) installer='https://herdr.dev/install.sh'; directory="$bin_directory" ;;
			claude) installer='https://claude.ai/install.sh'; directory="$HOME/.local/share/claude and $HOME/.claude" ;;
			cursor-agent) installer='https://cursor.com/install'; directory="$HOME/.local/share/cursor-agent (it also links $bin_directory/agent)" ;;
			no-mistakes) installer='https://raw.githubusercontent.com/kunchenguid/no-mistakes/main/docs/install.sh'; directory="$HOME/.no-mistakes and starts its background daemon as a user service" ;;
			esac
			if consent "Install $command_name using its upstream native installer ($installer). Commands go in $bin_directory; $command_name also manages its native files under $directory. No shell configuration changes are needed."; then
				install_native_tool "$command_name" "$installer"
			else
				die "$command_name installation pending"
			fi
		fi
		"$command_name" --version >/dev/null 2>&1 || die "$command_name is installed but cannot run; repair it using its native installer"
	done
}

# A capability check, not a version floor: stable releases document axi run --intent and --yes.
no_mistakes_is_suitable() {
	local help flag pattern
	help="$(NO_MISTAKES_NO_UPDATE_CHECK=1 NO_MISTAKES_TELEMETRY=0 no-mistakes axi run --help 2>/dev/null)" || return 1
	for flag in --intent --yes; do
		# An exact flag: --intent-file alone is not the stable interface.
		pattern="${flag}([^[:alnum:]_-]|\$)"
		[[ "$help" =~ $pattern ]] || return 1
	done
}

install_github_cli_ubuntu() {
	local scratch repository_line
	scratch="$(mktemp -d "${TMPDIR:-/tmp}/mini-factory-gh.XXXXXX")"
	if ! curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg -o "$scratch/keyring.gpg"; then
		rm -rf -- "$scratch"
		return 1
	fi
	repository_line="deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main"
	printf '%s\n' "$repository_line" >"$scratch/github-cli.list"
	sudo mkdir -p -m 755 /etc/apt/keyrings /etc/apt/sources.list.d
	sudo install -m 644 "$scratch/keyring.gpg" /etc/apt/keyrings/githubcli-archive-keyring.gpg
	sudo install -m 644 "$scratch/github-cli.list" /etc/apt/sources.list.d/github-cli.list
	rm -rf -- "$scratch"
	sudo apt-get update
	sudo apt-get install -y --no-install-recommends gh
}

# Newer Ubuntu releases carry Gum in universe; older ones use Charm's official apt repository.
# madison lists only repository-provided versions, unlike policy's Candidate, which can be
# an installed-only version whose repository was removed.
gum_in_ubuntu_archive() {
	[ -n "$(apt-cache madison gum 2>/dev/null)" ]
}

install_gum_ubuntu() {
	local scratch
	local install_arguments=(apt-get install -y --no-install-recommends gum)
	command -v sudo >/dev/null 2>&1 || die 'sudo is required to install Gum; ask the host administrator'
	# An installed but unrunnable package is repaired by reinstalling it.
	! command -v gum >/dev/null 2>&1 || install_arguments=(apt-get install -y --reinstall --no-install-recommends gum)
	if gum_in_ubuntu_archive; then
		consent "Gum provides the mf-config and nm-config editors. Run sudo ${install_arguments[*]} from your configured Ubuntu archive? This changes system packages." ||
			die 'Gum installation pending'
		sudo "${install_arguments[@]}"
		return
	fi
	consent "Gum provides the mf-config and nm-config editors and is not in your configured Ubuntu archive. Install it from Charm's official apt repository? This writes /etc/apt/keyrings/charm.asc and /etc/apt/sources.list.d/charm.list, then runs sudo apt-get update and sudo ${install_arguments[*]}." ||
		die 'Gum installation pending'
	scratch="$(mktemp -d "${TMPDIR:-/tmp}/mini-factory-gum.XXXXXX")"
	if ! curl -fsSL https://repo.charm.sh/apt/gpg.key -o "$scratch/charm.asc"; then
		rm -rf -- "$scratch"
		die 'unable to download the Charm apt repository key; rerun make setup'
	fi
	printf '%s\n' 'deb [signed-by=/etc/apt/keyrings/charm.asc] https://repo.charm.sh/apt/ * *' >"$scratch/charm.list"
	sudo mkdir -p -m 755 /etc/apt/keyrings /etc/apt/sources.list.d
	sudo install -m 644 "$scratch/charm.asc" /etc/apt/keyrings/charm.asc
	sudo install -m 644 "$scratch/charm.list" /etc/apt/sources.list.d/charm.list
	rm -rf -- "$scratch"
	sudo apt-get update
	sudo "${install_arguments[@]}"
}

install_native_tool() {
	local tool="$1" url="$2" scratch status=0
	[ ! -e "$bin_directory/$tool" ] && [ ! -L "$bin_directory/$tool" ] ||
		die "a $tool file exists outside PATH at $bin_directory/$tool; add it to PATH or resolve it before installation"
	# Cursor's installer replaces both of its command names.
	[ "$tool" != cursor-agent ] || { [ ! -e "$bin_directory/agent" ] && [ ! -L "$bin_directory/agent" ]; } ||
		die "an unrelated $bin_directory/agent exists and Cursor's installer would replace it; resolve it before installation"
	scratch="$(mktemp -d "${TMPDIR:-/tmp}/mini-factory-native.XXXXXX")"
	if curl -fsSL "$url" -o "$scratch/install.sh"; then
		case "$tool" in
		codex)
			# The native installer skips its optional Codex launch in this mode.
			# Keeping its bin on PATH also prevents its shell-profile editor.
			PATH="$bin_directory:$PATH" CODEX_INSTALL_DIR="$bin_directory" CODEX_NON_INTERACTIVE=true sh "$scratch/install.sh" || status=$?
			;;
		herdr) HERDR_INSTALL_DIR="$bin_directory" sh "$scratch/install.sh" || status=$? ;;
		# Keeping the bin directory on PATH avoids the installers' PATH/profile guidance branches.
		claude | cursor-agent) PATH="$bin_directory:$PATH" bash "$scratch/install.sh" || status=$? ;;
		# An explicit link directory keeps the installer from using sudo for /usr/local/bin.
		no-mistakes) PATH="$bin_directory:$PATH" NO_MISTAKES_LINK_DIR="$bin_directory" sh "$scratch/install.sh" || status=$? ;;
		esac
	else
		status=1
	fi
	rm -rf -- "$scratch"
	[ "$status" -eq 0 ] || die "$tool installation failed; rerun make setup after resolving the upstream error"
	PATH="$PATH:$bin_directory"
	export PATH
}

install_bundle() {
	local input source relative quoted
	local inputs=(Makefile README.md .gitignore bin/ghd bin/mf-config bin/nm-config gh-dash/config.yml no-mistakes/config.yaml
		scripts/setup.sh scripts/update.sh scripts/doctor.sh scripts/doctor.py scripts/mf_config.py scripts/nm_config.py
		scripts/integrations/gh-dash/gh-dash-codex-issue-dispatch.sh
		scripts/integrations/gh-dash/gh-dash-codex-issue.sh
		scripts/integrations/gh-dash/gh-dash-codex-pr-review.sh
		scripts/integrations/gh-dash/gh-dash-codex-pr-review-dispatch.sh)
	mkdir -p -- "$(dirname "$runtime")" "$bin_directory"
	stage="$(mktemp -d "$(dirname "$runtime")/.mini-factory-stage.XXXXXX")"
	for input in "${inputs[@]}" 'tests/*.py'; do
		case "$input" in
		tests/*)
			# Expand only Python source files, never caches or local runtime state.
			for source in "$bundle"/$input; do
				[ -f "$source" ] && [ ! -L "$source" ] || die "missing or unsafe bundle source: $source"
				relative="${source#"$bundle"/}"
				mkdir -p -- "$stage/$(dirname "$relative")"
				cp -p -- "$source" "$stage/$relative"
			done
			;;
		*)
			[ -f "$bundle/$input" ] && [ ! -L "$bundle/$input" ] || die "missing or unsafe bundle source: $input"
			mkdir -p -- "$stage/$(dirname "$input")"
			cp -p -- "$bundle/$input" "$stage/$input"
			;;
		esac
	done
	chmod 755 "$stage/bin/ghd" "$stage/bin/mf-config" "$stage/bin/nm-config" "$stage/scripts/setup.sh" "$stage/scripts/update.sh" "$stage/scripts/doctor.sh" "$stage/scripts/integrations/gh-dash/"*.sh
	printf '%s\n' "$install_marker" >"$stage/.mini-factory-install"
	"$stage/scripts/doctor.sh" --bundle "$stage" --integrity-only || die 'replacement bundle failed validation; existing installation preserved'
	launcher_stage="$(mktemp "$bin_directory/.mini-factory-launcher.XXXXXX")"
	printf -v quoted '%q' "$runtime/bin/ghd"
	printf '#!/usr/bin/env bash\n# mini-factory managed launcher v1\nexec %s "$@"\n' "$quoted" >"$launcher_stage"
	chmod 755 "$launcher_stage"
	bash -n "$launcher_stage"
	# Installers can take minutes; recheck ownership before replacing anything.
	check_destinations
	backup="$(mktemp -d "$(dirname "$runtime")/.mini-factory-backup.XXXXXX")"
	if [ -d "$runtime" ]; then
		mv -- "$runtime" "$backup/runtime"
	fi
	replacement_started=1
	mv -- "$stage" "$runtime"
	stage=''
	mv -f -- "$launcher_stage" "$launcher"
	launcher_stage=''
	replacement_complete=1
	if [ -d "$backup/runtime" ]; then
		rm -rf -- "$backup/runtime"
	fi
	rmdir -- "$backup"
	backup=''
	notice "Installed: $runtime"
	notice "Launcher: $launcher"
}

# The optional mf-config and nm-config launchers never replace another command (for example a
# dotfiles-owned one); the clone's bin/mf-config and bin/nm-config always work.
install_optional_launcher() {
	local name="$1" quoted expected existing staged
	local path="$bin_directory/$name"
	printf -v quoted '%q' "$runtime/bin/$name"
	expected="$(printf '#!/usr/bin/env bash\n# mini-factory managed launcher v1\nexec %s "$@"\n' "$quoted")"
	if [ -e "$path" ] || [ -L "$path" ]; then
		if ! { [ -f "$path" ] && [ ! -L "$path" ] && [ -O "$path" ] &&
			[ "$(cat "$path")" = "$expected" ]; }; then
			notice "Optional $name launcher skipped: $path is not managed by mini-factory and was left untouched. Run $bundle/bin/$name instead."
			return 0
		fi
	fi
	existing="$(command -v "$name" 2>/dev/null || true)"
	if [ -n "$existing" ] && [ "$existing" != "$path" ]; then
		notice "Optional $name launcher skipped: another $name command is on PATH ($existing). Run $bundle/bin/$name instead."
		return 0
	fi
	[ ! -f "$path" ] || { notice "$name launcher: $path"; return 0; }
	staged="$(mktemp "$bin_directory/.mini-factory-$name.XXXXXX")"
	printf '%s\n' "$expected" >"$staged"
	chmod 755 "$staged"
	# Never clobber an entry that appeared since the check above.
	# link(2) fails atomically for any existing destination, including directories/symlinks.
	if ! python3 -I -B -c 'import os, sys; os.link(sys.argv[1], sys.argv[2])' "$staged" "$path" 2>/dev/null; then
		rm -f -- "$staged"
		notice "Optional $name launcher skipped: $path appeared during setup. Run $bundle/bin/$name instead."
		return 0
	fi
	rm -f -- "$staged"
	notice "$name launcher: $path"
}

agent_is_authenticated() {
	case "$1" in
	claude) claude auth status >/dev/null 2>&1 ;;
	codex) codex login status >/dev/null 2>&1 ;;
	# Cursor's status exits 0 while logged out; read only its boolean, never display it.
	cursor) cursor-agent status --format json 2>/dev/null | jq -e '.isAuthenticated == true' >/dev/null 2>&1 ;;
	esac
}

login_agent() {
	local kind="$1" command_text detail
	case "$kind" in
	claude) command_text='claude auth login'; detail='Open its URL in a browser on this or another machine.' ;;
	codex) command_text='codex login --device-auth'; detail='Enable device-code login in ChatGPT security settings/workspace permissions first, then use a browser on this or another machine.' ;;
	cursor) command_text='cursor-agent login'; detail='On a headless server set NO_OPEN_BROWSER=1 and open its URL in a browser on another machine.' ;;
	esac
	agent_is_authenticated "$kind" && return 0
	if consent "$kind authentication is pending. Run $command_text now? $detail Authentication stays in the native CLI; do not paste credentials here."; then
		case "$kind" in
		claude) claude auth login || pending=1 ;;
		codex) codex login --device-auth || pending=1 ;;
		cursor) cursor-agent login || pending=1 ;;
		esac
	else
		notice "Remaining action: $command_text"
		pending=1
	fi
}

# Reads node --version output: Node.js 22.13+ succeeds; empty or older output fails.
node_version_is_suitable() {
	awk 'NR == 1 {sub(/^v/, ""); split($0, v, "."); ok = v[1] > 22 || (v[1] == 22 && v[2] >= 13)} END {exit !ok}'
}

# Your shell's node and npm install acpx.
node_is_suitable() {
	command -v node >/dev/null 2>&1 &&
		node --version 2>/dev/null | node_version_is_suitable
}

# acpx starts the node that the daemon's PATH finds first, whichever node your shell finds.
daemon_node_is_suitable() {
	env PATH="$daemon_path" /bin/sh -c 'node --version' 2>/dev/null | node_version_is_suitable
}

# madison lists repository-provided versions only (as for Gum); any configured source counts, such as NodeSource.
node_in_apt_sources() {
	apt-cache madison nodejs 2>/dev/null | awk -F '|' '{
		version = $2; gsub(/[ \t]/, "", version); sub(/^[0-9]+:/, "", version); split(version, v, /[.+~-]/)
		if (v[1] > 22 || (v[1] == 22 && v[2] >= 13)) found = 1
	} END { exit !found }'
}

# Only a missing Node.js is installed; an existing one (system, Homebrew, fnm, nvm, ...) is never replaced.
install_node() {
	if [ "$platform" = macos ]; then
		command -v brew >/dev/null 2>&1 || return 1
		consent 'Node.js with npm is missing; acpx, the ACP runner No-Mistakes uses for Cursor, needs Node.js 22.13+. Install it with brew install node? No general brew update/upgrade or shell edits.' ||
			return 1
		HOMEBREW_NO_AUTO_UPDATE=1 HOMEBREW_NO_INSTALL_CLEANUP=1 brew install node || return 1
	else
		command -v sudo >/dev/null 2>&1 && node_in_apt_sources || return 1
		consent 'Node.js with npm is missing; acpx, the ACP runner No-Mistakes uses for Cursor, needs Node.js 22.13+, which your configured apt sources offer. Run sudo apt-get install --no-install-recommends nodejs, then the same for npm only if nodejs does not provide it? This changes system packages.' ||
			return 1
		sudo apt-get install -y --no-install-recommends nodejs || return 1
		hash -r
		command -v npm >/dev/null 2>&1 || sudo apt-get install -y --no-install-recommends npm || return 1
	fi
	hash -r
}

acpx_runs_for_daemon() {
	[ -n "$acpx_path" ] || return 1
	# shellcheck disable=SC2016 # Expanded by the child shell with the daemon's PATH.
	env PATH="$daemon_path" /bin/sh -c 'command -v "$1" >/dev/null 2>&1 && "$1" --version >/dev/null 2>&1' sh "$acpx_path"
}

# Node.js 22.13+, npm, and acpx are baseline: No-Mistakes runs Cursor (cursor or acp:cursor, as the
# pipeline agent or any review role) through acpx, so choosing Cursor later needs no new install.
ensure_node_and_acpx() {
	local prefix found daemon_node
	local npm_arguments=(install -g acpx@latest)
	daemon_path="$(python3 -I -B "$bundle/scripts/nm_config.py" daemon-path 2>/dev/null)" || daemon_path="$service_path"
	[ -n "$daemon_path" ] || daemon_path="$service_path"
	command -v node >/dev/null 2>&1 || install_node || true
	if ! node_is_suitable || ! command -v npm >/dev/null 2>&1; then
		found='Node.js is missing'
		if command -v node >/dev/null 2>&1; then
			found="$(command -v node) is Node.js $(node --version 2>/dev/null || printf 'of unknown version')"
			command -v npm >/dev/null 2>&1 || found="$found without npm"
		fi
		notice "Remaining action: $found; acpx needs Node.js 22.13+ with npm. Setup never replaces an existing Node.js or version manager: upgrade or install it yourself (for example brew install node, a configured apt source such as NodeSource, or https://nodejs.org) so node and npm are first on PATH, including your login shell's PATH that the No-Mistakes daemon adopts (or ~/.local/bin, /opt/homebrew/bin, /usr/local/bin, or /usr/bin); then rerun make setup, restart the No-Mistakes daemon (a running daemon keeps the PATH it started with), and rerun make doctor."
		pending=1
		return 0
	fi
	# A suitable shell Node.js never stands in for the daemon's; acpx is still provisioned below.
	if ! daemon_node_is_suitable; then
		daemon_node="$(env PATH="$daemon_path" /bin/sh -c 'command -v node' 2>/dev/null)" || daemon_node=''
		found='no Node.js'
		if [ -n "$daemon_node" ]; then
			found="$daemon_node, Node.js $(env PATH="$daemon_path" /bin/sh -c 'node --version' 2>/dev/null || printf 'of unknown version')"
		fi
		notice "Remaining action: the No-Mistakes daemon's PATH $daemon_path (your login shell's PATH plus well-known directories) finds $found first, but acpx runs with that PATH and needs Node.js 22.13+; your current shell's $(command -v node) does not count. Setup never replaces an existing Node.js or version manager: put a Node.js 22.13+ first on that PATH yourself (for example by activating your version manager's 22.13+ default in your login shell's startup files, or by upgrading the Node.js found there with the tool that installed it), then rerun make setup, restart the No-Mistakes daemon (a running daemon keeps the PATH it started with), and rerun make doctor."
		pending=1
	fi
	# An existing acpx the daemon can run (from ~/bin, Homebrew, ... or acpx_path) is reused as is.
	acpx_runs_for_daemon && return 0
	if [ "$acpx_path" != acpx ]; then
		# An unreadable acpx_path was already reported.
		[ -z "$acpx_path" ] || notice "Remaining action: acpx_path $acpx_path in the No-Mistakes config does not run (with the Node.js 22.13+ it needs) from the daemon's PATH $daemon_path. Fix that executable or setting yourself, then rerun make setup."
		pending=1
		return 0
	fi
	if ! command -v acpx >/dev/null 2>&1; then
		prefix="$(npm prefix -g 2>/dev/null || true)"
		# A global prefix that is root-owned (system Node) or outside the daemon's PATH (such as a per-shell
		# fnm path) gets a user-owned acpx in $bin_directory instead; npm's configured prefix is never changed.
		case ":$daemon_path:" in
		*":$prefix/bin:"*) [ -w "$prefix/lib/node_modules" ] && [ -w "$prefix/bin" ] || prefix='' ;;
		*) prefix='' ;;
		esac
		[ -n "$prefix" ] || npm_arguments=(install -g --prefix "$HOME/.local" acpx@latest)
		if consent "acpx is the ACP runner No-Mistakes uses for Cursor. Install it with its documented npm ${npm_arguments[*]}?"; then
			npm "${npm_arguments[@]}" || true
			PATH="$PATH:$bin_directory"
			export PATH
			hash -r
			acpx_runs_for_daemon && return 0
		fi
	fi
	if ! command -v acpx >/dev/null 2>&1 || ! acpx --version >/dev/null 2>&1; then
		notice "Remaining action: npm ${npm_arguments[*]} (acpx, the ACP runner No-Mistakes uses for Cursor), then rerun make setup"
		pending=1
	else
		notice "Remaining action: $(command -v acpx) runs only from your current shell PATH, not from the No-Mistakes daemon's PATH $daemon_path (your login shell's PATH plus well-known directories). Make acpx and the Node.js 22.13+ it runs available there (for example from your login shell's startup files, or npm install -g --prefix ~/.local acpx@latest with a Homebrew, apt, or nodejs.org Node.js), then rerun make setup, restart the No-Mistakes daemon (a running daemon keeps the PATH it started with), and rerun make doctor."
		pending=1
	fi
}

configure_native_tools() {
	local codex_directory integration kind description login_arguments login_kinds
	if ! gh auth status --hostname github.com >/dev/null 2>&1; then
		if consent 'GitHub authentication is pending. Run gh auth login --hostname github.com --web now? Follow its native device-code instructions in a browser on this or another machine. Choose Git transport yourself; setup will not configure Git credentials.'; then
			login_arguments=(auth login --hostname github.com --web)
			if consent "Optional: also request GitHub's project scope (only for GitHub Projects access)? Ordinary issue and PR actions do not need it."; then
				login_arguments=(auth login --hostname github.com --web --scopes project)
			fi
			gh "${login_arguments[@]}" || pending=1
		else
			notice 'Remaining action: gh auth login --hostname github.com --web'
			pending=1
		fi
	fi
	if ! gh dash --version >/dev/null 2>&1; then
		if consent 'Install the gh-dash extension with gh extension install dlvhdr/gh-dash? Existing gh-dash configuration is preserved; ghd uses the bundled config explicitly.'; then
			gh extension install dlvhdr/gh-dash || pending=1
		else
			notice 'Remaining action: gh extension install dlvhdr/gh-dash'
			pending=1
		fi
	fi
	# Only agents that a gh-dash role or a No-Mistakes duty uses need login; others may stay logged out.
	login_kinds=("${role_agents[@]}")
	for kind in "${duty_agents[@]+"${duty_agents[@]}"}"; do
		contains "$kind" "${login_kinds[@]}" || login_kinds+=("$kind")
	done
	for kind in "${login_kinds[@]}"; do
		login_agent "$kind"
	done
	ensure_node_and_acpx
	codex_directory="${CODEX_HOME:-$HOME/.codex}"
	case "$codex_directory" in
	/*) ;;
	*) die 'CODEX_HOME must be an absolute path before integration installation' ;;
	esac
	integration="$(herdr integration status 2>/dev/null || true)"
	# Herdr detects the gh-dash roles' agents through native integrations; No-Mistakes needs none.
	for kind in "${role_agents[@]}"; do
		! printf '%s\n' "$integration" | grep -q "^$kind: current " || continue
		case "$kind" in
		codex)
			if [ ! -d "$codex_directory" ]; then
				if [ -e "$codex_directory" ] || [ -L "$codex_directory" ]; then
					die "Codex configuration path is not a directory: $codex_directory"
				fi
				if consent "Create the Codex configuration directory $codex_directory for its native Herdr integration?"; then
					(umask 077; mkdir -p -- "$codex_directory")
				else
					notice "Remaining action: create $codex_directory, then herdr integration install codex"
					pending=1
					continue
				fi
			fi
			description="$codex_directory/herdr-agent-state.sh, hooks.json, and config.toml (enabling hooks and retiring its deprecated Codex hook flag)"
			;;
		claude) description="Claude Code's user hook settings under $HOME/.claude" ;;
		cursor) description="Cursor's user hook files under $HOME/.cursor" ;;
		esac
		if consent "Run herdr integration install $kind? This native installer changes $description. Review native trust decisions yourself. Other settings remain owned by their native tools."; then
			herdr integration install "$kind" || pending=1
		else
			notice "Remaining action: herdr integration install $kind"
			pending=1
		fi
	done
}

[ "$#" -eq 0 ] || die 'usage: scripts/setup.sh (run make setup)'
detect_platform
check_destinations
check_source_clone
select_issue_agent
# A compatible No-Mistakes must be in place first: its installer and updater
# restart the daemon before the config link is created.
install_dependencies
link_no_mistakes_config
read_duty_agents
read_acpx_path
install_bundle
install_optional_launcher mf-config
install_optional_launcher nm-config
configure_native_tools
case ":$parent_path:" in
*":$bin_directory:"*) ;;
*)
	# shellcheck disable=SC2016
	notice 'For this shell, run exactly: export PATH="$HOME/.local/bin:$PATH"'
	notice 'Setup is a child process and cannot change its parent shell environment. Add that line to your chosen shell startup file yourself for future shells.'
	pending=1
	;;
esac
"$runtime/scripts/doctor.sh" --bundle "$runtime" || pending=1
if [ "$pending" -ne 0 ]; then
	notice 'Installed; authentication/setup actions remain pending. Resolve the actions above and rerun make setup or make doctor.'
	exit 1
fi
notice 'Installation and authentication checks passed. Enter a Herdr pane for your target checkout, then run ghd.'
