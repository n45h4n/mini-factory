#!/usr/bin/env bash
set -euo pipefail

bundle="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
runtime="${XDG_DATA_HOME:-$HOME/.local/share}/gh-dash-share"
bin_directory="$HOME/.local/bin"
launcher="$bin_directory/ghd"
parent_path="$PATH"
install_marker='gh-dash-share-v1'
agent_setting="${XDG_CONFIG_HOME:-$HOME/.config}/gh-dash-share/issue-agent"
nm_home="${NM_HOME:-$HOME/.no-mistakes}"
nm_config="$nm_home/config.yaml"
nm_source="$bundle/no-mistakes/config.yaml"
nm_backup="$nm_config.gh-dash-share-backup"
# Tested release: v1.105.0 (prerelease). Stable v1.84.0 lacks the bot settings in no-mistakes/config.yaml.
nm_minimum='1.105.0'
nm_template_agent='agent: codex # Initialize to the chosen pipeline agent during first setup.'
issue_agent=''
pipeline_agent=''
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
			[ "$(cat "$runtime/.gh-dash-share-install" 2>/dev/null || true)" = "$install_marker" ]; then
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
		[ -f "$runtime/.gh-dash-share-install" ] && [ ! -L "$runtime/.gh-dash-share-install" ] &&
			[ "$(cat "$runtime/.gh-dash-share-install")" = "$install_marker" ] ||
			die "refusing unrelated existing installation directory: $runtime"
	fi
	printf -v quoted '%q' "$runtime/bin/ghd"
	expected="$(printf '#!/usr/bin/env bash\n# gh-dash-share managed launcher v1\nexec %s "$@"\n' "$quoted")"
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
		die 'run make setup from your retained gh-dash-share clone, not the installed runtime copy'
	[ -f "$nm_source" ] && [ ! -L "$nm_source" ] ||
		die "missing tracked No-Mistakes config: $nm_source; run make setup from your gh-dash-share clone"
}

select_issue_agent() {
	local saved=''
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
	notice "Issue agent for i and I: $issue_agent (saved in $agent_setting; change it with make setup ISSUE_AGENT=claude|codex|cursor)."
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

read_pipeline_agent() {
	local file="$nm_source"
	[ ! -r "$nm_config" ] || file="$nm_config"
	pipeline_agent="$(awk '/^agent:/ { sub(/^agent:[ \t]*/, ""); sub(/[ \t]*#.*$/, ""); gsub(/["\047]/, ""); print; exit }' "$file")"
	case "$pipeline_agent" in
	claude | codex | cursor) ;;
	*)
		notice "No-Mistakes pipeline agent: ${pipeline_agent:-unset} (not provisioned by setup; log in through its native CLI, doctor reports its authentication as unverified)."
		pipeline_agent=''
		;;
	esac
}

agent_command() {
	case "$1" in
	cursor) printf 'cursor-agent\n' ;;
	*) printf '%s\n' "$1" ;;
	esac
}

python_is_suitable() {
	command -v python3 >/dev/null 2>&1 &&
		python3 -I -c 'import sys; raise SystemExit(sys.version_info < (3, 9))' >/dev/null 2>&1
}

git_is_suitable() {
	command -v git >/dev/null 2>&1 || return 1
	git --version | awk 'NR == 1 {split($3,v,"."); exit !(v[1] > 2 || (v[1] == 2 && v[2] >= 29))}'
}

gh_is_suitable() {
	command -v gh >/dev/null 2>&1 || return 1
	gh --version | awk 'NR == 1 {split($3,v,"."); exit !(v[1] > 2 || (v[1] == 2 && v[2] >= 47))}'
}

install_dependencies() {
	local command_name package proposal
	local packages=()
	local installs=() upgrades=()
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
		if [ "${#packages[@]}" -gt 0 ]; then
			command -v brew >/dev/null 2>&1 || die 'Homebrew is required for missing dependencies; follow the macOS bootstrap instructions in README.md'
			proposal='Homebrew changes for missing/unsuitable dependencies only:'
			for package in "${packages[@]}"; do
				if brew list --versions "$package" >/dev/null 2>&1; then
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
	fi
	python_is_suitable || die 'python3 still resolves to a version below 3.9; fix PATH to use the installed Python and rerun'
	git_is_suitable || die 'git must be version 2.29 or later; fix PATH to the suitable installation and rerun'
	gh_is_suitable || die 'gh must be version 2.47 or later; fix PATH to the suitable installation and rerun'
	# Codex stays required for PR review; add the issue agent, then No-Mistakes.
	# The pipeline agent is installed after linking, once its config is known.
	install_tools codex herdr "$(agent_command "$issue_agent")" no-mistakes
	if ! no_mistakes_is_suitable; then
		if consent "No-Mistakes is older than the tested v$nm_minimum; stable releases before it lack the bot settings in $nm_source. Run its native updater, no-mistakes update --beta? It installs the newest prerelease and restarts the daemon, and refuses while runs are active."; then
			no-mistakes update --beta || die 'no-mistakes update --beta failed; resolve its reported blocker and rerun make setup'
		else
			die "No-Mistakes v$nm_minimum or newer is required"
		fi
		no_mistakes_is_suitable || die "No-Mistakes is still older than v$nm_minimum; fix PATH or update it natively and rerun"
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
			if consent "Install $command_name using its upstream native installer ($installer). Commands go in $bin_directory; $command_name also manages its native files under $directory. No Node/npm or shell configuration changes are needed."; then
				install_native_tool "$command_name" "$installer"
			else
				die "$command_name installation pending"
			fi
		fi
		"$command_name" --version >/dev/null 2>&1 || die "$command_name is installed but cannot run; repair it using its native installer"
	done
}

