#!/usr/bin/env python3
"""Compare two docs/schema.json files and print a human-friendly report.
Note that schema differences between different systems are normal. All it takes
is a different disk type or a change in configuration (e.g. snapshot schedule).

Usage:
  python scripts/compare_schema.py old_schema.json new_schema.json

Output: summary of measurements added/removed and per-measurement tag/field diffs.
"""
import json
import sys
from pathlib import Path
from typing import Dict, Any, Set


def load_schema(path: Path) -> Dict[str, Any]:
    with path.open('r', encoding='utf-8') as f:
        return json.load(f)


def values_from_entries(entries):
    """Extract a set of non-empty values from a list of dict entries."""
    vals = set()
    for e in entries:
        for v in e.values():
            if isinstance(v, str) and v.strip():
                vals.add(v.strip())
            elif v is not None and not isinstance(v, dict):
                vals.add(str(v))
    return vals


def compare(old: Dict[str, Any], new: Dict[str, Any]):
    old_keys = set(old.keys())
    new_keys = set(new.keys())

    added = sorted(new_keys - old_keys)
    removed = sorted(old_keys - new_keys)
    common = sorted(old_keys & new_keys)

    print(f"Measurements: total_old={len(old_keys)} total_new={len(new_keys)} added={len(added)} removed={len(removed)} common={len(common)}")
    if added:
        print('\nAdded measurements:')
        for m in added:
            print('  +', m)
    if removed:
        print('\nRemoved measurements:')
        for m in removed:
            print('  -', m)

    # per-measurement diffs
    diffs = {}
    for m in common:
        oldm = old.get(m, {})
        newm = new.get(m, {})
        old_tags = values_from_entries(oldm.get('tags', []))
        new_tags = values_from_entries(newm.get('tags', []))
        old_fields = values_from_entries(oldm.get('fields', []))
        new_fields = values_from_entries(newm.get('fields', []))

        tags_added = sorted(new_tags - old_tags)
        tags_removed = sorted(old_tags - new_tags)
        fields_added = sorted(new_fields - old_fields)
        fields_removed = sorted(old_fields - new_fields)

        if tags_added or tags_removed or fields_added or fields_removed:
            diffs[m] = {
                'tags_added': tags_added,
                'tags_removed': tags_removed,
                'fields_added': fields_added,
                'fields_removed': fields_removed,
            }

    if diffs:
        print('\nPer-measurement differences:')
        for m, d in diffs.items():
            print(f"\nMeasurement: {m}")
            if d['tags_added']:
                print('  Tags added:')
                for t in d['tags_added']:
                    print('    +', t)
            if d['tags_removed']:
                print('  Tags removed:')
                for t in d['tags_removed']:
                    print('    -', t)
            if d['fields_added']:
                print('  Fields added:')
                for t in d['fields_added']:
                    print('    +', t)
            if d['fields_removed']:
                print('  Fields removed:')
                for t in d['fields_removed']:
                    print('    -', t)

    if not added and not removed and not diffs:
        print('\nNo differences found between the two schema files.')

    return diffs


def main():
    if len(sys.argv) != 3:
        print('Usage: compare_schema.py old_schema.json new_schema.json', file=sys.stderr)
        sys.exit(2)
    old_path = Path(sys.argv[1])
    new_path = Path(sys.argv[2])
    if not old_path.exists() or not new_path.exists():
        print('Both files must exist', file=sys.stderr)
        sys.exit(2)
    old = load_schema(old_path)
    new = load_schema(new_path)
    diffs = compare(old, new)
    # optionally write a JSON report next to new_path
    report_path = new_path.with_name(new_path.stem + '.diff.json')
    with report_path.open('w', encoding='utf-8') as rf:
        json.dump(diffs, rf, indent=2, sort_keys=True)
    print(f'Wrote report: {report_path}')


if __name__ == '__main__':
    main()
