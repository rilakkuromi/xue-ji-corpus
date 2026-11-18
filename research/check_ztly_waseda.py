#!/usr/bin/env python3
"""Reconcile the P036 second witness with the generated primary alignment."""
import argparse
import hashlib
import json
from pathlib import Path

import check_print_case

ROOT = check_print_case.ROOT
RECORD = ROOT / 'research/witness_reviews/ZTLY_P036_WASEDA_2026-11-18.json'
PRIMARY = ROOT / 'research/print_case_reviews/ZTLY_V1_P036_1_2026-11-09.json'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pdf', type=Path)
    parser.add_argument('--render', type=Path)
    args = parser.parse_args()
    record = json.loads(RECORD.read_text())
    primary = check_print_case.build(path=PRIMARY)
    if primary['case_id'] != record['case_id'] or primary != json.loads(
        (ROOT / record['primary_comparison']).read_text()
    ):
        raise ValueError('P036 primary alignment drift')
    if record['human_adjudication'] != 'pending':
        raise ValueError('Unsupported expert review claim')
    reading = ''.join(record['scan_columns'])
    differences = []
    for row, char in zip(primary['alignment'], reading, strict=True):
        if row['working'] != row['scan'] or row['working'] != char:
            differences.append({
                'ordinal': row['ordinal'], 'source_start_char': row['source_start_char'],
                'working': row['working'], 'ncl': row['scan'], 'waseda': char,
            })
    if differences != record['expected_differences']:
        raise ValueError('Three-way alignment differs from the reviewed record')
    if not reading[33:].startswith('桃仁四劑而定後又出血') or not reading.endswith('治之而愈'):
        raise ValueError('P036 treatment stages drift')
    for path, key in ((args.pdf, 'pdf'), (args.render, 'render')):
        if path is not None:
            data = path.read_bytes()
            if hashlib.sha256(data).hexdigest() != record[f'{key}_sha256']:
                raise ValueError(f'{key} hash mismatch')
            if key == 'pdf' and len(data) != record['pdf_bytes']:
                raise ValueError('PDF byte count mismatch')
    print(f"P036: {len(reading)} characters, {len(differences)} variant positions; "
          f"PDF hash {'checked' if args.pdf else 'not checked'}, "
          f"render hash {'checked' if args.render else 'not checked'}")


if __name__ == '__main__':
    main()
