#!/usr/bin/env bash
# Lightweight Arch Linux container smoke check of setup's real package and shell behavior, run by CI. Docker is
# test infrastructure only: normal installation and make test never need it. The checkout is mounted read-only;
# setup runs as a regular sudo user from a disposable writable copy inside the container, with real pacman
# packages and inert GitHub CLI, agent, Herdr, No-Mistakes, and acpx commands (no logins or network services).
set -euo pipefail

repository="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
image="${MINI_FACTORY_ARCH_IMAGE:-archlinux:latest}"
if ! command -v docker >/dev/null 2>&1 || ! docker info >/dev/null 2>&1; then
	printf 'NOT RUN: the Arch container smoke check needs a working Docker daemon\n' >&2
	exit 2
fi

IFS= read -r -d '' smoke <<'SMOKE' || true
set -euo pipefail
fail() {
	printf 'FAIL: %s\n' "$1" >&2
	[ -z "${2:-}" ] || cat "$2" >&2
	exit 1
}
transactions() { grep -c '\[ALPM\] transaction started' /var/log/pacman.log || true; }
as_tester() { su - tester -c "export PATH=\"\$HOME/.local/bin:\$PATH\"; cd ~/mini-factory && $1"; }

# Container bootstrap as root. The image ships without a local pacman master key, which the keyring package
# needs to trust current packagers; then sudo for a regular user, with the full upgrade Arch requires.
pacman-key --init >/dev/null 2>&1
pacman -Syu --noconfirm --needed sudo >/dev/null
useradd -m -s /bin/bash tester
printf 'tester ALL=(ALL) NOPASSWD: ALL\n' >/etc/sudoers.d/tester
chmod 440 /etc/sudoers.d/tester
cp -a /src /home/tester/mini-factory
rm -rf /home/tester/mini-factory/.git
chown -R tester:tester /home/tester/mini-factory

# Inert commands for everything that would log in or reach a network service. Real packages provide the rest.
bin=/home/tester/.local/bin
install -d -o tester -g tester /home/tester/.local "$bin"
inert() {
	cat >"$bin/$1"
	chmod 755 "$bin/$1"
	chown tester:tester "$bin/$1"
}
inert gh <<'INERT'
#!/bin/sh
case "$*" in
--version) echo 'gh version 2.88.1 (inert)' ;;
'auth status --hostname github.com') ;;
'extension list') printf 'gh dash\tdlvhdr/gh-dash\tv4.15.0\n' ;;
'dash --version') echo 'gh-dash version 4.15.0 (inert)' ;;
'dash --help') echo '--config' ;;
*) echo "inert gh: unexpected $*" >&2; exit 64 ;;
esac
INERT
inert codex <<'INERT'
#!/bin/sh
case "$*" in
--version) echo 'codex-cli 0.166.0 (inert)' ;;
'login status') ;;
'login --help') echo '--device-auth' ;;
*) echo "inert codex: unexpected $*" >&2; exit 64 ;;
esac
INERT
inert claude <<'INERT'
#!/bin/sh
case "$*" in
--version) echo '2.1.0 (Claude Code, inert)' ;;
'auth status') ;;
*) echo "inert claude: unexpected $*" >&2; exit 64 ;;
esac
INERT
inert cursor-agent <<'INERT'
#!/bin/sh
case "$*" in
--version) echo '2026.10.22-inert' ;;
'status --format json') echo '{"isAuthenticated": true}' ;;
*) echo "inert cursor-agent: unexpected $*" >&2; exit 64 ;;
esac
INERT
inert herdr <<'INERT'
#!/bin/sh
case "$*" in
--version) echo 'herdr 0.9.5 (inert)' ;;
'integration status') printf 'claude: current (inert)\ncodex: current (inert)\ncursor: current (inert)\n' ;;
*--help*) echo 'integration install status claude codex cursor --cwd --path --base --branch --kind --pane --timeout --wait' ;;
*) echo "inert herdr: unexpected $*" >&2; exit 64 ;;
esac
INERT
inert no-mistakes <<'INERT'
#!/bin/sh
case "$*" in
--version) echo 'no-mistakes version v1.84.0 (inert)' ;;
'axi run --help') echo '--intent string --base-branch string -y, --yes' ;;
doctor) printf '  \342\234\223 gate validation  codex is runnable (inert)\n' ;;
*) echo "inert no-mistakes: unexpected $*" >&2; exit 64 ;;
esac
INERT
inert acpx <<'INERT'
#!/bin/sh
[ "$*" = --version ] && echo '0.20.0 (inert)'
INERT
# The consented No-Mistakes configuration link, as an earlier setup leaves it.
install -d -o tester -g tester /home/tester/.no-mistakes
ln -s /home/tester/mini-factory/no-mistakes/config.yaml /home/tester/.no-mistakes/config.yaml
chown -h tester:tester /home/tester/.no-mistakes/config.yaml

