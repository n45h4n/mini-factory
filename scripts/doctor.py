#!/usr/bin/env python3
"""Read-only installation and inherited Herdr route checks. No dispatch."""

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys


def output(argv, environment=None, timeout=15):
    try:
        result = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, env=environment)
        return result.stdout if result.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def authenticated(argv):
    # Native authentication status may contain credential details; never collect it.
    try:
        return subprocess.run(argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                              timeout=20).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


# The three gh-dash agents keep their own native install and login flows; all three are installed.
AGENTS = {
    "claude": ("claude", "Claude Code", "claude auth login"),
    "codex": ("codex", "Codex", "codex login --device-auth"),
    "cursor": ("cursor-agent", "Cursor", "cursor-agent login"),
}
# Diagnostics stay side-effect free: no background update check or telemetry event.
NO_MISTAKES_ENVIRONMENT = dict(os.environ, NO_MISTAKES_NO_UPDATE_CHECK="1", NO_MISTAKES_TELEMETRY="0")
ROLES = (("issue-prepare", "Issues i preparer"), ("issue-implement", "Issues I implementer"),
         ("pr-review", "PRs I reviewer"))
# The fixed PATH No-Mistakes gives its daemon service (shellenv.WellKnownBinDirsForHome). The daemon appends it to
# its login shell's PATH and keeps only it when that probe fails; your current shell's PATH is not assumed.
SERVICE_PATH = os.pathsep.join([str(Path.home() / name) for name in (".local/bin", "go/bin", ".cargo/bin", "bin")]
                               + ["/opt/homebrew/bin", "/opt/homebrew/sbin", "/usr/local/bin", "/usr/local/sbin",
                                  "/usr/bin", "/bin", "/usr/sbin", "/sbin"])


def agent_authenticated(kind):
    if kind == "claude":
        return authenticated(["claude", "auth", "status"])
    if kind == "codex":
        return authenticated(["codex", "login", "status"])
    # Cursor's status exits 0 while logged out; read only its boolean field.
    try:
        return json.loads(output(["cursor-agent", "status", "--format", "json"])).get("isAuthenticated") is True
    except (TypeError, ValueError, AttributeError):
        return False


