#!/usr/bin/env python3
"""Mini-Factory editor for the No-Mistakes global config (nm-config).

Reads and edits only the live ${NM_HOME:-$HOME/.no-mistakes}/config.yaml link
target: the tracked no-mistakes/config.yaml in the retained mini-factory clone.
Each change is a small line edit of one known field. Comments, unknown fields,
and unrelated YAML stay byte for byte; a YAML form this small parser does not
understand is refused for that edit, never rewritten. The installed No-Mistakes
loads each candidate in a disposable NM_HOME before the live file is replaced
atomically. nm-config never starts, stops, or reconfigures runs or the daemon.
"""

import difflib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import signal
import stat
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
# Reuse mf-config's Gum helpers and local model pickers (loaded by path: python -I omits the script directory).
_SPEC = importlib.util.spec_from_file_location("mf_config", str(HERE / "mf_config.py"))
mf = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(mf)
ConfigError, Cancelled = mf.ConfigError, mf.Cancelled

USAGE = """usage: nm-config [show | --help]

  nm-config        edit No-Mistakes global defaults in Gum (needs an interactive terminal)
  nm-config show   print the configured global defaults without a terminal
"""

# Native No-Mistakes harnesses (v1.84.0 global config reference), independent of mf-config's issue agents.
HARNESSES = {"codex": "Codex", "claude": "Claude Code", "grok": "Grok", "opencode": "OpenCode", "pi": "Pi",
             "copilot": "Copilot", "rovodev": "Rovo Dev", "antigravity": "Antigravity", "cursor": "Cursor",
             "devin": "Devin"}
PIPELINE_AGENTS = ("auto",) + tuple(HARNESSES)
COMMANDS = {"codex": "codex", "claude": "claude", "grok": "grok", "opencode": "opencode", "pi": "pi",
            "copilot": "copilot", "rovodev": "acli", "antigravity": "agy", "cursor": "cursor-agent",
            "devin": "devin"}
# Effort levels the stable No-Mistakes adapters accept (v1.84.0 global config reference), not each
# CLI's own menu; Grok and OpenCode pass any common level on to the model/provider. ACP aliases
# (Cursor, Devin) run through acpx, which takes a model only. Rovo Dev and Antigravity are absent:
# No-Mistakes can set neither knob for them, and agent_config for them is a native config error.
COMMON_EFFORTS = ("minimal", "low", "medium", "high", "xhigh", "max")
EFFORTS = {"codex": ("minimal", "low", "medium", "high"),
           "claude": ("low", "medium", "high", "xhigh", "max"),
           "grok": COMMON_EFFORTS, "opencode": COMMON_EFFORTS, "pi": COMMON_EFFORTS, "copilot": COMMON_EFFORTS,
           "cursor": (), "devin": ()}
# Raw agent_args_override flags that natively pin a knob (Codex -c/--config assignments handled separately).
PIN_FLAGS = {"codex": {"model": ("-m", "--model")},
             "claude": {"model": ("--model",), "effort": ("--effort",)},
             "grok": {"model": ("--model", "-m"), "effort": ("--reasoning-effort", "--effort")},
             "copilot": {"model": ("--model",), "effort": ("--effort", "--reasoning-effort")},
             "pi": {"model": ("--model",), "effort": ("--thinking",)}}
# First-class ACP aliases share one agent_config/review profile with their acp:<target> spelling.
ACP_ALIASES = {"cursor": "acp:cursor", "devin": "acp:devin"}
ROLES = {"reviewer": "reviewer", "fixer": "fixer",
         "reviewer_after_round": "later-round reviewer", "fixer_after_round": "later-round fixer"}
# Native defaults documented for v1.84.0, shown only for unset fields.
AUTO_FIX = {"rebase": 3, "review": 0, "test": 3, "lint": 3, "ci": 3}
MENU = (("agent", "Pipeline agent (agent)"),
        ("agent_config", "Harness model/effort defaults (agent_config)"),
        ("reviewer", "Reviewer (review_agents.reviewer)"),
        ("fixer", "Fixer (review_agents.fixer)"),
        ("reviewer_after_round", "Later-round reviewer (review_agents.reviewer_after_round)"),
        ("fixer_after_round", "Later-round fixer (review_agents.fixer_after_round)"),
        ("auto_fix", "Auto-fix attempts (auto_fix)"),
        ("session_reuse", "Fixer session reuse (session_reuse)"))
SAVE = "Review and save changes"
QUIT = "Quit without saving"
NATIVE = "Native default (clear override)"
INHERIT = "Inherit agent_config (clear)"
ROLE_INHERIT = "Inherit the pipeline agent (clear override)"
OVERLAY_CLEAR = "No later-round override (clear)"
KEEP = "Keep current: "
SESSION_NATIVE = "Native default (clear; true in v1.84.0)"
NATIVE_ENVIRONMENT = dict(NO_MISTAKES_NO_UPDATE_CHECK="1", NO_MISTAKES_TELEMETRY="0")


# A deliberately small YAML subset: block mappings, one-line plain or quoted scalars, and
# scalar lists (block or one-line flow). Everything else is opaque or refused.

class Unsafe(Exception):
    """A YAML form nm-config does not change; the user edits it manually."""

    def __init__(self, reason, line=None):
        super().__init__(reason + ("" if line is None else " (line " + str(line + 1) + ")"))


