#!/usr/bin/env python3
"""Reproduce recorded DjVu alignments, without claiming to verify vision."""
import argparse
import hashlib
import json
from pathlib import Path
import build_close_read_160 as core
from check_print_case import PUNCTUATION

ROOT = core.ROOT
INPUT = ROOT / 'research/djvu_reviews/BYCY_CADAL_2026-11-05.json'
OUT = ROOT / 'research/samples/djvu_cases_bycy.json'

def build(record=None):
    record = record if record is not None else json.loads(INPUT.read_text())
    if (record['method'] != 'model_visual_full_case_read_and_comparison_not_expert_collation'
            or record['source_url'] != 'https://upload.wikimedia.org/wikipedia/commons/8/83/CADAL06040558_%E8%96%9B%E6%B0%8F%E9%86%AB%E6%A1%88%C2%B7%E5%8D%B7%E4%BA%94.djvu'
            or record['source_sha256'] != '616279ce69c2518e4abfce5b5a556361e2c1dbda416b76a635cb51af4ef92138'
            or record['source_bytes'] != 4020710 or record['page_count'] != 146):
        raise ValueError('DjVu witness identity mismatch')
    _, sample, index = core.build()
    cases = {c['case_id']: c for c in sample}
    rows = []
    seen = set()
    for r in record['cases']:
        cid = r['case_id']
        if cid in seen:
            raise ValueError('Duplicate DjVu case')
        seen.add(cid)
        case = cases[cid]
        if (case['work_ref'] != 'XJ-BYCY' or r['human_adjudication'] != 'pending'
                or r['initial_query_eligible'] is not False or r['expert_collated_cases'] != 0
                or r['full_case_model_image_comparisons'] != 1):
            raise ValueError('Unsupported DjVu verification claim')
        if len(r['scan_columns']) != len(r['column_locations']):
            raise ValueError('Column roster mismatch')
        previous = (0, 0)
        positions = []
        for column, loc in zip(r['scan_columns'], r['column_locations']):
            page, number = loc['djvu_page'], loc['column_from_right']
            if (type(page) is not int or not 1 <= page <= record['page_count']
                    or type(number) is not int or not 1 <= number <= 8
                    or (page, number) <= previous or not column):
                raise ValueError('Invalid DjVu column location')
            previous = (page, number)
            positions.extend({**loc, 'scan_column_char_index': i + 1} for i in range(len(column)))
        chars = [(s['source_ref'], p, index[s['source_ref']][p])
                 for s in case['segments'] for p in range(s['start'], s['end'])
                 if index[s['source_ref']][p] not in PUNCTUATION]
        reading = ''.join(r['scan_columns'])
        if len(chars) != len(reading):
            raise ValueError('Full-case character count mismatch')
        alignment = [
            {'source_ref': sid, 'source_start_char': p, 'source_end_char_exclusive': p + 1,
             'working': w, 'scan': scan, **loc}
            for (sid, p, w), scan, loc in zip(chars, reading, positions)]
        differences = [
            {'position_one_based': i + 1, 'working': x['working'], 'scan': x['scan']}
            for i, x in enumerate(alignment) if x['working'] != x['scan']]
        if differences != r['expected_differences']:
            raise ValueError('DjVu differences drift')
        rows.append({**r, 'compared_body_characters': len(chars),
                     'case_text_sha256': hashlib.sha256(case['body'].encode()).hexdigest(),
                     'source_git_blob': core.base.BLOB_SHA_AT_FREEZE, 'alignment': alignment})
    return {'source_url': record['source_url'], 'source_sha256': record['source_sha256'],
            'source_bytes': record['source_bytes'], 'cases': rows}

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--write', action='store_true')
    parser.add_argument('--source', type=Path)
    args = parser.parse_args()
    result = build()
    if args.source:
        raw = args.source.read_bytes()
        if len(raw) != result['source_bytes'] or hashlib.sha256(raw).hexdigest() != result['source_sha256']:
            raise ValueError('Actual DjVu file mismatch')
    text = json.dumps(result, ensure_ascii=False, indent=2) + '\n'
    if args.write:
        OUT.write_text(text)
    if OUT.read_text() != text:
        raise ValueError('DjVu derived artifact drift')
    print('PASS: recorded DjVu alignment reproduces; visual accuracy requires image review')

if __name__ == '__main__':
    main()
