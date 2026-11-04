# mini-factory

```sh
git clone https://github.com/n45h4n/mini-factory.git
cd mini-factory
make setup ISSUE_AGENT=codex   # or claude, or cursor
# Optional: also choose the PRs I reviewer, for example Cursor for every role:
# make setup ISSUE_AGENT=cursor PR_REVIEW_AGENT=cursor
```

`ISSUE_AGENT` selects the shared agent for both issue actions and is saved in
`${XDG_CONFIG_HOME:-$HOME/.config}/mini-factory/issue-agent`. Without it, the
first setup saves `codex` and later runs keep the saved choice; rerun with a new
value to change it. `PR_REVIEW_AGENT` saves the PRs `I` reviewer in the
`mf-config` profile (Codex is the default; without it, setup keeps the saved
reviewer). To choose the `i` and `I` agents separately, or a model and
effort per key, use [`mf-config`](#agent-profiles-mf-config). Setup installs
Codex, Claude Code, and Cursor regardless, so changing a role later needs no
new install. **Keep this clone**: No-Mistakes reads its configuration
from the tracked `no-mistakes/config.yaml` here (see
[No-Mistakes](#no-mistakes-configuration-and-unattended-runs); edit it with
[`nm-config`](#no-mistakes-global-defaults-nm-config)). Update later with
`ghd update` from any directory, or `make update` from this clone (see
[Updating](#updating)).

Complete the native login/integration steps offered by setup. If setup reports a
PATH action, run `export PATH="$HOME/.local/bin:$PATH"` in your current shell.
Then, from a terminal **outside Herdr**, open your target repository:

```sh
cd /path/to/your/repository
herdr --session my-project
```

Inside its shell pane, confirm you are in that repository. Before the first
issue `i` or PR `I`, stay in that checkout and run the **installed** doctor,
then `ghd`:

```sh
"${XDG_DATA_HOME:-$HOME/.local/share}/mini-factory/scripts/doctor.sh"
ghd
```

That doctor run checks this pane's Herdr context and the target repository's
effective Git fetch URL and authentication with a read-only `git ls-remote`.
GitHub CLI login alone does not prove Git can fetch the repository. If it
reports Git transport pending, follow [Git transport](#git-transport-for-pr-reviews-and-issue-preparation)
and rerun the same command. `make doctor` from the Mini-Factory clone, outside
Herdr, checks only the installation (it reports Git transport as not checked). In the target
checkout, `make doctor` would run that repository's own Makefile, and
`make -C /path/to/mini-factory doctor` changes away from the target.

| View | Key | Action |
| ---- | --- | ------ |
| Issues | `i` | Prepare the issue with the selected agent: check it against freshly fetched `main` (the default branch), then edit only its title/body into an executable prompt and report **ready to dispatch**, **needs a decision**, or **already satisfied**. |
| Issues | `I` | Implement the issue with the selected agent, commit it, and run No-Mistakes unattended (`--yes`) to an open PR. Never merges. |
| PRs | `I` | Review the PR **read-only** with the selected agent (Codex by default, or Claude Code or Cursor). Findings appear only in the reviewer's Herdr pane; nothing is posted to GitHub (see [What the workflows do](#what-the-workflows-do)). |

**Each target repository needs PR checks.** No-Mistakes reports a finished run
only when the PR has registered checks (GitHub Actions or external CI), or when
the owner deliberately declared `no_ci: true` in the repository's trusted
default-branch `.no-mistakes.yaml`. Set this up on the target's default branch
before relying on `I`; see the [CI prerequisite](#ci-prerequisite-for-each-target-repository).

The selected item must belong to the source repository captured by `ghd`; the
existing helpers enforce that identity. Agents start with their native model
defaults unless you save a model/effort with [`mf-config`](#agent-profiles-mf-config).
Neither setup nor `mf-config` adds trust or permission overrides; only the PR
reviewer starts in its native read-only mode. Review each agent's native
repository trust and permission prompts yourself (see
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
targeted upgrade only when an installed required formula is unsuitable (a Gum
that cannot run is repaired with `brew reinstall gum`); it does not run a
general `brew upgrade`.

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
when GitHub CLI needs installation. Gum (setup's confirmation prompt and the
`mf-config`/`nm-config` editor; offered before GitHub CLI) comes from your
configured Ubuntu archive when its `gum` candidate is version 0.15 or later (newer releases carry it
in universe); otherwise setup offers
[Charm's official apt repository](https://github.com/charmbracelet/gum#installation),
which writes `/etc/apt/keyrings/charm.asc` and `/etc/apt/sources.list.d/charm.list`.
It shows the packages and privileged changes before asking for consent. Do not
use `sudo make setup`.

For a remote server, SSH in normally, then run setup and Herdr on the server.
Herdr works through the terminal; a graphical desktop is unnecessary. Use a
terminal type installed on the server (for example `xterm-256color` if your
terminal's private terminfo is unavailable). You can detach from Herdr with its
default `ctrl+b`, then `q`, and reattach with `herdr --session my-project`.

## Installation and authentication

Setup checks tools first and reuses suitable installations. The runtime needs
Bash, Git 2.29+, Make, GitHub CLI 2.47+, jq, Python 3.9+, Gum 0.15+, Herdr,
No-Mistakes (its stable `axi run --intent`/`--yes` interface), **all three
agent CLIs (Codex, Claude Code, and Cursor)**, Node.js 22.13+ with npm, `acpx`,
and the standard system utilities used by the dispatchers. These are installed
whichever agents the roles currently select, so a later `mf-config` or
`nm-config` change needs no new install; only the agents in use need login
(below). Python supports diagnostics and safe log handling; no pip packages are
needed.
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

None of these needs Node/npm. No-Mistakes runs Cursor (`cursor` or
`acp:cursor`, as the pipeline agent or any review role) through the ACP runner
`acpx`, which needs Node.js 22.13+, so both are baseline:

- **Node.js and npm**: a suitable existing Node.js (any version manager) is
  reused. Only when `node` is missing does setup offer `brew install node` on
  macOS, or on Ubuntu `sudo apt-get install nodejs` (then `npm` if separate)
  when your configured apt sources offer 22.13+ (Ubuntu's own archive may be
  older; a configured NodeSource source qualifies). Otherwise, and for an older
  Node.js, setup prints the exact action and reports setup pending; it never
  replaces an existing Node.js or version manager, npm prefix, or shell file.
- **acpx**: an existing `acpx` the daemon can run is reused. Otherwise setup
  offers acpx's documented `npm install -g acpx@latest`, adding
  `--prefix ~/.local` when npm's global prefix is not user-writable or not on
  the No-Mistakes daemon's PATH, so acpx never needs sudo. npm's configured
  prefix is not changed.
- **Visible to the daemon**: the No-Mistakes daemon runs as a user service
  that adopts your login shell's PATH (probed as an interactive login shell for
  bash and zsh, so fnm or nvm set up in their startup files count) plus
  `~/.local/bin`, `~/go/bin`, `~/.cargo/bin`, `~/bin`, `/opt/homebrew/bin` and
  `sbin`, `/usr/local/bin` and `sbin`, `/usr/bin`, `/bin`, `/usr/sbin`, and
  `/sbin`. Setup and doctor resolve that PATH the same way and check that
  `acpx` (and the `node` it starts) runs from it, and that the first `node` on
  it is 22.13+. That check is separate from the shell Node.js and npm that
  install acpx: a suitable Node.js in your current shell does not stand in for
  an older one that the daemon finds first. When the No-Mistakes global
  config sets `acpx_path`, that executable is checked instead and setup never
  installs over it. An `acpx` or Node.js that only your current shell provides
  fails this check with the exact action instead of passing silently.

Existing installations whose capabilities fail doctor need deliberate
repair/update through their own installer; setup does not silently upgrade
unrelated software.

Every package install, privileged operation, login, and configuration change
requires explicit consent, asked with a Gum confirmation (`gum confirm`, with No
as the default; ctrl+c stops setup). Confirmations require stdin, stdout, and
stderr to be terminals and disable inherited Gum timeouts. Gum 0.15+ is required
to distinguish ctrl+c from a decline. Installing or repairing missing, broken,
or older Gum, together with any missing prerequisites offered in the same step,
uses a plain `Proceed? [y/N]` prompt; only `y` or `yes` approves.
With no interactive terminal, setup reports the
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
choice is separate from access needed by Git itself. The native login flow may
offer to set up HTTPS Git credentials; setup never repeats that prompt or
changes Git credentials. After login it notes that GitHub CLI login alone does
not prove Git can fetch a target repository. When no Git credential helper is
configured for `https://github.com`, it also prints `gh auth setup-git --hostname github.com`
as an optional follow-up for HTTPS users (see
[Git transport](#git-transport-for-pr-reviews-and-issue-preparation)). Setup installs the
extension, with consent, when it is missing:

```sh
gh extension install dlvhdr/gh-dash
```

Agent authentication stays in each agent's CLI. Setup and doctor require login
only for agents that are actually used: by a gh-dash role (`i`, `I`, or PRs
`I`), or by a No-Mistakes duty (the pipeline `agent` and any
`review_agents` reviewer/fixer/later-round role, with `acp:cursor` counting as
Cursor). Setup offers only the missing logins; installed but unused agents may
stay logged out. With the defaults, that is Codex only.

```sh
codex login --device-auth
claude auth login         # when Claude Code is used
cursor-agent login        # when Cursor is used; set NO_OPEN_BROWSER=1 when headless
```

For `agent: auto` or a fallback list, No-Mistakes picks the agent itself;
doctor notes that and relies on native `no-mistakes doctor`, so log in to those
agents yourself.

Enable device-code login in your ChatGPT security settings or workspace
permissions first, then open its URL and enter its one-time code in your own
browser. Where device login is unavailable, use native `codex login` with a
browser, or OpenAI's documented SSH callback forwarding flow. See
[official authentication guidance](https://learn.chatgpt.com/docs/auth). Do not
paste credentials into these scripts or share your authentication files. Setup
does not collect or log login output; the native CLIs control their own storage.

Herdr detects the gh-dash agents through native integrations. When Codex
handles a gh-dash role, after establishing `${CODEX_HOME:-$HOME/.codex}`, setup offers:

```sh
herdr integration install codex
```

This changes Codex's native hook/configuration files: `herdr-agent-state.sh`,
`hooks.json`, and hook settings in `config.toml`. The native Herdr installer owns
this operation and preserves other settings; we do not implement a second
config editor. When Claude Code or Cursor handles `i`, `I`, or PRs `I`, setup
offers `herdr integration install claude` or `herdr integration install cursor`,
which add Herdr's state hook to that agent's user configuration. No-Mistakes
runs its agents without Herdr, so an agent used only by a No-Mistakes duty
needs no integration. Review any native decisions yourself. Check with
`herdr integration status`.

### Agent permissions for unattended issue runs

No-Mistakes' `--yes` answers **No-Mistakes** decisions only. The issue agent
running in Herdr still asks for its own permissions: an unattended `I` needs it
to edit the worktree, run the repository's checks, `git commit`, read the
captured intent under `${XDG_STATE_HOME:-$HOME/.local/state}`, and run
`no-mistakes` (which talks to its local daemon and GitHub). Grant these through
the agent's own trust and permission settings, or answer its prompts while it
works; setup does not change them. A run waiting on such a prompt shows as
blocked in Herdr.

## Agent profiles (mf-config)

`mf-config` configures the three interactive gh-dash agents independently:

| Profile | Harness | Knobs |
| ------- | ------- | ----- |
| Issues `i` preparer | Codex, Claude Code, or Cursor | model, effort (Codex/Claude Code), Codex Fast |
| Issues `I` implementer | Codex, Claude Code, or Cursor | model, effort (Codex/Claude Code), Codex Fast |
| PRs `I` reviewer | Codex (default), Claude Code, or Cursor | model, effort (Codex/Claude Code), Codex Fast |

```sh
mf-config          # Gum editor: pick one profile, choose, preview, confirm
mf-config show     # effective values; works without a terminal (scripts, SSH)
```

Setup installs a managed `~/.local/bin/mf-config` launcher only when no other
`mf-config` command or file exists there or on `PATH`; it never replaces one.
`bin/mf-config` in your retained clone always works as the fallback.

Choices are saved in
`${XDG_CONFIG_HOME:-$HOME/.config}/mini-factory/agent-profiles.json` only after
you confirm; cancelling (Esc/Ctrl-C), declining, or invalid input leaves the
saved file unchanged. Each issue key uses, in order: its `mf-config` selection,
then the shared `ISSUE_AGENT` from setup, then Codex. An existing installation
with only `issue-agent` keeps using that agent for both keys. `make setup
ISSUE_AGENT=...` changes only the shared choice and never rewrites a per-key
selection; choose **Shared issue agent** in `mf-config` to remove one.
`mf-config` never changes the No-Mistakes pipeline agent; use
[`nm-config`](#no-mistakes-global-defaults-nm-config) for that.

Every knob offers **Native default (no override)**, which passes nothing, and a
custom/unverified value; saved custom values are kept. Pickers read only local
metadata, which is a convenience, not proof of account access:

- **Codex**: model slugs from `${CODEX_HOME:-$HOME/.codex}/models_cache.json`
  when present, and the chosen model's advertised reasoning levels (otherwise
  common levels). **Fast** On/Off is offered only when the installed Codex is
  0.154.0 or newer and the model's metadata advertises Fast; Off is the
  default. A saved On is preserved for review if metadata later disappears.
  Without an explicit Fast choice your native Fast setting is untouched. A
  missing or stale cache never blocks configuration.
- **Cursor**: model IDs from a bounded `cursor-agent --list-models`; the model
  ID owns Cursor's variant/effort, so there is no separate effort choice.
- **Claude Code**: native aliases (`opus`, `sonnet`, `haiku`, plus those named
  by `claude --help`) or an exact ID, and the effort levels `claude --help`
  lists; not every model/account supports every level.

Profiles apply only when a **fresh** Herdr agent starts, translated to the
native interactive options `--model`, Codex `--config model_reasoning_effort=...`
and `--config service_tier=...`, and Claude Code `--effort`. A fresh launch
refuses an option the installed CLI does not offer. The PR reviewer always
starts in its native interactive read-only mode (see
[What the workflows do](#what-the-workflows-do)), and a fresh launch refuses a
CLI whose help does not offer that mode; only its model/effort/Fast are
appended. `make setup PR_REVIEW_AGENT=...` saves a bare reviewer harness (or,
for `codex`, removes the override), keeping saved options for the same harness. A working, blocked, or idle agent is
reused with its original harness and options and is never restarted because
settings differ. To apply new preferences, close it (exit the agent in its
pane), then press the key again.

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
before running. Skip `gh auth setup-git` when Git already has a working
credential helper for GitHub (for example, when the native `gh auth login` flow
already set up HTTPS Git). It sets GitHub CLI as the `github.com`
credential helper in your global Git config and can replace a helper previously
configured for that host:

```sh
gh auth setup-git --hostname github.com
# In the target checkout; this also applies to its linked worktrees.
git config url."https://github.com/".insteadOf 'git@github.com:'
git ls-remote --get-url "$(gh repo view --json sshUrl --jq .sshUrl)"
git ls-remote "$(gh repo view --json sshUrl --jq .sshUrl)" HEAD
```

No SSH key is required when the effective transport is working HTTPS. Setup
does not change Git credential helpers, Git remotes, URL rewriting, or SSH
configuration. After either choice, rerun the installed doctor from the target
checkout's Herdr pane, staying in that checkout:

```sh
"${XDG_DATA_HOME:-$HOME/.local/share}/mini-factory/scripts/doctor.sh"
```

Doctor checks the effective transport only inside a target Herdr context, using
bounded, read-only `git ls-remote` and no terminal prompts. It prints the
effective URL (hiding any embedded credentials), and a failure names the SSH or
HTTPS remedy. Outside Herdr, or when the runtime context fails first, it reports
Git transport as not checked. With default SSH it requires pre-established host
trust; it does not accept host keys or create them as a side effect. A custom
`GIT_SSH`, `GIT_SSH_COMMAND`, or Git `core.sshCommand` needs manual transport
verification; doctor skips executing it and fails with Git transport not
checked. Doctor never changes remotes, URL rewriting, or the fetch protocol.

## What the workflows do

Both issue keys dispatch asynchronously through Herdr and retain the workers'
existing identity, conflict, worktree reuse, server compatibility, and
diagnostic checks. A repeated key press reuses its worktree and agent: it never
starts a second agent and never re-prompts an agent that is working or blocked
(it focuses it instead). An idle or finished agent is prompted again. If you
changed `ISSUE_AGENT` or an `mf-config` profile while an agent still exists,
that agent is kept and reused with its original options; the new choice applies
once it is closed.

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
`no-mistakes init` if the repository is not initialized, check the target's
real PR-check expectations (see the
[CI prerequisite](#ci-prerequisite-for-each-target-repository)), and start:

```sh
no-mistakes axi run --yes --intent "$(cat -- "$intent_file")"
```

The full issue title and body are untrusted data: the quoted command
substitution passes the file's contents as one argument, including multiline
text, and its output is never run as shell code. Only trailing newlines are
dropped. These are the stable CLI's documented flags. Stable No-Mistakes has
no `--intent-file` or `--closes`, so **closing the issue is not automated**:
Mini-Factory passes no closing metadata, and the agent reports this rather than
adding any. After merging, check the issue and close it yourself if needed.

The agent then drives that run with the installed No-Mistakes skill and reports
the actual outcome and PR URL. A dispatch notification only means the prompt was
delivered; see [No-Mistakes](#no-mistakes-configuration-and-unattended-runs) for
outcomes and blockers.

The distribution contains only these issue and PR review integrations. It does
not include Pepper/Factory workflows, queues, Supervisors, or Docker sandbox
infrastructure. The worker file names, state directories, and refs still say
`codex` for compatibility; the issue and PR workers run the selected agent.

PR **I** is an interactive, read-only, terminal-only review. It verifies the
selected PR's head and base, fetches both (the base without updating any local
ref), and opens or reuses a clean, detached review worktree at the PR head in
its own Herdr workspace. It writes the PR's complete diff from the merge base
(`git diff --stat --patch`) to a private file outside the worktree, named by
the merge-base and PR-head commits and never rewritten, then starts the
`mf-config` reviewer (Codex by default) in its native interactive read-only
mode:

| Reviewer | Native read-only launch |
| -------- | ----------------------- |
| Codex | `--ask-for-approval never --strict-config --cd WORKTREE` with a launch-scoped `:read-only` permission profile and no network |
| Claude Code | `--permission-mode plan` (Plan mode), `--setting-sources user`, `--add-dir` for the diff |
| Cursor | `--mode ask` (Ask mode), `--add-dir` for the diff |

The PR author controls the review worktree's project settings, which can run
commands as you when an agent starts. Claude Code therefore loads only your user
settings (your Herdr hooks still run), never the PR's `.claude/settings.json`,
`.claude/settings.local.json`, or `.mcp.json` servers. Cursor CLI has no option
to skip project hooks: once you trust the worktree, it runs `.cursor/hooks.json`
and Claude project hooks from those two settings files. PR `I` therefore refuses
to start or prompt a Cursor reviewer when the PR head defines hooks there; pick
Codex or Claude Code for that PR with `mf-config`. Cursor still asks before
starting project MCP servers; decline them in the pane. Codex loads the
worktree's `.codex/config.toml` (including MCP servers it starts at launch)
and `.codex/rules` exec policies (whose allow rules run commands outside the
sandbox) once the repository is trusted, and a review worktree inherits the
trust of your main checkout. Its interactive CLI has no option to skip project
config, so PR `I` refuses to start or prompt a Codex reviewer when the PR head
has `.codex/config.toml`, `.codex/rules`, or `.codex/hooks.json`, or when
`.codex` is a symbolic link; pick Claude Code or Cursor for that PR. Other
`.codex` content, such as skills, does not block Codex.

The prompt asks for concise, actionable findings ordered by severity with
file/line references, or an explicit "no actionable findings", **in the
reviewer's pane only**. PR `I` posts no comments or reviews, never changes
draft/ready state, and makes no other GitHub change, commit, or push. These
native modes are not hardened OS sandboxes, and an agent may still offer to
leave its read-only mode (for example Claude Code's plan approval); decline
that in the pane. A repeated `I` never
starts a second reviewer: an idle, finished, or working reviewer gets the
review prompt again with the current diff in its own file, while diffs from
earlier prompts stay readable until a fresh reviewer starts; a blocked one (for example waiting on
a plan or trust prompt) and one with an unknown status are focused instead,
never typed into. A live reviewer keeps its original harness and options; a new
`mf-config` choice applies once you exit it in its pane and press `I` again.
Herdr does not report a live reviewer's launch options, so PR `I` cannot verify
that a reused reviewer is still read-only: it warns that it may not be, and
never restarts or replaces it. Exit it in its pane and press `I` again to start
a fresh reviewer with the configured read-only options.

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

A **stable No-Mistakes release is enough**; no beta is needed. This
distribution targets the stable `no-mistakes axi run --intent ... --yes`
interface (latest stable v1.84.0 when this was written). Setup installs
No-Mistakes with its native script (stable channel) if it is missing. It reuses
any installed release whose `axi run --help` offers `--intent` and `--yes`,
including a newer prerelease you installed deliberately, so it never downgrades
one. Only when those flags are missing does setup offer the native stable
updater `no-mistakes update`, with your consent. That updater restarts the
daemon and refuses while pipeline runs are active; setup never passes `--beta`
or `--force`, and it reports the refusal instead of interrupting your runs.
`make update` offers the same stable updater as an optional upgrade (see
[Updating](#updating)). Both run before the config link is created, because they restart the daemon; the
default `config.yaml` that a fresh install writes is then kept as the backup
described below. Doctor checks the same `axi run` capability, not a version
number.

The real configuration is the tracked file **`no-mistakes/config.yaml` in this
clone**. Setup links `${NM_HOME:-$HOME/.no-mistakes}/config.yaml` to that file's
absolute path (never to the runtime copy):

- missing: the link is created;
- already the correct link: left alone;
- anything else: with consent, renamed to `config.yaml.mini-factory-backup`
  (a symbolic link is renamed, never followed) and then linked. If that backup
  already exists, setup changes nothing and reports the conflict.

```yaml
agent: codex # Initialize to the chosen pipeline agent during first setup.
auto_fix:
  review: 5
  ci: 3
```

This default uses only fields from the stable
[global config reference](https://github.com/kunchenguid/no-mistakes/blob/v1.84.0/docs/src/content/docs/reference/global-config.md).
`agent` is No-Mistakes' own pipeline agent, independent of `ISSUE_AGENT`. When
setup first creates the link and that line is unedited, it sets it to the issue
agent you chose; after that, setup never rewrites the file, including when you
change `ISSUE_AGENT`. Edit the file in the clone, or use
[`nm-config`](#no-mistakes-global-defaults-nm-config), to change any native setting;
`no-mistakes doctor` validates it. No-Mistakes rejects fields it does not know.
Earlier versions of this file had the prerelease-only
`ci.review_bot_comments` and `ci.release_after_checks_pass`. If your clone still
has them, or any other field your installed release does not support, setup
leaves the file unchanged and doctor shows the rejected fields. Remove them
yourself, or keep using a release that supports them. Your edits are local changes in the clone, so
`make update` keeps them unless an update changes the same file, in which case
it stops and you merge them yourself. Keep the clone in place: if you
move it, rerun `make setup` from the new location to relink, and deleting it
leaves No-Mistakes without its configuration.

### No-Mistakes global defaults (nm-config)

`nm-config` edits the useful stable settings in that linked clone file:

```sh
nm-config          # Gum menu: change settings, review the diff, confirm once
nm-config show     # configured global defaults; works without a terminal (scripts, SSH)
```

For example, Codex reviews, Claude Code fixes, Codex takes over fixing from
round 3, and the Review and CI fix budgets are adjusted:

```yaml
agent: codex # Initialized from the issue agent during first setup.
auto_fix:
  review: 2
  ci: 2
review_agents:
  reviewer:
    agent: codex
    effort: high
  fixer:
    agent: claude
    model: opus
    effort: max
  fixer_after_round:
    agent: codex
    after_round: 2
```

- **Settings:** `agent` (`auto` or a native harness: `codex`, `claude`,
  `grok`, `opencode`, `pi`, `copilot`, `rovodev`, `antigravity`, `cursor`,
  `devin`; an existing fallback list or `acp:<target>` is shown and kept, so
  edit those in YAML), `agent_config` model/effort per harness,
  `review_agents.reviewer`/`fixer` and their `*_after_round` overrides,
  `auto_fix` (`rebase`, `review`, `test`, `lint`, `ci`), and `session_reuse`.
  Each choice can be cleared back to the native default or inheritance.
  Efforts are the stable adapter's levels (Codex `minimal`-`high`, Claude Code
  `low`-`max`, Pi/Copilot `minimal`-`max`; Grok and OpenCode support depends on
  the model/provider); Cursor and Devin take a model only, OpenCode needs
  `provider/model`, and Rovo Dev/Antigravity take neither. Model pickers use
  mf-config's local metadata for Codex, Claude Code, and Cursor; custom IDs are
  unverified.
- **One native Review phase:** reviewer and fixer serve only its repeated
  review/fix rounds; Test, CI, and every other step use `agent`. `after_round: N`
  keeps rounds 1 to N on the base role and uses the override from round N+1.
  `auto_fix` values are maximum automatic fix attempts, not guaranteed passes.
  They are global defaults: a target repository's trusted `.no-mistakes.yaml`
  may override per-step budgets (`show` cannot know it). Saved choices apply to
  runs started afterwards, not to active runs.
- **Precedence:** `agent_args_override` is kept and its native arguments win
  over overlapping `agent_config` and role knobs (for example a Codex `-m`
  pins the model); `show` and the editor point this out.
- **Safety:** nm-config edits only the clone file linked from
  `${NM_HOME:-$HOME/.no-mistakes}/config.yaml`. It refuses a missing or broken
  link, a regular file, a link to an unrelated file (such as a dotfiles config),
  the runtime copy, or another clone, and names the fix. Edits are small line
  changes; comments, unknown and prerelease fields stay. A YAML form it cannot
  change safely (flow mappings, anchors, block scalars, ...) is refused for
  that setting; tabs, CRLF line endings, directives, or document markers other
  than one leading `---` make it refuse the whole file. Edit those by hand. Nothing is written until you confirm the
  diff. Cancelling, invalid input, or a native load rejection changes nothing.
  Before saving, the installed No-Mistakes loads the candidate in a disposable
  `NM_HOME`; unrelated daemon, login, or agent readiness problems are reported
  without blocking the edit.
- Setup installs a managed `~/.local/bin/nm-config` only when no other
  `nm-config` exists (for example from dotfiles); otherwise run `bin/nm-config`
  from this clone. Setup installs Codex, Claude Code, Cursor, and `acpx`, and
  checks login for any of them a pipeline or review role uses (including
  `acp:cursor`); install and log in to any other harness natively.

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
report as such) with the PR open for your review. The agent stops there; the
No-Mistakes daemon may keep monitoring the open PR natively.

### CI prerequisite for each target repository

`checks-passed` requires registered CI checks on the PR. A generic empty check
list is not ready, so a repository without PR checks leaves the run waiting.
Setup and doctor check only this installation, not each target repository's CI.
Each target repository therefore needs one of these on its **default branch**:

- a PR-triggered GitHub Actions workflow (for example `on: pull_request`);
- external CI that reports checks on its pull requests;
- an intentional `no_ci: true` in the trusted default-branch `.no-mistakes.yaml`,
  chosen only by the repository owner.

Mini-Factory's own CI does not provide CI to any other repository. No-Mistakes'
native `no-mistakes ci-workflow` writes `.github/workflows/ci.yml` from the
repository's `.no-mistakes.yaml` commands, but its template is Go-oriented
(`actions/setup-go`); other stacks need a suitable workflow of their own.

Before starting a run, the `I` agent checks the target's real PR-check
expectations. A missing `.github/workflows` directory alone does not prove that
no CI exists. The agent creates or edits the target's workflows for this purpose
only when the issue asks for it, never edits `.no-mistakes.yaml` for this
purpose, and never sets `no_ci`, even if the issue asks. When missing checks
are clearly established, it still delivers the PR and tells you to add
PR-triggered CI to the default branch, or to deliberately declare `no_ci: true`
there. When the agent first observes No-Mistakes waiting at CI with zero PR
checks, it starts a separate two-minute check-registration interval; earlier
run/reattach waits do not count. It polls native status and PR checks during
that interval and continues the same run normally if checks appear. Only if
that interval ends with no checks, or a blocker is independently confirmed
earlier, does it stop reattaching. It leaves the run and PR in place and checks
PR mergeability and workflow trigger status before assigning the blocker.
Zero checks alone do not prove CI is missing: a merge conflict can
prevent a `pull_request` workflow from running. The agent reports the conflict
or other observed trigger blocker, or an unknown cause if unconfirmed, along
with the exact native CI status and appropriate corrective action. It recommends
adding CI only when missing CI is independently established. After resolving
the blocker, continue with `no-mistakes axi status` from the worktree. This bundle
never bypasses CI or marks checks passed.

## Updating

```sh
ghd update                 # from any directory, or equivalently:
cd /path/to/mini-factory   # your retained clone, with main checked out
make update
```

`ghd update` runs exactly `make update` in the retained clone that setup
recorded, never in the directory or repository you run it from, and takes no
arguments. The same rules below apply. If that clone is missing, was moved, or
is no longer a Git checkout, it stops: run `make setup` from your retained
clone to record its current location. It never clones, searches, or picks
another repository. **Existing installations** get `ghd update` only after
running `make update` (or `make setup`) once from their clone.

`make update` runs only from the retained clone, on `main` with an upstream
configured. It refuses the installed runtime copy, a detached HEAD, or another
branch; switch yourself (`git switch main`), because it never switches branches.
It then:

1. **Fast-forwards only.** It fetches the upstream and runs
   `git merge --ff-only --no-autostash`, the equivalent of `git pull --ff-only`
   without depending on your rebase/autostash settings. A clean worktree is not
   required: local edits, including your tracked `no-mistakes/config.yaml`,
   carry over when upstream did not change the same files. If upstream changed
   one of them (or adds a file where you have an untracked one), or `main` has
   diverged, it stops before changing anything and prints the manual steps. It
   never resets, stashes, force-pulls, or discards configuration.
2. **Offers optional upgrades**, each with its own Gum confirmation (No by default), for every
   installed tool Mini-Factory provisions (including all three agent CLIs and
   `acpx`, whichever roles use them), through the mechanism that matches how
   each one was installed (table below).
3. **Runs `make setup`**, which refreshes the managed runtime and ends with the
   doctor checks, then prints a summary.

| Tool | Offered when installed as | Command |
| ---- | ------------------------- | ------- |
| GitHub CLI, Gum | Homebrew formula, or apt package | `brew upgrade gh` (Homebrew may refresh its index first); or `sudo apt-get update`, then `sudo apt-get install --only-upgrade gh` |
| gh-dash | the `dlvhdr/gh-dash` extension | `gh extension upgrade dash` |
| Herdr | native `~/.local/bin/herdr` | `herdr update` (no `--handoff`) |
| Codex | standalone, under `${CODEX_HOME:-~/.codex}/packages/standalone` | `codex update` |
| No-Mistakes | native, in `~/.no-mistakes/bin` | `no-mistakes update` |
| Claude Code, Cursor (whichever roles use them) | native, under `~/.local/share/claude` or `~/.local/share/cursor-agent` | `claude update`, `cursor-agent update` |
| Node.js and npm | Homebrew `node` formula, or apt `nodejs` (with `npm` when installed separately) | `brew upgrade node`; or `sudo apt-get update`, then `sudo apt-get install --only-upgrade nodejs npm` |
| acpx | setup's npm install (`~/.local`, or a writable npm global prefix) | `npm install -g [--prefix ~/.local] acpx@latest` |

A native updater is offered only when the installed CLI lists it. Any other
installation (for example npm, or a package manager not shown) gets manual
guidance instead, and missing tools are left to setup. A Node.js from fnm, nvm,
Volta, or another installer gets the exact command to run yourself: `make update`
never changes a Node version manager, npm prefix, or shell configuration, and the
setup/doctor run that follows checks that `acpx` still runs for the No-Mistakes
daemon. Each updater decides whether a newer release exists: Mini-Factory
compares no versions and never runs a general `brew upgrade` or `apt upgrade`.
System prerequisites (Git, Make, jq, Python, curl, tar) keep setup's targeted
checks.

- **Stable only.** No-Mistakes is updated with plain `no-mistakes update`, never
  `--beta`, `--force`, or `--yes`. Its updater reports a newer prerelease you
  installed deliberately as already up to date instead of downgrading it, and it
  refuses while pipeline runs are active; those runs are left alone, so rerun
  `make update` after they finish. Manage beta releases yourself, outside
  `make update`.
- **Consent.** Declining (`n`, Esc, or Enter on the default No) keeps the
  installed version; ctrl+c stops `make update` before it reruns setup. Without
  an interactive terminal (for example `ssh host 'cd mini-factory && make update'`),
  or when Gum cannot run or is older than 0.15, upgrade prompts are skipped with
  the commands to run yourself; no approval is assumed, and the setup run that
  follows offers to repair Gum.
  A failed updater makes `make update` exit nonzero. It may already have changed
  its tool, so nothing is rolled back; the setup and doctor output shows whether
  the installation still works. A refused fast-forward or a failed setup also
  exits nonzero with the action to take.
- `make update` never runs automatically or in the background, and never edits
  shell startup files.

## Managed files, diagnostics, and updates

Setup copies the runtime into
`${XDG_DATA_HOME:-$HOME/.local/share}/mini-factory/`, with a
`.mini-factory-install` ownership marker and a `.mini-factory-clone` record of
the clone's path (read as data by `ghd update`), and installs the managed wrapper
`~/.local/bin/ghd`, plus the optional `~/.local/bin/mf-config` and `nm-config` launchers described
above. The dashboard runtime works on its own, but the clone must
stay where it is for the No-Mistakes configuration link above and for
`ghd update`; run setup from
the clone, never from the runtime copy. Updates replace only this project's
marked runtime and exact managed wrapper after validating the staged bundle. An
unrelated installation directory or `ghd` command is refused. Do not store
personal files in the managed runtime.

Setup also manages only the missing dependency installations you approve,
GitHub CLI's extension installation, your explicitly requested native logins,
the Codex directory and native Herdr integrations above, the shared issue-agent
setting, and the No-Mistakes configuration link. Only `mf-config` writes
`agent-profiles.json`. On Ubuntu an approved
GitHub CLI installation writes
`/etc/apt/keyrings/githubcli-archive-keyring.gpg` and
`/etc/apt/sources.list.d/github-cli.list`; an approved Gum installation from
Charm's repository writes the Charm files listed above.
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
launch from this context**. It checks the tools and versions above (including
Gum, all three agent CLIs, Node.js 22.13+ and npm in your shell, and Node.js
22.13+ and `acpx` running from the No-Mistakes daemon's PATH), the shared issue agent and each gh-dash role's
effective agent, authentication for the agents a gh-dash role or No-Mistakes
duty uses, Herdr integrations for the gh-dash roles' agents only, the
No-Mistakes configuration link, and the pipeline agent's readiness via native
`no-mistakes doctor` (run without update checks or telemetry). Unused agents may
stay logged out. Doctor checks No-Mistakes login only for duties set to
`claude`, `codex`, `cursor`, or `acp:cursor`; for other native selections such
as `auto` or agent lists it prints a note and relies on native doctor, which
proves only that the agent runs, so log in to that agent through its own CLI.
Outside Herdr it skips runtime-context and Git transport checks and explains how to enter a pane.
Inside Herdr it checks the inherited route, active compatible server, the
gh-dash roles' detection manifests, target repository, and Git transport. To
check a target, run the installed
`"${XDG_DATA_HOME:-$HOME/.local/share}/mini-factory/scripts/doctor.sh"` from
its Herdr pane, as in the quick start. `make doctor` above checks this
installation from the clone. It notes, without
failing, when the optional `mf-config` or `nm-config` launcher is not on `PATH`. It never starts
agents or pipelines, creates worktrees, sends prompts, writes PR comments, or
marks PRs ready. It returns nonzero for required failed/pending checks.

Dispatcher diagnostics live in
`${XDG_STATE_HOME:-$HOME/.local/state}/gh-dash-codex-issue/` (preparation logs
end in `-prepare.log`; captured intents are in its private `intents/`
directory) and `${XDG_STATE_HOME:-$HOME/.local/state}/gh-dash-codex-pr-review/`
(review diffs are in its private `contexts/` directory, one
`pr-MERGE_BASE-HEAD.diff` per reviewed commit pair).
Preparation keeps its last fetched default-branch commit under
`refs/gh-dash-issue-prepare/` in the target repository. Dispatch reports the
relevant log path. Herdr's default-session logs are under
`~/.config/herdr/`; named-session logs live under its `sessions/NAME/` directory.

To update, run `ghd update` from any directory, or `make update` from your
retained clone (see [Updating](#updating)).

`make help` lists the five standalone targets. `make test` uses disposable homes
and Git repositories with mocked external tools; it needs Bash, Git, Make, jq,
and Python 3.9+. It does not install packages or authenticate/run agents, and it
needs no live No-Mistakes daemon, network installer, GitHub write, or real PR.

## Maintainer: development

This repository is now the source of truth for mini-factory. Make changes here
to the launcher, setup/doctor scripts, gh-dash configuration, workers, and tests.
No dotfiles checkout or export step is required.

Keep the existing runtime-relative directory layout when updating the workers.

Before committing changes, review the diff and run the focused checks:

```sh
git diff --check
make test
# For changes to the launcher, setup/doctor, or worker shell scripts:
bash -n bin/ghd bin/mf-config bin/nm-config scripts/setup.sh scripts/update.sh scripts/doctor.sh scripts/integrations/gh-dash/*.sh
shellcheck -x bin/ghd bin/mf-config bin/nm-config scripts/setup.sh scripts/update.sh scripts/doctor.sh scripts/integrations/gh-dash/*.sh
```

Commit and push reviewed changes to this repository. Users update with
`ghd update` from any directory, or `make update` from their clone (a
fast-forward, consented tool upgrades, then `make setup`). There is no
background updater or automatic cross-repository sync.

Mini-Factory's own CI, `.github/workflows/ci.yml`, runs `make test` on an Ubuntu
runner for every pull request and push to `main`, with read-only repository
permissions. That gives No-Mistakes a real PR check to observe here. The
workflow file alone does not prove CI works: GitHub Actions must be enabled for
the repository and the check must actually appear on the PR. It does not apply
to target repositories (see the
[CI prerequisite](#ci-prerequisite-for-each-target-repository)).

Installation instructions were checked against upstream documentation and native
CLI help on 2026-10-08; the issue-agent additions against Herdr 0.9.5 help and
Claude Code/Cursor CLI help and installers on 2026-10-30; and the stable
No-Mistakes support against the v1.84.0 (latest stable) documentation and native
help on 2026-11-01; `mf-config` against Codex CLI 0.166.0, Claude Code 2.1.316,
Cursor CLI 2026.10.22, Gum 2.0.2, and Herdr 0.9.5 help on 2026-11-01; and
`nm-config` against the No-Mistakes v1.84.0 global config reference and its
native config loader (`no-mistakes doctor`) on 2026-11-01; and `make update`
against the native help and installers of Herdr 0.9.5, Codex CLI 0.166.0,
Claude Code 2.1.316, Cursor CLI 2026.10.22, and GitHub CLI 2.103.3, and the
No-Mistakes v1.84.0 updater source, on 2026-11-02; and the selectable read-only
PR reviewer against the native help of Codex CLI 0.166.0 (including a local
`codex sandbox` check of the no-network `:read-only` profile), Claude Code
2.1.317 (`--permission-mode plan`, `--add-dir`), and Cursor CLI 2026.10.22
(`--mode ask`, `--add-dir`) on 2026-11-02; and, with local hook fixtures on
2026-11-03, that Claude Code 2.1.317 with `--setting-sources user` skips project
and local hooks and `.mcp.json` servers while running user hooks, and that
trusted Cursor CLI 2026.10.22 Ask mode runs `.cursor/hooks.json` and Claude
project hooks; and, against the Codex CLI 0.166.0 source and an isolated local
`codex mcp list` check on 2026-11-03, that a linked worktree of a trusted main
checkout loads that worktree's `.codex/config.toml` MCP servers and
`.codex/rules`, while hook declarations come from the main checkout and run
only with persisted hook trust. Mocked
macOS/Ubuntu coverage is not
native verification. Native macOS and Ubuntu Server installation and live
Herdr/agent/No-Mistakes onboarding still need verification by users on those
hosts.

### Real-machine smoke test

Run this on a separate, disposable test host or account after merging, never
against a workstation you depend on. Use a test repository with registered CI
checks (or an owner-declared `no_ci: true`) and a small, real issue.

1. Fresh clone, `make setup ISSUE_AGENT=<agent>`, complete the native logins,
   then `make doctor` reports ready.
2. In a Herdr pane of the test repository, run the installed doctor (as in the
   quick start) until it reports Git transport authenticated, then run `ghd`, select the issue, press
   `i`: the preparation agent reports the `main` branch/commit it inspected and
   one verdict, and edits only the issue's title/body.
3. Press `I`: the implementation agent commits on `agent/issue-N`, starts
   `no-mistakes axi run --yes --intent ...` with the captured issue, and drives it.
4. Confirm the agent's final report gives the actual No-Mistakes outcome and the
   open PR URL, including any skips, overrides, or blockers, and that the PR was
   not merged.
5. In the PRs view, press `I` on that PR once for each reviewer (`mf-config`
   PRs `I`: Codex, Claude Code, Cursor; exit the previous reviewer in its pane
   first): each starts in its read-only mode, reads the diff file, and reports
   findings or "no actionable findings" only in its pane. The PR gets no new
   comment, review, or draft/ready change, and the review worktree stays clean.
6. From the clone, `make update` fast-forwards (or reports already up to date),
   offers only the native upgrades that match each tool's installation, and
   ends with setup's doctor report. `ghd update` from another directory does
   the same for the recorded clone.
