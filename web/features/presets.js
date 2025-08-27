import { createModal, showTextModal } from "../ui/modal.js";
import { el } from "../ui/helpers.js";
import { fetchPresets } from "../api/joycaption.js";

export async function applyPresetFlow(node, { getPreset, setPrompt, onDone }) {
  const chosen = getPreset();
  if (!chosen || chosen === "(none)") {
    showTextModal("Preset Not Applicable", "Pick a real preset.");
    return;
  }

  const data = await fetchPresets();
  if (data.status !== "success") {
    showTextModal("Error", data.message || "Failed to load presets.");
    return;
  }

  const tmpl = data.mapping[chosen];
  if (!tmpl) {
    showTextModal("Error", `No preset text found for: ${chosen}`);
    return;
  }

  const placeholders = data.meta?.[chosen]?.placeholders ?? [];
  const extras = Array.isArray(data.extras) ? data.extras : [];

  if (placeholders.length === 0 && !extras.some((e) => !e.header)) {
    setPrompt(tmpl);
    onDone?.();
    return;
  }

  const body = el("div");
  const addVarRow = (name, ph) => {
    const row = el("div");
    Object.assign(row.style, { display: "flex", gap: "8px", margin: "6px 0" });
    const label = el("label");
    Object.assign(label.style, { width: "140px" });
    label.textContent = `{${name}}`;
    const input = el("input", { type: "text" });
    input.className = "comfy-input";
    input.placeholder = ph;
    input.dataset.var = name;
    Object.assign(input.style, { flex: "1" });
    row.append(label, input);
    body.append(row);
  };

  if (placeholders.length) {
    const h = el("div");
    h.innerHTML = "<strong>Template variables</strong>";
    h.style.marginBottom = "6px";
    body.append(h);
    for (const name of placeholders) {
      addVarRow(
        name,
        name === "word_count"
          ? "e.g. 60"
          : name === "length"
          ? "short / medium / long"
          : name
      );
    }
  }

  const usableExtras = extras.filter((e) => !e.header);
  if (usableExtras.length) {
    const gh = el("div");
    gh.innerHTML = "<strong>Extra options</strong>";
    gh.style.marginTop = "10px";
    body.append(gh);

    for (const item of extras) {
      if (item.header) {
        const hh = el("div");
        hh.textContent = item.label;
        hh.style.opacity = "0.8";
        hh.style.marginTop = "8px";
        body.append(hh);
        continue;
      }
      const row = el("label");
      Object.assign(row.style, {
        display: "flex",
        alignItems: "center",
        gap: "8px",
        margin: "4px 0",
      });
      const cb = el("input", { type: "checkbox" });
      cb.dataset.label = item.label;
      const span = el("span");
      span.textContent = item.label;
      row.append(cb, span);
      body.append(row);
    }
  }

  const { cleanup } = createModal({
    title: `Apply preset: ${chosen}`,
    width: 700,
    body,
    actions: [
      {
        label: "Insert",
        default: true,
        onClick: () => {
          const varInputs = /** @type {NodeListOf<HTMLInputElement>} */ (
            body.querySelectorAll("input[data-var]")
          );
          let composed = tmpl;
          varInputs.forEach((inp) => {
            const key = inp.dataset.var || "";
            const val = (inp.value || "").trim();
            composed = composed.replaceAll(`{${key}}`, val);
          });

          const checkboxes = /** @type {NodeListOf<HTMLInputElement>} */ (
            body.querySelectorAll('input[type="checkbox"][data-label]')
          );
          const picked = [];
          checkboxes.forEach((cb) => {
            if (cb.checked) {
              const label = cb.dataset.label || "";
              const found = extras.find((e) => e.label === label && !e.header);
              if (found?.text) picked.push(found.text);
            }
          });
          if (picked.length) composed += "\n" + picked.join("\n");

          setPrompt(composed);
          cleanup();
          onDone?.();
        },
      },
      { label: "Cancel", onClick: () => cleanup() },
    ],
  });
}
