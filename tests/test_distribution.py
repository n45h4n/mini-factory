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
import shlex
import shutil
import signal
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
import json, os, pathlib, re, shutil, subprocess, sys
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
def native_update():
    if name in os.environ.get("MOCK_UPDATE_FAIL", "").split():
        (root / (name + "-partly-updated")).write_text("yes")
        fail(name + " update: simulated failure after replacing files")
    (root / (name + "-updated")).write_text("yes")
    print(name + " is up to date (test)")
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
    elif args[:2] == ["pr", "view"]:
        if "GH_REPO" in os.environ or args[2:5] != ["7", "--repo", "friend/target"]:
            fail("unexpected pull request lookup")
        head = os.environ["MOCK_PR_HEAD"]
        print(json.dumps({"number": 7, "state": "OPEN", "headRefOid": head,
                          "baseRefOid": os.environ.get("MOCK_PR_BASE", head),
                          "baseRefName": "main", "isCrossRepository": False}))
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
    elif args == ["extension", "upgrade", "dash"]:
        print("[dash]: already up to date")
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
        print("codex-cli " + os.environ.get("MOCK_CODEX_VERSION", "0.115.0"))
    elif args == ["--help"]:
        print("Codex CLI: login logout --version" if os.environ.get("MOCK_AGENT_HELP") == "old"
              else "Codex CLI\n  -c, --config <key=value>\n      --strict-config\n  -m, --model <MODEL>\n"
                   "  -C, --cd <DIR>\n      --add-dir <DIR>\n  -a, --ask-for-approval <APPROVAL_POLICY>\n"
                   "  login logout --version\n"
                   "Commands:\n  update            Update Codex to the latest version")
    elif args == ["update"]:
        native_update()
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
    elif args == ["--help"]:
        if os.environ.get("MOCK_AGENT_HELP") == "old":
            print("  --model <model>  Model for the current session")
        else:
            print("  --effort <level>                      Effort level for the current session\n"
                  "                                        (low, medium, high, xhigh, max)\n"
                  "  --model <model>                       Model for the current session. Provide\n"
                  "                                        an alias for the latest model (e.g.\n"
                  "                                        'fable', 'opus', or 'sonnet') or a\n"
                  "                                        model's full name.\n"
                  "  --name <name>                         Session name\n"
                  "  --add-dir <directories...>            Additional directories to allow tool\n"
                  "                                        access to\n"
                  "  --permission-mode <mode>              Permission mode to use for the session\n"
                  "                                        (choices: \"acceptEdits\", \"auto\",\n"
                  "                                        \"bypassPermissions\", \"manual\",\n"
                  "                                        \"dontAsk\", " + ("" if os.environ.get("MOCK_AGENT_HELP")
                                                                         == "no-plan" else "\"plan\"") + ")\n"
                  "  --permission-prompts <target>         Who answers permission prompts\n"
                  + ("" if os.environ.get("MOCK_AGENT_HELP") == "no-setting-sources" else
                     "  --setting-sources <sources>           Comma-separated list of setting sources\n"
                     "                                        to load (user, project, local).\n")
                  + "Commands:\n  update|upgrade                        Check for updates and install if available")
    elif args == ["update"]:
        native_update()
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
    elif args == ["--help"]:
        print("  --model <model>  Model to use\n  --list-models  List available models and exit\n"
              "  --mode <mode>                Start in the given execution mode. plan:\n"
              "                               read-only/planning (analyze, propose plans, no\n"
              "                               edits). " + ("" if os.environ.get("MOCK_AGENT_HELP") == "no-ask" else
                                                           "ask: Q&A style for explanations and\n"
                                                           "                               questions (read-only). ")
              + "(choices: \"plan\"" + ("" if os.environ.get("MOCK_AGENT_HELP") == "no-ask" else ", \"ask\"") + ")\n"
              "  --plan                       Start in plan mode (shorthand for --mode=plan).\n"
              "  --add-dir <path>             Add an additional workspace root directory\n"
              "Commands:\n  update                       Update Cursor Agent to the latest version")
    elif args == ["update"]:
        native_update()
    elif args == ["--list-models"]:
        if os.environ.get("MOCK_CURSOR_MODELS") == "missing":
            fail("Error: Authentication required.")
        print("\x1b[1mAvailable models\x1b[0m\n\nauto - Auto\ngpt-5 - GPT-5\n"
              "claude-opus-4-8[context=1m,effort=high] - Opus 4.8 (bracketed)")
    elif args == ["status", "--format", "json"]:
        # Native Cursor status succeeds while logged out; only the boolean distinguishes it.
        pending = os.environ.get("MOCK_CURSOR_AUTH") == "pending" and not (root / "cursor-authenticated").exists()
        print(json.dumps({"isAuthenticated": not pending, "email": "AUTH_SECRET_SENTINEL"}))
    elif args == ["login"]:
        (root / "cursor-authenticated").write_text("yes")
    else:
        fail()
elif name == "gum":
    if args == ["--version"]:
        if os.environ.get("MOCK_GUM") == "broken" and not (root / "gum-repaired").exists():
            fail("gum: cannot execute")
        print("gum version 0.17.0 (test)")
    elif args[:1] == ["confirm"] and "MOCK_GUM_ANSWERS" not in os.environ:
        # Setup and update confirmations read the key typed at the terminal, as native Gum does.
        if not os.isatty(0):
            fail("gum confirm: no terminal")
        print(args[-1], file=sys.stderr, flush=True)  # rendered on the terminal, as native Gum does
        typed = os.read(0, 1024)
        if not typed:
            sys.exit(1)
        key = typed.decode().strip()
        if key == "<cancel>":
            sys.exit(130)  # ctrl+c
        if key == "":
            # Enter takes the default, which native Gum makes Yes unless --default=false.
            sys.exit(1 if "--default=false" in args else 0)
        if key not in ("y", "Y", "n", "N"):
            fail("unexpected gum confirm keystroke: " + key)
        sys.exit(0 if key in ("y", "Y") else 1)
    elif args[:1] in (["choose"], ["input"], ["confirm"]):
        answers_path = pathlib.Path(os.environ["MOCK_GUM_ANSWERS"])
        answers = json.loads(answers_path.read_text())
        if not answers:
            fail("unexpected gum prompt")
        answer = answers.pop(0)
        answers_path.write_text(json.dumps(answers))
        if answer == "<cancel>":
            sys.exit(130)
        if args[0] == "confirm":
            sys.exit(0 if answer == "yes" else 1)
        print(answer)
    else:
        fail()
