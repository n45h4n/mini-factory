#!/usr/bin/env python3
"""Mini-Factory agent profiles for the gh-dash issue i/I and PR I keys.

Saved choices apply only when a fresh Herdr agent starts. This tool never
starts, stops, or changes an agent and never edits the No-Mistakes pipeline
agent. Picker metadata comes from local native CLIs only and is a convenience,
not proof of account access.
"""

import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import tempfile

USAGE = """usage: mf-config [show | --help]

  mf-config        edit one agent profile in Gum (needs an interactive terminal)
  mf-config show   print the effective profiles without a terminal
"""
# Internal, used by setup, doctor, and the workers:
#   mf-config agent ROLE             print the effective harness and its source
#   mf-config launch-args ROLE KIND  print native launch options, one per line
#   mf-config set-agent pr-review KIND  save setup's PR_REVIEW_AGENT choice

HARNESSES = {"codex": "Codex", "claude": "Claude Code", "cursor": "Cursor"}
COMMANDS = {"codex": "codex", "claude": "claude", "cursor": "cursor-agent"}
ROLES = {
    "issue-prepare": "Issues i - preparer",
    "issue-implement": "Issues I - implementer",
    "pr-review": "PRs I - reviewer",
}
KNOBS = {"codex": ("model", "effort", "fast"), "claude": ("model", "effort"), "cursor": ("model",)}
SOURCES = {
    "override": "mf-config per-role selection",
    "shared": "shared issue agent (no per-role override)",
    "default": "default (no saved selection)",
}
# Each PR reviewer starts in its native interactive read-only mode; the worker adds the
# options, and a fresh launch first checks that the installed CLI offers them:
# (options that must be offered, option whose help must list the mode, mode).
REVIEW_MODES = {
    "codex": (("--ask-for-approval", "--strict-config", "--config", "--cd"), None, None),
    "claude": (("--permission-mode", "--add-dir"), "--permission-mode", "plan"),
    "cursor": (("--mode", "--add-dir"), "--mode", "ask"),
}
REVIEW_MODE_NAMES = {"codex": "permission profile :read-only, no network", "claude": "Plan mode", "cursor": "Ask mode"}
# Codex 0.154.0 introduced the explicit service_tier routing used for Fast on/off.
CODEX_FAST_MINIMUM = (0, 154, 0)
CODEX_EFFORTS = ("low", "medium", "high", "xhigh")
CLAUDE_EFFORTS = ("low", "medium", "high", "xhigh", "max")
CLAUDE_ALIASES = ("opus", "sonnet", "haiku")
NATIVE = "Native default (no override)"
CUSTOM_MODEL = "Custom model ID (unverified)"
CUSTOM_EFFORT = "Custom value (unverified)"
# Saved values become single argv entries: no whitespace/control characters and
# no leading dash, so a value can never be read as another native option.
VALUE = re.compile(r"[^\s\x00-\x1f\x7f-][^\s\x00-\x1f\x7f]{0,199}")


class ConfigError(Exception):
    pass


class Cancelled(Exception):
    pass


def config_directory():
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    if not os.path.isabs(base):
        raise ConfigError("XDG_CONFIG_HOME must be an absolute path")
    return Path(base) / "mini-factory"


def profiles_path():
    return config_directory() / "agent-profiles.json"


def shared_path():
    return config_directory() / "issue-agent"


def shared_agent():
    """The make setup ISSUE_AGENT choice; None when it was never saved."""
    path = shared_path()
    if not path.exists() and not path.is_symlink():
        return None
    try:
        value = path.read_text(encoding="utf-8").split("\n", 1)[0] if path.is_file() else None
    except (OSError, UnicodeError):
        value = None
    if value not in HARNESSES:
        raise ConfigError("invalid issue agent setting in " + str(path)
                          + "; run make setup ISSUE_AGENT=claude|codex|cursor")
    return value


def unique_fields(pairs):
    document = {}
    for key, value in pairs:
        if key in document:
            raise ValueError("duplicate field " + repr(key))
        document[key] = value
    return document