KEY = re.compile(r"""("(?:[^"\\]|\\.)*"|'(?:[^']|'')*'|[^\s#'"&*!|>%@`{}\[\],?:-](?:[^\s:]|:(?=\S))*):(?=[ \t]|$)""")
COMMENT_OR_END = re.compile(r"[ \t]+#|[ \t]*$")
FLOW_PLAIN = re.compile(r"[^,\[\]{}#]*")
PLAIN_SAFE = re.compile(r"[A-Za-z][A-Za-z0-9_./@+-]*")
YAML11_WORDS = {"y", "n", "yes", "no", "on", "off", "true", "false", "null"}


def plain(raw):
    if raw in ("", "~", "null", "Null", "NULL"):
        return None
    if raw in ("true", "True", "TRUE", "false", "False", "FALSE"):
        return raw.lower() == "true"
    if re.fullmatch(r"[-+]?[0-9]+", raw):
        return int(raw)
    return raw


def skip(line, index):
    while index < len(line) and line[index] in " \t":
        index += 1
    return index


def token(line, index, number):
    """One plain or quoted scalar starting at index: (value, end)."""
    first = line[index]
    if first == '"':
        end = index + 1
        while end < len(line) and line[end] != '"':
            end += 2 if line[end] == "\\" else 1
        if end >= len(line):
            raise Unsafe("multi-line double-quoted value", number)
        try:
            return json.loads(line[index:end + 1]), end + 1
        except ValueError:
            raise Unsafe("unsupported escape in a double-quoted value", number)
    if first == "'":
        end = index + 1
        while True:
            end = line.find("'", end)
            if end < 0:
                raise Unsafe("multi-line single-quoted value", number)
            if line.startswith("''", end):
                end += 2
                continue
            return line[index + 1:end].replace("''", "'"), end + 1
    if first in "{[&*!|>%@`" or (first in "-?:" and line[index + 1:index + 2] in ("", " ", "\t")):
        raise Unsafe("unsupported YAML form (flow mapping, anchor, alias, tag, block scalar, or nested entry)",
                     number)
    end = COMMENT_OR_END.search(line, index).start()
    raw = line[index:end]
    if re.search(r":(?:[ \t]|$)", raw):
        raise Unsafe("a nested mapping on one line", number)
    return plain(raw), end


def flow_list(line, index, number):
    items, index = [], skip(line, index + 1)
    if line.startswith("]", index):
        return items, index + 1
    while True:
        if index >= len(line):
            raise Unsafe("multi-line flow list", number)
        if line[index] in "'\"":
            value, index = token(line, index, number)
        else:
            raw = FLOW_PLAIN.match(line, index).group().rstrip()
            if not raw or raw[0] in "&*!|>%@`-?:":
                raise Unsafe("unsupported flow list entry", number)
            value, index = plain(raw), index + len(raw)
        items.append(value)
        index = skip(line, index)
        if line.startswith(",", index):
            index = skip(line, index + 1)
            continue
        if line.startswith("]", index):
            return items, index + 1
        raise Unsafe("unsupported flow list", number)


def inline(line, index, number):
    """The value after a colon or list dash: (kind, value, start, stop); kind 'null' means nothing written."""
    index = skip(line, index)
    if index >= len(line) or line[index] == "#":
        return "null", None, index, index
    if line[index] == "[":
        kind, (value, stop) = "list", flow_list(line, index, number)
    else:
        kind, (value, stop) = "scalar", token(line, index, number)
    if line[stop:].strip() and not re.match(r"[ \t]+#", line[stop:]):
        raise Unsafe("unexpected text after a value", number)
    return kind, value, index, stop


def is_entry(body):
    return body == "-" or body.startswith("- ")


def unquote(key):
    if key[0] == '"':
        return json.loads(key)
    if key[0] == "'":
        return key[1:-1].replace("''", "'")
    return key


class Node:
    def __init__(self, key, line, indent):
        self.key, self.line, self.indent, self.end = key, line, indent, line
        self.kind, self.value, self.children = "null", None, {}
        self.colon = self.start = self.stop = 0
        self.comment = False