elif name == "apt-cache":
    archive = os.environ.get("MOCK_APT_GUM") == "archive"
    installed = (root / "gum").exists()
    # Newer Ubuntu releases carry gum in universe; older archives list no repository version.
    if args == ["madison", "gum"]:
        if archive:
            print("       gum |   0.17.0-1 | http://archive.ubuntu.com/ubuntu noble/universe amd64 Packages")
    elif args == ["madison", "nodejs"]:
        for version in os.environ.get("MOCK_APT_NODE", "18.19.1+dfsg-6ubuntu5").split():
            print("    nodejs | " + version + " | http://archive.ubuntu.com/ubuntu noble/universe amd64 Packages")
    elif args == ["policy", "gum"]:
        # Like APT, policy's Candidate may be an installed-only version whose repository was removed.
        print("gum:\n  Installed: " + ("0.17.0-1" if installed else "(none)") + "\n  Candidate: "
              + ("0.17.0-1" if archive or installed else "(none)") + "\n  Version table:")
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
    if args == ["--version"]:
        print("10.9.0")
    elif args == ["prefix", "-g"]:
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
    # Like the native strict (KnownFields) loader, reject any key outside the installed release's schema;
    # the ci bot fields exist only from prerelease v1.105.0.
    schema = {
        "": {"agent", "acpx_path", "forgejo_axi_path", "acp_registry_overrides", "agent_path_override",
             "agent_config", "agent_args_override", "ci_timeout", "step_quiet_warning", "agent_timeout",
             "review_agent_timeout", "test_agent_timeout", "daemon_connect_timeout", "branch_sync_remote_timeout",
             "gate_reconcile_interval", "gate_reconcile_timeout", "log_level", "session_reuse", "worktree_roots",
             "forge_profiles", "auto_fix", "ci", "rebase", "commit", "intent", "test", "providers", "review_agents"},
        "auto_fix": {"rebase", "review", "test", "document", "lint", "ci", "babysit"},
        "ci": {"rerun_transient", "revalidate_repairs"}
              | ({"review_bot_comments", "release_after_checks_pass"} if numeric >= (1, 105, 0) else set()),
    }
    types = {"": "config.GlobalRaw", "auto_fix": "config.AutoFixRaw", "ci": "config.CIRaw"}
    rejected, section = [], ""
    for number, line in enumerate(config.read_text().splitlines() if config.exists() else [], 1):
        key = re.match(r"( *)([A-Za-z_][\w-]*):", line)
        if not key:
            continue
        if not key.group(1):
            section = key.group(2)
        scope = "" if not key.group(1) else section
        if scope in schema and key.group(2) not in schema[scope]:
            rejected.append((number, key.group(2), types[scope]))
    if args == ["--version"]:
        print("no-mistakes version " + version + " (test) 2026-10-01T00:00:00Z")
    elif args == ["--help"]:
        print("Available Commands:\n  doctor      Check system health and dependencies\n"
              "  update      Update no-mistakes and reset the daemon")
    elif args == ["daemon", "restart"]:
        # Native startup writes a default config when missing.
        if rejected:
            fail("load config: field " + rejected[0][1] + " not found")
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
                  + "\n".join("  line " + str(number) + ": field " + field + " not found in type " + kind
                              for number, field, kind in rejected)
                  + ")\n\n  some checks failed")
        elif os.environ.get("MOCK_NM_REJECT") and re.search(os.environ["MOCK_NM_REJECT"], config.read_text()):
            # A native load rejection that nm-config's own checks cannot predict.
            rejection = re.search(os.environ["MOCK_NM_REJECT"], config.read_text()).group()
            print("  \u2717 gate validation  unavailable: load config (mock rejection: " + rejection
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
elif name == "herdr" and os.environ.get("MOCK_PR_WORKFLOW") == "1" and (
        args[:1] in (["worktree"], ["agent"]) or args[:3] in (["tab", "get", "pr-tab"], ["pane", "get", "pr-pane"])):
    state_file = root / "pr-workflow.json"
    state = json.loads(state_file.read_text()) if state_file.exists() else {}
    def worktrees(source):
        listing = subprocess.run([os.environ["REAL_GIT"], "-C", source, "worktree", "list", "--porcelain"],
                                 check=True, capture_output=True, text=True).stdout
        found = []
        for block in listing.strip().split("\n\n")[1:]:
            path = block.splitlines()[0].split(" ", 1)[1]
            found.append({"branch": None, "path": path, "is_bare": False, "is_detached": "detached" in block,
                          "is_prunable": False, "is_linked_worktree": True,
                          **({"open_workspace_id": "pr-ws"} if state.get("open") == path else {})})
        return found
    def agent():
        return {"name": state["alias"], "agent": state.get("kind", "codex"), "workspace_id": "pr-ws",
                "tab_id": "pr-tab", "pane_id": "pr-pane", "agent_status": os.environ.get("MOCK_AGENT_STATUS", "idle")}
    if args[:2] == ["worktree", "list"]:
        print(json.dumps({"id": "test", "result": {"type": "worktree_list",
            "source": {"source_checkout_path": args[args.index("--cwd") + 1], "source_workspace_id": "ws"},
            "worktrees": worktrees(args[args.index("--cwd") + 1])}}))
    elif args[:2] == ["worktree", "open"] and "--path" in args:
        path = args[args.index("--path") + 1]
        already_open, state["open"] = state.get("open") == path, path
        state_file.write_text(json.dumps(state))
        print(json.dumps({"id": "test", "result": {"type": "worktree_opened", "already_open": already_open,
            "workspace": {"workspace_id": "pr-ws"}, "tab": {"tab_id": "pr-tab", "workspace_id": "pr-ws"},
            "root_pane": {"pane_id": "pr-pane", "tab_id": "pr-tab", "workspace_id": "pr-ws", "foreground_cwd": path},
            "worktree": next(item for item in worktrees(args[args.index("--cwd") + 1]) if item["path"] == path)}}))
    elif args[:3] == ["tab", "get", "pr-tab"]:
        envelope("tab_info", "tab", {"tab_id": "pr-tab", "workspace_id": "pr-ws"})
    elif args[:3] == ["pane", "get", "pr-pane"]:
        envelope("pane_info", "pane", {"pane_id": "pr-pane", "tab_id": "pr-tab", "workspace_id": "pr-ws",
                                       "foreground_cwd": state["open"]})
    elif args[:2] == ["agent", "list"]:
        envelope("agent_list", "agents", [agent()] if "alias" in state else [])
    elif args[:2] == ["agent", "get"]:
        if state.get("alias") != args[2]:
            print(json.dumps({"id": "test", "error": {"code": "agent_not_found", "message": "agent not found"}}))
            sys.exit(1)
        envelope("agent_info", "agent", agent())
    elif (args[:2] == ["agent", "start"] and args[3] == "--kind" and args[4] in ("claude", "codex", "cursor")
          and args[5:8] == ["--pane", "pr-pane", "--timeout"] and "alias" not in state):
        state["alias"], state["kind"] = args[2], args[4]
        state_file.write_text(json.dumps(state))
        envelope("agent_started", "agent", agent())
    elif args[:3] in (["agent", "prompt", "pr-pane"], ["agent", "focus", "pr-pane"]) and "alias" in state:
        envelope("agent_prompted" if args[1] == "prompt" else "agent_info", "agent", agent())
    else:
        fail("unexpected PR review Herdr action")
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
    elif args == ["--help"]:
        print("Usage: herdr [options]\n       herdr update [--handoff]\n"
              "  herdr update                     Download and install the latest version")
    elif args == ["update"]:
        native_update()
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
        if (branch is None or args[3:9] != ["--kind", args[4], "--pane", sessions[branch]["pane"], "--timeout", "30000"]
                or args[9:10] not in ([], ["--"]) or args[4] not in ("claude", "codex", "cursor")):
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
    elif name == "brew" and args == ["--cellar"]:
        print(os.environ.get("MOCK_BREW_CELLAR", str(root / "no Homebrew Cellar")))
    elif name == "brew" and args[:2] == ["list", "--versions"]:
        if args[2] not in os.environ.get("MOCK_BREW_LISTED", "").split():
            sys.exit(1)
        print(args[2] + " 1.0.0")
    elif name == "sudo" and args[:1] == ["mkdir"] and all(
            value in ("mkdir", "-p", "-m", "755", "/etc/apt/keyrings", "/etc/apt/sources.list.d")
            for value in args):
        pass
    elif "install" in args or "upgrade" in args or "update" in args or "reinstall" in args:
        if os.environ.get("MOCK_INSTALL_FAIL"):
            fail("simulated interrupted package installation")
        if "gum" in args:
            (root / "gum-repaired").write_text("yes")
        provided = {"gh": ("gh",), "gum": ("gum",), "node": ("node", "npm"), "nodejs": ("node",), "npm": ("npm",)}
        for command in (command for package in args for command in provided.get(package, ())):
            if not (root / command).exists():
                shutil.copyfile(root / "mock-cli", root / command)
                (root / command).chmod(0o755)
    else:
        fail()
elif name == "git":
    if "ls-remote" in args:
        # Like native Git, --get-url only resolves configured rewrites locally; authentication happens on lookup.
        if os.environ.get("MOCK_TRANSPORT") == "pending" and "--get-url" not in args:
            fail("mock Git transport authentication failure")
        print(os.environ.get("MOCK_EFFECTIVE_URL", "git@github.com:friend/target.git")
              if "--get-url" in args else "0123456789abcdef0123456789abcdef01234567\tHEAD")
        sys.exit(0)
    if "fetch" in args and os.environ.get("MOCK_REMOTE"):
        # Preparation fetches GitHub's sshUrl; route it to a disposable local fixture.
        if os.environ.get("MOCK_FETCH") == "fail":
            fail("mock default-branch fetch failure")
        args = [os.environ["MOCK_REMOTE"] if arg == "git@github.com:friend/target.git" else arg for arg in args]
    elif (os.environ.get("MOCK_PR_WORKFLOW") == "1" and "worktree" in args
          and args[args.index("worktree") + 1:args.index("worktree") + 3] == ["add", "--detach"]):
        pass
    elif os.environ.get("MOCK_CLONE_UPDATE") == "1" and args[2:3] in (["fetch"], ["merge"]):
        pass  # make update fetches and fast-forwards the disposable retained clone fixture
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
    elif url == "https://repo.charm.sh/apt/gpg.key":
        destination.write_bytes(b"MOCK Charm armored key\n")
    else:
        fail("unexpected upstream URL")
elif name == "dpkg":
    if args == ["--print-architecture"]:
        print("amd64")
    elif args[:1] == ["-S"] and len(args) == 2:
        owners = json.loads(os.environ.get("MOCK_DPKG", "{}"))
        if args[1] not in owners:
            print("dpkg-query: no path found matching pattern " + args[1], file=sys.stderr)
            sys.exit(1)
        print(owners[args[1]] + ": " + args[1])
    else:
        fail()
else:
    fail()
'''.replace("#!PYTHON", "#!" + sys.executable).replace("ISSUE_BODY_LITERAL", repr(ISSUE_BODY)).replace(
    "import json, os, pathlib, shutil, subprocess, sys",
    "import json, os, pathlib, re, shutil, subprocess, sys",
)

# nm-config menu entries, as offered by Gum.
NM_MENU = {"agent": "Pipeline agent (agent)", "agent_config": "Harness model/effort defaults (agent_config)",
           "reviewer": "Reviewer (review_agents.reviewer)", "fixer": "Fixer (review_agents.fixer)",
           "reviewer_after_round": "Later-round reviewer (review_agents.reviewer_after_round)",
           "fixer_after_round": "Later-round fixer (review_agents.fixer_after_round)",
           "auto_fix": "Auto-fix attempts (auto_fix)", "session_reuse": "Fixer session reuse (session_reuse)",
           "save": "Review and save changes", "quit": "Quit without saving"}
INHERIT_CODEX = "Inherit agent_config.codex (clear)"
STABLE_DEFAULT = ("agent: codex # Initialized from the issue agent during first setup.\n"
                  "auto_fix:\n  review: 3\n  ci: 3\n")


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
        for name in ("gh", "codex", "claude", "cursor-agent", "node", "npm", "no-mistakes", "herdr", "uname",
                     "brew", "curl", "sudo", "apt-get", "apt-cache", "git", "nohup", "ssh", "dpkg", "gum"):
            (self.mock / name).symlink_to(mock_script.name)
        # acpx runs from the No-Mistakes daemon's PATH (login shell plus well-known directories) where setup's
        # npm --prefix ~/.local puts it.
        self.acpx = self.home / ".local/bin/acpx"
        self.acpx.parent.mkdir(parents=True)
        shutil.copyfile(mock_script, self.acpx)
        self.acpx.chmod(0o755)
        # acpx starts the node the daemon's PATH finds first. ~/bin precedes the system directories there (but is
        # not on the shell's PATH, whose node is mock bin/node), so no host Node.js decides the daemon checks.
        self.daemon_node = self.home / "bin/node"
        self.daemon_node.parent.mkdir()
        shutil.copyfile(mock_script, self.daemon_node)
        self.daemon_node.chmod(0o755)
        # A controlled PATH makes genuinely missing dependencies reproducible.
        utilities = ("bash sh env make jq python3 tar mkdir cp mv rm chmod cat find readlink dirname "
                     "basename mktemp sed awk tr stat date sleep touch ln id ps cmp head cut sort uniq "
                     "wc xargs grep install tee gzip unzip which du rmdir sha256sum shasum")
        for name in utilities.split():
            executable = sys.executable if name == "python3" else shutil.which(name, path=REAL_PATH)
            if executable and not (self.mock / name).exists():
                (self.mock / name).symlink_to(executable)
        self.env = {"HOME": str(self.home), "XDG_DATA_HOME": str(self.home / "data with spaces"),
                    "XDG_STATE_HOME": str(self.home / "state"), "XDG_CONFIG_HOME": str(self.home / "config"),
                    "PATH": str(self.home / ".local/bin") + os.pathsep + str(self.mock), "MOCK_BIN": str(self.mock), "MOCK_LOG": str(self.log),
                    "REAL_GIT": REAL_GIT or "", "LANG": "C", "TERM": "dumb",
                    # The login shell No-Mistakes probes for its daemon PATH; startup files live in the test home.
                    "SHELL": shutil.which("bash", path=REAL_PATH) or "/bin/bash",
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
        # More than one prompt may be needed; every answer remains explicit.
        return self.run_in_terminal([str(self.bundle / "scripts/setup.sh")], dict(self.env, **overrides),
                                    ((answer + "\n") * 24).encode())

    def run_in_terminal(self, argv, env, keystrokes=b""):
        master, slave = pty.openpty()
        process = subprocess.Popen(argv, cwd=self.root, env=env, stdin=slave,
                                   stdout=slave, stderr=slave, close_fds=True)
        os.close(slave)
        output = bytearray()
        deadline = time.monotonic() + 30
        try:
            os.write(master, keystrokes)
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
                    self.fail("terminal command did not finish; output: " + output.decode(errors="replace"))
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

    def npm_changes(self):
        """npm invocations other than read-only version and global-prefix queries."""
        return [call for call in self.calls("npm") if call["args"] not in (["--version"], ["prefix", "-g"])]

    def gum_confirms(self):
        return [call["args"] for call in self.calls("gum") if call["args"][:1] == ["confirm"]]

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
        for relative in ("bin/ghd", "bin/mf-config", "bin/nm-config", "scripts/setup.sh", "scripts/update.sh",
                         "scripts/doctor.sh", "scripts/integrations/gh-dash/gh-dash-codex-issue.sh",
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
        self.wrapper.parent.mkdir(parents=True, exist_ok=True)
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
        self.assertFalse(self.npm_changes(), "an existing acpx needs no npm")
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

    def test_setup_guides_git_transport_without_prompting_for_or_changing_git_credentials(self):
        (self.home / ".codex").mkdir()
        gitconfig = self.home / ".gitconfig"
        # Only the disposable home's Git configuration decides whether a GitHub credential helper exists.
        isolated = {"GIT_CONFIG_NOSYSTEM": "1", "MOCK_GH_AUTH": "pending"}
        doctor = subprocess.run(["bash", "-c", 'printf %q "$1"', "quote", str(self.installed / "scripts/doctor.sh")],
                                capture_output=True, text=True, check=True).stdout
        follow_up = "No Git credential helper is configured for https://github.com"

        def assert_no_git_credential_change():
            self.assertFalse([c["args"] for c in self.calls("gh") if c["args"][:2] == ["auth", "setup-git"]])
            for call in self.calls("git"):
                if "config" in call["args"]:
                    self.assertTrue(any(arg.startswith("--get") for arg in call["args"]), call["args"])

        # Declined login: a useful next step, no transport changes, and nothing to verify yet.
        result = self.interactive_setup("n", **isolated)
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn("Remaining action: gh auth login --hostname github.com --web", result.stdout)
        self.assertNotIn(follow_up, result.stdout)
        self.assertFalse(gitconfig.exists())
        assert_no_git_credential_change()
        # Consented login: the native flow owns its HTTPS credential prompt; setup adds no second prompt.
        self.log.write_text("")
        result = self.interactive_setup("y", **isolated)
        self.assert_success(result)
        self.assertIn(["auth", "login", "--hostname", "github.com", "--web", "--scopes", "project"],
                      [c["args"] for c in self.calls("gh")])
        text = " ".join(result.stdout.split())
        self.assertIn("does not by itself prove Git can fetch your target repository", text)
        self.assertIn("run " + doctor + " from the target checkout's Herdr pane, staying in that checkout", text)
        self.assertIn(follow_up, text)
        self.assertIn("gh auth setup-git --hostname github.com yourself", text)
        self.assertIn("can replace a helper previously configured for that host", text)
        self.assertNotRegex(result.stdout, r"setup-git[^\n]*\r?\n?Proceed\?")
        self.assertIn("run " + doctor + " there to check its Git transport, then run ghd", text)
        self.assertFalse(gitconfig.exists())
        assert_no_git_credential_change()
        # Noninteractive rerun: the same guidance, no prompt, no approval inferred, and no change.
        self.log.write_text("")
        result = self.setup(**isolated)
        self.assert_success(result)
        self.assertIn(follow_up, result.stdout)
        self.assertNotIn("Consent pending", result.stdout)
        self.assertNotIn(["auth", "login", "--hostname", "github.com", "--web"],
                         [c["args"][:5] for c in self.calls("gh")])
        self.assertFalse(gitconfig.exists())
        assert_no_git_credential_change()
        # An existing HTTPS helper (as native gh auth login or gh auth setup-git writes it) is left alone.
        existing = '[credential "https://github.com"]\n\thelper = \n\thelper = !/usr/bin/gh auth git-credential\n'
        gitconfig.write_text(existing)
        self.log.write_text("")
        result = self.interactive_setup("y", **isolated)
        self.assert_success(result)
        self.assertIn("does not by itself prove Git can fetch", " ".join(result.stdout.split()))
        self.assertNotIn(follow_up, result.stdout)
        self.assertEqual(existing, gitconfig.read_text())
        assert_no_git_credential_change()
        self.assert_no_actions()

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

    def test_installed_dispatchers_ignore_an_unrelated_dotfiles_installation(self):
        # An inherited DOTFILES_DIR naming another installation with the same layout (such as a personal dotfiles
        # checkout) never chooses the backend helper; each dispatcher runs its own bundle's helper.
        self.install()
        repo, _ = self.source_repo()
        unrelated = self.root / "unrelated dotfiles"
        marker = self.root / "unrelated helper ran"
        helpers = unrelated / "scripts/integrations/gh-dash"
        helpers.mkdir(parents=True)
        for name in ("gh-dash-codex-issue.sh", "gh-dash-codex-pr-review.sh"):
            (helpers / name).write_text("#!/usr/bin/env bash\ntouch '" + str(marker) + "'\n")
            (helpers / name).chmod(0o755)
        directory = self.installed / "scripts/integrations/gh-dash"
        for name in ("gh-dash-codex-issue-dispatch.sh", "gh-dash-codex-pr-review-dispatch.sh"):
            self.assert_success(self.run_script(directory / name, "friend/target", "8", cwd=repo,
                                                env={"DOTFILES_DIR": str(unrelated)}))
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
        self.assertFalse(marker.exists())
        self.assert_no_actions()

    def test_issue_and_pr_routes_use_chmod_operand_order_native_bsd_accepts(self):
        # Native macOS/BSD chmod stops parsing options at the mode, so "chmod 700 -- path" names a file "--";
        # GNU chmod permutes arguments and hides that. This chmod follows the BSD rule.
        chmod = self.mock / "chmod"
        chmod.unlink()
        chmod.write_text("""#!/bin/sh
mode_seen= options_ended=
for argument do
	if [ -n "$mode_seen" ]; then
		[ "$argument" != -- ] || { echo 'chmod: --: No such file or directory' >&2; exit 1; }
	elif [ -z "$options_ended" ] && [ "$argument" = -- ]; then
		options_ended=1
	elif [ -n "$options_ended" ] || [ "${argument#-}" = "$argument" ]; then
		mode_seen=1
	fi
done
exec '""" + shutil.which("chmod", path=REAL_PATH) + """' "$@"
""")
        chmod.chmod(0o755)
        rejected = subprocess.run([str(chmod), "700", "--", str(self.root)], capture_output=True, text=True)
        self.assertEqual((rejected.returncode, rejected.stderr), (1, "chmod: --: No such file or directory\n"))
        state = Path(self.env["XDG_STATE_HOME"])
        directory = self.bundle / "scripts/integrations/gh-dash"
        repo, git = self.source_repo(base=self.root / "issue")
        # The gh-dash bindings: issue i, issue I, and PR I (whose launcher execs its dispatcher).
        for script, *mode in (("gh-dash-codex-issue-dispatch.sh", "prepare"), ("gh-dash-codex-issue-dispatch.sh",),
                              ("gh-dash-codex-pr-review.sh",)):
            with self.subTest(script=script, mode=mode):
                self.assert_success(self.run_script(directory / script, "friend/target", "8", *mode, cwd=repo))
        deadline = time.monotonic() + 5
        logs = []
        while time.monotonic() < deadline:
            logs = list(state.glob("gh-dash-codex-*/*.log"))
            if len(logs) == 3 and all("HERDR_SOCKET_PATH" in file.read_text() for file in logs):
                break
            time.sleep(0.02)
        self.assertEqual(len(logs), 3)
        for file in logs:
            self.assertNotIn("chmod", file.read_text())
            self.assertEqual(stat.S_IMODE(file.stat().st_mode), 0o600)
        # The backends protect their state, lock, intent, and review-context directories.
        self.advance_default_branch(git, "Current default branch")
        route = self.issue_environment(repo, git, cwd=repo)
        self.assert_success(self.issue_helper(**route))
        self.assert_success(self.issue_helper("prepare", **route))
        pr_repo, pr_git = self.source_repo(base=self.root / "pr")
        self.assert_success(self.run_pr_review(pr_repo, self.pr_environment(pr_repo, pr_git)))
        _, context = self.pr_review_paths()
        for path in (state / "gh-dash-codex-issue", state / "gh-dash-codex-issue/locks",
                     state / "gh-dash-codex-issue/intents", state / "gh-dash-codex-pr-review",
                     state / "gh-dash-codex-pr-review/locks", context.parent, context):
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o700, path)

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
        # The captured issue text controls implementation; a later fetch is context only.
        quoted_intent = re.search(r"^intent_file=(.+)$", prompt, re.MULTILINE).group(1)
        self.assertTrue(prompt.startswith("Use the title and body of issue friend/target#8 captured in the private file "
                                          + quoted_intent + " as the implementation prompt;"))
        for rule in ("that captured text is authoritative for the implementation scope",
                     "a later issue revision must not change the implementation scope",
                     "report the difference instead of implementing it"):
            self.assertIn(rule, prompt)
        self.assertNotIn("use its body as the prompt", prompt)
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
                            "Do not create or change this repository's CI workflows for this purpose unless the issue asks",
                            "never change its .no-mistakes.yaml for this purpose or set no_ci, even if the issue asks",
                            "owner must add PR-triggered CI and get it onto the default branch",
                            "deliberately declare no_ci: true there"):
            self.assertIn(requirement, prompt)
        # Allow CI its own registration interval, independent of earlier run waits.
        stop = prompt.index("Do not reattach forever to an empty check list.")
        self.assertLess(prompt.index("reattach to the same run"), stop)
        for requirement in ("When you first observe that the CI step is waiting and gh pr checks reports no checks",
                            "start a separate two-minute check-registration interval",
                            "time spent in earlier run/reattach waits does not count",
                            "During that interval, poll native status and PR checks at bounded intervals",
                            "If checks appear, continue driving the same run normally",
                            "Only if the full two-minute interval ends with no checks, or a blocker is independently confirmed earlier",
                            "stop reattaching, keep the run and PR in place",
                            "inspect PR mergeability and workflow trigger status before assigning the blocker",
                            "An empty check list alone does not establish missing CI",
                            "If a merge conflict prevented a pull_request workflow from running, report the conflict as the blocker",
                            "follow native branch_sync/recovery guidance",
                            "Otherwise report the observed trigger blocker",
                            "if the cause cannot be confirmed, report it as unknown",
                            "Report the exact native CI status, the supporting evidence, and the appropriate corrective action",
                            "recommend the owner's corrective action from step 3 only when missing CI is independently established",
                            "Never bypass CI, mark checks passed, or set no_ci yourself"):
            self.assertIn(requirement, prompt[stop:])
        self.assertNotIn("If a bounded wait expires while the CI step is still waiting", prompt[stop:])
        self.assertNotIn("the missing CI is established:", prompt[stop:])
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
        # The issue keys use Cursor and the default PR reviewer uses Codex.
        installs = [args for args in self.herdr_calls("integration", "install") if "--help" not in args]
        self.assertEqual(installs, [["integration", "install", "cursor"], ["integration", "install", "codex"]])
        self.assertFalse(self.npm_changes())
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

    def test_acpx_is_baseline_and_installed_user_owned_for_system_node(self):
        # Every role and No-Mistakes duty is Codex; acpx is still provisioned so Cursor can be chosen later.
        self.acpx.unlink()
        self.assert_success(self.interactive_setup("y"))
        # Without a user-writable global prefix on the daemon's PATH, acpx goes beside the other commands, never sudo.
        self.assertEqual([c["args"] for c in self.calls("npm") if c["args"][:1] == ["install"]],
                         [["install", "-g", "--prefix", str(self.home / ".local"), "acpx@latest"]])
        self.assertTrue(self.acpx.is_file())
        self.assertFalse(self.calls("sudo"))
        self.assert_no_actions(allow_onboarding=True)

    def test_acpx_must_run_for_the_no_mistakes_daemon_without_changing_npm_or_node(self):
        # A writable global prefix on the shell's PATH but outside the daemon's PATH (not set by the login shell).
        self.acpx.unlink()
        prefix = self.root / "npm global"
        (prefix / "lib/node_modules").mkdir(parents=True)
        (prefix / "bin").mkdir()
        self.env["PATH"] += os.pathsep + str(prefix / "bin")
        environment = {"MOCK_NPM_PREFIX": str(prefix), "MOCK_NODE_VERSION": "v22.13.0"}
        self.assert_success(self.interactive_setup("y", **environment))
        self.assertEqual([c["args"] for c in self.calls("npm") if c["args"][:1] == ["install"]],
                         [["install", "-g", "--prefix", str(self.home / ".local"), "acpx@latest"]])
        self.assertTrue(self.acpx.is_file())
        self.assertFalse((prefix / "bin/acpx").exists())
        # A rerun finds acpx and needs no npm.
        self.log.unlink()
        self.assert_success(self.setup(**environment))
        self.assertFalse(self.npm_changes() + self.calls("brew"))
        # An acpx that runs only from the shell's PATH is reported, never moved or reinstalled.
        self.acpx.rename(prefix / "bin/acpx")
        result = self.setup(**environment)
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn("runs only from your current shell PATH, not from the No-Mistakes daemon's PATH", result.stdout)
        doctor = self.run_script(self.installed / "scripts/doctor.sh", env=environment)
        self.assertNotEqual(doctor.returncode, 0)
        self.assertIn("FAIL: acpx or its Node.js does not run from the No-Mistakes daemon's PATH", doctor.stdout)
        self.assertTrue((prefix / "bin/acpx").is_file())
        self.assertFalse(self.npm_changes())
        self.assert_no_actions()

    def test_existing_acpx_in_home_bin_runs_for_the_daemon_and_is_reused(self):
        # ~/bin is on the No-Mistakes service PATH even where the shell PATH lacks it: nothing is installed or moved.
        home_bin = self.home / "bin"
        home_bin.mkdir(exist_ok=True)
        self.acpx.rename(home_bin / "acpx")
        self.install()
        self.assertFalse(self.npm_changes())
        self.assertFalse(self.acpx.exists())
        doctor = self.run_script(self.installed / "scripts/doctor.sh")
        self.assert_success(doctor)
        self.assertIn("OK: acpx runs from the No-Mistakes daemon's PATH", doctor.stdout.splitlines())
        # One there that does not run is genuinely unusable: reported, never claimed ready.
        (home_bin / "acpx").write_text("#!/bin/sh\nexit 1\n")
        self.log.write_text("")
        result = self.setup()
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn("Remaining action: npm install -g --prefix " + str(self.home / ".local") + " acpx@latest",
                      result.stdout)
        doctor = self.run_script(self.installed / "scripts/doctor.sh")
        self.assertNotEqual(doctor.returncode, 0)
        self.assertIn("FAIL: acpx or its Node.js does not run from the No-Mistakes daemon's PATH", doctor.stdout)
        self.assertFalse(self.npm_changes())
        self.assert_no_actions()

    def test_acpx_from_a_version_manager_in_the_login_shell_runs_for_the_daemon(self):
        # Like nvm or fnm: acpx (and its Node.js) only on the PATH the login shell's startup files set. The daemon
        # adopts that PATH, so setup and doctor accept it without installing or moving anything.
        manager = self.root / "nvm versions/node/v22.13.0/bin"
        manager.mkdir(parents=True)
        self.acpx.rename(manager / "acpx")
        profile = self.home / ".bash_profile"
        profile.write_text('echo "rc output"\nPATH="' + str(manager) + ':$PATH"\nexport PATH\n')
        self.env["PATH"] += os.pathsep + str(manager)
        self.install()
        self.assertFalse(self.npm_changes())
        self.assertFalse(self.acpx.exists())
        doctor = self.run_script(self.installed / "scripts/doctor.sh")
        self.assert_success(doctor)
        self.assertIn("OK: acpx runs from the No-Mistakes daemon's PATH", doctor.stdout.splitlines())
        # Without that startup file the daemon would not find it: reported, never moved or reinstalled.
        profile.unlink()
        self.env["PATH"] += os.pathsep + str(manager)
        result = self.setup()
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn("runs only from your current shell PATH, not from the No-Mistakes daemon's PATH", result.stdout)
        doctor = self.run_script(self.installed / "scripts/doctor.sh")
        self.assertNotEqual(doctor.returncode, 0)
        self.assertIn("FAIL: acpx or its Node.js does not run from the No-Mistakes daemon's PATH", doctor.stdout)
        self.assertTrue((manager / "acpx").is_file())
        self.assertFalse(self.npm_changes())
        self.assert_no_actions()

    def test_shell_node_24_does_not_mask_daemon_node_18(self):
        # Like a version manager's Node.js 24 active only in your shell while the daemon's PATH finds an older
        # Node.js 18 first: acpx would run on 18, so readiness fails with the action, and nothing is replaced.
        self.install()
        old_node = "#!/bin/sh\necho v18.19.1\n"
        self.daemon_node.write_text(old_node)
        self.log.write_text("")
        result = self.interactive_setup("y")
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn("Remaining action: the No-Mistakes daemon's PATH ", result.stdout)
        self.assertIn("finds " + str(self.daemon_node) + ", Node.js v18.19.1 first, but acpx runs with that PATH "
                      "and needs Node.js 22.13+; your current shell's " + str(self.mock / "node") + " does not count",
                      result.stdout)
        self.assertIn("OK: Node.js 22.13+ for acpx", result.stdout.splitlines())
        # A running daemon keeps the PATH it started with, so the action includes restarting it before doctor.
        self.assertIn("restart the No-Mistakes daemon (a running daemon keeps the PATH it started with), and rerun "
                      "make doctor.", result.stdout)
        doctor = self.run_script(self.installed / "scripts/doctor.sh")
        self.assertNotEqual(doctor.returncode, 0)
        self.assertIn("OK: Node.js 22.13+ for acpx", doctor.stdout.splitlines())
        self.assertIn("FAIL: Node.js 22.13+ required by acpx from the No-Mistakes daemon's PATH (", doctor.stdout)
        self.assertIn("which finds " + str(self.daemon_node) + " v18.19.1; your shell's Node.js does not count",
                      doctor.stdout)
        self.assertIn("restart the No-Mistakes daemon, which keeps the PATH it started with", doctor.stdout)
        self.assertEqual(self.daemon_node.read_text(), old_node)
        self.assertFalse(self.npm_changes() + self.calls("sudo")
                         + [c for c in self.calls("brew") if c["args"][:1] in (["install"], ["upgrade"])])
        # Activating Node.js 24 from the login shell's startup files, as a version manager does, makes it ready.
        manager = self.root / "fnm node-versions/v24.11.0/bin"
        manager.mkdir(parents=True)
        shutil.copyfile(self.mock / "mock-cli", manager / "node")
        (manager / "node").chmod(0o755)
        (self.home / ".bash_profile").write_text('PATH="' + str(manager) + ':$PATH"\nexport PATH\n')
        self.assert_success(self.setup())
        doctor = self.run_script(self.installed / "scripts/doctor.sh")
        self.assert_success(doctor)
        self.assertIn("OK: Node.js 22.13+ runs from the No-Mistakes daemon's freshly resolved PATH", doctor.stdout.splitlines())
        self.assertEqual(self.daemon_node.read_text(), old_node)
        self.assert_no_actions()

    def test_daemon_path_timeout_does_not_wait_for_a_detached_stdout_holder(self):
        shell = self.root / "probe shell"
        helper_pid = self.root / "detached-helper.pid"
        shell.write_text("#!" + sys.executable + "\nimport subprocess, sys\n"
                         "from pathlib import Path\n"
                         "helper = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'], "
                         "start_new_session=True)\n"
                         "Path(" + repr(str(helper_pid)) + ").write_text(str(helper.pid))\n"
                         "print('PATH=/probe-only', flush=True)\n")
        shell.chmod(0o755)
        try:
            result = subprocess.run([sys.executable, "-I", "-B", str(self.bundle / "scripts/nm_config.py"),
                                     "daemon-path"], env=dict(self.env, SHELL=str(shell)), capture_output=True,
                                    text=True, timeout=45)
            self.assert_success(result)
            self.assertNotIn("/probe-only", result.stdout)
            self.assertTrue(result.stdout.startswith(str(self.home / ".local/bin") + os.pathsep))
        finally:
            if helper_pid.exists():
                try:
                    os.kill(int(helper_pid.read_text()), signal.SIGKILL)
                except ProcessLookupError:
                    pass

    def test_doctor_waits_for_a_slow_login_shell_as_no_mistakes_does(self):
        # No-Mistakes allows each login-shell probe 30 seconds. A startup file slower than the old 10-second probe
        # and 15-second doctor limits must still yield the daemon's PATH instead of a false acpx failure.
        manager = self.root / "nvm versions/node/v22.13.0/bin"
        manager.mkdir(parents=True)
        self.acpx.rename(manager / "acpx")
        profile = self.home / ".bash_profile"
        profile.write_text('PATH="' + str(manager) + ':$PATH"\nexport PATH\n')
        self.env["PATH"] += os.pathsep + str(manager)
        self.install()
        profile.write_text("sleep 16\n" + profile.read_text())
        doctor = self.run_script(self.installed / "scripts/doctor.sh")
        self.assert_success(doctor)
        self.assertIn("OK: acpx runs from the No-Mistakes daemon's PATH", doctor.stdout.splitlines())

    def test_configured_acpx_path_is_what_setup_and_doctor_check(self):
        self.install()
        source = self.bundle / "no-mistakes/config.yaml"
        original = source.read_text()
        custom = self.root / "custom acpx/acpx"
        custom.parent.mkdir()
        self.acpx.rename(custom)
        # Native No-Mistakes runs acpx_path verbatim instead of acpx from its PATH.
        source.write_text(original + "acpx_path: " + json.dumps(str(custom)) + "\n")
        self.log.write_text("")
        result = self.interactive_setup("y")
        self.assert_success(result)
        self.assertIn("No-Mistakes acpx_path: " + str(custom), result.stdout)
        doctor = self.run_script(self.installed / "scripts/doctor.sh")
        self.assert_success(doctor)
        self.assertIn("OK: acpx runs from the No-Mistakes daemon's PATH (acpx_path: " + str(custom) + ")",
                      doctor.stdout.splitlines())
        # A configured acpx_path that does not run is reported and never installed over, even with consent;
        # an acpx on the PATH does not stand in for it.
        custom.rename(self.acpx)
        result = self.interactive_setup("y")
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn("Remaining action: acpx_path " + str(custom) + " in the No-Mistakes config does not run",
                      result.stdout)
        doctor = self.run_script(self.installed / "scripts/doctor.sh")
        self.assertNotEqual(doctor.returncode, 0)
        self.assertIn("FAIL: acpx (acpx_path: " + str(custom) + ") or its Node.js does not run from the No-Mistakes "
                      "daemon's PATH", doctor.stdout)
        # An acpx_path nm-config cannot read is never assumed to be acpx.
        source.write_text(original + "acpx_path: [acpx]\n")
        result = self.setup()
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn("Remaining action: No-Mistakes acpx_path not checked", result.stdout)
        doctor = self.run_script(self.installed / "scripts/doctor.sh")
        self.assertNotEqual(doctor.returncode, 0)
        self.assertIn("FAIL: cannot read acpx_path", doctor.stdout)
        # Without the setting, the acpx on the daemon's PATH is used again.
        source.write_text(original)
        self.assert_success(self.setup())
        self.assertFalse(self.npm_changes())
        self.assert_no_actions()

    def test_missing_node_is_installed_only_with_consent_and_an_existing_one_is_never_replaced(self):
        self.acpx.unlink()
        for name in ("node", "npm"):
            (self.mock / name).unlink()
        (self.home / ".codex").mkdir()
        for run in (self.setup, lambda: self.interactive_setup("n")):
            result = run()
            self.assertNotEqual(result.returncode, 0, result.stdout)
            self.assertIn("Remaining action: Node.js is missing; acpx needs Node.js 22.13+ with npm. Setup never "
                          "replaces an existing Node.js or version manager", result.stdout)
            self.assertIn("authentication/setup actions remain pending", result.stdout)
            self.assertTrue(self.installed.is_dir())
        self.assertFalse([c for c in self.calls("brew") if c["args"][:1] in (["install"], ["upgrade"])])
        self.assertFalse(self.npm_changes())
        # With consent, Homebrew installs the missing Node.js (with npm), then npm installs acpx.
        self.assert_success(self.interactive_setup("y"))
        self.assertEqual([c["args"] for c in self.calls("brew") if c["args"][:1] in (["install"], ["upgrade"])],
                         [["install", "node"]])
        self.assertTrue(self.acpx.is_file())
        # An older Node.js (for example from fnm or nvm) is reported with the exact action, never replaced.
        self.acpx.unlink()
        self.log.write_text("")
        result = self.interactive_setup("y", MOCK_NODE_VERSION="v20.11.0")
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn(str(self.mock / "node") + " is Node.js v20.11.0; acpx needs Node.js 22.13+ with npm", result.stdout)
        self.assertIn("FAIL: Node.js 22.13+ required by acpx (found v20.11)", result.stdout)
        self.assertFalse([c for c in self.calls("brew") if c["args"][:1] in (["install"], ["upgrade"])])
        self.assertFalse(self.npm_changes() + self.calls("sudo"))
        self.assert_no_actions(allow_onboarding=True)

    def test_mocked_ubuntu_installs_missing_node_only_from_suitable_apt_sources(self):
        if not Path("/etc/os-release").exists() or not re.search(r'^ID=["\']?ubuntu', Path("/etc/os-release").read_text(), re.M):
            self.skipTest("Ubuntu detection reads the native os-release file")
        ubuntu = {"MOCK_OS": "Linux", "MOCK_ARCH": "x86_64"}
        self.acpx.unlink()
        for name in ("node", "npm"):
            (self.mock / name).unlink()
        # Ubuntu's archive offers only an older nodejs: guidance instead of a package change.
        result = self.interactive_setup("y", **ubuntu)
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn("Remaining action: Node.js is missing", result.stdout)
        self.assertFalse([c for c in self.calls("sudo") if {"nodejs", "npm"} & set(c["args"])])
        # A configured source with 22.13+ (a newer archive or NodeSource) is used with consent; npm follows if separate.
        self.log.write_text("")
        self.assert_success(self.interactive_setup("y", MOCK_APT_NODE="22.14.0-1nodesource1", **ubuntu))
        self.assertEqual([c["args"] for c in self.calls("sudo") if {"nodejs", "npm"} & set(c["args"])],
                         [["apt-get", "install", "-y", "--no-install-recommends", "nodejs"],
                          ["apt-get", "install", "-y", "--no-install-recommends", "npm"]])
        self.assertEqual([c["args"] for c in self.calls("npm") if c["args"][:1] == ["install"]],
                         [["install", "-g", "--prefix", str(self.home / ".local"), "acpx@latest"]])
        self.assert_no_actions(allow_onboarding=True)

    def test_cursor_for_every_role_needs_no_codex_login_or_integration(self):
        self.assertNotEqual(self.setup(PR_REVIEW_AGENT="copilot").returncode, 0)
        self.assertFalse(self.installed.exists())
        pending = {"MOCK_CODEX_AUTH": "pending", "MOCK_INTEGRATION": "pending"}
        result = self.interactive_setup("y", ISSUE_AGENT="cursor", PR_REVIEW_AGENT="cursor", **pending)
        self.assert_success(result)
        self.assertIn("Issues i preparer: cursor; Issues I implementer: cursor; PRs I reviewer: cursor", result.stdout)
        path = self.profiles_file()
        self.assertEqual(json.loads(path.read_text()), {"version": 1, "profiles": {"pr-review": {"agent": "cursor"}}})
        # All three CLIs are installed; only Cursor logs in and gets a Herdr integration.
        self.assertNotIn(["login", "--device-auth"], [c["args"] for c in self.calls("codex")])
        self.assertEqual([args for args in self.herdr_calls("integration", "install") if "--help" not in args],
                         [["integration", "install", "cursor"]])
        self.assertFalse((self.home / ".codex").exists())
        self.env["PATH"] = str(self.wrapper.parent) + os.pathsep + str(self.mock)
        doctor = self.run_script(self.installed / "scripts/doctor.sh", env=pending)
        self.assert_success(doctor)
        for line in ("OK: codex version responds", "OK: claude version responds", "OK: cursor-agent version responds",
                     "OK: acpx runs from the No-Mistakes daemon's PATH", "OK: PRs I reviewer: Cursor (mf-config selection)",
                     "OK: Cursor authenticated", "OK: Herdr Cursor integration current"):
            self.assertIn(line, doctor.stdout.splitlines())
        self.assertNotIn("Codex authenticated", doctor.stdout)
        self.assertNotIn("Herdr Codex integration", doctor.stdout)
        # The saved choice survives later runs; switching another role later needs no new prerequisite install.
        self.assert_success(self.setup(**pending))
        self.assertEqual(self.mf_config("agent", "pr-review").stdout, "cursor\noverride\n")
        self.profiles_file({"pr-review": {"agent": "claude", "model": "opus"}})
        self.log.write_text("")
        result = self.interactive_setup("y", MOCK_INTEGRATION="pending")
        self.assert_success(result)
        self.assertFalse(self.calls("curl") + self.npm_changes() + [c for c in self.calls("brew") if "install" in c["args"]])
        self.assertIn(["integration", "install", "claude"], self.herdr_calls("integration", "install"))
        # PR_REVIEW_AGENT keeps a same-harness profile; Codex is the default, so choosing it removes the override.
        self.assert_success(self.setup(PR_REVIEW_AGENT="claude"))
        self.assertEqual(json.loads(path.read_text())["profiles"]["pr-review"], {"agent": "claude", "model": "opus"})
        self.assert_success(self.interactive_setup("y", PR_REVIEW_AGENT="codex"))
        self.assertEqual(self.mf_config("agent", "pr-review").stdout, "codex\ndefault\n")
        self.assert_no_actions(allow_onboarding=True)

    def test_doctor_reports_unfinished_agent_and_no_mistakes_onboarding(self):
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
        self.save_issue_agent("codex")
        # An unused, logged-out agent never blocks doctor.
        self.assert_success(self.run_script(doctor, env={"MOCK_CLAUDE_AUTH": "pending", "MOCK_CURSOR_AUTH": "pending"}))
        # auto (and fallback lists) rely on native doctor instead of blocking onboarding.
        source.write_text(original.replace("agent: codex", "agent: auto", 1))
        result = self.run_script(doctor)
        self.assert_success(result)
        self.assertIn("NOTE: No-Mistakes agent auto login not checked", result.stdout)
        self.assertIn("Authentication/setup: complete", result.stdout)
        result = self.run_script(doctor, env={"MOCK_NM_DOCTOR": "fail"})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("No-Mistakes pipeline agent not ready", result.stdout)
        # A Cursor duty needs Cursor login wherever it is configured, but no Herdr integration.
        (self.mock / "herdr-integrated-codex").write_text("yes")
        for config, line in (
                (original.replace("agent: codex", "agent: acp:cursor", 1), "OK: No-Mistakes agent: acp:cursor"),
                (original.replace("agent: codex", "agent: auto", 1) + "review_agents:\n  reviewer:\n    agent: cursor\n",
                 "OK: No-Mistakes review_agents.reviewer: cursor"),
                (original + "review_agents:\n  fixer:\n    agent: acp:cursor\n", "OK: No-Mistakes review_agents.fixer: acp:cursor"),
                (original + "review_agents:\n  fixer_after_round:\n    agent: cursor\n    after_round: 2\n",
                 "OK: No-Mistakes review_agents.fixer_after_round: cursor")):
            with self.subTest(config=config):
                source.write_text(config)
                result = self.run_script(doctor, env={"MOCK_INTEGRATION": "pending"})
                self.assert_success(result)
                self.assertIn(line + " (Cursor login checked; no Herdr integration needed)", result.stdout)
                self.assertIn("OK: Cursor authenticated", result.stdout)
                self.assertNotIn("Herdr Cursor integration", result.stdout)
                result = self.run_script(doctor, env={"MOCK_CURSOR_AUTH": "pending"})
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("FAIL: Cursor authentication/setup pending: cursor-agent login", result.stdout)
                result = self.setup(MOCK_CURSOR_AUTH="pending")
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("No-Mistakes agents needing login: ", result.stdout)
                self.assertIn("Remaining action: cursor-agent login", result.stdout)
                self.assertEqual(source.read_bytes().decode(), config)
        # Duties nm-config cannot read may need a logged-out agent: login stays pending, never complete.
        for config in (original + "review_agents: &roles\n  reviewer:\n    agent: cursor\n",
                       original + "review_agents:\n  reviewer: {agent: cursor}\n",
                       (original + "review_agents:\n  fixer:\n    agent: cursor\n").replace("\n", "\r\n")):
            with self.subTest(config=config):
                source.write_text(config)
                result = self.run_script(doctor, env={"MOCK_CURSOR_AUTH": "pending"})
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("FAIL: No-Mistakes agent login pending: cannot read their agents", result.stdout)
                self.assertNotIn("Authentication/setup: complete", result.stdout)
                result = self.setup(MOCK_CURSOR_AUTH="pending")
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("Remaining action: No-Mistakes agents not checked", result.stdout)
                self.assertEqual(source.read_bytes().decode(), config)
        source.write_text(original)
        self.acpx.unlink()
        result = self.run_script(doctor)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("FAIL: acpx or its Node.js does not run from the No-Mistakes daemon's PATH", result.stdout)
        self.assertIn("Installation: incomplete", result.stdout)
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
        # The installation check names the target-context command instead of implying transport was verified.
        self.assertIn("NOTE: Git transport not checked", result.stdout)
        self.assertIn("pane run " + shlex.quote(str(self.installed / "scripts/doctor.sh")) + " before ghd",
                      result.stdout)
        self.assertIn("make doctor in the Mini-Factory clone checks only this installation", result.stdout)
        self.assertFalse([c for c in self.calls("git") if "ls-remote" in c["args"]])
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
        self.assertIn("OK: Git transport authenticated over SSH: git@github.com:friend/target.git (read-only ls-remote)",
                      result.stdout)
        transports = [call for call in self.calls("git")
                      if "ls-remote" in call["args"] and "--get-url" not in call["args"]]
        self.assertTrue(transports)
        command = transports[-1]["env"].get("GIT_SSH_COMMAND", "")
        for option in ("BatchMode=yes", "StrictHostKeyChecking=yes", "UpdateHostKeys=no", "CheckHostIP=no"):
            self.assertIn(option, command, "doctor SSH check could prompt or modify host trust")
        # The README's quick-start command, run from the target checkout's pane, checks that target's transport.
        quick_start = (self.bundle / "README.md").read_text().split("## Bootstrap on macOS")[0]
        documented = '"${XDG_DATA_HOME:-$HOME/.local/share}/mini-factory/scripts/doctor.sh"'
        self.assertIn(documented + "\nghd\n", quick_start)
        self.log.write_text("")
        result = subprocess.run(["bash", "-c", documented], cwd=repo, env=dict(self.env, **route),
                                stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=30)
        self.assert_success(result)
        self.assertIn("OK: Git transport authenticated over SSH", result.stdout)
        lookups = [call for call in self.calls("git") if "ls-remote" in call["args"]]
        self.assertEqual(len(lookups), 2)
        self.assertTrue(all(call["cwd"] == str(repo) for call in lookups), lookups)
        for flag in ("MOCK_SERVER", "MOCK_ROUTE", "MOCK_MANIFEST", "MOCK_TRANSPORT"):
            result = self.run_script(self.installed / "scripts/doctor.sh", cwd=repo,
                env=dict(route, **{flag: "incompatible" if flag == "MOCK_SERVER" else "wrong" if flag == "MOCK_ROUTE" else "pending" if flag == "MOCK_TRANSPORT" else "missing"}))
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertNotIn("ready to launch from this context", result.stdout.lower())
            # A context failure stops before transport, and says so.
            self.assertEqual("NOTE: Git transport not checked" in result.stdout, flag != "MOCK_TRANSPORT",
                             result.stdout)
        self.assert_no_actions()

    def test_doctor_transport_failures_name_the_ssh_or_https_remedy_and_change_nothing(self):
        self.install()
        repo, _ = self.source_repo()
        route = {"HERDR_SOCKET_PATH": str(self.home / "test.sock"), "HERDR_WORKSPACE_ID": "ws",
                 "HERDR_TAB_ID": "tab", "HERDR_PANE_ID": "pane", "MOCK_TRANSPORT": "pending"}
        rerun = "then rerun " + shlex.quote(str(self.installed / "scripts/doctor.sh"))
        local_config = (repo / ".git/config").read_text()
        ssh_guide = "https://docs.github.com/en/authentication/connecting-to-github-with-ssh"
        result = self.run_script(self.installed / "scripts/doctor.sh", cwd=repo, env=route)
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("ready to launch from this context", result.stdout.lower())
        self.assertIn("FAIL: Git transport authentication/trust pending: read-only git ls-remote of "
                      "git@github.com:friend/target.git", result.stdout)
        for text in ("over SSH", ssh_guide, "verify GitHub's host key fingerprint yourself",
                     "doctor never accepts host keys", "choose HTTPS deliberately: gh auth setup-git --hostname "
                     "github.com", "can replace a previously configured one",
                     "in this target checkout git config url.\"https://github.com/\".insteadOf 'git@github.com:'",
                     rerun):
            self.assertIn(text, result.stdout)
        # An HTTPS rewrite gets the HTTPS remedy; credentials embedded in the URL are never shown.
        result = self.run_script(self.installed / "scripts/doctor.sh", cwd=repo, env=dict(
            route, MOCK_EFFECTIVE_URL="https://friend:TOKEN_SENTINEL@github.com/friend/target.git"))
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("TOKEN_SENTINEL", result.stdout + result.stderr)
        self.assertIn("read-only git ls-remote of https://***@github.com/friend/target.git", result.stdout)
        for text in ("over HTTPS without prompts; Git insteadOf rewrote GitHub sshUrl git@github.com:friend/target.git",
                     "give Git a credential helper with access to this repository",
                     "gh auth setup-git --hostname github.com", "remove the insteadOf rewrite to use SSH", rerun):
            self.assertIn(text, result.stdout)
        self.assertNotIn(ssh_guide, result.stdout)
        # Diagnostics only read Git configuration: no remote, rewrite, helper, or host-trust change.
        self.assertEqual(local_config, (repo / ".git/config").read_text())
        self.assertFalse((self.home / ".gitconfig").exists())
        self.assertFalse((self.home / ".ssh").exists())
        for call in self.calls("git"):
            if "config" in call["args"]:
                self.assertTrue(any(arg.startswith("--get") for arg in call["args"]), call["args"])
        self.assertFalse([c for c in self.calls("gh") if c["args"][:2] == ["auth", "setup-git"]])
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
                self.assertIn("FAIL: Git transport not checked: custom SSH", result.stdout)
                self.assertIn("choose HTTPS deliberately", result.stdout)
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
        self.assertIn("OK: Git transport authenticated over HTTPS: https://github.com/friend/target.git (read-only "
                      "ls-remote; Git insteadOf rewrote GitHub sshUrl git@github.com:friend/target.git)", result.stdout)
        self.assertTrue(any("ls-remote" in call["args"] and "--get-url" not in call["args"]
                            for call in self.calls("git")))
        self.assertFalse(self.calls("ssh"))
        self.assert_no_actions()

    # mf-config: per-key agent profiles, the Gum editor, and fresh-launch options.

    def profiles_file(self, profiles=None):
        path = Path(self.env["XDG_CONFIG_HOME"]) / "mini-factory/agent-profiles.json"
        if profiles is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"version": 1, "profiles": profiles}))
        return path

    def mf_config(self, *args, **env):
        return self.run_script(self.bundle / "bin/mf-config", *args, env=env)

    def edit_profiles(self, *answers, **overrides):
        answers_file = self.root / "gum answers.json"
        answers_file.write_text(json.dumps(list(answers)))
        self.log.write_text("")
        result = self.run_in_terminal([str(self.bundle / "bin/mf-config")],
                                      dict(self.env, MOCK_GUM_ANSWERS=str(answers_file), **overrides))
        return result, json.loads(answers_file.read_text())

    def gum_prompts(self):
        prompts = []
        for call in self.calls("gum"):
            args = call["args"]
            if args[0] == "confirm":
                prompts.append(("confirm", args[1], None, []))
            elif args[0] in ("choose", "input"):
                index = 3
                current = None
                if args[3:4] in (["--selected"], ["--value"]):
                    current, index = args[4], 5
                prompts.append((args[0], args[2], current, args[index:]))
        return prompts

    def codex_cache(self, present=True):
        directory = self.home / "codex home"
        directory.mkdir(exist_ok=True)
        cache = directory / "models_cache.json"
        if present:
            cache.write_text(json.dumps({"client_version": "0.166.0", "models": [
                {"slug": "gpt-test-fast", "visibility": "list",
                 "supported_reasoning_levels": [{"effort": "low"}, {"effort": "high"}, {"effort": "ultra"}],
                 "service_tiers": [{"id": "priority", "name": "Fast"}], "additional_speed_tiers": ["fast"]},
                {"slug": "gpt-test-standard", "visibility": "list",
                 "supported_reasoning_levels": [{"effort": "medium"}], "service_tiers": [],
                 "additional_speed_tiers": []},
                {"slug": "gpt-hidden-internal", "visibility": "hide"}]}))
        elif cache.exists():
            cache.unlink()
        return {"CODEX_HOME": str(directory)}

    def pr_environment(self, repo, git, **overrides):
        # main is the PR base; the PR head adds one change on top of it, outside the source checkout.
        base = git("rev-parse", "HEAD")
        git("update-ref", "refs/heads/main", base)
        git("checkout", "-q", "-b", "pr-head-fixture")
        (repo / "reviewed.txt").write_text("reviewed change\n")
        git("add", "reviewed.txt")
        git("commit", "-q", "-m", "PR change")
        head = git("rev-parse", "HEAD")
        git("checkout", "-q", "feature/friend")
        git("branch", "-q", "-D", "pr-head-fixture")
        git("update-ref", "refs/pull/7/head", head)
        return {"HERDR_SOCKET_PATH": str(self.home / "test.sock"), "HERDR_WORKSPACE_ID": "ws",
                "HERDR_TAB_ID": "tab", "HERDR_PANE_ID": "pane", "MOCK_PR_WORKFLOW": "1",
                "MOCK_REMOTE": str(repo), "MOCK_PR_HEAD": head, "MOCK_PR_BASE": base,
                "GH_DASH_SOURCE_ROOT": str(repo), "GH_DASH_SOURCE_REPO": "friend/target",
                "GH_DASH_SOURCE_BRANCH": "feature/friend", "GH_DASH_SOURCE_SHA": base,
                "GH_DASH_SOURCE_DIRTY": "0", "GH_DASH_CODEX_PR_REVIEW_BACKEND": "1", **overrides}

    def test_mf_config_show_reports_legacy_fallback_and_precedence_without_a_terminal(self):
        self.save_issue_agent("claude")
        result = self.mf_config("show")
        self.assert_success(result)
        lines = result.stdout.splitlines()
        self.assertIn("Issues i - preparer: Claude Code - shared issue agent (no per-role override)", lines)
        self.assertIn("Issues I - implementer: Claude Code - shared issue agent (no per-role override)", lines)
        self.assertIn("PRs I - reviewer: Codex - default (no saved selection); interactive, read-only (permission "
                      "profile :read-only, no network); findings stay in its terminal", lines)
        self.assertIn("(none saved yet)", result.stdout)
        self.assertIn("its mf-config selection, then the shared issue agent, then Codex", result.stdout)
        for role in ("issue-prepare", "issue-implement"):
            self.assertEqual(self.mf_config("agent", role).stdout, "claude\nshared\n")
        self.profiles_file({"issue-implement": {"agent": "cursor", "model": "gpt-5"},
                            "pr-review": {"agent": "codex", "effort": "high", "fast": False}})
        result = self.mf_config("show")
        self.assert_success(result)
        self.assertIn("Issues i - preparer: Claude Code - shared issue agent", result.stdout)
        self.assertIn("Issues I - implementer: Cursor - mf-config per-role selection", result.stdout)
        self.assertIn("model: gpt-5 (Cursor's model ID owns its variant/effort)", result.stdout)
        self.assertIn("model: native default; reasoning effort: high; Fast: off", result.stdout)
        self.assertEqual(self.mf_config("agent", "issue-implement").stdout, "cursor\noverride\n")
        self.assertEqual(self.mf_config("agent", "pr-review").stdout, "codex\noverride\n")
        # Each harness can review PRs; show names its native read-only mode and terminal-only output.
        for kind, label, mode in (("claude", "Claude Code", "Plan mode"), ("cursor", "Cursor", "Ask mode")):
            self.profiles_file({"pr-review": {"agent": kind}})
            result = self.mf_config("show")
            self.assert_success(result)
            self.assertIn("PRs I - reviewer: " + label + " - mf-config selection; interactive, read-only (" + mode
                          + "); findings stay in its terminal", result.stdout.splitlines())
            self.assertIn("no file edits, PR comments, reviews, or other GitHub writes", result.stdout)
            self.assertEqual(self.mf_config("agent", "pr-review").stdout, kind + "\noverride\n")
        # Editing needs a terminal; show stays available.
        result = self.mf_config()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("mf-config show", result.stderr)
        self.assertFalse(self.calls("gum"))

    def test_pr_profile_lookups_ignore_invalid_shared_issue_agent(self):
        path = Path(self.env["XDG_CONFIG_HOME"]) / "mini-factory/issue-agent"
        path.parent.mkdir(parents=True)
        for invalid in ("invalid value", None):
            if invalid is None:
                path.unlink()
                path.mkdir()
            else:
                path.write_text(invalid)
            for profiles, source, arguments in (({}, "default", ""),
                    ({"pr-review": {"agent": "codex", "model": "review-model", "effort": "high"}},
                     "override", '--model\nreview-model\n--config\nmodel_reasoning_effort="high"\n')):
                with self.subTest(invalid=invalid, profiles=profiles):
                    self.profiles_file(profiles)
                    result = self.mf_config("agent", "pr-review")
                    self.assert_success(result)
                    self.assertEqual(result.stdout, "codex\n" + source + "\n")
                    result = self.mf_config("launch-args", "pr-review", "codex")
                    self.assert_success(result)
                    self.assertEqual(result.stdout, arguments)
                    for role in ("issue-prepare", "issue-implement"):
                        result = self.mf_config("agent", role)
                        self.assertEqual(result.returncode, 1)
                        self.assertIn("invalid issue agent setting", result.stderr)
            if invalid is not None:
                self.assertEqual(path.read_text(), invalid)
            else:
                self.assertTrue(path.is_dir())

    def test_mf_config_rejects_invalid_profiles_without_repairing_them(self):
        invalid = (
            '{"version": 1, "profiles": {"pr-review": {"agent": "cursor", "effort": "high"}}}',
            '{"version": 1, "profiles": {"pr-review": {"agent": "claude", "fast": true}}}',
            '{"version": 1, "profiles": {"issue-prepare": {"agent": "cursor", "effort": "high"}}}',
            '{"version": 1, "profiles": {"issue-prepare": {"agent": "codex", "model": "--yolo"}}}',
            '{"version": 1, "profiles": {"issue-prepare": {"agent": "codex", "fast": "on"}}}',
            '{"version": 1, "profiles": {"issue-prepare": {"agent": "codex"}, "issue-prepare": {"agent": "claude"}}}',
            '{"version": 2, "profiles": {}}',
            'not json',
        )
        path = self.profiles_file({})
        for content in invalid:
            with self.subTest(content=content):
                path.write_text(content)
                for args in (("show",), ("agent", "issue-prepare"), ("launch-args", "pr-review", "codex")):
                    result = self.mf_config(*args)
                    self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                    self.assertIn("mf-config:", result.stderr)
                self.assertEqual(path.read_text(), content)
        # A worker refuses before creating anything when the preference is unreadable.
        repo, git = self.source_repo()
        result = self.issue_helper(**self.issue_environment(repo, git, cwd=repo))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unable to read the I agent preference", result.stderr)
        self.assertFalse(self.herdr_calls("worktree", "create") or self.herdr_calls("agent", "start"))

    def test_editor_offers_three_profiles_and_saves_only_after_confirmation(self):
        self.save_issue_agent("claude")
        path = self.profiles_file()
        source = self.bundle / "no-mistakes/config.yaml"
        pipeline = source.read_text()
        result, remaining = self.edit_profiles("Issues i - preparer", "Claude Code", "opus", "max", "yes")
        self.assert_success(result)
        self.assertEqual(remaining, [])
        prompts = self.gum_prompts()
        self.assertEqual(prompts[0][0], "choose")
        self.assertEqual(prompts[0][3], ["Issues i - preparer", "Issues I - implementer", "PRs I - reviewer"])
        harness = prompts[1]
        self.assertEqual(harness[3], ["Shared issue agent: Claude Code (no per-role override)", "Codex",
                                      "Claude Code", "Cursor"])
        self.assertEqual(harness[2], "Shared issue agent: Claude Code (no per-role override)")
        # Claude aliases and effort levels come from claude --help; native default is first.
        self.assertEqual(prompts[2][3], ["Native default (no override)", "fable", "opus", "sonnet", "haiku",
                                         "Custom model ID (unverified)"])
        self.assertEqual(prompts[3][3], ["Native default (no override)", "low", "medium", "high", "xhigh", "max",
                                         "Custom value (unverified)"])
        self.assertEqual(prompts[4][0], "confirm")
        self.assertEqual(json.loads(path.read_text()),
                         {"version": 1, "profiles": {"issue-prepare": {"agent": "claude", "model": "opus",
                                                                       "effort": "max"}}})
        self.assertEqual(self.mf_config("agent", "issue-implement").stdout, "claude\nshared\n")
        self.assertEqual(source.read_text(), pipeline, "mf-config must not touch the No-Mistakes pipeline agent")
        self.assertIn("Existing Herdr agents keep their original harness and options", result.stdout)
        saved = path.read_bytes()
        # Cancellation, a declined save, and invalid input all leave the saved file unchanged.
        for answers, status in ((("Issues I - implementer", "<cancel>"), 130),
                                (("Issues I - implementer", "Codex", "<cancel>"), 130),
                                (("Issues I - implementer", "Cursor", "auto", "no"), 130),
                                (("Issues I - implementer", "Codex", "Custom model ID (unverified)", "--yolo"), 1),
                                (("Issues I - implementer", "Codex", "Custom model ID (unverified)", "has space"), 1),
                                (("Issues I - implementer", "Not a listed harness"), 1)):
            with self.subTest(answers=answers):
                result, _ = self.edit_profiles(*answers)
                self.assertEqual(result.returncode, status, result.stdout)
                self.assertEqual(path.read_bytes(), saved)
                self.assertIn("unchanged" if status == 130 else "invalid", result.stdout)
        # Selecting the shared agent removes only that key's override.
        result, remaining = self.edit_profiles("Issues i - preparer", "Shared issue agent: Claude Code (no per-role override)",
                                               "yes")
        self.assert_success(result)
        self.assertEqual(remaining, [])
        self.assertEqual(json.loads(path.read_text()), {"version": 1, "profiles": {}})
        self.assertEqual(self.mf_config("agent", "issue-prepare").stdout, "claude\nshared\n")
        result, remaining = self.edit_profiles("Issues i - preparer",
                                               "Shared issue agent: Claude Code (no per-role override)")
        self.assert_success(result)
        self.assertIn("No change; nothing was saved.", result.stdout)

    def test_codex_picker_uses_local_cache_effort_levels_and_fast_availability(self):
        cache = self.codex_cache()
        path = self.profiles_file()
        new = dict(cache, MOCK_CODEX_VERSION="0.166.0")
        result, remaining = self.edit_profiles("Issues I - implementer", "Codex", "gpt-test-fast", "ultra", "On", "yes",
                                               **new)
        self.assert_success(result)
        self.assertEqual(remaining, [])
        prompts = self.gum_prompts()
        # Hidden cache entries are not offered; custom input always remains available.
        self.assertEqual(prompts[2][3], ["Native default (no override)", "gpt-test-fast", "gpt-test-standard",
                                         "Custom model ID (unverified)"])
        self.assertEqual(prompts[3][3], ["Native default (no override)", "low", "high", "ultra",
                                         "Custom value (unverified)"])
        self.assertEqual(prompts[4][1], "Issues I - implementer: Codex Fast (separate from reasoning effort)")
        self.assertEqual(prompts[4][2], "Off", "an explicit Fast choice defaults to Off")
        self.assertEqual(prompts[4][3], ["Off", "On", "Native default (no override)"])
        self.assertEqual(json.loads(path.read_text())["profiles"]["issue-implement"],
                         {"agent": "codex", "model": "gpt-test-fast", "effort": "ultra", "fast": True})
        # A saved On survives when metadata disappears, but only as an explicit, preselected choice.
        self.codex_cache(present=False)
        result, remaining = self.edit_profiles("Issues I - implementer", "Codex", "gpt-test-fast", "ultra", "Off", "yes",
                                               **new)
        self.assert_success(result)
        self.assertEqual(remaining, [])
        prompts = self.gum_prompts()
        self.assertEqual(prompts[2][3], ["Native default (no override)", "gpt-test-fast", "Custom model ID (unverified)"])
        self.assertEqual(prompts[2][2], "gpt-test-fast")
        self.assertEqual(prompts[3][3], ["Native default (no override)", "ultra", "low", "medium", "high", "xhigh",
                                         "Custom value (unverified)"])
        self.assertEqual(prompts[4][2], "On")
        self.assertIn("kept for review", result.stdout)
        self.assertEqual(json.loads(path.read_text())["profiles"]["issue-implement"]["fast"], False)
        # A saved Off without advertised support can stay Off or be cleared, but never become On.
        saved = path.read_bytes()
        result, remaining = self.edit_profiles("Issues I - implementer", "Codex", "gpt-test-fast", "ultra", "On",
                                               **new)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(remaining, [])
        self.assertEqual(path.read_bytes(), saved)
        prompts = self.gum_prompts()
        self.assertEqual(prompts[4][2], "Off")
        self.assertEqual(prompts[4][3], ["Off", "Native default (no override)"])
        result, remaining = self.edit_profiles("Issues I - implementer", "Codex", "gpt-test-fast", "ultra",
                                               "Native default (no override)", "yes", **new)
        self.assert_success(result)
        self.assertEqual(remaining, [])
        self.assertEqual(json.loads(path.read_text())["profiles"]["issue-implement"],
                         {"agent": "codex", "model": "gpt-test-fast", "effort": "ultra"})
        # Missing cache, custom model: no Fast choice is offered and native Fast stays untouched.
        result, remaining = self.edit_profiles("PRs I - reviewer", "Codex", "Custom model ID (unverified)",
                                               "my-model-1", "high", "yes", **new)
        self.assert_success(result)
        self.assertEqual(remaining, [])
        self.assertFalse([prompt for prompt in self.gum_prompts() if "Fast" in prompt[1]])
        self.assertIn("No local Codex model cache", result.stdout)
        self.assertEqual(json.loads(path.read_text())["profiles"]["pr-review"],
                         {"agent": "codex", "model": "my-model-1", "effort": "high"})
        # An installed Codex without Fast routing is never offered Fast, even for an advertising model.
        self.codex_cache()
        for answers in (("Issues i - preparer", "Codex", "gpt-test-fast", "high", "yes"),
                        ("Issues i - preparer", "Codex", "Native default (no override)",
                         "Native default (no override)", "yes")):
            with self.subTest(answers=answers):
                result, remaining = self.edit_profiles(*answers, **cache)
                self.assert_success(result)
                self.assertEqual(remaining, [])
                self.assertFalse([prompt for prompt in self.gum_prompts() if "Fast" in prompt[1]])
        self.assertEqual(json.loads(path.read_text())["profiles"]["issue-prepare"], {"agent": "codex"})
        # Codex with all-native choices is the default reviewer, so its override is removed.
        result, remaining = self.edit_profiles("PRs I - reviewer", "Codex", "Native default (no override)",
                                               "Native default (no override)", "yes", **new)
        self.assert_success(result)
        self.assertNotIn("pr-review", json.loads(path.read_text())["profiles"])
        # Claude Code and Cursor reviewers are saved even with native defaults; only native options are offered.
        result, remaining = self.edit_profiles("PRs I - reviewer", "Claude Code", "Native default (no override)",
                                               "high", "yes")
        self.assert_success(result)
        self.assertEqual(remaining, [])
        harness = self.gum_prompts()[1]
        self.assertEqual(harness[1], "PRs I - reviewer: harness (Codex is the default; each starts read-only)")
        self.assertEqual(harness[2], "Codex")
        self.assertEqual(harness[3], ["Codex", "Claude Code", "Cursor"])
        self.assertEqual(json.loads(path.read_text())["profiles"]["pr-review"], {"agent": "claude", "effort": "high"})
        result, remaining = self.edit_profiles("PRs I - reviewer", "Cursor", "Native default (no override)", "yes")
        self.assert_success(result)
        self.assertEqual(remaining, [])
        self.assertEqual(self.gum_prompts()[1][2], "Claude Code", "the current reviewer harness is preselected")
        self.assertFalse([prompt for prompt in self.gum_prompts() if "effort" in prompt[1].lower()])
        self.assertEqual(json.loads(path.read_text())["profiles"]["pr-review"], {"agent": "cursor"})

    def test_cursor_picker_uses_bounded_model_list_and_preserves_custom_values(self):
        path = self.profiles_file()
        bracketed = "claude-opus-4-8[context=1m,effort=high]"
        result, remaining = self.edit_profiles("Issues i - preparer", "Cursor", bracketed, "yes")
        self.assert_success(result)
        self.assertEqual(remaining, [])
        prompts = self.gum_prompts()
        self.assertEqual(prompts[2][3], ["Native default (no override)", "auto", "gpt-5", bracketed,
                                         "Custom model ID (unverified)"])
        self.assertEqual(prompts[3][0], "confirm", "Cursor has no separate effort selector")
        self.assertEqual(json.loads(path.read_text())["profiles"]["issue-prepare"],
                         {"agent": "cursor", "model": bracketed})
        self.assertEqual([c["args"] for c in self.calls("cursor-agent")], [["--list-models"]])
        # Unavailable metadata (for example logged out) keeps the saved and custom values usable.
        saved = path.read_bytes()
        result, remaining = self.edit_profiles("Issues i - preparer", "Cursor", "Native default (no override)", "no",
                                               MOCK_CURSOR_MODELS="missing")
        self.assertEqual(result.returncode, 130)
        self.assertEqual(remaining, [])
        self.assertEqual(path.read_bytes(), saved)
        prompts = self.gum_prompts()
        self.assertEqual(prompts[2][3], ["Native default (no override)", bracketed, "Custom model ID (unverified)"])
        # Gum splits --selected on commas; the saved model ID is escaped.
        self.assertEqual(prompts[2][2], bracketed.replace(",", "\\,"))
        self.assertIn("model list is unavailable", result.stdout)

    def test_separate_issue_profiles_reach_only_fresh_agents_with_native_options(self):
        self.save_issue_agent("cursor")
        self.profiles_file({"issue-prepare": {"agent": "claude", "model": "opus", "effort": "high"},
                            "issue-implement": {"agent": "codex", "model": "gpt-test-fast",
                                                "effort": "xhigh", "fast": False}})
        repo, git = self.source_repo()
        self.advance_default_branch(git, "Current default branch")
        route = self.issue_environment(repo, git, cwd=repo, MOCK_CODEX_VERSION="0.166.0")
        self.assert_success(self.issue_helper(**route))
        self.assert_success(self.issue_helper("prepare", **route))
        self.assertEqual(self.herdr_calls("agent", "start"), [
            ["agent", "start", "target-8", "--kind", "codex", "--pane", "issue-pane", "--timeout", "30000",
             "--", "--model", "gpt-test-fast", "--config", 'model_reasoning_effort="xhigh"',
             "--config", 'service_tier="default"'],
            ["agent", "start", "target-prep-8", "--kind", "claude", "--pane", "prep-pane", "--timeout", "30000",
             "--", "--model", "opus", "--effort", "high"]])
        # Changing a profile while its agent exists never replaces the agent or its options.
        self.profiles_file({"issue-prepare": {"agent": "cursor", "model": "gpt-5"},
                            "issue-implement": {"agent": "codex", "model": "gpt-test-standard", "fast": True}})
        for status in ("working", "blocked", "idle"):
            with self.subTest(status=status):
                self.log.write_text("")
                self.assert_success(self.issue_helper(**dict(route, MOCK_AGENT_STATUS=status)))
                self.assert_success(self.issue_helper("prepare", **dict(route, MOCK_AGENT_STATUS=status)))
                self.assertFalse(self.herdr_calls("agent", "start"))
                self.assertFalse([c for c in self.calls("herdr") if c["args"][:2] in (["pane", "close"], ["agent", "send-keys"])])
                self.assertEqual(self.herdr_calls("agent", "focus"), [["agent", "focus", "issue-pane"],
                                                                     ["agent", "focus", "prep-pane"]])
                implement, prepare = self.notifications()[-2:]
                self.assertIn("Reused the existing Codex agent with its original options", implement)
                self.assertIn("Kept the existing Claude Code agent with its original options", prepare)
                for notification in (implement, prepare):
                    self.assertIn("exit it in its pane", notification)
                # Saved knobs are not even read for retained agents.
                self.assertFalse([c for c in self.calls() if c["tool"] in ("codex", "claude", "cursor-agent")
                                  and c["args"] == ["--help"]])

    def test_launch_refuses_options_the_installed_cli_cannot_accept(self):
        repo, git = self.source_repo()
        route = self.issue_environment(repo, git, cwd=repo)
        cases = ((("issue-implement", {"agent": "claude", "effort": "max"}), {"MOCK_AGENT_HELP": "old"}, "--effort"),
                 (("issue-implement", {"agent": "codex", "fast": True}), {}, "Codex 0.154.0 or newer"),
                 (("issue-implement", {"agent": "cursor", "model": "auto"}), {"MOCK_AGENT_HELP": "old"}, None))
        for (role, profile), overrides, refusal in cases:
            with self.subTest(profile=profile):
                self.profiles_file({role: profile})
                self.log.write_text("")
                result = self.issue_helper(**dict(route, **overrides))
                if refusal is None:
                    # Cursor's --model is still advertised by the older help fixture.
                    self.assert_success(result)
                    self.assertEqual(self.herdr_calls("agent", "start")[0][-3:], ["--", "--model", "auto"])
                    continue
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(refusal, result.stderr)
                self.assertIn("agent not started and prompt not sent", result.stderr)
                self.assertFalse(self.herdr_calls("agent", "start") or self.herdr_calls("agent", "prompt"))

    def pr_review_paths(self):
        state = Path(self.env["XDG_STATE_HOME"]) / "gh-dash-codex-pr-review"
        identity = "repo-6-friend-6-target-pr-7-review"
        return state / "worktrees" / identity, state / "contexts" / identity

    def run_pr_review(self, repo, route, **overrides):
        self.log.write_text("")
        return self.run_script(self.bundle / "scripts/integrations/gh-dash/gh-dash-codex-pr-review.sh",
                               "friend/target", "7", cwd=repo, env=dict(route, **overrides))

    def assert_terminal_only_review(self, repo, worktree):
        # Only reads reach GitHub, and neither checkout is changed.
        self.assertEqual({tuple(c["args"][:2]) for c in self.calls("gh")}, {("repo", "view"), ("pr", "view")})
        for args in (c["args"] for c in self.calls("git")):
            self.assertFalse({"push", "commit", "merge", "rebase", "reset", "checkout"} & set(args), args)
        self.assertEqual(subprocess.run([REAL_GIT, "-C", str(worktree), "status", "--porcelain", "--untracked-files=all"],
                                        capture_output=True, text=True, check=True).stdout, "")
        self.assertEqual((repo / "source.txt").read_text(), "committed content\n")
        self.assertFalse((repo / "reviewed.txt").exists())

    def test_pr_review_starts_each_harness_in_its_native_read_only_mode(self):
        repo, git = self.source_repo()
        route = self.pr_environment(repo, git, MOCK_CODEX_VERSION="0.166.0")
        worktree, context = self.pr_review_paths()
        # The reviewer is independent of a broken shared issue-agent setting and of issue profiles.
        self.save_issue_agent("invalid")
        codex = ["--ask-for-approval", "never", "--strict-config", "--cd", str(worktree),
                 "--config", 'default_permissions="gh_dash_pr_review"',
                 "--config", 'permissions.gh_dash_pr_review={extends=":read-only"}']
        cases = (
            ("codex", None, codex),
            ("codex", {"agent": "codex", "model": "gpt-test-fast", "effort": "high", "fast": True},
             [*codex, "--model", "gpt-test-fast", "--config", 'model_reasoning_effort="high"',
              "--config", 'service_tier="fast"', "--config", "features.fast_mode=true"]),
            ("claude", {"agent": "claude", "model": "opus", "effort": "high"},
             ["--permission-mode", "plan", "--setting-sources", "user", "--add-dir", str(context), "--model", "opus",
              "--effort", "high"]),
            ("cursor", {"agent": "cursor", "model": "gpt-5"}, ["--mode", "ask", "--add-dir", str(context), "--model", "gpt-5"]),
        )
        command = {"codex": "codex", "claude": "claude", "cursor": "cursor-agent"}
        for kind, profile, native in cases:
            with self.subTest(kind=kind, profile=profile):
                self.profiles_file({"issue-implement": {"agent": "claude", "model": "opus"},
                                    **({"pr-review": profile} if profile else {})})
                result = self.run_pr_review(repo, route)
                self.assert_success(result)
                start = self.herdr_calls("agent", "start")
                self.assertEqual(len(start), 1)
                self.assertEqual(start[0][3:10], ["--kind", kind, "--pane", "pr-pane", "--timeout", "30000", "--"])
                # Native read-only options come first; only that CLI's saved model/effort options follow.
                self.assertEqual(start[0][10:], native)
                self.assertTrue([c for c in self.calls(command[kind]) if c["args"] == ["--help"]],
                                "a fresh reviewer's read-only mode is checked against the installed CLI")
                for other in set(command.values()) - {command[kind]}:
                    self.assertFalse(self.calls(other), other)
                # The whole merge-base diff is readable outside the worktree, even without a shell.
                diff_path = context / ("pr-" + route["MOCK_PR_BASE"] + "-" + route["MOCK_PR_HEAD"] + ".diff")
                diff = diff_path.read_text()
                self.assertIn("reviewed.txt | 1 +", diff)
                self.assertIn("+reviewed change", diff)
                self.assertNotIn("source.txt", diff)
                self.assertEqual(stat.S_IMODE(context.stat().st_mode), 0o700)
                prompts = self.herdr_calls("agent", "prompt")
                self.assertEqual(len(prompts), 1)
                prompt = prompts[0][3]
                self.assertIn("\n" + str(diff_path) + "\n", prompt)
                self.assertIn("detached at the PR head " + route["MOCK_PR_HEAD"], prompt)
                self.assertIn("merge base " + route["MOCK_PR_BASE"], prompt)
                for rule in ("report your findings only here, in this terminal", "severity and a file/line reference",
                             "say explicitly that there are no actionable findings", "Do not write to GitHub",
                             "do not modify, create, or delete files"):
                    self.assertIn(rule, prompt)
                for removed in ("<!-- gh-dash-codex-pr-review -->", "ready for review", "publish"):
                    self.assertNotIn(removed, prompt)
                self.assertIn("read-only " + {"codex": "Codex", "claude": "Claude Code", "cursor": "Cursor"}[kind]
                              + " reviewer; its findings appear in its pane.", self.notifications()[-1])
                self.assert_terminal_only_review(repo, worktree)
                # Close the reviewer and its worktree before the next harness.
                (self.mock / "pr-workflow.json").unlink()
                git("worktree", "remove", "--force", str(worktree))

    def test_pr_review_reuses_a_live_reviewer_with_its_original_harness(self):
        repo, git = self.source_repo()
        route = self.pr_environment(repo, git)
        worktree, _ = self.pr_review_paths()
        self.profiles_file({"pr-review": {"agent": "claude"}})
        self.assert_success(self.run_pr_review(repo, route))
        self.assertEqual(self.herdr_calls("agent", "start")[0][4], "claude")
        # A changed selection never duplicates or replaces the live reviewer; idle, finished, or working
        # reviewers get the review prompt again, as before.
        self.profiles_file({"pr-review": {"agent": "cursor", "model": "gpt-5"}})
        for status in ("idle", "done", "working"):
            with self.subTest(status=status):
                result = self.run_pr_review(repo, route, MOCK_AGENT_STATUS=status)
                self.assert_success(result)
                self.assertFalse(self.herdr_calls("agent", "start"))
                self.assertEqual([args[:3] for args in self.herdr_calls("agent", "prompt")],
                                 [["agent", "prompt", "pr-pane"]])
                self.assertIn("exact existing Claude Code reviewer", self.notifications()[-1])
                self.assertNotIn("exact read-only", self.notifications()[-1])
                self.assertIn("Kept the existing Claude Code reviewer with its original options; the Cursor setting "
                              "applies once it is closed", self.notifications()[-1])
                self.assertIn("it may not be read-only", self.notifications()[-1])
                # Saved options are not even read for a retained reviewer.
                self.assertFalse(self.calls("cursor-agent") + self.calls("claude"))
                self.assert_terminal_only_review(repo, worktree)
        # A blocked reviewer may be waiting on its own plan or trust dialog: it is focused, never typed into.
        for status in ("blocked", "unexpected-status"):
            with self.subTest(status=status):
                result = self.run_pr_review(repo, route, MOCK_AGENT_STATUS=status)
                self.assert_success(result)
                self.assertFalse(self.herdr_calls("agent", "prompt") or self.herdr_calls("agent", "start"))
                self.assertEqual(self.herdr_calls("agent", "focus"), [["agent", "focus", "pr-pane"]])
                self.assertIn("prompt not sent", self.notifications()[-1])
        # Detection must cover the retained reviewer, not the new selection.
        result = self.run_pr_review(repo, route, MOCK_MANIFEST="claude")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("does not have an active Claude Code detection manifest", result.stderr)
        self.assertFalse(self.herdr_calls("agent", "prompt") or self.herdr_calls("agent", "focus"))
        self.assert_success(self.run_pr_review(repo, route, MOCK_MANIFEST="cursor"))
        # The same harness with saved options is reused with a notice.
        self.profiles_file({"pr-review": {"agent": "claude", "model": "opus"}})
        self.assert_success(self.run_pr_review(repo, route))
        self.assertFalse(self.herdr_calls("agent", "start"))
        self.assertIn("Reused the existing reviewer with its original options", self.notifications()[-1])
        self.assertIn("it may not be read-only", self.notifications()[-1])

    def test_pr_review_warns_that_a_reused_default_reviewer_may_not_be_read_only(self):
        repo, git = self.source_repo()
        route = self.pr_environment(repo, git)
        worktree, _ = self.pr_review_paths()
        # No mf-config selection: the default Codex reviewer starts read-only, as it reports.
        self.assert_success(self.run_pr_review(repo, route))
        self.assertEqual(self.herdr_calls("agent", "start")[0][4], "codex")
        self.assertIn("exact read-only Codex reviewer", self.notifications()[-1])
        self.assertNotIn("may not be read-only", self.notifications()[-1])
        # Reused with the same default selection, its launch options cannot be verified: warn, never restart.
        result = self.run_pr_review(repo, route)
        self.assert_success(result)
        self.assertFalse(self.herdr_calls("agent", "start"))
        self.assertEqual([args[:3] for args in self.herdr_calls("agent", "prompt")], [["agent", "prompt", "pr-pane"]])
        notice = self.notifications()[-1]
        self.assertIn("exact existing Codex reviewer", notice)
        self.assertNotIn("exact read-only", notice)
        self.assertIn("Reused the existing reviewer with its original options. WARNING: Herdr does not report those "
                      "options, so its read-only permissions cannot be verified and it may not be read-only. Exit it "
                      "in its pane, then press I again to start a fresh reviewer with the configured read-only options.",
                      notice)
        self.assertIn("its read-only permissions cannot be verified", result.stderr)
        self.assert_terminal_only_review(repo, worktree)

    def advance_pr_head(self, repo, git, route, files, links=()):
        # The fixture PR head plus FILES (and symbolic LINKS) becomes the PR's new head.
        git("checkout", "-q", "--detach", route["MOCK_PR_HEAD"])
        for name, content in files.items():
            (repo / name).parent.mkdir(parents=True, exist_ok=True)
            (repo / name).write_text(content)
            git("add", name)
        for name, target in links:
            (repo / name).parent.mkdir(parents=True, exist_ok=True)
            (repo / name).symlink_to(target)
            git("add", name)
        git("commit", "-q", "-m", "PR update")
        head = git("rev-parse", "HEAD")
        git("checkout", "-q", "feature/friend")
        git("update-ref", "refs/pull/7/head", head)
        return dict(route, MOCK_PR_HEAD=head)

    def test_pr_review_keeps_each_prompted_diff_when_the_pr_advances(self):
        repo, git = self.source_repo()
        route = self.pr_environment(repo, git)
        worktree, context = self.pr_review_paths()
        self.assert_success(self.run_pr_review(repo, route))
        first = context / ("pr-" + route["MOCK_PR_BASE"] + "-" + route["MOCK_PR_HEAD"] + ".diff")
        self.assertIn("\n" + str(first) + "\n", self.herdr_calls("agent", "prompt")[0][3])
        first_diff = first.read_text()
        # The PR advances to head B while the reviewer still works on head A's prompt; the same reviewer and the
        # refreshed worktree get head B's diff in a new file, and head A's prompt keeps naming its unchanged diff.
        advanced = self.advance_pr_head(repo, git, route, {"reviewed.txt": "reviewed change\nsecond change\n"})
        self.assert_success(self.run_pr_review(repo, advanced, MOCK_AGENT_STATUS="working"))
        self.assertFalse(self.herdr_calls("agent", "start"))
        second = context / ("pr-" + route["MOCK_PR_BASE"] + "-" + advanced["MOCK_PR_HEAD"] + ".diff")
        self.assertIn("\n" + str(second) + "\n", self.herdr_calls("agent", "prompt")[0][3])
        self.assertEqual(git("-C", str(worktree), "rev-parse", "HEAD"), advanced["MOCK_PR_HEAD"])
        self.assertEqual(first.read_text(), first_diff)
        self.assertNotIn("+second change", first_diff)
        self.assertIn("+second change", second.read_text())
        self.assertEqual(sorted(path.name for path in context.iterdir()), sorted([first.name, second.name]))
        # Prompting the same head again reuses its diff file as is.
        identity = second.stat().st_ino
        self.assert_success(self.run_pr_review(repo, advanced, MOCK_AGENT_STATUS="idle"))
        self.assertEqual(second.stat().st_ino, identity)
        # Once that reviewer has exited, a fresh one removes the obsolete diffs, including a legacy pr.diff.
        (context / "pr.diff").write_text("legacy\n")
        state_file = self.mock / "pr-workflow.json"
        state = json.loads(state_file.read_text())
        del state["alias"]
        state_file.write_text(json.dumps(state))
        self.assert_success(self.run_pr_review(repo, advanced))
        self.assertEqual(len(self.herdr_calls("agent", "start")), 1)
        self.assertEqual([path.name for path in context.iterdir()], [second.name])
        self.assert_terminal_only_review(repo, worktree)

    def test_codex_reviewer_refuses_a_pr_head_with_executable_project_codex_config(self):
        # Codex loads a trusted worktree's .codex/config.toml (MCP servers it starts as the user at launch) and
        # .codex/rules (allow rules run outside the sandbox), and a linked worktree inherits the main checkout's
        # trust. Such a PR head never gets a Codex reviewer started or prompted; other .codex content is fine.
        repo, git = self.source_repo()
        route = self.pr_environment(repo, git, MOCK_CODEX_VERSION="0.166.0")
        worktree, _ = self.pr_review_paths()
        mcp = '[mcp_servers.pr]\ncommand = "touch"\nargs = ["pwned"]\n'
        rules = 'prefix_rule(pattern = ["touch"], decision = "allow")\n'
        hooks = json.dumps({"hooks": {"SessionStart": [{"hooks": [{"type": "command", "command": "touch pwned"}]}]}})
        for files, links, refused in (({".codex/config.toml": mcp}, (), ".codex/config.toml"),
                                      ({".codex/rules/default.rules": rules}, (), ".codex/rules"),
                                      ({".codex/hooks.json": hooks}, (), ".codex/hooks.json"),
                                      ({".codex/config.toml": "", ".codex/rules/default.rules": rules}, (),
                                       ".codex/config.toml, .codex/rules"),
                                      ({"settings/skills/review/SKILL.md": "Review.\n"}, ((".codex", "settings"),),
                                       ".codex (symbolic link)"),
                                      ({"settings/notes.md": "Notes.\n"}, ((".codex/config.toml", "../settings/notes.md"),),
                                       ".codex/config.toml")):
            with self.subTest(refused=refused):
                result = self.run_pr_review(repo, self.advance_pr_head(repo, git, route, files, links))
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("this PR defines project Codex configuration that Codex would load as you once the "
                              "repository is trusted (" + refused + ")", result.stderr)
                self.assertIn("the Codex reviewer was not started or prompted", self.notifications()[-1])
                self.assertFalse(self.herdr_calls("agent", "start") or self.herdr_calls("agent", "prompt"))
                self.assertFalse(self.calls("codex"))
                self.assert_terminal_only_review(repo, worktree)
                self.assertFalse((worktree / "pwned").exists())
        # Skills and other .codex content run no code by themselves: the Codex reviewer starts as before.
        harmless = self.advance_pr_head(repo, git, route, {".codex/skills/review/SKILL.md": "Review carefully.\n",
                                                           ".codex/README.md": "Project notes.\n"})
        self.assert_success(self.run_pr_review(repo, harmless))
        self.assertEqual(self.herdr_calls("agent", "start")[0][4:5] + self.herdr_calls("agent", "start")[0][10:14],
                         ["codex", "--ask-for-approval", "never", "--strict-config", "--cd"])
        # A live Codex reviewer is not prompted once the PR head adds project configuration.
        result = self.run_pr_review(repo, self.advance_pr_head(repo, git, route, {".codex/config.toml": mcp}))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("(.codex/config.toml)", result.stderr)
        self.assertFalse(self.herdr_calls("agent", "start") or self.herdr_calls("agent", "prompt"))
        # Claude Code loads only user settings, so it reviews the same head.
        (self.mock / "pr-workflow.json").unlink()
        git("worktree", "remove", "--force", str(worktree))
        self.profiles_file({"pr-review": {"agent": "claude"}})
        self.assert_success(self.run_pr_review(repo, self.advance_pr_head(repo, git, route, {".codex/config.toml": mcp})))
        self.assertEqual(len(self.herdr_calls("agent", "prompt")), 1)

    def test_pr_review_refuses_a_cli_without_its_interactive_read_only_mode(self):
        repo, git = self.source_repo()
        route = self.pr_environment(repo, git)
        for kind, help_fixture, missing in (("claude", "no-plan", "--permission-mode plan"),
                                            # Without it, the PR's project hooks would run when Claude starts.
                                            ("claude", "no-setting-sources", "--setting-sources"),
                                            ("claude", "old", "--permission-mode, --setting-sources, --add-dir"),
                                            ("cursor", "no-ask", "--mode ask"),
                                            ("codex", "old", "--ask-for-approval, --strict-config, --config, --cd")):
            with self.subTest(kind=kind, help=help_fixture):
                self.profiles_file({"pr-review": {"agent": kind}} if kind != "codex" else {})
                result = self.run_pr_review(repo, route, MOCK_AGENT_HELP=help_fixture)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("does not offer " + missing + ", needed for the interactive read-only PR reviewer",
                              result.stderr)
                self.assertIn("agent not started and prompt not sent", result.stderr)
                self.assertFalse(self.herdr_calls("agent", "start") or self.herdr_calls("agent", "prompt"))

    def test_cursor_reviewer_refuses_a_pr_head_with_project_hooks(self):
        # Cursor CLI cannot skip project hooks: once trusted, it runs the worktree's .cursor/hooks.json and imported
        # Claude project hooks as the user. Such a PR head never gets a Cursor reviewer started or prompted.
        repo, git = self.source_repo()
        route = self.pr_environment(repo, git)
        worktree, _ = self.pr_review_paths()

        def pr_head(files):
            # The fixture PR head plus FILES becomes the PR's new head.
            git("checkout", "-q", "--detach", route["MOCK_PR_HEAD"])
            for name, content in files.items():
                (repo / name).parent.mkdir(exist_ok=True)
                (repo / name).write_text(content)
                git("add", name)
            git("commit", "-q", "-m", "PR update")
            head = git("rev-parse", "HEAD")
            git("checkout", "-q", "feature/friend")
            git("update-ref", "refs/pull/7/head", head)
            return dict(route, MOCK_PR_HEAD=head)

        cursor_hooks = json.dumps({"version": 1, "hooks": {"sessionStart": [{"command": "touch pwned"}]}})
        claude_hooks = json.dumps({"hooks": {"SessionStart": [
            {"matcher": "", "hooks": [{"type": "command", "command": "touch pwned"}]}]}})
        self.profiles_file({"pr-review": {"agent": "cursor"}})
        for name, content in ((".cursor/hooks.json", cursor_hooks), (".claude/settings.json", claude_hooks),
                              (".claude/settings.local.json", claude_hooks),
                              # Cursor reads JSONC hooks; a file jq cannot prove hook-free is refused too.
                              (".cursor/hooks.json", "// comment\n" + cursor_hooks)):
            with self.subTest(file=name, content=content):
                result = self.run_pr_review(repo, pr_head({name: content}))
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("this PR defines project hooks that Cursor would run as you (" + name + ")",
                              result.stderr)
                self.assertIn("the Cursor reviewer was not started or prompted", self.notifications()[-1])
                self.assertFalse(self.herdr_calls("agent", "start") or self.herdr_calls("agent", "prompt"))
                self.assertFalse(self.calls("cursor-agent"))
                self.assert_terminal_only_review(repo, worktree)
        # Hook-free settings files are harmless: the Cursor reviewer starts as before.
        self.assert_success(self.run_pr_review(repo, pr_head({
            ".cursor/hooks.json": json.dumps({"version": 1, "hooks": {}}),
            ".claude/settings.json": json.dumps({"permissions": {"allow": ["Read"]}}),
            ".claude/settings.local.json": json.dumps({"hooks": None})})))
        self.assertEqual(self.herdr_calls("agent", "start")[0][4:5] + self.herdr_calls("agent", "start")[0][10:12],
                         ["cursor", "--mode", "ask"])
        # A live Cursor reviewer is not prompted once the PR head adds hooks.
        hooked = pr_head({".cursor/hooks.json": cursor_hooks, ".claude/settings.json": claude_hooks})
        result = self.run_pr_review(repo, hooked)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("(.cursor/hooks.json, .claude/settings.json)", result.stderr)
        self.assertFalse(self.herdr_calls("agent", "start") or self.herdr_calls("agent", "prompt"))
        # Claude Code loads only user settings, so it reviews the same head.
        (self.mock / "pr-workflow.json").unlink()
        git("worktree", "remove", "--force", str(worktree))
        self.profiles_file({"pr-review": {"agent": "claude"}})
        self.assert_success(self.run_pr_review(repo, hooked))
        self.assertEqual(self.herdr_calls("agent", "start")[0][10:14],
                         ["--permission-mode", "plan", "--setting-sources", "user"])
        self.assertEqual(len(self.herdr_calls("agent", "prompt")), 1)

    def test_setup_installs_every_harness_and_keeps_per_key_selections(self):
        self.save_issue_agent("codex")
        path = self.profiles_file({"issue-prepare": {"agent": "claude", "effort": "high"},
                                   "issue-implement": {"agent": "claude"}})
        saved = path.read_bytes()
        for name in ("claude", "cursor-agent"):
            (self.mock / name).unlink()
        result = self.interactive_setup("y", MOCK_INTEGRATION="pending")
        self.assert_success(result)
        self.assertIn("Issues i preparer: claude; Issues I implementer: claude", result.stdout)
        urls = [argument for call in self.calls("curl") for argument in call["args"] if argument.startswith("https://")]
        # Every agent CLI is installed, but only the gh-dash roles' agents (Claude Code issues, Codex reviews)
        # log in and get a Herdr integration; the unused Cursor stays logged out.
        self.assertIn("https://claude.ai/install.sh", urls)
        self.assertIn("https://cursor.com/install", urls)
        self.assertNotIn(["login"], [c["args"] for c in self.calls("cursor-agent")])
        installs = [args for args in self.herdr_calls("integration", "install") if "--help" not in args]
        self.assertEqual(installs, [["integration", "install", "claude"], ["integration", "install", "codex"]])
        self.assertIn("OK: Issues i preparer: Claude Code (mf-config selection)", result.stdout)
        self.assertEqual(path.read_bytes(), saved)
        # ISSUE_AGENT stays the shared compatibility path; it never overwrites a per-key selection.
        self.env["PATH"] = str(self.wrapper.parent) + os.pathsep + str(self.mock)
        result = self.setup(ISSUE_AGENT="codex")
        self.assert_success(result)
        self.assertEqual(path.read_bytes(), saved)
        self.assertEqual(self.mf_config("agent", "issue-implement").stdout, "claude\noverride\n")
        # The shared agent still applies to a key without its own selection.
        (self.mock / "cursor-agent").symlink_to("mock-cli")
        self.profiles_file({"issue-prepare": {"agent": "claude"}})
        self.assert_success(self.setup(ISSUE_AGENT="cursor"))
        self.assertEqual(self.mf_config("agent", "issue-implement").stdout, "cursor\nshared\n")
        self.assertEqual(self.mf_config("agent", "issue-prepare").stdout, "claude\noverride\n")
        doctor = self.run_script(self.installed / "scripts/doctor.sh", env={"MOCK_CURSOR_AUTH": "pending"})
        self.assertNotEqual(doctor.returncode, 0)
        self.assertIn("FAIL: Cursor authentication/setup pending", doctor.stdout)
        self.assertIn("OK: Issues I implementer: Cursor (shared issue agent)", doctor.stdout)
        path.write_text("{broken")
        doctor = self.run_script(self.installed / "scripts/doctor.sh")
        self.assertNotEqual(doctor.returncode, 0)
        self.assertIn("FAIL: mf-config agent profiles unreadable", doctor.stdout)
        result = self.setup()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("cannot read the mf-config agent profiles", result.stderr)
        self.assertEqual(path.read_text(), "{broken")

    def test_managed_mf_config_launcher_never_replaces_another_command(self):
        self.install()
        launcher = self.wrapper.parent / "mf-config"
        content = launcher.read_bytes()
        self.assertIn(b"# mini-factory managed launcher v1", content)
        self.assertTrue(content.endswith(b'/mini-factory/bin/mf-config "$@"\n'))
        self.assert_success(self.run_script(launcher, "show"))
        self.assert_success(self.setup())
        self.assertEqual(launcher.read_bytes(), content)
        doctor = self.run_script(self.installed / "scripts/doctor.sh")
        self.assert_success(doctor)
        self.assertIn("OK: mf-config launcher resolves on PATH", doctor.stdout)
        # An unrelated file at the launcher path, or another mf-config on PATH, is left alone.
        launcher.write_text("#!/bin/sh\necho unrelated\n")
        result = self.setup()
        self.assert_success(result)
        self.assertEqual(launcher.read_text(), "#!/bin/sh\necho unrelated\n")
        self.assertIn("Run " + str(self.bundle / "bin/mf-config") + " instead.", result.stdout)
        doctor = self.run_script(self.installed / "scripts/doctor.sh")
        self.assert_success(doctor)
        self.assertIn("NOTE: optional mf-config launcher is not on PATH", doctor.stdout)
        launcher.unlink()
        other = self.mock / "mf-config"
        other.write_text("#!/bin/sh\necho other\n")
        other.chmod(0o755)
        result = self.setup()
        self.assert_success(result)
        self.assertFalse(launcher.exists())
        self.assertEqual(other.read_text(), "#!/bin/sh\necho other\n")
        self.assertIn("another mf-config command is on PATH", result.stdout)
        # The repository-local fallback still works.
        self.assert_success(self.mf_config("show"))
        self.assert_no_actions()

    def test_mf_config_launcher_preserves_destination_created_during_publication(self):
        self.install()
        launcher = self.wrapper.parent / "mf-config"
        real_mv = shutil.which("mv", path=REAL_PATH)
        # Insert the collision at publication itself, after setup's existence checks.
        shim = "#!" + sys.executable + "\n" + '''import os, pathlib, sys
destination = pathlib.Path(os.environ["RACE_LAUNCHER"])
args = sys.argv[1:]
if args and args[-1] == str(destination):
    kind = os.environ["RACE_KIND"]
    if kind == "file":
        destination.write_text("unrelated command\\n")
    elif kind == "directory":
        destination.mkdir()
    else:
        destination.symlink_to("unrelated-missing-target")
executable = REAL_MV if pathlib.Path(sys.argv[0]).name == "mv" else REAL_PYTHON
os.execv(executable, [executable, *args])
'''.replace("REAL_MV", repr(real_mv)).replace("REAL_PYTHON", repr(sys.executable))
        for name in ("mv", "python3"):
            (self.mock / name).unlink()
            (self.mock / name).write_text(shim)
            (self.mock / name).chmod(0o755)
        for kind in ("file", "directory", "symlink"):
            with self.subTest(kind=kind):
                launcher.unlink()
                result = self.setup(RACE_LAUNCHER=str(launcher), RACE_KIND=kind)
                self.assert_success(result)
                self.assertIn("mf-config appeared during setup", result.stdout)
                if kind == "file":
                    self.assertEqual(launcher.read_text(), "unrelated command\n")
                elif kind == "directory":
                    self.assertTrue(launcher.is_dir())
                    self.assertEqual(list(launcher.iterdir()), [])
                    launcher.rmdir()
                    launcher.touch()
                else:
                    self.assertTrue(launcher.is_symlink())
                    self.assertEqual(os.readlink(launcher), "unrelated-missing-target")
                self.assertEqual(list(launcher.parent.glob(".mini-factory-mf-config.*")), [])

    def test_gum_is_installed_or_repaired_only_with_consent_and_checked_by_doctor(self):
        self.install()
        doctor = self.installed / "scripts/doctor.sh"
        (self.mock / "gum").unlink()
        result = self.run_script(doctor)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("FAIL: gum missing; run make setup", result.stdout)
        self.assertFalse(self.calls("brew"), "doctor must stay read-only")
        self.assertNotEqual(self.setup().returncode, 0)
        self.assertFalse([c for c in self.calls("brew") if "install" in c["args"]])
        self.assertNotEqual(self.interactive_setup("n").returncode, 0)
        self.assertFalse([c for c in self.calls("brew") if "install" in c["args"]])
        result = self.interactive_setup("y")
        self.assert_success(result)
        self.assertIn("brew install gum", result.stdout)
        self.assertIn(["install", "gum"], [c["args"] for c in self.calls("brew")])
        self.assertIn("OK: gum available", result.stdout)
        # An installed but unrunnable Homebrew Gum is repaired with reinstall, not left broken.
        (self.mock / "gum-repaired").unlink()
        self.log.write_text("")
        result = self.interactive_setup("y", MOCK_GUM="broken", MOCK_BREW_LISTED="gum")
        self.assert_success(result)
        self.assertEqual([c["args"] for c in self.calls("brew") if c["args"][:1] in (["install"], ["reinstall"])],
                         [["reinstall", "gum"]])

    def test_mocked_ubuntu_gum_from_archive_or_charm_repository(self):
        if not Path("/etc/os-release").exists() or not re.search(r'^ID=["\']?ubuntu', Path("/etc/os-release").read_text(), re.M):
            self.skipTest("Ubuntu detection reads the native os-release file")
        for source in ("archive", "charm"):
            with self.subTest(source=source):
                if (self.mock / "gum").exists():
                    (self.mock / "gum").unlink()
                self.log.write_text("")
                result = self.interactive_setup("y", MOCK_OS="Linux", MOCK_ARCH="x86_64",
                                                **({"MOCK_APT_GUM": "archive"} if source == "archive" else {}))
                self.assert_success(result)
                self.assertTrue((self.mock / "gum").exists())
                actions = [c["args"] for c in self.calls("sudo")]
                self.assertEqual(actions[-1], ["apt-get", "install", "-y", "--no-install-recommends", "gum"])
                charm = [args for args in actions if "/etc/apt/sources.list.d/charm.list" in args]
                downloads = [c["args"] for c in self.calls("curl") if "https://repo.charm.sh/apt/gpg.key" in c["args"]]
                if source == "archive":
                    self.assertFalse(charm or downloads)
                else:
                    self.assertTrue(charm and downloads)
                    self.assertIn(["apt-get", "update"], actions)
                self.assert_no_actions(allow_onboarding=True)

    def test_mocked_ubuntu_installed_only_gum_is_repaired_from_charm_repository(self):
        if not Path("/etc/os-release").exists() or not re.search(r'^ID=["\']?ubuntu', Path("/etc/os-release").read_text(), re.M):
            self.skipTest("Ubuntu detection reads the native os-release file")
        # A broken gum whose repository was removed has no archive version to reinstall from.
        if (self.mock / "gum-repaired").exists():
            (self.mock / "gum-repaired").unlink()
        self.log.write_text("")
        result = self.interactive_setup("y", MOCK_OS="Linux", MOCK_ARCH="x86_64", MOCK_GUM="broken")
        self.assert_success(result)
        self.assertIn("is not in your configured Ubuntu archive", result.stdout)
        actions = [c["args"] for c in self.calls("sudo")]
        self.assertTrue([args for args in actions if "/etc/apt/sources.list.d/charm.list" in args])
        self.assertIn(["apt-get", "update"], actions)
        self.assertEqual(actions[-1], ["apt-get", "install", "-y", "--reinstall", "--no-install-recommends", "gum"])
        self.assert_no_actions(allow_onboarding=True)

    def test_setup_confirms_with_gum_defaulting_to_no_and_never_assumes_consent(self):
        setup = [str(self.bundle / "scripts/setup.sh")]
        (self.mock / "codex").unlink()
        # Enter takes Gum's default, No; n declines too. Only the pending installer is reported.
        for keys in (b"\n", b"n\n"):
            with self.subTest(keys=keys):
                self.log.write_text("")
                result = self.run_in_terminal(setup, self.env, keys)
                self.assertNotEqual(result.returncode, 0, result.stdout)
                self.assertIn("Declined; existing configuration was preserved.", result.stdout)
                self.assertIn("codex installation pending", result.stdout)
                self.assertEqual(self.gum_confirms(), [["confirm", "--default=false", "Proceed?"]])
                self.assertNotIn("[y/N]", result.stdout)
                self.assertFalse(self.calls("curl"))
        # Cancelling Gum (ctrl+c) stops setup without the change.
        self.log.write_text("")
        result = self.run_in_terminal(setup, self.env, b"<cancel>\n")
        self.assertEqual(result.returncode, 130, result.stdout)
        self.assertIn("Cancelled; setup stopped without this change.", result.stdout)
        self.assertFalse(self.calls("curl"))
        self.assertFalse(self.installed.exists())
        # Without a terminal, Gum is never asked and nothing is approved.
        self.log.write_text("")
        result = self.setup()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Consent pending: rerun make setup in an interactive terminal. No approval was assumed.",
                      result.stdout)
        self.assertFalse(self.gum_confirms())
        self.assertFalse(self.calls("curl"))
        # Yes runs the installer; every confirmation used Gum.
        self.log.write_text("")
        result = self.interactive_setup("y")
        self.assert_success(result)
        self.assertTrue((self.wrapper.parent / "codex").is_file())
        self.assertIn(["confirm", "--default=false", "Proceed?"], self.gum_confirms())
        self.assertNotIn("[y/N]", result.stdout)
        self.assert_no_actions(allow_onboarding=True)

    def test_missing_or_broken_gum_is_bootstrapped_with_a_plain_prompt_that_assumes_nothing(self):
        setup = [str(self.bundle / "scripts/setup.sh")]
        (self.mock / "gum").unlink()
        (self.mock / "codex").unlink()
        # EOF, Enter, or n at the plain bootstrap prompt installs nothing.
        for keys in (b"\x04", b"\n", b"n\n"):
            with self.subTest(keys=keys):
                self.log.write_text("")
                result = self.run_in_terminal(setup, self.env, keys)
                self.assertNotEqual(result.returncode, 0, result.stdout)
                self.assertIn("brew install gum", result.stdout)
                self.assertIn("Proceed? [y/N]", result.stdout)
                self.assertIn("dependencies pending: gum", result.stdout)
                self.assertFalse([c for c in self.calls("brew") if "install" in c["args"]])
                self.assertFalse(self.calls("curl"))
        # A broken Gum cannot ask either: declining its repair changes nothing and asks Gum nothing.
        self.log.write_text("")
        (self.mock / "gum").symlink_to("mock-cli")
        result = self.run_in_terminal(setup, dict(self.env, MOCK_GUM="broken", MOCK_BREW_LISTED="gum"), b"n\n")
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn("brew reinstall gum", result.stdout)
        self.assertFalse([c for c in self.calls("brew") if "reinstall" in c["args"]])
        self.assertFalse(self.gum_confirms())
        (self.mock / "gum").unlink()
        # Only Gum's own installation uses the plain prompt; the next confirmation (Codex's installer) uses Gum.
        self.log.write_text("")
        result = self.interactive_setup("y")
        self.assert_success(result)
        self.assertEqual(result.stdout.count("Proceed? [y/N]"), 1, result.stdout)
        self.assertIn(["install", "gum"], [c["args"] for c in self.calls("brew")])
        self.assertIn(["confirm", "--default=false", "Proceed?"], self.gum_confirms())
        self.assertTrue((self.wrapper.parent / "codex").is_file())
        self.assert_no_actions(allow_onboarding=True)

    def test_mocked_ubuntu_installs_gum_before_github_cli_so_later_confirmations_use_it(self):
        if not Path("/etc/os-release").exists() or not re.search(r'^ID=["\']?ubuntu', Path("/etc/os-release").read_text(), re.M):
            self.skipTest("Ubuntu detection reads the native os-release file")
        (self.mock / "gum").unlink()
        (self.mock / "gh").unlink()
        result = self.interactive_setup("y", MOCK_OS="Linux", MOCK_ARCH="x86_64", MOCK_APT_GUM="archive")
        self.assert_success(result)
        actions = [c["args"] for c in self.calls("sudo")]
        self.assertLess(actions.index(["apt-get", "install", "-y", "--no-install-recommends", "gum"]),
                        actions.index(["apt-get", "install", "-y", "--no-install-recommends", "gh"]))
        # Gum's own installation is the last plain prompt; GitHub CLI's installation is confirmed with Gum.
        after_gum = result.stdout[result.stdout.index("Gum provides"):]
        self.assertEqual(after_gum.count("Proceed? [y/N]"), 1, result.stdout)
        self.assertIn(["confirm", "--default=false", "Proceed?"], self.gum_confirms())
        self.assert_no_actions()


    # nm-config: the No-Mistakes global config editor for the clone file linked from NM_HOME.

    def nm_link(self, content=None):
        """Link NM_HOME/config.yaml to the clone's tracked config, as make setup does."""
        source = self.bundle / "no-mistakes/config.yaml"
        if content is not None:
            source.write_text(content)
        link = self.home / ".no-mistakes/config.yaml"
        link.parent.mkdir(parents=True, exist_ok=True)
        if link.is_symlink() or link.exists():
            link.unlink()
        link.symlink_to(source)
        return source

    def nm_config(self, *args, **env):
        return self.run_script(self.bundle / "bin/nm-config", *args, env=env)

    def edit_nm(self, *answers, tool=None, **overrides):
        answers_file = self.root / "gum answers.json"
        answers_file.write_text(json.dumps(list(answers)))
        self.log.write_text("")
        result = self.run_in_terminal([str(tool or self.bundle / "bin/nm-config")],
                                      dict(self.env, MOCK_GUM_ANSWERS=str(answers_file), **overrides))
        return result, json.loads(answers_file.read_text())

    def prompt(self, header_start):
        return next(prompt for prompt in self.gum_prompts() if prompt[1].startswith(header_start))

    def test_nm_config_show_reports_defaults_roles_and_native_precedence_without_a_terminal(self):
        source = self.nm_link(STABLE_DEFAULT)
        result = self.nm_config("show")
        self.assert_success(result)
        lines = result.stdout.splitlines()
        self.assertIn("No-Mistakes global config: " + str(self.home / ".no-mistakes/config.yaml") + " -> "
                      + str(source), lines)
        self.assertIn("Pipeline agent (agent): codex", lines)
        self.assertIn("  Reviewer: no override - uses the pipeline agent (codex) with its agent_config", lines)
        self.assertIn("  Fixer: no override - uses the pipeline agent (codex) with its agent_config", lines)
        self.assertIn("  Later-round reviewer: none - every round uses the reviewer", lines)
        self.assertIn("  review: 3", lines)
        self.assertIn("  test: unset - native default (3 in v1.84.0)", lines)
        self.assertIn("Fixer session reuse (session_reuse): unset - native default (true in v1.84.0)", lines)
        self.assertIn("nm-config does not read target repositories.", result.stdout)
        self.assertIn("Test, CI, and every other step", result.stdout)
        configured = ("agent: [codex, claude] # fallback order\n"
                      "agent_config:\n  codex:\n    model: gpt-5.4\n    effort: low\n"
                      "agent_args_override:\n  codex:\n    - -m\n    - o3\n    - -c\n    - service_tier=\"priority\"\n"
                      "review_agents:\n  reviewer:\n    agent: codex\n    effort: high\n"
                      "  fixer:\n    agent: claude\n    model: opus\n    effort: max\n"
                      "  fixer_after_round:\n    agent: codex\n    after_round: 2\n"
                      "auto_fix:\n  review: 4\n  ci: 2\n")
        source.write_text(configured)
        result = self.nm_config("show")
        self.assert_success(result)
        lines = result.stdout.splitlines()
        pin = " - overridden: agent_args_override.codex pins -m o3"
        self.assertIn("Pipeline agent (agent): ordered fallback list codex, claude (first available entry runs)", lines)
        self.assertIn("  Codex: model: gpt-5.4" + pin + "; effort: low", lines)
        self.assertIn("  Reviewer: Codex - model: gpt-5.4 (agent_config)" + pin + "; effort: high", lines)
        self.assertIn("  Fixer: Claude Code - model: opus; effort: max", lines)
        self.assertIn("  Later-round fixer: Codex - model: gpt-5.4 (agent_config)" + pin + "; effort: low (agent_config); "
                      "from round 3 (after_round: 2; rounds 1-2 use the fixer)", lines)
        self.assertIn('  codex: -m o3 -c service_tier="priority" - pins model', lines)
        self.assertIn("  review: 4", lines)
        self.assertEqual(source.read_text(), configured)
        # Native inheritance: empty role knobs inherit agent_config, and cursor shares acp:cursor's profile.
        source.write_text("agent: codex\n"
                          "agent_config:\n  codex:\n    model: gpt-5.4\n    effort: low\n"
                          "  cursor:\n    model: \"\"\n  acp:cursor:\n    model: gpt-5\n"
                          "review_agents:\n  reviewer:\n    agent: codex\n    model: \"\"\n    effort: \"\"\n"
                          "  fixer:\n    agent: cursor\n")
        result = self.nm_config("show")
        self.assert_success(result)
        lines = result.stdout.splitlines()
        self.assertIn("  Reviewer: Codex - model: gpt-5.4 (agent_config); effort: low (agent_config)", lines)
        self.assertIn("  Fixer: Cursor - model: gpt-5 (agent_config.acp:cursor); effort: not settable (acpx takes a "
                      "model only)", lines)
        self.assertFalse(self.calls("gum"))
        self.assertFalse(self.calls("no-mistakes"), "show stays read-only and needs no native command")
        # Editing needs a terminal; show stays available.
        result = self.nm_config()
        self.assertEqual(result.returncode, 1)
        self.assertIn("nm-config show", result.stderr)
        self.assertFalse(self.calls("gum"))

    def test_nm_config_show_treats_yaml_nulls_as_native_defaults(self):
        for value in ("", "~", "null", "Null", "NULL"):
            with self.subTest(value=value):
                config = ("agent: " + value + "\n"
                          "auto_fix:\n" + "".join("  " + step + ": " + value + "\n"
                                                   for step in ("rebase", "review", "test", "lint", "ci"))
                          + "session_reuse: " + value + "\n"
                          "review_agents:\n"
                          "  reviewer_after_round:\n    agent: codex\n    after_round: " + value + "\n"
                          "  fixer_after_round:\n    agent: claude\n    after_round: " + value + "\n")
                source = self.nm_link(config)
                result = self.nm_config("show")
                self.assert_success(result)
                lines = result.stdout.splitlines()
                self.assertIn("Pipeline agent (agent): unset - native default auto", lines)
                for step, default in (("rebase", 3), ("review", 0), ("test", 3), ("lint", 3), ("ci", 3)):
                    self.assertIn("  " + step + ": unset - native default (" + str(default) + " in v1.84.0)", lines)
                self.assertIn("Fixer session reuse (session_reuse): unset - native default (true in v1.84.0)", lines)
                for role, harness in (("reviewer", "Codex"), ("fixer", "Claude Code")):
                    self.assertIn("  Later-round " + role + ": " + harness
                                  + " - model: native default; effort: native default; from round 2"
                                  + " (after_round: 1; rounds 1-1 use the " + role + ")", lines)
                self.assertNotIn("None", result.stdout)
                self.assertEqual(source.read_bytes(), config.encode())
        source = self.nm_link("agent: codex\nauto_fix:\n  review: 0\nsession_reuse: false\n")
        result = self.nm_config("show")
        self.assert_success(result)
        self.assertIn("  review: 0", result.stdout.splitlines())
        self.assertIn("Fixer session reuse (session_reuse): false", result.stdout.splitlines())
        self.assertFalse(self.calls("gum"))
        self.assertFalse(self.calls("no-mistakes"))

    def test_nm_config_show_resolves_null_ci_to_legacy_babysit(self):
        values = (None, "", "~", "null", "Null", "NULL", "0", "2")
        for ci in values:
            for babysit in values:
                with self.subTest(ci=ci, babysit=babysit):
                    config = "agent: codex\nauto_fix:\n  review: 1\n"
                    for key, value in (("ci", ci), ("babysit", babysit)):
                        if value is not None:
                            config += "  " + key + ": " + value + "\n"
                    source = self.nm_link(config)
                    result = self.nm_config("show")
                    self.assert_success(result)
                    if ci in ("0", "2"):
                        expected = ci
                    elif babysit in ("0", "2"):
                        expected = babysit + " (legacy auto_fix.babysit)"
                    else:
                        expected = "unset - native default (3 in v1.84.0)"
                    self.assertIn("  ci: " + expected, result.stdout.splitlines())
                    self.assertEqual(source.read_bytes(), config.encode())
        self.assertFalse(self.calls("gum"))
        self.assertFalse(self.calls("no-mistakes"))

    def test_nm_config_null_numeric_settings_prefill_as_blank(self):
        for value in ("", "~", "null", "Null", "NULL"):
            with self.subTest(value=value):
                config = ("agent: codex\nauto_fix:\n"
                          + "".join("  " + step + ": " + value + "\n"
                                    for step in ("rebase", "review", "test", "lint", "ci"))
                          + "review_agents:\n"
                          "  reviewer_after_round:\n    agent: codex\n    after_round: " + value + "\n"
                          "  fixer_after_round:\n    agent: codex\n    after_round: " + value + "\n")
                source = self.nm_link(config)
                result, remaining = self.edit_nm(
                    NM_MENU["auto_fix"], "", "", "", "", "",
                    NM_MENU["reviewer_after_round"], "Codex", INHERIT_CODEX, INHERIT_CODEX, "",
                    NM_MENU["fixer_after_round"], "Codex", INHERIT_CODEX, INHERIT_CODEX, "",
                    NM_MENU["save"], "yes")
                self.assert_success(result)
                self.assertEqual(remaining, [])
                for step in ("rebase", "review", "test", "lint", "ci"):
                    self.assertEqual(self.prompt("auto_fix." + step + ":")[2], "")
                for role in ("reviewer_after_round", "fixer_after_round"):
                    self.assertEqual(self.prompt("review_agents." + role + ": after_round")[2], "")
                self.assertEqual(source.read_text(), "agent: codex\nreview_agents:\n"
                                 "  reviewer_after_round:\n    agent: codex\n"
                                 "  fixer_after_round:\n    agent: codex\n")

    def test_nm_config_edits_explicit_ci_budget_without_changing_legacy_babysit(self):
        for ci in ("0", "2", "null"):
            with self.subTest(ci=ci):
                config = "agent: codex\nauto_fix:\n  ci: " + ci + " # explicit budget\n  babysit: 5\n"
                source = self.nm_link(config)
                if ci == "null":
                    result, remaining = self.edit_nm(NM_MENU["auto_fix"], "", "", "", "", NM_MENU["save"])
                    self.assert_success(result)
                    self.assertEqual(source.read_text(), config)
                    self.assertIn("auto_fix.babysit (legacy ci) is set", result.stdout)
                    self.assertFalse([prompt for prompt in self.gum_prompts() if prompt[1].startswith("auto_fix.ci:")])
                else:
                    result, remaining = self.edit_nm(NM_MENU["auto_fix"], "", "", "", "", "4",
                                                     NM_MENU["save"], "yes")
                    self.assert_success(result)
                    self.assertIn("Native check: the installed No-Mistakes loads the edited config.", result.stdout)
                    self.assertEqual(self.prompt("auto_fix.ci:")[2], ci)
                    self.assertNotIn("rename it to ci", result.stdout)
                    self.assertEqual(source.read_text(), config.replace("ci: " + ci, "ci: 4"))
                self.assertEqual(remaining, [])

    def test_nm_config_edits_ci_budget_when_ci_and_legacy_babysit_are_null(self):
        for value in ("", "~", "null"):
            with self.subTest(value=value):
                config = "agent: codex\nauto_fix:\n  ci: " + value + "\n  babysit: " + value + "\n"
                source = self.nm_link(config)
                result, remaining = self.edit_nm(NM_MENU["auto_fix"], "", "", "", "", "4",
                                                 NM_MENU["save"], "yes")
                self.assert_success(result)
                self.assertEqual(remaining, [])
                self.assertIn("Native check: the installed No-Mistakes loads the edited config.", result.stdout)
                self.assertNotIn("rename it to ci", result.stdout)
                self.assertEqual(self.prompt("auto_fix.ci:")[2], "")
                self.assertEqual(source.read_text(), config.replace("ci: " + value, "ci: 4", 1))

    def test_nm_config_ci_prompt_says_clearing_ci_exposes_legacy_babysit(self):
        for babysit, blank in (("5", "blank = clear ci; legacy auto_fix.babysit then applies"),
                               ("~", "blank = native default 3")):
            with self.subTest(babysit=babysit):
                config = "agent: codex\nauto_fix:\n  ci: 0\n  babysit: " + babysit + "\n"
                source = self.nm_link(config)
                result, remaining = self.edit_nm(NM_MENU["auto_fix"], "", "", "", "", "", NM_MENU["save"], "yes")
                self.assert_success(result)
                self.assertEqual(remaining, [])
                self.assertIn(blank, self.prompt("auto_fix.ci:")[1])
                # Only the explicit ci is cleared; babysit is kept, so it becomes the effective CI budget.
                self.assertEqual(source.read_text(), "agent: codex\nauto_fix:\n  babysit: " + babysit + "\n")
        show = self.nm_config("show")
        self.assert_success(show)
        self.assertIn("  ci: unset - native default (3 in v1.84.0)", show.stdout.splitlines())
        source.write_text("agent: codex\nauto_fix:\n  babysit: 5\n")
        show = self.nm_config("show")
        self.assertIn("  ci: 5 (legacy auto_fix.babysit)", show.stdout.splitlines())

    def test_nm_config_recovery_requires_the_same_native_rejection(self):
        source = self.nm_link(STABLE_DEFAULT)
        result, remaining = self.edit_nm(NM_MENU["auto_fix"], "", "2", "", "", "3", NM_MENU["save"],
                                         MOCK_NM_REJECT="review: [23]")
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertEqual(remaining, [])
        self.assertIn("rejects the edited config", result.stdout)
        self.assertIn("mock rejection: review: 2", result.stdout)
        self.assertFalse([prompt for prompt in self.gum_prompts() if prompt[0] == "confirm"])
        self.assertEqual(source.read_text(), STABLE_DEFAULT)
        # The same pre-existing rejection permits a targeted recovery edit.
        result, remaining = self.edit_nm(NM_MENU["auto_fix"], "", "2", "", "", "3", NM_MENU["save"], "yes",
                                         MOCK_NM_REJECT="agent: codex")
        self.assert_success(result)
        self.assertEqual(remaining, [])
        self.assertIn("already rejected this config before the edit", result.stdout)
        self.assertEqual(source.read_text(), STABLE_DEFAULT.replace("review: 3", "review: 2"))
        # Inserting an earlier setting moves line numbers in an unchanged native schema rejection.
        config = STABLE_DEFAULT + "ci:\n  review_bot_comments: always\n"
        source.write_text(config)
        result, remaining = self.edit_nm(NM_MENU["auto_fix"], "1", "3", "", "", "3", NM_MENU["save"], "yes")
        self.assert_success(result)
        self.assertEqual(remaining, [])
        self.assertIn("already rejected this config before the edit", result.stdout)
        self.assertEqual(source.read_text(), config.replace("  ci: 3\n", "  ci: 3\n  rebase: 1\n"))
        self.assert_no_actions()

    def test_nm_config_edits_review_roles_and_budgets_and_preserves_unrelated_yaml(self):
        customized = ("agent: codex # my pipeline choice\n"
                      "auto_fix:\n  review: 1 # keep reviews short\n  ci: 3\n  document: 2\n"
                      "# personal note\n"
                      "log_level: debug\n"
                      "ci:\n  review_bot_comments: always\n  release_after_checks_pass: true\n"
                      "agent_args_override:\n  claude:\n  - --permission-mode\n  - acceptEdits\n")
        source = self.nm_link(customized)
        source.chmod(0o640)
        # A deliberately installed prerelease accepts its ci fields; nm-config neither removes nor adds them.
        newer = dict(self.codex_cache(), MOCK_NM_VERSION="v1.105.0")
        result, remaining = self.edit_nm(
            NM_MENU["reviewer"], "Codex", "gpt-test-fast", "high",
            NM_MENU["fixer"], "Claude Code", "opus", "max",
            NM_MENU["fixer_after_round"], "Codex", INHERIT_CODEX, "low", "2",
            NM_MENU["auto_fix"], "", "2", "4", "", "1",
            NM_MENU["save"], "yes", **newer)
        self.assert_success(result)
        self.assertEqual(remaining, [])
        edited = ("agent: codex # my pipeline choice\n"
                  "auto_fix:\n  review: 2 # keep reviews short\n  ci: 1\n  document: 2\n  test: 4\n"
                  "# personal note\n"
                  "log_level: debug\n"
                  "ci:\n  review_bot_comments: always\n  release_after_checks_pass: true\n"
                  "agent_args_override:\n  claude:\n  - --permission-mode\n  - acceptEdits\n"
                  "review_agents:\n"
                  "  reviewer:\n    agent: codex\n    model: gpt-test-fast\n    effort: high\n"
                  "  fixer:\n    agent: claude\n    model: opus\n    effort: max\n"
                  "  fixer_after_round:\n    agent: codex\n    effort: low\n    after_round: 2\n")
        self.assertEqual(source.read_text(), edited)
        self.assertEqual(stat.S_IMODE(source.stat().st_mode), 0o640)
        self.assertEqual(os.readlink(self.home / ".no-mistakes/config.yaml"), str(source))
        # Stable adapter levels, not each CLI's wider menu; local model metadata and inheritance stay visible.
        self.assertEqual(self.prompt("review_agents.reviewer: Codex model")[3],
                         [INHERIT_CODEX, "gpt-test-fast", "gpt-test-standard", "Custom model ID (unverified)"])
        self.assertEqual(self.prompt("review_agents.reviewer: Codex effort")[3],
                         [INHERIT_CODEX, "minimal", "low", "medium", "high"])
        self.assertEqual(self.prompt("review_agents.fixer: Claude Code effort")[3],
                         ["Inherit agent_config.claude (clear)", "low", "medium", "high", "xhigh", "max"])
        self.assertEqual(self.prompt("review_agents.fixer: Claude Code model")[3][:5],
                         ["Inherit agent_config.claude (clear)", "fable", "opus", "sonnet", "haiku"])
        self.assertEqual(self.prompt("auto_fix.review")[2], "1", "the current budget is prefilled")
        self.assertIn("Rounds 1-2 use the fixer; from round 3 the later-round fixer applies.", result.stdout)
        self.assertIn("+  test: 4", result.stdout)
        self.assertIn("Native check: the installed No-Mistakes loads the edited config.", result.stdout)
        # The native check ran in a disposable NM_HOME, never against the live configuration directory.
        doctors = [call for call in self.calls("no-mistakes") if call["args"] == ["doctor"]]
        self.assertTrue(doctors)
        for call in doctors:
            self.assertNotEqual(Path(call["cwd"]), self.home / ".no-mistakes")
            self.assertFalse(Path(call["cwd"]).exists())
        self.assert_no_actions()
        show = self.nm_config("show", MOCK_NM_VERSION="v1.105.0")
        self.assert_success(show)
        self.assertIn("  Reviewer: Codex - model: gpt-test-fast; effort: high", show.stdout)
        self.assertIn("  Fixer: Claude Code - model: opus; effort: max", show.stdout)
        self.assertIn("  Later-round fixer: Codex - model: native default; effort: low; from round 3", show.stdout)
        # Clearing the overrides and choosing Cursor (model only) keeps everything else.
        result, remaining = self.edit_nm(
            NM_MENU["fixer_after_round"], "No later-round override (clear)",
            NM_MENU["reviewer"], "Inherit the pipeline agent (clear override)",
            NM_MENU["agent_config"], "Cursor", "gpt-5",
            NM_MENU["save"], "yes", **newer)
        self.assert_success(result)
        self.assertEqual(remaining, [])
        self.assertIn("Cursor runs through acpx, which takes a model only", result.stdout)
        self.assertEqual(source.read_text(), edited.replace(
            "  reviewer:\n    agent: codex\n    model: gpt-test-fast\n    effort: high\n", "").replace(
            "  fixer_after_round:\n    agent: codex\n    effort: low\n    after_round: 2\n", "")
            + "agent_config:\n  cursor:\n    model: gpt-5\n")
        # Under the stable release the prerelease fields already fail natively; that is reported separately and
        # does not block an otherwise valid edit, and the fields are kept.
        before = source.read_text()
        result, remaining = self.edit_nm(NM_MENU["session_reuse"], "false", NM_MENU["save"], "yes")
        self.assert_success(result)
        self.assertIn("already rejected this config before the edit", result.stdout)
        self.assertEqual(source.read_text(), before + "session_reuse: false\n")

    def test_nm_config_cancel_invalid_input_and_native_rejection_leave_the_config_unchanged(self):
        source = self.nm_link(STABLE_DEFAULT)
        saved = source.read_bytes()
        for answers, status, message in (
                (("<cancel>",), 130, "unchanged"),
                ((NM_MENU["reviewer"], "Codex", "<cancel>"), 130, "unchanged"),
                ((NM_MENU["auto_fix"], "1", "2", "3", "4", "5", "<cancel>"), 130, "unchanged"),
                ((NM_MENU["auto_fix"], "", "2", "", "", "", NM_MENU["save"], "no"), 130, "unchanged"),
                ((NM_MENU["auto_fix"], "", "2", "", "", "", NM_MENU["quit"]), 0, "is unchanged"),
                ((NM_MENU["auto_fix"], "", "-1"), 1, "invalid auto_fix.review"),
                ((NM_MENU["auto_fix"], "", "two"), 1, "invalid auto_fix.review"),
                ((NM_MENU["fixer_after_round"], "Codex", INHERIT_CODEX, INHERIT_CODEX, "0"), 1, "invalid after_round"),
                ((NM_MENU["reviewer"], "Codex", "Custom model ID (unverified)", "has space"), 1, "invalid model ID"),
                ((NM_MENU["reviewer"], "Not a listed harness"), 1, "invalid selection"),
                ((NM_MENU["save"],), 0, "No change; nothing was saved.")):
            with self.subTest(answers=answers):
                result, remaining = self.edit_nm(*answers)
                self.assertEqual(result.returncode, status, result.stdout)
                self.assertEqual(remaining, [])
                self.assertIn(message, result.stdout)
                self.assertEqual(source.read_bytes(), saved)
        # A native load rejection of the candidate is refused before any confirmation.
        result, remaining = self.edit_nm(NM_MENU["fixer_after_round"], "Codex", INHERIT_CODEX, INHERIT_CODEX, "2",
                                         NM_MENU["save"], MOCK_NM_REJECT="after_round: 2")
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertEqual(remaining, [])
        self.assertIn("the installed No-Mistakes rejects the edited config", result.stdout)
        self.assertIn("nothing was saved", result.stdout)
        self.assertFalse([prompt for prompt in self.gum_prompts() if prompt[0] == "confirm"])
        self.assertEqual(source.read_bytes(), saved)
        # Unrelated native readiness failures are reported separately and never block a valid edit.
        result, remaining = self.edit_nm(NM_MENU["auto_fix"], "", "2", "", "", "3", NM_MENU["save"], "yes",
                                         MOCK_NM_DOCTOR="fail")
        self.assert_success(result)
        self.assertIn("environment readiness, not blocking this save", result.stdout)
        self.assertEqual(source.read_text(), STABLE_DEFAULT.replace("review: 3", "review: 2"))
        self.assertEqual(list(source.parent.glob(".config.yaml.nm-config.*")), [])
        self.assert_no_actions()

    def test_nm_config_refuses_non_scalar_agent_config_knobs_without_rewriting_them(self):
        for knobs, problem in (
                ("    model:\n      name: gpt-5.4\n    effort: high\n",
                 "agent_config.codex.model must be one value, not a mapping; fix it in YAML (line 4)"),
                ("    model: gpt-5.4\n    effort:\n      - high\n",
                 "agent_config.codex.effort must be one value, not a list; fix it in YAML (line 5)"),
                ("    effort: [high, low]\n",
                 "agent_config.codex.effort must be one value, not a list; fix it in YAML (line 4)")):
            with self.subTest(knobs=knobs):
                config = "agent: codex\nagent_config:\n  codex:\n" + knobs + "auto_fix:\n  review: 3\n"
                source = self.nm_link(config)
                show = self.nm_config("show")
                self.assert_success(show)
                line = next(line for line in show.stdout.splitlines() if line.startswith("  Codex: "))
                self.assertIn("agent_config unreadable (" + problem + ")", line)
                self.assertNotIn("native default", line)
                result, remaining = self.edit_nm(NM_MENU["agent_config"], "Codex", NM_MENU["save"])
                self.assert_success(result)
                self.assertEqual(remaining, [])
                self.assertIn("nm-config cannot safely edit Harness model/effort defaults (agent_config): " + problem,
                              result.stdout)
                self.assertIn("No change; nothing was saved.", result.stdout)
                self.assertEqual(source.read_text(), config)
        # Empty and null scalars remain native defaults.
        self.nm_link("agent: codex\nagent_config:\n  codex:\n    model:\n    effort: ~\n")
        show = self.nm_config("show")
        self.assert_success(show)
        self.assertIn("  Codex: model: native default; effort: native default", show.stdout.splitlines())

    def test_nm_config_show_reports_unreadable_agent_config_before_not_settable(self):
        for harness, shown, settable in (
                ("rovodev", "Rovo Dev", "model/effort: not settable by No-Mistakes (use its native CLI defaults)"),
                ("antigravity", "Antigravity", "model/effort: not settable by No-Mistakes (use its native CLI defaults)"),
                ("cursor", "Cursor", "model: gpt-5; effort: not settable (acpx takes a model only)")):
            with self.subTest(harness=harness):
                problem = ("agent_config." + harness + ".effort must be one value, not a list; fix it in YAML "
                           "(line 5)")
                self.nm_link("agent: codex\nagent_config:\n  " + harness + ":\n    model: gpt-5\n"
                             "    effort: [high]\n")
                show = self.nm_config("show")
                self.assert_success(show)
                line = next(line for line in show.stdout.splitlines() if line.startswith("  " + shown + ": "))
                self.assertIn("agent_config unreadable (" + problem + ")", line)
                self.assertNotIn("not settable", line)
                # A valid configuration keeps the special-harness response.
                self.nm_link("agent: codex\nagent_config:\n  " + harness + ":\n    model: gpt-5\n")
                show = self.nm_config("show")
                self.assert_success(show)
                self.assertIn("  " + shown + ": " + settable, show.stdout.splitlines())

    def test_nm_config_refuses_unsafe_yaml_per_edit_without_rewriting_it(self):
        config = ("agent: [codex, claude]\n"
                  "agent_config:\n  codex: &shared\n    model: gpt-5.4\n"
                  "review_agents: {reviewer: {agent: codex}}\n"
                  "auto_fix:\n  review: 3\n")
        source = self.nm_link(config)
        result, remaining = self.edit_nm(NM_MENU["agent"], NM_MENU["reviewer"], NM_MENU["agent_config"], "Codex",
                                         NM_MENU["auto_fix"], "", "2", "", "", "", NM_MENU["save"], "yes")
        self.assert_success(result)
        self.assertEqual(remaining, [])
        self.assertIn("agent is an ordered fallback list (codex, claude); nm-config keeps it.", result.stdout)
        self.assertIn("nm-config cannot safely edit Reviewer (review_agents.reviewer): unsupported YAML form", result.stdout)
        self.assertIn("nm-config cannot safely edit Harness model/effort defaults (agent_config)", result.stdout)
        self.assertIn("yourself for this setting", result.stdout)
        # Only the safe, targeted edit was applied; the refused forms are untouched.
        self.assertEqual(source.read_text(), config.replace("review: 3", "review: 2"))
        show = self.nm_config("show")
        self.assert_success(show)
        self.assertIn("  Reviewer: cannot display safely (unsupported YAML form", show.stdout)
        # A top-level merge can supply any setting, so every edit is refused rather than shadowing it.
        merged = "<<: &defaults\n  auto_fix:\n    review: 5\n    test: 8\nagent: codex\n"
        source.write_text(merged)
        result, remaining = self.edit_nm(NM_MENU["auto_fix"], NM_MENU["agent"], NM_MENU["session_reuse"],
                                         NM_MENU["save"])
        self.assert_success(result)
        self.assertEqual(remaining, [])
        self.assertIn("nm-config cannot safely edit Auto-fix attempts (auto_fix): a top-level merge key (<<) (line 1)",
                      result.stdout)
        self.assertIn("No change; nothing was saved.", result.stdout)
        self.assertEqual(source.read_text(), merged)
        show = self.nm_config("show")
        self.assert_success(show)
        self.assertIn("  cannot display safely (a top-level merge key (<<) (line 1)); see the YAML", show.stdout)
        self.assertNotIn("test: unset", show.stdout)
        # A file whose structure nm-config cannot read is never edited; both modes explain why.
        for content in ("agent: codex\r\nauto_fix:\r\n  review: 3\r\n", "---\nagent: codex\n---\nagent: pi\n",
                        "%YAML 1.2\n---\nagent: codex\n", "agent: codex\nagent: claude\n",
                        "auto_fix:\n\treview: 3\n"):
            with self.subTest(content=content):
                source.write_bytes(content.encode())
                result = self.nm_config("show")
                self.assertEqual(result.returncode, 1)
                self.assertIn("cannot safely read", result.stderr)
                result, _ = self.edit_nm()
                self.assertEqual(result.returncode, 1)
                self.assertIn("nothing was changed", result.stdout)
                self.assertFalse(self.calls("gum"))
                self.assertEqual(source.read_bytes(), content.encode())

    def test_nm_config_keeps_a_leading_document_start_marker(self):
        config = "# globals\n--- # start\nagent: codex\nauto_fix:\n  review: 3\n"
        source = self.nm_link(config)
        show = self.nm_config("show")
        self.assert_success(show)
        self.assertIn("Pipeline agent (agent): codex", show.stdout)
        self.assertIn("  review: 3", show.stdout)
        result, remaining = self.edit_nm(NM_MENU["auto_fix"], "", "2", "", "", "", NM_MENU["save"], "yes")
        self.assert_success(result)
        self.assertEqual(remaining, [])
        self.assertEqual(source.read_text(), config.replace("review: 3", "review: 2"))

    def test_nm_config_show_explains_lists_and_mappings_where_one_value_belongs(self):
        config = ("agent:\n  name: codex\n"
                  "review_agents:\n  reviewer:\n    agent: [codex, claude]\n"
                  "  fixer_after_round:\n    agent: claude\n    after_round:\n      n: 2\n"
                  "auto_fix:\n  review:\n    max: 2\n  test: 4\n"
                  "session_reuse: [true]\n")
        source = self.nm_link(config)
        show = self.nm_config("show")
        self.assert_success(show)
        self.assertNotIn("None", show.stdout)
        for expected in (
                "Pipeline agent (agent): cannot display safely (agent must be one value, not a mapping; fix it in "
                "YAML (line 1)); see the YAML",
                "  Reviewer: cannot display safely (review_agents.reviewer.agent must be one value, not a list; fix "
                "it in YAML (line 5)); see the YAML",
                "  Later-round fixer: cannot display safely (review_agents.fixer_after_round.after_round must be "
                "one value, not a mapping; fix it in YAML (line 8)); see the YAML",
                "  review: cannot display safely (auto_fix.review must be one value, not a mapping; fix it in YAML "
                "(line 11)); see the YAML",
                "  test: 4",
                "Fixer session reuse (session_reuse): cannot display safely (session_reuse must be one value, not a "
                "list; fix it in YAML (line 14)); see the YAML"):
            self.assertIn(expected, show.stdout)
        # The editor opens with the same explanation, and refusing the unsafe edit leaves the file untouched.
        result, remaining = self.edit_nm(NM_MENU["auto_fix"], "", "2", "4", "", "", NM_MENU["quit"])
        self.assert_success(result)
        self.assertEqual(remaining, [])
        self.assertIn("  Reviewer: cannot display safely", result.stdout)
        self.assertIn("nm-config cannot safely edit Auto-fix attempts (auto_fix): auto_fix.review holds a mapping or "
                      "list", result.stdout)
        self.assertEqual(self.prompt("auto_fix.review: max automatic fix attempts")[2], "")
        self.assertEqual(source.read_text(), config)

    def test_nm_config_follows_acp_alias_profiles_and_combined_codex_pins(self):
        # cursor and acp:cursor share one native profile: prefill and clear the entry that applies.
        alias_only = "agent: cursor\nagent_config:\n  acp:cursor:\n    model: gpt-5\nlog_level: debug\n"
        source = self.nm_link(alias_only)
        result, remaining = self.edit_nm(NM_MENU["agent_config"], "Cursor", "Native default (clear override)",
                                         NM_MENU["save"], "yes")
        self.assert_success(result)
        self.assertEqual(remaining, [])
        self.assertEqual(self.prompt("agent_config.acp:cursor: Cursor model")[2], "gpt-5")
        self.assertEqual(source.read_text(), "agent: cursor\nlog_level: debug\n")
        dual = "agent: cursor\nagent_config:\n  cursor:\n    model: a-model\n  acp:cursor:\n    model: b-model\n"
        for answers, expected in (
                (("Native default (clear override)",), "agent: cursor\n"),
                (("Custom model ID (unverified)", "c-model"), dual.replace("a-model", "c-model"))):
            with self.subTest(answers=answers):
                source.write_text(dual)
                result, remaining = self.edit_nm(NM_MENU["agent_config"], "Cursor", *answers, NM_MENU["save"], "yes")
                self.assert_success(result)
                self.assertEqual(remaining, [])
                self.assertEqual(self.prompt("agent_config.cursor: Cursor model")[2], "a-model")
                self.assertEqual(source.read_text(), expected)
        # Combined -c/--config tokens pin codex knobs natively, as the stable adapter recognizes them.
        pinned = ("agent: codex\nagent_config:\n  codex:\n    model: gpt-5.4\n    effort: high\n"
                  "agent_args_override:\n  codex:\n    - '-c model_reasoning_effort=\"low\"'\n"
                  "    - --config=model=o3\n    - -c\n    - service_tier=\"priority\"\n")
        source.write_text(pinned)
        show = self.nm_config("show")
        self.assert_success(show)
        self.assertIn("  Codex: model: gpt-5.4 - overridden: agent_args_override.codex pins --config=model=o3; effort: "
                      "high - overridden: agent_args_override.codex pins -c model_reasoning_effort=\"low\"",
                      show.stdout.splitlines())
        self.assertIn("  codex: -c model_reasoning_effort=\"low\" --config=model=o3 -c service_tier=\"priority\" - pins "
                      "effort and model", show.stdout.splitlines())
        result, remaining = self.edit_nm(NM_MENU["agent_config"], "Codex", "Native default (clear override)", "medium",
                                         NM_MENU["quit"], **self.codex_cache())
        self.assert_success(result)
        self.assertEqual(remaining, [])
        self.assertIn("Note: agent_args_override.codex pins effort (-c model_reasoning_effort=\"low\")", result.stdout)
        self.assertEqual(source.read_text(), pinned)

    def test_nm_config_offers_native_harnesses_beyond_the_issue_agents(self):
        # No-Mistakes harnesses are independent of mf-config's issue agents (Codex, Claude Code, Cursor).
        source = self.nm_link(STABLE_DEFAULT + "agent_args_override:\n  pi:\n    - --thinking=low\n")
        custom = "Custom model ID (unverified)"
        result, remaining = self.edit_nm(
            NM_MENU["agent"], "pi",
            NM_MENU["agent_config"], "Pi", custom, "anthropic/claude-opus-4-8", "max",
            NM_MENU["reviewer"], "Copilot", custom, "gpt-5", "xhigh",
            NM_MENU["fixer"], "OpenCode", custom, "openai/gpt-5", "high",
            NM_MENU["fixer_after_round"], "Rovo Dev", "",
            NM_MENU["save"], "yes")
        self.assert_success(result)
        self.assertEqual(remaining, [])
        self.assertEqual(self.prompt("Pipeline agent")[3],
                         ["auto", "codex", "claude", "grok", "opencode", "pi", "copilot", "rovodev", "antigravity",
                          "cursor", "devin"])
        self.assertNotIn("Rovo Dev", self.prompt("agent_config: harness")[3])
        self.assertEqual(self.prompt("review_agents.reviewer: Copilot effort")[3],
                         ["Inherit agent_config.copilot (clear)", "minimal", "low", "medium", "high", "xhigh", "max"])
        self.assertIn("Note: agent_args_override.pi pins effort (--thinking=low)", result.stdout)
        self.assertIn("No-Mistakes cannot set a model or effort for Rovo Dev", result.stdout)
        self.assertEqual(source.read_text(), STABLE_DEFAULT.replace("agent: codex", "agent: pi")
                         + "agent_args_override:\n  pi:\n    - --thinking=low\n"
                         + "agent_config:\n  pi:\n    model: anthropic/claude-opus-4-8\n    effort: max\n"
                         + "review_agents:\n  reviewer:\n    agent: copilot\n    model: gpt-5\n    effort: xhigh\n"
                         + "  fixer:\n    agent: opencode\n    model: openai/gpt-5\n    effort: high\n"
                         + "  fixer_after_round:\n    agent: rovodev\n")
        show = self.nm_config("show")
        self.assert_success(show)
        lines = show.stdout.splitlines()
        self.assertIn("  Pi: model: anthropic/claude-opus-4-8; effort: max - overridden: agent_args_override.pi pins "
                      "--thinking=low", lines)
        self.assertIn("  Reviewer: Copilot - model: gpt-5; effort: xhigh", lines)
        self.assertIn("  Later-round fixer: Rovo Dev - model/effort: not settable by No-Mistakes (use its native CLI "
                      "defaults); from round 2 (after_round: 1; rounds 1-1 use the fixer)", lines)
        # OpenCode needs provider/model natively; a bare name is refused before anything is saved.
        before = source.read_text()
        result, remaining = self.edit_nm(NM_MENU["fixer"], "OpenCode", custom, "gpt-5")
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertEqual(remaining, [])
        self.assertIn("provider/model form", result.stdout)
        self.assertEqual(source.read_text(), before)

    def test_nm_config_edits_only_the_live_link_to_this_clone(self):
        source = self.bundle / "no-mistakes/config.yaml"
        default = source.read_bytes()
        link = self.home / ".no-mistakes/config.yaml"

        def refused(expected, tool=None):
            for mode in ("show", "edit"):
                result = (self.run_script(tool or self.bundle / "bin/nm-config", "show") if mode == "show"
                          else self.edit_nm(tool=tool)[0])
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                self.assertIn(expected, result.stdout + result.stderr)
                self.assertFalse(self.calls("gum"))
            self.assertEqual(source.read_bytes(), default)

        refused("does not exist; run make setup from your retained mini-factory clone")
        link.parent.mkdir()
        link.write_text("agent: codex\n")
        refused("is not linked to a mini-factory clone")
        self.assertEqual(link.read_text(), "agent: codex\n")
        link.unlink()
        # A dotfiles-owned or other unrelated config is never edited, even with the same file name.
        dotfiles = self.root / "dotfiles/no-mistakes/config.yaml"
        dotfiles.parent.mkdir(parents=True)
        dotfiles.write_text("agent: claude\n")
        link.symlink_to(dotfiles)
        refused("not in a mini-factory clone with nm-config")
        self.assertEqual(dotfiles.read_text(), "agent: claude\n")
        link.unlink()
        link.symlink_to(self.root / "moved clone/no-mistakes/config.yaml")
        refused("missing or not a regular file; was the clone moved or deleted?")
        link.unlink()
        link.symlink_to("relative/no-mistakes/config.yaml")
        refused("not to a mini-factory clone's no-mistakes/config.yaml")
        link.unlink()
        # The installed runtime copy is never the edited source of truth.
        shutil.copytree(self.bundle, self.installed)
        (self.installed / ".mini-factory-install").write_text("mini-factory-v1\n")
        runtime_copy = (self.installed / "no-mistakes/config.yaml").read_bytes()
        link.symlink_to(self.installed / "no-mistakes/config.yaml")
        refused("links into the installed runtime copy")
        self.assertEqual((self.installed / "no-mistakes/config.yaml").read_bytes(), runtime_copy)
        link.unlink()
        # From another clone, nm-config names the clone that owns the live link.
        other = self.root / "other clone"
        shutil.copytree(self.bundle, other)
        link.symlink_to(other / "no-mistakes/config.yaml")
        refused("Run " + str(other / "bin/nm-config") + " instead")
        self.assert_success(self.run_script(other / "bin/nm-config", "show"))
        link.unlink()
        # NM_HOME selects the live link; the default location is then ignored.
        custom = self.root / "custom nm home"
        custom.mkdir()
        (custom / "config.yaml").symlink_to(source)
        result = self.nm_config("show", NM_HOME=str(custom))
        self.assert_success(result)
        self.assertIn(str(custom / "config.yaml") + " -> " + str(source), result.stdout)
        result = self.nm_config("show", NM_HOME="relative")
        self.assertEqual(result.returncode, 1)
        self.assertIn("NM_HOME must be an absolute path", result.stderr)

    def test_doctor_checks_config_target_clone_files(self):
        self.install()
        link = self.home / ".no-mistakes/config.yaml"
        unrelated = self.root / "dotfiles/no-mistakes/config.yaml"
        unrelated.parent.mkdir(parents=True)
        unrelated.write_text("agent: codex\n")
        link.unlink()
        link.symlink_to(unrelated)

        def refused():
            result = self.run_script(self.installed / "scripts/doctor.sh")
            self.assertNotEqual(result.returncode, 0, result.stdout)
            self.assertIn("target is not in a mini-factory clone with nm-config", result.stdout)
            self.assertNotIn("OK: No-Mistakes config links to your clone", result.stdout)
            self.assertEqual(unrelated.read_text(), "agent: codex\n")

        refused()
        clone = unrelated.parent.parent
        for relative in ("bin/nm-config", "scripts/nm_config.py"):
            helper = clone / relative
            helper.parent.mkdir(parents=True, exist_ok=True)
            helper.symlink_to(self.bundle / relative)
            refused()
            helper.unlink()
            helper.write_bytes((self.bundle / relative).read_bytes())
        # Both regular helper files pass the same clone-file check used by nm-config.
        result = self.run_script(self.installed / "scripts/doctor.sh")
        self.assert_success(result)
        self.assertIn("OK: No-Mistakes config links to your clone", result.stdout)

    def test_managed_nm_config_launcher_edits_the_clone_and_never_replaces_another_command(self):
        self.install()
        launcher = self.wrapper.parent / "nm-config"
        content = launcher.read_bytes()
        self.assertIn(b"# mini-factory managed launcher v1", content)
        self.assertTrue(content.endswith(b'/mini-factory/bin/nm-config "$@"\n'))
        source = self.bundle / "no-mistakes/config.yaml"
        runtime_copy = (self.installed / "no-mistakes/config.yaml").read_bytes()
        # The fresh stable default stays valid and is edited in the clone, never in the runtime copy.
        self.assertEqual(source.read_text(), STABLE_DEFAULT)
        self.assert_success(self.run_script(launcher, "show"))
        # Gum prefills each current budget; the mock returns the final field text, so "3" keeps ci.
        result, remaining = self.edit_nm(NM_MENU["agent"], "claude", NM_MENU["auto_fix"], "", "2", "", "", "3",
                                         NM_MENU["save"], "yes", tool=launcher)
        self.assert_success(result)
        self.assertEqual(remaining, [])
        self.assertEqual(source.read_text(), STABLE_DEFAULT.replace("agent: codex", "agent: claude")
                         .replace("review: 3", "review: 2"))
        self.assertEqual((self.installed / "no-mistakes/config.yaml").read_bytes(), runtime_copy)
        self.assertIn("Native check: the installed No-Mistakes loads the edited config.", result.stdout)
        self.assertIn("rerun it after saving if Claude Code is not logged in on this machine", result.stdout)
        doctor = self.run_script(self.installed / "scripts/doctor.sh")
        self.assert_success(doctor)
        self.assertIn("OK: nm-config launcher resolves on PATH", doctor.stdout)
        self.assert_success(self.setup())
        self.assertEqual(launcher.read_bytes(), content)
        # An unrelated (for example dotfiles-owned) nm-config file or command is left alone.
        launcher.write_text("#!/bin/sh\necho dotfiles nm-config\n")
        result = self.setup()
        self.assert_success(result)
        self.assertEqual(launcher.read_text(), "#!/bin/sh\necho dotfiles nm-config\n")
        self.assertIn("Run " + str(self.bundle / "bin/nm-config") + " instead.", result.stdout)
        doctor = self.run_script(self.installed / "scripts/doctor.sh")
        self.assert_success(doctor)
        self.assertIn("NOTE: optional nm-config launcher is not on PATH", doctor.stdout)
        launcher.unlink()
        other = self.mock / "nm-config"
        other.write_text("#!/bin/sh\necho other\n")
        other.chmod(0o755)
        result = self.setup()
        self.assert_success(result)
        self.assertFalse(launcher.exists())
        self.assertEqual(other.read_text(), "#!/bin/sh\necho other\n")
        self.assertIn("another nm-config command is on PATH", result.stdout)
        self.assertIn("mf-config launcher: " + str(self.wrapper.parent / "mf-config"), result.stdout)
        # The repository-local command still works.
        self.assert_success(self.nm_config("show"))
        self.assert_no_actions()

    # make update: fast-forward the retained clone, optional native upgrades, then the setup/doctor handoff.

    def clone_fixture(self):
        """Make the copied bundle a retained clone of a disposable upstream, as git clone leaves it."""
        identity = {"GIT_AUTHOR_NAME": "Maintainer", "GIT_AUTHOR_EMAIL": "maintainer@example.invalid",
                    "GIT_COMMITTER_NAME": "Maintainer", "GIT_COMMITTER_EMAIL": "maintainer@example.invalid"}

        def git(directory, *args):
            return subprocess.run([REAL_GIT, "-C", str(directory), *args], env=dict(self.env, PATH=REAL_PATH, **identity),
                                  check=True, capture_output=True, text=True).stdout.strip()

        upstream, maintainer = self.root / "upstream with spaces.git", self.root / "maintainer clone"
        git(self.bundle, "init", "-q", "-b", "main")
        git(self.bundle, "add", "-A")
        git(self.bundle, "commit", "-q", "-m", "Release 1")
        git(self.root, "clone", "-q", "--bare", str(self.bundle), str(upstream))
        git(self.bundle, "remote", "add", "origin", str(upstream))
        git(self.bundle, "fetch", "-q", "origin")
        git(self.bundle, "branch", "-q", "--set-upstream-to=origin/main", "main")
        git(self.root, "clone", "-q", str(upstream), str(maintainer))

        def publish(relative, content, message="Upstream change"):
            path = maintainer / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
            git(maintainer, "add", relative)
            git(maintainer, "commit", "-q", "-m", message)
            git(maintainer, "push", "-q", "origin", "main")
            return git(maintainer, "rev-parse", "HEAD")

        return git, publish

    def update(self, **env):
        return self.run_script(self.bundle / "scripts/update.sh", env=dict(MOCK_CLONE_UPDATE="1", **env))

    def interactive_update(self, answers, **env):
        return self.run_in_terminal([str(self.bundle / "scripts/update.sh")], dict(self.env, MOCK_CLONE_UPDATE="1", **env),
                                    "".join(answer + "\n" for answer in answers).encode())

    def native_updates(self, tool):
        return [c["args"] for c in self.calls(tool) if c["args"][:1] == ["update"]]

    def assert_safe_clone_actions(self):
        clone = [c["args"] for c in self.calls("git") if c["args"][:2] == ["-C", str(self.bundle)]]
        for args in clone:
            self.assertFalse({"reset", "stash", "checkout", "switch", "pull", "rebase", "push", "clean", "restore",
                              "--force"} & set(args), args)
        self.assertTrue(all("--ff-only" in args for args in clone if args[2] == "merge"), clone)

    def native_layouts(self, *tools):
        """Place mock CLIs exactly where each upstream native installer puts them."""
        local_bin = self.home / ".local/bin"

        def copy(destination):
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(self.mock / "mock-cli", destination)
            destination.chmod(0o755)
            return destination

        for tool in tools:
            if tool == "herdr":
                copy(local_bin / "herdr")
            elif tool == "acpx":
                # Setup's npm install -g --prefix ~/.local links its command into ~/.local/bin.
                self.acpx.unlink()
                self.acpx.symlink_to(copy(self.home / ".local/lib/node_modules/acpx/dist/cli.js"))
            elif tool == "codex":
                release = copy(self.home / ".codex/packages/standalone/releases/0.115.0/bin/codex").parent.parent
                (release.parent.parent / "current").symlink_to(release)
                (local_bin / "codex").symlink_to(release.parent.parent / "current/bin/codex")
            else:
                (local_bin / tool).symlink_to(copy({
                    "no-mistakes": self.home / ".no-mistakes/bin/no-mistakes",
                    "claude": self.home / ".local/share/claude/versions/2.1.0",
                    "cursor-agent": self.home / ".local/share/cursor-agent/versions/2026.10.22/cursor-agent",
                }[tool]))
            if tool == "cursor-agent":
                # Cursor's installer also links agent and writes its cursor shim.
                (local_bin / "agent").symlink_to(os.readlink(local_bin / tool))
                (local_bin / "cursor").write_text("#!/bin/sh\n# Find cursor executable in PATH, excluding the current shim\n")

    def test_update_fast_forwards_clean_clone_refreshes_runtime_and_reruns_idempotently(self):
        git, publish = self.clone_fixture()
        # First-time setup initializes the tracked No-Mistakes YAML, so the clone is no longer clean.
        self.install()
        source = self.bundle / "no-mistakes/config.yaml"
        link = self.home / ".no-mistakes/config.yaml"
        self.assertEqual(git(self.bundle, "status", "--porcelain"), "M no-mistakes/config.yaml")
        configured = source.read_bytes()
        setting = Path(self.env["XDG_CONFIG_HOME"]) / "mini-factory/issue-agent"
        profiles = self.profiles_file({"issue-prepare": {"agent": "codex"}})
        kept = {path: path.read_bytes() for path in (setting, profiles)}
        for path in (self.home / ".local/bin/personal-tool", link.with_name("notes.txt")):
            path.write_text("keep me\n")
            kept[path] = path.read_bytes()
        upstream = publish("README.md", (self.bundle / "README.md").read_text() + "\nUpstream release note.\n")
        result = self.update()
        self.assert_success(result)
        self.assertEqual(git(self.bundle, "rev-parse", "HEAD"), upstream)
        self.assertIn("Clone: fast-forwarded main", result.stdout)
        # The existing make setup path refreshed the managed runtime and ended with doctor.
        self.assertIn("Upstream release note.", (self.installed / "README.md").read_text())
        self.assertIn("Installation: installed", result.stdout)
        self.assertIn("Authentication/setup: complete", result.stdout)
        self.assertIn("Runtime: make setup passed, including the doctor checks.", result.stdout)
        self.assertEqual(source.read_bytes(), configured)
        self.assertEqual(os.readlink(link), str(source))
        # Mock tools are not native installations: guidance only; the extension offer is skipped headless.
        self.assertIn("Herdr: manual update only", result.stdout)
        self.assertIn("Skipped without an interactive terminal; no approval was assumed. "
                      "Run gh extension upgrade dash yourself", result.stdout)
        # Every baseline tool is inspected, whichever roles use it.
        for baseline in ("Claude Code: manual update only", "Cursor CLI: manual update only",
                         "Node.js and npm: manual update only", "acpx: manual update only"):
            self.assertIn(baseline, result.stdout)
        for tool in ("herdr", "codex", "claude", "cursor-agent", "no-mistakes"):
            self.assertFalse(self.native_updates(tool), tool)
        self.assertFalse([c for c in self.calls("gh") if c["args"][:2] == ["extension", "upgrade"]])
        runtime = (self.installed / "bin/ghd").read_bytes()
        result = self.update()
        self.assert_success(result)
        self.assertIn("Clone: already up to date with origin/main", result.stdout)
        self.assertEqual(git(self.bundle, "rev-parse", "HEAD"), upstream)
        self.assertEqual((self.installed / "bin/ghd").read_bytes(), runtime)
        self.assertEqual(source.read_bytes(), configured)
        self.assertEqual(os.readlink(link), str(source))
        for path, content in kept.items():
            self.assertEqual(path.read_bytes(), content, path)
        self.assert_safe_clone_actions()
        self.assert_no_actions()

    def test_update_refuses_runtime_copy_non_clone_detached_head_other_branch_and_missing_upstream(self):
        self.install()
        result = self.run_script(self.installed / "scripts/update.sh", env={"MOCK_CLONE_UPDATE": "1"})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("run make update from your retained mini-factory clone, not the installed runtime copy",
                      result.stderr)
        result = self.update()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("is not a Git clone", result.stderr)
        git, publish = self.clone_fixture()
        publish("README.md", "Upstream rewrite\n")
        start = git(self.bundle, "rev-parse", "HEAD")
        git(self.bundle, "checkout", "-q", "-b", "feature/local")
        result = self.update()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("on branch feature/local: make update runs only on main and never switches branches", result.stderr)
        self.assertIn("Switch yourself (git switch main)", result.stderr)
        self.assertEqual(git(self.bundle, "branch", "--show-current"), "feature/local")
        git(self.bundle, "checkout", "-q", "--detach", "main")
        result = self.update()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("detached HEAD: make update runs only on main", result.stderr)
        self.assertEqual(git(self.bundle, "branch", "--show-current"), "")
        git(self.bundle, "checkout", "-q", "main")
        git(self.bundle, "branch", "-q", "--unset-upstream")
        result = self.update()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("main has no upstream branch", result.stderr)
        self.assertIn("git branch --set-upstream-to=origin/main main", result.stderr)
        self.assertEqual(git(self.bundle, "rev-parse", "HEAD"), start)
        self.assertNotIn("make setup", result.stdout)
        self.assertFalse([c for c in self.calls("git") if {"fetch", "merge"} & set(c["args"])])
        self.assert_safe_clone_actions()

    def test_update_keeps_nonconflicting_local_config_and_stops_on_conflicts_or_divergence(self):
        git, publish = self.clone_fixture()
        self.install()
        source = self.bundle / "no-mistakes/config.yaml"
        edited = source.read_text().replace("review: 3", "review: 1") + "# my local setting\n"
        source.write_text(edited)
        publish("README.md", (self.bundle / "README.md").read_text() + "\nUnrelated upstream change.\n")
        self.assert_success(self.update())
        self.assertEqual(source.read_text(), edited)
        self.assertIn("Unrelated upstream change.", (self.installed / "README.md").read_text())
        # Upstream changes to a locally edited file, or to the path of an untracked file, stop before any change.
        head = git(self.bundle, "rev-parse", "HEAD")
        (self.bundle / "notes.txt").write_text("my untracked notes\n")
        publish("no-mistakes/config.yaml", git(self.bundle, "show", "HEAD:no-mistakes/config.yaml") + "\n# upstream\n")
        publish("notes.txt", "upstream notes\n")
        result = self.update()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("origin/main changes files that you edited or created locally: no-mistakes/config.yaml, notes.txt",
                      result.stderr)
        self.assertIn("git stash push --include-untracked -- no-mistakes/config.yaml notes.txt", result.stderr)
        self.assertNotIn("Refreshing the managed runtime", result.stdout)
        self.assertEqual(git(self.bundle, "rev-parse", "HEAD"), head)
        self.assertEqual(source.read_text(), edited)
        self.assertEqual((self.bundle / "notes.txt").read_text(), "my untracked notes\n")
        # A local commit on main makes the histories diverge; nothing is rebased or reset.
        (self.bundle / "notes.txt").unlink()
        (self.bundle / "local.md").write_text("local commit\n")
        git(self.bundle, "add", "local.md")
        git(self.bundle, "commit", "-q", "-m", "Local commit")
        local = git(self.bundle, "rev-parse", "HEAD")
        result = self.update()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("main and origin/main have diverged (1 local, 2 upstream commit(s))", result.stderr)
        self.assertIn("git rebase origin/main", result.stderr)
        self.assertEqual(git(self.bundle, "rev-parse", "HEAD"), local)
        self.assertEqual(source.read_text(), edited)
        self.assertEqual(git(self.bundle, "stash", "list"), "")
        self.assert_safe_clone_actions()

    def test_update_never_overwrites_an_ignored_local_file_that_upstream_adds(self):
        git, publish = self.clone_fixture()
        self.install()
        head = git(self.bundle, "rev-parse", "HEAD")
        with (self.bundle / ".git/info/exclude").open("a") as exclude:
            exclude.write("notes.txt\n")
        (self.bundle / "notes.txt").write_text("my ignored notes\n")
        publish("notes.txt", "upstream notes\n")
        result = self.update()
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn("did not complete", result.stderr)
        self.assertNotIn("Refreshing the managed runtime", result.stdout)
        self.assertEqual(git(self.bundle, "rev-parse", "HEAD"), head)
        self.assertEqual((self.bundle / "notes.txt").read_text(), "my ignored notes\n")
        self.assert_safe_clone_actions()

    def test_update_offers_every_agent_cli_and_acpx_whatever_the_selection(self):
        self.clone_fixture()
        self.install()
        self.native_layouts("claude", "cursor-agent")
        # Every role and duty uses Codex, yet the baseline agent CLIs, Node.js, and acpx are all inspected.
        result = self.update()
        self.assert_success(result)
        for offered in ("Claude Code (2.1.0 (Claude Code)): native installer", "Cursor CLI (2026.10.22-test): native installer",
                        "Run claude update yourself", "Run cursor-agent update yourself",
                        "Node.js and npm: manual update only", "acpx: manual update only"):
            self.assertIn(offered, result.stdout)
        self.assertIn("Skipped without a terminal: gh-dash claude cursor-agent", result.stdout)
        for tool in ("claude", "cursor-agent"):
            self.assertFalse(self.native_updates(tool), tool)
        self.assertFalse(self.npm_changes())

    def test_update_offers_node_and_acpx_only_through_their_owning_installation(self):
        self.clone_fixture()
        self.install()
        self.native_layouts("acpx")
        cellar = self.root / "brew/Cellar"
        formula = cellar / "node/24.11.0/bin/node"
        formula.parent.mkdir(parents=True)
        shutil.copyfile(self.mock / "mock-cli", formula)
        formula.chmod(0o755)
        # The Node.js acpx starts is the one the No-Mistakes daemon's PATH finds.
        self.daemon_node.unlink()
        self.daemon_node.symlink_to(formula)
        brew = {"MOCK_BREW_CELLAR": str(cellar)}
        # Prompt order: gh-dash, then Node.js (Homebrew's node includes npm), then acpx (setup's ~/.local install).
        result = self.interactive_update(["n", "y", "y"], **brew)
        self.assert_success(result)
        self.assertIn("Node.js and npm (v24.11.0): Homebrew formula node", result.stdout)
        self.assertEqual([c["args"] for c in self.calls("brew") if c["args"][:1] == ["upgrade"]], [["upgrade", "node"]])
        self.assertEqual([c["args"] for c in self.npm_changes()],
                         [["install", "-g", "--prefix", str(self.home / ".local"), "acpx@latest"]])
        self.assertIn("Finished; acpx is still 0.20.0 (already current).", result.stdout)
        self.assertIn("Updater completed (updated or already current): node acpx", result.stdout)
        # A version manager's Node.js gets exact guidance; its manager, npm prefix, and shell files stay untouched.
        fnm = self.root / "fnm/node-versions/v24.11.0/installation/bin/node"
        fnm.parent.mkdir(parents=True)
        shutil.copyfile(self.mock / "mock-cli", fnm)
        fnm.chmod(0o755)
        self.daemon_node.unlink()
        self.daemon_node.symlink_to(fnm)
        self.log.write_text("")
        result = self.interactive_update(["n", "n"], **brew)
        self.assert_success(result)
        self.assertIn("Node.js and npm: manual update only: " + str(fnm) + " is managed by fnm; run fnm install --lts",
                      result.stdout)
        self.assertIn("make update never changes a Node version manager, npm prefix, or shell configuration", result.stdout)
        self.assertIn("Declined (left unchanged): gh-dash acpx", result.stdout)
        self.assertFalse([c for c in self.calls("brew") if c["args"][:1] == ["upgrade"]])
        self.assertFalse(self.npm_changes())
        self.assert_no_actions()

    def test_update_targets_the_daemon_node_not_a_different_shell_node(self):
        self.clone_fixture()
        self.install()

        def place(path, version):
            path.parent.mkdir(parents=True)
            path.write_text("#!/bin/sh\necho " + version + "\n")
            path.chmod(0o755)
            return path

        cellar = self.root / "brew/Cellar"
        formula = place(cellar / "node/24.11.0/bin/node", "v24.11.0")
        fnm = place(self.root / "fnm/node-versions/v23.0.0/installation/bin/node", "v23.0.0")
        brew = {"MOCK_BREW_CELLAR": str(cellar)}
        # Your shell finds Homebrew's node but the daemon's PATH finds fnm's: only fnm guidance, no brew upgrade.
        (self.mock / "node").unlink()
        (self.mock / "node").symlink_to(formula)
        self.daemon_node.unlink()
        self.daemon_node.symlink_to(fnm)
        self.log.write_text("")
        result = self.interactive_update(["n"], **brew)
        self.assert_success(result)
        self.assertIn("Node.js and npm: manual update only: " + str(fnm) + " is managed by fnm", result.stdout)
        self.assertNotIn("Homebrew formula node", result.stdout)
        self.assertFalse([c for c in self.calls("brew") if c["args"][:1] == ["upgrade"]])
        # Reversed, the plan and the displayed version are the daemon's Homebrew node, not the shell's fnm node.
        (self.mock / "node").unlink()
        (self.mock / "node").symlink_to(fnm)
        self.daemon_node.unlink()
        self.daemon_node.symlink_to(formula)
        self.log.write_text("")
        result = self.interactive_update(["n", "y"], **brew)
        self.assert_success(result)
        self.assertIn("Node.js and npm (v24.11.0): Homebrew formula node", result.stdout)
        self.assertIn("for " + str(self.daemon_node) + ", the Node.js the No-Mistakes daemon's PATH finds", result.stdout)
        self.assertNotIn("v23.0.0", result.stdout)
        self.assertEqual([c["args"] for c in self.calls("brew") if c["args"][:1] == ["upgrade"]], [["upgrade", "node"]])
        self.assertFalse(self.npm_changes())
        self.assert_no_actions()

    def test_update_uses_configured_acpx_outside_path_and_keeps_ownership_checks(self):
        self.clone_fixture()
        self.install()
        source = self.bundle / "no-mistakes/config.yaml"
        original = source.read_text()
        prefix = self.root / "custom npm prefix"
        target = prefix / "lib/node_modules/acpx/dist/cli.js"
        target.parent.mkdir(parents=True)
        target.write_text((self.mock / "mock-cli").read_text().replace('print("0.20.0")', 'print("0.21.0")'))
        target.chmod(0o755)
        custom = prefix / "bin/acpx"
        custom.parent.mkdir()
        custom.symlink_to(target)
        source.write_text(original + "acpx_path: " + json.dumps(str(custom)) + "\n")
        environment = {"MOCK_NPM_PREFIX": str(prefix)}
        # The configured runner is outside PATH; the different acpx on PATH must not stand in for it.
        result = self.update(**environment)
        self.assert_success(result)
        self.assertIn("acpx (0.21.0): npm package acpx", result.stdout)
        self.assertFalse(self.npm_changes())
        self.acpx.unlink()
        self.log.write_text("")
        result = self.interactive_update(["n", "y"], **environment)
        self.assert_success(result)
        self.assertIn("acpx (0.21.0): npm package acpx", result.stdout)
        self.assertEqual([c["args"] for c in self.npm_changes()], [["install", "-g", "acpx@latest"]])
        # An unrecognized installation gets manual guidance for the configured path, never an unrelated upgrade.
        standalone = self.root / "standalone/acpx"
        standalone.parent.mkdir()
        shutil.copyfile(target, standalone)
        standalone.chmod(0o755)
        source.write_text(original + "acpx_path: " + json.dumps(str(standalone)) + "\n")
        self.log.write_text("")
        result = self.interactive_update(["n"], **environment)
        self.assert_success(result)
        self.assertIn("acpx: manual update only: " + str(standalone), result.stdout)
        self.assertFalse(self.npm_changes())
        # An unreadable setting cannot fall back to the unrelated acpx on PATH.
        shutil.copyfile(self.mock / "mock-cli", self.acpx)
        self.acpx.chmod(0o755)
        source.write_text(original + "acpx_path: [acpx]\n")
        result = self.update(**environment)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("acpx: manual update only: cannot read No-Mistakes acpx_path", result.stdout)
        self.assertFalse(self.npm_changes())
        self.assert_safe_clone_actions()
        self.assert_no_actions()

    def test_update_offers_each_native_upgrade_with_consent_and_reports_decline_and_failure(self):
        self.clone_fixture()
        self.install()
        self.profiles_file({"issue-prepare": {"agent": "claude"}, "issue-implement": {"agent": "cursor"}})
        self.native_layouts("herdr", "codex", "no-mistakes", "claude", "cursor-agent")
        cellar = self.root / "brew/Cellar"
        formula = cellar / "gh/2.88.1/bin/gh"
        formula.parent.mkdir(parents=True)
        shutil.copyfile(self.mock / "mock-cli", formula)
        formula.chmod(0o755)
        (self.mock / "gh").unlink()
        (self.mock / "gh").symlink_to(formula)
        brew = {"MOCK_BREW_CELLAR": str(cellar)}
        # Prompt order: gh, gh-dash, herdr, codex, no-mistakes, claude, cursor-agent (this Gum is not brew-owned).
        result = self.interactive_update(["y", "n", "y", "n", "y", "y", "y"], MOCK_UPDATE_FAIL="cursor-agent", **brew)
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn(["upgrade", "gh"], [c["args"] for c in self.calls("brew")])
        self.assertFalse([c for c in self.calls("brew") if c["args"][:1] == ["upgrade"] and c["args"] != ["upgrade", "gh"]])
        self.assertFalse([c for c in self.calls("gh") if c["args"][:2] == ["extension", "upgrade"]])
        self.assertEqual(self.native_updates("herdr"), [["update"]])
        self.assertFalse(self.native_updates("codex"))
        # Stable channel only: never --beta, --force, or --yes.
        self.assertEqual(self.native_updates("no-mistakes"), [["update"]])
        self.assertEqual(self.native_updates("claude"), [["update"]])
        self.assertEqual(self.native_updates("cursor-agent"), [["update"]])
        self.assertIn("Declined; gh-dash extension was left unchanged.", result.stdout)
        self.assertIn("Declined; Codex was left unchanged.", result.stdout)
        self.assertIn("Gum: manual update only", result.stdout)
        self.assertIn("FAILED: cursor-agent update exited with status 91. It may have changed Cursor CLI before failing; "
                      "nothing was rolled back.", result.stdout)
        # Setup and doctor still decide readiness after the failed optional upgrade.
        self.assertIn("Installation: installed", result.stdout)
        self.assertIn("Runtime: make setup passed, including the doctor checks.", result.stdout)
        self.assertIn("FAILED optional upgrade (may be partly changed; see setup/doctor above): cursor-agent", result.stdout)
        self.assertIn("Updater completed (updated or already current): gh herdr no-mistakes claude", result.stdout)
        self.assertIn("Finished; Herdr is still herdr version 0.20.0 (already current).", result.stdout)
        # Declining every offer leaves the working installation in place and succeeds.
        self.log.write_text("")
        result = self.interactive_update(["n"] * 7, **brew)
        self.assert_success(result)
        self.assertIn("Declined (left unchanged): gh gh-dash herdr codex no-mistakes claude cursor-agent", result.stdout)
        self.assertFalse([c for c in self.calls("brew") if c["args"][:1] == ["upgrade"]])
        for tool in ("herdr", "codex", "claude", "cursor-agent", "no-mistakes"):
            self.assertFalse(self.native_updates(tool), tool)
        self.assert_no_actions()

    def test_update_gives_cursor_guidance_when_its_updater_would_replace_unrelated_commands(self):
        self.clone_fixture()
        self.install()
        self.profiles_file({"issue-prepare": {"agent": "cursor"}, "issue-implement": {"agent": "cursor"}})
        self.native_layouts("cursor-agent")
        local_bin = self.home / ".local/bin"
        ide = self.root / "cursor ide/cursor"
        ide.parent.mkdir()
        ide.write_text("#!/bin/sh\necho ide\n")
        (local_bin / "agent").unlink()
        (local_bin / "cursor").unlink()
        for unrelated in ("agent", "cursor"):
            with self.subTest(unrelated):
                if unrelated == "agent":
                    (local_bin / "agent").write_text("#!/bin/sh\necho my agent\n")
                else:
                    (local_bin / "agent").unlink()
                    (local_bin / "cursor").symlink_to(ide)
                kept = {path: (path.is_symlink() and os.readlink(path), path.read_bytes())
                        for path in (local_bin / "agent", local_bin / "cursor", ide) if path.exists()}
                self.log.write_text("")
                result = self.interactive_update(["y"] * 8)
                self.assert_success(result)
                self.assertIn("Cursor CLI: manual update only: its updater also replaces", result.stdout)
                self.assertFalse(self.native_updates("cursor-agent"))
                for path, content in kept.items():
                    self.assertEqual((path.is_symlink() and os.readlink(path), path.read_bytes()), content, path)

    def test_stable_no_mistakes_update_leaves_a_busy_daemon_alone(self):
        self.clone_fixture()
        self.install()
        self.native_layouts("no-mistakes")
        result = self.interactive_update(["y"] * 8, MOCK_NM_ACTIVE_RUNS="1")
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn("refusing to update while 1 pipeline run is active", result.stdout)
        self.assertIn("they were left running: make update never passes --force or --beta", result.stdout)
        self.assertEqual(self.native_updates("no-mistakes"), [["update"]])
        self.assertIn(["extension", "upgrade", "dash"], [c["args"] for c in self.calls("gh")])
        self.assertIn("Installation: installed", result.stdout)
        self.assertIn("FAILED optional upgrade (may be partly changed; see setup/doctor above): no-mistakes", result.stdout)

    def test_update_without_terminal_skips_upgrades_and_gives_guidance(self):
        self.clone_fixture()
        self.install()
        self.native_layouts("herdr", "codex", "claude", "cursor-agent")
        result = self.update(MOCK_AGENT_HELP="old")
        self.assert_success(result)
        self.assertIn("Herdr (herdr version 0.20.0): native installer at " + str(self.home / ".local/bin/herdr"),
                      result.stdout)
        self.assertIn("Skipped without an interactive terminal; no approval was assumed. Run herdr update yourself",
                      result.stdout)
        # A CLI that does not list its updater gets guidance instead of a guessed command.
        self.assertIn("Codex: manual update only: the installed codex does not list an update command", result.stdout)
        self.assertIn("Claude Code: manual update only: the installed claude does not list an update command", result.stdout)
        self.assertIn("Skipped without a terminal: gh-dash herdr cursor-agent", result.stdout)
        for tool in ("herdr", "codex", "claude", "cursor-agent", "no-mistakes"):
            self.assertFalse(self.native_updates(tool), tool)
        self.assert_no_actions()

    def test_update_reports_failed_setup_after_fast_forward_and_keeps_the_runtime(self):
        git, publish = self.clone_fixture()
        self.install()
        worker = "scripts/integrations/gh-dash/gh-dash-codex-issue.sh"
        installed = (self.installed / worker).read_bytes()
        upstream = publish(worker, "#!/usr/bin/env bash\nif\n", "Broken worker")
        result = self.update()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(git(self.bundle, "rev-parse", "HEAD"), upstream)
        self.assertIn("replacement bundle failed validation; existing installation preserved", result.stderr)
        self.assertIn("Runtime: make setup did not pass", result.stdout)
        self.assertEqual((self.installed / worker).read_bytes(), installed)

    def test_mocked_ubuntu_update_upgrades_only_the_apt_owned_package(self):
        if not Path("/etc/os-release").exists() or not re.search(r'^ID=["\']?ubuntu', Path("/etc/os-release").read_text(), re.M):
            self.skipTest("Ubuntu detection reads the native os-release file")
        ubuntu = {"MOCK_OS": "Linux", "MOCK_ARCH": "x86_64"}
        self.clone_fixture()
        self.assert_success(self.interactive_setup("y", **ubuntu))
        self.env["PATH"] = str(self.wrapper.parent) + os.pathsep + str(self.mock)
        system = self.root / "usr bin/gum"
        system.parent.mkdir()
        shutil.copyfile(self.mock / "mock-cli", system)
        system.chmod(0o755)
        (self.mock / "gum").unlink()
        (self.mock / "gum").symlink_to(system)
        self.log.write_text("")
        result = self.interactive_update(["y"] * 8, MOCK_DPKG=json.dumps({str(system): "gum"}), **ubuntu)
        self.assert_success(result)
        self.assertEqual([c["args"] for c in self.calls("sudo")],
                         [["apt-get", "update"], ["apt-get", "install", "-y", "--only-upgrade", "--no-install-recommends", "gum"]])
        self.assertIn("GitHub CLI: manual update only", result.stdout)
        self.assertIn("Updater completed (updated or already current): gh-dash gum", result.stdout)
        self.assertFalse([c for c in self.calls("brew") if c["args"][:1] in (["upgrade"], ["install"])])
        self.assert_no_actions()

    def test_update_confirms_with_gum_defaulting_to_no_and_cancel_or_unrunnable_gum_changes_nothing(self):
        self.clone_fixture()
        self.install()
        self.native_layouts("herdr")
        upgrades = lambda: ([c for c in self.calls("gh") if c["args"][:2] == ["extension", "upgrade"]]
                            + self.native_updates("herdr"))
        # Prompt order: gh-dash, herdr (the mock GitHub CLI and Gum are not brew- or apt-owned). Enter takes No.
        self.log.write_text("")
        result = self.interactive_update(["", ""])
        self.assert_success(result)
        self.assertEqual(self.gum_confirms(), [
            ["confirm", "--default=false", "Run " + command + " now? It decides itself whether a newer release exists."]
            for command in ("gh extension upgrade dash", "herdr update")])
        self.assertIn("Declined (left unchanged): gh-dash herdr", result.stdout)
        self.assertNotIn("[y/N]", result.stdout)
        self.assertFalse(upgrades())
        # Cancelling Gum (ctrl+c) stops make update before any upgrade or setup rerun.
        self.log.write_text("")
        result = self.interactive_update(["<cancel>"])
        self.assertEqual(result.returncode, 130, result.stdout)
        self.assertIn("Cancelled; gh-dash extension was left unchanged and make update stopped before rerunning setup.",
                      result.stdout)
        self.assertNotIn("== Refreshing the managed runtime", result.stdout)
        self.assertFalse(upgrades())
        # A Gum that cannot run asks nothing and approves nothing; setup then offers its repair with a plain prompt.
        self.log.write_text("")
        result = self.interactive_update(["n"], MOCK_GUM="broken")
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn("Skipped: Gum cannot run to ask for consent; no approval was assumed.", result.stdout)
        self.assertIn("Skipped without a runnable Gum (no approval assumed): gh-dash herdr", result.stdout)
        self.assertIn("dependencies pending: gum", result.stdout)
        self.assertIn("Runtime: make setup did not pass", result.stdout)
        self.assertFalse(self.gum_confirms())
        self.assertFalse(upgrades())
        self.assertFalse([c for c in self.calls("brew") if c["args"][:1] in (["install"], ["reinstall"], ["upgrade"])])
        self.assert_safe_clone_actions()
        self.assert_no_actions()

    def test_ghd_update_runs_make_update_in_the_recorded_clone_from_any_directory(self):
        git, publish = self.clone_fixture()
        self.install()
        record = self.installed / ".mini-factory-clone"
        self.assertEqual(record.read_text(), str(self.bundle) + "\n")
        repo, repo_git = self.source_repo()
        repo_head = repo_git("rev-parse", "HEAD")
        elsewhere = self.root / "not a repository"
        elsewhere.mkdir()
        upstream = publish("README.md", (self.bundle / "README.md").read_text() + "\nUpstream release note.\n")
        update = {"MOCK_CLONE_UPDATE": "1"}
        # From another Git repository: only the recorded clone is fetched, fast-forwarded, and set up.
        result = self.run_script(self.wrapper, "update", cwd=repo, env=update)
        self.assert_success(result)
        self.assertIn("Clone: fast-forwarded main", result.stdout)
        self.assertEqual(git(self.bundle, "rev-parse", "HEAD"), upstream)
        self.assertIn("Upstream release note.", (self.installed / "README.md").read_text())
        self.assertIn("Runtime: make setup passed, including the doctor checks.", result.stdout)
        self.assertEqual(repo_git("rev-parse", "HEAD"), repo_head)
        self.assertEqual(repo_git("status", "--porcelain"), "")
        # In the caller's checkout only ghd's read-only check of the recorded clone runs.
        self.assertEqual([c["args"] for c in self.calls() if c["cwd"] == str(repo)],
                         [["-C", str(self.bundle), "rev-parse", "--show-toplevel"]])
        self.assertFalse([c for c in self.calls("gh") if c["args"][:1] == ["dash"] and "--config" in c["args"]])
        # Already current: a second run from outside any repository is safe.
        result = self.run_script(self.wrapper, "update", cwd=elsewhere, env=update)
        self.assert_success(result)
        self.assertIn("Clone: already up to date with origin/main", result.stdout)
        self.assertEqual(git(self.bundle, "rev-parse", "HEAD"), upstream)
        self.assertEqual(record.read_text(), str(self.bundle) + "\n")
        self.assert_safe_clone_actions()
        self.assert_no_actions()

    def test_ghd_update_refuses_arguments_and_a_missing_moved_or_other_checkout_without_changes(self):
        git, publish = self.clone_fixture()
        self.install()
        record = self.installed / ".mini-factory-clone"
        repo, _ = self.source_repo()
        (repo / "subdirectory").mkdir()
        recovery = "run make setup from your retained mini-factory clone to record it"
        upstream = publish("README.md", "Upstream rewrite\n")
        start = git(self.bundle, "rev-parse", "HEAD")

        def refused(message, *args, fetched=False):
            self.log.write_text("")
            result = self.run_script(self.wrapper, "update", *args, cwd=repo, env={"MOCK_CLONE_UPDATE": "1"})
            self.assertNotEqual(result.returncode, 0, result.stdout)
            self.assertIn(message, result.stderr)
            # Only a diverged main is detected after the (read-only) fetch; nothing is ever merged.
            self.assertEqual(fetched, bool([c for c in self.calls("git") if "fetch" in c["args"]]))
            self.assertFalse([c for c in self.calls("git") if "merge" in c["args"]])
            self.assertFalse(self.calls("gh"), "neither gh-dash nor setup ran")
            return result

        for args in (("now",), ("--force",), ("",)):
            with self.subTest(args=args):
                refused("usage: ghd update (no arguments; it runs make update in your retained mini-factory clone)", *args)
        record.unlink()
        refused("no recorded mini-factory clone (" + str(record) + "); " + recovery)
        # The record is data, never shell: a relative path or another checkout is refused, never selected.
        marker = self.root / "executed"
        for recorded in ("$(touch " + str(marker) + ")", str(repo), str(repo / "subdirectory")):
            with self.subTest(recorded=recorded):
                record.write_text(recorded + "\n")
                refused(recovery)
        self.assertFalse(marker.exists())
        record.write_text(str(self.bundle) + "\n")
        moved = self.root / "moved clone"
        self.bundle.rename(moved)
        refused("the recorded mini-factory clone " + str(self.bundle) + " is missing, moved, or no longer a Git checkout; "
                + recovery)
        self.assertEqual(git(moved, "rev-parse", "HEAD"), start)
        # A failed setup from the moved clone keeps the record; a successful one publishes the new location.
        worker = moved / "scripts/integrations/gh-dash/gh-dash-codex-issue.sh"
        content = worker.read_bytes()
        worker.write_text("#!/usr/bin/env bash\nif\n")
        self.assertNotEqual(self.run_script(moved / "scripts/setup.sh").returncode, 0)
        self.assertEqual(record.read_text(), str(self.bundle) + "\n")
        worker.write_bytes(content)
        self.assert_success(self.run_in_terminal([str(moved / "scripts/setup.sh")], self.env, b"y\n" * 24))
        self.assertEqual(record.read_text(), str(moved) + "\n")
        # The updater's own refusals still apply: another branch, then a diverged main, change nothing.
        git(moved, "checkout", "-q", "-b", "feature/local")
        refused("on branch feature/local: make update runs only on main and never switches branches")
        self.assertEqual(git(moved, "branch", "--show-current"), "feature/local")
        git(moved, "checkout", "-q", "main")
        git(moved, "commit", "-q", "--allow-empty", "-m", "Local commit")
        local = git(moved, "rev-parse", "HEAD")
        result = refused("have diverged", fetched=True)
        self.assertIn("Nothing was changed.", result.stderr)
        self.assertEqual(git(moved, "rev-parse", "HEAD"), local)
        self.assertNotEqual(local, upstream)
        self.assert_no_actions(allow_onboarding=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
