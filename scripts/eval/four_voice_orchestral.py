#!/usr/bin/env python3
"""Compare newly generated four-part strings with Bach BWV 1068/2 Air.

Reference: Mutopia-2008/10/28-242, CC BY-SA 3.0, Bach-Gesellschaft,
maintainer Jeff Covey. Uses its symbolic MIDI; not a downloaded recording.
"""
from __future__ import annotations
import hashlib
import itertools
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import numpy as np
from scripts.eval.compare_bwv318 import extract, longest

OUT = ROOT/'runs/orchestral_four_voice_v2'
SOURCE = ROOT/'runs/orchestral_four_voice/source'
NAMES = ['Violin I', 'Violin II', 'Viola', 'Continuo bass']
VELOCITIES = [92, 70, 66, 74]
# Written LilyPond measures: [1..5], first ending 6, second ending 7,
# then 8..19 with a repeat. Intervals in written quarter-note coordinates.
PLAY_ORDER = [(0.,24.), (0.,20.), (24.,28.), (28.,76.), (28.,76.)]
COMMAND = '/key D /tempo 60 /compose-grammar strings allegro 32 downbeat seed=orchestral-four-voice-v2 memory=on'


def read_midi_tracks(path):
    import mido
    mf = mido.MidiFile(str(path))
    tracks = []
    for track in mf.tracks:
        tick, active, notes = 0, {}, []
        for msg in track:
            tick += msg.time
            if msg.type == 'note_on' and msg.velocity:
                key = (msg.channel, msg.note)
                active.setdefault(key, []).append(tick)
            elif msg.type == 'note_off' or (msg.type == 'note_on' and not msg.velocity):
                key = (msg.channel, msg.note)
                if active.get(key):
                    on = active[key].pop(0)
                    if tick > on:
                        notes.append({'midi': msg.note, 'on': on/mf.ticks_per_beat,
                                      'dur': (tick-on)/mf.ticks_per_beat})
        if active and any(active.values()):
            raise ValueError('Unterminated MIDI notes')
        if notes:
            tracks.append(sorted(notes, key=lambda e:(e['on'], e['midi'])))
    return tracks


