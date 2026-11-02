# Rule and Grammar Inventory

This page is the GitHub entry point for the musical rules used by ComposerChat / Score Studio. The project has several kinds of rules, and they should not be treated as one interchangeable list:

- human-readable theory guidance;
- executable predicates that accept or reject notes;
- corpus-learned productions and probabilities;
- editable thresholds stored with a style grammar;
- evaluation code and result records.

Relative links below work in a GitHub checkout.

## 1. Human-readable rule library

The catalog is [`skills/composition/rules/catalog.yaml`](skills/composition/rules/catalog.yaml). It maps each documented rule to its explanation, implementation, tags, and sources.

The principal documents are:

- counterpoint: [`first_species.md`](skills/composition/rules/counterpoint/first_species.md);
- voice leading: [`satb_basics.md`](skills/composition/rules/voice_leading/satb_basics.md) and [`parallels.md`](skills/composition/rules/voice_leading/parallels.md);
- harmony: [`progressions.md`](skills/composition/rules/harmony/progressions.md), [`phrase_model.md`](skills/composition/rules/harmony/phrase_model.md), and [`cadences.md`](skills/composition/rules/harmony/cadences.md);
- form: [`phrase_period.md`](skills/composition/rules/form/phrase_period.md);
- melody: [`contour.md`](skills/composition/rules/melody/contour.md) and [`nonharmonic_tones.md`](skills/composition/rules/melody/nonharmonic_tones.md);
- rhythm: [`meter_basics.md`](skills/composition/rules/rhythm/meter_basics.md) and [`accompaniment.md`](skills/composition/rules/rhythm/accompaniment.md).

These files explain musical conventions. They are not, by themselves, the executable source of truth for the SATB checker.

## 2. Executable SATB hard rules

The shared implementation used by both chorale generation and completed-score diagnosis is [`score_learning/grammar/check.py`](score_learning/grammar/check.py). The rule IDs are:

- **R01**: parallel perfect fifths, octaves, and unisons between moving voices;
- **R02**: direct or hidden perfect fifths and octaves in the outer voices when the soprano leaps;
- **R03**: voice crossing and voice overlap;
- **R04**: excessive spacing between adjacent voices (reported together with R03 where appropriate);
- **R05**: notes outside the stored soprano, alto, tenor, or bass range;
- **R06**: unresolved diatonic or secondary leading tones in the outer voices;
- **R07**: unresolved chordal sevenths, subject to the encoded licenses;
- **R08**: forbidden melodic intervals, including tritones, sevenths, and leaps larger than an octave, subject to the encoded recovery rule;
- **R09**: duplicated leading tones and incomplete chords.

The same file also contains:

- `REFINEMENTS`, the explicit textbook licenses and later predicate refinements;
- `ROOT_CAUSE_SUPPORT`, the context-size ordering used to rank simultaneous reports;
- helper functions for structural non-chord tones, secondary leading tones, seventh resolution, and overlap.

The chorale generator that calls these predicates is [`score_learning/grammar/compose.py`](score_learning/grammar/compose.py). The checker entry point is [`score_learning/grammar/check.py`](score_learning/grammar/check.py). The lead-sheet equivalents are [`score_learning/leadsheet/compose.py`](score_learning/leadsheet/compose.py) and [`score_learning/leadsheet/check.py`](score_learning/leadsheet/check.py).

## 3. Learned style grammars

Each learned style pack keeps machine-readable rules in `grammar.yaml` and a prose rendering in `grammar.md`. The current grammar-bearing packs are:

- [`baroque/bach-keyboard`](skills/composition/genre/packs/baroque/bach-keyboard/);
- [`classical/piano-sonata`](skills/composition/genre/packs/classical/piano-sonata/);
- [`classical/string-quartet`](skills/composition/genre/packs/classical/string-quartet/);
- [`classical/symphony`](skills/composition/genre/packs/classical/symphony/);
- [`folk/british-folk-tune`](skills/composition/genre/packs/folk/british-folk-tune/);
- [`jazz/swing-standard`](skills/composition/genre/packs/jazz/swing-standard/);
- [`pop/pop-standard`](skills/composition/genre/packs/pop/pop-standard/);
- [`romantic/chopin-piano`](skills/composition/genre/packs/romantic/chopin-piano/);
- [`sacred/chorale`](skills/composition/genre/packs/sacred/chorale/);
- [`vocal/madrigal`](skills/composition/genre/packs/vocal/madrigal/).