def issue_agent_setting():
    path = Path(os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")) / "mini-factory/issue-agent"
    try:
        value = path.read_text().strip()
    except OSError:
        return None, path
    return (value if value in AGENTS else None), path


def role_agents():
    """Each gh-dash role's effective harness, resolved by the bundled mf-config."""
    helper = Path(__file__).resolve().parent / "mf_config.py"
    agents = {}
    for role, _ in ROLES:
        try:
            result = subprocess.run([sys.executable, "-I", "-B", str(helper), "agent", role],
                                    capture_output=True, text=True, timeout=15)
        except (OSError, subprocess.TimeoutExpired) as error:
            raise ValueError(str(error))
        lines = result.stdout.splitlines()
        if result.returncode or len(lines) != 2 or lines[0] not in AGENTS:
            raise ValueError((result.stderr or result.stdout).strip() or "no result")
        agents[role] = tuple(lines)
    return agents


def managed_launcher(path, target):
    expected = output([
        "bash", "-c", 'printf \'#!/usr/bin/env bash\n# mini-factory managed launcher v1\nexec %q "$@"\n\' "$1"',
        "mini-factory-doctor", str(target),
    ])
    try:
        return not path.is_symlink() and path.read_text() == expected
    except OSError:
        return False


def no_mistakes_duties(config):
    """[(duty, agent, provisioned harness or None)] read by the bundled nm-config; native doctor validates the file."""
    helper = Path(__file__).resolve().parent / "nm_config.py"
    try:
        result = subprocess.run([sys.executable, "-I", "-B", str(helper), "duties", str(config)],
                                capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ValueError(str(error))
    if result.returncode:
        raise ValueError((result.stderr or result.stdout).strip().replace("nm-config: ", "", 1) or "no result")
    duties = [line.split("\t") for line in result.stdout.splitlines()]
    if not all(len(fields) == 3 and (fields[2] in AGENTS or fields[2] == "-") for fields in duties):
        raise ValueError("unexpected nm-config duties output")
    return [(duty, agent, None if kind == "-" else kind) for duty, agent, kind in duties]


def acpx_executable(config):
    """The acpx No-Mistakes runs for ACP agents (global acpx_path, else acpx), read by the bundled nm-config."""
    if not config.exists():
        return "acpx"
    helper = Path(__file__).resolve().parent / "nm_config.py"
    try:
        result = subprocess.run([sys.executable, "-I", "-B", str(helper), "acpx-path", str(config)],
                                capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ValueError(str(error))
    if result.returncode or not result.stdout.strip():
        raise ValueError((result.stderr or result.stdout).strip().replace("nm-config: ", "", 1) or "no result")
    return result.stdout.rstrip("\n")


def daemon_path():
    """The PATH the No-Mistakes daemon resolves (login-shell PATH plus SERVICE_PATH), read by the bundled nm-config."""
    helper = Path(__file__).resolve().parent / "nm_config.py"
    # Covers the helper's 30-second login-shell probe (as No-Mistakes allows) plus its bounded 5-second cleanup.
    text = output([sys.executable, "-I", "-B", str(helper), "daemon-path"], timeout=45)
    return text.strip() if text and text.strip() else SERVICE_PATH


def node_version(text):
    match = re.match(r"v?(\d+)\.(\d+)", (text or "").strip())
    return tuple(map(int, match.groups())) if match else None


def config_link_problem(link, bundle):
    if not link.is_symlink():
        return "not a link to your clone's no-mistakes/config.yaml"
    target = Path(os.readlink(link))
    if not target.is_absolute() or target.parts[-2:] != ("no-mistakes", "config.yaml"):
        return "links to an unrelated file: " + str(target)
    if target.is_symlink() or not target.is_file():
        return "link target is missing; was the clone moved or deleted? " + str(target)
    if bundle.resolve() in target.resolve().parents:
        return "links into the installed runtime copy instead of your clone"
    clone = target.parent.parent
    if not all((clone / name).is_file() and not (clone / name).is_symlink()
               for name in ("bin/nm-config", "scripts/nm_config.py")):
        return "target is not in a mini-factory clone with nm-config: " + str(target)
    return None


def native_pipeline_status():
    text = output(["no-mistakes", "doctor"], NO_MISTAKES_ENVIRONMENT) or ""
    lines = text.splitlines()
    starts = [index for index, line in enumerate(lines) if "gate validation" in line]
    if not starts:
        return False, "no gate validation result"
    # A config load error continues on the following lines (one per rejected field).
    detail = [lines[starts[0]].strip()]
    for line in lines[starts[0] + 1:]:
        if not line.strip() or line.strip()[:1] in ("\u2713", "\u2717", "\u2013"):
            break
        detail.append(line.strip())
    ready = len(starts) == 1 and "\u2713" in detail[0] and "some checks failed" not in text
    return ready, " ".join(detail)


def flag_available(text, flag):
    # An exact flag, so --intent-file alone does not satisfy --intent.
    return re.search(re.escape(flag) + r"(?![\w-])", text) is not None


def integrity(bundle):
    workers = bundle / "scripts/integrations/gh-dash"
    required = [bundle / "Makefile", bundle / "README.md", bundle / "gh-dash/config.yml",
                bundle / "no-mistakes/config.yaml", bundle / "scripts/doctor.py", bundle / "scripts/mf_config.py",
                bundle / "scripts/nm_config.py"]
    executables = [bundle / "bin/ghd", bundle / "bin/mf-config", bundle / "bin/nm-config", bundle / "scripts/setup.sh",
                   bundle / "scripts/update.sh", bundle / "scripts/doctor.sh"]
    executables += [workers / name for name in (
        "gh-dash-codex-issue.sh", "gh-dash-codex-issue-dispatch.sh",
        "gh-dash-codex-pr-review.sh", "gh-dash-codex-pr-review-dispatch.sh")]
    for path in required + executables:
        if path.is_symlink() or not path.is_file():
            raise ValueError("missing regular bundle file: " + str(path))
    for path in executables:
        if not os.access(path, os.X_OK):
            raise ValueError("bundle entrypoint is not executable: " + str(path))
        if output(["bash", "-n", str(path)]) is None:
            raise ValueError("bundle entrypoint failed Bash syntax check: " + str(path))
    config = (bundle / "gh-dash/config.yml").read_text()
    if (re.findall(r"^\s+- key: (\S+)\s*$", config, re.M) != ["I", "i", "I"]
            or config.count("gh-dash-codex-pr-review.sh") != 1
            or config.count("gh-dash-codex-issue-dispatch.sh") != 2
            or any(token in config for token in (
                "--factory", "$HOME/dotfiles", "diffnav", "repoPaths:", "pager:",
                "universal:", "octo", "tuicr", "lazygit", "sandbox"))):
        raise ValueError("bundle config does not contain the isolated PR I and issue i/I routes")
    for script in ("scripts/doctor.py", "scripts/mf_config.py", "scripts/nm_config.py"):
        compile((bundle / script).read_bytes(), str(bundle / script), "exec")


def route_check(kinds):
    def document(argv, kind=None):
        raw = output(["herdr", *argv])
        try:
            value = json.loads(raw)
        except (TypeError, ValueError):
            raise ValueError("Herdr returned no valid JSON for " + " ".join(argv))
        if not isinstance(value, dict) or value.get("error") is not None:
            raise ValueError("Herdr route check failed: " + " ".join(argv))
        if kind is not None and (
            set(value) != {"id", "result"} or not isinstance(value.get("id"), str)
            or not value["id"] or not isinstance(value.get("result"), dict)
            or value["result"].get("type") != kind
        ):
            raise ValueError("Herdr response type mismatch: " + " ".join(argv))
        return value

    names = ("HERDR_SOCKET_PATH", "HERDR_WORKSPACE_ID", "HERDR_TAB_ID", "HERDR_PANE_ID")
    if not all(os.environ.get(name) for name in names):
        raise ValueError("incomplete inherited Herdr socket/workspace/tab/pane context")
    status = document(["status", "--json"])
    server = status.get("server", {})
    if not isinstance(server, dict) or server.get("running") is not True or server.get("compatible") is not True:
        raise ValueError("inherited Herdr server is not running or is incompatible")
    workspace, tab, pane = (os.environ[name] for name in names[1:])
    documents = (
        (["workspace", "get", workspace], "workspace_info", "workspace", {"workspace_id": workspace}),
        (["tab", "get", tab], "tab_info", "tab", {"tab_id": tab, "workspace_id": workspace}),
        (["pane", "get", pane], "pane_info", "pane",
         {"pane_id": pane, "tab_id": tab, "workspace_id": workspace}),
    )
    for argv, kind, field, identity in documents:
        actual = document(argv, kind).get("result", {}).get(field, {})
        if not isinstance(actual, dict) or any(actual.get(key) != value for key, value in identity.items()):
            raise ValueError("inherited Herdr " + field + " identity mismatch")
    manifests = document(["server", "agent-manifests", "--json"], "agent_manifest_status")
    entries = manifests.get("result", {}).get("manifests")
    if not isinstance(entries, list) or not all(
        isinstance(item, dict) and isinstance(item.get("agent"), str) and item["agent"]
        and (item.get("active_version") is None
             or isinstance(item["active_version"], str) and item["active_version"])
        for item in entries
    ):
        raise ValueError("invalid Herdr agent detection manifest response")
    for kind in kinds:
        matches = [entry for entry in entries if entry.get("agent") == kind]
        if len(matches) != 1 or not matches[0].get("active_version"):
            raise ValueError("Herdr server has no active " + AGENTS[kind][1] + " detection manifest")
    root = output(["git", "rev-parse", "--show-toplevel"])
    if not root:
        raise ValueError("enter the target Git repository in this Herdr pane before running ghd")
    if not output(["git", "symbolic-ref", "--quiet", "--short", "HEAD"]):
        raise ValueError("detached HEAD is not supported")
    if not output(["git", "rev-parse", "--verify", "HEAD^{commit}"]):
        raise ValueError("target repository has no committed snapshot")
    raw = output(["env", "-u", "GH_REPO", "gh", "repo", "view", "--json", "nameWithOwner,sshUrl"])
    try:
        repository = json.loads(raw)
        fetch_url = repository["sshUrl"]
        if not isinstance(repository.get("nameWithOwner"), str) or not repository["nameWithOwner"]:
            raise ValueError()
        if not isinstance(fetch_url, str) or not fetch_url.startswith(("git@github.com:", "ssh://git@github.com/")):
            raise ValueError()
    except (TypeError, ValueError, KeyError):
        raise ValueError("cannot resolve the target GitHub repository and PR fetch URL")
    # The canonical PR worker requests sshUrl. Git's configured insteadOf rules
    # may route it over HTTPS; inspect that effective URL before requiring SSH.
    effective_url = output(["git", "ls-remote", "--get-url", fetch_url])
    if not effective_url:
        raise ValueError("cannot inspect the PR Git transport")
    environment = os.environ.copy()
    environment["GIT_TERMINAL_PROMPT"] = "0"
    if effective_url.startswith(("git@", "ssh://")):
        if shutil.which("ssh") is None:
            raise ValueError("PR Git transport requires ssh; install OpenSSH or configure HTTPS rewriting as in README")
        if ("GIT_SSH_COMMAND" in environment or "GIT_SSH" in environment
                or output(["git", "config", "--get", "core.sshCommand"])):
            raise ValueError("custom SSH transport requires manual verification; doctor will not execute a custom command that could change host trust")
        # Freeze existing host trust during this diagnostic; native SSH can add
        # address/key records even after a strictly authenticated connection.
        environment["GIT_SSH_COMMAND"] = (
            "ssh -o BatchMode=yes -o StrictHostKeyChecking=yes"
            " -o UpdateHostKeys=no -o CheckHostIP=no"
        )
    if output(["git", "ls-remote", fetch_url, "HEAD"], environment) is None:
        raise ValueError("PR Git transport authentication/trust pending; follow README and verify git ls-remote yourself")
    print("OK: PR Git transport authenticated (read-only ls-remote)")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--integrity-only", action="store_true")
    modes.add_argument("--installation-only", action="store_true")
    args = parser.parse_args()
    bundle = args.bundle or Path(os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local/share")) / "mini-factory"
    failures = []

    def check(ok, success, failure):
        print(("OK: " + success) if ok else ("FAIL: " + failure))
        if not ok:
            failures.append(failure)
        return ok

    try:
        integrity(bundle)
        print("OK: installed bundle/config/entrypoint integrity: " + str(bundle))
    except (OSError, ValueError, SyntaxError) as error:
        check(False, "", "bundle integrity: " + str(error))
    if args.integrity_only:
        return int(bool(failures))

    issue_agent, setting = issue_agent_setting()
    try:
        roles, role_problem = role_agents(), None
    except ValueError as error:
        # Fall back to the shared choice and the Codex reviewer so the remaining checks still run.
        roles, role_problem = {}, str(error)
    # gh-dash roles need login, Herdr integration, and detection; No-Mistakes duties need login only.
    role_kinds = list(dict.fromkeys(kind for kind, _ in roles.values())) or list(dict.fromkeys(
        (issue_agent or "codex", "codex")))
    no_mistakes_config = Path(os.environ.get("NM_HOME") or str(Path.home() / ".no-mistakes")) / "config.yaml"
    duties, duty_problem = [], None
    if no_mistakes_config.exists():
        try:
            duties = no_mistakes_duties(no_mistakes_config)
        except ValueError as error:
            duty_problem = str(error)
    agents = list(dict.fromkeys([*role_kinds, *(kind for _, _, kind in duties if kind)]))
    # All three agent CLIs, Node.js/npm, and acpx are baseline, whichever roles use them. Only the daemon runs
    # acpx, so it is checked below from the daemon's PATH and acpx_path rather than from your shell's PATH.
    commands = [command for command, _, _ in AGENTS.values()] + ["no-mistakes", "node", "npm"]
    for name in ("bash", "git", "make", "gh", "jq", "python3", "herdr", "curl", "tar", "gum",
                 "env", "tr", "mkdir", "rmdir", "rm", "date", "chmod", "sleep", "nohup", "stat", *commands):
        check(shutil.which(name), name + " available", name + " missing; run make setup")
    for name in ("git", "gh", "jq", "herdr", "gum", *commands):
        text = output([name, "--version"], NO_MISTAKES_ENVIRONMENT)
        check(bool(text and text.strip()), name + " version responds", name + " version check failed")
    version = node_version(output(["node", "--version"]))
    check(version is not None and version >= (22, 13), "Node.js 22.13+ for acpx",
          "Node.js 22.13+ required by acpx (found " + ("v" + ".".join(map(str, version)) if version else "none")
          + "); upgrade it with the tool that installed it, then run make setup")
    try:
        acpx, acpx_problem = acpx_executable(no_mistakes_config), None
    except ValueError as error:
        acpx, acpx_problem = None, str(error)
    path = daemon_path()
    # acpx starts the node the daemon's PATH finds first; a suitable node in your shell does not stand in for it.
    # The PATH is resolved afresh, as a newly started daemon would; a running daemon keeps the PATH it started with.
    found = (output(["env", "PATH=" + path, "/bin/sh", "-c",
                     'command -v node && { node --version || echo "of unknown version"; }']) or "").splitlines()
    daemon_node = node_version(found[1]) if len(found) == 2 else None
    check(daemon_node is not None and daemon_node >= (22, 13), "Node.js 22.13+ runs from the No-Mistakes daemon's freshly resolved PATH",
          "Node.js 22.13+ required by acpx from the No-Mistakes daemon's PATH (" + path + "), which finds "
          + (found[0] + " " + found[1].strip() if len(found) == 2 else "no Node.js")
          + "; your shell's Node.js does not count. Put a 22.13+ first on that PATH, then run make setup for the "
          "exact action and restart the No-Mistakes daemon, which keeps the PATH it started with")
    service = acpx and output(["env", "PATH=" + path, "/bin/sh", "-c",
                               'command -v "$1" >/dev/null && "$1" --version', "sh", acpx])
    configured = "" if acpx in (None, "acpx") else " (acpx_path: " + acpx + ")"
    check(bool(service and service.strip()), "acpx runs from the No-Mistakes daemon's PATH" + configured,
          "cannot read acpx_path (" + str(acpx_problem) + "); write it as one plain value" if acpx_problem else
          "acpx" + configured + " or its Node.js does not run from the No-Mistakes daemon's PATH (" + path
          + "); run make setup for the exact action")
    # Stable releases provide the unattended interface; any newer release that keeps it is accepted.
    help_text = output(["no-mistakes", "axi", "run", "--help"], NO_MISTAKES_ENVIRONMENT) or ""
    check(all(flag_available(help_text, flag) for flag in ("--intent", "--yes")),
          "No-Mistakes unattended AXI run (--intent, --yes) available",
          "No-Mistakes axi run --intent/--yes capability missing; run make setup (offers the native stable no-mistakes update)")
    git_version = output(["git", "--version"]) or ""
    match = re.search(r"git version (\d+)\.(\d+)", git_version)
    check(match and tuple(map(int, match.groups())) >= (2, 29),
          "Git supports --no-write-fetch-head", "Git >= 2.29 required for PR fetch isolation")
    gh_version = output(["gh", "--version"]) or ""
    match = re.search(r"gh version (\d+)\.(\d+)", gh_version)
    check(match and tuple(map(int, match.groups())) >= (2, 47),
          "GitHub CLI meets supported version", "GitHub CLI >= 2.47 required; older Ubuntu versions have deprecated API failures")
    for argv, tokens, label in (
        (["codex", "login", "--help"], ("--device-auth",), "Codex device login"),
        (["herdr", "worktree", "create", "--help"], ("--base", "--cwd", "--branch"), "Herdr worktree create"),
        (["herdr", "worktree", "open", "--help"], ("--cwd", "--path"), "Herdr worktree open"),
        (["herdr", "agent", "start", "--help"], ("--kind", "--pane", "--timeout"), "Herdr agent start"),
        (["herdr", "agent", "prompt", "--help"], ("--wait", "--timeout"), "Herdr agent prompt"),
        (["herdr", "integration", "install", "--help"], tuple(role_kinds), "Herdr agent integration installer"),
        (["gh", "dash", "--help"], ("--config",), "gh-dash extension"),
    ):
        text = output(argv, NO_MISTAKES_ENVIRONMENT) or ""
        check(all(token in text for token in tokens), label + " available", label + " capability missing")
    installation_failed = bool(failures)
    print("Installation: " + ("incomplete" if installation_failed else "installed"))
    if args.installation_only:
        return int(bool(failures))

    check(authenticated(["gh", "auth", "status", "--hostname", "github.com"]),
          "GitHub authenticated", "GitHub authentication/setup pending: gh auth login --hostname github.com --web")
    check(issue_agent is not None, "shared issue agent: " + str(issue_agent),
          "issue agent setting pending: make setup ISSUE_AGENT=claude|codex|cursor (" + str(setting) + ")")
    sources = {"override": "mf-config selection", "shared": "shared issue agent", "default": "default"}
    if check(role_problem is None, "agent profiles readable (mf-config show for details)",
             "mf-config agent profiles unreadable (" + str(role_problem) + ")"):
        for role, label in ROLES:
            kind, source = roles[role]
            print("OK: " + label + ": " + AGENTS[kind][1] + " (" + sources.get(source, source) + ")")
    for duty, agent, kind in duties:
        if kind:
            print("OK: No-Mistakes " + duty + ": " + agent + " (" + AGENTS[kind][1] + " login checked; no Herdr "
                  "integration needed)")
        else:
            # Native doctor only proves the resolved agent is runnable, not logged in.
            print("NOTE: No-Mistakes " + duty + " " + agent + " login not checked by this doctor; "
                  "readiness relies on native no-mistakes doctor")
    # An unreadable file may select a logged-out agent, so its login cannot be reported complete.
    check(duty_problem is None, "No-Mistakes agents read",
          "No-Mistakes agent login pending: cannot read their agents (" + str(duty_problem) + "); write "
          "agent and review_agents in block form (as nm-config does) so their login can be checked")
    # Installed agents that no role or duty uses may stay logged out.
    for kind in agents:
        _, label, login = AGENTS[kind]
        check(agent_authenticated(kind), label + " authenticated",
              label + " authentication/setup pending: " + login)
    integration = output(["herdr", "integration", "status"]) or ""
    for kind in role_kinds:
        lines = [line for line in integration.splitlines() if line.startswith(kind + ":")]
        check(len(lines) == 1 and lines[0].startswith(kind + ": current "),
              "Herdr " + AGENTS[kind][1] + " integration current",
              "Herdr " + AGENTS[kind][1] + " integration setup pending: herdr integration install " + kind)
    problem = config_link_problem(no_mistakes_config, bundle)
    check(problem is None, "No-Mistakes config links to your clone: " + str(no_mistakes_config),
          "No-Mistakes config link pending (" + str(problem) + "); rerun make setup from your clone")
    ready, detail = native_pipeline_status()
    action = "run no-mistakes doctor"
    if not ready and "load config" in detail:
        # Customizations are the user's: explain the rejected fields, never strip them.
        action = ("the installed No-Mistakes cannot load " + str(no_mistakes_config) + "; setup never rewrites it. "
                  "Edit the reported fields in your clone's no-mistakes/config.yaml yourself (stable releases reject "
                  "prerelease-only settings such as ci.review_bot_comments), or use a release that supports them")
    check(ready, "No-Mistakes pipeline agent ready (native doctor: " + detail + ")",
          "No-Mistakes pipeline agent not ready (native doctor: " + detail + "); " + action)
    launcher = Path.home() / ".local/bin/ghd"
    active = shutil.which("ghd")
    try:
        managed = (managed_launcher(launcher, bundle / "bin/ghd")
                   and (bundle / ".mini-factory-install").read_text() == "mini-factory-v1\n")
    except OSError:
        managed = False
    check(active and Path(active).resolve() == launcher.resolve() and managed,
          "managed launcher resolves on PATH", 'launcher PATH/setup pending: export PATH="$HOME/.local/bin:$PATH"; run make setup if ghd is absent')
    # The mf-config and nm-config launchers are optional: setup never replaces another command of that name.
    for name in ("mf-config", "nm-config"):
        config_launcher = Path.home() / ".local/bin" / name
        active = shutil.which(name)
        if (active and Path(active).resolve() == config_launcher.resolve()
                and managed_launcher(config_launcher, bundle / "bin" / name)):
            print("OK: " + name + " launcher resolves on PATH")
        else:
            print("NOTE: optional " + name + " launcher is not on PATH (absent, or another " + name + " command "
                  "exists); run bin/" + name + " from your retained mini-factory clone")
    setup_pending = bool(failures) and not installation_failed
    print("Authentication/setup: " + ("pending" if setup_pending or installation_failed else "complete"))

    if any(os.environ.get(name) for name in (
        "HERDR_SOCKET_PATH", "HERDR_WORKSPACE_ID", "HERDR_TAB_ID", "HERDR_PANE_ID"
    )):
        try:
            route_check(role_kinds)
            print("OK: inherited Herdr route, compatible server, source repository and agent detection")
        except (OSError, ValueError) as error:
            check(False, "", "runtime context: " + str(error))
        if not failures:
            print("Runtime: ready to launch from this context")
        else:
            print("Runtime: context checks failed or setup pending")
    else:
        print("Runtime-context checks not performed: outside Herdr. In a target checkout run herdr, then run ghd in its pane.")
    print("Git transport authentication is separate from CLI login; see README before the first PR review fetch.")
    return int(bool(failures))


if __name__ == "__main__":
    raise SystemExit(main())
