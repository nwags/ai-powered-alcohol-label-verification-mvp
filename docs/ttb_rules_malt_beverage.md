# TTB Rules (Malt Beverage) - Distilled Summary for MVP

This note is a concise implementation aid for MVP heuristics.

## Scope

Malt beverage profile heuristics in this prototype focus on:

- profile inference cues (beer/malt lexicon, customary units)
- label-type hinting support
- core field extraction behavior for existing 7 fields

## MVP Heuristic Guidance

- Alcohol content may be conditional; absence should default to `review`, not hard mismatch.
- Net contents frequently appear in U.S. customary forms (`fl oz`, `oz`).
- Brand/class extraction should avoid treating style-only lines as brand names.
- Government warning logic remains shared across profiles.

## Non-goals

- Full legal completeness for all malt beverage labeling requirements.
- Advanced geometric layout analysis.
