P4 minimal supplementary resource check: clothing only, existing sanitized tab22.

Original files:
  runs/20261002_205503/browser_measurement.js is the original interaction-timing collector.
  runs/20261002_205503/lifecycle_after.json contains prior inline snapshots (no standalone lifecycle collector was saved).
  runs/20261002_205503/service_resource_after_cycles.json is only one final service sample.

Install lifecycle_collector.js after one prewarm, while the clothing selector is closed and synthetic node1063/1030 baselines are restored.
It creates __m9cLife. It does not install an observer, listener or polling loop. It wraps only four timer APIs for source-stack attribution.
Existing T06/M9b fetch wrappers may remain installed; do not arm their timing measurement during these resource cycles.

Cycle 0: __m9cLife.markClosed(0); wait at least 5 seconds; __m9cLife.sample(0).
Immediately collect CDP heap/listener data and run: python lifecycle_service_sample.py 0.
Cycles 1..10: open the same UAP clothing button, wait for cards, enter the same query 'hoodie', wait for matching results, close to the same console state.
Do not select/apply cards. Record __m9cLife.markClosed(cycle) after each close.
At cycle 5 and 10, wait the same 5 seconds and collect sample(cycle), CDP and lifecycle_service_sample.py 5|10.
Retain actual settled_ms and service timestamps. Shell service RSS samples are adjacent, not atomically simultaneous with browser values.
Check 0/5/10 identity and prompt guards, no clothing DOM after close, same closed workbench state, and source-attributed timer counts.
Whole-page DOM/JS heap are context, not exclusively clothing-owned memory. No forced GC. Existing accepted 60-second idle evidence remains separately labelled.

Timer scope:
- Only registrations after collector installation whose Error.stack has anima_clothing_selector.js, anima_shared_prompt_data.js or workbench_shell.js.
- Function timeouts leave the active map on firing, both timer kinds leave on clearTimeout/clearInterval (shared browser ID pool).
- Intervals remain active until cleared; metadata contains no callback/DOM strong references.
- No callback string is executed by instrumentation; string timeout callbacks are reported untracked.
- The stack identifies registration provenance, not exclusive component ownership. Do not claim pre-existing/all-page timer enumeration.
- No extra polling. Restore original APIs via cleanup; do not cancel outstanding application timers.

Listener attribution (root-owned CDP calls):
1. Obtain executed scriptIds for URLs ending anima_clothing_selector.js and anima_shared_prompt_data.js, plus workbench_shell.js, prompt_target.js, anima_selector_ui.js and modal_focus.js if present.
2. Runtime.evaluate({expression:'window',returnByValue:false,objectGroup:'m9c-lifecycle-listeners'}) -> objectId.
   DOMDebugger.getEventListeners({objectId}) -> listeners. Repeat for document.
3. Preserve each matching listener's target(window/document), type, useCapture, passive, once, scriptId, lineNumber, columnNumber.
   Filter by these observed scriptIds; do not replace attribution with Performance.getMetrics JSEventListeners.
4. Optional once while open: evaluate document.querySelector('#anima-clothing-selector-overlay') and get its listeners (subtree depth if supported).
5. Runtime.releaseObjectGroup for the group after each snapshot. Do not retain remote references to closed overlays.
6. Compare 0/5/10 *closed* attributed window/document listener sets. Stable UAP/workbench baseline handlers are allowed and identified.
   Removed overlay DOM plus stable globals is scoped evidence; it does not prove all detached objects are collectible.

Specific production attribution (source lines are 1-based; CDP lineNumber is 0-based):
- anima_shared_prompt_data.js checkRevision at line868 (CDP867): window focus + document visibilitychange; registered891/892, removed864/865.
- Its module-level window anima-tools-shared-prompts-updated handler at line23 (CDP22) is installed once and intentionally survives closure.
- prompt_target.js external at line78 (CDP77): document capture input/change; undoKey line79 (CDP78): document capture keydown.
  These three writer listeners register84/85/86 and dispose152; clothing closeModal calls insertionControls.dispose at1329.
- anima_selector_ui.js onInteraction at147 (CDP146): optional document capture pointerdown/keydown for favorite focus protection; not normally added by plain query/close.
- modal_focus.js uses root keydown/body MutationObserver, no global focus listener. These are not inferred from a document listener count.
- clothing closeModal1324 clears searchTimer1326, stops library watcher1327, disposes insertion controls1329 and image observer1330, removes overlay1332, disposes dialog1333.
- clothing search timeout is140ms (675–679); sidebar/list restoration is60ms/50ms (795/1030). shared revision1000ms is a Date.now dedup threshold, not an interval.

CDP Performance.getMetrics: capture JSHeapUsedSize/JSHeapTotalSize at each checkpoint if available; source label them separately from performance.memory.
Dedicated renderer RSS may remain unavailable when no reliable PID mapping is possible. Never use total Codex RSS as page RSS.

Finish: save __m9cLife.snapshot(); const cleanup=__m9cLife.cleanup(); save cleanup.
Then perform the previously planned T06/M9b cleanup and final guards. This collector changes no production files or formal data.
