# Lumière — craft direction (design guideline + scoped refinement proposal)

Status: **guideline; R1–R6 as modified by the owner's decisions of 2026-10-10 are now IMPLEMENTED in the sandbox** (see §7). Sections 1–5 keep the original proposal text for the record; the mock `prototypes/craft_mock.py` is superseded by the real renders from `prototypes/render_screens.py`. Lumière is the approved design direction, not an approved name (no rename, no trademark check done). Part of the sandbox; nothing committed or installed.

## 1. Philosophy: a small independent cinematheque, made by a person
The interface should read as *edited*, not *generated*: someone decided what is large, what is quiet, what is left empty and why. Three tests for any visual decision:
1. **Does it help someone find, start or resume a film?** If not, it is decoration; remove it.
2. **Could a template have produced it?** Uniform rounded cards, centred-everything, equal gaps, icon-in-a-circle: these are template tells. Prefer a decision with a reason.
3. **Does it survive a keyboard, a small window, reduced motion and a light theme?** If not, it is not finished.

### Principles
- **Hierarchy by type, not by boxes.** Serif carries identity (display line, section heads, film titles); sans carries function (controls, status, settings). Few sizes, used consistently: display 30–34, section 20, title 17–19, body 13–14, label/caption 11–12. Numbers in timecodes and sizes use tabular figures where the font supports them.
- **Asymmetry with a reason.** Align the content to the logo edge and give the free space to one side; make the most recent film larger because it is what you most likely want. No random offsets, no rotation, no "imperfection".
- **Negative space is a material.** More air *between* sections than inside them; fewer containers; one hairline where a divider is needed, no box where spacing says it.
- **Restrained borders, printed-card corners.** Radii 4 px (was 8/6); borders only where they carry meaning (focus, hover, input fields, drop target). Pills stay for chips only.
- **Small meaningful details.** The film-gate frame (crop marks) marks *the one place you start a film* and nothing else; the progress hairline sits on the card's bottom edge like a timecode strip; tooltips tell the truth ("Last opened", not "watched").
- **Motion is a consequence, not a feature.** Existing rules stay: 120/200/320 ms, interruptible, reduced-motion aware, nothing delays an action, no playback-control fade.
- **A human voice, plain facts.** Warm but exact copy ("Resume at 1:43:20", "Not started"); technical messages stay literal.

### Deliberately NOT done (and why)
Artificial grain or paper noise, faux-handwriting, random offsets, hand-drawn strokes, parallax, glow, blur, gradients, decorative icons, posters (no source), animated backgrounds. They imitate craft instead of having it, cost contrast and performance, and add maintenance. "Material" in Lumière means **flat warm tonal steps** (ivory/charcoal surfaces already in the tokens); no texture is proposed.

## 2. Review of the current implementation against the philosophy
| area | now | verdict |
|---|---|---|
| Palette/tokens (`theme.py`) | warm ivory/charcoal, burgundy accent, olive-grey, near-black canvas, contrast-checked | **keep untouched** |
| Focus system, two-band ring, motion durations, reduced-motion, `_Fade`/`HoverFade`/banner | tested, accessible | **keep untouched** |
| Player screen (dark, near-black) | calm; controls unchanged | **keep untouched** |
| Dialogs, banner, tour, toast, messages | consistent, plain voice | **keep** (inherit radius change only) |
| Title cleaner, `recent.json`, engine, packaging | out of scope | **untouched** |
| Home hero | centred icon + centred headline + centred row inside a boxed card with four corner marks: symmetrical, template-like | **change** (R1) |
| "Continue watching" heading | 12 px bold grey sans label | **change** (R2) |
| Cards | grey art block with two initials (carries no information), 8 px radius, bordered, 1-line elided title | **change** (R3) |
| Radii | 8 / 6 px everywhere | **change** (R4) |
| Vertical rhythm | one gap size (`S4`) between all home blocks | **change** (R5) |
| Settings | clear, hairline-separated, bold sans row titles | **small change** (R6) |
| Wordmark/brand | "Kino Stream" until the name is decided; Lumière only by env preview | **unchanged** |

