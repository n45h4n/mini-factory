# gh-dash-share

```sh
git clone https://github.com/n45h4n/gh-dash-share.git
cd gh-dash-share
make setup ISSUE_AGENT=codex   # or claude, or cursor
```

`ISSUE_AGENT` selects the agent for both issue actions and is saved in
`${XDG_CONFIG_HOME:-$HOME/.config}/gh-dash-share/issue-agent`. Without it, the
first setup saves `codex` and later runs keep the saved choice; rerun with a new
value to change it. **Keep this clone**: No-Mistakes reads its configuration
from the tracked `no-mistakes/config.yaml` here (see
[No-Mistakes](#no-mistakes-configuration-and-unattended-runs)).

Complete the native login/integration steps offered by setup. If setup reports a
PATH action, run `export PATH="$HOME/.local/bin:$PATH"` in your current shell.
Then, from a terminal **outside Herdr**, open your target repository:

```sh
cd /path/to/your/repository
herdr --session my-project
```

Inside its shell pane, confirm you are in that repository and run:

```sh
ghd
```

| View | Key | Action |
| ---- | --- | ------ |
| Issues | `i` | Prepare the issue with the selected agent: check it against freshly fetched `main` (the default branch), then edit only its title/body into an executable prompt and report **ready to dispatch**, **needs a decision**, or **already satisfied**. |
| Issues | `I` | Implement the issue with the selected agent, commit it, and run No-Mistakes unattended (`--yes`) to an open PR. Never merges. |
| PRs | `I` | Review the PR with **Codex** (unchanged; see [What the workflows do](#what-the-workflows-do)). |

The selected item must belong to the source repository captured by `ghd`; the
existing helpers enforce that identity. Agents start with their native model
defaults. Setup adds no model, effort, trust, or permission overrides: review
each agent's native repository trust and permission prompts yourself (see
[Agent permissions](#agent-permissions-for-unattended-issue-runs)).

If you already have a Herdr session, run this from an existing Herdr shell pane
to create and focus a workspace associated with the target checkout:

```sh
herdr workspace create --cwd /path/to/your/repository --label my-project --focus
```

Run `ghd` in the **new workspace's shell pane**. Do not launch nested `herdr`
inside an existing pane. These commands were checked against Herdr 0.9.3's native
help and its [onboarding guide](https://herdr.dev/agent-guide.md). A fresh session
may show Herdr's own onboarding screen before its shell appears.

## Bootstrap on macOS

Supported architectures are Intel x86_64 and Apple Silicon arm64. Git and Make
must exist before the clone/setup commands can run. Apple's Command Line Tools
provide them:

```sh
xcode-select --install
```

Complete Apple's installer. If tools are missing, setup uses Homebrew for only
the required packages. Install Homebrew first using its
[official instructions](https://brew.sh/) and apply the `brew shellenv` command
it prints for your machine. Setup does not install Homebrew or change your shell
startup files. It disables Homebrew's automatic update/cleanup and offers a
targeted upgrade only when an installed required formula is unsuitable; it does
not run a general `brew upgrade`.

## Bootstrap on native Ubuntu Server

Supported: Ubuntu 22.04 or newer, x86_64 or arm64. WSL and other Linux
distributions are outside this distribution's support. Start as a regular user
with sudo access, not as root:

```sh
sudo apt-get update
sudo apt-get install --no-install-recommends git make ca-certificates
```

These are unavoidable prerequisites for cloning and running `make setup`.
Setup offers apt installation for missing tools and the
[official GitHub CLI apt repository](https://github.com/cli/cli/blob/trunk/docs/install_linux.md)
when GitHub CLI needs installation. It shows the packages and privileged changes
before asking for consent. Do not use `sudo make setup`.

For a remote server, SSH in normally, then run setup and Herdr on the server.
Herdr works through the terminal; a graphical desktop is unnecessary. Use a
terminal type installed on the server (for example `xterm-256color` if your
terminal's private terminfo is unavailable). You can detach from Herdr with its
default `ctrl+b`, then `q`, and reattach with `herdr --session my-project`.

## Installation and authentication

Setup checks tools first and reuses suitable installations. The runtime needs
Bash, Git 2.29+, Make, GitHub CLI 2.47+, jq, Python 3.9+, Codex, Herdr,
No-Mistakes v1.105.0+, the selected issue agent, the configured No-Mistakes
pipeline agent, and the standard system utilities used by the dispatchers.
**Codex is always required** because the PR `I` review route still runs Codex,
even when Claude Code or Cursor handles issues. Python supports diagnostics and
safe log handling; no pip packages are needed.
The GitHub CLI minimum avoids the community Ubuntu 2.45/2.46 releases' deprecated
API failures documented by [GitHub CLI](https://github.com/cli/cli/blob/trunk/docs/install_linux.md#ubuntu-community).
Curl and tar support the native installers. Missing tools are installed only
with consent, each through its own upstream installer, placing commands in
`~/.local/bin`:

| Tool | Native installer | Native login |
| ---- | ---------------- | ------------ |
| Codex | [standalone installer](https://learn.chatgpt.com/docs/codex/cli) | `codex login --device-auth` |
| Claude Code | `https://claude.ai/install.sh` | `claude auth login` |
| Cursor CLI | `https://cursor.com/install` (installs `cursor-agent` and `agent`) | `cursor-agent login` |
| Herdr | [installer](https://herdr.dev/install.sh) | n/a |
| No-Mistakes | [install script](https://github.com/kunchenguid/no-mistakes/blob/main/docs/install.sh) (binary in `~/.no-mistakes/bin`, user daemon service) | n/a |

None of these needs Node/npm. The exception is Cursor as the **No-Mistakes
pipeline agent**: No-Mistakes runs it through the ACP runner `acpx`, which needs
Node.js 22.13+. Setup reuses a suitable Node/npm on `PATH`; otherwise it offers
`brew install node` (or `brew upgrade node`) on macOS, or Node.js 24 LTS from the
[NodeSource apt repository](https://github.com/nodesource/distributions) on Ubuntu
(it shows the key, source list, and apt pin it writes before asking). It then offers
acpx's documented `npm install -g acpx@latest`, adding `--prefix ~/.local` when
npm's global prefix is not user-writable so acpx never needs sudo. Declining
either step leaves the prerequisite reported as pending.
Cursor as the issue agent alone does not need acpx. Existing installations whose
capabilities fail doctor need deliberate repair/update through their own
installer; setup does not silently upgrade unrelated software.

Every package install, privileged operation, login, and configuration change
requires explicit consent. With no interactive terminal, setup reports the
remaining action and exits unsuccessfully instead of waiting or assuming yes.
A pending login/integration/PATH action can leave a valid runtime installed;
rerunning setup completes onboarding. It is safe to run outside a target Git
repository and outside Herdr.

GitHub API authentication is checked quietly. To log in yourself:

```sh
gh auth login --hostname github.com --web
```

Follow the CLI's one-time device code and URL in a browser on your laptop if the
server is headless. When setup runs this login it separately offers GitHub's
optional `project` scope, for GitHub Projects only; ordinary issue and PR
actions do not need it. To add it later:
`gh auth refresh --hostname github.com --scopes project`. GitHub CLI's transport
choice is separate from access needed by Git itself. Setup installs the
extension, with consent, when it is missing:

```sh
gh extension install dlvhdr/gh-dash
```

Agent authentication stays in each agent's CLI; setup checks the issue agent,
the pipeline agent, and Codex (PR reviews), and offers only the missing logins:

```sh
codex login --device-auth
claude auth login         # when Claude Code is selected
cursor-agent login        # when Cursor is selected; set NO_OPEN_BROWSER=1 when headless
```

Enable device-code login in your ChatGPT security settings or workspace
permissions first, then open its URL and enter its one-time code in your own
browser. Where device login is unavailable, use native `codex login` with a
browser, or OpenAI's documented SSH callback forwarding flow. See
[official authentication guidance](https://learn.chatgpt.com/docs/auth). Do not
paste credentials into these scripts or share your authentication files. Setup
does not collect or log login output; the native CLIs control their own storage.

After establishing `${CODEX_HOME:-$HOME/.codex}`, setup offers:

```sh
herdr integration install codex
```

This changes Codex's native hook/configuration files: `herdr-agent-state.sh`,
`hooks.json`, and hook settings in `config.toml`. The native Herdr installer owns
this operation and preserves other settings; we do not implement a second
config editor. When Claude Code or Cursor is the issue agent, setup also offers
`herdr integration install claude` or `herdr integration install cursor`, which
add Herdr's state hook to that agent's user configuration. Review any native
decisions yourself. Check with `herdr integration status`.

### Agent permissions for unattended issue runs

No-Mistakes' `--yes` answers **No-Mistakes** decisions only. The issue agent
running in Herdr still asks for its own permissions: an unattended `I` needs it
to edit the worktree, run the repository's checks, `git commit`, read the
captured intent under `${XDG_STATE_HOME:-$HOME/.local/state}`, and run
`no-mistakes` (which talks to its local daemon and GitHub). Grant these through
the agent's own trust and permission settings, or answer its prompts while it
works; setup does not change them. A run waiting on such a prompt shows as
blocked in Herdr.

## Git transport for PR reviews and issue preparation

The existing PR worker, and issue preparation's default-branch fetch, use
GitHub's `sshUrl`, including when `origin` uses HTTPS. With the default SSH transport, configure your own GitHub SSH key and
verify GitHub's host key using
[GitHub's SSH instructions](https://docs.github.com/en/authentication/connecting-to-github-with-ssh).
Then check in your target checkout:

```sh
git ls-remote "$(gh repo view --json sshUrl --jq .sshUrl)" HEAD
```

If you already use authenticated HTTPS, you can deliberately route this URL
through Git's native rewriting instead. These optional commands change your Git
credential configuration and the target repository's local config; review them
before running:

```sh
gh auth setup-git --hostname github.com
# In the target checkout; this also applies to its linked worktrees.
git config url."https://github.com/".insteadOf 'git@github.com:'
git ls-remote --get-url "$(gh repo view --json sshUrl --jq .sshUrl)"
git ls-remote "$(gh repo view --json sshUrl --jq .sshUrl)" HEAD
```

No SSH key is required when the effective transport is working HTTPS. Setup
does not change Git credential helpers, Git remotes, URL rewriting, or SSH
configuration. Doctor checks the effective transport only inside a target
Herdr context, using bounded, read-only `git ls-remote` and no terminal prompts.
With default SSH it requires pre-established host trust; it does not accept host
keys or create them as a side effect. A custom `GIT_SSH`, `GIT_SSH_COMMAND`, or
Git `core.sshCommand` needs manual transport verification; doctor skips executing
it and reports pending.

## What the workflows do

Both issue keys dispatch asynchronously through Herdr and retain the workers'
existing identity, conflict, worktree reuse, server compatibility, and
diagnostic checks. A repeated key press reuses its worktree and agent: it never
starts a second agent and never re-prompts an agent that is working or blocked
(it focuses it instead). An idle or finished agent is prompted again. If you
changed `ISSUE_AGENT` while an agent of the old kind still exists, that agent is
kept and reused; the new choice applies once it is closed.

Issue **i** fetches the repository's default branch from GitHub immediately and
creates or reuses a separate `agent/prepare-issue-N` worktree, Herdr workspace,
and agent; it never touches the implementation session. A new preparation
branch starts at the fetched commit. A retained preparation worktree is reused
(fast-forwarded to it when behind) only when its agent is not working or
blocked, it has no local changes, and it has not diverged; otherwise nothing is
refreshed or sent,
and the notification explains how to start fresh (close the agent, run
`herdr worktree remove --workspace ID`, delete the branch). If the fetch fails,
preparation does not start rather than analysing an older snapshot. The prompt
names the branch and commit inspected and allows only title/body edits of that
issue.

Issue **I** creates or reuses an `agent/issue-N` implementation worktree. A new
branch starts at the commit `ghd` captured (below), which can be older than the
`main` commit a preparation inspected; the prompt and notification show the
starting branch and SHA, or the retained branch's current SHA. The helper
captures the issue title and body into a private file outside the worktree, and
the prompt asks the agent to implement and commit the change, run
`no-mistakes init` if the repository is not initialized, and start:

```sh
no-mistakes axi run --yes --intent-file "$intent_file" --closes "$issue_number"
```

It then drives that run with the installed No-Mistakes skill and reports the
actual outcome and PR URL. A dispatch notification only means the prompt was
delivered; see [No-Mistakes](#no-mistakes-configuration-and-unattended-runs) for
outcomes and blockers.

The distribution contains only these issue and PR review integrations. It does
not include Pepper/Factory workflows, queues, Supervisors, or Docker sandbox
infrastructure. The worker file names still say `codex` for compatibility; the
issue workers run the selected agent.

PR **I is not read-only**. It opens/reuses a PR review worktree and asks Codex to
review the selected PR. The existing prompt can publish or update the review
comment carrying the marker `<!-- gh-dash-codex-pr-review -->`. Under its existing
all-clear conditions it can also mark a draft PR ready. Review runs use your
own GitHub identity and permissions.

`ghd` captures the physical source root, canonical GitHub repository, branch,
commit SHA, and dirty status **before** opening gh-dash. New implementation
worktrees contain the captured committed snapshot; uncommitted/untracked changes stay in
your source checkout. A dirty checkout produces a warning. Detached HEAD and
repositories without a commit are rejected. Later changes in the source checkout
do not replace the captured snapshot. Invoke `ghd` from the target checkout,
not from this distribution's clone.

The bundled config includes existing defaults and exactly the three custom
bindings above. Personal config files are preserved. `ghd` explicitly selects its
bundled config and refuses config override flags; ordinary flags such as
`--debug`, `--cpuprofile PATH`, `--help`, and `--version` are forwarded.

## No-Mistakes configuration and unattended runs

This distribution is tested with **No-Mistakes v1.105.0**, a prerelease. The
stable channel (v1.84.0 when this was written) lacks the bot settings below, so
a plain stable/latest install is not enough. Setup installs No-Mistakes with its
native script if it is missing and, when the installed version is older than
v1.105.0, offers its native updater `no-mistakes update --beta` (newest
prerelease; it restarts the daemon and refuses while runs are active). Both run
before the config link is created, because the installer restarts the daemon
and older releases reject the bot fields; the default `config.yaml` that a
fresh install writes is then kept as the backup described below. Doctor checks
the version and the `axi run` flags used here. Newer releases are
accepted when they pass those checks.

The real configuration is the tracked file **`no-mistakes/config.yaml` in this
clone**. Setup links `${NM_HOME:-$HOME/.no-mistakes}/config.yaml` to that file's
absolute path (never to the runtime copy):

- missing: the link is created;
- already the correct link: left alone;
- anything else: with consent, renamed to `config.yaml.gh-dash-share-backup`
  (a symbolic link is renamed, never followed) and then linked. If that backup
  already exists, setup changes nothing and reports the conflict.

```yaml
agent: codex # Initialize to the chosen pipeline agent during first setup.
auto_fix:
  review: 3
  ci: 3
ci:
  review_bot_comments: always
  release_after_checks_pass: true
```

`agent` is No-Mistakes' own pipeline agent, independent of `ISSUE_AGENT`. When
setup first creates the link and that line is unedited, it sets it to the issue
agent you chose; after that, setup never rewrites the file, including when you
change `ISSUE_AGENT`. Edit the file in the clone to change any native setting
(see the [global config reference](https://github.com/kunchenguid/no-mistakes/blob/v1.105.0/docs/src/content/docs/reference/global-config.md));
`no-mistakes doctor` validates it. Your edits are local changes in the clone, so
`git pull --ff-only` keeps them unless an update changes the same file, in which
case Git stops and you merge them yourself. Keep the clone in place: if you
move it, rerun `make setup` from the new location to relink, and deleting it
leaves No-Mistakes without its configuration.

**Unattended means `--yes`.** `no-mistakes axi run --yes` resolves ordinary
gates natively: it selects the findings for a fix round, accepts the result, and
fixes each step at most once, so it is not an unlimited fix-until-clean loop.
`auto_fix` sets the automatic attempts made before a gate. `yolo: true` is
**not** a configuration key. Review conversations
are not enabled. Some states still need an explicit answer that `--yes` does not
give, such as a protected-path refusal, an open review question, or a Test
budget cut. The agent leaves the run and work in place and reports the blocker
with the native next step; you continue with `no-mistakes axi status` and the
command it suggests (for example `no-mistakes axi respond`, or reattaching with
`no-mistakes axi run --yes` from the worktree). A bounded wait expiring is not a
failure: the agent checks `axi status` and reattaches to the same run. Nothing
is merged automatically. A successful run ends at `checks-passed` (or a
qualified `passed-with-skips` / `passed-with-override`, which the agent must
report as such) with the PR open for your review, and with
`release_after_checks_pass: true` the run then stops monitoring it.

**CI prerequisite.** `checks-passed` requires registered CI checks on the PR.
A repository intentionally operated without CI can declare `no_ci: true` in
`.no-mistakes.yaml` on its trusted default branch; only the repository owner
should make that choice. Otherwise an empty check list stays waiting. This
bundle never adds that declaration or uses it to get past missing or failing
checks.

**Review bots.** No-Mistakes' native bot support reads unresolved bot review
comments (`review_bot_comments: always`). CodeRabbit users can additionally
require a completed CodeRabbit review by adding this to the target repository's
trusted default-branch `.no-mistakes.yaml`:

```yaml
ci:
  required_reviews: [coderabbit]
```

This bundle does not require any bot globally.

## Managed files, diagnostics, and updates

Setup copies the runtime into
`${XDG_DATA_HOME:-$HOME/.local/share}/gh-dash-share/`, with a
`.gh-dash-share-install` ownership marker, and installs the managed wrapper
`~/.local/bin/ghd`. The dashboard runtime works on its own, but the clone must
stay where it is for the No-Mistakes configuration link above; run setup from
the clone, never from the runtime copy. Updates replace only this project's
marked runtime and exact managed wrapper after validating the staged bundle. An
unrelated installation directory or `ghd` command is refused. Do not store
personal files in the managed runtime.

Setup also manages only the missing dependency installations you approve,
GitHub CLI's extension installation, your explicitly requested native logins,
the Codex directory and native Herdr integrations above, the issue-agent
setting, and the No-Mistakes configuration link. On Ubuntu an approved
GitHub CLI installation writes
`/etc/apt/keyrings/githubcli-archive-keyring.gpg` and
`/etc/apt/sources.list.d/github-cli.list`; an approved Node.js installation
writes `/etc/apt/keyrings/nodesource.asc`,
`/etc/apt/sources.list.d/nodesource.list`, and `/etc/apt/preferences.d/nodejs`.
It never copies the maintainer's
credentials or personal config. Existing gh-dash, Herdr, shell and unrelated
agent settings are preserved.

If `~/.local/bin` is missing from PATH, the exact action in your current shell is:

```sh
export PATH="$HOME/.local/bin:$PATH"
```

Add that line to your chosen shell's startup file yourself for future shells.
A child setup process cannot update its parent shell environment. Reopen/reload
the shell before retrying `ghd` if another command shadows it.

```sh
make doctor
```

Doctor separates **installed**, **authentication/setup pending**, and **ready to
launch from this context**. It checks the tools and versions above, the saved
issue agent, authentication for Codex, the issue agent, and the pipeline agent,
their Herdr integrations, `acpx` when Cursor is the pipeline agent, the
No-Mistakes configuration link, and the pipeline agent's readiness via native
`no-mistakes doctor` (run without update checks or telemetry). Doctor checks
pipeline login only for `agent: claude`, `codex`, or `cursor`; other native
selections such as `auto`, `acp:...`, or agent lists stay pending as
authentication unverified, because native doctor proves only that the agent
runs. Outside Herdr it
skips runtime-context checks and explains how to enter a pane. Inside Herdr it
checks the inherited route, active compatible server, Codex and issue-agent
detection manifests, target repository, and Git transport. It never starts
agents or pipelines, creates worktrees, sends prompts, writes PR comments, or
marks PRs ready. It returns nonzero for required failed/pending checks.

Dispatcher diagnostics live in
`${XDG_STATE_HOME:-$HOME/.local/state}/gh-dash-codex-issue/` (preparation logs
end in `-prepare.log`; captured intents are in its private `intents/`
directory) and `${XDG_STATE_HOME:-$HOME/.local/state}/gh-dash-codex-pr-review/`.
Preparation keeps its last fetched default-branch commit under
`refs/gh-dash-issue-prepare/` in the target repository. Dispatch reports the
relevant log path. Herdr's default-session logs are under
`~/.config/herdr/`; named-session logs live under its `sessions/NAME/` directory.

To update from your retained clone:

```sh
git pull --ff-only
make setup
no-mistakes update --beta   # optional: newer No-Mistakes prerelease, natively
```

`make help` lists the four standalone targets. `make test` uses disposable homes
and Git repositories with mocked external tools; it needs Bash, Git, Make, jq,
and Python 3.9+. It does not install packages or authenticate/run agents.

## Maintainer: development

This repository is now the source of truth for gh-dash-share. Make changes here
to the launcher, setup/doctor scripts, gh-dash configuration, workers, and tests.
No dotfiles checkout or export step is required.

Keep the existing runtime-relative directory layout when updating the workers.

Before committing changes, review the diff and run the focused checks:

```sh
git diff --check
make test
# For changes to the launcher, setup/doctor, or worker shell scripts:
bash -n bin/ghd scripts/setup.sh scripts/doctor.sh scripts/integrations/gh-dash/*.sh
shellcheck -x bin/ghd scripts/setup.sh scripts/doctor.sh scripts/integrations/gh-dash/*.sh
```

Commit and push reviewed changes to this repository. Users update their clone
with `git pull --ff-only`, then run `make setup` to refresh the installed copy.
There is no background updater or automatic cross-repository sync.

Installation instructions were checked against upstream documentation and native
CLI help on 2026-10-08; the issue-agent and No-Mistakes additions against Herdr
0.9.5 help, Claude Code/Cursor CLI help and installers, and the No-Mistakes
v1.105.0 documentation on 2026-10-30. Mocked macOS/Ubuntu coverage is not
native verification. Native macOS and Ubuntu Server installation and live
Herdr/agent/No-Mistakes onboarding still need verification by users on those
hosts.

### Real-machine smoke test

Run this on a separate, disposable test host or account after merging, never
against a workstation you depend on. Use a test repository with registered CI
checks (or an owner-declared `no_ci: true`) and a small, real issue.

1. Fresh clone, `make setup ISSUE_AGENT=<agent>`, complete the native logins,
   then `make doctor` reports ready.
2. In a Herdr pane of the test repository, run `ghd`, select the issue, press
   `i`: the preparation agent reports the `main` branch/commit it inspected and
   one verdict, and edits only the issue's title/body.
3. Press `I`: the implementation agent commits on `agent/issue-N`, starts
   `no-mistakes axi run --yes`, and drives it.
4. Confirm the agent's final report gives the actual No-Mistakes outcome and the
   open PR URL, including any skips, overrides, or blockers, and that the PR was
   not merged.
