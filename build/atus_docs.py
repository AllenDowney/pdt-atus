"""Parse the ATUS 2003-25 data dictionaries (pdftotext -layout output) into entries.

Both dictionaries (atusintcodebk0325.pdf, Interview Data; atuscpscodebk0325.pdf, ATUS-CPS
Data) list variables in the same layout:

    Name               Description                                          File
    TESEX              Edited: sex                                          Roster File,
                                                                            Activity Summary File
                       Edited          All persons on roster
                       Universe:
                       Valid           1                Male
                       Entries:
                                       2                Female
                       *Note           For TUYEAR < = 2004, ...

dictionary(path) returns {NAME: entry}, entry = {name, description, files, universe,
rows: [(code, label)], min, max, notes, page}. "Min Value"/"Max Value" rows give a range.
Running page headers and page numbers are dropped; wrapped descriptions, labels and notes
are joined.
"""

import re
from pathlib import Path

NOISE = re.compile(r"^(_{20,}|ATUS (Interview|-CPS) [Dd]ata:.*|ATUS-CPS data:.*|\s*\d{4}-\d{4} ATUS Data Dictionary:.*|"
                   r"Name\s+Description\s+File|\s+\d{1,3})\s*$")
START = re.compile(r"^([A-Z][A-Z0-9_]*|t\d{6})\s{2,}(\S.*)$")
FIELD = re.compile(r"^\s{10,30}(Edited|Universe:|Valid|Entries:|\*Note)(?=\s|$)\s*(.*)$")
FILE_TAIL = re.compile(r"^(.*?)\s{3,}((?:[A-Z][\w-]*\s)*(?:File|Files),?)\s*$")
ROW = re.compile(r"^(-?\d+)\s{2,}(\S.*)$")


def pages(path):
    out = []
    for i, page in enumerate(Path(path).read_text(encoding="utf-8", errors="replace").split("\f"), 1):
        out += [(i, line.rstrip()) for line in page.splitlines()]
    return out


def split_file(text):
    """'Edited: sex     Roster File,' -> ('Edited: sex', 'Roster File,')."""
    m = FILE_TAIL.match(text)
    return (m.group(1).strip(), m.group(2).strip()) if m else (text.strip(), "")


def dictionary(path, start_after="Name "):
    entries, cur, field = {}, None, None
    started = False
    for page, line in pages(path):
        if not started:  # skip the front matter: entries start at the first "Name  Description  File" header
            started = bool(re.match(r"^Name\s+Description\s+File\s*$", line))
            continue
        if not line.strip() or NOISE.match(line):
            continue
        if re.match(r"^\s*(Appendix|APPENDIX) [A-Z]\b", line):  # the appendices follow the last entry
            break
        m = START.match(line)
        if m:
            desc, files = split_file(m.group(2))
            cur = entries[m.group(1)] = {"name": m.group(1), "description": desc, "files": [files] if files else [],
                                         "universe": "", "rows": [], "min": None, "max": None, "notes": [], "page": page}
            field = "description"
            continue
        if cur is None:
            continue
        f = FIELD.match(line)
        if f:
            label, rest = f.group(1), f.group(2).strip()
            field = {"Edited": "universe", "Universe:": "universe", "Valid": "values", "Entries:": "values",
                     "*Note": "notes"}[label]
            if field == "notes" and rest:
                cur["notes"].append(rest)
                continue
            if not rest:
                continue
            line_text = rest
        else:
            line_text = line.strip()
        if field == "description" and len(line) - len(line.lstrip()) >= 60:
            cur["files"].append(line.strip())  # the File column wrapped onto its own line
        elif field == "description":
            text, files = split_file(line_text)
            if files and (not text or line.startswith(" " * 60)):
                cur["files"].append(files)
            elif files:
                cur["description"] += " " + text
                cur["files"].append(files)
            else:
                cur["description"] += " " + text
        elif field == "universe":
            cur["universe"] = (cur["universe"] + " " + line_text).strip()
        elif field == "values":
            r = ROW.match(line_text)
            if r:
                code, label = int(r.group(1)), r.group(2).strip()
                if label == "Min Value":
                    cur["min"] = code
                elif label == "Max Value":
                    cur["max"] = code
                else:
                    cur["rows"].append([code, label])
            elif cur["rows"]:
                cur["rows"][-1][1] += " " + line_text  # a wrapped label
        elif field == "notes":
            if cur["notes"] and not FIELD.match(line):
                cur["notes"][-1] += " " + line_text
            else:
                cur["notes"].append(line_text)
    for e in entries.values():
        e["files"] = [x.rstrip(",") for x in " ".join(e["files"]).replace("File,", "File|").split("|") if x.strip()]
        e["files"] = [x.strip().rstrip(",") for x in e["files"]]
        e["notes"] = "\n".join(e["notes"])
    return entries
