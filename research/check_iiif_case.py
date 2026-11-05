#!/usr/bin/env python3
"""Validate recorded IIIF case alignment, without claiming to validate vision."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import build_close_read_160 as core
from check_print_case import PUNCTUATION

ROOT=core.ROOT
INPUT=ROOT/'research/iiif_reviews/LZWKFH_V5_P183_2026-11-01.json'
OUT=ROOT/'research/samples/iiif_case_lzwkfh_v5_p183.json'
SUMMARY=ROOT/'research/samples/image_case_summary.json'

def build(record=None):
    r=copy.deepcopy(record) if record is not None else json.loads(INPUT.read_text())
    if (r['human_adjudication']!='pending' or r['initial_query_eligible'] is not False or
        r['expert_collated_cases']!=0 or r['full_case_model_image_comparisons']!=1 or r.get('unresolved_readings')):
        raise ValueError('Unsupported IIIF verification claim')
    raw=(ROOT/r['manifest_snapshot']).read_bytes()
    if hashlib.sha256(raw).hexdigest()!=r['manifest_sha256']:raise ValueError('Manifest digest drift')
    manifest=json.loads(raw)
    if manifest['@id']!=r['manifest_uri']:raise ValueError('Manifest identity drift')
    if not manifest['label'].startswith('立齋外科發揮'):raise ValueError('Manifest work mismatch')
    if r['waseda_retry']['visual_read_performed'] is not False:
        raise ValueError('Tokyo image cannot verify Waseda witness')
    canvases=manifest['sequences'][0]['canvases']
    visited=r['viewed_canvases']
    if len({x['ordinal_one_based'] for x in visited})!=len(visited):raise ValueError('Duplicate viewed canvas')
    for x in visited:
        n=x['ordinal_one_based']
        if type(n) is not int or not 1<=n<=len(canvases):raise ValueError('Canvas outside manifest')
        c=canvases[n-1];resource=c['images'][0]['resource']
        if (x['canvas_uri']!=c['@id'] or x['image_service']!=resource['service']['@id'] or
            x['download_url']!=x['image_service']+'/full/'+str(x['requested_width'])+',/0/default.jpg'):
            raise ValueError('Canvas image identity drift')
        if x['bytes']<=0 or len(x['sha256'])!=64 or any(c not in '0123456789abcdef' for c in x['sha256']):
            raise ValueError('Invalid image artifact identity')
    case_page=next((x for x in visited if x['ordinal_one_based']==r['case_canvas_ordinal_one_based']),None)
    if case_page is None:raise ValueError('Case canvas not viewed')
    _,sample,index=core.build()
    case=next(c for c in sample if c['case_id']==r['case_id'])
    if case['work_ref']!=r['work_ref'] or r['work_ref']!='XJ-LZWKFH':raise ValueError('Case witness work mismatch')
    if len(r['scan_columns'])!=len(r['column_locations']):raise ValueError('Column roster drift')
    positions=[];previous=None
    for text,loc in zip(r['scan_columns'],r['column_locations']):
        if loc['page_half'] not in {'right','left'} or type(loc['column_from_right']) is not int or loc['column_from_right']<1:
            raise ValueError('Invalid column location')
        order=({'right':0,'left':1}[loc['page_half']],loc['column_from_right'])
        start=loc.get('start_char_one_based',1)
        if type(start) is not int or start<1 or previous is not None and order<=previous:
            raise ValueError('Invalid column order or offset')
        previous=order
        positions.extend({**loc,'scan_column_char_index':start+i} for i in range(len(text)))
    chars=[(seg['source_ref'],p,index[seg['source_ref']][p]) for seg in case['segments']
           for p in range(seg['start'],seg['end']) if index[seg['source_ref']][p] not in PUNCTUATION]
    reading=''.join(r['scan_columns'])
    if len(chars)!=len(reading):raise ValueError('Full-case character count mismatch')
    alignment=[{'source_ref':sid,'source_start_char':p,'source_end_char_exclusive':p+1,
                'working':w,'scan':s,**loc} for (sid,p,w),s,loc in zip(chars,reading,positions)]
    differences=[x for x in alignment if x['working']!=x['scan']]
    if [{'working':x['working'],'scan':x['scan']} for x in differences]!=r['expected_substitutions']:
        raise ValueError('IIIF differences drift')
    return {**r,'source_git_blob':core.base.BLOB_SHA_AT_FREEZE,
            'case_text_sha256':hashlib.sha256(case['body'].encode()).hexdigest(),
            'compared_body_characters':len(chars),'scan_reading':reading,'alignment':alignment,
            'differences':differences,'case_canvas_uri':case_page['canvas_uri']}

def summarize(row):
    pdf=json.loads((ROOT/'research/samples/print_case_summary.json').read_text())
    if row['case_id'] in pdf['case_ids']:raise ValueError('Duplicate case across PDF and IIIF')
    summary = {'scope':'combined_model_image_comparisons_not_expert_collation','cases':pdf['cases']+1,
            'compared_body_characters':pdf['compared_body_characters']+row['compared_body_characters'],
            'pdf_cases':pdf['cases'],'iiif_cases':1,'works':sorted({*pdf['cases_by_work'],'LZWKFH'}),
            'cases_by_work':{**pdf['cases_by_work'],'LZWKFH':pdf['cases_by_work'].get('LZWKFH',0)+1},
            'compared_body_characters_by_work':{**pdf['compared_body_characters_by_work'],
                'LZWKFH':pdf['compared_body_characters_by_work'].get('LZWKFH',0)+row['compared_body_characters']},
            'equal_length_different_positions':pdf['different_character_positions']+len(row['differences']),
            'reviewed_block_difference_events':pdf['reviewed_block_difference_events'],
            'pending_model_image_readings':pdf['pending_model_image_readings'],
            'viewed_iiif_canvases':len(row['viewed_canvases']),
            'page_counting_note':'IIIF canvases are not PDF pages; manifest identifiers retained separately',
            'expert_collated_cases':0,'initial_query_exported':0}
    import check_djvu_case
    djvu = check_djvu_case.build()['cases']
    seen = set(pdf['case_ids']) | {row['case_id']}
    for case in djvu:
        if case['case_id'] in seen:
            raise ValueError('Duplicate case across image formats')
        seen.add(case['case_id'])
        summary['cases'] += 1
        summary['compared_body_characters'] += case['compared_body_characters']
        summary['cases_by_work']['BYCY'] += 1
        summary['compared_body_characters_by_work']['BYCY'] += case['compared_body_characters']
        summary['equal_length_different_positions'] += len(case['expected_differences'])
    summary['djvu_cases'] = len(djvu)
    summary['page_counting_note'] = 'PDF pages, IIIF canvases and DjVu pages are separate source units'
    return summary

def check_images(row,paths):
    known={(x['sha256'],x['bytes']) for x in row['viewed_canvases']}
    actual=set()
    for f in paths:
        raw=f.read_bytes();identity=(hashlib.sha256(raw).hexdigest(),len(raw))
        if identity not in known:raise ValueError('Actual image identity mismatch')
        actual.add(identity)
    page=next(x for x in row['viewed_canvases'] if x['ordinal_one_based']==row['case_canvas_ordinal_one_based'])
    if (page['sha256'],page['bytes']) not in actual:raise ValueError('Actual case image required')

def main():
    p=argparse.ArgumentParser();p.add_argument('--write',action='store_true');p.add_argument('--image',type=Path,action='append');a=p.parse_args()
    row=build()
    if a.image:check_images(row,a.image)
    summary=summarize(row)
    for path,obj in [(OUT,row),(SUMMARY,summary)]:
        text=json.dumps(obj,ensure_ascii=False,indent=2)+'\n'
        if a.write:path.write_text(text)
        if path.read_text()!=text:raise ValueError('IIIF derived artifact drift')
    print(json.dumps(summary,ensure_ascii=False))
    print('PASS: recorded IIIF provenance and alignment reproduce; visual accuracy not established by program')

if __name__=='__main__':main()
