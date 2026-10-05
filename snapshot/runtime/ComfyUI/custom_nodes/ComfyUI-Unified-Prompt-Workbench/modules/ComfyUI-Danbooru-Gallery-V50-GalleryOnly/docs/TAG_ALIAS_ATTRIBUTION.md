# Tag alias data attribution

The optional official-alias database used by this plugin is derived from the
following immutable dataset snapshot:

- Dataset and credited publisher: `deepghs/site_tags` by deepghs
- Source file: `danbooru.donmai.us/tag_aliases.csv`
- Source URL: <https://huggingface.co/datasets/deepghs/site_tags/resolve/2b4de8c3f79540b10387a6fa7f251274f0b224a8/danbooru.donmai.us/tag_aliases.csv>
- Revision: `2b4de8c3f79540b10387a6fa7f251274f0b224a8`
- Source size: `1,684,212` bytes
- Source SHA-256: `a3dad50f86f4b8d117096c64ba1bd332be02b16222c587a8d2cddddf86ed852a`
- Declared dataset license: [Creative Commons Attribution 4.0 International (CC BY 4.0)](https://creativecommons.org/licenses/by/4.0/)
- Snapshot verified: 2026-07-19

## Changes and filtering performed by this plugin

The source CSV is not bundled as an unmodified dataset dump. The local importer
reads only the `alias` and `tag` relation, normalizes both lookup keys with
Unicode NFKC, case-folding, and whitespace-to-underscore conversion, rejects
malformed/self/conflicting relations, and de-duplicates identical relations.

At import time, a relation is retained only when its canonical target already
exists in the local `hot_tags` table and that target is not category `1`
(`artist`). Missing canonical targets and every artist-targeting relation are
excluded. The importer does not insert, update, delete, merge, or rename any
`hot_tags` row, and translations always remain properties of canonical tags.

The resulting SQLite alias rows include the source URL, declared license,
revision, SHA-256, relation type, and import timestamp. A separate provenance
record stores input, eligibility, insertion, update, preservation, rejection,
missing-target, and artist-filter counts.

The plugin's own source code remains under its repository license. The adapted
alias data remains subject to the CC BY 4.0 terms above.
