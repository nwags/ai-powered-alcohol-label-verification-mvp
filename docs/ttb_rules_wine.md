# TTB Rules (Wine) - Distilled Summary for MVP

This note is a concise implementation aid for MVP heuristics.

## Scope

Wine profile heuristics in this prototype focus on:

- profile inference cues (wine/varietal/mead/cider lexicon)
- label-type hinting support
- core field extraction behavior for existing 7 fields

## MVP Heuristic Guidance

- Class/type extraction should use wine-oriented terms and avoid spirits false positives.
- Brand extraction should avoid replacing brand with varietal/type-only lines.
- Alcohol content handling should remain conservative and prefer `review` when uncertain.
- Appellation and sulfites are important extensions but out of scope for this step.
- Government warning logic remains shared across profiles.

## Non-goals

- Full legal completeness for all wine labeling requirements.
- Full appellation/sulfites validation logic.
