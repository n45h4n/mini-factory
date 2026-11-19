#!/usr/bin/env python3
"""Read-only installation and inherited Herdr route checks. No dispatch."""

import argparse
import atexit
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tempfile


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
NO_MISTAKES_ENVIRONMENT = dict(os.environ, NO_MISTAKES_NO_UPDATE_CHECK="1", NO_MISTAKES_TELEMETRY="0",
                               MISE_OFFLINE="1")
ROLES = (("issue-prepare", "Issues i preparer"), ("issue-implement", "Issues I implementer"),
         ("pr-review", "PRs I reviewer"))
# The fixed PATH No-Mistakes gives its daemon service (shellenv.WellKnownBinDirsForHome). The daemon appends it to
# its login shell's PATH and keeps only it when that probe fails; your current shell's PATH is not assumed.
SERVICE_PATH = os.pathsep.join([str(Path.home() / name) for name in (".local/bin", "go/bin", ".cargo/bin", "bin")]
                               + ["/opt/homebrew/bin", "/opt/homebrew/sbin", "/usr/local/bin", "/usr/local/sbin",
                                  "/usr/bin", "/bin", "/usr/sbin", "/sbin"])
# Platform detection and Omarchy's lazy mise launchers come from the bundled helper that setup and update source.
PLATFORM_HELPER = Path(__file__).resolve().parent / "platform.sh"
BASH = shutil.which("bash") or "/bin/bash"
# The tools Omarchy can provide as lazy mise tools, which install themselves the first time they run.
LAZY_TOOLS = ("gh", "codex", "claude", "cursor-agent", "node", "npm")
# Every command doctor runs as a version or capability probe. Any of them may be a mise launcher (Omarchy's lazy
# tools, or your own mise's), so lazy mise tool discovery covers them all.
PROBED_TOOLS = ("git", "jq", "herdr", "gum", "no-mistakes") + LAZY_TOOLS


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


def forge_profiles(config, cli):
    """Whether native no-mistakes doctor runs cli (gh or glab) auth status, as it does for each forge profile with a
    gh_config_dir (GitHub) or glab_config_dir (GitLab), read by the bundled nm-config; assumed when the file cannot be
    read."""
    if not config.exists():
        return False
    helper = Path(__file__).resolve().parent / "nm_config.py"
    text = output([sys.executable, "-I", "-B", str(helper), cli + "-profiles", str(config)])
    return text is None or bool(text.strip())


def daemon_path():
    """The PATH the No-Mistakes daemon resolves (login-shell PATH plus SERVICE_PATH), read by the bundled nm-config."""
    helper = Path(__file__).resolve().parent / "nm_config.py"
    # Covers the helper's 30-second login-shell probe (as No-Mistakes allows) plus its bounded 5-second cleanup.
    text = output([sys.executable, "-I", "-B", str(helper), "daemon-path"], timeout=45)
    return text.strip() if text and text.strip() else SERVICE_PATH


def detect_platform():
    """(platform, None) for a platform setup supports (macos, ubuntu, arch, omarchy), otherwise (None, why not)."""
    try:
        result = subprocess.run([BASH, str(PLATFORM_HELPER), "detect"], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as error:
        return None, str(error)
    text = result.stdout.strip()
    if result.returncode == 0 and text in ("macos", "ubuntu", "arch", "omarchy"):
        return text, None
    return None, text or "cannot identify the platform"


def lazy_pending(names, path=None):
    """The named commands that PATH (or the given PATH) resolves to a mise launcher whose tool is not installed yet,
    or None when the helper fails or times out (an unknown result, not an empty one). The helper only reads the
    launchers; running one, even for --version, would install its tool first."""
    environment = None if path is None else dict(os.environ, PATH=path)
    text = output([BASH, str(PLATFORM_HELPER), "lazy", *names], environment)
    return None if text is None else set(text.splitlines())


def probe_path(path, names=PROBED_TOOLS):
    """(PATH, tools, unsafe) for doctor's probes of the named commands, or None when the helper fails or times out.
    Each named launcher script that runs mise use (and so writes your global mise configuration every run) is in tools,
    mapped to the installed tool it would run, which PATH (the given one behind a private directory, removed on exit)
    finds first for a command name; unsafe names such a launcher whose tool cannot be resolved, which no probe may run.
    Every other command, and the PATH your workflow uses, is unchanged."""
    text = output([BASH, str(PLATFORM_HELPER), "configuring", *names], dict(os.environ, PATH=path))
    if text is None:
        return None
    lines = text.splitlines()
    tools = dict(line.split("\t", 1) for line in lines if "\t" in line)
    unsafe = {line for line in lines if line and "\t" not in line}
    # A configured path (such as an absolute acpx_path) is run as its tool instead; only names go on PATH.
    links = {name: tool for name, tool in tools.items() if os.sep not in name}
    if links:
        directory = tempfile.mkdtemp(prefix="mini-factory-doctor-")
        atexit.register(shutil.rmtree, directory, True)
        for name, tool in links.items():
            os.symlink(tool, os.path.join(directory, name))
        path = directory + os.pathsep + path
    return path, tools, unsafe


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
                   bundle / "scripts/update.sh", bundle / "scripts/doctor.sh", bundle / "scripts/platform.sh"]
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
    return fetch_url


