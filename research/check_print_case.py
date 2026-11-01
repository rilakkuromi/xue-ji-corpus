#!/usr/bin/env python3
"""Compare a recorded full-case model image reading to frozen text, not validate vision."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import build_close_read_160 as core

ROOT=core.ROOT
INPUT=ROOT/'research/print_case_reviews/KCLY_H3_P005_2026-10-28.json'
OUT=ROOT/'research/samples/print_case_kcly_h3_p005.json'
PUNCTUATION=set('，。；：！？、')

def align_blocks(blocks,chars,reading):
    if ''.join(b['working'] for b in blocks)!=''.join(c[2] for c in chars) or ''.join(b['scan'] for b in blocks)!=reading:
        raise ValueError('Reviewed blocks must cover both full texts in order')
    result=[];wi=si=0
    for b in blocks:
        w,s,k=b['working'],b['scan'],b['kind']
        valid=(k=='equal' and w==s and bool(w) or
               k=='insertion_in_print' and not w and bool(s) or
               k=='deletion_in_print' and bool(w) and not s or
               k=='substitution' and bool(w) and bool(s) and w!=s or
               k=='transposition_candidate' and w!=s and sorted(w)==sorted(s))
        if not valid:raise ValueError('Invalid reviewed alignment block')
        result.append({**b,'working_start_ordinal_zero_based':wi,'working_end_ordinal_exclusive':wi+len(w),
                       'scan_start_ordinal_zero_based':si,'scan_end_ordinal_exclusive':si+len(s),
                       'working_character_refs':[{'source_ref':sid,'source_start_char':p,'source_end_char_exclusive':p+1} for sid,p,_ in chars[wi:wi+len(w)]]})
        wi+=len(w);si+=len(s)
    return result

def build(record=None, path=INPUT):
    _,sample,index=core.build()
    r=copy.deepcopy(record) if record is not None else json.loads(path.read_text())
    if r.get('unresolved_readings'):
        raise ValueError('Unresolved image reading cannot be counted as full-case comparison')
    case=next(c for c in sample if c['case_id']==r['case_id'])
    if r['human_adjudication']!='pending' or r['initial_query_eligible'] is not False:
        raise ValueError('Unsupported print verification or query claim')
    if r['full_case_model_image_comparisons']!=1 or r['expert_collated_cases']!=0:
        raise ValueError('Model image comparison is not expert collation')
    witness=json.loads((ROOT/r['pdf_record']).read_text())
    work=r['case_id'].split('-')[1]
    if {s['source_ref'].split('-')[1] for s in witness['spots']}!={work}:
        raise ValueError('Case work and PDF witness work mismatch')
    if r['pdf_record']=='research/scan_reviews/KCLY_target_spots_2026-10-27.json':
        import check_witness_bibliography as bibliography
        audited=bibliography.build()
        if audited['pdf_sha256']!=witness['pdf_sha256']:raise ValueError('Bibliographic witness mismatch')
        r.update(bibliographic_review_ref='research/witness_reviews/KCLY_bibliography_2026-10-29.json',
                 edition_date_verification=audited['date_claim']['status'])
        import check_witness_catalog as catalog
        reviewed_catalog=catalog.build()
        r.update(catalog_review_ref='research/witness_reviews/KCLY_catalog_2026-10-29.json',
                 edition_catalog_verification=reviewed_catalog['edition_catalog_verification'])
    else:
        r.update(edition_date_verification='inherited_metadata_not_reverified_from_images',
                 bibliographic_metadata_origin=witness.get('bibliographic_metadata_origin','inherited_scan_record_not_new_titlepage_audit'))
    if not 1<=r['pdf_page']<=witness['pdf_pages']:raise ValueError('Page outside PDF')
    if any(not 1<=x['pdf_page']<=witness['pdf_pages'] for x in r.get('boundary_checks',[])):
        raise ValueError('Boundary inspection page outside PDF')
    reading=''.join(r['scan_columns'])
    column_positions=[]
    if 'column_locations' in r:
        if len(r['column_locations'])!=len(r['scan_columns']):raise ValueError('Column location roster drift')
        previous=None
        for col,(text,location) in enumerate(zip(r['scan_columns'],r['column_locations']),1):
            start=location.get('start_char_one_based',1)
            if (not 1<=location['pdf_page']<=witness['pdf_pages'] or
                location['page_half'] not in {'left','right'} or
                type(location['column_from_right']) is not int or location['column_from_right']<1 or
                type(start) is not int or start<1):
                raise ValueError('Invalid column location')
            order=(location['pdf_page'],{'right':0,'left':1}[location['page_half']],location['column_from_right'])
            if previous is not None and order<=previous:raise ValueError('Duplicate or reversed column reading order')
            previous=order
            column_positions.extend({'scan_column_index':col,'scan_column_char_index':i+start} for i in range(len(text)))
    chars=[]
    used_pages={x['pdf_page'] for x in r.get('column_locations',[{'pdf_page':r['pdf_page']}])}
    if len(used_pages)>1:
        renders=r.get('page_renders',[])
        if (len(renders)!=len(used_pages) or {x['pdf_page'] for x in renders}!=used_pages or
            any(len(x.get('render_sha256',''))!=64 or any(c not in '0123456789abcdef' for c in x['render_sha256']) for x in renders)):
            raise ValueError('Cross-page reading requires one rendered-page identity per used page')
    for segment in case['segments']:
        text=index[segment['source_ref']]
        for pos in range(segment['start'],segment['end']):
            if text[pos] not in PUNCTUATION:
                chars.append((segment['source_ref'],pos,text[pos]))
    if 'alignment_blocks' in r:
        blocks=align_blocks(r['alignment_blocks'],chars,reading)
        if column_positions:
            refs=[{**p,**r['column_locations'][p['scan_column_index']-1],'scan_char':reading[i]}
                  for i,p in enumerate(column_positions)]
            for block in blocks:
                block['scan_character_refs']=refs[block['scan_start_ordinal_zero_based']:block['scan_end_ordinal_exclusive']]
        return {**r,'source_git_blob':core.base.BLOB_SHA_AT_FREEZE,
                'case_text_sha256':hashlib.sha256(case['body'].encode()).hexdigest(),
                'pdf_sha256':witness['pdf_sha256'],'pdf_bytes':witness['pdf_bytes'],
                'working_case_evidence':core.evidence_for(case,''.join(case['parts']),index),
                'scan_reading':reading,'compared_body_characters_excluding_modern_punctuation':len(chars),
                'scan_body_characters':len(reading),'reviewed_alignment':blocks,
                'block_differences':[b for b in blocks if b['kind']!='equal'],
                'differences':[], 'difference_counting_scope':'block_events_not_character_position_differences',
                'limitations':['Manual model alignment is not expert collation or an automatic correction.',
                               'Insertion/deletion labels are relative to frozen working text, not edition history.']}
    if len(chars)!=len(reading):raise ValueError('Full-case alignment requires equal character count; review insertions or omissions explicitly')
    alignment=[{'ordinal':i+1,'source_ref':sid,'source_start_char':pos,
                'source_end_char_exclusive':pos+1,'working':w,'scan':s,
                'status':'same_model_reading' if w==s else 'different_model_reading'}
               for i,((sid,pos,w),s) in enumerate(zip(chars,reading))]
    differences=[x for x in alignment if x['working']!=x['scan']]
    if column_positions:
        for row,position in zip(alignment,column_positions):row.update(position)
    if [{'working':x['working'],'scan':x['scan']} for x in differences]!=r['expected_substitutions']:
        raise ValueError('Recorded print differences drift')
    return {**r,'source_git_blob':core.base.BLOB_SHA_AT_FREEZE,
            'case_text_sha256':hashlib.sha256(case['body'].encode()).hexdigest(),
            'pdf_sha256':witness['pdf_sha256'],'pdf_bytes':witness['pdf_bytes'],
            'working_case_evidence':core.evidence_for(case,''.join(case['parts']),index),
            'scan_reading':reading,'compared_body_characters_excluding_modern_punctuation':len(chars),
            'differences':differences,'alignment':alignment,
            'limitations':['Program validates recorded alignment and provenance, not the model visual reading.',
                           'One printed witness cannot adjudicate other editions or correct the frozen corpus.',
                           'Punctuation, kundoku marks and paleographic glyph variants are not fully collated.']}

def pending_readings(record=None):
    paths=sorted((ROOT/'research/print_case_pending').glob('*.json'))
    rows=[copy.deepcopy(record)] if record is not None else [json.loads(p.read_text()) for p in paths]
    _,sample,_=core.build();cases={c['case_id']:c for c in sample}
    for r in rows:
        if (r['status']!='unresolved_image_glyph_not_full_case_comparison' or
            r['human_adjudication']!='pending' or r['initial_query_eligible'] is not False or
            r['full_case_model_image_comparisons']!=0 or r['expert_collated_cases']!=0):
            raise ValueError('Pending image record cannot claim completion or query eligibility')
        witness=json.loads((ROOT/r['pdf_record']).read_text())
        if {s['source_ref'].split('-')[1] for s in witness['spots']}!={r['case_id'].split('-')[1]}:
            raise ValueError('Pending case work and PDF witness work mismatch')
        if r['pdf_sha256']!=witness['pdf_sha256']:raise ValueError('Pending PDF identity drift')
        if not r['unresolved_readings']:raise ValueError('Pending image record needs an unresolved reading')
        pages=r['viewed_pdf_pages']
        if not pages or len(pages)!=len(set(pages)) or any(not 1<=p<=witness['pdf_pages'] for p in pages):
            raise ValueError('Invalid pending viewed pages')
        for u in r['unresolved_readings']:
            if (not u['working_quote'] or u['working_quote'] not in cases[r['case_id']]['body'] or
                u['resolved_scan_text'] is not None or u['pdf_page'] not in pages or
                u['page_half'] not in {'left','right'} or type(u['column_from_right']) is not int or u['column_from_right']<1):
                raise ValueError('Pending quote or unresolved location drift')
    if len({r['case_id'] for r in rows})!=len(rows):raise ValueError('Duplicate pending case')
    return rows

def summarize(records, pending=None):
    ids=[r['case_id'] for r in records]
    if len(ids)!=len(set(ids)):raise ValueError('Duplicate full-case comparison case')
    result={'scope':'full_case_model_image_comparisons_not_expert_collation',
            'cases':len(records),'case_ids':ids,
            'compared_body_characters':sum(r['compared_body_characters_excluding_modern_punctuation'] for r in records),
            'different_character_positions':sum(len(r['differences']) for r in records),
            'unique_pdf_pages':len({(r['pdf_sha256'],loc['pdf_page']) for r in records
                                    for loc in r.get('column_locations',[{'pdf_page':r['pdf_page']}])}),
            'expert_collated_cases':0,'initial_query_exported':0}
    if any('block_differences' in r for r in records):
        result.update(reviewed_block_cases=sum('block_differences' in r for r in records),
                      reviewed_block_difference_events=sum(len(r.get('block_differences',[])) for r in records),
                      counting_note='different_character_positions covers equal-length cases only; block events reported separately')
        pages={(r['pdf_sha256'],loc['pdf_page']) for r in records for loc in r.get('column_locations',[{'pdf_page':r['pdf_page']}])}
        boundaries={(r['pdf_sha256'],x['pdf_page']) for r in records for x in r.get('boundary_checks',[])}
        result.update(boundary_only_pdf_pages=len(boundaries-pages),unique_pdf_pages_including_boundary_checks=len(pages|boundaries))
    if pending:
        if set(ids)&{r['case_id'] for r in pending}:raise ValueError('Pending case cannot also be completed')
        result.update(pending_model_image_readings=len(pending),pending_case_ids=[r['case_id'] for r in pending])
    works=sorted({r['case_id'].split('-')[1] for r in records})
    result.update(cases_by_work={w:sum(r['case_id'].split('-')[1]==w for r in records) for w in works},
                  compared_body_characters_by_work={w:sum(r['compared_body_characters_excluding_modern_punctuation'] for r in records if r['case_id'].split('-')[1]==w) for w in works})
    return result

def main():
    p=argparse.ArgumentParser();p.add_argument('--write',action='store_true');p.add_argument('--pdf',type=Path,action='append',help='Repeat for every compared PDF when --all spans multiple witnesses');p.add_argument('--all',action='store_true');a=p.parse_args()
    supplied={(pdf.stat().st_size,hashlib.sha256(pdf.read_bytes()).hexdigest()) for pdf in (a.pdf or [])}
    paths=sorted((ROOT/'research/print_case_reviews').glob('*.json')) if a.all else [INPUT]
    records=[]
    for path in paths:
        r=build(path=path);records.append(r)
        if supplied and (r['pdf_bytes'],r['pdf_sha256']) not in supplied:
            raise ValueError('PDF identity mismatch')
        # Preserve the first published artifact name for backwards compatibility.
        out=OUT if path==INPUT else ROOT/'research/samples'/('print_case_'+path.stem.lower()+'.json')
        text=json.dumps(r,ensure_ascii=False,indent=2)+'\n'
        if a.write:out.write_text(text)
        if out.read_text()!=text:raise ValueError('Full-case image comparison artifact drift')
    result=summarize(records,pending_readings() if a.all else None)
    if a.all:
        out=ROOT/'research/samples/print_case_summary.json';text=json.dumps(result,ensure_ascii=False,indent=2)+'\n'
        if a.write:out.write_text(text)
        if out.read_text()!=text:raise ValueError('Full-case summary drift')
    print(json.dumps(result,ensure_ascii=False))
    print('PASS: recorded full-case model reading reproduces; visual accuracy and expert review not established')

if __name__=='__main__':main()