def validate_profile(role, profile, where):
    location = where + ": " + role
    if not isinstance(profile, dict):
        raise ConfigError(location + " must be an object")
    agent = profile.get("agent")
    if agent not in HARNESSES:
        raise ConfigError(location + ": agent must be codex, claude, or cursor")
    unknown = sorted(set(profile) - {"agent", *KNOBS[agent]})
    if unknown:
        raise ConfigError(location + ": unsupported field(s) for " + HARNESSES[agent] + ": " + ", ".join(unknown))
    for key in ("model", "effort"):
        if key in profile and not (isinstance(profile[key], str) and VALUE.fullmatch(profile[key])):
            raise ConfigError(location + ": " + key + " must be a native value without spaces or a leading dash")
    if "fast" in profile and type(profile["fast"]) is not bool:
        raise ConfigError(location + ": fast must be true or false")
    return dict(profile)


def load_profiles(path):
    """Return (profiles, raw bytes or None). Invalid files are reported, never repaired."""
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return {}, None
    except OSError as error:
        raise ConfigError("cannot read " + str(path) + ": " + str(error))
    hint = "; fix or remove it, then rerun mf-config"
    try:
        document = json.loads(raw.decode("utf-8"), object_pairs_hook=unique_fields)
    except (UnicodeError, ValueError) as error:
        raise ConfigError(str(path) + ": invalid JSON (" + str(error) + ")" + hint)
    if (not isinstance(document, dict) or set(document) - {"version", "profiles"}
            or document.get("version") != 1 or not isinstance(document.get("profiles", {}), dict)):
        raise ConfigError(str(path) + ': expected {"version": 1, "profiles": {...}}' + hint)
    profiles = {}
    for role, profile in document.get("profiles", {}).items():
        if role not in ROLES:
            raise ConfigError(str(path) + ": unknown profile " + repr(role) + hint)
        profiles[role] = validate_profile(role, profile, str(path))
    return profiles, raw


def effective(role, profiles, shared):
    """Precedence: per-role mf-config selection, then shared issue agent, then Codex."""
    if role in profiles:
        return dict(profiles[role]), "override"
    if role != "pr-review" and shared:
        return {"agent": shared}, "shared"
    return {"agent": "codex"}, "default"


def native_arguments(profile):
    """Only explicit knobs become options; an unset knob keeps the native default."""
    agent, argv = profile["agent"], []
    if "model" in profile:
        argv += ["--model", profile["model"]]
    if agent == "codex":
        if "effort" in profile:
            argv += ["--config", "model_reasoning_effort=" + json.dumps(profile["effort"])]
        if "fast" in profile:
            # Explicit standard routing ("default") suppresses inherited Fast; unset leaves it alone.
            argv += ["--config", "service_tier=" + json.dumps("fast" if profile["fast"] else "default")]
            if profile["fast"]:
                argv += ["--config", "features.fast_mode=true"]
    elif agent == "claude" and "effort" in profile:
        argv += ["--effort", profile["effort"]]
    return argv


def probe(argv, timeout=15, limit=4 * 1024 * 1024):
    """Bounded, noninteractive local metadata; None when unavailable."""
    if shutil.which(argv[0]) is None:
        return None
    try:
        with tempfile.TemporaryDirectory(prefix="mf-config-") as directory, tempfile.TemporaryFile() as output:
            child = subprocess.Popen(argv, cwd=directory, stdin=subprocess.DEVNULL, stdout=output,
                                     stderr=subprocess.DEVNULL, start_new_session=True)
            try:
                status = child.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                os.killpg(child.pid, signal.SIGKILL)
                child.wait()
                return None
            output.seek(0)
            raw = output.read(limit + 1)
    except OSError:
        return None
    if status or len(raw) > limit:
        return None
    return raw.decode("utf-8", "replace")


def flag_available(text, flag):
    return re.search(re.escape(flag) + r"(?![\w-])", text) is not None


def codex_version():
    match = re.search(r"(\d+)\.(\d+)\.(\d+)", probe(["codex", "--version"]) or "")
    return tuple(map(int, match.groups())) if match else None


