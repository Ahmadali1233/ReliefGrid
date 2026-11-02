"""Reads CSV, TSV, JSON and XML files into a list of rows (dicts of text values).

To support a brand-new file format on competition day: add a function here that
returns (columns, rows), and register its file extension in PARSERS at the bottom.
"""

import csv
import io
import json
import xml.etree.ElementTree as ET


class FileFormatError(ValueError):
    """The file can't be read at all. The message says what to fix."""


def _decode(content):
    if not content or not content.strip():
        raise FileFormatError("The file is empty.")
    not_text = FileFormatError("The file isn't readable text (is it an Excel or image file?). "
                               "Save it as CSV (UTF-8), JSON or XML.")
    encodings = ["utf-16"] if content[:2] in (b"\xff\xfe", b"\xfe\xff") else ["utf-8-sig", "cp1252"]
    for encoding in encodings:
        try:
            text = content.decode(encoding)
        except UnicodeDecodeError:
            continue
        # Real text files have almost no control characters; binary files are full of them.
        controls = sum(1 for ch in text if ord(ch) < 32 and ch not in "\r\n\t")
        if "\x00" in text or controls > max(2, len(text) // 100):
            raise not_text
        return text
    raise not_text


def _text(value):
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value)
    return str(value).strip()


def parse_csv(text):
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    reader = csv.reader(io.StringIO(text), dialect)
    lines = [row for row in reader]
    header_index = next((i for i, row in enumerate(lines) if any(c.strip() for c in row)), None)
    if header_index is None:
        raise FileFormatError("The file has no header row.")
    columns = [c.strip() for c in lines[header_index]]
    if not any(columns):
        raise FileFormatError("The header row is blank.")
    rows = []
    for offset, values in enumerate(lines[header_index + 1:], start=header_index + 2):
        if not any(v.strip() for v in values):
            continue                      # skip blank lines (Excel loves adding these)
        record = {col: (values[i].strip() if i < len(values) else "") for i, col in enumerate(columns) if col}
        record["__row"] = offset
        rows.append(record)
    if not rows:
        raise FileFormatError("The file has a header but no data rows.")
    return [c for c in columns if c], rows


def _flatten(obj, prefix=""):
    out = {}
    for key, value in obj.items():
        name = f"{prefix}{key}"
        if isinstance(value, dict):
            out.update(_flatten(value, f"{name}_"))
        else:
            out[name] = _text(value)
    return out


def parse_json(text):
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise FileFormatError(f"The JSON is broken near line {e.lineno}, column {e.colno}.")
    records = None
    if isinstance(data, list):
        records = data
    elif isinstance(data, dict):
        lists = [v for v in data.values() if isinstance(v, list) and v and all(isinstance(x, dict) for x in v)]
        if lists:
            records = max(lists, key=len)
        elif all(not isinstance(v, (list, dict)) for v in data.values()):
            records = [data]
    if not records or not all(isinstance(r, dict) for r in records):
        raise FileFormatError("The JSON must be a list of records, like [{\"item\": \"Water\", ...}].")
    rows, columns = [], []
    for i, rec in enumerate(records, start=1):
        flat = _flatten(rec)
        for c in flat:
            if c not in columns:
                columns.append(c)
        flat["__row"] = i
        rows.append(flat)
    return columns, rows


def parse_xml(text):
    try:
        root = ET.fromstring(text.encode("utf-8") if text.lstrip().startswith("<?xml") else text)
    except ET.ParseError as e:
        raise FileFormatError(f"The XML is broken: {e}.")
    # Find the element type that repeats most: those are the records.
    counts = {}
    for parent in root.iter():
        tags = [child.tag for child in parent]
        for tag in set(tags):
            n = tags.count(tag)
            if n > counts.get(tag, (0, None))[0]:
                counts[tag] = (n, parent)
    if not counts:
        raise FileFormatError("The XML has no records in it.")
    tag, (_, parent) = max(counts.items(), key=lambda kv: kv[1][0])
    rows, columns = [], []
    for i, el in enumerate(parent.findall(tag), start=1):
        rec = {k: v.strip() for k, v in el.attrib.items()}
        for child in el:
            if len(child):
                for sub in child:
                    rec[f"{child.tag}_{sub.tag}"] = (sub.text or "").strip()
            else:
                rec[child.tag] = (child.text or "").strip()
        if not rec and (el.text or "").strip():
            continue
        for c in rec:
            if c not in columns:
                columns.append(c)
        rec["__row"] = i
        rows.append(rec)
    if not rows:
        raise FileFormatError("The XML has no records in it.")
    return columns, rows


PARSERS = {
    "csv": parse_csv, "tsv": parse_csv, "txt": parse_csv,
    "json": parse_json,
    "xml": parse_xml,
}


def parse_file(content, filename):
    """Return (columns, rows). Each row has a '__row' key with its position in the file."""
    text = _decode(content)
    ext = (filename or "").rsplit(".", 1)[-1].lower() if "." in (filename or "") else ""
    parser = PARSERS.get(ext)
    if parser is None:
        stripped = text.lstrip()
        if stripped.startswith(("[", "{")):
            parser = parse_json
        elif stripped.startswith("<"):
            parser = parse_xml
        else:
            parser = parse_csv
    return parser(text)
