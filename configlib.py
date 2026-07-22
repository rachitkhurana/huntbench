#!/usr/bin/env python3
"""configlib - dependency-free config layer for Huntbench.

Loads config/profile.yml and config/portals.yml using PyYAML when available, else a tiny
built-in parser tuned to those two files. Read-only. Copy the *.example.yml files in config/
to their real names (or run `./jobsdb.py setup`) and edit them.

Self-test:  python3 configlib.py --selftest
"""

import os
import re

MODULE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_DIR = os.path.join(MODULE_DIR, "config")

# our region buckets -> profile.yml compensation.by_region keys
_REGION_TO_COMP = {"uae": "uae", "remote-emea": "london_eu", "europe": "london_eu"}


# ---- minimal YAML (subset tuned to profile.yml + portals.yml) ----------------

def _strip_comment(line):
    out, q, i = [], None, 0
    while i < len(line):
        c = line[i]
        if q:
            out.append(c)
            if c == q:
                q = None
        elif c in ('"', "'"):
            q = c
            out.append(c)
        elif c == "#" and (i == 0 or line[i - 1] == " "):
            break
        else:
            out.append(c)
        i += 1
    return "".join(out).rstrip()


def _scalar(s):
    s = s.strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in ('"', "'"):
        return s[1:-1]
    low = s.lower()
    if low in ("true", "yes"):
        return True
    if low in ("false", "no"):
        return False
    if low in ("null", "~", ""):
        return None
    if re.fullmatch(r"-?\d+", s):
        return int(s)
    if re.fullmatch(r"-?\d+\.\d+", s):
        return float(s)
    return s


def _first_unquoted_colon(s):
    q = None
    for i, c in enumerate(s):
        if q:
            if c == q:
                q = None
        elif c in ('"', "'"):
            q = c
        elif c == ":" and (i + 1 == len(s) or s[i + 1] == " "):
            return i
    return -1


def _parse_map(tokens, i, indent):
    result = {}
    while i < len(tokens):
        ci, content = tokens[i]
        if ci < indent or content.startswith("- "):
            break
        key, _, rest = content.partition(":")
        key, rest = key.strip(), rest.strip()
        i += 1
        if rest == "":
            if i < len(tokens) and tokens[i][0] > indent:
                child, i = _parse_block(tokens, i, tokens[i][0])
                result[key] = child
            else:
                result[key] = None
        else:
            result[key] = _scalar(rest)
    return result, i


def _parse_list(tokens, i, indent):
    items = []
    while i < len(tokens):
        ci, content = tokens[i]
        if ci < indent or not content.startswith("- "):
            break
        inline = content[2:].strip()
        i += 1
        item_indent = indent + 2
        if _first_unquoted_colon(inline) != -1:
            sub = [(item_indent, inline)]
            while (i < len(tokens) and tokens[i][0] >= item_indent
                   and not tokens[i][1].startswith("- ")):
                sub.append(tokens[i])
                i += 1
            val, _ = _parse_map(sub, 0, item_indent)
            items.append(val)
        else:
            items.append(_scalar(inline))
    return items, i


def _parse_block(tokens, i, indent):
    if i >= len(tokens):
        return None, i
    if tokens[i][1].startswith("- "):
        return _parse_list(tokens, i, indent)
    return _parse_map(tokens, i, indent)


def _mini_yaml(text):
    tokens = []
    for raw in text.splitlines():
        line = _strip_comment(raw.rstrip("\n"))
        if line.strip() == "":
            continue
        indent = len(line) - len(line.lstrip(" "))
        tokens.append((indent, line.strip()))
    if not tokens:
        return {}
    val, _ = _parse_block(tokens, 0, tokens[0][0])
    return val


def load_yaml(path):
    with open(path, encoding="utf-8") as f:
        text = f.read()
    try:
        import yaml
        return yaml.safe_load(text)
    except ImportError:
        return _mini_yaml(text)


# ---- resolution + accessors --------------------------------------------------

def _resolve(name):
    """config/<name>, falling back to config/<name>.example so a fresh clone still runs."""
    real = os.path.join(CONFIG_DIR, name)
    if os.path.exists(real):
        return real
    root, ext = os.path.splitext(name)
    example = os.path.join(CONFIG_DIR, "%s.example%s" % (root, ext))
    return example if os.path.exists(example) else None


def load_profile():
    """Return (profile_dict, path_or_None)."""
    p = _resolve("profile.yml")
    return ((load_yaml(p) or {}) if p else {}), p


def load_portals():
    """Return (portals_dict, path_or_None)."""
    p = _resolve("portals.yml")
    return ((load_yaml(p) or {}) if p else {}), p


def comp_band(profile, region):
    """The {target_range, minimum} band for a job's region bucket, or None."""
    key = _REGION_TO_COMP.get(region)
    if not key:
        return None
    comp = (profile or {}).get("compensation") or {}
    return (comp.get("by_region") or {}).get(key)


def profile_keywords(profile):
    """Lowercased title/role keywords from target_roles + archetypes (for scoring)."""
    tr = (profile or {}).get("target_roles") or {}
    words = list(tr.get("primary") or [])
    words += [a.get("name", "") for a in (tr.get("archetypes") or []) if isinstance(a, dict)]
    return [w.lower() for w in words if w]


# ---- self-test ---------------------------------------------------------------

def selftest():
    checks = []

    def c(name, cond):
        checks.append((name, bool(cond)))

    prof, pp = load_profile()
    port, rp = load_portals()
    cand = (prof.get("candidate") or {})
    tr = (prof.get("target_roles") or {})
    c("profile loaded", bool(prof))
    c("candidate.full_name set", bool(cand.get("full_name")))
    c("candidate.email set", bool(cand.get("email")))
    c("target_roles.primary is list", isinstance(tr.get("primary"), list) and len(tr["primary"]) >= 1)
    c("profile_keywords non-empty", len(profile_keywords(prof)) >= 1)
    c("portals loaded", bool(port))
    c("title_filter.positive list", isinstance((port.get("title_filter") or {}).get("positive"), list))
    tc = port.get("tracked_companies") or []
    c("tracked_companies list of maps", isinstance(tc, list) and (not tc or isinstance(tc[0], dict)))
    c("location_filter.always_allow list",
      isinstance((port.get("location_filter") or {}).get("always_allow"), list))

    ok = all(v for _, v in checks)
    for name, v in checks:
        print(("PASS" if v else "FAIL"), name)
    print("\n%s (%d/%d)" % ("ALL PASS" if ok else "FAILURES",
                            sum(1 for _, v in checks if v), len(checks)))
    print("profile: %s\nportals: %s" % (pp, rp))
    return 0 if ok else 1


if __name__ == "__main__":
    import sys
    if "--selftest" in sys.argv[1:]:
        sys.exit(selftest())
    prof, pp = load_profile()
    import json
    print(json.dumps(prof, indent=2, ensure_ascii=False))
