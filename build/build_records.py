"""Build the ATUS slice's records from BLS's 2003-25 data dictionaries and the multi-year files.

Usage:
    python build/build_records.py          (make build sets PYTHONPATH for pdt)

Run it under the memory cap (CLAUDE.md): the activity file has 5 million rows, so it is
read row by row, keeping only counts.

Reads build/slice.yaml, the two dictionaries (data/raw/2003-2025/*.pdf, as text in
data/interim/) and the three CSV files. Writes
metadata/releases/2003-2025/<table>/variables.jsonl and build/report.md.

Where each field comes from (STANDARD.md §3):
- label (the dictionary's Description), question text (a Description that is a question),
  universe, notes, codes and labels, valid range (Min/Max Value): the dictionaries
- missing codes -1 Blank, -2 Don't know, -3 Refused: the dictionary's "Valid Values" section
  (p. 7), which says they apply to many variables and aren't listed under each; a record
  gets the ones that occur in its column (rule atus_general_codes)
- storage type, availability by year and n: the data file (rule storage_type_from_values)
- variable type: rule atus_variable_type, from BLS's naming conventions
- codes a note declares ("-4 (Hours vary) is also valid for TEHRUSLT"): rule atus_codes_from_notes
- measure: build/slice.yaml (hand)
- code lists (metadata/code_lists.jsonl): the 2003-2025 coding lexicon, lexiconnoex0325.pdf:
  6-digit codes, second-tier and first-tier codes, labels, and its Notes column (read by
  position: build/atus_lexicon.py); tier 50, "Data Codes", typed missing by rule atus_data_codes
- the summary file's activity columns t010101 ... t509989: rule atus_summary_from_lexicon,
  one record per lexicon code, with the code in extensions.atus.activity_code
- the replicate weights TUFNWGTP001 ... TUFNWGTP160: rule atus_replicate_weights, from the
  zip's Repl0325_info.txt
- groups (metadata/groups.jsonl): one per first-tier category, of the summary's activity columns
"""

import collections
import csv
import io
import json
import re
import subprocess
import zipfile
from pathlib import Path

import yaml

import atus_docs
import atus_lexicon

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw" / "2003-2025"
INTERIM = ROOT / "data" / "interim"
META = ROOT / "metadata"
DATASET = "atus"
RULE_VERSION = "0.1"
INT_DOC, CPS_DOC = "atus-0325-interview-dictionary", "atus-0325-cps-dictionary"
ZIPS = {"respondent": "atusresp-0325.zip", "summary": "atussum-0325.zip", "activity": "atusact-0325.zip",
        "replicates": "atuswgts-0325.zip"}
LEXICON = "atus-0325-lexicon"
LISTS = {"codes": "atus-lexicon-0325", "tier2": "atus-lexicon-0325-tier2", "tier1": "atus-lexicon-0325-tier1"}

# The dictionary's "Valid Values" section, p. 7: "Many ATUS variables have the following possible
# valid values ... Because so many variables have these possible values, they are not shown as
# valid entries for each variable."
GENERAL = {-1: ("Blank", ["unspecified"]), -2: ("Don't know", ["dk"]), -3: ("Refused", ["refused"])}
GENERAL_PAGE = 7


def data_source(table):
    return f"atus-0325-{table}"


def text_of(pdf):
    out = INTERIM / (pdf.stem + ".txt")
    if not out.exists():
        out.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["pdftotext", "-layout", str(pdf), str(out)], check=True)
    return out


def dictionaries():
    """{name: (entry, source id)}: the interview dictionary for T names, the ATUS-CPS one for P and G."""
    interview = atus_docs.dictionary(text_of(RAW / "atusintcodebk0325.pdf"))
    cps = atus_docs.dictionary(text_of(RAW / "atuscpscodebk0325.pdf"))
    out = {n: (e, CPS_DOC) for n, e in cps.items()}
    out.update({n: (e, INT_DOC) for n, e in interview.items() if n.startswith("T") or n not in out})
    return out


# ---------------------------------------------------------------- the lexicon

