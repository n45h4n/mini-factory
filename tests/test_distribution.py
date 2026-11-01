"""Exercise the shipped bundle in disposable homes with inert external CLIs.

No test uses the developer's gh/Codex/Herdr configuration or a live agent.
The same suite is shipped with the distribution and runs through make test.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import pty
import re
import select
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import unittest


BUNDLE = Path(__file__).resolve().parents[1]
REAL_PATH = os.environ.get("PATH", os.defpath)
REAL_GIT = shutil.which("git")

# External mutations are inert and limited to explicitly tested onboarding.
# Even a regression in setup/doctor cannot publish or dispatch a live agent.
ISSUE_BODY = ("Body with \"quotes\", $(touch interpolated-marker), `touch backtick-marker`, and 'single' quotes.\n"
              "Unicode \u2014 stays data.\n")

MOCK = r'''#!PYTHON
import json, os, pathlib, shutil, subprocess, sys
ISSUE_BODY = ISSUE_BODY_LITERAL
name = pathlib.Path(sys.argv[0]).name
args = sys.argv[1:]
root = pathlib.Path(os.environ["MOCK_BIN"])
entry = {"tool": name, "args": args, "cwd": os.getcwd(),
         "env": {k: v for k, v in os.environ.items()
                 if k.startswith("GH_DASH_SOURCE_") or k in ("GH_REPO", "DOTFILES_DIR", "GIT_SSH_COMMAND")}}
with open(os.environ["MOCK_LOG"], "a") as stream:
    stream.write(json.dumps(entry) + "\n")
def fail(message="forbidden external action"):
    print(message, file=sys.stderr)
    sys.exit(91)
def envelope(kind, key, value):
    print(json.dumps({"id": "test", "result": {"type": kind, key: value}}))
if name == "uname":
    print(os.environ.get("MOCK_ARCH", "arm64") if args == ["-m"]
          else os.environ.get("MOCK_OS", "Darwin"))
elif name == "gh":
    if args == ["--version"]:
        print("gh version 2.88.1 (test)")
    elif args[:2] == ["repo", "view"]:
        if "GH_REPO" in os.environ:
            fail("inherited GH_REPO contaminated repository resolution")
        if any("sshUrl" in arg for arg in args):
            print(json.dumps({"nameWithOwner": "friend/target", "sshUrl": "git@github.com:friend/target.git",
                              "defaultBranchRef": {"name": "main"}}))
        else:
            print("friend/target")
    elif args[:2] == ["issue", "view"]:
        if "GH_REPO" in os.environ or args != ["issue", "view", "8", "--repo", "friend/target", "--json", "number,title,body"]:
            fail("unexpected issue lookup")
        print(json.dumps({"number": 8, "title": "Add 'quoted' $(title)", "body": ISSUE_BODY}))
    elif args[:2] == ["auth", "status"]:
        if os.environ.get("MOCK_GH_AUTH") == "pending" and not (root / "gh-authenticated").exists():
            fail("AUTH_SECRET_SENTINEL should never be displayed")
        print("github.com: logged in")
    elif args[:2] == ["auth", "login"] and "--help" in args:
        print("--web --git-protocol --hostname")
    elif args[:5] == ["auth", "login", "--hostname", "github.com", "--web"] and args[5:] in ([], ["--scopes", "project"]):
        print("Native mock device login: open github.com/login/device in another browser")
        (root / "gh-authenticated").write_text("yes")
    elif args[:2] == ["extension", "list"]:
        if os.environ.get("MOCK_EXTENSION") != "missing":
            print("gh dash\tdlvhdr/gh-dash\tv4.15.0")
    elif args[:2] == ["extension", "install"]:
        if args != ["extension", "install", "dlvhdr/gh-dash"]:
            fail()
        (root / "extension-installed").write_text("yes")
    elif args and args[0] == "dash":
        if "--version" in args:
            if os.environ.get("MOCK_EXTENSION") == "missing" and not (root / "extension-installed").exists():
                fail("gh-dash unavailable")
            print("gh-dash version 4.15.0")
        elif "--help" in args:
            print("--config --repo --debug --version")
        else:
            if os.environ.get("MOCK_BINDINGS"):
                config = pathlib.Path(args[args.index("--config") + 1]).read_text()
                commands = re.findall(r'command:\s*>[-+]?\s*\n\s*([^\n]+)', config)
                if len(commands) != 3:
                    fail("mock could not parse the bundled PR I and issue i/I commands")
                for command in commands:
                    command = command.replace("{{.RepoName}}", "friend/target")
                    command = command.replace("{{.PrNumber}}", "7").replace("{{.IssueNumber}}", "8")
                    completed = subprocess.run(["bash", "-c", command], check=False)
                    if completed.returncode:
                        sys.exit(completed.returncode)
    else:
        fail()
elif name == "codex":
    if args == ["--version"]:
        print("codex-cli 0.115.0")
    elif args == ["--help"]:
        print("Codex CLI: login logout --version")
    elif args[:2] == ["login", "status"]:
        if os.environ.get("MOCK_CODEX_AUTH") == "pending" and not (root / "codex-authenticated").exists():
            fail("AUTH_SECRET_SENTINEL should never be displayed")
        print("Logged in using ChatGPT")
    elif args[:1] == ["login"] and "--help" in args:
        print("--device-auth --with-api-key")
    elif args == ["login", "--device-auth"]:
        print("Native mock device login: open the Codex device page in another browser")
        (root / "codex-authenticated").write_text("yes")
    else:
        fail()
elif name == "claude":
    if args == ["--version"]:
        print("2.1.0 (Claude Code)")
    elif args == ["auth", "status"]:
        if os.environ.get("MOCK_CLAUDE_AUTH") == "pending" and not (root / "claude-authenticated").exists():
            fail("AUTH_SECRET_SENTINEL should never be displayed")
        print('{"loggedIn": true}')
    elif args == ["auth", "login"]:
        (root / "claude-authenticated").write_text("yes")
    else:
        fail()
elif name == "cursor-agent":
    if args == ["--version"]:
        print("2026.10.22-test")
    elif args == ["status", "--format", "json"]:
        # Native Cursor status succeeds while logged out; only the boolean distinguishes it.
        pending = os.environ.get("MOCK_CURSOR_AUTH") == "pending" and not (root / "cursor-authenticated").exists()
        print(json.dumps({"isAuthenticated": not pending, "email": "AUTH_SECRET_SENTINEL"}))
    elif args == ["login"]:
        (root / "cursor-authenticated").write_text("yes")
    else:
        fail()
elif name == "acpx":
    if args == ["--version"]:
        print("0.20.0")
    else:
        fail()
elif name == "node":
    if args == ["--version"]:
        print(os.environ.get("MOCK_NODE_VERSION", "v24.11.0"))
    else:
        fail()
elif name == "npm":
    # The default global prefix models a root-owned system Node in /usr.
    default_prefix = os.environ.get("MOCK_NPM_PREFIX", "/usr")
    if args == ["prefix", "-g"]:
        print(default_prefix)
    elif args == ["install", "-g", "acpx@latest"] or (
            len(args) == 5 and args[:3] == ["install", "-g", "--prefix"] and args[4] == "acpx@latest"):
        bin_directory = pathlib.Path(args[-2] if "--prefix" in args else default_prefix) / "bin"
        if not os.access(bin_directory.parent, os.W_OK):
            fail("npm ERR! code EACCES")
        bin_directory.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(root / "mock-cli", bin_directory / "acpx")
        (bin_directory / "acpx").chmod(0o755)
    else:
        fail()
elif name == "no-mistakes":
    # The default models the latest stable release (v1.84.0); a stable update installs it.
    version = "v1.84.0" if (root / "no-mistakes-updated").exists() else os.environ.get("MOCK_NM_VERSION", "v1.84.0")
    numeric = tuple(map(int, version[1:].split(".")))
    config = pathlib.Path(os.environ.get("NM_HOME", os.path.expanduser("~/.no-mistakes"))) / "config.yaml"
    # Like the native strict loader, releases before v1.105.0 reject the prerelease-only bot fields.
    rejected = [field for field in ("review_bot_comments", "release_after_checks_pass")
                if numeric < (1, 105, 0) and config.exists() and field in config.read_text()]
    if args == ["--version"]:
        print("no-mistakes version " + version + " (test) 2026-10-01T00:00:00Z")
    elif args == ["daemon", "restart"]:
        # Native startup writes a default config when missing.
        if rejected:
            fail("load config: field " + rejected[0] + " not found")
        if not config.exists() and not config.is_symlink():
            config.parent.mkdir(parents=True, exist_ok=True)
            config.write_text("agent: auto\n")
    elif args == ["axi", "run", "--help"]:
        if os.environ.get("NO_MISTAKES_TELEMETRY") != "0" or os.environ.get("NO_MISTAKES_NO_UPDATE_CHECK") != "1":
            fail("capability probes must not send telemetry or check for updates")
        if numeric < (1, 50, 0):
            # An older fixture without the stable interface; its --intent-file alone must not count.
            print("      --intent-file string   file containing the run intent\n      --wait duration")
        elif numeric < (1, 105, 0):
            print("      --intent string   what the user set out to accomplish\n"
                  "  -y, --yes   auto-resolve eligible gates\n      --wait duration")
        else:
            print("      --intent string\n      --intent-file string\n  -y, --yes\n      --closes int\n      --wait duration")
    elif args == ["doctor"]:
        if os.environ.get("NO_MISTAKES_TELEMETRY") != "0" or os.environ.get("NO_MISTAKES_NO_UPDATE_CHECK") != "1":
            fail("doctor diagnostics must not send telemetry or check for updates")
        if rejected:
            print("  \u2717 gate validation  unavailable: load config (parse global config: yaml: unmarshal errors:\n"
                  + "\n".join("  line 0: field " + field + " not found in type config.CIRaw" for field in rejected)
                  + ")\n\n  some checks failed")
        elif os.environ.get("MOCK_NM_DOCTOR") == "fail":
            print("  \u2717 gate validation  unavailable: agent cursor needs acpx\n\n  some checks failed")
        else:
            print("  \u2713 gate validation  codex is runnable")
    elif args == ["update"]:
        # The native updater refuses to restart the daemon while runs are active (without --force).
        if os.environ.get("MOCK_NM_ACTIVE_RUNS"):
            print("refusing to update while 1 pipeline run is active: 01TEST running agent/issue-8", file=sys.stderr)
            sys.exit(1)
        (root / "no-mistakes-updated").write_text("yes")
    else:
        fail()
elif name == "herdr":
    issue_mode = os.environ.get("MOCK_ISSUE_WORKFLOW") == "1"
    base = pathlib.Path(os.environ.get("MOCK_WORKTREE_BASE", str(root.parent)))
    issue_file = base / "issue-workflow.json"
    issue_state = json.loads(issue_file.read_text()) if issue_file.exists() else {}
    # Implementation and preparation are separate Herdr workspaces, agents, and worktrees.
    sessions = {
        "agent/issue-8": {"alias": "target-8", "ws": "issue-ws", "tab": "issue-tab", "pane": "issue-pane",
                          "directory": "issue worktree with spaces"},
        "agent/prepare-issue-8": {"alias": "target-prep-8", "ws": "prep-ws", "tab": "prep-tab", "pane": "prep-pane",
                                  "directory": "prepare worktree with spaces"},
    }
    def session(key, value):
        return next((branch for branch, item in sessions.items() if item[key] == value), None)
    def save():
        issue_file.write_text(json.dumps(issue_state))
    def issue_worktree(branch):
        return {"branch": branch, "path": issue_state[branch]["path"],
                "is_bare": False, "is_detached": False, "is_prunable": False,
                "is_linked_worktree": True, "open_workspace_id": sessions[branch]["ws"]}
    def issue_agent(branch):
        item, state = sessions[branch], issue_state[branch]
        return {"name": item["alias"], "agent": state["kind"], "workspace_id": item["ws"],
                "tab_id": item["tab"], "pane_id": os.environ.get("MOCK_AGENT_PANE", item["pane"]),
                "agent_status": os.environ.get("MOCK_AGENT_STATUS", state.get("agent_status", "working"))}
    started = [branch for branch in sessions if issue_state.get(branch, {}).get("agent_started")]
    if args == ["--version"] or args == ["version"]:
        print("herdr version 0.20.0")
    elif "--help" in args:
        print("integration install status list claude codex cursor --json --cwd --workspace --pane --kind --timeout --wait --base --branch --path server agent-manifests")
    elif args[:1] == ["integration"] and args[1:2] in (["status"], ["list"]):
        for kind in ("claude", "codex", "cursor"):
            pending = os.environ.get("MOCK_INTEGRATION") == "pending" and not (root / ("herdr-integrated-" + kind)).exists()
            print(kind + (": not installed (test fixture)" if pending else ": current (test fixture)"))
    elif args[:2] == ["integration", "install"] and args[2:] in (["claude"], ["codex"], ["cursor"]):
        if args[2] == "codex":
            directory = pathlib.Path(os.environ.get("CODEX_HOME", str(pathlib.Path.home() / ".codex")))
            directory.mkdir(parents=True, exist_ok=True)
            with (directory / "config.toml").open("a") as stream:
                stream.write("# Mock native Herdr integration\n")
            (directory / "herdr-agent-state.sh").write_text("# Native mock hook\n")
            (directory / "hooks.json").write_text("{}\n")
        (root / ("herdr-integrated-" + args[2])).write_text("yes")
    elif args[:1] == ["notification"]:
        pass
    elif args[:1] == ["status"]:
        print(json.dumps({"server": {"running": True,
            "compatible": os.environ.get("MOCK_SERVER") != "incompatible"}}))
    elif args[:2] == ["workspace", "get"]:
        envelope("workspace_info", "workspace", {"workspace_id": args[2] if issue_mode else "ws"})
    elif args[:2] == ["tab", "get"]:
        branch = issue_mode and session("tab", args[2])
        envelope("tab_info", "tab", {"tab_id": args[2] if issue_mode else "tab",
            "workspace_id": sessions[branch]["ws"] if branch else "ws"})
    elif args[:2] == ["pane", "get"]:
        branch = issue_mode and session("pane", args[2])
        envelope("pane_info", "pane", {"pane_id": "wrong" if os.environ.get("MOCK_ROUTE") == "wrong" else args[2] if issue_mode else "pane",
            "tab_id": sessions[branch]["tab"] if branch else "tab", "workspace_id": sessions[branch]["ws"] if branch else "ws",
            "foreground_cwd": issue_state[branch]["path"] if branch else os.getcwd()})
    elif args[:2] == ["server", "agent-manifests"]:
        envelope("agent_manifest_status", "manifests", [{"agent": kind,
            "active_version": None if os.environ.get("MOCK_MANIFEST") in ("missing", kind) else "1"}
            for kind in ("claude", "codex", "cursor")])
    elif issue_mode and args[:2] == ["worktree", "list"]:
        source = args[args.index("--cwd") + 1]
        print(json.dumps({"id": "test", "result": {"type": "worktree_list",
            "source": {"source_checkout_path": source, "source_workspace_id": "ws"},
            "worktrees": [issue_worktree(branch) for branch in sessions if "path" in issue_state.get(branch, {})]}}))
    elif issue_mode and args[:2] in (["worktree", "create"], ["worktree", "open"]):
        source = pathlib.Path(args[args.index("--cwd") + 1]).resolve()
        if not source.is_relative_to(root.parent):
            fail("worktree fixture escaped disposable test root")
        branch = args[args.index("--branch") + 1]
        if branch not in sessions:
            fail("unexpected issue branch")
        state = issue_state.setdefault(branch, {})
        if args[1] == "create":
            destination = base / sessions[branch]["directory"]
            subprocess.run([os.environ["REAL_GIT"], "-C", str(source), "worktree", "add",
                            str(destination), branch], check=True, capture_output=True)
            state["path"] = str(destination)
            save()
        elif "path" not in state:
            fail("cannot open absent issue worktree")
        item = sessions[branch]
        print(json.dumps({"id": "test", "result": {"type": "worktree_created" if args[1] == "create" else "worktree_opened",
            "workspace": {"workspace_id": item["ws"]},
            "tab": {"tab_id": item["tab"], "workspace_id": item["ws"]},
            "root_pane": {"pane_id": item["pane"], "tab_id": item["tab"], "workspace_id": item["ws"],
                          "foreground_cwd": state["path"]},
            "worktree": issue_worktree(branch)}}))
    elif issue_mode and args[:2] == ["agent", "list"]:
        envelope("agent_list", "agents", [issue_agent(branch) for branch in started])
    elif issue_mode and args[:2] == ["agent", "get"]:
        branch = session("alias", args[2])
        if branch not in started:
            print(json.dumps({"id": "test", "error": {"code": "agent_not_found"}}))
            sys.exit(1)
        envelope("agent_info", "agent", issue_agent(branch))
    elif issue_mode and args[:2] == ["agent", "start"]:
        branch = session("alias", args[2])
        if (branch is None or args[3:] != ["--kind", args[4], "--pane", sessions[branch]["pane"], "--timeout", "30000"]
                or args[4] not in ("claude", "codex", "cursor")):
            fail("unexpected issue agent launch")
        issue_state[branch].update(agent_started=True, agent_status="idle", kind=args[4])
        save()
        envelope("agent_started", "agent", issue_agent(branch))
    elif issue_mode and args[:2] in (["agent", "prompt"], ["agent", "focus"]):
        branch = session("pane", args[2])
        if branch not in started:
            fail("issue agent action escaped validated pane")
        if args[1] == "prompt":
            issue_state[branch]["agent_status"] = "working"
            save()
        envelope("agent_prompted" if args[1] == "prompt" else "agent_info", "agent", issue_agent(branch))
    else:
        fail()
elif name in ("brew", "sudo", "apt-get"):
    if name == "brew" and args == ["--version"]:
        print("Homebrew 4.6.0")
    elif name == "sudo" and args[:1] == ["mkdir"] and all(
            value in ("mkdir", "-p", "-m", "755", "/etc/apt/keyrings", "/etc/apt/sources.list.d")
            for value in args):
        pass
    elif "install" in args or "upgrade" in args or "update" in args:
        if os.environ.get("MOCK_INSTALL_FAIL"):
            fail("simulated interrupted package installation")
        provided = {"gh": ("gh",)}
        for command in (command for package in args for command in provided.get(package, ())):
            shutil.copyfile(root / "mock-cli", root / command)
            (root / command).chmod(0o755)
    else:
        fail()
elif name == "git":
    if "ls-remote" in args:
        if os.environ.get("MOCK_TRANSPORT") == "pending":
            fail("mock Git transport authentication failure")
        print(os.environ.get("MOCK_EFFECTIVE_URL", "git@github.com:friend/target.git")
              if "--get-url" in args else "0123456789abcdef0123456789abcdef01234567\tHEAD")
        sys.exit(0)
    if "fetch" in args and os.environ.get("MOCK_REMOTE"):
        # Preparation fetches GitHub's sshUrl; route it to a disposable local fixture.
        if os.environ.get("MOCK_FETCH") == "fail":
            fail("mock default-branch fetch failure")
        args = [os.environ["MOCK_REMOTE"] if arg == "git@github.com:friend/target.git" else arg for arg in args]
    elif any(arg in args for arg in ("worktree", "push", "fetch", "clone", "commit", "checkout", "reset")):
        fail("unexpected Git mutation")
    os.execv(os.environ["REAL_GIT"], [os.environ["REAL_GIT"], *args])
elif name == "nohup":
    # The existing dispatchers own asynchronous execution; retain their execution
    # route but make the backend reach only its missing-Herdr safety check.
    result = subprocess.run(args, check=False)
    sys.exit(result.returncode)
elif name == "curl":
    if "-o" not in args:
        fail("unexpected download")
    url = next((argument for argument in args if argument.startswith("https://")), "")
    destination = pathlib.Path(args[args.index("-o") + 1])
    installers = {
        "https://chatgpt.com/codex/install.sh": ("codex", "${CODEX_INSTALL_DIR:?}"),
        "https://herdr.dev/install.sh": ("herdr", "${HERDR_INSTALL_DIR:?}"),
        "https://claude.ai/install.sh": ("claude", "$HOME/.local/bin"),
        "https://cursor.com/install": ("cursor-agent", "$HOME/.local/bin"),
        "https://raw.githubusercontent.com/kunchenguid/no-mistakes/main/docs/install.sh":
            ("no-mistakes", "${NO_MISTAKES_LINK_DIR:?}"),
    }
    if url in installers:
        tool, location = installers[url]
        script = '#!/bin/sh\nset -eu\n'
        if os.environ.get("MOCK_INSTALL_FAIL"):
            script += 'echo "simulated interrupted native installation" >&2\nexit 81\n'
        else:
            script += 'destination="' + location + '"\n'
            if tool == "codex":
                script += '[ "$CODEX_NON_INTERACTIVE" = true ]\n'
                script += 'mkdir -p "$HOME/.codex"\n'
            if tool != "herdr":
                script += 'case ":$PATH:" in *":$destination:"*) ;; *) exit 82 ;; esac\n'
            script += 'mkdir -p "$destination"\n'
            for command in (tool, "agent") if tool == "cursor-agent" else (tool,):
                script += 'cp "$MOCK_BIN/mock-cli" "$destination/' + command + '"\n'
                script += 'chmod 755 "$destination/' + command + '"\n'
            if tool == "no-mistakes":
                # The native installer ends by restarting the daemon under set -e.
                script += '"$destination/no-mistakes" daemon restart >/dev/null\n'
        destination.write_text(script)
    elif url == "https://cli.github.com/packages/githubcli-archive-keyring.gpg":
        destination.write_bytes(b"MOCK official keyring\n")
    else:
        fail("unexpected upstream URL")
elif name == "dpkg":
    if args == ["--print-architecture"]:
        print("amd64")
    else:
        fail()
else:
    fail()
'''.replace("#!PYTHON", "#!" + sys.executable).replace("ISSUE_BODY_LITERAL", repr(ISSUE_BODY)).replace(
    "import json, os, pathlib, shutil, subprocess, sys",
    "import json, os, pathlib, re, shutil, subprocess, sys",
)


class DistributionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="mini-factory tests ")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.home = self.root / "home with spaces"
        self.home.mkdir()
        self.bundle = self.root / "relocated bundle with spaces"
        shutil.copytree(BUNDLE, self.bundle, ignore=shutil.ignore_patterns(".git", "__pycache__"))
        self.mock = self.root / "mock bin"
        self.mock.mkdir()
        self.log = self.root / "calls.jsonl"
        mock_script = self.mock / "mock-cli"
        mock_script.write_text(MOCK)
        mock_script.chmod(0o755)
        for name in ("gh", "codex", "claude", "cursor-agent", "acpx", "no-mistakes", "herdr", "uname",
                     "brew", "curl", "sudo", "apt-get", "git", "nohup", "ssh", "dpkg"):
            (self.mock / name).symlink_to(mock_script.name)
        # A controlled PATH makes genuinely missing dependencies reproducible.
        utilities = ("bash sh env make jq python3 tar mkdir cp mv rm chmod cat find readlink dirname "
                     "basename mktemp sed awk tr stat date sleep touch ln id ps cmp head cut sort uniq "
                     "wc xargs grep install tee gzip unzip which du rmdir")
        for name in utilities.split():
            executable = sys.executable if name == "python3" else shutil.which(name, path=REAL_PATH)
            if executable and not (self.mock / name).exists():
                (self.mock / name).symlink_to(executable)
        self.env = {"HOME": str(self.home), "XDG_DATA_HOME": str(self.home / "data with spaces"),
                    "XDG_STATE_HOME": str(self.home / "state"), "XDG_CONFIG_HOME": str(self.home / "config"),
                    "PATH": str(self.home / ".local/bin") + os.pathsep + str(self.mock), "MOCK_BIN": str(self.mock), "MOCK_LOG": str(self.log),
                    "REAL_GIT": REAL_GIT or "", "LANG": "C", "TERM": "dumb",
                    "PYTHONDONTWRITEBYTECODE": "1"}
        self.installed = Path(self.env["XDG_DATA_HOME"]) / "mini-factory"
        self.wrapper = self.home / ".local/bin/ghd"

    def run_script(self, script, *args, cwd=None, env=None):
        return subprocess.run([str(script), *map(str, args)], cwd=cwd or self.root,
                              env=dict(self.env, **(env or {})), stdin=subprocess.DEVNULL,
                              capture_output=True, text=True, timeout=30)

    def setup(self, **env):
        return self.run_script(self.bundle / "scripts/setup.sh", env=env)

    def interactive_setup(self, answer="n", **overrides):
        master, slave = pty.openpty()
        process = subprocess.Popen([str(self.bundle / "scripts/setup.sh")], cwd=self.root,
                                   env=dict(self.env, **overrides), stdin=slave,
                                   stdout=slave, stderr=slave, close_fds=True)
        os.close(slave)
        output = bytearray()
        deadline = time.monotonic() + 30
        try:
            # More than one prompt may be needed; every answer remains explicit.
            os.write(master, ((answer + "\n") * 24).encode())
            while time.monotonic() < deadline:
                ready, _, _ = select.select([master], [], [], 0.1)
                if ready:
                    try:
                        block = os.read(master, 65536)
                    except OSError:
                        break
                    if not block:
                        break
                    output.extend(block)
                if process.poll() is not None and not ready:
                    break
            if process.poll() is None:
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    self.fail("interactive setup did not finish; output: " + output.decode(errors="replace"))
            process.wait(timeout=5)
        finally:
            os.close(master)
            if process.poll() is None:
                process.kill()
                process.wait()
        return subprocess.CompletedProcess(process.args, process.returncode,
                                           output.decode(errors="replace"), "")

    def calls(self, tool=None):
        records = [json.loads(line) for line in self.log.read_text().splitlines()] if self.log.exists() else []
        return [record for record in records if tool is None or record["tool"] == tool]

    def assert_success(self, result):
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def install(self):
        self.assert_success(self.interactive_setup("y"))
        self.assertTrue(self.installed.is_dir())
        self.assertTrue(self.wrapper.is_file())
        self.env["PATH"] = str(self.wrapper.parent) + os.pathsep + str(self.mock)

    def source_repo(self, commit=True, base=None):
        repo = (base or self.root) / "target repo with spaces"
        repo.mkdir(parents=True)
        def git(*args):
            return subprocess.run([REAL_GIT, "-C", str(repo), *args], env=dict(self.env, PATH=REAL_PATH),
                                  check=True, capture_output=True, text=True).stdout.strip()
        git("init", "-b", "feature/friend")
        git("config", "user.name", "Distribution Test")
        git("config", "user.email", "test@example.invalid")
        git("remote", "add", "origin", "https://github.com/friend/target.git")
        if commit:
            (repo / "source.txt").write_text("committed content\n")
            git("add", "source.txt")
            git("commit", "-m", "Fixture")
        return repo, git

    def advance_default_branch(self, git, message):
        # The fixture repository doubles as the fetched remote; main differs from the captured branch.
        parent = git("rev-parse", "main" if git("branch", "--list", "main") else "HEAD")
        commit = git("commit-tree", parent + "^{tree}", "-p", parent, "-m", message)
        git("update-ref", "refs/heads/main", commit)
        return commit

    def issue_environment(self, repo, git, **overrides):
        return {"HERDR_SOCKET_PATH": str(self.home / "test.sock"), "HERDR_WORKSPACE_ID": "ws",
                "HERDR_TAB_ID": "tab", "HERDR_PANE_ID": "pane", "MOCK_ISSUE_WORKFLOW": "1",
                "MOCK_REMOTE": str(repo), "MOCK_WORKTREE_BASE": str(repo.parent),
                "GH_DASH_SOURCE_ROOT": str(repo), "GH_DASH_SOURCE_REPO": "friend/target",
                "GH_DASH_SOURCE_BRANCH": "feature/friend", "GH_DASH_SOURCE_SHA": git("rev-parse", "HEAD"),
                "GH_DASH_SOURCE_DIRTY": "0", **overrides}

    def herdr_calls(self, *prefix):
        return [call["args"] for call in self.calls("herdr") if call["args"][:len(prefix)] == list(prefix)]

    def notifications(self):
        return [args[args.index("--body") + 1] for args in self.herdr_calls("notification", "show")]

    def assert_no_actions(self, allow_onboarding=False):
        for record in self.calls():
            args, tool = record["args"], record["tool"]
            if "--help" in args:
                continue
            if tool == "gh":
                self.assertNotIn(args[:2], (["pr", "comment"], ["pr", "ready"], ["pr", "merge"], ["issue", "edit"]))
                if not allow_onboarding:
                    self.assertNotEqual(args[:2], ["auth", "login"])
            if tool == "herdr":
                self.assertNotIn(args[:2], (["worktree", "create"], ["agent", "prompt"], ["agent", "start"]))
                if not allow_onboarding:
                    self.assertNotEqual(args[:2], ["integration", "install"] if "--help" not in args else [])
            if tool == "codex":
                self.assertNotEqual(args[:1], ["exec"])
            if tool == "no-mistakes":
                # Setup and doctor never initialize repositories, drive runs, or manage the daemon.
                self.assertNotIn(args[:1], (["init"], ["axi"], ["rerun"]))
                if not allow_onboarding:
                    # Only the consented native installer restarts the daemon.
                    self.assertNotIn(args[:1], (["update"], ["daemon"]))
            if tool in ("claude", "cursor-agent") and not allow_onboarding:
                self.assertNotIn("login", args)
            if tool == "git":
                self.assertNotIn("worktree", args)

    def test_exact_config_and_runtime_permissions(self):
        config = (self.bundle / "gh-dash/config.yml").read_text()
        self.assertEqual(re.findall(r"^([A-Za-z][A-Za-z0-9_]*):", config, re.M), ["defaults", "keybindings"])
        self.assertEqual(re.findall(r"key:\s*(\S+)", config), ["I", "i", "I"])
        self.assertIn("gh-dash-codex-pr-review.sh", config)
        self.assertIn("gh-dash-codex-issue-dispatch.sh", config)
        for forbidden in ("--factory", "diffnav", "lazygit", "tuicr", "octo", "queue", "sandbox", "$HOME/dotfiles", "repoPaths"):
            self.assertNotIn(forbidden, config)
        for relative in ("bin/ghd", "scripts/setup.sh", "scripts/doctor.sh",
                         "scripts/integrations/gh-dash/gh-dash-codex-issue.sh",
                         "scripts/integrations/gh-dash/gh-dash-codex-issue-dispatch.sh",
                         "scripts/integrations/gh-dash/gh-dash-codex-pr-review.sh",
                         "scripts/integrations/gh-dash/gh-dash-codex-pr-review-dispatch.sh"):
            self.assertTrue(os.access(self.bundle / relative, os.X_OK), relative)

    def test_clean_install_and_idempotent_second_run(self):
        self.install()
        before = (self.installed / "bin/ghd").read_bytes()
        self.assert_success(self.setup())
        self.assertEqual(before, (self.installed / "bin/ghd").read_bytes())
        self.assert_no_actions()

    def test_clean_bundle_and_update_remove_factory_assets(self):
        self.install()
        self.assertFalse((self.bundle / "tools/pepper").exists())
        obsolete = ("tools/pepper/lib/factory.py", "SOURCE_REVISION",
                    "scripts/integrations/gh-dash/gh_dash_codex_issue_context.py")
        for relative in obsolete:
            self.assertFalse((self.bundle / relative).exists(), relative)
            self.assertFalse((self.installed / relative).exists(), relative)
            file = self.installed / relative
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_text("obsolete fixture\n")
        self.assert_success(self.setup())
        self.assertFalse((self.installed / "tools/pepper").exists())
        for relative in obsolete:
            self.assertFalse((self.installed / relative).exists(), relative)
        self.assert_no_actions()

    def test_runtime_survives_source_clone_removal(self):
        self.install()
        shutil.rmtree(self.bundle)
        repo, _ = self.source_repo()
        self.assert_success(self.run_script(self.wrapper, cwd=repo))
        dash = [c for c in self.calls("gh") if c["args"][:1] == ["dash"] and "--config" in c["args"]][-1]
        self.assertEqual(dash["env"]["DOTFILES_DIR"], str(self.installed))

    def test_preserves_existing_personal_configuration(self):
        settings = [self.home / ".zshrc", self.home / ".bashrc", self.home / ".gitconfig",
                    self.home / ".codex/config.toml", self.home / ".config/gh-dash/config.yml",
                    self.home / ".config/herdr/config.toml"]
        for file in settings:
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_text("# personal setting sentinel\n")
        self.install()
        for file in settings:
            self.assertEqual(file.read_text(), "# personal setting sentinel\n")
        self.assert_no_actions()

    def test_refuses_unrelated_runtime_directory(self):
        self.installed.mkdir(parents=True)
        sentinel = self.installed / "unrelated"
        sentinel.write_text("preserve me")
        result = self.setup()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(sentinel.read_text(), "preserve me")
        self.assertFalse(self.wrapper.exists())

    def test_refuses_unrelated_launcher(self):
        self.wrapper.parent.mkdir(parents=True)
        self.wrapper.write_text("#!/bin/sh\necho unrelated\n")
        self.wrapper.chmod(0o755)
        result = self.setup()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.wrapper.read_text(), "#!/bin/sh\necho unrelated\n")

    def test_refuses_unrelated_command_on_path_and_symlinked_runtime(self):
        command = self.mock / "ghd"
        command.write_text("#!/bin/sh\necho unrelated\n")
        command.chmod(0o755)
        self.assertNotEqual(self.setup().returncode, 0)
        self.assertEqual(command.read_text(), "#!/bin/sh\necho unrelated\n")
        command.unlink()
        unrelated = self.root / "unrelated installation"
        unrelated.mkdir()
        self.installed.parent.mkdir(parents=True)
        self.installed.symlink_to(unrelated, target_is_directory=True)
        self.assertNotEqual(self.setup().returncode, 0)
        self.assertTrue(self.installed.is_symlink())
        self.assertEqual(list(unrelated.iterdir()), [])

    def test_fresh_install_defaults_issue_agent_to_codex(self):
        self.install()
        setting = Path(self.env["XDG_CONFIG_HOME"]) / "mini-factory/issue-agent"
        self.assertEqual(setting.read_text(), "codex\n")
        self.assert_success(self.setup())
        self.assertEqual(setting.read_text(), "codex\n")

    def test_noninteractive_missing_dependency_never_installs(self):
        (self.mock / "gh").unlink()
        result = self.setup()
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.installed.exists())
        self.assertFalse(any("install" in c["args"] for c in self.calls("brew")))
        self.assert_no_actions()

    def test_declined_dependency_installation(self):
        (self.mock / "gh").unlink()
        result = self.interactive_setup("n")
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertFalse(any("install" in c["args"] for c in self.calls("brew")))
        self.assertFalse(self.installed.exists())

    def test_failed_install_then_successful_rerun(self):
        (self.mock / "gh").unlink()
        result = self.interactive_setup("y", MOCK_INSTALL_FAIL="1")
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertFalse(self.installed.exists())
        self.assertFalse(self.wrapper.exists())
        self.assert_success(self.interactive_setup("y"))
        self.assertTrue(self.installed.is_dir())

    def test_native_installers_require_consent_and_recover_after_failure(self):
        for name in ("codex", "herdr"):
            (self.mock / name).unlink()
        shell = self.home / ".bashrc"
        shell.write_text("# preserve shell configuration\n")
        self.assertNotEqual(self.setup().returncode, 0)
        self.assertFalse(self.calls("curl"))
        self.assertNotEqual(self.interactive_setup("n").returncode, 0)
        self.assertFalse(self.calls("curl"))
        self.assertNotEqual(self.interactive_setup("y", MOCK_INSTALL_FAIL="1").returncode, 0)
        self.assertFalse(self.installed.exists())
        self.assert_success(self.interactive_setup("y"))
        self.assertTrue((self.wrapper.parent / "codex").is_file())
        self.assertTrue((self.wrapper.parent / "herdr").is_file())
        self.assertEqual(shell.read_text(), "# preserve shell configuration\n")
        urls = [argument for call in self.calls("curl") for argument in call["args"] if argument.startswith("https://")]
        self.assertIn("https://chatgpt.com/codex/install.sh", urls)
        self.assertIn("https://herdr.dev/install.sh", urls)
        self.assertFalse(self.calls("npm"))
        self.assertFalse(self.calls("node"))
        self.assert_no_actions()

    def test_native_auth_and_integration_delegate_after_consent(self):
        directory = self.home / ".codex"
        directory.mkdir()
        config = directory / "config.toml"
        config.write_text('# Existing native setting\nmodel = "user-choice"\n')
        result = self.interactive_setup("y", MOCK_GH_AUTH="pending", MOCK_CODEX_AUTH="pending", MOCK_INTEGRATION="pending")
        self.assert_success(result)
        self.assertTrue(config.read_text().startswith('# Existing native setting\nmodel = "user-choice"\n'))
        self.assertTrue((directory / "herdr-agent-state.sh").is_file())
        self.assertIn("hooks.json", result.stdout)
        self.assertIn("config.toml", result.stdout)
        # The optional project scope is requested only because this run consented to it.
        self.assertIn(["auth", "login", "--hostname", "github.com", "--web", "--scopes", "project"],
                      [c["args"] for c in self.calls("gh")])
        self.assertIn(["login", "--device-auth"], [c["args"] for c in self.calls("codex")])
        self.assertIn(["integration", "install", "codex"], [c["args"] for c in self.calls("herdr")])
        self.assert_no_actions(allow_onboarding=True)

    def test_replacement_validation_preserves_working_install(self):
        self.install()
        before = (self.installed / "bin/ghd").read_bytes()
        launcher = self.bundle / "scripts/integrations/gh-dash/gh-dash-codex-issue.sh"
        launcher.write_text("#!/usr/bin/env bash\nif\n")
        result = self.setup()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(before, (self.installed / "bin/ghd").read_bytes())

    def test_mocked_ubuntu_setup(self):
        if not Path("/etc/os-release").exists() or not re.search(r'^ID=["\']?ubuntu', Path("/etc/os-release").read_text(), re.M):
            self.skipTest("Ubuntu detection reads the native os-release file")
        self.assert_success(self.interactive_setup("y", MOCK_OS="Linux", MOCK_ARCH="x86_64"))
        self.assert_no_actions()

    def test_mocked_ubuntu_official_gh_install_uses_only_inert_privileged_tools(self):
        if not Path("/etc/os-release").exists() or not re.search(r'^ID=["\']?ubuntu', Path("/etc/os-release").read_text(), re.M):
            self.skipTest("Ubuntu detection reads the native os-release file")
        (self.mock / "gh").unlink()
        self.assert_success(self.interactive_setup("y", MOCK_OS="Linux", MOCK_ARCH="x86_64"))
        self.assertTrue((self.mock / "gh").exists())
        self.assertTrue(any("https://cli.github.com/packages/githubcli-archive-keyring.gpg" in c["args"] for c in self.calls("curl")))
        actions = [c["args"] for c in self.calls("sudo")]
        self.assertIn(["apt-get", "install", "-y", "--no-install-recommends", "gh"], actions)
        self.assertTrue(any("/etc/apt/sources.list.d/github-cli.list" in args for args in actions))
        self.assert_no_actions()

    def test_missing_path_installs_but_reports_parent_shell_action(self):
        (self.home / ".codex").mkdir()
        result = self.setup(PATH=str(self.mock))
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(self.installed.is_dir())
        self.assertIn('export PATH="$HOME/.local/bin:$PATH"', result.stdout)
        self.assert_no_actions()

    def test_noninteractive_auth_and_integration_are_pending_without_actions(self):
        (self.home / ".codex").mkdir()
        result = self.setup(MOCK_GH_AUTH="pending", MOCK_CODEX_AUTH="pending", MOCK_INTEGRATION="pending")
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(self.installed.is_dir())
        self.assertIn("pending", result.stdout.lower())
        self.assertNotIn("AUTH_SECRET_SENTINEL", result.stdout + result.stderr)
        self.assert_no_actions()

    def test_extension_requires_consent_and_installs_only_requested_extension(self):
        (self.home / ".codex").mkdir()
        result = self.setup(MOCK_EXTENSION="missing")
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.calls("gh") and any(c["args"][:2] == ["extension", "install"] for c in self.calls("gh")))
        self.assert_success(self.interactive_setup("y", MOCK_EXTENSION="missing"))
        extensions = [c["args"] for c in self.calls("gh") if c["args"][:2] == ["extension", "install"]]
        self.assertEqual(extensions, [["extension", "install", "dlvhdr/gh-dash"]])

    def test_unsupported_platform_and_architecture(self):
        for overrides in ({"MOCK_OS": "FreeBSD"}, {"MOCK_ARCH": "sparc64"}):
            with self.subTest(**overrides):
                self.assertNotEqual(self.setup(**overrides).returncode, 0)
                self.assertFalse(self.installed.exists())

    def test_launcher_captures_full_physical_snapshot_and_isolates_inheritance(self):
        self.install()
        repo, git = self.source_repo()
        link = self.root / "symlink to target"
        link.symlink_to(repo, target_is_directory=True)
        self.assert_success(self.run_script(self.wrapper, "--debug", cwd=link,
            env={"DOTFILES_DIR": "/unrelated/dotfiles", "GH_REPO": "wrong/repository"}))
        dash = [c for c in self.calls("gh") if c["args"][:1] == ["dash"] and "--config" in c["args"]][-1]
        self.assertEqual(dash["env"]["DOTFILES_DIR"], str(self.installed))
        self.assertEqual({k: dash["env"][k] for k in ("GH_DASH_SOURCE_ROOT", "GH_DASH_SOURCE_REPO",
            "GH_DASH_SOURCE_BRANCH", "GH_DASH_SOURCE_SHA", "GH_DASH_SOURCE_DIRTY")}, {
            "GH_DASH_SOURCE_ROOT": str(repo), "GH_DASH_SOURCE_REPO": "friend/target",
            "GH_DASH_SOURCE_BRANCH": "feature/friend", "GH_DASH_SOURCE_SHA": git("rev-parse", "HEAD"),
            "GH_DASH_SOURCE_DIRTY": "0"})
        self.assertIn("--debug", dash["args"])
        self.assertEqual(dash["args"][dash["args"].index("--config") + 1], str(self.installed / "gh-dash/config.yml"))

    def test_dirty_warning_and_captured_commit(self):
        self.install()
        repo, git = self.source_repo()
        captured = git("rev-parse", "HEAD")
        (repo / "source.txt").write_text("uncommitted content\n")
        result = self.run_script(self.wrapper, cwd=repo)
        self.assert_success(result)
        self.assertIn("dirty", result.stderr)
        self.assertIn("uncommitted", result.stderr)
        dash = [c for c in self.calls("gh") if c["args"][:1] == ["dash"] and "--config" in c["args"]][-1]
        self.assertEqual(dash["env"]["GH_DASH_SOURCE_SHA"], captured)
        self.assertEqual(dash["env"]["GH_DASH_SOURCE_DIRTY"], "1")

    def test_launcher_rejects_no_repo_detached_and_missing_commit(self):
        self.install()
        result = self.run_script(self.wrapper)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Git repository", result.stderr)
        repo, git = self.source_repo()
        git("checkout", "--detach", "HEAD")
        result = self.run_script(self.wrapper, cwd=repo)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("detached", result.stderr)
        shutil.rmtree(repo)
        empty, _ = self.source_repo(commit=False)
        result = self.run_script(self.wrapper, cwd=empty)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("commit", result.stderr)

    def test_config_replacement_arguments_are_rejected(self):
        self.install()
        repo, _ = self.source_repo()
        for arguments in (("--config", "other.yml"), ("--config=other.yml",), ("-c", "other.yml"), ("-cother.yml",)):
            with self.subTest(arguments=arguments):
                self.assertNotEqual(self.run_script(self.wrapper, *arguments, cwd=repo).returncode, 0)

    def test_all_installed_binding_routes_stop_safely_without_herdr(self):
        self.install()
        shutil.rmtree(self.bundle)
        repo, _ = self.source_repo()
        self.assert_success(self.run_script(self.wrapper, cwd=repo, env={"MOCK_BINDINGS": "1",
            "DOTFILES_DIR": "/unavailable/dotfiles"}))
        deadline = time.monotonic() + 5
        logs = []
        while time.monotonic() < deadline:
            logs = list(Path(self.env["XDG_STATE_HOME"]).glob("gh-dash-codex-*/*.log"))
            if len(logs) == 3 and all("HERDR_SOCKET_PATH" in file.read_text() for file in logs):
                break
            time.sleep(0.02)
        self.assertEqual(sorted(file.name.rsplit("-", 2)[-1] for file in logs),
                         ["8.log", "prepare.log", "review.log"])
        for file in logs:
            self.assertIn("HERDR_SOCKET_PATH", file.read_text())
            self.assertNotIn("/unavailable/dotfiles", file.read_text())
        self.assert_no_actions()

    def test_installed_dispatchers_resolve_bundle_without_dotfiles_environment(self):
        self.install()
        shutil.rmtree(self.bundle)
        repo, _ = self.source_repo()
        directory = self.installed / "scripts/integrations/gh-dash"
        for name in ("gh-dash-codex-issue-dispatch.sh", "gh-dash-codex-pr-review-dispatch.sh"):
            self.assert_success(self.run_script(directory / name, "friend/target", "8", cwd=repo))
        deadline = time.monotonic() + 5
        logs = []
        while time.monotonic() < deadline:
            logs = list(Path(self.env["XDG_STATE_HOME"]).glob("gh-dash-codex-*/*.log"))
            if len(logs) == 2 and all("HERDR_SOCKET_PATH" in file.read_text() for file in logs):
                break
            time.sleep(0.02)
        self.assertEqual(len(logs), 2)
        for file in logs:
            self.assertIn("HERDR_SOCKET_PATH", file.read_text())
            self.assertNotIn(str(self.home / "dotfiles"), file.read_text())
        self.assert_no_actions()

    def test_issue_starts_at_captured_commit_and_reuses_idle_agent(self):
        self.install()
        shutil.rmtree(self.bundle)
        repo, git = self.source_repo()
        route = self.issue_environment(repo, git, PYTHONPATH="/unavailable/dotfiles")
        captured = route["GH_DASH_SOURCE_SHA"]
        (repo / "source.txt").write_text("newer committed source\n")
        git("commit", "-am", "Advance source after dashboard launch")
        (repo / "source.txt").write_text("uncommitted source stays here\n")
        launcher = self.installed / "scripts/integrations/gh-dash/gh-dash-codex-issue.sh"
        self.log.write_text("")
        result = self.run_script(launcher, "friend/target", "8", cwd=repo, env=route)
        self.assert_success(result)
        worktree = self.root / "issue worktree with spaces"
        self.assertEqual(git("rev-parse", "agent/issue-8"), captured)
        self.assertEqual((worktree / "source.txt").read_text(), "committed content\n")
        self.assertEqual((repo / "source.txt").read_text(), "uncommitted source stays here\n")
        self.assertEqual(self.herdr_calls("agent", "start"), [["agent", "start", "target-8", "--kind", "codex",
                                                                "--pane", "issue-pane", "--timeout", "30000"]])
        prompts = self.herdr_calls("agent", "prompt")
        self.assertEqual(len(prompts), 1)
        self.assertEqual(prompts[0][:3] + prompts[0][4:], ["agent", "prompt", "issue-pane",
            "--wait", "--until", "working", "--timeout", "30000"])
        prompt = prompts[0][3]
        self.assertTrue(prompt.startswith("Fetch issue friend/target#8 and use its body as the prompt."))
        # The captured base stays visible and is not presented as the preparation commit.
        self.assertIn("starts from feature/friend at " + captured, prompt)
        (worktree / "source.txt").write_text("existing issue edits\n")
        result = self.run_script(launcher, "friend/target", "8", cwd=repo,
                                 env=dict(route, MOCK_AGENT_STATUS="idle"))
        self.assert_success(result)
        self.assertEqual((worktree / "source.txt").read_text(), "existing issue edits\n")
        self.assertEqual(len([c for c in self.calls("herdr") if c["args"][:2] == ["worktree", "create"]]), 1)
        self.assertEqual(len([c for c in self.calls("herdr") if c["args"][:2] == ["worktree", "open"]]), 1)
        self.assertEqual(len([c for c in self.calls("herdr") if c["args"][:2] == ["agent", "start"]]), 1)
        self.assertEqual(len([c for c in self.calls("herdr") if c["args"][:2] == ["agent", "prompt"]]), 2)
        self.assertEqual([c["args"] for c in self.calls("herdr") if c["args"][:2] == ["agent", "focus"]],
                         [["agent", "focus", "issue-pane"]])
        self.assertFalse((Path(self.env["XDG_STATE_HOME"]) / "gh-dash-codex-issue/contexts").exists())

    def test_issue_busy_blocked_and_unknown_agents_do_not_resend(self):
        self.install()
        repo, git = self.source_repo()
        route = self.issue_environment(repo, git)
        launcher = self.installed / "scripts/integrations/gh-dash/gh-dash-codex-issue.sh"
        self.assert_success(self.run_script(launcher, "friend/target", "8", cwd=repo, env=route))
        for status in ("working", "blocked", "unexpected-status"):
            with self.subTest(status=status):
                self.log.write_text("")
                result = self.run_script(launcher, "friend/target", "8", cwd=repo,
                                         env=dict(route, MOCK_AGENT_STATUS=status))
                self.assert_success(result)
                calls = self.calls("herdr")
                self.assertFalse(any(c["args"][:2] in (["agent", "start"], ["agent", "prompt"], ["worktree", "create"])
                                     for c in calls))
                self.assertEqual([c["args"] for c in calls if c["args"][:2] == ["agent", "focus"]],
                                 [["agent", "focus", "issue-pane"]])

    def test_issue_factory_argument_is_rejected_before_side_effects(self):
        directory = self.bundle / "scripts/integrations/gh-dash"
        for name in ("gh-dash-codex-issue.sh", "gh-dash-codex-issue-dispatch.sh"):
            with self.subTest(script=name):
                result = self.run_script(directory / name, "friend/target", "8", "--factory")
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("usage:", result.stderr.lower())
                self.assertFalse(self.calls(), "unsupported Factory invocation called external tools")
                self.assertFalse(Path(self.env["XDG_STATE_HOME"]).exists())

    def test_issue_conflicting_agent_identity_is_retained_without_action(self):
        self.install()
        repo, git = self.source_repo()
        route = self.issue_environment(repo, git)
        launcher = self.installed / "scripts/integrations/gh-dash/gh-dash-codex-issue.sh"
        self.assert_success(self.run_script(launcher, "friend/target", "8", cwd=repo, env=route))
        self.log.write_text("")
        result = self.run_script(launcher, "friend/target", "8", cwd=repo,
                                 env=dict(route, MOCK_AGENT_PANE="unrelated-pane"))
        self.assert_success(result)
        self.assertIn("conflicting", result.stderr)
        calls = self.calls("herdr")
        self.assertFalse(any(c["args"][:2] in (["agent", "start"], ["agent", "prompt"], ["agent", "focus"], ["worktree", "create"])
                             for c in calls))

    def issue_helper(self, *args, **env):
        repo = Path(env.pop("cwd"))
        return self.run_script(self.bundle / "scripts/integrations/gh-dash/gh-dash-codex-issue.sh",
                               "friend/target", "8", *args, cwd=repo, env=env)

    def save_issue_agent(self, kind):
        setting = Path(self.env["XDG_CONFIG_HOME"]) / "mini-factory/issue-agent"
        setting.parent.mkdir(parents=True, exist_ok=True)
        setting.write_text(kind + "\n")
        return setting

    def test_selected_agent_prepares_and_implements_in_separate_sessions(self):
        for kind in ("claude", "codex", "cursor"):
            with self.subTest(kind=kind):
                self.save_issue_agent(kind)
                repo, git = self.source_repo(base=self.root / kind)
                main = self.advance_default_branch(git, "Current default branch")
                route = self.issue_environment(repo, git, cwd=repo)
                captured = route["GH_DASH_SOURCE_SHA"]
                self.log.write_text("")
                self.assert_success(self.issue_helper(**route))
                self.assert_success(self.issue_helper("prepare", **route))
                self.assertEqual(self.herdr_calls("agent", "start"), [
                    ["agent", "start", "target-8", "--kind", kind, "--pane", "issue-pane", "--timeout", "30000"],
                    ["agent", "start", "target-prep-8", "--kind", kind, "--pane", "prep-pane", "--timeout", "30000"]])
                prompts = self.herdr_calls("agent", "prompt")
                self.assertEqual([args[2] for args in prompts], ["issue-pane", "prep-pane"])
                implement, prepare = (args[3] for args in prompts)
                # Implementation keeps the captured base; preparation inspects freshly fetched main.
                self.assertEqual(git("rev-parse", "agent/issue-8"), captured)
                self.assertEqual(git("rev-parse", "agent/prepare-issue-8"), main)
                self.assertNotEqual(captured, main)
                self.assertIn('no-mistakes axi run --yes --intent "$(cat -- "$intent_file")"', implement)
                for unsupported in ("--intent-file", "--closes"):
                    self.assertNotIn(unsupported, implement)
                self.assertIn("starts from feature/friend at " + captured, implement)
                self.assertTrue(prepare.startswith("Prepare issue friend/target#8 for dispatch; do not implement it."))
                self.assertIn("main commit " + main, prepare)
                self.assertIn("ready to dispatch, needs a decision, or already satisfied", prepare)
                self.assertNotIn("no-mistakes", prepare)

    def test_preparation_refreshes_only_when_safe_and_never_uses_a_stale_snapshot(self):
        repo, git = self.source_repo()
        main = self.advance_default_branch(git, "main 1")
        route = self.issue_environment(repo, git, cwd=repo)
        result = self.issue_helper("prepare", **dict(route, MOCK_FETCH="fail"))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("no older snapshot was used", result.stderr)
        self.assertFalse(self.herdr_calls("worktree", "create") or self.herdr_calls("agent", "start")
                         or self.herdr_calls("agent", "prompt"))
        self.assert_success(self.issue_helper("prepare", **route))
        self.assertEqual(git("rev-parse", "agent/prepare-issue-8"), main)
        self.assertEqual(git("branch", "--list", "agent/issue-8"), "")
        worktree = repo.parent / "prepare worktree with spaces"

        newer = self.advance_default_branch(git, "main 2")
        self.log.write_text("")
        self.assert_success(self.issue_helper("prepare", **dict(route, MOCK_AGENT_STATUS="idle")))
        self.assertEqual(git("rev-parse", "agent/prepare-issue-8"), newer)
        self.assertFalse(self.herdr_calls("agent", "start"))
        prompts = self.herdr_calls("agent", "prompt")
        self.assertEqual(len(prompts), 1)
        self.assertIn("main commit " + newer, prompts[0][3])

        # Local changes block reuse even when the fetched default branch is unchanged.
        (worktree / "source.txt").write_text("local change\n")
        self.log.write_text("")
        self.assert_success(self.issue_helper("prepare", **dict(route, MOCK_AGENT_STATUS="idle")))
        self.assertEqual((worktree / "source.txt").read_text(), "local change\n")
        self.assertFalse(self.herdr_calls("agent", "prompt"))
        self.assertIn("herdr worktree remove", self.notifications()[-1])
        (worktree / "source.txt").write_text("committed content\n")

        self.advance_default_branch(git, "main 3")
        self.log.write_text("")
        self.assert_success(self.issue_helper("prepare", **dict(route, MOCK_AGENT_STATUS="working")))
        self.assertEqual(git("rev-parse", "agent/prepare-issue-8"), newer)
        self.assertFalse(self.herdr_calls("agent", "prompt"))

        (worktree / "notes.txt").write_text("keep me\n")
        self.log.write_text("")
        self.assert_success(self.issue_helper("prepare", **dict(route, MOCK_AGENT_STATUS="idle")))
        self.assertEqual(git("rev-parse", "agent/prepare-issue-8"), newer)
        self.assertEqual((worktree / "notes.txt").read_text(), "keep me\n")
        self.assertFalse(self.herdr_calls("agent", "prompt"))
        self.assertTrue(any("not refreshed" in body and "herdr worktree remove" in body
                            for body in self.notifications()))

    def test_implementation_handoff_passes_captured_intent_as_data(self):
        repo, git = self.source_repo()
        route = self.issue_environment(repo, git, cwd=repo)
        self.assert_success(self.issue_helper(**route))
        prompt = self.herdr_calls("agent", "prompt")[0][3]
        intent = Path(self.env["XDG_STATE_HOME"]) / "gh-dash-codex-issue/intents/repo-6-friend-6-target-issue-8.md"
        content = intent.read_text()
        self.assertTrue(content.startswith("Issue friend/target#8: Add 'quoted' $(title)\n\n"))
        self.assertIn(ISSUE_BODY, content)
        self.assertEqual(stat.S_IMODE(intent.stat().st_mode), 0o600)
        worktree = repo.parent / "issue worktree with spaces"
        self.assertNotIn(worktree.resolve(), intent.resolve().parents)
        self.assertEqual(subprocess.run([REAL_GIT, "-C", str(worktree), "status", "--porcelain"],
                                        capture_output=True, text=True, check=True).stdout, "")
        self.assertFalse(list(self.root.rglob("*-marker")), "issue prose was evaluated as shell source")
        # Executing the prompt's start command passes the full captured issue as one --intent argument.
        command = prompt.split("Start the run with exactly:\n", 1)[1].split("\nStable No-Mistakes", 1)[0]
        self.assertEqual(command.splitlines()[1], 'no-mistakes axi run --yes --intent "$(cat -- "$intent_file")"')
        capture = self.root / "argv capture"
        capture.mkdir()
        (capture / "no-mistakes").write_text("#!" + sys.executable + "\nimport json, sys\nprint(json.dumps(sys.argv[1:]))\n")
        (capture / "no-mistakes").chmod(0o755)
        scratch = self.root / "shell scratch"
        scratch.mkdir()
        for shell in ("bash", "sh"):
            with self.subTest(shell=shell):
                completed = subprocess.run([shell, "-c", command], cwd=scratch, capture_output=True, text=True,
                                           env={"PATH": str(capture) + os.pathsep + REAL_PATH}, check=True)
                invoked = json.loads(completed.stdout)
                # Command substitution drops only trailing newlines; the multiline title/body stay intact.
                self.assertEqual(invoked, ["axi", "run", "--yes", "--intent", content.rstrip("\n")])
                self.assertIn(ISSUE_BODY.rstrip("\n"), invoked[-1])
                self.assertEqual(list(scratch.iterdir()), [])
        self.assertFalse(list(self.root.rglob("*-marker")), "issue prose was executed by the start command")
        # Stable No-Mistakes has no closing flag; nothing invents closing metadata.
        for unsupported in ("--intent-file", "--closes", "Closes #", "Fixes #"):
            self.assertNotIn(unsupported, prompt)
        self.assertIn("closing issue #8 is not automated", prompt)
        for requirement in ("clean, committed worktree", "reattach to the same run", "keeping --yes",
                            "Never merge the PR", "does not prove checks-passed", "replace it with a summary"):
            self.assertIn(requirement, prompt)
        # Dispatch reports only a launch; the agent reports the actual No-Mistakes outcome.
        self.assertIn("No-Mistakes outcome pending", self.notifications()[-1])
        self.assertNotIn("passed", self.notifications()[-1])

    def test_implementation_handoff_checks_target_ci_and_stops_on_an_empty_check_list(self):
        repo, git = self.source_repo()
        route = self.issue_environment(repo, git, cwd=repo)
        self.assert_success(self.issue_helper(**route))
        prompt = self.herdr_calls("agent", "prompt")[0][3]
        # The target's real PR-check expectations are checked before the run starts.
        self.assertLess(prompt.index("real PR-check expectations"), prompt.index("Start the run with exactly:"))
        for requirement in ("PR-triggered workflows on its default branch", "external CI that reports checks",
                            "no_ci: true in its trusted default-branch .no-mistakes.yaml",
                            "A missing .github/workflows directory alone does not prove there is no CI",
                            "Do not create or change this repository's CI workflows or .no-mistakes.yaml",
                            "owner must add PR-triggered CI and get it onto the default branch",
                            "deliberately declare no_ci: true there"):
            self.assertIn(requirement, prompt)
        # An established empty check list ends reattachment with the run preserved and the blocker reported.
        stop = prompt.index("Do not reattach forever to an empty check list.")
        self.assertLess(prompt.index("reattach to the same run"), stop)
        for requirement in ("gh pr checks reports no checks", "stop reattaching, keep the run and PR in place",
                            "report the exact native CI status and the owner's corrective action",
                            "Never bypass CI, mark checks passed, or set no_ci yourself"):
            self.assertIn(requirement, prompt[stop:])
        self.assertNotIn("abort", prompt[stop:].split("\n", 1)[0])
        # The dispatcher itself never inspects, creates, or edits the target's CI configuration.
        worktree = repo.parent / "issue worktree with spaces"
        for checkout in (repo, worktree):
            self.assertFalse((checkout / ".github").exists())
            self.assertFalse((checkout / ".no-mistakes.yaml").exists())
        self.assertEqual(subprocess.run([REAL_GIT, "-C", str(worktree), "status", "--porcelain"],
                                        capture_output=True, text=True, check=True).stdout, "")
        self.assertFalse([c for c in self.calls("gh") if c["args"][:2] in (["pr", "checks"], ["workflow", "run"])])

    def test_setting_change_keeps_retained_agent_without_duplicate_prompts(self):
        repo, git = self.source_repo()
        route = self.issue_environment(repo, git, cwd=repo)
        self.assert_success(self.issue_helper(**route))
        self.save_issue_agent("claude")
        for status in ("working", "blocked", "idle"):
            with self.subTest(status=status):
                self.log.write_text("")
                self.assert_success(self.issue_helper(**dict(route, MOCK_AGENT_STATUS=status)))
                self.assertFalse(self.herdr_calls("agent", "start"))
                self.assertEqual(len(self.herdr_calls("agent", "prompt")), 1 if status == "idle" else 0)
                self.assertEqual(self.herdr_calls("agent", "focus"), [["agent", "focus", "issue-pane"]])
                self.assertIn("Kept the existing Codex agent", self.notifications()[-1])

    def test_retained_agent_detection_is_checked_instead_of_the_new_setting(self):
        repo, git = self.source_repo()
        route = self.issue_environment(repo, git, cwd=repo)
        # A new launch still requires detection for the selected kind before creating a worktree.
        self.save_issue_agent("claude")
        result = self.issue_helper(**dict(route, MOCK_MANIFEST="claude"))
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse(self.herdr_calls("worktree", "create"))
        self.save_issue_agent("codex")
        self.assert_success(self.issue_helper(**route))
        self.save_issue_agent("claude")
        for status in ("working", "idle"):
            with self.subTest(status=status):
                # The retained Codex agent stays usable without a Claude detection manifest.
                self.log.write_text("")
                self.assert_success(self.issue_helper(**dict(route, MOCK_AGENT_STATUS=status, MOCK_MANIFEST="claude")))
                self.assertEqual(self.herdr_calls("agent", "focus"), [["agent", "focus", "issue-pane"]])
                self.assertEqual(len(self.herdr_calls("agent", "prompt")), 1 if status == "idle" else 0)
                # Without detection for the retained Codex agent, nothing is focused or prompted.
                self.log.write_text("")
                result = self.issue_helper(**dict(route, MOCK_AGENT_STATUS=status, MOCK_MANIFEST="codex"))
                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertFalse(self.herdr_calls("agent", "focus"))
                self.assertFalse(self.herdr_calls("agent", "prompt"))
                self.assertFalse(self.herdr_calls("agent", "start"))

    def test_relinking_after_codex_setup_keeps_the_pipeline_agent(self):
        source = self.bundle / "no-mistakes/config.yaml"
        link = self.home / ".no-mistakes/config.yaml"
        self.assert_success(self.interactive_setup("y", ISSUE_AGENT="codex"))
        self.env["PATH"] = str(self.wrapper.parent) + os.pathsep + str(self.mock)
        self.assertTrue(source.read_text().startswith("agent: codex "))
        edited = source.read_text().replace("review: 3", "review: 1")
        source.write_text(edited)
        # A missing link (as after moving the clone) is relinked without re-initializing the agent.
        link.unlink()
        self.assert_success(self.interactive_setup("y", ISSUE_AGENT="claude"))
        self.assertEqual(os.readlink(link), str(source))
        self.assertEqual(source.read_text(), edited)

    def test_no_mistakes_config_link_initializes_once_and_preserves_edits(self):
        source = self.bundle / "no-mistakes/config.yaml"
        link = self.home / ".no-mistakes/config.yaml"
        setting = Path(self.env["XDG_CONFIG_HOME"]) / "mini-factory/issue-agent"
        self.assert_success(self.interactive_setup("y", ISSUE_AGENT="claude"))
        self.env["PATH"] = str(self.wrapper.parent) + os.pathsep + str(self.mock)
        self.assertTrue(link.is_symlink())
        self.assertEqual(os.readlink(link), str(source))
        self.assertTrue(source.read_text().startswith("agent: claude "))
        self.assertEqual(setting.read_text(), "claude\n")
        edited = source.read_text().replace("review: 3", "review: 1") + "# personal note\n"
        source.write_text(edited)
        self.assert_success(self.setup(ISSUE_AGENT="cursor"))
        self.assert_success(self.setup())
        self.assertEqual(source.read_text(), edited)
        self.assertEqual(os.readlink(link), str(source))
        self.assertEqual(setting.read_text(), "cursor\n")
        self.assertFalse(link.with_name("config.yaml.mini-factory-backup").exists())
        self.assert_no_actions()

    def test_existing_no_mistakes_config_is_backed_up_never_followed_or_overwritten(self):
        directory = self.home / ".no-mistakes"
        directory.mkdir()
        personal = self.root / "personal no-mistakes.yaml"
        personal.write_text("agent: codex\nlog_level: debug\n")
        link = directory / "config.yaml"
        link.symlink_to(personal)
        backup = directory / "config.yaml.mini-factory-backup"
        self.assert_success(self.interactive_setup("y"))
        self.assertEqual(os.readlink(backup), str(personal))
        self.assertEqual(personal.read_text(), "agent: codex\nlog_level: debug\n")
        self.assertEqual(os.readlink(link), str(self.bundle / "no-mistakes/config.yaml"))
        link.unlink()
        link.write_text("agent: codex\n# second unrelated file\n")
        result = self.interactive_setup("y")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("already exists", result.stdout)
        self.assertEqual(link.read_text(), "agent: codex\n# second unrelated file\n")
        self.assertEqual(os.readlink(backup), str(personal))
        self.assertEqual(personal.read_text(), "agent: codex\nlog_level: debug\n")

    def test_selected_agent_and_no_mistakes_install_and_login_natively(self):
        for name in ("cursor-agent", "no-mistakes"):
            (self.mock / name).unlink()
        result = self.setup(ISSUE_AGENT="cursor")
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.calls("curl"))
        result = self.interactive_setup("y", ISSUE_AGENT="cursor", MOCK_CURSOR_AUTH="pending",
                                        MOCK_INTEGRATION="pending")
        self.assert_success(result)
        self.assertNotIn("AUTH_SECRET_SENTINEL", result.stdout)
        for name in ("cursor-agent", "agent", "no-mistakes"):
            self.assertTrue((self.wrapper.parent / name).is_file(), name)
        urls = [argument for call in self.calls("curl") for argument in call["args"] if argument.startswith("https://")]
        self.assertIn("https://cursor.com/install", urls)
        self.assertIn("https://raw.githubusercontent.com/kunchenguid/no-mistakes/main/docs/install.sh", urls)
        self.assertIn(["login"], [c["args"] for c in self.calls("cursor-agent")])
        installs = [args for args in self.herdr_calls("integration", "install") if "--help" not in args]
        self.assertEqual(installs, [["integration", "install", "codex"], ["integration", "install", "cursor"]])
        self.assertFalse(self.calls("npm"))
        self.assert_no_actions(allow_onboarding=True)

    def no_mistakes_updates(self):
        return [c["args"] for c in self.calls("no-mistakes") if c["args"][:1] == ["update"]]

    def test_no_mistakes_without_stable_interface_requires_consented_native_stable_update(self):
        result = self.setup(MOCK_NM_VERSION="v1.40.0")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("axi run --intent and --yes", result.stdout + result.stderr)
        self.assertNotEqual(self.interactive_setup("n", MOCK_NM_VERSION="v1.40.0").returncode, 0)
        self.assertFalse(self.no_mistakes_updates())
        self.assertFalse(self.installed.exists())
        doctor = self.run_script(self.bundle / "scripts/doctor.sh", env={"MOCK_NM_VERSION": "v1.40.0"})
        self.assertIn("FAIL: No-Mistakes axi run --intent/--yes capability missing", doctor.stdout)
        self.assertFalse(self.no_mistakes_updates(), "doctor must stay read-only")
        result = self.interactive_setup("y", MOCK_NM_VERSION="v1.40.0")
        self.assert_success(result)
        self.assertIn("no-mistakes update", result.stdout)
        # The stable channel only: never a prerelease or a forced restart.
        self.assertEqual(self.no_mistakes_updates(), [["update"]])
        self.assertIn("OK: No-Mistakes unattended AXI run (--intent, --yes) available", result.stdout)

    def test_stable_update_refusal_for_active_runs_is_reported_without_forcing(self):
        link = self.home / ".no-mistakes/config.yaml"
        result = self.interactive_setup("y", MOCK_NM_VERSION="v1.40.0", MOCK_NM_ACTIVE_RUNS="1")
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn("refusing to update while 1 pipeline run is active", result.stdout)
        self.assertIn("wait for active runs to finish", result.stdout)
        self.assertEqual(self.no_mistakes_updates(), [["update"]])
        self.assertFalse(link.exists() or link.is_symlink())
        self.assertFalse(self.installed.exists())

    def test_newer_prerelease_no_mistakes_is_reused_without_update(self):
        self.assert_success(self.interactive_setup("y", MOCK_NM_VERSION="v1.107.0"))
        self.env["PATH"] = str(self.wrapper.parent) + os.pathsep + str(self.mock)
        result = self.run_script(self.installed / "scripts/doctor.sh", env={"MOCK_NM_VERSION": "v1.107.0"})
        self.assert_success(result)
        self.assertIn("OK: No-Mistakes unattended AXI run (--intent, --yes) available", result.stdout)
        self.assertFalse(self.no_mistakes_updates())
        self.assert_no_actions(allow_onboarding=True)

    def test_fresh_stable_no_mistakes_install_links_the_stable_default_config(self):
        (self.mock / "no-mistakes").unlink()
        source = self.bundle / "no-mistakes/config.yaml"
        link = self.home / ".no-mistakes/config.yaml"
        # The tracked default contains only settings the stable global config documents.
        self.assertEqual(source.read_text(), "agent: codex # Initialize to the chosen pipeline agent during first setup.\n"
                                             "auto_fix:\n  review: 3\n  ci: 3\n")
        result = self.interactive_setup("y")
        self.assert_success(result)
        commands = [c["args"] for c in self.calls("no-mistakes")]
        self.assertIn(["daemon", "restart"], commands)
        self.assertFalse(self.no_mistakes_updates())
        self.assertEqual(os.readlink(link), str(source))
        self.assertEqual(source.read_text(), "agent: codex # Initialized from the issue agent during first setup.\n"
                                             "auto_fix:\n  review: 3\n  ci: 3\n")
        # The stable loader accepts the linked default; native doctor reports it ready.
        self.assertIn("OK: No-Mistakes pipeline agent ready", result.stdout)
        # The native default written by the first daemon start is preserved, not overwritten.
        self.assertEqual(link.with_name("config.yaml.mini-factory-backup").read_text(), "agent: auto\n")
        self.assert_no_actions(allow_onboarding=True)

    def test_customized_prerelease_config_is_explained_and_never_rewritten(self):
        source = self.bundle / "no-mistakes/config.yaml"
        customized = ("agent: codex # my choice\nauto_fix:\n  review: 1\n  ci: 3\nci:\n"
                      "  review_bot_comments: always\n  release_after_checks_pass: true\nlog_level: debug\n")
        source.write_text(customized)
        link = self.home / ".no-mistakes/config.yaml"
        link.parent.mkdir()
        link.symlink_to(source)
        unrelated = link.with_name("notes.txt")
        unrelated.write_text("keep me\n")
        result = self.setup()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(source.read_text(), customized)
        self.assertEqual(os.readlink(link), str(source))
        self.assertEqual(unrelated.read_text(), "keep me\n")
        self.assertFalse(link.with_name("config.yaml.mini-factory-backup").exists())
        for explanation in ("field review_bot_comments not found", "field release_after_checks_pass not found",
                            "setup never rewrites it", "Edit the reported fields in your clone's no-mistakes/config.yaml"):
            self.assertIn(explanation, result.stdout)
        self.assertFalse(self.no_mistakes_updates())
        # A deliberately installed prerelease that supports the fields keeps the customization valid.
        self.assert_success(self.setup(MOCK_NM_VERSION="v1.105.0"))
        self.assertEqual(source.read_text(), customized)
        self.assertFalse(self.no_mistakes_updates())
        self.assert_no_actions()

    def test_cursor_pipeline_installs_user_owned_acpx_for_system_node(self):
        (self.mock / "acpx").unlink()
        for name in ("node", "npm"):
            (self.mock / name).symlink_to("mock-cli")
        self.assert_success(self.interactive_setup("y", ISSUE_AGENT="cursor"))
        # Without a user-writable global prefix, acpx goes beside the other commands instead of using sudo.
        self.assertEqual([c["args"] for c in self.calls("npm") if c["args"][:1] == ["install"]],
                         [["install", "-g", "--prefix", str(self.home / ".local"), "acpx@latest"]])
        self.assertTrue((self.wrapper.parent / "acpx").is_file())
        self.assertFalse(self.calls("sudo"))
        self.assert_no_actions(allow_onboarding=True)

    def test_cursor_pipeline_reuses_suitable_node_npm_and_acpx(self):
        (self.mock / "acpx").unlink()
        for name in ("node", "npm"):
            (self.mock / name).symlink_to("mock-cli")
        prefix = self.root / "npm global"
        (prefix / "lib/node_modules").mkdir(parents=True)
        (prefix / "bin").mkdir()
        self.env["PATH"] += os.pathsep + str(prefix / "bin")
        environment = {"ISSUE_AGENT": "cursor", "MOCK_NPM_PREFIX": str(prefix), "MOCK_NODE_VERSION": "v22.13.0"}
        self.assert_success(self.interactive_setup("y", **environment))
        self.assertEqual([c["args"] for c in self.calls("npm") if c["args"][:1] == ["install"]],
                         [["install", "-g", "acpx@latest"]])
        self.assertTrue((prefix / "bin/acpx").is_file())
        self.assertFalse(self.calls("brew"))
        # A rerun finds acpx and needs no npm.
        self.log.unlink()
        self.assert_success(self.setup(**environment))
        self.assertFalse(self.calls("npm") + self.calls("brew"))
        self.assert_no_actions()

    def test_missing_node_reports_incomplete_setup_without_installing_it(self):
        (self.mock / "acpx").unlink()
        (self.home / ".codex").mkdir()
        source = self.bundle / "no-mistakes/config.yaml"
        source.write_text(source.read_text().replace("agent: codex", "agent: cursor", 1))
        for run in (self.setup, lambda **environment: self.interactive_setup("y", **environment)):
            result = run(ISSUE_AGENT="cursor")
            self.assertNotEqual(result.returncode, 0, result.stdout)
            self.assertIn("Remaining action: put Node.js 22.13+ with npm first on PATH", result.stdout)
            self.assertIn("authentication/setup actions remain pending", result.stdout)
        self.assertFalse([c for c in self.calls("brew") if c["args"][:1] in (["install"], ["upgrade"])])
        self.assertFalse(self.calls("sudo"))
        self.assertFalse(self.calls("npm"))
        self.assertFalse((self.wrapper.parent / "acpx").exists())
        self.assertTrue(self.installed.is_dir())
        self.assert_no_actions(allow_onboarding=True)

    def test_doctor_reports_unfinished_agent_and_pipeline_onboarding(self):
        self.install()
        doctor = self.installed / "scripts/doctor.sh"
        self.save_issue_agent("claude")
        result = self.setup(MOCK_CLAUDE_AUTH="pending")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Remaining action: claude auth login", result.stdout)
        for kind, variable, label in (("claude", "MOCK_CLAUDE_AUTH", "Claude Code"), ("cursor", "MOCK_CURSOR_AUTH", "Cursor")):
            with self.subTest(kind=kind):
                self.save_issue_agent(kind)
                result = self.run_script(doctor, env={variable: "pending"})
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("FAIL: " + label + " authentication/setup pending", result.stdout)
                self.assertNotIn("AUTH_SECRET_SENTINEL", result.stdout + result.stderr)
        source = self.bundle / "no-mistakes/config.yaml"
        original = source.read_text()
        # Other native selections rely on native doctor instead of blocking onboarding.
        self.save_issue_agent("codex")
        for selection in ("auto", "acp:cursor"):
            with self.subTest(selection=selection):
                source.write_text(original.replace("agent: codex", "agent: " + selection, 1))
                result = self.run_script(doctor)
                self.assert_success(result)
                self.assertIn("NOTE: No-Mistakes pipeline agent " + selection + " login not checked", result.stdout)
                self.assertIn("Authentication/setup: complete", result.stdout)
                result = self.run_script(doctor, env={"MOCK_NM_DOCTOR": "fail"})
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("No-Mistakes pipeline agent not ready", result.stdout)
        source.write_text(original.replace("agent: codex", "agent: cursor", 1))
        (self.mock / "acpx").unlink()
        result = self.run_script(doctor)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("acpx missing", result.stdout)
        self.assertIn("Installation: incomplete", result.stdout)
        result = self.run_script(doctor, env={"MOCK_NM_DOCTOR": "fail"})
        self.assertIn("No-Mistakes pipeline agent not ready", result.stdout)
        self.bundle.rename(self.root / "moved clone")
        result = self.run_script(doctor)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("was the clone moved or deleted", result.stdout)
        self.assert_no_actions()

    def test_doctor_outside_herdr_is_successful_and_read_only(self):
        self.install()
        result = self.run_script(self.installed / "scripts/doctor.sh")
        self.assert_success(result)
        self.assertIn("runtime-context checks not performed", result.stdout.lower())
        self.assertNotIn("ready to launch from this context", result.stdout.lower())
        self.assert_no_actions()

    def test_doctor_without_installation_reports_incomplete_outside_herdr(self):
        result = self.run_script(self.bundle / "scripts/doctor.sh")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("installation: incomplete", result.stdout.lower())
        self.assertIn("runtime-context checks not performed", result.stdout.lower())
        self.assertNotIn("runtime: ready to launch", result.stdout.lower())
        self.assertFalse(self.installed.exists())
        self.assert_no_actions()

    def test_doctor_pending_authentication_hides_native_output(self):
        self.install()
        for variable in ("MOCK_GH_AUTH", "MOCK_CODEX_AUTH"):
            result = self.run_script(self.installed / "scripts/doctor.sh", env={variable: "pending"})
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("pending", (result.stdout + result.stderr).lower())
            self.assertNotIn("AUTH_SECRET_SENTINEL", result.stdout + result.stderr)
        self.assert_no_actions()

    def test_doctor_path_pending_and_missing_runtime_file(self):
        self.install()
        result = self.run_script(self.installed / "scripts/doctor.sh", env={"PATH": str(self.mock)})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("PATH", result.stdout + result.stderr)
        (self.installed / "scripts/integrations/gh-dash/gh-dash-codex-issue.sh").unlink()
        result = self.run_script(self.installed / "scripts/doctor.sh", "--integrity-only", "--bundle", self.installed)
        self.assertNotEqual(result.returncode, 0)
        self.assert_no_actions()

    def test_doctor_context_route_server_and_detection_capability(self):
        self.install()
        repo, _ = self.source_repo()
        route = {"HERDR_SOCKET_PATH": str(self.home / "test.sock"), "HERDR_WORKSPACE_ID": "ws",
                 "HERDR_TAB_ID": "tab", "HERDR_PANE_ID": "pane"}
        result = self.run_script(self.installed / "scripts/doctor.sh", cwd=repo, env=route)
        self.assert_success(result)
        self.assertIn("ready to launch from this context", result.stdout.lower())
        transports = [call for call in self.calls("git")
                      if "ls-remote" in call["args"] and "--get-url" not in call["args"]]
        self.assertTrue(transports)
        command = transports[-1]["env"].get("GIT_SSH_COMMAND", "")
        for option in ("BatchMode=yes", "StrictHostKeyChecking=yes", "UpdateHostKeys=no", "CheckHostIP=no"):
            self.assertIn(option, command, "doctor SSH check could prompt or modify host trust")
        for flag in ("MOCK_SERVER", "MOCK_ROUTE", "MOCK_MANIFEST", "MOCK_TRANSPORT"):
            result = self.run_script(self.installed / "scripts/doctor.sh", cwd=repo,
                env=dict(route, **{flag: "incompatible" if flag == "MOCK_SERVER" else "wrong" if flag == "MOCK_ROUTE" else "pending" if flag == "MOCK_TRANSPORT" else "missing"}))
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertNotIn("ready to launch from this context", result.stdout.lower())
        self.assert_no_actions()

    def test_doctor_custom_ssh_is_pending_but_working_https_requires_no_ssh(self):
        self.install()
        repo, git = self.source_repo()
        route = {"HERDR_SOCKET_PATH": str(self.home / "test.sock"), "HERDR_WORKSPACE_ID": "ws",
                 "HERDR_TAB_ID": "tab", "HERDR_PANE_ID": "pane"}
        for custom in ("environment", "git configuration"):
            with self.subTest(custom=custom):
                overrides = dict(route)
                if custom == "environment":
                    overrides["GIT_SSH_COMMAND"] = "/nonexistent/custom-ssh"
                else:
                    git("config", "core.sshCommand", "/nonexistent/custom-ssh")
                self.log.write_text("")
                result = self.run_script(self.installed / "scripts/doctor.sh", cwd=repo, env=overrides)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("custom SSH", result.stdout)
                self.assertFalse(any("ls-remote" in call["args"] and "--get-url" not in call["args"]
                                     for call in self.calls("git")), "doctor executed custom SSH transport")
                self.assert_no_actions()
        # Git URL rewriting chooses HTTPS before sshCommand or SSH availability
        # matters. A working HTTPS route must remain ready with either override.
        (self.mock / "ssh").unlink()
        self.log.write_text("")
        result = self.run_script(self.installed / "scripts/doctor.sh", cwd=repo,
            env=dict(route, MOCK_EFFECTIVE_URL="https://github.com/friend/target.git",
                     GIT_SSH_COMMAND="/nonexistent/custom-ssh"))
        self.assert_success(result)
        self.assertIn("ready to launch from this context", result.stdout.lower())
        self.assertTrue(any("ls-remote" in call["args"] and "--get-url" not in call["args"]
                            for call in self.calls("git")))
        self.assertFalse(self.calls("ssh"))
        self.assert_no_actions()


if __name__ == "__main__":
    unittest.main(verbosity=2)
