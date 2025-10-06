#!/usr/bin/env python3
"""
Dump InfluxDB schema to docs/SCHEMA.md using container exec and robust CSV parsing.
This script runs from the host and calls the influxdb3 binary inside the specified container.
It avoids brittle nested shell quoting and uses Python CSV parsing to produce Markdown tables.
"""

import csv
import subprocess
import sys
import shlex
from pathlib import Path

CONTAINER = "utils"
TOKEN_PATH = "/home/influx/epa.token"
INFLUX_BIN = "/home/influx/.influxdb/influxdb3"
INFLUX_HOST = "https://influxdb:8181"
DATABASE = "epa"
OUT_PATH = Path("docs/SCHEMA.md")


def run_cmd(cmd):
    # cmd is list
    try:
        out = subprocess.check_output(cmd, stderr=subprocess.STDOUT)
        return out.decode('utf-8', errors='replace')
    except subprocess.CalledProcessError as e:
        # print command output for easier debugging
        out_text = e.output.decode('utf-8', errors='replace') if hasattr(e, 'output') else ''
        print(f"Command failed: {' '.join(cmd)}\nExit: {e.returncode}\nOutput:\n{out_text}", file=sys.stderr)
        raise


def read_token():
    cmd = ['docker', 'compose', 'exec', '-T', CONTAINER, 'cat', TOKEN_PATH]
    out = run_cmd(cmd)
    return out.strip()


def query_csv(query, token):
    cmd = [
        'docker', 'compose', 'exec', '-T', CONTAINER,
        INFLUX_BIN, 'query', '-H', INFLUX_HOST,
        '--language', 'influxql', '--database', DATABASE,
        '--token', token, '--format', 'csv', query
    ]
    out = run_cmd(cmd)
    # splitlines preserves no trailing newline
    lines = out.splitlines()
    reader = csv.reader(lines)
    rows = list(reader)
    return rows


def csv_to_markdown(rows):
    if not rows:
        return "No results\n\n"
    # find first non-comment-ish header row
    header_idx = None
    for i, row in enumerate(rows):
        if not row:
            continue
        # treat rows beginning with '#datatype' or '#group' as preamble (skip)
        if any(cell.startswith('#') for cell in row if cell):
            continue
        header_idx = i
        break
    if header_idx is None:
        return "No results\n\n"
    header = rows[header_idx]
    data = rows[header_idx+1:]
    # build markdown
    out_lines = []
    out_lines.append('| ' + ' | '.join(header) + ' |')
    out_lines.append('| ' + ' | '.join(['---'] * len(header)) + ' |')
    for r in data:
        if not any(cell.strip() for cell in r):
            continue
        # pad to header len
        if len(r) < len(header):
            r += [''] * (len(header) - len(r))
        out_lines.append('| ' + ' | '.join(r) + ' |')
    out_lines.append('')
    return '\n'.join(out_lines)


def extract_measurements(rows):
    # rows is list of csv rows from SHOW MEASUREMENTS
    if not rows:
        return []
    # Find header row index that contains 'name' or 'measurement'
    header_idx = None
    for i, row in enumerate(rows):
        for cell in row:
            if cell and 'name' == cell.strip().lower():
                header_idx = i
                break
        if header_idx is not None:
            break
    if header_idx is None:
        for i, row in enumerate(rows):
            for cell in row:
                if cell and 'measurement' in cell.lower():
                    header_idx = i
                    break
            if header_idx is not None:
                break
    if header_idx is None:
        # fallback: first non-empty row
        for i, row in enumerate(rows):
            if any(cell.strip() for cell in row):
                header_idx = i
                break
    if header_idx is None:
        return []
    headers = rows[header_idx]
    # pick column: prefer 'name' if present, else 'measurement' occurrence, else second col
    midx = None
    for i, h in enumerate(headers):
        if h and h.strip().lower() == 'name':
            midx = i
            break
    if midx is None:
        for i, h in enumerate(headers):
            if h and 'measurement' in h.lower():
                midx = i
                break
    if midx is None:
        midx = 0
    vals = []
    for r in rows[header_idx+1:]:
        if len(r) <= midx:
            continue
        v = r[midx].strip()
        if not v:
            continue
        # skip obvious header-like tokens
        if v.lower() in ('measurement', 'measurements'):
            continue
        vals.append(v)
    # dedupe preserving order
    seen = set()
    out = []
    for x in vals:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out