def code_lists(spec):
    """The three lexicon lists, and {code: lexicon entry} for the 6-digit codes."""
    tier1, tier2, codes = atus_lexicon.lexicon(text_of(RAW / "lexiconnoex0325.pdf"))
    bbox = INTERIM / "lexiconnoex0325.bbox.html"
    if not bbox.exists():
        subprocess.run(["pdftotext", "-bbox-layout", str(RAW / "lexiconnoex0325.pdf"), str(bbox)], check=True)
    notes = atus_lexicon.notes(bbox)
    data_codes = {str(k): v for k, v in (spec.get("data_codes") or {}).items()}
    rule = {"origin": "rule", "rule": "atus_data_codes", "rule_version": RULE_VERSION, "source": LEXICON,
            "note": "The lexicon's tier 50, Data Codes: activities that couldn't be coded. The types come from the "
                    "labels (build/slice.yaml)."}

    def value(code, label, types=None):
        v = {"code": code, "label": label, "kind": "missing" if types else "valid"}
        if types:
            v["missing_types"], v["origin"] = types, rule
        return v

    six = []
    for c in codes:
        v = value(c["code"], c["label"], data_codes.get(c["code"]))
        attrs = {"tier1": c["code"][:2], "tier2": c["code"][:4]}
        if c["code"] in notes:
            attrs["note"] = notes[c["code"]]
            m = re.search(r"code was used in (\d{4})-(\d{4}) only", notes[c["code"]])
            if m:
                v["waves"] = {"from": int(m.group(1)), "to": int(m.group(2))}
            m = re.search(r"\((\d{6})\) was added to the lexicon in (\d{4})", notes[c["code"]])
            if m and m.group(1) == c["code"]:
                v["waves"] = {"from": int(m.group(2))}
        v["attributes"] = attrs
        six.append(v)
    t50 = {"5001": ["uncodeable"], "5099": ["unspecified"], "50": ["uncodeable", "refused", "dk", "unspecified"]}
    origin = {"origin": "publisher", "source": LEXICON}
    lists = [
        {"id": LISTS["codes"], "label": "ATUS 2003-2025 activity coding lexicon: 6-digit activity codes",
         "description": "The codes of the multi-year Activity and Activity Summary files. BLS: the multi-year lexicon "
                        "contains 'activity codes unique to the multi-year Activity and Activity Summary files' and "
                        "'should not be used with single-year files'. Pooled codes (ending 8x, e.g. 020681) combine "
                        "single-year codes; the note says which, and in which years.",
         "columns": {"tier1": "The first-tier (major) category: the code's first two digits.",
                     "tier2": "The second-tier category: the code's first four digits.",
                     "note": "The lexicon's Notes column: which single-year codes a pooled code includes, and "
                             "changes such as renamed or added categories."},
         "codes": six, "origin": origin,
         "note": "waves is set only where the lexicon's note says when a code was in use (500104, 140105). The "
                 "notes were matched to codes by their position on the page (build/atus_lexicon.py)."},
        {"id": LISTS["tier2"], "label": "ATUS 2003-2025 activity coding lexicon: second-tier categories (4 digits)",
         "codes": [value(k, v, t50.get(k) if k.startswith("50") else None) for k, v in tier2.items()],
         "origin": origin},
        {"id": LISTS["tier1"], "label": "ATUS 2003-2025 activity coding lexicon: first-tier (major) categories",
         "codes": [value(k, v, t50.get(k) if k == "50" else None) for k, v in tier1.items()],
         "origin": origin,
         "note": "There is no 17: travel was 17 in 2003-2004 and is 18 from 2005; the multi-year files use 18 for all years."},
    ]
    for cl in lists[1:]:
        for v in cl["codes"]:
            if v["kind"] == "missing":
                v["origin"] = dict(rule, note="Tier 50, Data Codes: activities that couldn't be coded.")
    return lists, {c["code"]: c for c in codes}, tier1


# ---------------------------------------------------------------- data

GENERAL_TOKEN = re.compile(r"-[123](\.0*)?")


def is_general(token):
    """-1, -2 or -3, however written: weights write -1 as "-1.000000" (TUFNWGTP in 2020)."""
    return bool(GENERAL_TOKEN.fullmatch(token))


def scan(table, names):
    """Read a table's columns as text, row by row: header, {name: Counter(token)}, {name: Counter(year)}, rows.

    Tokens are kept as written ("010201", "04:00:00", "-1"). The year is TUYEAR when the table
    has it, else the first four digits of TUCASEID (the activity file has no TUYEAR; its case
    ids start with the year, e.g. 20030100013280)."""
    with zipfile.ZipFile(RAW / ZIPS[table]) as z:
        member = next(n for n in z.namelist() if n.endswith(".dat"))
        with z.open(member) as f:
            reader = csv.reader(io.TextIOWrapper(f, encoding="latin-1"))
            header = next(reader)
            idx = {n: header.index(n) for n in names}
            yidx = header.index("TUYEAR") if "TUYEAR" in header else None
            cidx = header.index("TUCASEID")
            tokens = {n: collections.Counter() for n in names}
            years = {n: collections.Counter() for n in names}
            rows = 0
            for row in reader:
                rows += 1
                year = int(row[yidx] if yidx is not None else row[cidx][:4])
                for n, i in idx.items():
                    t = row[i]
                    tokens[n][t] += 1
                    if t != "" and not is_general(t):
                        years[n][year] += 1
    return header, tokens, years, rows