def require_support(profile, role):
    """Refuse a fresh launch whose explicit knobs, or reviewer read-only mode, the installed CLI cannot accept."""
    agent = profile["agent"]
    needed = ["--model"] if "model" in profile else []
    if agent == "codex" and ("effort" in profile or "fast" in profile):
        needed.append("--config")
    if agent == "claude" and "effort" in profile:
        needed.append("--effort")
    review = REVIEW_MODES[agent] if role == "pr-review" else None
    if review:
        needed += [flag for flag in review[0] if flag not in needed]
    if not needed:
        return
    command, label = COMMANDS[agent], HARNESSES[agent]
    help_text = probe([command, "--help"])
    if help_text is None:
        raise ConfigError("cannot read " + command + " --help to verify the " + label
                          + (" read-only reviewer launch" if review else " saved options") + "; repair "
                          + label + " or choose native defaults with mf-config")
    missing = [flag for flag in needed if not flag_available(help_text, flag)]
    if review and review[1] and review[1] not in missing and not re.search(
            r"\b" + review[2] + r"\b", option_block(help_text, review[1])):
        missing.append(review[1] + " " + review[2])
    if missing:
        if review:
            raise ConfigError("the installed " + command + " does not offer " + ", ".join(missing) + ", needed for "
                              "the interactive read-only PR reviewer (" + REVIEW_MODE_NAMES[agent] + "); update "
                              + label + " or choose another PR reviewer with mf-config")
        raise ConfigError("the installed " + command + " does not offer " + ", ".join(missing)
                          + "; update " + label + " or choose native defaults with mf-config")
    if agent == "codex" and "fast" in profile:
        version = codex_version()
        if version is None or version < CODEX_FAST_MINIMUM:
            raise ConfigError("the saved Codex Fast choice needs Codex 0.154.0 or newer; update Codex"
                              " or choose the native default Fast setting with mf-config")


def describe(profile):
    agent = profile["agent"]

    def value(key):
        if key not in profile:
            return "native default"
        if key == "fast":
            return "on" if profile["fast"] else "off"
        return profile[key]

    if agent == "codex":
        return "model: " + value("model") + "; reasoning effort: " + value("effort") + "; Fast: " + value("fast")
    if agent == "claude":
        return "model: " + value("model") + "; effort: " + value("effort")
    return "model: " + value("model") + " (Cursor's model ID owns its variant/effort)"


def show(profiles, shared, path, saved):
    print("Mini-Factory agent profiles: " + str(path) + ("" if saved else " (none saved yet)"))
    print("Shared issue agent: " + (HARNESSES[shared] if shared else "not set (Codex default)")
          + " (" + str(shared_path()) + "; set with make setup ISSUE_AGENT=claude|codex|cursor)")
    for role, label in ROLES.items():
        profile, source = effective(role, profiles, shared)
        detail = SOURCES[source]
        if role == "pr-review":
            detail = ("mf-config selection" if source == "override" else "default (no saved selection)")
            detail += ("; interactive, read-only (" + REVIEW_MODE_NAMES[profile["agent"]]
                       + "); findings stay in its terminal")
        print("\n" + label + ": " + HARNESSES[profile["agent"]] + " - " + detail)
        print("  " + describe(profile))
    print("\nPrecedence for each issue key: its mf-config selection, then the shared issue agent, then Codex.")
    print("The PR reviewer uses its mf-config selection, else Codex. It starts in that native read-only mode and is")
    print("asked to report findings only in its terminal: no file edits, PR comments, reviews, or other GitHub writes.")
    print("Profiles apply only when a fresh Herdr agent starts. A working, blocked, or idle agent keeps its original")
    print("harness and options; close it (exit the agent in its pane), then press the key again to relaunch.")
    print("mf-config never changes the No-Mistakes pipeline agent (no-mistakes/config.yaml in your clone).")


def gum(command, header, options=(), current=None):
    argv = ["gum", command, "--header", header]
    if command == "input":
        argv += ["--value", current or ""]
    elif current:
        # Gum splits --selected on unescaped commas, which Cursor model IDs may contain.
        argv += ["--selected", current.replace(",", "\\,")]
    argv.extend(options)
    result = subprocess.run(argv, stdout=subprocess.PIPE, text=True)
    if result.returncode:
        raise Cancelled()
    value = result.stdout[:-1] if result.stdout.endswith("\n") else result.stdout
    if command == "choose" and value not in options:
        raise ConfigError("invalid selection for '" + header + "'")
    return value


