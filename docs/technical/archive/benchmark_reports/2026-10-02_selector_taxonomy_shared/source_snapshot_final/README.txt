This package freezes 22 served frontend resources plus nodes.py.
Default: G:\ComfyUI-aki-v3\python\python.exe -B rollback.py (read-only preflight).
Explicit restore: add --apply; only five JS files and nodes.py are restored.
The script requires unchanged source/formal hashes and an idle owned service.
Apply performs no restart, queue action, workflow save, data write or deletion.
After apply, restart ComfyUI under an idle-service guard, refresh the browser and rerun acceptance.
Multi-file restore is not fully crash-transactional. Before and after bytes are retained.
