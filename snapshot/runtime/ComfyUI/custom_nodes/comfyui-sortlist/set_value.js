import { app } from "../../scripts/app.js";

app.registerExtension({
  name: "vf9.SetValue.uiOnly",

  async beforeRegisterNodeDef(nodeType, nodeData) {
    const n = nodeData?.name;
    if (n !== "Set Value" && n !== "VF9_SetValue") return;

    const origCreated = nodeType.prototype.onNodeCreated;

    nodeType.prototype.onNodeCreated = function () {
      if (origCreated) origCreated.apply(this, arguments);

      // đổi text hiển thị trên GUI
      const ws = this.widgets || [];
      const setLabel = (name, label) => {
        const w = ws.find(x => x?.name === name);
        if (w) w.label = label;
      };

      setLabel("enable_background", "Giữ Background");
      setLabel("enable_mask", "Giữ Mask");

      this.setDirtyCanvas(true, true);
    };
  },
});