[ "$(as_tester 'bash scripts/platform.sh detect')" = arch ] || fail 'the container was not detected as ordinary Arch'

# Without a terminal, setup assumes no consent and changes no package.
before="$(transactions)"
if as_tester ./scripts/setup.sh </dev/null >/tmp/noninteractive.log 2>&1; then
	fail 'setup without a terminal succeeded without installing prerequisites' /tmp/noninteractive.log
fi
grep -q 'Consent pending: rerun make setup in an interactive terminal' /tmp/noninteractive.log ||
	fail 'setup without a terminal did not report pending consent' /tmp/noninteractive.log
pending="$(sed -n 's/^ERROR: dependencies pending: //p' /tmp/noninteractive.log | tr ' ' '\n' | sort | tr '\n' ' ')"
[ "$pending" = 'git gum jq make nodejs npm python ' ] ||
	fail "unexpected pending Arch packages: $pending" /tmp/noninteractive.log
[ "$(transactions)" = "$before" ] || fail 'setup without a terminal changed packages'

# In a terminal, one consent (setup's plain prompt, as Gum is missing, then pacman's own confirmation of the
# whole transaction) runs one full-upgrade transaction. Each answer is typed once its prompt appears: sudo
# discards input typed ahead of the command it starts.
answer() {
	local waited=0
	until grep -qF "$1" /tmp/setup.log 2>/dev/null; do
		[ "$waited" -lt 900 ] || return 0
		sleep 1
		waited=$((waited + 1))
	done
	printf 'y\n'
}
: >/tmp/setup.log
if ! { answer 'Proceed? [y/N]'; answer 'Proceed with installation? [Y/n]'; } |
	as_tester 'script -qec ./scripts/setup.sh /dev/null' >/tmp/setup.log 2>&1; then
	fail 'consented setup did not pass' /tmp/setup.log
fi
grep -q 'WARNING: this also upgrades every installed package (a full system upgrade)' /tmp/setup.log ||
	fail 'setup did not warn that -Syu upgrades the system' /tmp/setup.log
grep -q 'Installation and authentication checks passed' /tmp/setup.log || fail 'setup did not finish ready' /tmp/setup.log
[ "$(transactions)" = "$((before + 1))" ] || fail 'consented setup did not run exactly one package transaction'
grep -q "\[PACMAN\] Running 'pacman -Syu --needed " /var/log/pacman.log || fail 'setup did not use pacman -Syu --needed'
pacman -Q git gum jq make nodejs npm python >/dev/null || fail 'the consented packages are not installed'
# The official name setup uses when GitHub CLI is missing (the inert gh stands in for it here).
pacman -Si github-cli >/dev/null || fail 'github-cli is not an official Arch package name'

# A healthy rerun through make starts no package transaction, and doctor agrees.
before="$(transactions)"
as_tester 'make setup' </dev/null >/tmp/rerun.log 2>&1 || fail 'healthy make setup rerun failed' /tmp/rerun.log
as_tester 'make doctor' </dev/null >/tmp/doctor.log 2>&1 || fail 'make doctor failed' /tmp/doctor.log
grep -qx 'OK: platform: arch' /tmp/doctor.log || fail 'doctor did not report ordinary Arch' /tmp/doctor.log
grep -qx "OK: Node.js 22.13+ runs from the No-Mistakes daemon's freshly resolved PATH" /tmp/doctor.log ||
	fail "Arch's nodejs package does not run from the No-Mistakes daemon's PATH" /tmp/doctor.log
[ "$(transactions)" = "$before" ] || fail 'a healthy rerun started a package transaction'

# An Omarchy runtime without its package is an incomplete Omarchy installation, never provisioned as Arch.
install -d /usr/share/omarchy/bin
printf '#!/bin/sh\nexit 0\n' >/usr/share/omarchy/bin/omarchy
chmod 755 /usr/share/omarchy/bin/omarchy
if as_tester ./scripts/setup.sh </dev/null >/tmp/incomplete.log 2>&1; then
	fail 'setup provisioned an incomplete Omarchy installation' /tmp/incomplete.log
fi
grep -q 'incomplete Omarchy installation' /tmp/incomplete.log || fail 'incomplete Omarchy was not explained' /tmp/incomplete.log
rm -rf /usr/share/omarchy
printf 'Declined without a terminal: %s\n' "$pending"
printf 'Consented: %s\n' "$(grep -F "[PACMAN] Running 'pacman -Syu --needed " /var/log/pacman.log | tail -n 1)"
printf 'Healthy rerun: no package transaction; %s\n' "$(grep -x 'OK: platform: arch' /tmp/doctor.log)"
printf 'Arch container smoke check passed\n'
SMOKE

printf 'Running the Arch container smoke check in %s (the checkout is mounted read-only)\n' "$image"
docker run --rm --platform linux/amd64 -v "$repository:/src:ro" "$image" /bin/bash -c "$smoke"