SSH_GUIDE = "https://docs.github.com/en/authentication/connecting-to-github-with-ssh"
# Choosing HTTPS is the user's deliberate, documented step; doctor only names it.
HTTPS_CHOICE = ("choose HTTPS deliberately: gh auth setup-git --hostname github.com (skip it when a working credential "
                "helper already exists; it sets GitHub CLI as the github.com credential helper and can replace a "
                "previously configured one), then in this target checkout git config url.\"https://github.com/\""
                ".insteadOf 'git@github.com:' (README: Git transport)")


def redacted(url):
    # An insteadOf rewrite may embed credentials in the URL; never print them.
    return re.sub(r"^(https?://)[^/]*@", r"\1***@", url, flags=re.I)


def transport_check(fetch_url, rerun):
    """Read-only check of the effective Git transport for the target's GitHub sshUrl from this checkout."""
    # The canonical PR worker requests sshUrl. Git's configured insteadOf rules
    # may route it over HTTPS; inspect that effective URL before requiring SSH.
    effective_url = (output(["git", "ls-remote", "--get-url", fetch_url]) or "").strip()
    if not effective_url:
        raise ValueError("not checked: cannot inspect the effective Git URL for " + fetch_url + "; rerun " + rerun)
    shown = redacted(effective_url)
    origin = "" if effective_url == fetch_url else "; Git insteadOf rewrote GitHub sshUrl " + fetch_url
    environment = os.environ.copy()
    environment["GIT_TERMINAL_PROMPT"] = "0"
    if effective_url.startswith(("git@", "ssh://")):
        if shutil.which("ssh") is None:
            raise ValueError("not checked: " + shown + " uses SSH, but ssh is missing; install OpenSSH, or "
                             + HTTPS_CHOICE + "; then rerun " + rerun)
        if ("GIT_SSH_COMMAND" in environment or "GIT_SSH" in environment
                or output(["git", "config", "--get", "core.sshCommand"])):
            raise ValueError("not checked: custom SSH transport (GIT_SSH_COMMAND, GIT_SSH, or core.sshCommand) "
                             "requires manual verification; doctor will not execute a custom command that could "
                             "change host trust. Verify git ls-remote " + fetch_url + " HEAD yourself in this "
                             "checkout, or " + HTTPS_CHOICE + "; then rerun " + rerun)
        # Freeze existing host trust during this diagnostic; native SSH can add
        # address/key records even after a strictly authenticated connection.
        environment["GIT_SSH_COMMAND"] = (
            "ssh -o BatchMode=yes -o StrictHostKeyChecking=yes"
            " -o UpdateHostKeys=no -o CheckHostIP=no"
        )
        transport = "SSH"
        remedy = ("to use SSH, add an SSH key to your GitHub account and verify GitHub's host key fingerprint "
                  "yourself, following " + SSH_GUIDE + " (doctor never accepts host keys); or " + HTTPS_CHOICE)
    elif effective_url.lower().startswith("https://"):
        transport = "HTTPS"
        remedy = ("give Git a credential helper with access to this repository, for example gh auth setup-git "
                  "--hostname github.com (it sets GitHub CLI as the github.com credential helper and can replace a "
                  "previously configured one), or remove the insteadOf rewrite to use SSH (README: Git transport)")
    else:
        transport = "a rewritten URL"
        remedy = "fix the Git insteadOf rewrite that produces this URL (README: Git transport)"
    if output(["git", "ls-remote", fetch_url, "HEAD"], environment) is None:
        raise ValueError("authentication/trust pending: read-only git ls-remote of " + shown + " failed over "
                         + transport + " without prompts" + origin + "; " + remedy + "; then rerun " + rerun)
    print("OK: Git transport authenticated over " + transport + ": " + shown + " (read-only ls-remote" + origin + ")")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--integrity-only", action="store_true")
    modes.add_argument("--installation-only", action="store_true")
    args = parser.parse_args()
    # Every probe runs offline for mise: its launchers would otherwise install a due update of their tool (Omarchy's
    # agents auto-update) or a lazy tool before running it. Offline, they run the installed version, routed as usual.
    os.environ["MISE_OFFLINE"] = "1"
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
    platform, platform_problem = detect_platform()
    check(platform is not None, "platform: " + str(platform), "unsupported platform: " + str(platform_problem))
    # Lazy mise tools (Omarchy's, or your own mise's on Arch) install themselves when run, so doctor runs none that is
    # not installed yet (nor on an unrecognized platform): each is setup pending, and the probes that would run it
    # are skipped.
    guarded = platform not in ("macos", "ubuntu")
    # Native no-mistakes doctor runs glab from PATH for a GitLab forge profile, so glab is then discovered and run as
    # doctor's own probed commands are.
    probed = PROBED_TOOLS + (("glab",) if guarded and forge_profiles(no_mistakes_config, "glab") else ())
    lazy, undiscovered = set(), False
    if guarded:
        lazy = lazy_pending(probed)
        probes = None if lazy is None else probe_path(os.environ.get("PATH", ""), probed)
        if probes is None:
            # Failed discovery is not an empty result: any of these may be such a launcher, so none of them runs.
            lazy, undiscovered = set(probed), True
            check(False, "", "lazy mise tool discovery failed (" + str(PLATFORM_HELPER) + " did not complete), so "
                  "doctor runs none of " + ", ".join(probed) + ", acpx, or native no-mistakes doctor, as any "
                  "of them could install a lazy mise tool or write your global mise configuration; run make setup")
        else:
            # Probes, including native no-mistakes doctor, run an installed tool directly rather than through a
            # launcher that writes mise configuration (as omarchy-mise-install does); such a launcher whose tool
            # cannot be resolved runs no more than one whose tool is not installed yet.
            os.environ["PATH"] = NO_MISTAKES_ENVIRONMENT["PATH"] = probes[0]
            lazy |= probes[2]
    # Why doctor runs none of the commands in lazy.
    not_run = " was not run (lazy mise tool discovery failed)" if undiscovered else " is not installed yet"
    # All three agent CLIs, Node.js/npm, and acpx are baseline, whichever roles use them. Only the daemon runs
    # acpx, so it is checked below from the daemon's PATH and acpx_path rather than from your shell's PATH.
    commands = [command for command, _, _ in AGENTS.values()] + ["no-mistakes", "node", "npm"]
    for name in ("bash", "git", "make", "gh", "jq", "python3", "herdr", "curl", "tar", "gum",
                 "env", "tr", "mkdir", "rmdir", "rm", "date", "chmod", "sleep", "nohup", "stat", *commands):
        check(shutil.which(name), name + " available", name + " missing; run make setup")
    for name in probed:
        if name not in lazy or undiscovered:
            continue
        if name in LAZY_TOOLS:
            check(False, "", name + " is a lazy mise tool that is not installed yet (running it would install "
                  "it first); setup pending: run make setup, which asks before mise install "
                  + ("node" if name == "npm" else name))
        else:
            # Setup installs no other tool through mise; its owner does.
            check(False, "", name + " is a mise launcher whose tool is not installed yet (running it would install "
                  "it first, or write your global mise configuration); install it with mise yourself (mise install "
                  + name + "), then run make doctor")
    for name in ("git", "gh", "jq", "herdr", "gum", *commands):
        if name in lazy:
            continue
        text = output([name, "--version"], NO_MISTAKES_ENVIRONMENT)
        check(bool(text and text.strip()), name + " version responds", name + " version check failed")
    if "node" not in lazy:
        version = node_version(output(["node", "--version"]))
        check(version is not None and version >= (22, 13), "Node.js 22.13+ for acpx",
              "Node.js 22.13+ required by acpx (found " + ("v" + ".".join(map(str, version)) if version else "none")
              + "); upgrade it with the tool that installed it, then run make setup")
    try:
        acpx, acpx_problem = acpx_executable(no_mistakes_config), None
    except ValueError as error:
        acpx, acpx_problem = None, str(error)
    path = daemon_path()
    # acpx runs node, so neither runs while the daemon's PATH (or this shell's) would install a lazy Node.js first,
    # nor while discovery for either PATH failed; nor does acpx while the acpx the daemon runs (acpx_path, else acpx
    # from its PATH) is itself such a launcher. Probes run the daemon's PATH as probe_path presents it, and acpx as
    # the installed tool it would run, so no launcher writes mise configuration.
    run_path, run_acpx, acpx_lazy = path, acpx, False
    node_lazy, node_undiscovered = bool(lazy & {"node", "npm"}), undiscovered
    if guarded and not node_lazy:
        names = ["node"] + ([acpx] if acpx else [])
        daemon_lazy = lazy_pending(names, path)
        probes = None if daemon_lazy is None else probe_path(path, names)
        if probes is None:
            run_path, node_lazy, node_undiscovered = None, True, True
        else:
            run_path, tools, unsafe = probes
            daemon_lazy |= unsafe
            node_lazy, acpx_lazy, run_acpx = "node" in daemon_lazy, acpx in daemon_lazy, tools.get(acpx, acpx)
    if node_lazy:
        check(False, "", "Node.js and acpx not checked from the No-Mistakes daemon's PATH (" + path + "): "
              + ("lazy mise tool discovery failed, so running node or acpx could install a lazy mise Node.js or "
                 "write your global mise configuration" if node_undiscovered else "a lazy mise Node.js is not "
                 "installed yet, and running node or acpx would install it") + "; run make setup")
    else:
        # acpx starts the node the daemon's PATH finds first; a suitable node in your shell does not stand in for it.
        # The PATH is resolved afresh, as a newly started daemon would; a running daemon keeps its starting PATH.
        found = (output(["env", "PATH=" + run_path, "/bin/sh", "-c",
                         'command -v node && { node --version || echo "of unknown version"; }']) or "").splitlines()
        daemon_node = node_version(found[1]) if len(found) == 2 else None
        check(daemon_node is not None and daemon_node >= (22, 13), "Node.js 22.13+ runs from the No-Mistakes daemon's freshly resolved PATH",
              "Node.js 22.13+ required by acpx from the No-Mistakes daemon's PATH (" + path + "), which finds "
              + (found[0] + " " + found[1].strip() if len(found) == 2 else "no Node.js")
              + "; your shell's Node.js does not count. Put a 22.13+ first on that PATH, then run make setup for the "
              "exact action and restart the No-Mistakes daemon, which keeps the PATH it started with")
        configured = "" if acpx in (None, "acpx") else " (acpx_path: " + acpx + ")"
        if acpx_lazy:
            check(False, "", "acpx" + configured + " not checked from the No-Mistakes daemon's PATH (" + path + "): "
                  "it is a mise launcher whose tool is not installed yet, and running it would install it first (or "
                  "write your global mise configuration); install it with mise yourself, then run make doctor")
        else:
            service = acpx and output(["env", "PATH=" + run_path, "/bin/sh", "-c",
                                       'command -v "$1" >/dev/null && "$1" --version', "sh", run_acpx])
            check(bool(service and service.strip()), "acpx runs from the No-Mistakes daemon's PATH" + configured,
                  "cannot read acpx_path (" + str(acpx_problem) + "); write it as one plain value" if acpx_problem
                  else "acpx" + configured + " or its Node.js does not run from the No-Mistakes daemon's PATH ("
                  + path + "); run make setup for the exact action")
    # Stable releases provide the unattended interface; any newer release that keeps it is accepted.
    if "no-mistakes" not in lazy:
        help_text = output(["no-mistakes", "axi", "run", "--help"], NO_MISTAKES_ENVIRONMENT) or ""
        check(all(flag_available(help_text, flag) for flag in ("--intent", "--base-branch", "--yes")),
              "No-Mistakes unattended AXI run (--intent, --base-branch, --yes) available",
              "No-Mistakes axi run --intent/--base-branch/--yes capability missing; run make setup (offers the native stable no-mistakes update)")
    if "git" not in lazy:
        git_version = output(["git", "--version"]) or ""
        match = re.search(r"git version (\d+)\.(\d+)", git_version)
        check(match and tuple(map(int, match.groups())) >= (2, 29),
              "Git supports --no-write-fetch-head", "Git >= 2.29 required for PR fetch isolation")
    if "gh" not in lazy:
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
        if argv[0] in lazy:
            continue
        text = output(argv, NO_MISTAKES_ENVIRONMENT) or ""
        check(all(token in text for token in tokens), label + " available", label + " capability missing")
    installation_failed = bool(failures)
    print("Installation: " + ("incomplete" if installation_failed else "installed"))
    if args.installation_only:
        return int(bool(failures))

    if "gh" in lazy:
        check(False, "", "GitHub authentication not checked: gh" + not_run + "; run make setup")
    else:
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
        command, label, login = AGENTS[kind]
        if command in lazy:
            check(False, "", label + " authentication not checked: " + command + not_run + "; run make setup")
            continue
        check(agent_authenticated(kind), label + " authenticated",
              label + " authentication/setup pending: " + login)
    # A herdr that is not run is already reported above.
    integration = "" if "herdr" in lazy else output(["herdr", "integration", "status"]) or ""
    for kind in ([] if "herdr" in lazy else role_kinds):
        lines = [line for line in integration.splitlines() if line.startswith(kind + ":")]
        check(len(lines) == 1 and lines[0].startswith(kind + ": current "),
              "Herdr " + AGENTS[kind][1] + " integration current",
              "Herdr " + AGENTS[kind][1] + " integration setup pending: herdr integration install " + kind)
    problem = config_link_problem(no_mistakes_config, bundle)
    check(problem is None, "No-Mistakes config links to your clone: " + str(no_mistakes_config),
          "No-Mistakes config link pending (" + str(problem) + "); rerun make setup from your clone")
    # Native doctor checks that the pipeline agent runs, which would install a lazy agent (or acpx's Node.js) first.
    # It also runs git --version, gh auth status for each GitHub forge profile (gh_config_dir), and glab auth status for
    # each GitLab forge profile (glab_config_dir) from PATH; glab is probed only for such a profile.
    delegated = lazy & {"git", "glab", "no-mistakes", *(command for command, _, _ in AGENTS.values())}
    if "gh" in lazy and forge_profiles(no_mistakes_config, "gh"):
        delegated.add("gh")
    if node_lazy or delegated:
        check(False, "", "No-Mistakes pipeline agent not checked: native no-mistakes doctor could start "
              + ("a launcher that lazy mise tool discovery could not check" if undiscovered or node_undiscovered
                 else "a lazy mise tool that is not installed yet") + "; run make setup")
    else:
        ready, detail = native_pipeline_status()
        action = "run no-mistakes doctor"
        if not ready and "load config" in detail:
            # Customizations are the user's: explain the rejected fields, never strip them.
            action = ("the installed No-Mistakes cannot load " + str(no_mistakes_config) + "; setup never rewrites "
                      "it. Edit the reported fields in your clone's no-mistakes/config.yaml yourself (stable releases "
                      "reject prerelease-only settings such as ci.review_bot_comments), or use a release that supports "
                      "them")
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

    # The installed doctor, run from the target checkout's Herdr pane, is what checks that target.
    rerun = shlex.quote(str(bundle / "scripts/doctor.sh"))
    if any(os.environ.get(name) for name in (
        "HERDR_SOCKET_PATH", "HERDR_WORKSPACE_ID", "HERDR_TAB_ID", "HERDR_PANE_ID"
    )):
        fetch_url = None
        try:
            if "gh" in lazy:
                raise ValueError("gh" + not_run + ", so the target GitHub repository cannot be resolved; run "
                                 "make setup")
            for name in ("herdr", "git"):
                if name in lazy:
                    raise ValueError(name + not_run + ", so the inherited Herdr route and target repository cannot "
                                     "be checked")
            fetch_url = route_check(role_kinds)
            print("OK: inherited Herdr route, compatible server, source repository and agent detection")
        except (OSError, ValueError) as error:
            check(False, "", "runtime context: " + str(error))
            print("NOTE: Git transport not checked; fix the runtime context above, then rerun " + rerun
                  + " from the target checkout in its Herdr pane")
        if fetch_url:
            try:
                transport_check(fetch_url, rerun)
            except (OSError, ValueError) as error:
                check(False, "", "Git transport " + str(error))
        if not failures:
            print("Runtime: ready to launch from this context")
        else:
            print("Runtime: context checks failed or setup pending")
    else:
        print("Runtime-context checks not performed: outside Herdr. In a target checkout run herdr, then in its "
              "pane run " + rerun + " before ghd.")
        print("NOTE: Git transport not checked: only that command, run from the target checkout's Herdr pane, checks "
              "the target's effective fetch URL and authentication (make doctor in the Mini-Factory clone checks "
              "only this installation).")
    return int(bool(failures))


if __name__ == "__main__":
    raise SystemExit(main())
