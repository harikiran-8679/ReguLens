"""Extract the 230-record rule register from the corrected FINAL PDF.

The PDF text layer is a *flattened* serialization of the register: mapping
keys are printed one per line with a uniform two-space prefix regardless of
nesting depth, and long scalar values wrap across lines. Structure can only
be recovered from the canonical key order of each record plus the register
grammar:

    rule_id rule_number sub_rule title type category
      requirement {field?, required?, description}
      applicability {scope | commodity_type/channel list}
      conditions (null | dict)
      validation {type, [validation_subtype], parameters {…}}
    severity evidence_required effective_from effective_to version
      source {document, provision, amendment}
    status

`parameters` is a free-form dict: it begins after the `parameters:` key and
runs until the *last* top-level tail key (`severity … status`) sequence
starts, so any parameter key that merely *looks like* a tail key but appears
before the genuine tail is retained as a parameter.

Usage:
    python tools/extract_register.py <pdf> <out.json>
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pymupdf

HDR = re.compile(r"^(\d+)\.\s+(.+)$")
PAGE_MARK = re.compile(r"^=== PAGE \d+ ===$")
PAGE_HDR = re.compile(r"^LMPC Packaged Commodities Rules 2011\u20132026 .*Register$")
PAGE_NO = re.compile(r"^Page \d+$")
RULE_SEP = re.compile(r"^RULE(?: '\d+')?(?: [A-Za-z ]*Schedule)?$")
ANNEX_HDR = re.compile(r"^RULE 7 - IMPLEMENTATION SPECIFICATION FOR OCR \+ PHOTO VALIDATION")
KEY_RE = re.compile(r"^ {0,4}([A-Za-z0-9_]+): ?(.*)$")
LIST_RE = re.compile(r"^ {0,4}- (.*)$")

# Canonical top-level slot order for every record body.
SLOTS = ["rule_id", "rule_number", "sub_rule", "title", "type", "category",
         "requirement", "applicability", "conditions", "validation",
         "severity", "evidence_required", "effective_from", "effective_to",
         "version", "source", "status"]

# Keys that must belong to the top-level tail (end a `parameters` block).
TAIL = {"severity", "evidence_required", "effective_from", "effective_to",
        "version", "source", "status"}

CONTAINER_KIDS = {
    "requirement": {"field", "required", "description"},
    "applicability": {"scope", "commodity_type", "channel"},
    "conditions": None,          # free-form dict (children until validation)
    "validation": {"type", "validation_subtype", "parameters"},
    "source": {"document", "provision", "amendment"},
}


def extract_text(pdf: Path) -> str:
    doc = pymupdf.open(str(pdf))
    pages = []
    for i in range(len(doc)):
        page = doc[i]
        pages.append(f"=== PAGE {i+1} ===")
        pages.append(page.get_text())
    return "\n".join(pages)


def split_records(raw: str) -> list[dict]:
    records: list[dict] = []
    cur: dict | None = None
    in_annex = False
    for ln in raw.splitlines():
        s = ln.rstrip()
        if not s.strip():
            continue
        if PAGE_MARK.match(s) or PAGE_HDR.match(s) or PAGE_NO.match(s):
            continue
        stripped = s.strip()
        if ANNEX_HDR.match(stripped):
            in_annex = True
            continue
        if in_annex:
            continue  # register ends at record 230; annex is reference prose
        if RULE_SEP.match(stripped):
            continue  # section separator "RULE 'N'" / "RULE <Schedule>"
        m = HDR.match(s)
        if m:
            if cur:
                records.append(cur)
            cur = {"_seq": int(m.group(1)), "_lines": []}
            continue
        if cur is not None:
            cur["_lines"].append(s)
    if cur:
        records.append(cur)
    return records


def tokenize(lines: list[str]) -> list[tuple]:
    """Return (kind, name, value): kind ∈ key|item|text."""
    toks: list[tuple] = []
    for ln in lines:
        if not ln.strip():
            continue
        m = LIST_RE.match(ln)
        if m:
            toks.append(("item", None, m.group(1).strip()))
            continue
        m = KEY_RE.match(ln)
        if m:
            toks.append(("key", m.group(1), m.group(2).strip()))
        else:
            toks.append(("text", None, ln.strip()))
    return toks


def _clean(v: str):
    v = v.strip()
    if v == "null":
        return None
    if v in ("true", "false"):
        return v == "true"
    if len(v) >= 2 and v[0] == v[-1] and v[0] in ("'", '"'):
        return v[1:-1]
    return v


def parse_record(lines: list[str]) -> dict:
    toks = tokenize(lines)
    n = len(toks)
    i = 0

    def peek():
        return toks[i] if i < n else ("eof", None, "")

    def nxt():
        nonlocal i
        t = peek()
        i += 1
        return t

    def scalar(inline: str) -> str:
        parts = [inline] if inline else []
        while True:
            kind, _, v = peek()
            if kind == "text":
                parts.append(v)
                nxt()
            else:
                break
        return " ".join(x for x in parts if x).strip()

    def list_val() -> list[str]:
        out: list[str] = []
        while True:
            kind, _, v = peek()
            if kind == "item":
                out.append(v)
                nxt()
            elif kind == "text":
                nxt()
                if out:
                    out[-1] += " " + v.strip()
            else:
                break
        return out

    def tail_starts_here() -> bool:
        """True when the current key is `severity` that begins the genuine
        top-level tail (severity … status, ending the record)."""
        kind, kname, _ = peek()
        if kind != "key" or kname != "severity":
            return False
        order = ["severity", "evidence_required", "effective_from",
                 "effective_to", "version", "source", "status"]
        j = i
        for o in order:
            if j >= n or toks[j][0] != "key" or toks[j][1] != o:
                return False
            j += 1
        return j == n  # tail must run to the end of the record

    root: dict = {}
    rp = 0  # index into SLOTS

    while rp < len(SLOTS) and i < n:
        slot = SLOTS[rp]
        kind, kname, v = peek()
        if kind != "key":
            nxt()
            continue
        # -------- if the current key is exactly the expected slot ----------
        if kname == slot:
            nxt()
            if slot == "requirement":
                obj: dict = {}
                root["requirement"] = obj
                while i < n:
                    kk, kkname, vv = peek()
                    if kk == "key" and kkname == "applicability":
                        break
                    if kk == "key":
                        nxt()
                        if kkname == "description":
                            obj["description"] = scalar(vv)
                        elif kkname in ("field", "required"):
                            obj[kkname] = _clean(vv) if vv else None
                        else:
                            obj[kkname] = scalar(vv) if not vv else _clean(vv)
                    else:
                        nxt()
                rp += 1
                continue
            if slot == "applicability":
                obj = {}
                root["applicability"] = obj
                while i < n:
                    kk, kkname, vv = peek()
                    if kk == "key" and kkname == "conditions":
                        break
                    if kk == "key":
                        nxt()
                        if kkname in ("commodity_type", "channel"):
                            lst = list_val()
                            if vv:
                                lst.insert(0, vv)
                            obj[kkname] = lst
                        elif kkname == "scope":
                            obj["scope"] = scalar(vv)
                        else:
                            obj[kkname] = scalar(vv) if not vv else _clean(vv)
                    else:
                        nxt()
                rp += 1
                continue
            if slot == "conditions":
                if v == "null":
                    root["conditions"] = None
                else:
                    cond: dict = {}
                    root["conditions"] = cond
                    while i < n:
                        kk, kkname, vv = peek()
                        if kk == "key" and kkname == "validation":
                            break
                        if kk == "key":
                            nxt()
                            cond[kkname] = _clean(vv) if not vv else _clean(vv)
                        else:
                            nxt()
                rp += 1
                continue
            if slot == "validation":
                obj = {}
                root["validation"] = obj
                params: dict | None = None
                while i < n:
                    kk, kkname, vv = peek()
                    if kk != "key":
                        nxt()
                        continue
                    if kkname == "severity":
                        break
                    if params is None and kkname in ("type", "validation_subtype"):
                        nxt()
                        obj[kkname] = vv
                        continue
                    if params is None and kkname == "parameters":
                        nxt()
                        params = {}
                        obj["parameters"] = params
                        continue
                    # inside free-form parameters (or stray key pre-parameters)
                    if params is None:
                        nxt()
                        obj[kkname] = scalar(vv)
                        continue
                    if kkname in TAIL and tail_starts_here():
                        break
                    nxt()
                    params[kkname] = _clean(scalar(vv))
                rp += 1
                continue
            if slot == "source":
                src: dict = {}
                root["source"] = src
                while i < n:
                    kk, kkname, vv = peek()
                    if kk == "key" and kkname == "status":
                        break
                    if kk == "key":
                        nxt()
                        src[kkname] = scalar(vv)
                    else:
                        nxt()
                rp += 1
                continue
            # plain scalar slot
            root[slot] = _clean(scalar(v))
            rp += 1
            continue
        # ---- current key is NOT the expected slot -------------------------
        if kname in SLOTS:
            idx = SLOTS.index(kname)
            if idx >= rp:
                rp = idx
                continue  # reprocess as the expected slot
        nxt()

    return root


def _apply_documented_repairs(parsed: list[dict]) -> list[dict]:
    """Apply repairs for defects that exist in the source register itself.

    Every change is logged in record['_repairs'] with the source evidence
    used, so nothing is silently invented.
    """
    by_seq = {p["_seq"]: p for p in parsed}
    repairs: dict[int, list[str]] = {}

    def log(seq: int, msg: str) -> None:
        repairs.setdefault(seq, []).append(msg)

    # --- Record 1 (LMPC-R1-001, Rule 1(1) Short title): the PDF text layer
    # ends the record at the requirement.description page wrap; the tail and
    # the description's final word are absent from the register itself.
    r1 = by_seq.get(1)
    if r1:
        desc = (r1.get("requirement") or {}).get("description") or ""
        if desc.endswith("Rules,"):
            r1["requirement"]["description"] = desc + " 2011."
            log(1, "description completed '2011.' at the page-wrap boundary "
                    "(statutory short title of the principal Rules).")
        r1.setdefault("applicability", {"scope": r1["requirement"]["description"]})
        r1.setdefault("conditions", None)
        r1.setdefault("validation", {"type": "not_applicable", "parameters": {
            "check_scope": "historical_or_interpretive_record",
            "runtime_action": "do_not_generate_product_pass_fail"}})
        for key, val in (("severity", "INFO"), ("evidence_required", False),
                         ("effective_from", "2011-04-01"), ("effective_to", None),
                         ("version", "2011.0"), ("status", "active")):
            if key not in r1 or r1.get(key) is None:
                r1[key] = val
                log(1, f"{key} reconstructed from sibling record 1(2) "
                        "(register truncates record 1 at the page break).")
        if "source" not in r1:
            r1["source"] = {"document": "Legal Metrology (Packaged Commodities) Rules, 2011",
                             "provision": "1(1)", "amendment": "Original"}
            log(1, "source reconstructed from register conventions.")

    # --- Record 47 (LMPC-R6-003): the register's corrected-text overlay
    # merged the version value into the effective_to line
    # ('effective_to: null version 2011.0' + a stray 'version: null').
    r47 = by_seq.get(47)
    if r47:
        et = r47.get("effective_to")
        if isinstance(et, str) and "version" in et:
            r47["effective_to"] = None
            r47["version"] = "2011.0"
            log(47, "effective_to/version un-merged from overlay corruption "
                    "('effective_to: null version 2011.0'); version set to 2011.0.")

    # --- Records whose register text prints literal 'effective_from: null'
    # but whose own description/amendment states the operative start date.
    prose_dates = {
        179: ("2011-04-01", "record description: 'effective from 2011-04-01'; "
                            "sibling 24(a)/24(b) records share the same window"),
        189: ("2024-01-01", "record description: 'effective from 2024-01-01'; "
                            "sibling 26(f)(iii) record shares the same window"),
        214: ("2012-06-05", "record description: 'originated on 5 June 2012'; "
                            "amendment G.S.R. 427(E), 05-06-2012"),
    }
    for seq, (date, ev) in prose_dates.items():
        r = by_seq.get(seq)
        if r and r.get("effective_from") is None:
            r["effective_from"] = date
            log(seq, f"effective_from {date} filled from the record's own prose "
                     f"({ev}).")

    # --- Records 223-230: register section separators ('RULE First Schedule')
    # leaked into the status scalar during extraction (already removed from
    # _lines; strip any residual contamination).
    for p in parsed:
        st = str(p.get("status") or "")
        if " RULE " in st:
            p["status"] = st.split(" RULE ", 1)[0].strip()
            log(p["_seq"], "status stripped of leaked 'RULE <Schedule>' separator.")

    # --- A text-overlay defect splices the next record's amendment chain onto
    # the end of some records' version value
    # (e.g. '2011.0 source G.S.R. 784(E), 24-10-2011; ...'). The register's
    # own clean siblings show version is always a bare token, so split there.
    for p in parsed:
        v = p.get("version")
        if isinstance(v, str) and " source " in v:
            clean = v.split(" source ", 1)[0].strip()
            log(p["_seq"], f"version '{v[:60]}…' trimmed to '{clean}' "
                            "(overlay bleed of the following record's amendment "
                            "chain onto the version row).")
            p["version"] = clean

    for p in parsed:
        if p["_seq"] in repairs:
            p["_repairs"] = repairs[p["_seq"]]
    return parsed


def main(pdf: str, out: str) -> None:
    raw = extract_text(Path(pdf))
    recs = split_records(raw)
    parsed = []
    problems = []
    for r in recs:
        try:
            d = parse_record(r["_lines"])
        except Exception as exc:  # pragma: no cover
            problems.append((r["_seq"], f"EXC {exc}"))
            continue
        d["_seq"] = r["_seq"]
        parsed.append(d)
    parsed.sort(key=lambda x: x["_seq"])
    print(f"records: {len(parsed)}")
    seqs = [p["_seq"] for p in parsed]
    print("contiguous 1..230:", seqs == list(range(1, 231)))
    missing = []
    for p in parsed:
        for k in ("rule_id", "rule_number", "title", "type", "category",
                  "severity", "evidence_required", "effective_from",
                  "version", "status"):
            if p.get(k) in (None, ""):
                missing.append((p["_seq"], k))
    print("missing core fields:", missing[:40], f"({len(missing)})")
    if problems:
        print("problems:", problems[:20])
    Path(out).write_text(json.dumps(parsed, indent=1, ensure_ascii=False))
    print("wrote", out)
    repaired = _apply_documented_repairs(parsed)
    Path(out).write_text(json.dumps(repaired, indent=1, ensure_ascii=False))
    n = sum(1 for r in repaired if r.get("_repairs"))
    print(f"documented repairs applied to {n} records; wrote", out)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
