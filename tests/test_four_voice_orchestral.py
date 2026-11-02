import pytest
from scripts.eval.four_voice_orchestral import (
    unfold_reference, finish_events, stats, four_voice_match, assert_monophonic,
    read_midi_tracks, export_audio,
)
from score_learning.leadsheet.compose import accompaniment_quartet, apply_learned_motif_rhythm


def test_reference_repeat_and_endings():
    track=[{'midi':60+i%12,'on':float(i),'dur':1.}for i in range(76)]
    result=unfold_reference([track])[0]
    order=list(range(24))+list(range(20))+list(range(24,28))+list(range(28,76))*2
    assert len(result)==144
    assert [e['source_written_on']for e in result]==order
    assert [e['on']for e in result]==list(map(float,range(144)))
    assert_monophonic(result)


def test_onset_sync_and_pitch_repetition():
    es=finish_events([{'midi':60,'on':float(i),'dur':1.}for i in range(4)])
    result=stats([es]*4,4)
    assert result['mean_voices_per_attack']==4
    assert result['four_way_attack_fraction']==1
    assert all(p['onset_jaccard']==1 for p in result['onset_pair_jaccard'])
    assert all(v['repeated_pitch_fraction']==1 for v in result['voices'])


def test_four_voice_shift_must_be_constant_across_parts():
    a=[[{'midi':60+i,'on':0.,'dur':2.}]for i in range(4)]
    b=[[{'midi':65+i,'on':0.,'dur':2.}]for i in range(4)]
    assert four_voice_match(a,b,2,2)['duration_ql']==0
    assert four_voice_match(a,b,2,2,transpose=True)['duration_ql']==2
    b[2][0]['midi']+=1
    assert four_voice_match(a,b,2,2,transpose=True)['duration_ql']==0


def test_monophony_rejects_overlaps():
    with pytest.raises(ValueError):
        assert_monophonic([{'on':0.,'dur':2.},{'on':1.,'dur':1.}])


def test_midi_roundtrip_four_voices(tmp_path):
    import pretty_midi
    a=[[{'midi':60+i,'on':0.,'dur':2.}]for i in range(4)]
    path=tmp_path/'ensemble.mid'
    export_audio(a,2,path)
    pm=pretty_midi.PrettyMIDI(str(path))
    assert len(pm.instruments)==4 and all(i.program==48 for i in pm.instruments)
    read=read_midi_tracks(path)
    assert len(read)==4
    assert [es[0]['midi']for es in read]==list(range(60,64))
    assert all(es[0]['dur']==2 for es in read)


def test_quartet_inner_voices_have_distinct_four_four_roles():
    class G:
        bar_ql=4.;beat_ql=1.;meter='4/4'
    class Mel:
        pass
    slots=[{'t':0.,'tok':'0:M'}]
    vn2,va,vc=accompaniment_quartet(G(),slots,[48],2,Mel(),8.,[[55,64]])
    vn2_on={b*4+o for b,bar in enumerate(vn2) for o,_d,p in bar if p}
    va_on={b*4+o for b,bar in enumerate(va) for o,_d,p in bar if p}
    # 第一小节：Vn II 后半拍应答，Viola 在和声起点保持；末小节三声部终止长音。
    assert {0.5,1.5,2.5,3.5}.issubset(vn2_on)
    assert 0. in va_on and not ({0.5,1.5,2.5,3.5}&va_on)
    assert vn2_on != va_on


def test_learned_motif_plan_controls_location_span_and_density():
    import random
    class G:
        meter='4/4';bar_ql=4.
        theme_policy={'enabled':True,'intra_phrase':{
            'relation_counts':{'2:1:5':4},
            'source_profile_counts':{'2:1:5|3,4':4}}}
        s={'rhythm':{'templates':{'open':{'items':[
            {'pattern':'0n 1n 2n','id':'r1','p':1.},
            {'pattern':'0n 1.5n 2n 3n','id':'r2','p':1.},
            {'pattern':'0n','id':'too-static','p':10.},
        ]}}}}
    bars=[{'pattern':'0n','rule':'old','copy':None}for _ in range(8)]
    relation=apply_learned_motif_rhythm(G(),random.Random(4),bars)
    assert relation=={'span_bars':2,'source_bar':1,'target_bar':5,
                      'source_note_counts':[3,4],'harmony_shift':0}
    assert bars[5]['pattern']==bars[1]['pattern']
    assert bars[6]['pattern']==bars[2]['pattern']
    assert bars[5]['motif_source']==1 and bars[6]['motif_source']==2