# ---------------------------------------------------------------- build

INT = re.compile(r"-?\d+")
NUM = re.compile(r"-?\d*\.\d+|-?\d+")


def storage_type(tokens):
    """Rule storage_type_from_values: string if any value isn't a plain number or keeps a leading
    zero (TRCODEP 010201, TUSTARTTIM 04:00:00); else integer, or float."""
    present = [t for t in tokens if t != ""]
    if not present:
        return None
    if any(not NUM.fullmatch(t) or (len(t) > 1 and t.startswith("0") and "." not in t) for t in present):
        return "string"
    return "integer" if all(INT.fullmatch(t) for t in present) else "float"


def variable_type(name, measure, entry):
    """Rule atus_variable_type: BLS's naming conventions (dictionary p. 8): a second letter R is a
    recode; a Description that is a question is a response; weights by measure."""
    if measure == "weight":
        return "weight"
    if measure == "identifier":
        return None
    if len(name) > 1 and name[1] == "R":
        return "recode"
    if entry["description"].rstrip().endswith("?"):
        return "response"
    return None


ALSO_VALID = re.compile(r"(-?\d+) \(([^)]+)\) is also valid for (\w+)")
EDITED = re.compile(r"^(Edited|Unedited):\s*", re.I)


def build_variable(name, table, release, entry, source, measure, spec, tokens, years):
    hand = {"origin": "hand", "author": spec["author"], "date": spec["date"]}
    dat = data_source(table)
    fields = {"measure": hand}
    label = " ".join(entry["description"].split())
    record = {"dataset": DATASET, "release": release, "table": table, "name": name, "label": label}
    if label.endswith("?"):
        text = EDITED.sub("", label)
        record["questions"] = [{"text": text[0].upper() + text[1:]}]
        fields["questions"] = {"origin": "publisher", "source": source,
                               "note": "The dictionary's Description, which is the question, without its 'Edited:' prefix."}
    st = storage_type(tokens)
    if st:
        record["storage_type"] = st
        fields["storage_type"] = {"origin": "rule", "rule": "storage_type_from_values", "rule_version": RULE_VERSION,
                                  "source": dat, "note": "string if any value isn't a plain number or keeps a leading "
                                                         "zero (TRCODEP 010201); else integer or float."}
    record["measure"] = measure
    vt = variable_type(name, measure, entry)
    if vt:
        record["variable_type"] = vt
        fields["variable_type"] = {"origin": "rule", "rule": "atus_variable_type", "rule_version": RULE_VERSION,
                                   "source": source, "note": "BLS's naming conventions: a second letter R is a recode; "
                                                             "a Description that is a question is a response."}
    if entry["universe"]:
        record["universe"] = " ".join(entry["universe"].split())
    notes = [" ".join(entry["notes"].split())] if entry["notes"] else []
    if entry["files"]:
        notes.append("Files: " + ", ".join(entry["files"]) + " (the dictionary's File column).")
    if notes:
        record["notes"] = "\n".join(notes)
    values = [{"code": c, "label": " ".join(l.split()), "kind": "valid"} for c, l in entry["rows"]]
    for m in ALSO_VALID.finditer(entry["notes"]):  # rule atus_codes_from_notes
        if m.group(3) == name and int(m.group(1)) not in {v["code"] for v in values}:
            values.append({"code": int(m.group(1)), "label": m.group(2), "kind": "valid",
                           "origin": {"origin": "rule", "rule": "atus_codes_from_notes", "rule_version": RULE_VERSION,
                                      "source": source, "note": f"The entry's note: '{m.group(0)}'."}})
    listed = {v["code"] for v in values}
    general = []
    if measure != "identifier":
        for code, (label_, types) in GENERAL.items():
            if any(is_general(t) and float(t) == code for t in tokens) and code not in listed:
                general.append({"code": code, "label": label_, "kind": "missing", "missing_types": types,
                                "origin": {"origin": "publisher", "source": INT_DOC,
                                           "location": f"Valid Values, p. {GENERAL_PAGE}",
                                           "note": "BLS lists -1 Blank, -2 Don't know and -3 Refused once, for 'many "
                                                   "ATUS variables', not under each; the code is here because it occurs "
                                                   "in the column (rule atus_general_codes). 'Blank' gives no reason, "
                                                   "so its type is unspecified."}})
    if values or general:
        record["values"] = values + general
        if values:
            fields["values"] = {"origin": "publisher", "source": source, "note": "The dictionary's Valid Entries."}
    if entry["min"] is not None and entry["max"] is not None:
        record["valid_range"] = {"min": entry["min"], "max": entry["max"],
                                 "note": "The dictionary's Min Value and Max Value."}
        fields["valid_range"] = {"origin": "publisher", "source": source}
    record["availability"] = [{"wave": y, "n": n} for y, n in sorted(years.items())]
    fields["availability"] = {"origin": "data_file", "source": dat,
                              "note": "The year is TUYEAR, or the first four digits of TUCASEID in the activity file; "
                                      "n counts values that aren't empty or -1, -2, -3 (however written, e.g. -1.000000)."}
    record["source_location"] = {"source": source, "page": entry["page"], "anchor": name}
    record["provenance"] = {"record": {"origin": "publisher", "source": source}, "fields": fields}
    return record