def finish_events(es):
    from music21.pitch import Pitch
    es = sorted(es, key=lambda e:(e['on'],e['midi']))
    for i,e in enumerate(es):
        e['name'] = Pitch(midi=e['midi']).nameWithOctave
        e['measure'] = int(e['on']//4)+1
        e['ioi'] = es[i+1]['on']-e['on'] if i+1 < len(es) else e['dur']
    return es


def unfold_reference(tracks):
    result = []
    for es in tracks:
        expanded, cursor = [], 0.
        for start,end in PLAY_ORDER:
            for e in es:
                a,b = max(e['on'],start), min(e['on']+e['dur'],end)
                if b > a + 1e-9:
                    expanded.append({'midi':e['midi'],'on':cursor+a-start,'dur':b-a,
                                     'source_written_on':e['on']})
            cursor += end-start
        result.append(finish_events(expanded))
    return result


def assert_monophonic(es):
    for a,b in zip(es,es[1:]):
        if a['on']+a['dur'] > b['on']+1e-6:
            raise ValueError('Overlapping notes in a supposed single voice')


def stats(voices, total):
    from collections import Counter
    onset_sets=[{round(e['on'],7) for e in es} for es in voices]
    union=set.union(*onset_sets)
    pair=[]
    for i,j in itertools.combinations(range(4),2):
        pair.append({'voices':[NAMES[i],NAMES[j]],
                     'onset_jaccard':len(onset_sets[i]&onset_sets[j])/max(len(onset_sets[i]|onset_sets[j]),1)})
    return {'duration_ql':total, 'voices':[
        {'voice':NAMES[i], 'attacks':len(es),'attacks_per_quarter':len(es)/total,
         'median_duration_ql':float(np.median([e['dur'] for e in es])),
         'range_midi':[min(e['midi']for e in es),max(e['midi']for e in es)],
         'repeated_pitch_fraction':sum(a['midi']==b['midi']for a,b in zip(es,es[1:]))/max(len(es)-1,1),
         'short_note_fraction':sum(e['dur']<=.5+1e-9 for e in es)/len(es)}for i,es in enumerate(voices)],
        'onset_pair_jaccard':pair,
        'four_way_attack_fraction':len(set.intersection(*onset_sets))/max(len(union),1),
        'mean_voices_per_attack':sum(len(s)for s in onset_sets)/max(len(union),1)}


def four_voice_match(a,b,total_a,total_b,step=.25,transpose=False):
    def sample(vs,total):
        return [tuple(next((e['midi']for e in es if e['on']-1e-7<=t*step<e['on']+e['dur']-1e-7),None)
                      for es in vs)for t in range(int(total/step))]
    x,y=sample(a,total_a),sample(b,total_b)
    best={'frames':0,'duration_ql':0,'step_ql':step}
    # DP along diagonals; a single transposition must persist throughout a run.
    prev={}
    for i,frame in enumerate(x):
        row={}
        for j,other in enumerate(y):
            if any(v is None for v in frame+other):continue
            ds=tuple(v-w for v,w in zip(frame,other))
            if len(set(ds))!=1 or (not transpose and ds[0]!=0):continue
            shift=ds[0]
            length=prev.get((j-1,shift),0)+1
            row[(j,shift)]=length
            if length>best['frames']:
                best={'frames':length,'duration_ql':length*step,'step_ql':step,
                      'generated_on':(i-length+1)*step,'bach_playback_on':(j-length+1)*step,
                      'transpose_semitones':shift}
        prev=row
    return best


def export_audio(voices,total,path):
    import pretty_midi
    pm=pretty_midi.PrettyMIDI(initial_tempo=60)
    for name,velocity,es in zip(NAMES,VELOCITIES,voices):
        inst=pretty_midi.Instrument(program=48,name=name+' (String Ensemble)')
        for e in es:
            inst.notes.append(pretty_midi.Note(velocity=velocity,pitch=e['midi'],start=e['on'],end=e['on']+e['dur']))
        pm.instruments.append(inst)
    pm.write(str(path))


def main():
    from music21 import converter
    from llm_compose import ComposeSession,compose_from_text,validate_score_spec
    from render_enhance import preset,render_raw,write_wav
    import wave
    OUT.mkdir(exist_ok=True)
    score,spec,trace=compose_from_text(ComposeSession(),COMMAND)
    assert len(score.parts)==4 and not validate_score_spec(spec)
    assert all(not list(p.recurse().getElementsByClass('Chord'))for p in score.parts)
    score.write('musicxml',fp=str(OUT/'generated_strings.musicxml'))
    (OUT/'generated_spec.json').write_text(json.dumps(spec,ensure_ascii=False,indent=2))
    (OUT/'generated_trace.txt').write_text(COMMAND+'\n'+trace)
    generated=[finish_events(extract(p))for p in score.parts]
    raw=read_midi_tracks(SOURCE/'bach-air-score.mid')
    assert len(raw)==4
    # Validate the source order against LilyPond's four opening pitches.
    assert [es[0]['midi']for es in raw]==[78,74,69,50]
    assert abs(max(e['on']+e['dur']for es in raw for e in es)-76)<1e-7
    bach=unfold_reference(raw)
    for es in generated+bach:assert_monophonic(es)
    total_g,total_b=128.,144.
    assert abs(max(e['on']+e['dur']for es in generated for e in es)-total_g)<1e-7
    assert abs(max(e['on']+e['dur']for es in bach for e in es)-total_b)<1e-7
    pairs=[]
    for i,a in enumerate(generated):
        for j,b in enumerate(bach):
            pairs.append({'generated_voice':NAMES[i],'bach_voice':NAMES[j],'corresponding':i==j,
                          'strict':longest(a,b),
                          'transposed_rhythmic':longest(a,b,transpose=True),
                          'pitch_only':longest(a,b,transpose=True,rhythm=False),
                          'raw_transposed':longest(a,b,transpose=True,require_variety=False)})
    analysis={'generated_command':COMMAND,'reference':'J. S. Bach BWV 1068/2 Air',
              'source_url':'https://www.mutopiaproject.org/cgibin/piece-info.cgi?id=242',
              'license':'CC BY-SA 3.0, Mutopia-2008/10/28-242, Jeff Covey, Bach-Gesellschaft',
              'reference_playback':{'written_bars':19,'played_bars':36,'segments_ql':PLAY_ORDER,
                                    'repeat_policy':'first ending then repeat with second ending; second section repeated'},
              'generated':stats(generated,total_g),'bach':stats(bach,total_b),
              'voice_pair_similarity':pairs,
              'four_voice_exact':four_voice_match(generated,bach,total_g,total_b),
              'four_voice_transposed':four_voice_match(generated,bach,total_g,total_b,transpose=True),
              'generated_events':generated,'bach_events':bach,
              'limitations':['Generator uses classical string-quartet grammar, not a learned Bach orchestral Air style.',
                             'Reference is from Mutopia symbolic MIDI; its grace-note timing is retained.',
                             'Matching permits exact duration/IOI and fixed pitch shift, not ornament insertion/deletion.',
                             'Bass line only: no added keyboard realization of continuo or double-bass octave doubling.',
                             'Both use the same per-role dynamics (92/70/66/74), String Ensemble 1, 60 BPM, reverb and common gain.',
                             'Different lengths, 32 vs 36 played bars; density is normalized by quarter notes.',
                             'Onset similarity is descriptive, not an aesthetic or plagiarism score.']}
    (OUT/'comparison.json').write_text(json.dumps(analysis,ensure_ascii=False,indent=2))
    rendered=[]
    settings=preset(piano=False,soundfont='generaluser',reverb=.12,velocity='natural')
    for name,voices,total in [('generated_strings',generated,total_g),('bach_bwv1068_air',bach,total_b)]:
        midi=OUT/(name+'.mid');export_audio(voices,total,midi)
        audio=render_raw(str(midi),settings)
        if audio is None:raise RuntimeError('SoundFont rendering failed')
        rendered.append((name,audio[0],audio[1]))
    maxpeak=max(float(np.abs(a).max())for _n,a,_sr in rendered)
    assert maxpeak>0
    gain=.9/maxpeak
    audio_manifest=[]
    for name,a,sr in rendered:
        path=OUT/(name+'.wav');write_wav(str(path),a*gain,sr)
        with wave.open(str(path))as w:
            pcm=np.frombuffer(w.readframes(w.getnframes()),dtype='<i2').astype(float)/32768
            qa={'file':str(path.relative_to(ROOT)),'duration_seconds':w.getnframes()/sr,'sample_rate':sr,
                'peak':float(np.abs(pcm).max()),'rms':float(np.sqrt(np.mean(pcm**2))),
                'near_full_scale_samples':int(np.sum(np.abs(pcm)>=.999)),
                'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
            assert qa['rms']>.0001 and qa['near_full_scale_samples']==0
            audio_manifest.append(qa)
    manifest={'command':COMMAND,'source_attribution':analysis['license'],'source_url':analysis['source_url'],
              'derivative_changes':'repeat unfolding, 60 BPM, String Ensemble 1, per-role velocities 92/70/66/74, reverb and common gain; no pitch edits',
              'bach_render_license':'https://creativecommons.org/licenses/by-sa/3.0/',
              'render_preset':settings.to_dict(),'common_gain':gain,'audio':audio_manifest,
              'source_sha256':hashlib.sha256((SOURCE/'bach-air-score.mid').read_bytes()).hexdigest()}
    (OUT/'listening_manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2))
    print(json.dumps({'generated':analysis['generated'],'bach':analysis['bach'],
                      'corresponding_similarity':[{k:(v['longest_notes']if isinstance(v,dict)and 'longest_notes'in v else v)
                          for k,v in x.items()}for x in pairs if x['corresponding']],
                      'four_voice_exact':analysis['four_voice_exact'],'audio':audio_manifest},ensure_ascii=False,indent=2))


if __name__=='__main__':main()