def confirm(question):
    status = subprocess.run(["gum", "confirm", question]).returncode
    if status not in (0, 1):
        raise Cancelled()
    return status == 0


def checked(value, what):
    if not VALUE.fullmatch(value):
        raise ConfigError("invalid " + what + " " + repr(value)
                          + ": use the exact native value without spaces or a leading dash")
    return value


def choose_value(header, catalog, saved, custom, what):
    """Native default first, then local metadata, the saved value, and custom input."""
    options = [NATIVE] + [item for item in catalog if item != saved]
    if saved:
        options.insert(1, saved)
    options.append(custom)
    choice = gum("choose", header, options, saved or NATIVE)
    if choice == NATIVE:
        return None
    if choice == custom:
        return checked(gum("input", header + " - exact " + what + " (custom/unverified)", current=saved), what)
    return choice


def codex_catalog():
    """Local Codex model cache rows by slug; absence or staleness only empties the picker."""
    path = Path(os.environ.get("CODEX_HOME") or str(Path.home() / ".codex")) / "models_cache.json"
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
        rows = document["models"]
        models = {row["slug"]: row for row in rows if isinstance(row, dict) and isinstance(row.get("slug"), str)
                  and VALUE.fullmatch(row["slug"]) and row.get("visibility") != "hide"}
        version = document.get("client_version")
    except (OSError, UnicodeError, ValueError, KeyError, TypeError, AttributeError):
        return {}, path, None
    return models, path, version if isinstance(version, str) else None


def codex_advertises_fast(row):
    tiers, speeds = row.get("service_tiers") or [], row.get("additional_speed_tiers") or []
    return ((isinstance(tiers, list) and any(isinstance(tier, dict) and tier.get("id") in ("fast", "priority")
                                             for tier in tiers))
            or (isinstance(speeds, list) and "fast" in speeds))


def choose_codex(label, saved):
    models, cache, cache_version = codex_catalog()
    version = codex_version()
    if not models:
        print("No local Codex model cache at " + str(cache) + "; choose native default or a custom model ID.")
    elif cache_version and version and cache_version != ".".join(map(str, version)):
        print("The local Codex model cache came from Codex " + cache_version + "; it may be stale.")
    model = choose_value(label + ": Codex model (local cache; account access unverified)",
                         list(models), saved.get("model"), CUSTOM_MODEL, "model ID")
    row = models.get(model, {}) if model else {}
    levels = [entry["effort"] for entry in (row.get("supported_reasoning_levels") or [])
              if isinstance(entry, dict) and isinstance(entry.get("effort"), str) and VALUE.fullmatch(entry["effort"])]
    if not levels:
        levels = list(CODEX_EFFORTS)
        print("Reasoning levels for this model are not in the local cache; these common values are unverified.")
    profile = {"agent": "codex"}
    if model:
        profile["model"] = model
    effort = choose_value(label + ": Codex reasoning effort", levels, saved.get("effort"), CUSTOM_EFFORT, "effort")
    if effort:
        profile["effort"] = effort
    fast = choose_fast(label, saved, model, row, version)
    if fast is not None:
        profile["fast"] = fast
    return profile


def choose_fast(label, saved, model, row, version):
    """Offer Fast only for a chosen model whose metadata and installed CLI support it."""
    same_model = saved.get("model") == model
    previous = saved.get("fast") if same_model else None
    routing = version is not None and version >= CODEX_FAST_MINIMUM
    advertised = routing and model is not None and codex_advertises_fast(row)
    if not advertised and previous is None:
        if model is None:
            print("Fast is not offered for the native default model; your native Fast setting stays untouched.")
        elif not routing:
            print("Fast is not offered: the installed Codex lacks Fast routing (needs 0.154.0 or newer).")
        else:
            print("Fast is not offered: local metadata does not advertise Fast for " + model + ".")
        return None
    if not advertised:
        print("The saved Fast " + ("on" if previous else "off") + " choice is kept for review; "
              + "current local metadata or Codex no longer verifies it.")
    current = {True: "On", False: "Off"}.get(previous, NATIVE if same_model and saved else "Off")
    # Unverified Fast may be kept On or turned off, but never newly turned On.
    options = ["Off", "On", NATIVE] if advertised or previous else ["Off", NATIVE]
    choice = gum("choose", label + ": Codex Fast (separate from reasoning effort)", options, current)
    return None if choice == NATIVE else choice == "On"