no_mistakes_is_suitable() {
	no-mistakes --version 2>/dev/null | awk -v minimum="$nm_minimum" 'NR == 1 {
		version = $3; sub(/^v/, "", version); split(version, v, "."); split(minimum, m, ".")
		exit !(v[1] > m[1] || (v[1] == m[1] && (v[2] > m[2] || (v[2] == m[2] && v[3] + 0 >= m[3] + 0))))
	}'
}

install_github_cli_ubuntu() {
	local scratch repository_line
	scratch="$(mktemp -d "${TMPDIR:-/tmp}/gh-dash-share-gh.XXXXXX")"
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

install_native_tool() {
	local tool="$1" url="$2" scratch status=0
	[ ! -e "$bin_directory/$tool" ] && [ ! -L "$bin_directory/$tool" ] ||
		die "a $tool file exists outside PATH at $bin_directory/$tool; add it to PATH or resolve it before installation"
	# Cursor's installer replaces both of its command names.
	[ "$tool" != cursor-agent ] || { [ ! -e "$bin_directory/agent" ] && [ ! -L "$bin_directory/agent" ]; } ||
		die "an unrelated $bin_directory/agent exists and Cursor's installer would replace it; resolve it before installation"
	scratch="$(mktemp -d "${TMPDIR:-/tmp}/gh-dash-share-native.XXXXXX")"
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
	local inputs=(Makefile README.md .gitignore bin/ghd gh-dash/config.yml no-mistakes/config.yaml scripts/setup.sh scripts/doctor.sh scripts/doctor.py
		scripts/integrations/gh-dash/gh-dash-codex-issue-dispatch.sh
		scripts/integrations/gh-dash/gh-dash-codex-issue.sh
		scripts/integrations/gh-dash/gh-dash-codex-pr-review.sh
		scripts/integrations/gh-dash/gh-dash-codex-pr-review-dispatch.sh)
	mkdir -p -- "$(dirname "$runtime")" "$bin_directory"
	stage="$(mktemp -d "$(dirname "$runtime")/.gh-dash-share-stage.XXXXXX")"
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
	chmod 755 "$stage/bin/ghd" "$stage/scripts/setup.sh" "$stage/scripts/doctor.sh" "$stage/scripts/integrations/gh-dash/"*.sh
	printf '%s\n' "$install_marker" >"$stage/.gh-dash-share-install"
	"$stage/scripts/doctor.sh" --bundle "$stage" --integrity-only || die 'replacement bundle failed validation; existing installation preserved'
	launcher_stage="$(mktemp "$bin_directory/.gh-dash-share-launcher.XXXXXX")"
	printf -v quoted '%q' "$runtime/bin/ghd"
	printf '#!/usr/bin/env bash\n# gh-dash-share managed launcher v1\nexec %s "$@"\n' "$quoted" >"$launcher_stage"
	chmod 755 "$launcher_stage"
	bash -n "$launcher_stage"
	# Installers can take minutes; recheck ownership before replacing anything.
	check_destinations
	backup="$(mktemp -d "$(dirname "$runtime")/.gh-dash-share-backup.XXXXXX")"
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

node_is_suitable() {
	command -v node >/dev/null 2>&1 &&
		node --version 2>/dev/null | awk 'NR == 1 {sub(/^v/, ""); split($0, v, "."); exit !(v[1] > 22 || (v[1] == 22 && v[2] >= 13))}'
}

install_node_ubuntu() {
	local scratch status=0
	scratch="$(mktemp -d "${TMPDIR:-/tmp}/gh-dash-share-node.XXXXXX")"
	# Chained so a failed step stops here even when the caller handles the status.
	curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key -o "$scratch/nodesource.asc" &&
		printf 'deb [arch=%s signed-by=/etc/apt/keyrings/nodesource.asc] https://deb.nodesource.com/node_24.x nodistro main\n' \
			"$(dpkg --print-architecture)" >"$scratch/nodesource.list" &&
		printf 'Package: nodejs\nPin: origin deb.nodesource.com\nPin-Priority: 600\n' >"$scratch/nodejs" &&
		sudo mkdir -p -m 755 /etc/apt/keyrings /etc/apt/sources.list.d /etc/apt/preferences.d &&
		sudo install -m 644 "$scratch/nodesource.asc" /etc/apt/keyrings/nodesource.asc &&
		sudo install -m 644 "$scratch/nodesource.list" /etc/apt/sources.list.d/nodesource.list &&
		sudo install -m 644 "$scratch/nodejs" /etc/apt/preferences.d/nodejs &&
		sudo apt-get update &&
		sudo apt-get install -y --no-install-recommends nodejs || status=$?
	rm -rf -- "$scratch"
	return "$status"
}

# Ubuntu's own nodejs is too old or lacks npm, so Ubuntu uses NodeSource's LTS package, which bundles npm.
install_node() {
	local action=install
	if [ "$platform" = macos ]; then
		command -v brew >/dev/null 2>&1 || { notice 'Homebrew is required to install Node.js; follow the macOS bootstrap instructions in README.md'; return 0; }
		if brew list --versions node >/dev/null 2>&1; then action=upgrade; fi
		consent "acpx needs Node.js 22.13+ with npm. Homebrew change: brew $action node. No general brew update/upgrade or shell edits." || return 0
		HOMEBREW_NO_AUTO_UPDATE=1 HOMEBREW_NO_INSTALL_CLEANUP=1 brew "$action" node || notice "brew $action node failed"
	else
		command -v sudo >/dev/null 2>&1 || { notice 'sudo is required to install Node.js from the NodeSource apt repository; ask the host administrator'; return 0; }
		consent 'acpx needs Node.js 22.13+ with npm. Install Node.js 24 LTS from the NodeSource apt repository (https://deb.nodesource.com/node_24.x)? This writes /etc/apt/keyrings/nodesource.asc, /etc/apt/sources.list.d/nodesource.list, and /etc/apt/preferences.d/nodejs (preferring its nodejs, which bundles npm), then runs sudo apt-get update and sudo apt-get install nodejs, replacing Ubuntu nodejs/npm packages if present.' || return 0
		install_node_ubuntu || notice 'Node.js installation from NodeSource failed'
	fi
}

# No-Mistakes runs Cursor through the ACP runner acpx, which needs Node.js 22.13+.
ensure_acp_runner() {
	local prefix
	local npm_arguments=(install -g acpx@latest)
	[ "$pipeline_agent" = cursor ] || return 0
	command -v acpx >/dev/null 2>&1 && return 0
	{ command -v npm >/dev/null 2>&1 && node_is_suitable; } || install_node
	if command -v npm >/dev/null 2>&1 && node_is_suitable; then
		prefix="$(npm prefix -g 2>/dev/null || true)"
		# A root-owned global prefix (such as NodeSource's /usr) gets a user-owned acpx in $bin_directory, never sudo.
		[ -n "$prefix" ] && [ -w "$prefix/lib/node_modules" ] && [ -w "$prefix/bin" ] ||
			npm_arguments=(install -g --prefix "$HOME/.local" acpx@latest)
		if consent "The No-Mistakes pipeline agent is cursor, which runs through the ACP runner acpx. Install it with its documented npm ${npm_arguments[*]}?"; then
			npm "${npm_arguments[@]}" || pending=1
			PATH="$PATH:$bin_directory"
			export PATH
		fi
	fi
	command -v acpx >/dev/null 2>&1 && return 0
	notice "Remaining action: put Node.js 22.13+ with npm first on PATH, then npm install -g acpx@latest (needed by agent: cursor in $nm_source)"
	pending=1
}

configure_native_tools() {
	local codex_directory integration kind description login_arguments kinds
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
	# Codex reviews PRs; the issue and pipeline agents authenticate through their own CLIs.
	login_agent codex
	[ "$issue_agent" = codex ] || login_agent "$issue_agent"
	case "$pipeline_agent" in
	'' | codex | "$issue_agent") ;;
	*) login_agent "$pipeline_agent" ;;
	esac
	ensure_acp_runner
	codex_directory="${CODEX_HOME:-$HOME/.codex}"
	case "$codex_directory" in
	/*) ;;
	*) die 'CODEX_HOME must be an absolute path before integration installation' ;;
	esac
	integration="$(herdr integration status 2>/dev/null || true)"
	# Herdr detects the PR review agent (Codex) and the issue agent through native integrations.
	kinds=(codex)
	[ "$issue_agent" = codex ] || kinds[1]="$issue_agent"
	for kind in "${kinds[@]}"; do
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
# A compatible No-Mistakes must be in place first: its installer restarts the
# daemon, and older releases reject the linked config's newer fields.
install_dependencies
link_no_mistakes_config
read_pipeline_agent
[ -z "$pipeline_agent" ] || install_tools "$(agent_command "$pipeline_agent")"
install_bundle
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
