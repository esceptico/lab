# Lessons

- **Space stacked blocks with one sibling rule, not per-pair rules.** `.card + .card` missed a card that
  followed a grid row (`.pair`), so the Runs card sat flush against it (2026-09-23). Use
  `.col > * + * { margin-top }` so any new block type is covered. Check every seam in a screenshot, not only the first.

- **Design the core before stacking features; no hard-coded guesses** (2026-09-23). The owner flagged
  `blocks()` probing four attribute paths ("weird, too specific") and overall code quality. Roots: runs as raw
  dicts (69 string-key accesses, no schema), logic living in the CLI layer, duplicated constants across
  Python/JS, draft UI code shipped as-is. Rule: derive from the object (config, module structure) rather than
  listing known cases; define the record type once; after each slice, pause for a design pass before the next.

- **Every line and every word justifies itself** (2026-09-23). Mid-refactor the owner said the code became
  over-engineered. Cut: lost-run detection (pid + LOST + reconcile), symlinking skipped files, extra record
  fields for NaN/log errors, per-template smoke specs, closure factories. Keep a fix only when it closes a
  bug that was reproduced or is plausible in normal use; prefer deleting to adding. Same for copy: comments
  say why, never what; no claims the code does not back (campaign.toml said free-form keys show on the board).

- **Long strings wrap by one inherited rule, not per element** (2026-10-02). r010's command change ran out of
  the run pane: `white-space: pre` plus a grid `1fr` column sized to the longest unbreakable token. Fix:
  `overflow-wrap: anywhere` on `.card` and `pre-wrap` on code blocks. Exception: auto-layout tables, where
  `anywhere` squeezes columns mid-word, so they get `break-word`. Test with the longest real record (Kev r010).
  Follow-up: `anywhere` on a flex row squeezes short headings ("Progre/ss"), so flex labels get `flex-shrink: 0`;
  in an auto table only the prose cell (`.hyp`) and, on mobile, `th` get `anywhere`. In Paper, a text layer with
  `width: max-content` + `white-space: pre` only looks clipped; verify by layer bounds, fix with width 100% + pre-wrap.

- **Selecting never redraws what it does not change** (2026-10-03). Four board concepts were rejected, one reason
  being the progress chart reloading on every run click: the click handler called `drawProgress`, and a
  `ResizeObserver` on `body` fired whenever the run pane made the page taller. Fix: draw the chart per campaign
  and per width only; selection moves one ring element. The pane must not change the board's width either
  (fixed column when wide, an overlay when narrow). Also rejected: green accent, dated look, ASCII lineage,
  left nav, loose spacing. Build on the existing tokens and layout, not new styles.

- **"Redesign" means a new visual design, not a port** (2026-10-03). Asked to redesign the board, I rebuilt the
  existing look and the deliverables draft with a right panel; the owner called it a copy. A redesign request gets a
  new visual direction (type, palette, layout) with only the content they named kept. Show it in the chat as a link
  plus screenshots, never as file paths on their machine.

- **A redesign keeps every feature of the work it replaces unless the owner drops it** (2026-10-03). v2 had a new look
  but silently lost most of the concept's parts (status line, target gap, ×noise, lineage, full page, compare page,
  logs and tail, terminal, keys). Before redesigning, inventory every section, field, control and interaction of the
  reference, map each to its new home, and say in one line what is left out and why.

- **Look at good references and load the design skills before drawing** (2026-10-03). v2's dark band, amber parent
  links next to an amber best line, and mono uppercase labels read as a mess. Fix came from the dataviz skill (one
  accent line, grey context, solid hairline grid, one direct end label, no number on every point) and from looking
  at the PI speedrun page, Linear and Vercel first. One chart line per colour; lineage belongs in the run view.

- **A design pass is a process, not a patch on the last complaint** (2026-10-03). Owner: "you're not even trying".
  Order that worked: research, capture real reference screenshots and name what to take from each, write a one-page
  spec where every choice cites a reference or a lesson, build from the spec, then have a separate reviewer that has
  not seen the reasoning critique screenshots at every width and theme, and fix until it finds nothing serious.
  Five rounds took it from 16 serious problems to none; my own reviews had missed the phone overflow, mixed verdict
  and status words, "worse" on a change inside noise, and a gap-to-target measured from a non-comparable lock.

- **Copy earns its place; text is compact by default and expands on demand** (2026-10-03). On v3 the owner called
  Next/Findings raw, the stats strip too big, the run table "UI hell" (ids wrapped per character under lineage
  indent) and most copy useless. Rules: labels 1–3 words, no subtitle restating its heading, no helper prose on the
  board (it goes to the Guide or a tooltip), a cell only for a value that exists, one status mark per row, the id
  column never shrinks, record text one line until clicked, panels resizable and foldable instead of clipping.
  Never let CSS alter the owner's text (hyphens: auto inserted hyphens into records).

- **An open list of complaints is every complaint not yet fixed, not the last three** (2026-10-03). v3.2 fixed the
  three items in the handoff but shipped the stats strip the owner had already called too big, key glyphs inside
  buttons, and a chart that still could not show the run panel beside it ("is this graph sacred?"). Before each
  round, re-read every rejection in lessons.md and the spec's change log and check each one in the screenshots.
  Fixes that round: the strip became one sentence over the chart (the best value large, the rest as text, no boxes
  or meters); shortcuts live only in tooltips and the Guide; the run panel's column starts beside the chart, so
  the chart's width is fixed by the layout, not by keeping the panel away from it.

- **When the owner can't name what's wrong, decide and show one strong option** (2026-10-03). Three quick
  direction comps built without new references were called "ass", and a moodboard asking the owner to pick got
  "idk". What worked: capture real in-app screens first (marketing pages are weak references; PostHog, Linear,
  Braintrust and PlanetScale product UIs were useful), then commit to one direction with reasons and build it on
  real data. Never ask the owner to do the designer's job twice in a row.

- **No row of number tiles, in any form** (2026-10-03). The owner rejected the stats strip three times; it came
  back as boxed cells, then as a sentence, then as chart tabs ("for fucks sake"). A rejected element is rejected
  in every disguise. Put each number where it means something: the best and the gain as the chart's end label,
  spend as a header pill, run counts on the Runs tab. Before publishing, check every past rejection, including
  ones that come back reshaped.

- **Show each thing once, in full, in a form that needs no legend** (2026-10-03). v4 had Next twice (a banner and
  a tab), clipped the campaign question behind "More", and drew Δ as interval bars the owner couldn't read. Rules:
  one home per piece of content; the question and Next are short and decisive, so they're never truncated; prefer
  a number plus a plain unit ("+0.055 · 1.3× noise") to a mini chart that needs explaining; colour a change only
  at ≥2× noise.

- **Click every control and assert the page, before every publish** (2026-10-03). The Spend toggle replaced "the
  first .card" by selector; once Next became a card, Spend deleted Next and duplicated the chart. Screenshots after a
  click didn't catch it, and a phone table that clipped its Δ column passed a page-overflow check. Rule: replace parts
  by id, never by position; run `uv run --with playwright scripts/board_check.py <lab>` (clicks every control at 1440/1024/390 and asserts one
  chart, one Next, inspector = selection, no sideways overflow, no clipped number cells, tables fill their card) and
  get 0 failures before showing the owner anything.