class Document:
    def __init__(self, text):
        if text.startswith("﻿"):
            raise Unsafe("byte-order mark")
        if "\r" in text:
            raise Unsafe("carriage returns (CRLF line endings)")
        self.text, self.lines, self.content = text, text.split("\n"), []
        start = True
        for number, line in enumerate(self.lines):
            body = line.lstrip(" ")
            if not line.strip() or body.startswith("#"):
                continue
            if start and re.fullmatch(r"---(?:[ \t]+#.*)?[ \t]*", line):
                start = False
                continue
            start = False
            if body[0] == "\t":
                raise Unsafe("tab indentation", number)
            if re.match(r"(?:---|\.\.\.)(?:\s|$)|%", line):
                raise Unsafe("YAML document markers or directives", number)
            self.content.append((number, len(line) - len(body), line))
        self.unit = min([indent for _, indent, _ in self.content if indent] or [2])
        self.sections, self.parsed = {}, {}
        position = 0
        while position < len(self.content):
            number, indent, line = self.content[position]
            match = KEY.match(line) if indent == 0 else None
            if not match:
                raise Unsafe("unsupported top-level YAML", number)
            key = unquote(match.group(1))
            if key in self.sections:
                raise Unsafe("duplicate key " + key, number)
            stop = position + 1
            while stop < len(self.content) and (self.content[stop][1] or is_entry(self.content[stop][2])):
                stop += 1
            self.sections[key] = (position, stop)
            position = stop

    def entry(self, position, indent):
        number, _, line = self.content[position]
        match = KEY.match(line, indent)
        if not match:
            raise Unsafe("expected 'key: value'", number)
        node = Node(unquote(match.group(1)), number, indent)
        if node.key == "<<":
            raise Unsafe("merge keys", number)
        node.colon = match.end()
        node.kind, node.value, node.start, node.stop = inline(line, node.colon, number)
        node.comment = bool(line[node.stop:].strip())
        position += 1
        following = self.content[position] if position < len(self.content) else None
        if node.kind != "null" or following is None:
            if following and following[1] > indent:
                raise Unsafe("multi-line value", following[0])
            return node, position
        _, child, child_line = following
        if child >= indent and is_entry(child_line[child:]):
            node.kind, node.value = "list", []
            while position < len(self.content):
                number, entry_indent, line = self.content[position]
                if entry_indent != child or not is_entry(line[child:]):
                    break
                kind, value, _, _ = inline(line, child + 1, number)
                if kind != "scalar":
                    raise Unsafe("only one-line scalar list entries are supported", number)
                node.value.append(value)
                node.end, position = number, position + 1
            if position < len(self.content) and self.content[position][1] > indent:
                raise Unsafe("unexpected indentation", self.content[position][0])
            return node, position
        if child > indent:
            node.kind = "map"
            while position < len(self.content) and self.content[position][1] > indent:
                if self.content[position][1] != child:
                    raise Unsafe("inconsistent indentation", self.content[position][0])
                item, position = self.entry(position, child)
                if item.key in node.children:
                    raise Unsafe("duplicate key " + item.key, item.line)
                node.children[item.key] = item
                node.end = item.end
        return node, position

    def section(self, key):
        if key not in self.parsed:
            start, stop = self.sections[key]
            try:
                node, position = self.entry(start, 0)
                if position != stop:
                    raise Unsafe("unsupported YAML structure", self.content[position][0])
                self.parsed[key] = node
            except Unsafe as error:
                self.parsed[key] = error
        if isinstance(self.parsed[key], Unsafe):
            raise self.parsed[key]
        return self.parsed[key]

    def locate(self, path):
        """The deepest existing node on path (None for the document root) and the missing keys."""
        if "<<" in self.sections:
            # A top-level merge can supply any setting, so no key's absence or value is known here.
            raise Unsafe("a top-level merge key (<<)", self.content[self.sections["<<"][0]][0])
        if path[0] not in self.sections:
            return None, list(path)
        node = self.section(path[0])
        for index, key in enumerate(path[1:], 1):
            if node.kind != "map" or key not in node.children:
                return node, list(path[index:])
            node = node.children[key]
        return node, []

    def get(self, path):
        node, missing = self.locate(path)
        return None if missing else node


def dotted(path):
    return ".".join(path)


def mapping(document, path):
    """Child nodes of an optional mapping; Unsafe when another YAML form is in the way."""
    node, missing = document.locate(path)
    if node is not None and node.kind not in ("map", "null"):
        raise Unsafe(dotted(path[:len(path) - len(missing)]) + " is not a plain mapping", node.line)
    return {} if missing else node.children


def scalar(node, path):
    """The value of a one-line setting; Unsafe when a list or mapping stands where one value belongs."""
    if node.kind in ("list", "map"):
        raise Unsafe(dotted(path) + " must be one value, not a " + ("list" if node.kind == "list" else "mapping")
                     + "; fix it in YAML", node.line)
    return node.value


def render(value):
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if PLAIN_SAFE.fullmatch(value) and value.lower() not in YAML11_WORDS:
        return value
    return json.dumps(value)


def set_value(text, path, value):
    document = Document(text)
    node, missing = document.locate(path)
    lines, rendered = list(document.lines), render(value)
    if not missing:
        if node.kind in ("map", "list"):
            raise Unsafe(dotted(path) + " holds a mapping or list", node.line)
        line = lines[node.line]
        if node.kind == "null":
            tail = line[node.colon:]
            lines[node.line] = line[:node.colon] + " " + rendered + (tail if tail.strip() else "")
        else:
            lines[node.line] = line[:node.start] + rendered + line[node.stop:]
        return "\n".join(lines)
    if node is None:
        indent, at = 0, len(lines) - 1 if lines[-1] == "" else len(lines)
    elif node.kind == "map":
        indent, at = next(iter(node.children.values())).indent, node.end + 1
    elif node.kind == "null":
        indent, at = node.indent + document.unit, node.end + 1
    else:
        raise Unsafe(dotted(path[:len(path) - len(missing)]) + " is not a plain mapping", node.line)
    lines[at:at] = [" " * (indent + depth * document.unit) + key + ":"
                    + (" " + rendered if depth == len(missing) - 1 else "") for depth, key in enumerate(missing)]
    if node is None and document.lines[-1] != "":
        lines.append("")
    return "\n".join(lines)


def delete_value(text, path):
    """Remove one key and its block, then any parent left empty without a comment."""
    document = Document(text)
    node, missing = document.locate(path)
    if missing:
        return text
    lines = list(document.lines)
    del lines[node.line:node.end + 1]
    text = "\n".join(lines)
    for depth in range(len(path) - 1, 0, -1):
        document = Document(text)
        parent = document.get(path[:depth])
        if parent is None or parent.kind != "null" or parent.comment:
            break
        lines = list(document.lines)
        del lines[parent.line]
        text = "\n".join(lines)
    return text


