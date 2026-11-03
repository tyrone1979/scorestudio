# Handwritten rules. A musician can edit this file.
# Change a number on a line that is already here, or delete a line under "all" or "except".
# Do not reword a line under "all" or "except". The program knows each sentence by its exact words.
# The full list of those sentences is in docs/handwritten_rules.md.
# Each rule starts with "rule Rxx". A line starting with # is a comment.

rule R01
name: Parallel perfect fifths or octaves
means: Any two voices. If both move, and the kind of interval before the move is the same as the kind after it, and that interval is a perfect fifth or a perfect octave, count one fault. Unisons, compound intervals larger than an octave, and contrary motion all count. If one voice stays still, the motion is oblique and does not count.
where: every pair of voices, at two successive moments
perfect fifth: 7
perfect octave: 0
all:
the upper voice moves
the lower voice moves
the interval class stays the same
the interval class is a perfect fifth or octave
except:
report: {upper} and {lower} move in parallel perfect fifths or octaves

rule R02
name: Hidden fifth or octave in the outer voices
means: Look only at the soprano and the bass. If they move in the same direction, arrive on a perfect fifth or octave, and the soprano leap is larger than the number of semitones below, count one fault. A soprano step, no larger than that number, is allowed. So is an exchange inside the same chord, or a bass move of an octave.
where: soprano and bass, at two successive moments
perfect fifth: 7
perfect octave: 0
soprano leap exceeds: 2
all:
the arrival is a perfect fifth or octave
both voices move
both voices move the same way
the soprano leap exceeds the limit
except:
same chord, voices exchange
bass moves by an octave
report: hidden fifth or octave between the outer voices

rule R03
name: Voice overlap
means: Overlap means the lower voice's new note is higher than the upper voice's previous note, or the upper voice's new note is lower than the lower voice's previous note. Crossing, where the voices are upside down at the same moment, is not this rule. Spacing handles that. Parting from the same note may be allowed. So may a move that passes only the note on the beat and not the note that came immediately before.
where: two adjacent voices, from the previous beat to this beat
all:
a voice overlaps
except:
voices part from a unison
it does not pass the note immediately before
report: voice overlap

rule R06
name: A leading tone must rise
means: When the tonic chord arrives, a leading tone in the soprano or the bass must rise by the number of semitones below. The inner voices are not checked. A leading tone in a secondary dominant must rise in the same way, unless that exception line is deleted.
where: soprano and bass, a leading tone into the tonic, or a secondary leading tone into its temporary tonic
rises by semitones: 1
voices: soprano, bass
all:
this voice has the leading tone
it does not rise by the required semitones
except:
a secondary leading tone must rise too
report: {voice} leading tone does not rise

rule R07
name: A seventh must fall by step
means: In a chord that has a seventh, that seventh should fall by a minor or major second on the next beat. The semitone sizes are listed below. Staying put still counts as a resolution when the next chord contains the same pitch. A fall that happens only on the half beat, a seventh that rises with the bass, or a seventh that is only a passing tone may be allowed.
where: whichever of the four voices holds the seventh of the previous chord
resolves down by: -1, -2
all:
this voice has the seventh
it neither falls by step nor holds a chord tone
except:
it falls by step on the half beat
the seventh rises with the bass
the seventh is only a passing tone
report: {voice} seventh does not fall by step

rule R08
name: A forbidden melodic interval
means: In one voice, two successive notes count as a fault when their distance in semitones is listed under forbidden semitones, or is greater than "wider than". The forbidden sizes now are a tritone (6), a minor seventh (10), and a major seventh (11). Wider than 12 means a leap past an octave. A descending tritone that immediately steps back the other way may be allowed.
where: each voice, two successive notes
forbidden semitones: 6, 10, 11
wider than: 12
all:
the melodic interval is forbidden
except:
a descending tritone steps back
report: {voice} forbidden melodic interval {interval}

rule R09
name: A chord should be complete, and its leading tone not doubled
means: A leading tone may appear at most the number of times written below. A triad must be heard with its root and its third. A seventh chord must also be heard with its seventh. Missing any of these counts as one fault. Doubling the third or the fifth is not forbidden here.
where: the four notes on each beat
leading tone at most: 1
must include: root, third
a seventh chord also needs: seventh
writer forbids a doubled seventh: yes
match: any
all:
the leading tone is doubled
a required chord tone is missing
except:
report: leading tone doubled, or the chord is incomplete

rule R04
name: Voices do not cross, and adjacent voices stay within a limit
means: At the same moment the soprano is not below the alto, the alto is not below the tenor, and the tenor is not below the bass. A unison is allowed. The soprano-alto gap and the alto-tenor gap may not exceed the semitone numbers below. The tenor-bass gap may be wider, and its limit is written separately. The checker reports this together with voice crossing. When the writer chooses inner voices, adjacent voices must also sit on different notes, one above the other.
where: the four notes on each beat
report id: R03/R04
soprano to alto at most: 12
alto to tenor at most: 12
tenor to bass at most: 19
unison allowed: yes
writer forbids unison: yes
match: any
all:
the voices cross
adjacent voices stand too far apart
except:
report: voices cross or stand too far apart

rule R05
name: A voice stays inside its own range
means: Soprano, alto, tenor, and bass each have a lowest and a highest note. A note outside that span counts as one fault. The lowest and highest notes themselves are inside the range. Those four limits are not written here. They are learned from public scores and stored in that style's rule file, under the voice ranges. Change a lowest or highest note there, and this test follows the new limit.
where: each voice's pitch, compared with the range learned for that voice
bounds included: yes
all:
the pitch is outside the voice range
except:
report: {voice} is outside its range

rule R10
name: Do not use a chord pair that never occurred
means: While writing, two chords in succession must be a pair that occurred in the public scores. A pair that never occurred is not a candidate. This rule constrains writing only. The checker does not report it on a finished score.
where: chord moves while writing
all:
an unattested chord pair is forbidden
except:
report: unattested chord pair

rule R11
name: The end of a phrase is locked to a cadence formula
means: The last few beats of each phrase must use the cadence formula that was drawn, and the soprano degrees are locked to that formula too. Earlier beats may be chosen freely. Only the writer uses this rule. The checker does not report it.
where: the end of each phrase while writing
beats locked at the end: 3
soprano degrees locked: 2
all:
the phrase ending uses the cadence formula
except:
report: the phrase ending is not locked to the cadence formula

rule shared
name: Judge a suspension on the beat by the note it resolves to
means: A suspension or appoggiatura on the beat, if it steps to a chord tone within the beat, is judged by that resolution for parallels, hidden fifths and octaves, and chord completeness. It is not judged by the suspended note itself. When the textbook exceptions are turned off, this rule does not apply.
where: R01, R02, and R09 when they look at a beat
step no wider than: 2
all:
a beat suspension is judged by its resolution
except:
report: judged by the resolution