A pack can also contain `style_contract.yaml`, `meta.yaml`, `theme_memory.yaml`, empirical summaries, and a `GENRE.md` description. These are style-local assets, not global hard rules.

Rule IDs inside learned packs are local namespaces. For example, a folk-pack `R01` is not the chorale hard-rule `R01`. When citing a learned rule outside its file, use a qualified name such as `folk/british-folk-tune:R01`.

## 4. Editable thresholds and learned parameters

Thresholds that belong to a musical rule are stored with the relevant grammar rather than duplicated in user-interface code. The chorale voice ranges, interpolation settings, learned harmony continuations, cadence formulae, form plans, contour statistics, and rhythm patterns are in [`skills/composition/genre/packs/sacred/chorale/grammar.yaml`](skills/composition/genre/packs/sacred/chorale/grammar.yaml). Lead-sheet pack thresholds are in the corresponding pack's `grammar.yaml` under its rule parameter blocks.

The induction and analysis paths are:

- chorale analysis and learning: [`score_learning/grammar/analyze.py`](score_learning/grammar/analyze.py), [`learn.py`](score_learning/grammar/learn.py), and [`theory.py`](score_learning/grammar/theory.py);
- lead-sheet analysis and learning: [`score_learning/leadsheet/analyze.py`](score_learning/leadsheet/analyze.py) and [`learn.py`](score_learning/leadsheet/learn.py);
- cross-section form relations: [`score_learning/relation/`](score_learning/relation/);
- thematic memory: [`score_learning/theme_memory.py`](score_learning/theme_memory.py).

## 5. Other deterministic composition rules

The broader application contains rules outside the paper's shared SATB checker:

- deterministic composition scripts and cadence/melody/accompaniment logic: [`compose_kernel.py`](compose_kernel.py);
- first-species counterpoint: [`music_score/two_part_species.py`](music_score/two_part_species.py);
- score-editor and SATB helpers: [`music_score/editor_core.py`](music_score/editor_core.py) and [`music_score/satb_piano.py`](music_score/satb_piano.py);
- chord advice: [`chord_advisor.py`](chord_advisor.py);
- rule discovery and presentation: [`rule_library.py`](rule_library.py).

These modules may implement additional composition conventions. They are not automatically part of R01--R09 unless they call the shared checker explicitly.

## 6. Evaluation and evidence

The main reproducibility and evaluation paths are:

- planted faults: [`score_learning/grammar/fault_inject.py`](score_learning/grammar/fault_inject.py);
- range and rule ablations: [`range_ablation.py`](score_learning/grammar/range_ablation.py) and [`rule_ablation.py`](score_learning/grammar/rule_ablation.py);
- held-out evaluation: [`score_learning/grammar/evaluate.py`](score_learning/grammar/evaluate.py);
- expert-pack construction and scoring: [`expert_pack.py`](score_learning/grammar/expert_pack.py) and [`expert_score.py`](score_learning/grammar/expert_score.py);
- chord-label agreement: [`chord_agreement.py`](score_learning/grammar/chord_agreement.py);
- broader experiment orchestration: [`score_learning/experiments.py`](score_learning/experiments.py);
- saved experiment records: [`runs/experiments/`](runs/experiments/).

Project-wide reproduction notes and locked dependencies are in [`REPRODUCIBILITY.md`](REPRODUCIBILITY.md) and [`requirements-lock.txt`](requirements-lock.txt).

## 7. Paper and release

The anonymous *Computer Music Journal* manuscript is in [`papers/cmj/main.tex`](papers/cmj/main.tex). The public GPL-3.0 software archive cited by the editorial material is [soundstudio v1.0.0](https://github.com/tyrone1979/soundstudio/releases/tag/v1.0.0).

When a rule changes, update the executable implementation first, then its human-readable description, relevant grammar parameters, tests or experiment records, and this inventory if a path or rule meaning changed.