def slugify(name):
    # simple slug: lowercase, replace spaces and non-alnum with hyphen
    import re
    s = name.lower()
    s = re.sub(r'[^a-z0-9._-]+', '-', s)
    s = re.sub(r'-+', '-', s).strip('-')
    return s


def main():
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    print('Reading token from container...')
    token = read_token()
    if not token:
        print('Error: empty token', file=sys.stderr)
        sys.exit(1)
    print('Querying measurements...')
    rows = query_csv('SHOW MEASUREMENTS', token)
    measurements = extract_measurements(rows)
    print(f'Found {len(measurements)} measurements')
    # write initial TOC
    with OUT_PATH.open('w', encoding='utf-8') as f:
        f.write('# InfluxDB Schema for EPA 4\n\n')
        f.write('## Measurements\n\n')
        for m in measurements:
            f.write(f'- [{m}](#measurement-{slugify(m)})\n')
        f.write('\n')
    schema = {}
    # per-measurement queries
    for m in measurements:
        print(f'Querying measurement: {m}')
        # avoid putting backslashes inside f-string expressions: precompute escaped name
        escaped = m.replace('"', '\\"')
        tag_q = f'SHOW TAG KEYS FROM "{escaped}"'
        field_q = f'SHOW FIELD KEYS FROM "{escaped}"'
        tag_rows = query_csv(tag_q, token)
        field_rows = query_csv(field_q, token)
        # append to markdown
        with OUT_PATH.open('a', encoding='utf-8') as f:
            f.write(f"<a id=\"measurement-{slugify(m)}\"></a>\n")
            f.write(f'## Measurement: {m}\n\n')
            f.write('### Tags\n')
            f.write('\n')
            f.write(csv_to_markdown(tag_rows))
            f.write('\n')
            f.write('### Fields\n')
            f.write('\n')
            f.write(csv_to_markdown(field_rows))
            f.write('\n')
        # build structured schema for JSON output
        tags = []
        fields = []
        # parse tag_rows into list of dicts
        if tag_rows:
            # find header row
            hidx = 0
            for i,row in enumerate(tag_rows):
                if row and not any(cell.startswith('#') for cell in row if cell):
                    hidx = i
                    break
            headers = [c.strip() for c in tag_rows[hidx]]
            for r in tag_rows[hidx+1:]:
                if not any(cell.strip() for cell in r):
                    continue
                entry = {headers[i]: r[i] if i < len(r) else '' for i in range(len(headers))}
                tags.append(entry)
        if field_rows:
            hidx = 0
            for i,row in enumerate(field_rows):
                if row and not any(cell.startswith('#') for cell in row if cell):
                    hidx = i
                    break
            headers = [c.strip() for c in field_rows[hidx]]
            for r in field_rows[hidx+1:]:
                if not any(cell.strip() for cell in r):
                    continue
                entry = {headers[i]: r[i] if i < len(r) else '' for i in range(len(headers))}
                fields.append(entry)
        schema[m] = {'tags': tags, 'fields': fields}
    # write JSON schema
    try:
        import json
        json_path = OUT_PATH.with_name('schema.json')
        with json_path.open('w', encoding='utf-8') as jf:
            json.dump(schema, jf, indent=2, sort_keys=True)
        print('Wrote JSON schema to', json_path)
    except Exception as e:
        print('Failed to write JSON schema:', e, file=sys.stderr)
    print('Done. Wrote', OUT_PATH)


if __name__ == '__main__':
    main()