def cursor_catalog():
    text = probe(["cursor-agent", "--list-models"])
    if text is None:
        print("Cursor's local model list is unavailable (cursor-agent missing, logged out, or offline);"
              " choose native default or a custom model ID.")
        return []
    clean = re.sub(r"\x1b\[[0-9;?]*[A-Za-z]", "", text)
    models = [line.split(" - ", 1)[0].strip() for line in clean.splitlines() if " - " in line]
    return list(dict.fromkeys(model for model in models if VALUE.fullmatch(model)))


def choose_cursor(label, saved):
    print("Cursor's interactive --model selection owns its variant/effort; there is no separate effort choice.")
    model = choose_value(label + ": Cursor model (cursor-agent --list-models; account access unverified)",
                         cursor_catalog(), saved.get("model"), CUSTOM_MODEL, "model ID")
    return {"agent": "cursor", **({"model": model} if model else {})}


def option_block(text, flag):
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if re.match(r"\s*(?:-\w,\s*)?" + re.escape(flag) + r"(?![\w-])", line):
            block = [line]
            for following in lines[index + 1:]:
                if re.match(r"\s*-", following):
                    break
                block.append(following)
            return "\n".join(block)
    return ""


def claude_catalog():
    """Aliases and effort levels from claude --help; built-in fallbacks otherwise."""
    text = probe(["claude", "--help"]) or ""
    aliases = re.findall(r"'([a-z][a-z0-9-]*)'", option_block(text, "--model"))
    match = re.search(r"\(([a-z]+(?:,\s*[a-z]+)+)\)", option_block(text, "--effort"))
    efforts = [value.strip() for value in match.group(1).split(",")] if match else list(CLAUDE_EFFORTS)
    return list(dict.fromkeys(aliases + list(CLAUDE_ALIASES))), efforts


def choose_claude(label, saved):
    aliases, efforts = claude_catalog()
    model = choose_value(label + ": Claude Code model (alias or exact ID; account access unverified)",
                         aliases, saved.get("model"), CUSTOM_MODEL, "model ID")
    effort = choose_value(label + ": Claude Code effort (not every model/account supports every level)",
                          efforts, saved.get("effort"), CUSTOM_EFFORT, "effort")
    profile = {"agent": "claude"}
    if model:
        profile["model"] = model
    if effort:
        profile["effort"] = effort
    return profile


PICKERS = {"codex": choose_codex, "claude": choose_claude, "cursor": choose_cursor}


def edit_role(role, profiles, shared):
    current = profiles.get(role)
    label = ROLES[role].split(" (", 1)[0]
    if role == "pr-review":
        # Codex with only native defaults is the default reviewer, so it saves no override.
        choice = gum("choose", label + ": harness (Codex is the default; each starts read-only)",
                     list(HARNESSES.values()), HARNESSES[current["agent"]] if current else HARNESSES["codex"])
        agent = next(kind for kind, name in HARNESSES.items() if name == choice)
    else:
        inherit = "Shared issue agent: " + HARNESSES[shared or "codex"] + " (no per-role override)"
        options = [inherit] + list(HARNESSES.values())
        choice = gum("choose", label + ": harness", options, HARNESSES[current["agent"]] if current else inherit)
        if choice == inherit:
            return None
        agent = next(kind for kind, name in HARNESSES.items() if name == choice)
    saved = current if current and current["agent"] == agent else {}
    profile = PICKERS[agent](label, saved)
    if role == "pr-review" and profile == {"agent": "codex"}:
        return None
    return profile


def set_agent(role, kind):
    """Setup's PR_REVIEW_AGENT: keep a same-harness profile, else save the bare harness (Codex is the default)."""
    path = profiles_path()
    profiles, before = load_profiles(path)
    current = profiles.get(role)
    if current and current["agent"] == kind:
        return "kept"
    candidate = dict(profiles)
    if kind == "codex":
        candidate.pop(role, None)
    else:
        candidate[role] = {"agent": kind}
    if candidate == profiles:
        return "kept"
    save(path, candidate, before)
    return "saved"