## 3. Proposed refinements (each separable; each can be accepted or refused)
**R1 Home hero, composed not centred.** Hide the icon; left-align a larger serif headline and the lead; action row starts at the text edge and the magnet field takes the free width; two crop marks (top-left, bottom-right) instead of four; tonal fill, no outline; the content column hugs the logo edge. Rationale: the first screen should have a point of view. *Risk:* at ≥1400 px the free space lies to the right; judge on the 1440 image. *Alternative:* keep the column centred and only left-align the text inside it.
**R2 Section heading.** Serif 20 with a hairline rule to the column edge (replaces the small bold label).
**R3 Title-card tiles.** Remove the initials block. Year (tabular, small) above; film title in the serif, up to 2 lines (elide after that); progress text in tabular figures; a 2 px progress line on the bottom edge. The newest entry is a wide "feature" tile (2 columns) with a larger title. Rationale: the initials say nothing; the cleaned title and year are the information; the first item is the likely action. *Risks:* flow-layout gaps next to the wide tile; long titles need a 2-line elide (the mock does not elide); more tooltip reliance. Behaviour, keyboard, tooltip, click and context menu are unchanged.
**R4 Radii** 8→4 (cards, drop zone), 6→4 (controls); two tokens in `theme.py`.
**R5 Rhythm.** `S6` above the section, `S3` below its heading, `S8` inside the hero; replaces uniform gaps.
**R6 Settings titles** in the serif (17–18); layout untouched.
**R7 (no change proposed)** playback-control fade: not implemented; any future proposal must show keyboard navigation, accessibility and real playback first.

## 4. Findings from the mock that the owner should know (honest limits)
- **Card edges (existing issue, visible in both before and after).** Card surface vs page is only 1.07:1 in the light theme (dark 1.11:1) and the card hairline 1.28:1, so tiles read faintly on ivory. Cards are identified by their text and, when focused, by the 3:1 focus ring, so this is not a failure of the focus/identification requirements, but it weakens the 'edited' look. If R3 is accepted, consider drawing the resting edge with `OUTLINE` (1.4–1.7:1) rather than `HAIRLINE`; do not remove the edge. The progress *track* (1.5:1) is decorative: the fill (≥6:1) and the text carry the state.
- **Contrast of the tokens used by the mock:** TEXT3 on SURFACE 5.01:1 dark / 5.23:1 light, TEXT2 5.95 / 6.80, ACCENT on SURFACE 6.13 / 6.22 (all ≥ 4.5:1). No new colours.
- **Wide windows:** R1's left bias is visible at 1440 px (right half of the page is empty below the header icons). Needs a judgement; see the alternative above.
- **Small window (720×520):** hero and first tile fit; the rest scrolls as today. Not verified with a keyboard in the mock (the mock does not add focus stops); the real implementation would need the existing focus tests re-run.
- The mock is an approximation (font features, exact metrics, hover/pressed states of the new tiles not exercised).

## 5. If approved: implementation plan (not started)
Files: `kino_stream_ui/theme.py` (radii, optional type tokens), `kino_stream_ui/home.py` (DropZone layout/paint, section heading, RecentCard layout, feature tile), `kino_stream_ui/settings_screen.py` (row titles). Tests to add/keep: `test_continue_watching`, `test_motion` (hover/pressed/focus on the new tiles), `test_accessibility` (focus ring contrast on the new surfaces, card edge), `test_theme`; screenshots regenerated both themes at 720×520, 1040×700, 1440×900. No persistent data, engine, cleaner or identifier changes.

## 6. Decisions requested
Accept / refuse / modify each of R1–R6 individually; choose R1 asymmetric column or centred-column alternative; confirm the "keep a visible card edge" recommendation; confirm that no texture is wanted.

