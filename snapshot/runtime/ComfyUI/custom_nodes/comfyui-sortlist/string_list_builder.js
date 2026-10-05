/**
 * StringListBuilder – auto-expanding dynamic STRING inputs
 *
 * Khi nối dây vào slot cuối cùng → tự thêm slot mới
 * Khi ngắt dây → dọn slot rỗng ở cuối (giữ lại 1 slot trống)
 */

import { app } from "../../scripts/app.js";

const NODE_NAME = "StringListBuilder";
const PREFIX = "string_";

/** Lấy tất cả input slot có tên string_N */
function getStringSlots(node) {
  return (node.inputs || []).filter((inp) => inp.name?.startsWith(PREFIX));
}

/** Thêm 1 slot mới: string_{N+1} */
function addSlot(node) {
  const n = getStringSlots(node).length;
  node.addInput(`${PREFIX}${n + 1}`, "STRING");
  node.setDirtyCanvas(true, true);
}

/** Xóa slot rỗng ở cuối, giữ ít nhất 1 slot trống */
function pruneEmpty(node) {
  const slots = getStringSlots(node);

  // Tìm số slot rỗng liên tiếp từ cuối
  let emptyTail = 0;
  for (let i = slots.length - 1; i >= 0; i--) {
    const linked = slots[i].link !== null && slots[i].link !== undefined;
    if (!linked) emptyTail++;
    else break;
  }

  // Chỉ giữ lại 1 slot rỗng ở cuối
  const toRemove = Math.max(0, emptyTail - 1);
  for (let r = 0; r < toRemove; r++) {
    // Luôn xóa string slot cuối cùng
    const allSlots = getStringSlots(node);
    const last = allSlots[allSlots.length - 1];
    const idx = node.inputs.indexOf(last);
    if (idx >= 0) node.removeInput(idx);
  }

  if (toRemove > 0) {
    renumber(node);
    node.setDirtyCanvas(true, true);
  }
}

/** Đánh số lại tên: string_1, string_2, ... */
function renumber(node) {
  let c = 1;
  for (const inp of node.inputs || []) {
    if (inp.name?.startsWith(PREFIX)) {
      inp.name = `${PREFIX}${c++}`;
    }
  }
}

app.registerExtension({
  name: "sortlist.StringListBuilder",

  async beforeRegisterNodeDef(nodeType, nodeData) {
    if (nodeData.name !== NODE_NAME) return;

    // ── onConnectionsChange ──────────────────────────────────────────────
    const _origChange = nodeType.prototype.onConnectionsChange;

    nodeType.prototype.onConnectionsChange = function (
      type,
      slotIndex,
      connected,
      linkInfo
    ) {
      if (_origChange) _origChange.apply(this, arguments);

      // type: 1 = INPUT, 2 = OUTPUT  (dùng số thay vì LiteGraph.INPUT)
      if (type !== 1) return;

      const slots = getStringSlots(this);
      if (!slots.length) return;

      if (connected) {
        // Nếu vừa nối vào slot cuối → thêm slot mới
        const lastSlot = slots[slots.length - 1];
        const lastIdx = (this.inputs || []).indexOf(lastSlot);
        if (slotIndex === lastIdx) {
          addSlot(this);
        }
      } else {
        // Ngắt dây → dọn slot rỗng cuối
        pruneEmpty(this);
      }
    };

    // ── onNodeCreated ──────────────────────────────────────────────────
    const _origCreated = nodeType.prototype.onNodeCreated;

    nodeType.prototype.onNodeCreated = function () {
      if (_origCreated) _origCreated.apply(this, arguments);
      // Đảm bảo luôn có ít nhất 1 slot khi tạo node mới
      if (getStringSlots(this).length === 0) {
        addSlot(this);
      }
    };
  },
});