def same(node, value):
    if node is None or value is None:
        return node is None and value is None
    return node.kind == "scalar" and type(node.value) is type(value) and node.value == value


def apply(text, base, knobs):
    """Set or clear each knob under base (None clears); the result must read back exactly."""
    document = Document(text)
    changed = {key: value for key, value in knobs.items() if not same(document.get(base + (key,)), value)}
    for key, value in changed.items():
        if value is not None:
            text = set_value(text, base + (key,), value)
    for key, value in changed.items():
        if value is None:
            text = delete_value(text, base + (key,))
    document = Document(text)
    for key, value in knobs.items():
        if not same(document.get(base + (key,)), value):
            raise Unsafe("the edit of " + dotted(base + (key,)) + " did not read back as intended")
    return text


# The live config link and its retained-clone target.

def nm_home():
    value = os.environ.get("NM_HOME") or str(Path.home() / ".no-mistakes")
    if not os.path.isabs(value):
        raise ConfigError("NM_HOME must be an absolute path")
    return Path(value)


def is_runtime(directory):
    runtime = Path(os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local/share")) / "mini-factory"
    return (directory / ".mini-factory-install").exists() or directory.resolve() == runtime.resolve()


def live_config():
    """The verified (link, clone file) pair; anything else is refused with guidance."""
    link = nm_home() / "config.yaml"
    relink = "run make setup from your retained mini-factory clone"
    if not link.is_symlink():
        if link.exists():
            raise ConfigError(str(link) + " is not linked to a mini-factory clone, so nm-config will not edit it. Either "
                              + relink + " (it renames this file to config.yaml.mini-factory-backup and links the "
                              "clone's no-mistakes/config.yaml), or edit " + str(link) + " yourself")
        raise ConfigError(str(link) + " does not exist; " + relink + " to link it")
    target = Path(os.readlink(str(link)))
    clone = target.parent.parent
    if not target.is_absolute() or target.parts[-2:] != ("no-mistakes", "config.yaml"):
        raise ConfigError(str(link) + " links to " + str(target) + ", not to a mini-factory clone's "
                          "no-mistakes/config.yaml; nm-config will not edit it. Edit it yourself, or " + relink)
    if target.is_symlink() or not target.is_file():
        raise ConfigError(str(link) + " links to " + str(target) + ", which is missing or not a regular file; was "
                          "the clone moved or deleted? " + relink[0].upper() + relink[1:] + " to relink")
    if is_runtime(clone):
        raise ConfigError(str(link) + " links into the installed runtime copy (" + str(target) + "); nm-config "
                          "never edits it. " + relink[0].upper() + relink[1:] + " to relink")
    if not all((clone / name).is_file() and not (clone / name).is_symlink()
               for name in ("bin/nm-config", "scripts/nm_config.py")):
        raise ConfigError(str(link) + " links to " + str(target) + ", which is not in a mini-factory clone with "
                          "nm-config (for example a dotfiles-managed config); nm-config will not edit it. Edit it "
                          "yourself, or " + relink + " to link that clone's config")
    bundle = HERE.parent
    if not is_runtime(bundle) and target.resolve() != (bundle / "no-mistakes/config.yaml").resolve():
        raise ConfigError(str(link) + " links to " + str(target) + ", not to this clone (" + str(bundle) + "). Run "
                          + str(clone / "bin/nm-config") + " instead, or run make setup here to relink")
    return link, target


def manual(target):
    return ("Edit " + str(target) + " yourself for this setting (see the No-Mistakes global config reference); "
            "nm-config only changes plain 'key: value' YAML mappings")


def read(target):
    try:
        raw = target.read_bytes()
        return raw, raw.decode("utf-8")
    except OSError as error:
        raise ConfigError("cannot read " + str(target) + ": " + str(error))
    except UnicodeError:
        raise ConfigError(str(target) + " is not UTF-8 text. " + manual(target))


def load(text, target):
    try:
        return Document(text)
    except Unsafe as error:
        raise ConfigError("cannot safely read " + str(target) + ": " + str(error) + ". " + manual(target)
                          + "; nothing was changed")


# Read-only description.

def label(harness):
    return HARNESSES.get(harness, str(harness))


def pinned(document, harness):
    """Model/effort knobs agent_args_override.<harness> pins natively (v1.84.0 precedence rules)."""
    node = document.get(("agent_args_override", harness))
    if node is None or node.kind != "list":
        return {}
    args, found = [str(item) for item in node.value], {}
    for index, argument in enumerate(args):
        name, _, attached = argument.partition("=")
        value = attached if attached else (args[index + 1] if index + 1 < len(args) else "")
        shown = argument if attached else (argument + " " + value).strip()
        knob = next((knob for knob, flags in PIN_FLAGS.get(harness, {}).items() if name in flags), None)
        if knob:
            found[knob] = shown
        elif harness == "codex":
            # A -c/--config override: split ("-c", "key=value") or one token ("-c key=value", "--config=key=value").
            setting = value if argument in ("-c", "--config") else next(
                (argument[len(prefix):] for prefix in ("-c ", "--config ", "-c=", "--config=")
                 if argument.startswith(prefix)), "")
            key, assigned, _ = setting.strip().partition("=")
            shown = argument if argument not in ("-c", "--config") else shown
            if assigned and key.strip() in ("model", "model_reasoning_effort"):
                found["model" if key.strip() == "model" else "effort"] = shown
    return found


def safe(function, *args):
    try:
        return function(*args), None
    except Unsafe as error:
        return None, str(error)


def filled(node):
    """Native No-Mistakes treats an empty model/effort as unset."""
    return node is not None and node.kind == "scalar" and node.value is not None and str(node.value).strip() != ""


def profile(document, harness):
    """The agent_config entry native No-Mistakes applies to harness: (key or None, children).

    An entry with no nonempty knob is dropped natively; an ACP alias then uses its other spelling's entry."""
    alias = ACP_ALIASES.get(harness) or next((name for name, target in ACP_ALIASES.items() if target == harness),
                                             None)
    for key in (harness, alias):
        if key is not None:
            children = mapping(document, ("agent_config", key))
            for knob in ("model", "effort"):
                if knob in children:
                    scalar(children[knob], ("agent_config", key, knob))  # a list/mapping is not unset
            if any(filled(children.get(knob)) for knob in ("model", "effort")):
                return key, children
    return None, {}


def knob_text(document, harness, role=None):
    harness = str(harness)
    found, problem = safe(profile, document, harness)
    key, defaults = found or (None, None)
    pins, pin_problem = safe(pinned, document, harness)
    if harness in ("rovodev", "antigravity"):
        return "model/effort: not settable by No-Mistakes (use its native CLI defaults)"
    parts = []
    for knob in ("model", "effort"):
        if (harness in ACP_ALIASES or harness.startswith("acp:")) and knob == "effort":
            parts.append("effort: not settable (acpx takes a model only)")
            continue
        if role and filled(role.get(knob)):
            text = str(role[knob].value).strip()
        elif defaults and filled(defaults.get(knob)):
            text = str(defaults[knob].value).strip() + (" (agent_config." + key + ")" if key != harness
                                                        else " (agent_config)" if role is not None else "")
        else:
            text = "native default" if defaults is not None else "agent_config unreadable (" + problem + ")"
        if pins and knob in pins:
            text += " - overridden: agent_args_override." + harness + " pins " + pins[knob]
        parts.append(knob + ": " + text)
    if pin_problem:
        parts.append("agent_args_override unreadable (" + pin_problem + "); check it in YAML")
    return "; ".join(parts)


def is_null(node):
    """An absent setting or a YAML null, including both empty and explicit null scalars."""
    return node is None or (node.kind in ("null", "scalar") and node.value is None)


def pipeline_text(document):
    node = document.get(("agent",))
    if is_null(node):
        return "unset - native default auto"
    if node.kind == "list":
        return "ordered fallback list " + ", ".join(map(str, node.value)) + " (first available entry runs)"
    return str(scalar(node, ("agent",)))


def role_text(document, role, pipeline):
    children = mapping(document, ("review_agents", role))
    base = role.replace("_after_round", "")
    if not children:
        if base != role:
            return "none - every round uses the " + base
        return "no override - uses the pipeline agent (" + pipeline + ") with its agent_config"
    values = {key: scalar(node, ("review_agents", role, key)) for key, node in children.items()
              if key in ("agent", "model", "effort", "after_round")}
    harness = values.get("agent")
    if not harness:
        return "no agent set (No-Mistakes requires one; fix it in YAML)"
    text = label(harness) + " - " + knob_text(document, harness, children)
    if base != role:
        after = values.get("after_round")
        after = 1 if after is None else after
        text += ("; from round " + str(after + 1) + " (after_round: " + str(after) + "; rounds 1-" + str(after)
                 + " use the " + base + ")") if type(after) is int else "; after_round: " + str(after)
    return text


def show(link, target, document):
    print("No-Mistakes global config: " + str(link) + " -> " + str(target))
    print("Global defaults only: a target repository's trusted .no-mistakes.yaml may override the agent and")
    print("per-step auto_fix budgets; nm-config does not read target repositories.")

    def line(title, function, *args):
        value, problem = safe(function, *args)
        print(title + (value if problem is None else "cannot display safely (" + problem + "); see the YAML"))

    pipeline, _ = safe(pipeline_text, document)
    print()
    line("Pipeline agent (agent): ", pipeline_text, document)
    print("  Runs Test, CI, and every other step, plus Review rounds without a role override below.")
    defaults, problem = safe(mapping, document, ("agent_config",))
    print("Harness model/effort defaults (agent_config):"
          + (" none (each harness keeps its native defaults)" if defaults == {} else ""))
    for harness in defaults or {}:
        line("  " + label(harness) + ": ", knob_text, document, harness)
    if problem:
        print("  cannot display safely (" + problem + "); see the YAML")
    print("Review phase (review_agents): one native Review step repeats review/fix rounds. These roles serve only")
    print("  its rounds; after_round: N keeps rounds 1-N on the base role and uses the override from round N+1.")
    for role, name in ROLES.items():
        line("  " + name[0].upper() + name[1:] + ": ", role_text, document, role, pipeline or "see agent")
    print("Auto-fix (auto_fix): max automatic fix attempts per step, not guaranteed passes; 0 disables.")
    children, problem = safe(mapping, document, ("auto_fix",))
    for step, default in AUTO_FIX.items() if problem is None else ():
        legacy = step == "ci" and is_null(children.get(step)) and "babysit" in children
        key = "babysit" if legacy else step
        line("  " + step + ": ", lambda: ("unset - native default (" + str(default) + " in v1.84.0)")
             if is_null(children.get(key)) else str(scalar(children[key], ("auto_fix", key)))
             + (" (legacy auto_fix.babysit)" if legacy else ""))
    if problem:
        print("  cannot display safely (" + problem + "); see the YAML")
    line("Fixer session reuse (session_reuse): ",
         lambda: "unset - native default (true in v1.84.0)" if is_null(document.get(("session_reuse",)))
         else str(scalar(document.get(("session_reuse",)), ("session_reuse",))).lower())
    overrides, problem = safe(mapping, document, ("agent_args_override",))
    if overrides or problem:
        print("Native argument overrides (agent_args_override) win over agent_config and review_agents:")
        for harness, node in (overrides or {}).items():
            pins, _ = safe(pinned, document, harness)
            arguments = " ".join(map(str, node.value)) if node.kind == "list" else "(not a list)"
            print("  " + harness + ": " + arguments + ((" - pins " + " and ".join(sorted(pins))) if pins else ""))
        if problem:
            print("  cannot display safely (" + problem + "); see the YAML")
    print("New choices apply to runs started after saving; active runs are not reconfigured.")


# Gum editing flows: each returns the updated text or raises Unsafe for that edit.

def choose_model(header, harness, current, clear):
    if harness == "codex":
        models, cache, _ = mf.codex_catalog()
        catalog = list(models)
        if not models:
            print("No local Codex model cache at " + str(cache) + "; choose " + clear + " or a custom model ID.")
    elif harness == "claude":
        catalog = mf.claude_catalog()[0]
    elif harness == "cursor":
        catalog = mf.cursor_catalog()
    else:
        catalog = []  # no local catalog: native default, the current value, or an exact custom ID
    if harness == "opencode":
        header += " (provider/model, for example openai/gpt-5)"
    options = [clear] + ([current] if current else []) + [model for model in catalog if model != current]
    choice = mf.gum("choose", header + " (local metadata; account access unverified)",
                    options + [mf.CUSTOM_MODEL], current or clear)
    if choice == clear:
        return None
    if choice == mf.CUSTOM_MODEL:
        choice = mf.checked(mf.gum("input", header + " - exact model ID (custom/unverified)", current=current),
                            "model ID")
    if harness == "opencode" and not re.fullmatch(r"[^/]+/.+", choice):
        raise ConfigError("invalid OpenCode model " + repr(choice) + ": No-Mistakes needs the provider/model form, "
                          "for example openai/gpt-5")
    return choice


def choose_effort(header, harness, current, clear):
    levels = EFFORTS[harness]
    if not levels:
        print(label(harness) + " runs through acpx, which takes a model only; No-Mistakes cannot set its effort.")
        return None
    unlisted = [current] if current and current not in levels else []
    if unlisted:
        print("The current effort " + current + " is outside the stable adapter's documented levels; it is kept "
              "only if you choose it again.")
    scope = (" levels; support is model/provider-specific)" if levels is COMMON_EFFORTS and harness in
             ("grok", "opencode") else " levels)")
    choice = mf.gum("choose", header + " (stable No-Mistakes " + label(harness) + scope,
                    [clear] + unlisted + list(levels), current or clear)
    return None if choice == clear else choice


def choose_harness(header, first, current):
    options = [first] + list(HARNESSES.values())
    if current and current not in HARNESSES:
        options.append(KEEP + str(current))
    selected = label(current) if current in HARNESSES else (KEEP + str(current) if current else first)
    choice = mf.gum("choose", header, options, selected)
    if choice == first or choice.startswith(KEEP):
        return choice
    return next(kind for kind, name in HARNESSES.items() if name == choice)


def warn_pins(document, harness, knobs):
    pins, problem = safe(pinned, document, harness)
    for knob in ("model", "effort"):
        if knobs.get(knob) is not None and pins and knob in pins:
            print("Note: agent_args_override." + harness + " pins " + knob + " (" + pins[knob] + "); that native "
                  "argument still wins, so this " + knob + " will not override it. Edit agent_args_override in YAML "
                  "to change it.")
    if problem:
        print("Note: agent_args_override could not be read (" + problem + "); its native arguments still win.")


def note_command(harness):
    command = COMMANDS.get(harness)
    if command and shutil.which(command) is None:
        print("Note: " + command + " is not on PATH. make setup provisions the pipeline and issue agents only; "
              "install and log in to " + label(harness) + " natively for review roles.")


def edit_agent(text, target):
    document = Document(text)
    node = document.get(("agent",))
    if node is not None and node.kind == "list":
        print("agent is an ordered fallback list (" + ", ".join(map(str, node.value)) + "); nm-config keeps it. "
              "Edit the order in " + str(target) + " yourself.")
        return text
    current = node.value if node is not None and isinstance(node.value, str) else None
    options = list(PIPELINE_AGENTS) + ([current] if current and current not in PIPELINE_AGENTS else [])
    choice = mf.gum("choose", "Pipeline agent: Test, CI, other steps, and Review rounds without a role override",
                    options, current or "auto")
    if choice == (current or "auto"):
        return text
    if choice in mf.HARNESSES:
        print("make setup installs and logs in to the pipeline agent; rerun it after saving if "
              + label(choice) + " is new on this machine.")
    elif choice in HARNESSES:
        print("make setup does not provision " + label(choice) + "; install and log in to it natively.")
        note_command(choice)
    return apply(text, (), {"agent": choice})


def edit_agent_config(text, target):
    document = Document(text)
    choice = mf.gum("choose", "agent_config: harness whose No-Mistakes model/effort defaults to set (Rovo Dev "
                    "and Antigravity have none)", [HARNESSES[harness] for harness in EFFORTS])
    harness = next(kind for kind, name in HARNESSES.items() if name == choice)
    # Edit the entry native No-Mistakes applies; an ACP alias may inherit its other spelling's entry.
    key, current = profile(document, harness)
    base = ("agent_config", key or harness)
    if key not in (None, harness):
        print("agent_config." + harness + " is unset, so native No-Mistakes applies " + dotted(base) + " to "
              + label(harness) + "; nm-config edits that entry.")
    header = dotted(base) + ": " + label(harness)
    knobs = {"model": choose_model(header + " model", harness, value_of(current, "model"), NATIVE),
             "effort": choose_effort(header + " effort", harness, value_of(current, "effort"), NATIVE)}
    warn_pins(document, harness, knobs)
    text = apply(text, base, knobs)
    if all(value is None for value in knobs.values()):
        # A cleared entry is dropped natively, so the other alias spelling's entry would apply instead.
        for spelling in (harness, ACP_ALIASES.get(harness)):
            if spelling not in (None, base[1]) and any(
                    filled(mapping(Document(text), ("agent_config", spelling)).get(knob)) for knob in knobs):
                text = apply(text, ("agent_config", spelling), knobs)
    return text


def value_of(children, key):
    node = children.get(key)
    return node.value if node is not None and node.kind == "scalar" and isinstance(node.value, str) else None


def edit_role(text, target, role):
    document = Document(text)
    path = ("review_agents", role)
    current = mapping(document, path)
    overlay = role.endswith("_after_round")
    clear = OVERLAY_CLEAR if overlay else ROLE_INHERIT
    present = value_of(current, "agent")
    harness = choose_harness(dotted(path) + ": " + ROLES[role] + " harness", clear, present)
    if harness == clear:
        return delete_value(text, path)
    if harness.startswith(KEEP):
        return text
    saved = current if present == harness else {}
    header = dotted(path) + ": " + label(harness)
    clear_knob = INHERIT.replace("agent_config", "agent_config." + harness)
    if harness in EFFORTS:
        knobs = {"agent": harness,
                 "model": choose_model(header + " model", harness, value_of(saved, "model"), clear_knob),
                 "effort": choose_effort(header + " effort", harness, value_of(saved, "effort"), clear_knob)}
    else:
        print("No-Mistakes cannot set a model or effort for " + label(harness) + "; it uses its native defaults.")
        knobs = {"agent": harness, "model": None, "effort": None}
    if overlay:
        node = current.get("after_round")
        answer = mf.gum("input", dotted(path) + ": after_round - base-role rounds before the switch (1 or more; "
                        "blank = native default 1)",
                        current="" if is_null(node) or node.kind != "scalar" else str(node.value)).strip()
        if answer and not re.fullmatch(r"[1-9][0-9]{0,3}", answer):
            raise ConfigError("invalid after_round " + repr(answer) + ": use a whole number from 1 to 9999, or "
                              "leave it blank for the native default 1")
        knobs["after_round"] = int(answer) if answer else None
        after = knobs["after_round"] or 1
        print("Rounds 1-" + str(after) + " use the " + role.replace("_after_round", "") + "; from round "
              + str(after + 1) + " the " + ROLES[role] + " applies.")
    warn_pins(document, harness, knobs)
    note_command(harness)
    return apply(text, path, knobs)


def edit_auto_fix(text, target):
    document = Document(text)
    current = mapping(document, ("auto_fix",))
    knobs = {}
    for step, default in AUTO_FIX.items():
        if step == "ci" and is_null(current.get("ci")) and not is_null(current.get("babysit")):
            print("auto_fix.babysit (legacy ci) is set; rename it to ci in " + str(target) + " to edit it here.")
            continue
        node = current.get(step)
        # Clearing an explicit ci exposes a non-null legacy babysit natively, not the native default.
        legacy = step == "ci" and not is_null(current.get("babysit"))
        blank = "clear ci; legacy auto_fix.babysit then applies" if legacy else "native default " + str(default)
        answer = mf.gum("input", "auto_fix." + step + ": max automatic fix attempts (0 disables; blank = " + blank
                        + ")", current="" if is_null(node) or node.kind != "scalar" else str(node.value)).strip()
        if answer and not re.fullmatch(r"0|[1-9][0-9]{0,3}", answer):
            raise ConfigError("invalid auto_fix." + step + " " + repr(answer) + ": use a whole number from 0 to "
                              "9999, or leave it blank (" + blank + ")")
        knobs[step] = int(answer) if answer else None
    return apply(text, ("auto_fix",), knobs)


def edit_session_reuse(text, target):
    node = Document(text).get(("session_reuse",))
    current = node.value if node is not None and isinstance(node.value, bool) else None
    choice = mf.gum("choose", "session_reuse: keep one resumable fixer session across a run's review-fix turns",
                    [SESSION_NATIVE, "true", "false"], SESSION_NATIVE if current is None else str(current).lower())
    return apply(text, (), {"session_reuse": None if choice == SESSION_NATIVE else choice == "true"})


FLOWS = {"agent": edit_agent, "agent_config": edit_agent_config, "auto_fix": edit_auto_fix,
         "session_reuse": edit_session_reuse}
FLOWS.update({role: (lambda role: lambda text, target: edit_role(text, target, role))(role) for role in ROLES})


# Validation and publication.

def native_load(text):
    """Load text with the installed No-Mistakes in a disposable NM_HOME: (True|False|None, detail)."""
    if shutil.which("no-mistakes") is None:
        return None, "no-mistakes is not on PATH"
    try:
        with tempfile.TemporaryDirectory(prefix="nm-config-") as home:
            (Path(home) / "config.yaml").write_text(text, encoding="utf-8")
            result = subprocess.run(["no-mistakes", "doctor"], cwd=home, stdin=subprocess.DEVNULL,
                                    capture_output=True, text=True, timeout=30,
                                    env=dict(os.environ, NM_HOME=home, **NATIVE_ENVIRONMENT))
    except (OSError, subprocess.TimeoutExpired) as error:
        return None, "native doctor did not finish: " + str(error)
    lines = result.stdout.splitlines()
    starts = [index for index, line in enumerate(lines) if "gate validation" in line]
    if not starts:
        return None, "native doctor printed no gate validation result"
    detail = [lines[starts[0]].strip()]
    for line in lines[starts[0] + 1:]:
        if not line.strip() or line.strip()[:1] in ("✓", "✗", "–"):
            break
        detail.append(line.strip())
    detail = " ".join(detail)
    return "load config" not in detail, detail


def validate_natively(original, candidate):
    loaded, detail = native_load(candidate)
    if loaded is None:
        print("Native validation skipped (" + detail + "); nm-config checked its own edits. Run make doctor after "
              "saving.")
    elif loaded:
        print("Native check: the installed No-Mistakes loads the edited config.")
        if not detail.startswith("✓"):
            print("Native doctor also reported (environment readiness, not blocking this save): " + detail)
    else:
        original_loaded, original_detail = native_load(original)
        # Targeted edits can move an existing YAML error to another line. Compare the full diagnostic
        # apart from those locations, so a different native rejection cannot use the recovery exception.
        identity = lambda message: re.sub(r"\bline [0-9]+:", "line:", message)
        if original_loaded is False and identity(detail) == identity(original_detail):
            print("Note: the installed No-Mistakes already rejected this config before the edit (" + detail + "). The "
                  "edit passed nm-config's checks; fix the reported fields in YAML yourself (make doctor shows them).")
        else:
            raise ConfigError("the installed No-Mistakes rejects the edited config (" + detail + "); nothing was saved")


def save(link, target, before, text):
    if live_config() != (link, target):
        raise ConfigError(str(link) + " changed while nm-config was open; nothing was saved. Rerun nm-config.")
    if target.read_bytes() != before:
        raise ConfigError(str(target) + " changed while nm-config was open; nothing was saved. Rerun nm-config.")
    mode = stat.S_IMODE(target.stat().st_mode)
    descriptor, temporary = tempfile.mkstemp(prefix=".config.yaml.nm-config.", dir=str(target.parent))
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, str(target))
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def edit():
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        raise ConfigError("editing needs an interactive terminal (local or SSH); use nm-config show to view settings")
    if shutil.which("gum") is None:
        raise ConfigError("editing requires Gum; run make setup from your mini-factory clone (make doctor checks it)")
    link, target = live_config()
    before, original = read(target)
    show(link, target, load(original, target))
    text, labels = original, dict(MENU)
    while True:
        print()
        choice = mf.gum("choose", "No-Mistakes setting (nothing is saved until you review and confirm)",
                        list(labels.values()) + [SAVE, QUIT])
        if choice == QUIT:
            print("Quit; " + str(target) + " is unchanged.")
            return 0
        if choice == SAVE:
            break
        key = next(key for key, name in labels.items() if name == choice)
        try:
            updated = FLOWS[key](text, target)
        except Unsafe as error:
            print("nm-config cannot safely edit " + choice + ": " + str(error) + ". " + manual(target) + ".")
            continue
        if updated != text:
            text = updated
            print("Pending: " + choice + " (review and save to apply).")
    if text == original:
        print("No change; nothing was saved.")
        return 0
    print("\nChanges to " + str(target) + ":")
    for line in difflib.unified_diff(original.splitlines(), text.splitlines(), "current", "edited", lineterm=""):
        print(line)
    validate_natively(original, text)
    if not mf.confirm("Save these No-Mistakes global defaults to your clone's no-mistakes/config.yaml?"):
        raise Cancelled()
    # A completed confirmation is published atomically or not at all.
    handlers = {sig: signal.signal(sig, signal.SIG_IGN) for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)}
    try:
        save(link, target, before, text)
    except OSError as error:
        raise ConfigError("cannot write " + str(target) + " (" + str(error) + "); nothing was saved")
    finally:
        for sig, handler in handlers.items():
            signal.signal(sig, handler)
    print("Saved: " + str(target) + " (live through " + str(link) + ").")
    print("New runs use these global defaults; active runs are not reconfigured. Run make doctor for native "
          "diagnostics.")
    return 0


def main(argv):
    if argv in (["--help"], ["-h"], ["help"]):
        print(USAGE, end="")
        return 0
    if argv == ["show"]:
        link, target = live_config()
        show(link, target, load(read(target)[1], target))
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
        print("\nCancelled; the No-Mistakes config is unchanged.", file=sys.stderr)
        sys.exit(130)
    except ConfigError as error:
        print("nm-config: " + str(error), file=sys.stderr)
        sys.exit(1)
