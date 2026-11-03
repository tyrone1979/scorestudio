# How to read and edit the handwritten rules

The writer and the checker share one definition. The file is:

`score_learning/grammar/handwritten_rules.dsl`

Open it and edit a number that is already there, or delete a line under `all:` or `except:`. Save the file. The next time you write or check a score, that edit is used.

In the desktop window, choose Help, then Handwritten rules. The left side is the reading. The right side is the file.

## Which sentences you may write

A line under `all:` or `except:` is a fixed sentence. The program already knows each one, and it matches the words exactly. `the upper voice moves` is one of those sentences. It is already written under R01. You keep it, or you delete the whole line.

You do not invent a new sentence, and you do not reword one. `the top voice moves` is a different sentence. The program does not know it, and the next check stops with `has an unknown condition`.

`name`, `means`, `where`, and `report` are for reading. Changing those words does not change the test.

The lines you may keep or delete are these.

R01, under `all:`

```
the upper voice moves
the lower voice moves
the interval class stays the same
the interval class is a perfect fifth or octave
```

R02, under `all:`

```
the arrival is a perfect fifth or octave
both voices move
both voices move the same way
the soprano leap exceeds the limit
```

R02, under `except:`

```
same chord, voices exchange
bass moves by an octave
```

R03, under `all:`

```
a voice overlaps
```

R03, under `except:`

```
voices part from a unison
it does not pass the note immediately before
```

R04, under `all:`

```
the voices cross
adjacent voices stand too far apart
```

R05, under `all:`

```
the pitch is outside the voice range
```

R06, under `all:`

```
this voice has the leading tone
it does not rise by the required semitones
```

R06, under `except:`

```
a secondary leading tone must rise too
```

R07, under `all:`

```
this voice has the seventh
it neither falls by step nor holds a chord tone
```

R07, under `except:`

```
it falls by step on the half beat
the seventh rises with the bass
the seventh is only a passing tone
```

R08, under `all:`

```
the melodic interval is forbidden
```

R08, under `except:`

```
a descending tritone steps back
```

R09, under `all:`

```
the leading tone is doubled
a required chord tone is missing
```

R10, under `all:`

```
an unattested chord pair is forbidden
```

R11, under `all:`

```
the phrase ending uses the cadence formula
```

`shared`, under `all:`

```
a beat suspension is judged by its resolution
```

A line with a colon is a name the program already knows, followed by a value. Change the value. Do not add a new name. The names are:

```
perfect fifth
perfect octave
soprano leap exceeds
rises by semitones
voices
resolves down by
forbidden semitones
wider than
leading tone at most
must include
a seventh chord also needs
writer forbids a doubled seventh
soprano to alto at most
alto to tenor at most
tenor to bass at most
unison allowed
writer forbids unison
bounds included
beats locked at the end
soprano degrees locked
step no wider than
```

`voices` takes `soprano`, `alto`, `tenor`, `bass`. `must include` and `a seventh chord also needs` take `root`, `third`, `fifth`, `seventh`. A yes-or-no value is the word `yes` or the word `no`.

## How a rule is laid out

Each rule starts with `rule` and an id. The ids run from R01 to R11. One more rule, `shared`, covers a suspension on the beat.

A rule usually has these lines:

- `name`: what the rule is called.
- `means`: the definition in ordinary musical language.
- `where`: which notes are checked.
- A line with a number: a limit you can change, for example `soprano leap exceeds: 2`.
- `all`: every sentence below must be true before a fault is counted. If the rule says `match: any`, one true sentence is enough.
- `except`: cases that are allowed through. Delete one of those lines, and that case is no longer allowed.
- `report`: the words used in the check result.

A line that starts with `#` is a comment. The program skips it.

R10 and R11 are used only while writing. A chord pair that never occurred in the scores is not used, and the last beats of a phrase stay locked to the cadence formula that was drawn. The checker does not report these two on a finished score.

## What each rule covers

| Id | Name | What you usually change |
| --- | --- | --- |
| R01 | Parallel perfect fifths or octaves | the semitone numbers after `perfect fifth` and `perfect octave` |
| R02 | Hidden fifth or octave in the outer voices | `soprano leap exceeds`. A larger number waits for a larger leap |
| R03 | Voice overlap | the two lines under `except`. Delete one and that motion is no longer allowed |
| R04 | No crossing, and a limit on the gap | the three `at most` numbers. Tenor to bass may be wider than the pairs above |
| R05 | Range | the limits are not in this file. They are the learned range for each voice. This rule only says that a note outside the range counts, and that the limits themselves are inside the range |
| R06 | A leading tone must rise | `rises by semitones`, and which voices are checked |
| R07 | A seventh must fall by step | the semitone numbers after `resolves down by`. The default is -1 and -2 |
| R08 | A forbidden melodic interval | `forbidden semitones` and `wider than` |
| R09 | A complete chord, and no doubled leading tone | `leading tone at most`, `must include`, and `a seventh chord also needs` |
| R10 | Do not use a chord pair that never occurred | delete the sentence under `all`, and writing may use a pair that never occurred |
| R11 | The end of a phrase is locked to a cadence formula | `beats locked at the end` and `soprano degrees locked` |

`shared`: a suspension or appoggiatura on the beat, if it steps to a chord tone within the beat, is judged by that resolution for parallels, hidden fifths and octaves, and chord completeness. `step no wider than` defaults to 2 semitones.

## Change one number

A hidden fifth now requires the soprano leap to be larger than 2 semitones. To catch only a larger leap, change this line under R02:

```
soprano leap exceeds: 4
```

Save, then check again. A move whose soprano leap is 3 or 4 semitones, with every other condition met, is no longer reported as R02.

Do not change a voice range in this file. Open the style's rule file and change the lowest or highest note. Lower the soprano's highest note, check again, and a note above the new limit is reported as R05.

## Delete one exception

R08 allows a descending tritone that immediately steps back. To count that motion as well, delete this line under R08:

```
a descending tritone steps back
```

Leave the heading `except:`. A heading with no sentences under it means nothing is allowed through.

## These are not the learned rules

A learned rule records one way of writing and how often it occurred. It lives in the style's rule file. A sentence in this file is a yes-or-no test written by a person. If a step fails the test, the writer will not take it, and the checker reports the rule and the beat.

The lowest and highest notes used by R05 are learned numbers attached to this handwritten test. Changing those numbers changes the range check. It does not change the list of learned chord pairs.
