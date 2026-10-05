T06 only: isolated insertion / exact undo timing

1. Keep __m9b installed. Import M9c_perf_workflow (graph id a2b12b8e-d5c6-5b86-9dc9-26ab3378cbf8), activate a1, open UAP.
2. While the unique positive textarea displays exactly "M9B synthetic 1063", evaluate the entire t06_collector.js async IIFE.
   It imports /scripts/app.js read-only, captures #1063 positive and the visible UAP textarea, and requires #1030 text == "".
   It installs window.__m9cT06 plus one synthetic positive fixture. No separate t06_value_reader installation is needed.
3. Set the UI's [aria-label="资料库插入目标"] to positive; click #uap-daily-desk .desk-library-action.
4. Synthetic card ID: m9c-positive-20261002_214157
   Set that card's [data-act="insert-mode"] to append_end through the UI before arming.
5. Call __m9cT06.arm('insert', {cohort:'fresh', iteration:1, page:1}), perform a real click on the returned selector, then await __m9cT06.wait().
6. Call __m9cT06.arm('undo', {cohort:'fresh', iteration:1, page:1}), real click on the returned selector, then await __m9cT06.wait().
7. Same page: repeat matched insert/undo pairs with cohort:'warm', iteration:1..7. Other two fresh pages each use cohort:'fresh', iteration:1, page:2 or 3.
   Each arm verifies exact preceding state. Do not restore widget values through scripts.
8. Save __m9cT06.snapshot(). Return to UAP and record the visible positive textarea, #1063 node, and #1030 side node.
9. Cleanup in this exact order: const receipt=__m9cT06.cleanup(); then __m9b.cleanup() after saving its evidence.
   The first cleanup removes only T06's fetch wrapper; the underlying M9b fetch/XHR guard remains.

Result status must be ready_after_two_animation_frames. Each sample records node_ready_ms, bound_input_ready_ms,
both_ready_ms and readiness sources; paint_opportunity_ms, raf_tail_ms and raf_tails are separate callback timing evidence.
Version 2-dom-observer-raf-tail uses a MutationObserver on panel status/DOM mutations to read exact node/input values;
an active-only rAF loop is the fallback. Value readiness is an observed upper bound, not an exact assignment timestamp.
The .value assignment itself does not trigger MO; subsequent production status/DOM changes provide the checkpoint.
Hot readiness checks do not force geometry/layout. Trusted click, target identity, exact values, visibility/focus, synthetic requests and blocked writes remain recorded.
Do not label a long rAF tail as insertion execution time or proof of actual painted pixels. CPU diagnosis is in t06_cpu_analysis.txt.
The 10-second deadline starts on the real click. An armed case with no click expires after 60 seconds. No idle background polling is installed.
Hidden bound UAP textarea is retained as the actual insertion target; visibility is explicitly recorded. Return-to-UAP visual mirror proof remains required.

Network isolation scope:
- GET library/index and library/prompts: one positive fixture with consistent category count.
- GET library/prompt: only that synthetic prompt_id; other detail IDs are rejected.
- POST mark_used: only that synthetic id + category; immediate local {} HTTP200.
- Other writes denied, except the existing precisely named read-only POST routes and logger acknowledgment delegated to __m9b.
- XHR guard remains owned by __m9b. Fixture routes use the production fetch interface.
- No synthetic response counts as production persistence performance. The reused semantic binding is an equality token in an isolated front-end fixture, not classifier evidence.

Self-check: node t06_fixture_selfcheck.mjs
This Node VM contract check exercises index/list/detail consistency, only-fixture mark_used acknowledgment, real-write denials,
unchanged graph values and cleanup restoration. It is not browser or insertion/undo acceptance.
Additional instrumentation self-check: node t06_observer_selfcheck.mjs. Its fake clock/observer/click only verify MO/fallback/RAF separation and cleanup.

Files: t06_collector.js (self-contained), t06_fixture_selfcheck.mjs, t06_fixture_selfcheck.json (receipt after running).
