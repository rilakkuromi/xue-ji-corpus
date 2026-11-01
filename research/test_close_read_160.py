"""Negative regression checks for provenance, boundary and verification claims."""
import copy
import unittest
import build_close_read_160 as review


class ReviewContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.records, cls.sample, cls.index = review.build()

    def test_all_rows_are_five_domain_model_drafts(self):
        review.validate_records(self.records, self.sample, self.index)
        self.assertEqual(sum(r['default_retrieval_excluded'] for r in self.records), 3)
        self.assertEqual(sum(len(o['evidence']) > 1 for r in self.records
                             for f in r['fields'].values() for o in f['observations']), 13)

    def test_tampered_literal_rejected(self):
        rows = copy.deepcopy(self.records)
        rows[0]['fields']['symptoms']['observations'][0]['evidence'][0]['raw_quote'] += '偽'
        with self.assertRaisesRegex(ValueError, 'Literal evidence'):
            review.validate_records(rows, self.sample, self.index)

    def test_outside_case_span_rejected(self):
        rows = copy.deepcopy(self.records)
        e = rows[0]['fields']['symptoms']['observations'][0]['evidence'][0]
        e['source_end_char_exclusive'] = len(self.index[e['source_ref']]) + 1
        with self.assertRaisesRegex(ValueError, 'outside case'):
            review.validate_records(rows, self.sample, self.index)

    def test_unchecked_query_export_rejected(self):
        rows = copy.deepcopy(self.records)
        rows[0]['fields']['mechanism']['observations'][0]['initial_query_eligible'] = True
        with self.assertRaisesRegex(ValueError, 'query export'):
            review.validate_records(rows, self.sample, self.index)

    def test_invented_human_review_rejected(self):
        rows = copy.deepcopy(self.records)
        rows[0]['human_adjudication'] = 'completed'
        with self.assertRaisesRegex(ValueError, 'verification claim'):
            review.validate_records(rows, self.sample, self.index)

    def test_pending_source_exclusion_cannot_be_dropped(self):
        rows = copy.deepcopy(self.records)
        r = next(r for r in rows if r['default_retrieval_excluded'])
        r['default_retrieval_excluded'] = False
        with self.assertRaisesRegex(ValueError, 'exclusion lost'):
            review.validate_records(rows, self.sample, self.index)

    def test_join_retains_unicode_and_punctuation(self):
        case = {'case_id': 'synthetic', 'parts': ['甲\u3000乙', '丙，丁'],
                'segments': [{'source_ref':'A','start':1,'end':4},
                             {'source_ref':'B','start':0,'end':3}]}
        index = {'A':'前甲\u3000乙後','B':'丙，丁尾'}
        ev = review.evidence_for(case, '乙丙，', index)
        self.assertEqual([e['raw_quote'] for e in ev], ['乙','丙，'])
        with self.assertRaisesRegex(ValueError, 'not found'):
            review.evidence_for(case, '甲乙', index)

    def test_repeated_quote_requires_disambiguation(self):
        case = {'case_id':'synthetic','parts':['甲甲'],
                'segments':[{'source_ref':'A','start':0,'end':2}]}
        with self.assertRaisesRegex(ValueError, 'ambiguous'):
            review.evidence_for(case, '甲', {'A':'甲甲'})

    def test_wrong_source_blob_rejected(self):
        rows = copy.deepcopy(self.records)
        rows[0]['source_git_blob'] = '0' * 40
        with self.assertRaisesRegex(ValueError, 'provenance drift'):
            review.validate_records(rows, self.sample, self.index)

    def test_duplicate_domain_observation_rejected(self):
        rows = copy.deepcopy(self.records)
        obs = rows[0]['fields']['symptoms']['observations']
        obs.append(copy.deepcopy(obs[0]))
        with self.assertRaisesRegex(ValueError, 'Duplicate observation'):
            review.validate_records(rows, self.sample, self.index)

    def test_snapshot_search_includes_overlapping_occurrences(self):
        from check_sample_snapshots import literal_locations
        self.assertEqual(literal_locations('甲甲甲', '甲甲'),
                         [{'start_char': 0, 'end_char_exclusive': 2},
                          {'start_char': 1, 'end_char_exclusive': 3}])
        with self.assertRaisesRegex(ValueError, 'Empty evidence'):
            literal_locations('甲', '')

    def test_snapshot_alignment_preserves_second_occurrence(self):
        from check_sample_snapshots import quote_alignment
        ev = {'raw_quote': '甲', 'source_start_char': 2, 'source_end_char_exclusive': 3}
        aligned = quote_alignment('甲乙甲', '甲乙甲', ev)
        self.assertEqual(aligned['snapshot_start_char'], 2)
        self.assertEqual(aligned['snapshot_occurrence_count'], 2)
        ambiguous = quote_alignment('甲丙甲', '甲乙甲', ev)
        self.assertNotIn('snapshot_start_char', ambiguous)
        self.assertEqual(len(ambiguous['snapshot_candidate_spans']), 2)
        self.assertIsNone(quote_alignment('乙', '甲乙甲', ev))
        with self.assertRaisesRegex(ValueError, 'lost evidence offset'):
            quote_alignment('甲乙甲', '甲乙甲', dict(ev, source_start_char=1))

    def test_second_pass_preserves_later_episode(self):
        by_id = {r['case_id']: r for r in self.records}
        row = by_id['XJ-BYCY-C-V5-L0521']
        for field in ('symptoms', 'mechanism'):
            self.assertEqual(row['fields'][field]['observations'][-1]['time_phase'],
                             'later_narrator_window')
        course = by_id['XJ-BYCY-C-V5-L0052']['fields']['course']['observations'][0]
        self.assertEqual(course['narrative_role'],
                         'after_earlier_treatment_before_narrator_assessment')

    def test_time_and_speaker_regressions(self):
        by_id = {r['case_id']:r for r in self.records}
        patient = by_id['XJ-NKZY-C-V2-P007-1']['fields']['mechanism']['observations'][0]
        self.assertEqual(patient['assertion_type'], 'patient_interpretation')
        post = by_id['XJ-LZWKFH-C-V2-P015-1']['fields']['mechanism']['observations']
        self.assertTrue(all(o['time_phase'] == 'later_narrator_window' for o in post))
        prior = by_id['XJ-KCLY-C-H3-P014-1']['fields']['prior_treatment']['observations']
        self.assertEqual(prior, [])


class ExtendedAndScanTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import build_extended_kcly as extended
        import check_scan_spots as scan
        import json
        cls.extended=extended
        cls.rows,cls.cases,cls.index=extended.build()
        cls.scan=scan
        cls.scan_record=json.loads(scan.PATH.read_text())

    def test_empty_tongue_slot_is_not_explicit_absence(self):
        rows=copy.deepcopy(self.rows)
        row=next(r for r in rows if not r['fields']['tongue_features']['observations'])
        row['fields']['tongue_features']['missingness']='explicitly_absent'
        with self.assertRaisesRegex(ValueError,'unresolved, not absent'):
            self.extended.validate(rows,self.cases,self.index)

    def test_extended_observation_cannot_enable_query_export(self):
        rows=copy.deepcopy(self.rows)
        row=next(r for r in rows if r['fields']['pulse']['observations'])
        row['fields']['pulse']['observations'][0]['initial_query_eligible']=True
        with self.assertRaisesRegex(ValueError,'query or phase'):
            self.extended.validate(rows,self.cases,self.index)

    def test_recurrent_case_pulse_stages_remain_separate(self):
        row=next(r for r in self.rows if r['case_id']=='XJ-KCLY-C-H2-P004-1')
        obs=row['fields']['pulse']['observations']
        self.assertEqual([o['reading_joined_source_segments'] for o in obs],['脈數而有力','脈數而無力'])
        self.assertEqual([o['time_phase'] for o in obs],['initial_narrator_window','later_narrator_window'])

    def test_tongue_swelling_cannot_be_promoted_to_formal_exam(self):
        rows=copy.deepcopy(self.rows)
        row=next(r for r in rows if r['fields']['tongue_features']['observations'])
        row['fields']['tongue_features']['observations'][0]['interpretation_type']='formal_tongue_exam'
        with self.assertRaisesRegex(ValueError,'formal tongue-exam'):
            self.extended.validate(rows,self.cases,self.index)

    def test_scan_spot_cannot_claim_full_case_collation(self):
        rec=copy.deepcopy(self.scan_record)
        rec['full_case_print_collations']=3
        with self.assertRaisesRegex(ValueError,'adjudication claim'):
            self.scan.validate(rec,self.index)

    def test_scan_page_must_be_in_downloaded_pdf(self):
        rec=copy.deepcopy(self.scan_record)
        rec['spots'][0]['pdf_page']=49
        with self.assertRaisesRegex(ValueError,'page out of range'):
            self.scan.validate(rec,self.index)

    def test_scan_artifact_hash_rejects_unrelated_pdf(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'unrelated.pdf';path.write_bytes(b'%PDF-not-the-recorded-artifact')
            with self.assertRaisesRegex(ValueError,'differs from recorded'):
                self.scan.validate(self.scan_record,self.index,path)

    def test_scan_reference_does_not_leak_to_other_case_in_same_paragraph(self):
        spot=self.scan_record['spots'][0]
        ev=spot['working_evidence']
        other_case={'segments':[{'source_ref':spot['source_ref'],
                                 'start':0,'end':ev['source_start_char']}]}
        self.assertEqual(review.case_scan_refs(other_case,[spot]),[])
        own_case={'segments':[{'source_ref':spot['source_ref'],
                               'start':ev['source_start_char'],'end':ev['source_end_char_exclusive']}]}
        self.assertEqual(review.case_scan_refs(own_case,[spot]),[spot['spot_id']])

    def test_case_cannot_invent_targeted_scan_reference(self):
        rows,sample,index=review.build()
        row=next(r for r in rows if not r['targeted_print_spot_refs'])
        row['targeted_print_spot_refs']=['unviewed-page']
        with self.assertRaisesRegex(ValueError,'verification claim'):
            review.validate_records(rows,sample,index)


class ZtlyEventTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import build_event_pilot as events
        cls.events=events
        cls.record,cls.case,cls.index=events.build()

    def test_patient_explanation_is_not_physician_endorsement(self):
        records,_,_=review.build()
        row=next(r for r in records if r['case_id']=='XJ-ZTLY-C-V1-P102-1')
        obs=row['fields']['mechanism']['observations']
        self.assertEqual([o['assertion_type'] for o in obs],
                         ['patient_interpretation','physician_interpretation'])
        self.assertEqual(obs[0]['speaker_role'],'patient_or_family')

    def test_role_override_cannot_rewrite_evidence(self):
        case={'case_id':'synthetic','parts':['甲'],
              'segments':[{'source_ref':'A','start':0,'end':1}]}
        overrides={'synthetic':{'mechanism':{'甲':{'evidence':[]}}}}
        with self.assertRaisesRegex(ValueError,'may not alter evidence'):
            review.make_observation(case,'mechanism','甲',{'A':'甲'},{},overrides)

    def test_general_theory_scan_does_not_attach_to_case(self):
        _,sample,_=review.build()
        case=next(c for c in sample if c['case_id']=='XJ-ZTLY-C-V1-P054-1')
        refs=review.case_scan_refs(case,review.scan_spots())
        self.assertIn('ZTLY-24-P054-CASE',refs)
        self.assertNotIn('ZTLY-24-P054-THEORY',refs)

    def test_medicinal_wine_does_not_generate_drinking_habit(self):
        import build_extended_kcly as extended
        rows,_,_=extended.build('ZTLY')
        row=next(r for r in rows if r['case_id']=='XJ-ZTLY-C-V1-P057-1')
        self.assertEqual(row['fields']['habits']['observations'],[])
        self.assertEqual(row['fields']['habits']['missingness'],
                         'unrecorded_or_unresolved_not_explicit_absence')

    def test_full_event_window_cannot_drop_outcome(self):
        row=copy.deepcopy(self.record);row['events'].pop();row['relations'].pop()
        with self.assertRaisesRegex(ValueError,'cover entire case window'):
            self.events.validate(row,self.case,self.index)

    def test_advice_is_not_performed_treatment(self):
        row=copy.deepcopy(self.record)
        row['events'][2]['intervention_status']='narrated_as_performed'
        with self.assertRaisesRegex(ValueError,'Recommendation cannot be promoted'):
            self.events.validate(row,self.case,self.index)

    def test_narrative_adjacency_is_not_causality(self):
        row=copy.deepcopy(self.record);row['relations'][0]['relation']='causes'
        with self.assertRaisesRegex(ValueError,'must not invent causality'):
            self.events.validate(row,self.case,self.index)

    def test_relative_day_cannot_invent_calendar_date(self):
        row=copy.deepcopy(self.record);row['events'][5]['calendar_date']='1528-01-02'
        with self.assertRaisesRegex(ValueError,'Unsupported event calendar date'):
            self.events.validate(row,self.case,self.index)

    def test_refusal_after_advice_is_not_initial_window(self):
        row=copy.deepcopy(self.record);row['events'][3]['time_phase']='initial_narrator_window'
        with self.assertRaisesRegex(ValueError,'phase crosses care-advice anchor'):
            self.events.validate(row,self.case,self.index)


class NkczIntentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import build_event_pilot as events
        cls.events=events
        cls.row,cls.case,cls.index=events.build('NKCZ')

    def test_prior_interpreter_is_not_assumed_to_be_narrator(self):
        rows,_,_=review.build()
        row=next(r for r in rows if r['case_id']=='XJ-NKCZ-C-V1-P103-1')
        obs=row['fields']['mechanism']['observations']
        self.assertEqual(obs[0]['speaker_role'],'uncertain_prior_interpreter')
        self.assertEqual(obs[0]['assertion_type'],'reported_prior_interpretation_actor_uncertain')
        self.assertEqual(obs[1]['assertion_type'],'physician_interpretation')
        self.assertEqual(row['fields']['symptoms']['observations'][0]['narrative_role'],
                         'after_earlier_treatment_before_narrator_assessment')

    def test_retrospective_mechanism_remains_later(self):
        rows,_,_=review.build()
        row=next(r for r in rows if r['case_id']=='XJ-NKCZ-C-V1-P022-1')
        self.assertTrue(all(o['time_phase']=='later_narrator_window'
                            for o in row['fields']['mechanism']['observations']))

    def test_habitual_affect_does_not_invent_episode_trigger(self):
        import build_extended_kcly as extended
        ext,_,_=extended.build('NKCZ')
        rows,_,_=review.build()
        cid='XJ-NKCZ-C-V1-P026-1'
        self.assertTrue(next(r for r in ext if r['case_id']==cid)['fields']['habits']['observations'])
        self.assertFalse(next(r for r in rows if r['case_id']==cid)['fields']['trigger']['observations'])

    def test_care_intent_cannot_be_claimed_performed(self):
        row=copy.deepcopy(self.row)
        row['events'][2]['intervention_status']='narrated_as_performed'
        with self.assertRaisesRegex(ValueError,'Intention cannot be promoted'):
            self.events.validate(row,self.case,self.index)

    def test_care_intent_cannot_be_claimed_issued_recommendation(self):
        row=copy.deepcopy(self.row)
        row['events'][2]['event_type']='care_recommendation'
        row['events'][2]['intervention_status']='recommendation_only_no_performance_claim'
        with self.assertRaisesRegex(ValueError,'anchor type differs'):
            self.events.validate(row,self.case,self.index)

    def test_event_identity_cannot_be_relabelled(self):
        row=copy.deepcopy(self.row);row['case_id']='XJ-ZTLY-C-V1-P108-1'
        with self.assertRaisesRegex(ValueError,'identity drift'):
            self.events.validate(row,self.case,self.index)


class NkzyClaimAndExclusionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import build_event_pilot as events
        import build_extended_kcly as extended
        cls.events=events;cls.extended=extended
        cls.event,cls.case,cls.index=events.build('NKZY')
        cls.rows,cls.cases,cls.index=extended.build('NKZY')
        cls.core,_,_=review.build()

    def test_three_pending_cases_stay_excluded_in_extended_dimensions(self):
        self.assertEqual(sum(r['default_retrieval_excluded'] for r in self.rows),3)
        rows=copy.deepcopy(self.rows)
        row=next(r for r in rows if r['default_retrieval_excluded'])
        row['default_retrieval_excluded']=False
        with self.assertRaisesRegex(ValueError,'pending-source exclusion lost'):
            self.extended.validate(rows,self.cases,self.index)

    def test_claimed_huanglian_is_not_performed_treatment(self):
        row=copy.deepcopy(self.event)
        event=next(e for e in row['events'] if e['event_id']=='E12')
        event['intervention_status']='narrated_as_performed'
        with self.assertRaisesRegex(ValueError,'claim cannot become performed'):
            self.events.validate(row,self.case,self.index)

    def test_claim_cannot_be_retyped_to_intervention(self):
        row=copy.deepcopy(self.event)
        event=next(e for e in row['events'] if e['event_id']=='E12')
        event['event_type']='intervention'
        with self.assertRaisesRegex(ValueError,'claim cannot become performed'):
            self.events.validate(row,self.case,self.index)

    def test_theory_does_not_generate_sexual_exposure(self):
        row=next(r for r in self.core if r['case_id']=='XJ-NKZY-C-V2-P078-1')
        self.assertFalse(row['fields']['trigger']['observations'])
        self.assertTrue(all(o['assertion_type']=='quoted_theory'
                            for o in row['fields']['mechanism']['observations']))

    def test_book_prediction_is_not_patient_three_year_course(self):
        row=next(r for r in self.core if r['case_id']=='XJ-NKZY-C-V1-P002-1')
        self.assertTrue(all('三年' not in o['reading_joined_source_segments']
                            for o in row['fields']['course']['observations']))

    def test_patient_suspicion_is_separate_from_later_narrator_judgment(self):
        row=next(r for r in self.core if r['case_id']=='XJ-NKZY-C-V1-P126-1')
        obs=row['fields']['mechanism']['observations']
        self.assertEqual(obs[0]['assertion_type'],'patient_interpretation')
        self.assertEqual(obs[1]['assertion_type'],'physician_interpretation')
        self.assertEqual(obs[2]['time_phase'],'later_narrator_window')

    def test_ice_water_is_episode_behavior_not_premorbid_habit(self):
        row=next(r for r in self.rows if r['case_id']=='XJ-NKZY-C-V1-P063-1')
        self.assertEqual(row['fields']['habits']['observations'][0]['interpretation_type'],
                         'episode_drinking_behavior_not_premorbid_habit')

    def test_pulse_prognosis_is_explicitly_marked_interpretive(self):
        row=next(r for r in self.rows if r['case_id']=='XJ-NKZY-C-V1-P075-1')
        obs=row['fields']['pulse']['observations'][0]
        self.assertEqual(obs['interpretation_type'],'narrated_pulse_with_narrator_prognostic_interpretation')
        self.assertEqual(obs['time_phase'],'later_narrator_window')


class WksyForecastAndWitnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import build_event_pilot as events
        import check_scan_spots as scan
        import json
        cls.events=events;cls.scan=scan
        cls.row,cls.case,cls.index=events.build('WKSY')
        cls.core,_,_=review.build()
        cls.scan_record=json.loads(scan.PATH.read_text())

    def test_healing_forecast_is_not_observed_outcome(self):
        row=copy.deepcopy(self.row)
        row['events'][3]['intervention_status']='observed_outcome'
        with self.assertRaisesRegex(ValueError,'expectation cannot become observed'):
            self.events.validate(row,self.case,self.index)

    def test_healing_forecast_cannot_be_retyped_as_outcome(self):
        row=copy.deepcopy(self.row)
        row['events'][3]['event_type']='narrated_outcome'
        with self.assertRaisesRegex(ValueError,'expectation cannot become observed'):
            self.events.validate(row,self.case,self.index)

    def test_collective_comparison_is_not_individual_death(self):
        row=next(r for r in self.core if r['case_id']=='XJ-WKSY-C-V3-P120-1')
        self.assertTrue(all('俱不救' not in o['reading_joined_source_segments']
                            for f in row['fields'].values() for o in f['observations']))

    def test_narrator_sexual_explanation_does_not_generate_reported_exposure(self):
        row=next(r for r in self.core if r['case_id']=='XJ-WKSY-C-V3-P083-1')
        self.assertFalse(row['fields']['trigger']['observations'])
        obs=next(o for o in row['fields']['mechanism']['observations']
                 if '思色' in o['reading_joined_source_segments'])
        self.assertEqual(obs['assertion_type'],'physician_interpretation')
        self.assertEqual(obs['time_phase'],'later_narrator_window')

    def test_general_theory_does_not_add_case_observations(self):
        row=next(r for r in self.core if r['case_id']=='XJ-WKSY-C-V3-P026-1')
        limit=self.index['XJ-WKSY-V3-P026'].index('經云')
        self.assertTrue(all(e['source_end_char_exclusive']<=limit
                            for f in row['fields'].values() for o in f['observations'] for e in o['evidence']))

    def test_mechanism_stops_before_next_treatment_marker(self):
        row=next(r for r in self.core if r['case_id']=='XJ-WKSY-C-V3-P017-1')
        obs=row['fields']['mechanism']['observations'][-1]
        self.assertTrue(obs['reading_joined_source_segments'].endswith('不能潰'))
        ev=obs['evidence'][-1];text=self.index[ev['source_ref']]
        self.assertEqual(text[ev['source_end_char_exclusive']:ev['source_end_char_exclusive']+3],'先。用')

    def test_synthetic_opposing_scan_reading_is_recordable(self):
        rec=copy.deepcopy(self.scan_record)
        rec['spots'][0]['model_verdict']='opposes_working_reading_at_target_only'
        rec['spots'][0]['image_target_reading_without_added_punctuation']='合成反例讀法'
        self.scan.validate(rec,self.index)

    def test_synthetic_unresolved_scan_reading_is_recordable(self):
        rec=copy.deepcopy(self.scan_record)
        rec['spots'][0]['model_verdict']='unresolved_model_reading'
        rec['spots'][0]['image_target_reading_without_added_punctuation']=''
        self.scan.validate(rec,self.index)

    def test_claimed_scan_support_requires_target_in_recorded_reading(self):
        rec=copy.deepcopy(self.scan_record)
        rec['spots'][0]['image_target_reading_without_added_punctuation']=''
        with self.assertRaisesRegex(ValueError,'support lacks working target'):
            self.scan.validate(rec,self.index)

    def test_ambiguous_background_does_not_default_to_drinking(self):
        import build_extended_kcly as extended
        for reading in ('素清苦','飲食如常'):
            with self.subTest(reading=reading):
                with self.assertRaisesRegex(ValueError,'Unclassified background'):
                    extended.interpretation_kind('habits',reading)


class LyjyBoundaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        rows,_,_=review.build()
        cls.rows={r['case_id']:r for r in rows}

    def observations(self,suffix,field):
        return self.rows['XJ-LYJY-C-'+suffix]['fields'][field]['observations']

    def test_persistent_gloom_is_not_episode_trigger(self):
        self.assertEqual(self.observations('V1-P086','trigger'),[])
        import build_extended_kcly as ex
        rows,cases,index=ex.build('LYJY'); ex.validate(rows,cases,index)
        obs=next(r for r in rows if r['case_id'].endswith('V1-P086'))['fields']['habits']['observations'][0]
        self.assertIn('not_proven_episode_cause',obs['interpretation_type'])

    def test_no_narrator_encounter_does_not_invent_first_visit(self):
        for field in ('symptoms','course','prior_treatment'):
            for o in self.observations('V1-P095',field):
                self.assertEqual(o['time_phase'],'unknown')
        import build_extended_kcly as ex
        rows,_,_=ex.build('LYJY')
        obs=next(r for r in rows if r['case_id'].endswith('V1-P095'))['fields']['habits']['observations'][0]
        self.assertEqual(obs['time_phase'],'unknown')
        self.assertIn('no_quantity_or_dependency',obs['interpretation_type'])

    def test_hair_loss_after_prior_drug_not_untreated_baseline(self):
        for f in ('symptoms','course'):
            for o in self.observations('V1-P093',f):
                self.assertEqual(o['narrative_role'],'after_earlier_treatment_before_narrator_assessment')
                self.assertFalse(o['initial_query_eligible'])

    def test_alternative_clauses_and_sexual_background_stay_literal(self):
        obs=self.observations('V1-P094','symptoms')
        self.assertTrue(any('或發熱惡寒' in o['reading_joined_source_segments'] and '或冷至脛' in o['reading_joined_source_segments'] for o in obs))
        self.assertEqual(self.observations('V1-P094','trigger'),[])
        import build_extended_kcly as ex
        self.assertEqual(ex.interpretation_kind('habits','素不慎房勞'),'reported_sexual_behavior_background_no_frequency_or_episode_causality_inferred')

    def test_unknown_prefix_does_not_imply_absence(self):
        _,sample,index=review.build();c=next(c for c in sample if c['case_id']=='XJ-LYJY-C-V1-P095')
        o=review.make_observation(c,'symptoms','@unknown:膿水淋漓',index,{})
        self.assertEqual(o['time_phase'],'unknown')
        self.assertEqual(o['polarity'],'present')
        self.assertFalse(o['initial_query_eligible'])


class LzwStagedCareTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        rows,_,_=review.build();cls.rows={r['case_id']:r for r in rows}

    def obs(self,suffix,field):
        return self.rows['XJ-LZWKFH-C-'+suffix]['fields'][field]['observations']

    def test_early_negative_and_later_positive_fever_do_not_collapse(self):
        obs=self.obs('V5-P030-1','symptoms')
        early=next(o for o in obs if o['reading_joined_source_segments']=='且不潮熱')
        late=next(o for o in obs if '更加潮熱' in o['reading_joined_source_segments'])
        self.assertEqual((early['polarity'],early['time_phase']),('explicitly_absent','initial_narrator_window'))
        self.assertEqual((late['polarity'],late['time_phase']),('present','later_narrator_window'))

    def test_absent_pain_after_moxibustion_is_not_baseline(self):
        obs=self.obs('V4-P005-1','symptoms')
        phases={o['reading_joined_source_segments']:(o['time_phase'],o['polarity']) for o in obs}
        self.assertEqual(phases['不痛'],('initial_narrator_window','explicitly_absent'))
        self.assertEqual(phases['尚不知痛'],('later_narrator_window','explicitly_absent'))
        self.assertEqual(phases['始痛'],('later_narrator_window','present'))

    def test_warning_is_not_verified_drug_mechanism(self):
        o=self.obs('V5-P030-1','mechanism')[0]
        self.assertEqual(o['assertion_type'],'physician_interpretation')
        self.assertEqual(o['narrative_role'],'narrator_warning_not_independently_verified_drug_mechanism')

    def test_post_purgation_state_is_separate_from_traumatic_blood_loss(self):
        obs=self.obs('V8-P113-1','symptoms')
        self.assertEqual(obs[0]['reading_joined_source_segments'],'出血過多')
        self.assertIn('after_earlier_treatment',obs[1]['narrative_role'])
        self.assertEqual(self.obs('V8-P113-1','prior_treatment')[0]['speaker_role'],'uncertain')

    def test_later_intent_cannot_be_promoted_to_performed(self):
        import build_event_pilot as e
        row,case,index=e.build('LZWKFH');e.validate(row,case,index)
        intent=next(x for x in row['events'] if x['event_id']=='E03')
        self.assertEqual(intent['time_phase'],'later_narrator_window')
        bad=copy.deepcopy(row);bad['events'][2]['event_type']='reported_narrator_intervention';bad['events'][2]['intervention_status']='narrated_as_performed'
        with self.assertRaisesRegex(ValueError,'Protected intent'):
            e.validate(bad,case,index)

    def test_unknown_protected_intent_id_rejected(self):
        import build_event_pilot as e
        row,case,index=e.build('LZWKFH');row['intent_only_event_ids']=['E99']
        with self.assertRaisesRegex(ValueError,'Unknown intent-only'):
            e.validate(row,case,index)


class IndependentJoinQualityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import build_extended_kcly as ex
        cls.rows,cls.cases,cls.index=ex.build('BYCY')

    def test_wrong_work_identity_rejected(self):
        import build_extended_kcly as ex
        rows=copy.deepcopy(self.rows);rows[0]['work_ref']='XJ-NKZY'
        with self.assertRaisesRegex(ValueError,'work identity drift'):
            ex.validate(rows,self.cases,self.index)

    def test_literal_pulse_cannot_be_retyped_as_habit(self):
        import build_extended_kcly as ex
        rows=copy.deepcopy(self.rows)
        obs=next(o for r in rows for o in r['fields']['pulse']['observations'])
        obs['interpretation_type']='reported_drinking_habit_no_quantity_or_dependency_inferred'
        with self.assertRaisesRegex(ValueError,'interpretation type drift'):
            ex.validate(rows,self.cases,self.index)

    def test_mother_evidence_cannot_be_promoted_to_child_feature(self):
        import check_cross_annotation_consistency as q
        record=__import__('json').loads((review.ROOT/'research/review_inputs/BYCY_extended_review.json').read_text())
        rows=copy.deepcopy(self.rows)
        candidate=next(c for c in record['held_out_candidates'] if c['decision']=='other_person_not_patient_feature')
        c=self.cases[candidate['case_id']]
        obs=review.make_observation(c,'symptoms',candidate['reading'],self.index,{})
        row=next(r for r in rows if r['case_id']==c['case_id'])
        row['fields']['pulse']['observations'].append(obs)
        with self.assertRaisesRegex(ValueError,'Held-out evidence was promoted'):
            q.validate_held_out(record,self.cases,self.index,rows)

    def test_cold_drink_wording_is_not_premorbid_habit(self):
        import build_extended_kcly as ex
        row=next(r for r in self.rows if r['case_id']=='XJ-BYCY-C-V5-L0527')
        o=row['fields']['habits']['observations'][0]
        self.assertEqual(o['reading_joined_source_segments'],'飲冷')
        self.assertEqual(o['interpretation_type'],'episode_cold_drink_descriptor_not_premorbid_habit_or_quantified_intake')
        self.assertFalse(o['initial_query_eligible'])

    def test_compound_pus_nonformation_is_split_without_negating_whole_case(self):
        rows,_,_=review.build();row=next(r for r in rows if r['case_id']=='XJ-LZWKFH-C-V1-P016-1')
        obs=row['fields']['symptoms']['observations']
        self.assertEqual([(o['reading_joined_source_segments'],o['polarity']) for o in obs],[('臂患癰','present'),('不作膿','explicitly_absent')])

    def test_bounded_negation_screen_flags_compound_without_auto_relabeling(self):
        import check_cross_annotation_consistency as q
        fixture=[{'case_id':'synthetic','fields':{'symptoms':{'observations':[{'reading_joined_source_segments':'臂患癰，不作膿','polarity':'present'}]}}}]
        flags=q.negation_candidates(fixture)
        self.assertEqual(flags[0]['matched_cue'],'不作膿')
        self.assertEqual(fixture[0]['fields']['symptoms']['observations'][0]['polarity'],'present')

    def test_interval_comparison_excludes_touching_endpoints(self):
        import check_cross_annotation_consistency as q
        a=[{'source_ref':'A','source_start_char':0,'source_end_char_exclusive':2}]
        b=[{'source_ref':'A','source_start_char':2,'source_end_char_exclusive':4}]
        self.assertFalse(q.overlap(a,b))
        b[0]['source_start_char']=1;self.assertTrue(q.overlap(a,b))
        b[0]['source_ref']='B';self.assertFalse(q.overlap(a,b))

    def test_real_overlapping_body_feature_phase_mismatch_flagged(self):
        import build_extended_kcly as ex
        import check_cross_annotation_consistency as q
        core,_,_=review.build();rows,_,_=ex.build('LYJY')
        row=next(r for r in rows if r['case_id']=='XJ-LYJY-C-V1-P087')
        row['fields']['habitus']['observations'][0]['time_phase']='later_narrator_window'
        flags,_,_=q.phase_candidates(core,rows,[])
        self.assertTrue(any(f['case_id']==row['case_id'] and f['kind']=='overlapping_dimension_phase_difference' for f in flags))

    def test_real_event_core_phase_mismatch_flagged(self):
        import build_event_pilot as ev
        import check_cross_annotation_consistency as q
        core,_,_=review.build();row,_,_=ev.build('LZWKFH')
        c=next(r for r in core if r['case_id']==row['case_id'])
        c['fields']['mechanism']['observations'][0]['time_phase']='later_narrator_window'
        flags,_,_=q.phase_candidates(core,[],[row])
        self.assertTrue(any(f['kind']=='observation_event_phase_difference' and f['case_id']==row['case_id'] for f in flags))


class LyjyDeclinedCareTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import build_event_pilot as event
        cls.event = event
        cls.record, cls.case, cls.index = event.build('LYJY')

    def test_declined_care_cannot_become_performed(self):
        row = copy.deepcopy(self.record)
        row['events'][5]['intervention_status'] = 'narrated_as_performed'
        with self.assertRaisesRegex(ValueError, 'Protected refusal'):
            self.event.validate(row, self.case, self.index)

    def test_declined_care_cannot_become_patient_refusal(self):
        row = copy.deepcopy(self.record)
        row['events'][5]['actor_role'] = 'patient'
        with self.assertRaisesRegex(ValueError, 'Protected refusal'):
            self.event.validate(row, self.case, self.index)

    def test_death_cannot_be_dropped_from_window(self):
        row = copy.deepcopy(self.record)
        row['events'].pop()
        with self.assertRaisesRegex(ValueError, 'entire case window'):
            self.event.validate(row, self.case, self.index)

    def test_relative_month_cannot_become_calendar_date(self):
        row = copy.deepcopy(self.record)
        row['events'][-1]['calendar_date'] = '1600-01-30'
        with self.assertRaisesRegex(ValueError, 'calendar date'):
            self.event.validate(row, self.case, self.index)

class BycyRoleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import build_role_pilot as role
        cls.role=role
        cls.record,cls.case,cls.index=role.build()

    def reject_change(self, finding_id, key, value):
        row=copy.deepcopy(self.record)
        next(f for f in row['findings'] if f['id']==finding_id)[key]=value
        with self.assertRaisesRegex(ValueError,'person/modality'):
            self.role.validate(row,self.case,self.index)

    def test_mother_assessment_cannot_be_child_feature(self):
        self.reject_change('MOTHER','subjects',['child'])

    def test_shared_medicine_cannot_drop_mother(self):
        self.reject_change('BOTH','subjects',['child'])

    def test_proposed_fuzi_cannot_be_performed(self):
        self.reject_change('PLAN','assertion_type','narrated_as_performed')

    def test_conditional_death_cannot_be_observed_outcome(self):
        self.reject_change('COUNTER','assertion_type','narrated_death')

    def test_unresolved_sign_cannot_be_standard_pulse(self):
        self.reject_change('SIGN','assertion_type','standard_wrist_pulse')

    def test_roles_cannot_keep_labels_but_swap_evidence(self):
        row=copy.deepcopy(self.record)
        row['findings'][0]['evidence']=row['findings'][1]['evidence']
        with self.assertRaisesRegex(ValueError,'evidence mapping'):
            self.role.validate(row,self.case,self.index)

class BycyFullEventTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import build_event_pilot as event
        cls.event=event
        cls.record,cls.case,cls.index=event.build('BYCY')

    def reject_event_change(self,event_id,key,value):
        row=copy.deepcopy(self.record)
        next(e for e in row['events'] if e['event_id']==event_id)[key]=value
        with self.assertRaises(ValueError):self.event.validate(row,self.case,self.index)

    def test_mother_diagnosis_cannot_move_to_child(self):
        self.reject_event_change('E05','subjects',['child'])

    def test_shared_treatment_cannot_drop_mother(self):
        self.reject_event_change('E06','subjects',['child'])

    def test_proposed_fuzi_cannot_be_performed(self):
        self.reject_event_change('E10','intervention_status','narrated_as_performed')

    def test_conditional_warning_cannot_be_death(self):
        self.reject_event_change('E27','event_type','narrated_death')

    def test_unknown_prior_treater_cannot_be_narrator(self):
        self.reject_event_change('E08','actor_role','case_narrator')

    def test_calendar_conversion_rejected(self):
        self.reject_event_change('E16','calendar_date','1537-01-01')

class BycyAssessmentBoundaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import build_event_pilot as event
        cls.records,cls.sample,cls.index=review.build()
        cls.pilot,cls.case,_=event.build('BYCY')

    def test_mechanism_stops_before_performed_care(self):
        row=next(r for r in self.records if r['case_id']==self.case['case_id'])
        obs=row['fields']['mechanism']['observations'][0]
        self.assertEqual(obs['reading_joined_source_segments'],'余作胎毒')
        self.assertEqual(len(obs['evidence']),1)
        self.assertEqual(obs['time_phase'],'initial_narrator_window')
        self.assertEqual(''.join(e['raw_quote'] for e in self.pilot['events'][2]['evidence']),'治之而瘥')

    def test_old_merged_quote_still_triggers_phase_candidate(self):
        import check_cross_annotation_consistency as q
        rows=copy.deepcopy(self.records)
        obs=next(r for r in rows if r['case_id']==self.case['case_id'])['fields']['mechanism']['observations'][0]
        obs['reading_joined_source_segments']='余作胎毒治之'
        obs['evidence']=review.evidence_for(self.case,'余作胎毒治之',self.index)
        flags,_,_=q.phase_candidates(rows,[],[self.pilot])
        self.assertTrue(any(f['reading']=='余作胎毒治之' for f in flags))

class KclySignedWitnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import build_event_pilot as event
        cls.event=event
        cls.record,cls.case,cls.index=event.build('KCLY')

    def reject_change(self,event_id,key,value):
        row=copy.deepcopy(self.record)
        next(e for e in row['events'] if e['event_id']==event_id)[key]=value
        with self.assertRaises(ValueError):self.event.validate(row,self.case,self.index)

    def test_physician_quote_cannot_be_patient_interpretation(self):
        self.reject_change('E04','speaker_role','signed_patient_witness')

    def test_praise_cannot_be_verified_outcome(self):
        self.reject_change('E08','event_type','independently_verified_outcome')

    def test_bystander_opinion_cannot_be_physician_observation(self):
        self.reject_change('E07','actor_role','quoted_physician_lizhai')

    def test_signature_cannot_be_lizhai(self):
        row=copy.deepcopy(self.record);row['narrator_identity']='physician_lizhai'
        with self.assertRaisesRegex(ValueError,'narrator drift'):
            self.event.validate(row,self.case,self.index)

    def test_ganzhi_cannot_be_calendar_date(self):
        self.reject_change('E01','calendar_date','1541-08-15')

class FullCasePrintComparisonTests(unittest.TestCase):
    def record(self):
        import check_print_case as p
        import json
        return p,json.loads(p.INPUT.read_text())

    def test_model_reading_cannot_be_expert_review(self):
        p,r=self.record();r['human_adjudication']='completed'
        with self.assertRaisesRegex(ValueError,'verification'):p.build(r)

    def test_scan_omission_cannot_pass_equal_length_alignment(self):
        p,r=self.record();r['scan_columns'][0]=r['scan_columns'][0][1:]
        with self.assertRaisesRegex(ValueError,'character count'):p.build(r)

    def test_differences_cannot_be_silently_emptied(self):
        p,r=self.record();r['expected_substitutions']=[]
        with self.assertRaisesRegex(ValueError,'differences drift'):p.build(r)

    def test_print_page_must_exist(self):
        p,r=self.record();r['pdf_page']=49
        with self.assertRaisesRegex(ValueError,'outside PDF'):p.build(r)

class MultiCasePrintTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import check_print_case as p
        cls.p=p
        cls.rows=[p.build(path=f) for f in sorted((p.ROOT/'research/print_case_reviews').glob('*.json'))]

    def test_actual_roster_and_unresolved_differences_retained(self):
        summary=self.p.summarize(self.rows)
        self.assertEqual(summary['cases'],17)
        self.assertEqual(summary['compared_body_characters'],1151)
        self.assertEqual(summary['different_character_positions'],8)
        self.assertEqual(len(next(r for r in self.rows if r['case_id']=='XJ-KCLY-C-H3-P014-1')['differences']),0)

    def test_duplicate_case_cannot_inflate_full_case_count(self):
        with self.assertRaisesRegex(ValueError,'Duplicate'):
            self.p.summarize([self.rows[0],self.rows[0]])

    def test_same_pdf_page_cannot_inflate_unique_page_count(self):
        rows=copy.deepcopy(self.rows)
        for row in rows:
            row['pdf_page']=rows[0]['pdf_page']
            for loc in row.get('column_locations',[]):loc['pdf_page']=rows[0]['pdf_page']
        self.assertEqual(self.p.summarize(rows)['unique_pdf_pages'],3)

    def test_column_roster_cannot_drop_half_leaf(self):
        import json
        r=json.loads((self.p.ROOT/'research/print_case_reviews/KCLY_H1_P011_2026-10-28.json').read_text())
        r['column_locations'].pop()
        with self.assertRaisesRegex(ValueError,'roster'):self.p.build(r)

    def test_invalid_leaf_side_rejected(self):
        import json
        r=json.loads((self.p.ROOT/'research/print_case_reviews/KCLY_H1_P011_2026-10-28.json').read_text())
        r['column_locations'][0]['page_half']='unknown'
        with self.assertRaisesRegex(ValueError,'column location'):self.p.build(r)

    def test_summary_counts_all_column_pages(self):
        rows=copy.deepcopy(self.rows)
        next(r for r in rows if r['case_id']=='XJ-KCLY-C-H1-P011-1')['column_locations'][-1]['pdf_page']=7
        self.assertEqual(self.p.summarize(rows)['unique_pdf_pages'],self.p.summarize(self.rows)['unique_pdf_pages']+1)

    def test_cross_page_record_cannot_drop_render_identity(self):
        import json
        r=json.loads((self.p.ROOT/'research/print_case_reviews/KCLY_H1_P010_2026-10-29.json').read_text())
        r['page_renders'].pop()
        with self.assertRaisesRegex(ValueError,'rendered-page identity'):self.p.build(r)

    def test_true_page_join_and_case_boundary_preserved(self):
        row=next(r for r in self.rows if r['case_id']=='XJ-KCLY-C-H1-P010-1')
        self.assertTrue(row['scan_columns'][5].endswith('後因怒寒熱'))
        self.assertTrue(row['scan_columns'][6].startswith('耳痛'))
        self.assertEqual([x['pdf_page'] for x in row['column_locations']],[5]*6+[6]*7)

    def test_corrected_neighbor_column_numbers_preserved(self):
        row=next(r for r in self.rows if r['case_id']=='XJ-KCLY-C-H1-P011-1')
        self.assertEqual([x['column_from_right'] for x in row['column_locations'][:2]],[8,9])

class ReviewedBlockAlignmentTests(unittest.TestCase):
    def test_true_insert_is_preserved_without_source_padding(self):
        import check_print_case as p
        chars=[('A',0,'甲'),('A',1,'乙')]
        r=p.align_blocks([{'kind':'equal','working':'甲','scan':'甲'},
                          {'kind':'insertion_in_print','working':'','scan':'丙'},
                          {'kind':'equal','working':'乙','scan':'乙'}],chars,'甲丙乙')
        self.assertEqual(r[1]['working_character_refs'],[])
        self.assertEqual(r[1]['scan_end_ordinal_exclusive']-r[1]['scan_start_ordinal_zero_based'],1)

    def test_missing_working_text_rejected(self):
        import check_print_case as p
        with self.assertRaisesRegex(ValueError,'cover both'):
            p.align_blocks([{'kind':'equal','working':'甲','scan':'甲'}],[('A',0,'乙')],'甲')

    def test_different_reading_cannot_be_marked_equal(self):
        import check_print_case as p
        with self.assertRaisesRegex(ValueError,'Invalid'):
            p.align_blocks([{'kind':'equal','working':'甲','scan':'乙'}],[('A',0,'甲')],'乙')

    def test_false_transposition_rejected(self):
        import check_print_case as p
        with self.assertRaisesRegex(ValueError,'Invalid'):
            p.align_blocks([{'kind':'transposition_candidate','working':'甲乙','scan':'乙丙'}],[('A',0,'甲'),('A',1,'乙')],'乙丙')

class PrintTraceabilityAuditTests(unittest.TestCase):
    def record(self):
        import check_print_case as p
        import json
        return p,json.loads((p.ROOT/'research/print_case_reviews/KCLY_H1_P012_2026-10-28.json').read_text())

    def test_duplicate_column_location_rejected(self):
        p,r=self.record();r['column_locations'][1]=copy.deepcopy(r['column_locations'][0])
        with self.assertRaisesRegex(ValueError,'column reading order'):p.build(r)

    def test_reversed_column_order_rejected(self):
        p,r=self.record();r['column_locations'].reverse()
        with self.assertRaisesRegex(ValueError,'column reading order'):p.build(r)

    def test_print_insertion_has_physical_position_without_fake_source(self):
        p,r=self.record();row=p.build(r)
        insertion=next(b for b in row['reviewed_alignment'] if b['kind']=='insertion_in_print')
        self.assertEqual(insertion['working_character_refs'],[])
        ref=insertion['scan_character_refs'][0]
        self.assertEqual((ref['scan_char'],ref['pdf_page'],ref['page_half'],ref['column_from_right'],ref['scan_column_char_index']),('發',6,'left',5,10))

class WitnessBibliographyTests(unittest.TestCase):
    def record(self):
        import check_witness_bibliography as b
        return b,b.build()

    def test_inherited_year_cannot_be_image_verified(self):
        b,r=self.record();r['date_claim']['status']='image_verified'
        with self.assertRaisesRegex(ValueError,'Inherited date'):b.build(r)

    def test_claim_cannot_cite_unviewed_page(self):
        b,r=self.record();r['title_claim']['supporting_pdf_pages']=[4]
        with self.assertRaisesRegex(ValueError,'unviewed page'):b.build(r)

    def test_bibliography_cannot_switch_pdf_identity(self):
        b,r=self.record();r['pdf_sha256']='0'*64
        with self.assertRaisesRegex(ValueError,'identity drift'):b.build(r)

    def test_case_output_inherits_year_limit(self):
        import check_print_case as p
        r=p.build()
        self.assertEqual(r['edition_date_verification'],'inherited_metadata_not_reverified_from_images')
        self.assertIn('witness_reviews/',r['bibliographic_review_ref'])

class WitnessCatalogTests(unittest.TestCase):
    def test_catalog_cannot_be_promoted_to_colophon(self):
        import check_witness_catalog as c
        r=c.build();r['colophon_verified']=True
        with self.assertRaisesRegex(ValueError,'cannot be promoted'):c.build(r)

    def test_other_book_number_rejected(self):
        import check_witness_catalog as c
        r=c.build();r['catalog_fields']['book_number']='06265-0014'
        with self.assertRaisesRegex(ValueError,'book number'):c.build(r)

    def test_citation_template_date_cannot_be_overwritten(self):
        import check_witness_catalog as c
        r=c.build();r['citation_template_date_label']='1654'
        with self.assertRaisesRegex(ValueError,'Separate citation date'):c.build(r)

    def test_catalog_and_image_verification_remain_separate(self):
        import check_print_case as p
        r=p.build()
        self.assertEqual(r['edition_date_verification'],'inherited_metadata_not_reverified_from_images')
        self.assertEqual(r['edition_catalog_verification'],'institutional_catalog_record_supported_not_colophon_verified')
        self.assertIn('witness_reviews/',r['catalog_review_ref'])

class PrintLipBatchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import check_print_case as p
        cls.rows={key:p.build(path=p.ROOT/f'research/print_case_reviews/KCLY_H1_{key}_2026-10-30.json')
                  for key in ['P005','P006','P009']}

    def test_same_reading_still_has_complete_source_alignment(self):
        for r in self.rows.values():
            self.assertEqual(r['differences'],[])
            self.assertEqual(len(r['alignment']),len(r['scan_reading']))
            self.assertTrue(all(a['working']==a['scan'] and a['source_end_char_exclusive']==a['source_start_char']+1 for a in r['alignment']))
            self.assertEqual(r['expert_collated_cases'],0)
            self.assertFalse(r['initial_query_eligible'])

    def test_neighbor_cases_end_before_next_case(self):
        a,b=self.rows['P005'],self.rows['P006']
        self.assertEqual(a['column_locations'][-1],{'pdf_page':4,'page_half':'left','column_from_right':2})
        self.assertEqual(b['column_locations'][0],{'pdf_page':4,'page_half':'left','column_from_right':3})
        self.assertTrue(a['scan_reading'].endswith('數劑而愈'))
        self.assertTrue(b['scan_reading'].endswith('乃去梔加參術而痊'))

    def test_half_page_transition_preserves_source_character_refs(self):
        r=self.rows['P009'];cut=len(r['scan_columns'][0])
        self.assertEqual(r['column_locations'][0],{'pdf_page':5,'page_half':'right','column_from_right':9})
        self.assertEqual(r['column_locations'][1],{'pdf_page':5,'page_half':'left','column_from_right':1})
        self.assertEqual((r['alignment'][cut-1]['scan'],r['alignment'][cut]['scan']),('出','血'))
        self.assertEqual((r['alignment'][cut-1]['scan_column_index'],r['alignment'][cut]['scan_column_index']),(1,2))

class PendingPrintReadingTests(unittest.TestCase):
    def record(self):
        import check_print_case as p
        return p,p.pending_readings()[0]

    def test_pending_reading_cannot_claim_complete(self):
        p,r=self.record();r['full_case_model_image_comparisons']=1
        with self.assertRaisesRegex(ValueError,'cannot claim completion'):p.pending_readings(r)
        with self.assertRaisesRegex(ValueError,'Unresolved image reading'):p.build(r)

    def test_unknown_reading_cannot_be_filled_silently(self):
        p,r=self.record();r['unresolved_readings'][0]['resolved_scan_text']='鹹'
        with self.assertRaisesRegex(ValueError,'unresolved location'):p.pending_readings(r)

    def test_pending_case_cannot_double_count_as_complete(self):
        p,r=self.record()
        rows=[p.build(path=f) for f in sorted((p.ROOT/'research/print_case_reviews').glob('*.json'))]
        summary=p.summarize(rows,[r])
        self.assertEqual((summary['cases'],summary['pending_model_image_readings']),(17,1))
        r['case_id']=rows[0]['case_id']
        with self.assertRaisesRegex(ValueError,'cannot also be completed'):p.summarize(rows,[r])

class NkczPrintWitnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import check_print_case as p
        cls.p=p
        cls.rows={key:p.build(path=p.ROOT/f'research/print_case_reviews/NKCZ_V1_{key}_2026-10-30.json')
                  for key in ['P096','P103','P105','P106']}

    def test_completed_and_pending_cannot_borrow_other_book_pdf(self):
        r=copy.deepcopy(self.rows['P096']);r['pdf_record']='research/scan_reviews/KCLY_target_spots_2026-10-27.json'
        with self.assertRaisesRegex(ValueError,'work mismatch'):self.p.build(r)
        pending=self.p.pending_readings()[0];pending['pdf_record']='research/scan_reviews/NKCZ_target_spots_2026-10-27.json'
        with self.assertRaisesRegex(ValueError,'work mismatch'):self.p.pending_readings(pending)

    def test_nkcz_does_not_inherit_kcly_catalog_support(self):
        for r in self.rows.values():
            self.assertEqual(r['edition_date_verification'],'inherited_metadata_not_reverified_from_images')
            self.assertNotIn('catalog_review_ref',r)
            self.assertNotIn('edition_catalog_verification',r)

    def test_print_difference_and_half_leaf_transition_preserved(self):
        r=self.rows['P105'];d=r['differences'][0]
        self.assertEqual((d['working'],d['scan'],d['source_ref'],d['source_start_char']),('痊','全','XJ-NKCZ-V1-P105',41))
        cut=len(r['scan_columns'][0])
        self.assertEqual((r['alignment'][cut-1]['scan'],r['alignment'][cut]['scan']),('補','血'))
        self.assertEqual(r['column_locations'][1],{'pdf_page':38,'page_half':'left','column_from_right':1})

    def test_following_theory_not_added_to_case_or_work_counts(self):
        r=self.rows['P103']
        self.assertTrue(r['scan_reading'].endswith('至春而愈'))
        self.assertNotIn('此症若',r['scan_reading'])
        self.assertIn('或以為木旺',r['scan_reading'])
        self.assertIn('余以為肝經',r['scan_reading'])
        s=self.p.summarize(list(self.rows.values()))
        self.assertEqual(s['cases_by_work'],{'NKCZ':4})
        self.assertEqual(s['compared_body_characters_by_work'],{'NKCZ':201})

class LyjyPrintBoundaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import check_print_case as p
        cls.rows={key:p.build(path=p.ROOT/f'research/print_case_reviews/LYJY_V1_{key}_2026-11-01.json')
                  for key in ['P096','P097']}

    def test_mechanism_and_refusal_not_changed_by_image_comparison(self):
        r=self.rows['P096']
        self.assertIn('此藥復傷脾胃虛敗也辭不治不越月而歿',r['scan_reading'])
        self.assertFalse(r['differences'])
        self.assertNotIn('catalog_review_ref',r)
        self.assertEqual(r['expert_collated_cases'],0)
        self.assertFalse(r['initial_query_eligible'])

    def test_final_character_on_next_half_leaf_kept_without_next_case(self):
        r=self.rows['P097']
        self.assertTrue(r['scan_reading'].endswith('逍遙散而瘡漸愈'))
        self.assertEqual(r['scan_columns'][-1],'愈')
        self.assertNotIn('性急善怒',r['scan_reading'])
        self.assertEqual(r['column_locations'][-1],{'pdf_page':36,'page_half':'left','column_from_right':1})
        self.assertEqual((r['alignment'][-1]['scan_column_index'],r['alignment'][-1]['scan_column_char_index']),(4,1))

if __name__ == '__main__':
    unittest.main()