## 7. Implemented (2026-10-10) — what the owner decided and what the code now does
| item | owner decision | implementation |
|---|---|---|
| R1 hero | approved, but a **balanced centred column** with left-aligned text (not hugging the left edge); composed at 720/1040/1440 px; no decorative filler | `HomeScreen.COLUMN_MAX = 932` (= 4 cards + gaps + margins, so hero, rule and card grid share edges); hero icon removed; `hero` serif 40 px; headline, lead and action row share one left edge (magnet field takes the free width); two crop marks (top-left, bottom-right); space above the hero grows with window height (24→64 px) |
| R2 headings | approved | `SectionHead` (serif 20 + hairline rule to the column edge), used for "Continue watching" only |
| R3 cards | approved with modification: balanced vs emphasised to be compared, no automatic emphasis | uniform 212×128 cards: year line (reserved row), serif title wrapped to 2 lines then elided (`wrap_elide`), progress in words, 2 px progress line on the bottom edge, original name in the tooltip. **Comparison** `screens/after/cards_balanced_*` vs `cards_emphasised_*`: **recommendation: keep balanced cards** — the wide card carries no extra information, makes the grid ragged and its title row looks emptier; no usability purpose found. Code default stays uniform |
| R4 radii | modified: a system, not one value | `R_CARD` 3 (editorial: cards, hero), `R_CTRL` 5 (buttons, inputs, menus), pills unchanged |
| R5 rhythm | approved | `GAP_SECTION` 32 / `GAP_GROUP` 16 / `GAP_TIGHT` 8; hero→section 32, heading→cards 16; Home and Settings headers share margins (24, 20) |
| R6 settings titles | approved | role `rowtitle` (serif 18); layout unchanged |
| card edge | keep visible, improve, not heavy; no texture | token `EDGE` (dark `#55514B` ≈ 2.0:1 vs page; light `#B8AF9D` ≈ 1.9:1), used on cards, the drop zone and outlined cards; kept while pressed; hover strengthens it |
| motion | unchanged | no new animation; hover/pressed/focus/reduced-motion code as before; playback screen untouched |
Not done on purpose: tabular figures (the installed Qt 6.4 has no `QFont.setFeature`), grain/texture, emphasised first card, new settings, data changes.

## 8. Review of the renders (2026-10-10, second review) and the refinements it justified
Checked at 720×520, 1040×700, 1440×900, both themes, populated / empty / long titles (`screens/after/`). Only evidence-based changes were made; nothing was added to fill space.
| finding | evidence | change |
|---|---|---|
| At 1440 px the hero box was mostly empty to the right of a 40 px headline | `after_*_1440x900` | the display line grows with the column: 40 px below 820 px hero width, 48 px above (typography, not decoration). Fits at all sizes (test) |
| Empty state read as unfinished: one small sans line under a heading and rule | `after_*_empty_*` | the hint is set in the serif (18 px, `TEXT2`, ≥ 4.5:1) with a 560 px measure, on the column's left edge. Same copy |
| A long compound word produced "Geschichte über Dona…" (cut in the middle of a word) | `after_*_long_titles_*` | elision now cuts between words ("Geschichte über…"); a first word that is itself too long is still cut by character. The full name is in the tooltip |
| Hero, section rule and card grid alignment | measured | share the left edge at 720/1040/1440 (tests); the grid never leaves the column |
| 1440 px "floating" | the populated page fills the column; the empty page ends at ~y 430 of 860 | **kept**: this is a launcher, the lower half is free space, and any filler would be decoration. The column cap (932) is kept: 4 cards per row fill it exactly; a wider cap makes the hero a mostly empty bar (judged on the earlier mock) |
| Small window (720) | hero controls inside the box, headline 40 px, cards wrap 2–3 per row, empty hint wraps | unchanged |
Open observation: at 1440 px a populated list with 1–2 rows ends well above the status strip. If this should be reconsidered, the evidence-based options are a slightly larger vertical offset for the hero at ≥ 800 px height (cheap) or leaving it as is (current). No change made.

## 9. The craft criterion for future design decisions
Before any visual change, answer in the review note:
1. **Typography first:** is the hierarchy achieved with scale, weight, spacing and alignment rather than a graphic?
2. **Purpose:** what does this help someone do (find, start, resume, understand)? If nothing, remove it.
3. **Restraint with a reason:** if it is asymmetric or unusual, can the reason be said in one sentence? Never random.
4. **No simulated material:** no grain, fake paper, glow, gratuitous gradient, decorative motion, random imperfection.
5. **Warm foundation:** charcoal, ivory, burgundy, olive-grey; contrast ratios documented.
6. **Interaction is earned:** hover/focus/pressed/transition/progress must give feedback; interruptible; reduced-motion; keyboard-visible.
7. **The film comes first:** the playback screen keeps its dark screening-room appearance in both application themes (tested: it always uses the dark token set).
8. **Evidence:** screenshots at 720/1040/1440 in both themes, long-title and empty cases, and the relevant tests.