def build_activity_column(code, lex, table, release, spec, tokens, years):
    """Rule atus_summary_from_lexicon: the summary file's column t<code> is the minutes the respondent
    spent on lexicon code <code> (Sum0325_info.txt in atussum-0325.zip)."""
    dat = data_source(table)
    rule = {"origin": "rule", "rule": "atus_summary_from_lexicon", "rule_version": RULE_VERSION, "source": dat,
            "note": "Sum0325_info.txt: 'The variable names identify activities by their 6-digit codes. The letter \"t\" "
                    "precedes the 6-digit codes.' The label is the code's label in the 2003-25 lexicon."}
    record = {"dataset": DATASET, "release": release, "table": table, "name": f"t{code}", "label": lex["label"],
              "measure": "continuous", "variable_type": "recode", "units": "minutes"}
    st = storage_type(tokens)
    if st:
        record["storage_type"] = st
    record["notes"] = (f"Minutes on the diary day spent on activity {code} (ATUS 2003-2025 coding lexicon)."
                       + (f" Lexicon note: {lex['note']}" if lex.get("note") else ""))
    record["availability"] = [{"wave": y, "n": n} for y, n in sorted(years.items())]
    record["source_location"] = {"source": LEXICON, "page": lex["page"], "anchor": code}
    record["extensions"] = {"atus": {"activity_code": code, "activity_code_list": LISTS["codes"]}}
    fields = {"label": {"origin": "publisher", "source": LEXICON}, "measure": rule, "variable_type": rule,
              "units": rule, "notes": rule,
              "availability": {"origin": "data_file", "source": dat,
                               "note": "n counts values that aren't empty or -1, -2, -3 (however written, e.g. -1.000000)."}}
    if st:
        fields["storage_type"] = {"origin": "rule", "rule": "storage_type_from_values", "rule_version": RULE_VERSION,
                                  "source": dat}
    record["provenance"] = {"record": rule, "fields": fields}
    return record


def build_replicate(name, i, n, prefix, table, release, spec, tokens, years):
    """Rule atus_replicate_weights: TUFNWGTP001 ... TUFNWGTP160 (Repl0325_info.txt in atuswgts-0325.zip)."""
    dat = data_source(table)
    rule = {"origin": "rule", "rule": "atus_replicate_weights", "rule_version": RULE_VERSION, "source": dat,
            "note": "Repl0325_info.txt: 'TUFNWGTP001...TUFNWGTP160 are replicate weights for the variable TUFNWGTP. "
                    "They were created using the 2006 weighting method.'"}
    record = {"dataset": DATASET, "release": release, "table": table, "name": name,
              "label": f"Replicate weight {i} of {n} for {prefix}", "measure": "weight", "variable_type": "weight"}
    st = storage_type(tokens)
    if st:
        record["storage_type"] = st
    if any(is_general(t) and float(t) == -1 for t in tokens):
        record["values"] = [{"code": -1, "label": "Blank", "kind": "missing", "missing_types": ["unspecified"],
                             "origin": {"origin": "publisher", "source": INT_DOC, "location": f"Valid Values, p. {GENERAL_PAGE}",
                                        "note": "BLS's general code -1 Blank (rule atus_general_codes). The file has no "
                                                "replicate weights for 2020; its rows hold -1."}}]
    record["availability"] = [{"wave": y, "n": k} for y, k in sorted(years.items())]
    record["provenance"] = {"record": rule, "fields": {
        "availability": {"origin": "data_file", "source": dat, "note": "The year is the first four digits of TUCASEID."}}}
    return record


