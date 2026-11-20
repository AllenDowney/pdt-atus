"""Parse the ATUS 2003-2025 multi-year coding lexicon (lexiconnoex0325.pdf, pdftotext -layout).

    01 Personal Care Activities                                   first tier: 2 digits at column 0
               0101 Sleeping                                      second tier: 4 digits
                             010101      Sleeping                 6-digit code, label, and in the
                             020681      Care for animals ...     Notes column, e.g. "includes 020601
                                                                  (all years), 020602 (2008 and later years)"

lexicon(path) returns (tier1, tier2, codes): tier1 {code: label}, tier2 {code: label},
codes [{code, label, note, page}] in the publisher's order. A label or note that wraps onto
the next line is joined. Page headers ("ATUS 2003-2025 Activity coding lexicon", the column
heads) and page numbers are dropped.
"""

import re
from pathlib import Path

TIER1 = re.compile(r"^(\d{2}) (\S.*)$")
TIER2 = re.compile(r"^\s{5,20}(\d{4}) (\S.*)$")
CODE = re.compile(r"^\s{15,}(\d{6})\s+(\S.*?)(?:\s{3,}(\S.*))?$")
NOISE = re.compile(r"^\s*(ATUS 2003-2025 Activity coding lexicon\s*|First and\s+6-digit.*|Major\s+second-tier.*|"
                   r"category\s+categories.*|\d{1,3}\s*|\* Not elsewhere classified\s*)$")
COLUMN_GAP = re.compile(r"\s{3,}")
NOTE_COLUMN = 90  # notes start near column 100; labels end before it


def lexicon(path):
    tier1, tier2, codes = {}, {}, []
    started = False
    for page, text in enumerate(Path(path).read_text(encoding="utf-8").split("\f"), 1):
        for line in text.splitlines():
            line = line.rstrip()
            if not line.strip() or NOISE.match(line):
                continue
            if not started:
                started = bool(TIER1.match(line))
                if not started:
                    continue
            m = CODE.match(line)
            if m:
                codes.append({"code": m.group(1), "label": m.group(2).strip(), "note": (m.group(3) or "").strip(),
                              "page": page})
                continue
            m = TIER2.match(line)
            if m and not CODE.match(line):
                tier2[m.group(1)] = COLUMN_GAP.split(m.group(2).strip())[0]  # Notes-column text can share the line
                continue
            m = TIER1.match(line)
            if m:
                tier1[m.group(1)] = COLUMN_GAP.split(m.group(2).strip())[0]
                continue
            if codes:  # a wrapped label or note
                indent = len(line) - len(line.lstrip())
                key = "note" if indent >= NOTE_COLUMN else "label"
                codes[-1][key] = (codes[-1][key] + " " + line.strip()).strip()
    return tier1, tier2, codes


# ---------------------------------------------------------------- the Notes column, by position

LINE = re.compile(r'<line xMin="([\d.]+)" yMin="([\d.]+)" xMax="([\d.]+)" yMax="([\d.]+)">(.*?)</line>', re.S)
WORD = re.compile(r'>([^<]+)</word>')
NOTE_START = re.compile(r"^(Includes|includes|The activity|code was)\b")
NOTE_X = 600     # the Notes column starts near x = 666 (of 1190)
CODE_X = 300     # 6-digit codes sit near x = 125-200
GAP = 20         # lines of one note are about 10 apart; a larger gap starts a new note


def notes(bbox_path):
    """{code: note} from `pdftotext -bbox-layout` output.

    The PDF centers a multi-line note vertically on its code's row, so its first line can sit
    beside the code above. Lines in the Notes column are grouped into notes (a new note starts
    with "Includes", "The activity" or "code was" after a note that ended with ")" or ".", or
    after a gap of more than a line), and
    each note goes to the code whose row is nearest the note's middle. Page numbers are dropped."""
    import html
    out = {}
    for page in Path(bbox_path).read_text(encoding="utf-8").split("<page ")[1:]:
        codes, lines = [], []
        for l in LINE.findall(page):
            words = [html.unescape(w) for w in WORD.findall(l[4])]
            if not words:
                continue
            y, x = (float(l[1]) + float(l[3])) / 2, float(l[0])
            if re.fullmatch(r"\d{6}", words[0]) and x < CODE_X:
                codes.append((y, words[0]))
            elif x >= NOTE_X and words != ["Notes"] and not re.fullmatch(r"\d{1,3}", " ".join(words)):
                lines.append((y, " ".join(words)))
        groups = []
        for y, t in sorted(lines):
            prev = " ".join(x for _, x in groups[-1]) if groups else ""
            gap = y - groups[-1][-1][0] if groups else 0
            if groups and gap < GAP and not (NOTE_START.match(t) and prev.rstrip().endswith((")", "."))):
                groups[-1].append((y, t))
            else:
                groups.append([(y, t)])
        for g in groups:
            middle = (g[0][0] + g[-1][0]) / 2
            code = min(codes, key=lambda c: abs(c[0] - middle))[1]
            out[code] = (out.get(code, "") + " " + " ".join(t for _, t in g)).strip()
    return out


# ---------------------------------------------------------------- single-year lexicons (XLS)

def single_year(xls, interim):
    """[(code, label)] from a single-year lexicon (lexiconwexYYYY.xls), in BLS's order.

    The .xls is converted with LibreOffice (`soffice --headless --convert-to csv`, every sheet)
    into `interim`; the lexicon sheet has one row per 6-digit code (code, label) followed by its
    example rows."""
    import csv
    import subprocess
    interim = Path(interim)
    stem = Path(xls).stem
    sheets = sorted(interim.glob(f"{stem}-*.csv"))
    if not sheets:
        interim.mkdir(parents=True, exist_ok=True)
        subprocess.run(["soffice", "--headless", "--convert-to",
                        "csv:Text - txt - csv (StarCalc):44,34,76,1,,0,false,true,false,false,false,-1",
                        "--outdir", str(interim), str(xls)], check=True, capture_output=True)
        sheets = sorted(interim.glob(f"{stem}-*.csv"))
    out = []
    for sheet in sheets:
        for row in csv.reader(open(sheet, encoding="utf-8", errors="replace")):
            if len(row) > 1 and re.fullmatch(r"\d{6}", row[0].strip()) and row[1].strip():
                out.append((row[0].strip(), " ".join(row[1].split())))
    return out


# ---------------------------------------------------------------- includes, from the Notes column

INCLUDE = re.compile(r"((?:\d{6}\s*(?:,|\+|and)?\s*)+)\(([^)]*)\)")


def years_of(text, first, last):
    """'2003-2004' -> (2003, 2004); '2008 and later years' -> (2008, last); 'all years' -> (first, last);
    '2003, 2004' -> (2003, 2004); '2003' -> (2003, 2003). None if it isn't one of these."""
    t = text.strip().lower()
    if t == "all years":
        return first, last
    m = re.fullmatch(r"(\d{4}) and later years", t)
    if m:
        return int(m.group(1)), last
    years = [int(y) for y in re.findall(r"\d{4}", t)]
    if years and re.fullmatch(r"[\d\s,\-–]+", t):
        return min(years), max(years)
    return None


def includes(note, first, last):
    """[(code, (from, to))] from a note like 'includes 020601 (all years), 020602 (2008 and later years)'
    or 'Includes 171001, 171002, 171003 (2003-2004); 181001 (2005 and later years)'."""
    out = []
    for codes, years in INCLUDE.findall(note or ""):
        span = years_of(years, first, last)
        if span is None:
            continue
        out += [(c, span) for c in re.findall(r"\d{6}", codes)]
    return out