def save(path, profiles, before):
    if path.is_symlink():
        raise ConfigError("refusing to replace the symbolic link " + str(path) + "; nothing was saved")
    try:
        current = path.read_bytes()
    except FileNotFoundError:
        current = None
    if current != before:
        raise ConfigError(str(path) + " changed while mf-config was open; nothing was saved. Rerun mf-config.")
    path.parent.mkdir(parents=True, exist_ok=True)
    document = {"version": 1, "profiles": {role: profiles[role] for role in ROLES if role in profiles}}
    descriptor, temporary = tempfile.mkstemp(prefix=".agent-profiles.", dir=str(path.parent))
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(json.dumps(document, indent=2) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def edit():
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        raise ConfigError("editing needs an interactive terminal (local or SSH); use mf-config show to view profiles")
    if shutil.which("gum") is None:
        raise ConfigError("editing requires Gum; run make setup from your mini-factory clone (make doctor checks it)")
    path = profiles_path()
    profiles, before = load_profiles(path)
    shared = shared_agent()
    show(profiles, shared, path, before is not None)
    print()
    label = gum("choose", "Agent profile to edit", list(ROLES.values()))
    role = next(key for key, name in ROLES.items() if name == label)
    candidate = dict(profiles)
    chosen = edit_role(role, profiles, shared)
    if chosen is None:
        candidate.pop(role, None)
    else:
        candidate[role] = chosen
    new, source = effective(role, candidate, shared)
    print("\nPreview - " + label + ": " + HARNESSES[new["agent"]] + " (" + SOURCES[source] + ")")
    print("  " + describe(new))
    if candidate == profiles:
        print("No change; nothing was saved.")
        return 0
    if not confirm("Save this " + label.split(" (", 1)[0] + " profile for future fresh agents?"):
        raise Cancelled()
    # A completed confirmation is published atomically or not at all.
    handlers = {sig: signal.signal(sig, signal.SIG_IGN) for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)}
    try:
        save(path, candidate, before)
    finally:
        for sig, handler in handlers.items():
            signal.signal(sig, handler)
    print("Saved: " + str(path))
    print("Existing Herdr agents keep their original harness and options. Close one (exit the agent in its pane),")
    print("then press its key again to start a fresh agent with this profile.")
    return 0


def main(argv):
    if argv in (["--help"], ["-h"], ["help"]):
        print(USAGE, end="")
        return 0
    if argv == ["show"]:
        path = profiles_path()
        profiles, raw = load_profiles(path)
        show(profiles, shared_agent(), path, raw is not None)
        return 0
    if len(argv) == 2 and argv[0] == "agent" and argv[1] in ROLES:
        shared = None if argv[1] == "pr-review" else shared_agent()
        profile, source = effective(argv[1], load_profiles(profiles_path())[0], shared)
        print(profile["agent"] + "\n" + source)
        return 0
    if len(argv) == 3 and argv[0] == "launch-args" and argv[1] in ROLES and argv[2] in HARNESSES:
        shared = None if argv[1] == "pr-review" else shared_agent()
        profile, _ = effective(argv[1], load_profiles(profiles_path())[0], shared)
        if profile["agent"] != argv[2]:
            raise ConfigError("the " + ROLES[argv[1]] + " harness changed to " + HARNESSES[profile["agent"]]
                              + " during this launch; press the key again")
        require_support(profile, argv[1])
        for argument in native_arguments(profile):
            print(argument)
        return 0
    if len(argv) == 3 and argv[0] == "set-agent" and argv[1] == "pr-review" and argv[2] in HARNESSES:
        print(set_agent(argv[1], argv[2]) + ": " + str(profiles_path()))
        return 0
    if argv:
        print(USAGE, end="", file=sys.stderr)
        return 2
    return edit()


def cancel(_signal, _frame):
    raise Cancelled()


if __name__ == "__main__":
    for signal_number in (signal.SIGHUP, signal.SIGTERM):
        signal.signal(signal_number, cancel)
    try:
        sys.exit(main(sys.argv[1:]))
    except (Cancelled, KeyboardInterrupt):
        print("\nCancelled; saved preferences are unchanged.", file=sys.stderr)
        sys.exit(130)
    except ConfigError as error:
        print("mf-config: " + str(error), file=sys.stderr)
        sys.exit(1)