def check(record, tokens, lists):
    """C4: codes in the data the record doesn't cover (skips identifiers, weights, text and dates)."""
    listed = {v["code"] for v in record.get("values", [])}
    if record.get("code_list"):
        listed |= {v["code"] for v in lists[record["code_list"]]["codes"]}
        return [f"- `{record['table']}/{record['name']}` code {t}: occurs {n:,} times, not in "
                f"{record['code_list']} or the record's values" for t, n in sorted(tokens.items())
                if t not in listed and not (re.fullmatch(r"-?\d+", t) and int(t) in listed)]
    if record["measure"] in ("identifier", "weight", "text", "date") or record.get("storage_type") == "string":
        return []
    vr = record.get("valid_range")
    if not listed and not vr:
        return []
    out = []
    for t, n in sorted(tokens.items()):
        if t == "":
            continue
        c = float(t)
        c = int(c) if c.is_integer() else c
        if c not in listed and not (vr and vr["min"] <= c <= vr["max"]):
            out.append(f"- `{record['table']}/{record['name']}` code {t}: occurs {n:,} times, not documented")
    return out


def main():
    spec = yaml.safe_load((ROOT / "build" / "slice.yaml").read_text())
    release = spec["release"]
    docs = dictionaries()
    lists, lex, tier1 = code_lists(spec)
    by_id = {cl["id"]: cl for cl in lists}
    report, problems, total, groups = [], [], 0, []
    for table, t in spec["tables"].items():
        names = list(t["variables"])
        rep = t.get("replicate_weights")
        reps = [f"{rep['prefix']}{i:03d}" for i in range(1, rep["n"] + 1)] if rep else []
        acts = list(lex) if t.get("activity_columns") else []
        header, tokens, years, rows = scan(table, names + [f"t{c}" for c in acts] + reps)
        undocumented = [c for c in header if c not in docs and not re.fullmatch(r"t\d{6}", c) and c not in reps]
        report += [f"## {table}", "", f"- {rows:,} rows, {len(header)} columns; records: {len(names) + len(acts) + len(reps)}",
                   f"- Columns the dictionaries don't document: {undocumented or 'none'}", ""]
        records = []
        for name in names:
            entry, source = docs[name]
            rec = build_variable(name, table, release, entry, source, t["variables"][name], spec,
                                 tokens[name], years[name])
            cl = (t.get("code_lists") or {}).get(name)
            if cl:
                rec["code_list"] = cl
                rec["provenance"]["fields"]["code_list"] = {
                    "origin": "publisher", "source": source,
                    "note": "The dictionary's note: 'See the 2003-25 Activity Coding Lexicon for activity definitions'."}
                listed = {v["code"] for v in by_id[cl]["codes"]}
                rec["values"] = [v for v in rec.get("values", []) if v["code"] not in listed] or None
                if rec["values"] is None:
                    del rec["values"]
            problems += check(rec, tokens[name], by_id)
            records.append(rec)
        for code in acts:
            records.append(build_activity_column(code, lex[code], table, release, spec, tokens[f"t{code}"], years[f"t{code}"]))
        for i, name in enumerate(reps, 1):
            records.append(build_replicate(name, i, rep["n"], rep["prefix"], table, release, spec, tokens[name], years[name]))
        if acts:
            for t1, label in tier1.items():
                groups.append({"id": f"activity-{t1}", "kind": "subject", "label": f"{t1} {label}",
                               "members": [{"release": release, "table": table, "name": f"t{c}"} for c in acts
                                           if c.startswith(t1)],
                               "ordered": True,
                               "origin": {"origin": "publisher", "source": LEXICON,
                                          "note": "The lexicon's first-tier category: the summary's activity columns "
                                                  "whose codes start with these two digits."}})
        write_jsonl(META / "releases" / release / table / "variables.jsonl", records)
        total += len(records)
    write_jsonl(META / "code_lists.jsonl", lists)
    write_jsonl(META / "groups.jsonl", groups)
    lines = [f"# Build report: {DATASET}, release {release}", "",
             "Generated by `build/build_records.py`. Do not edit.", "", f"- Records: {total}",
             f"- Code lists: " + ", ".join(f"{cl['id']} ({len(cl['codes'])} codes)" for cl in lists),
             f"- Groups: {len(groups)}", ""] + report
    lines += ["## Codes in the data the records don't cover", ""] + (problems or ["None."])
    (ROOT / "build" / "report.md").write_text("\n".join(lines) + "\n")
    print(f"{total} records; see build/report.md")


def write_jsonl(path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
