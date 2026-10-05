# Anima Tools Frontend Architecture

## Refactor goal

The frontend is being migrated from independent selector implementations to a shared UI foundation without changing node behavior, workflow serialization, backend APIs, persisted favorites, or local storage keys.

## Compatibility contract

The following are treated as stable external contracts:

- Python node class names, widget names, inputs, outputs, and prompt formatting
- Workflow serialization and restoration
- `/anima-tools/*` API paths and payload formats
- Favorites, groups, custom-item data, and local storage keys
- Selector apply, cancel, copy, search, filter, pagination, and restore behavior
- Existing translation keys

## Shared UI foundation

`js/anima_selector_ui.js` owns selector-agnostic frontend behavior:

- design tokens for shared surfaces, overlays, borders, shadows, and layers
- DOM creation, clipboard fallback, HTML escaping, prompt token parsing, and debounce
- secondary modal shells, confirmation button rows, and toast notifications
- the common visual-gallery stylesheet, parameterized by selector kind

Business data, filters, selection state, favorites, persistence, and node write-back remain inside each selector adapter.

## Migration status

| Selector | Shared primitives | Shared gallery stylesheet | Notes |
| --- | --- | --- | --- |
| Clothing | Yes | Yes | Existing selection restoration remains unchanged |
| Background | Yes | Yes | Existing one-way selection behavior remains unchanged |
| Pose | Yes | Yes | Existing one-way selection behavior remains unchanged |
| Artist | Pending | Pending | Large dataset, CDN behavior, and unique card metadata need a dedicated adapter |
| Character | Pending | Pending | Multi-dimensional filters need a dedicated adapter |
| LoRA | Node controls only | Not applicable | Shared node-row controls are complete; remote search, download, local files, and detail panel still need a dedicated shell |

## Migration rule

Selectors are migrated incrementally. A selector is considered migrated only when generated styles are equivalent to its previous inline styles, JavaScript parses successfully, shared primitive tests pass, and its persistence and node write-back contracts remain untouched.
