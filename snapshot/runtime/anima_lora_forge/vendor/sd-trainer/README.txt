SD-Trainer Portable
===================

Quick Start:
  1. Double-click run_gui.bat
  2. First launch requires internet (downloads ~3 GB of PyTorch)
  3. Open http://127.0.0.1:28000 in browser

Tagging:
  Default WD tagger (wd14-convnextv2-v2) is bundled under tagger-models/wd14/
  (~400 MB). Put extra WD/CL tag models in tagger-models/wd14/<model-key>/
  Future VLM caption models can be placed under tagger-models/vlm/<model-key>/
  with the files required by that model, such as model.onnx and selected_tags.csv.

Directories:
  run_gui.bat      - Stable entrypoint for portable users
  run_gui_portable.bat - Legacy shim (logic in SD-Trainer/scripts/portable/)
  python_embeded/  - Python runtime
  SD-Trainer/      - Project files
  SD-Trainer\\sd-models\\  - Models (file picker; put models here)
  SD-Trainer\\output\\    - Training output
  SD-Trainer\\logs\\       - Logs
  sd-models\\ / output\\ / logs\\ at package root - junctions to SD-Trainer (legacy paths)
  tagger-models/   - Local tagger models

Update:
  Update-SD-Trainer.bat                - Git update (recommended if .git exists)
  Update-SD-Trainer-Release.bat      - Download latest Release 7z and merge
  update\update_sd_trainer.bat       - Shortcut to Update-SD-Trainer.bat
  update\update_from_release.bat     - Shortcut to Update-SD-Trainer-Release.bat
  update\update_dependencies.bat     - Update Python packages

Requirements:
  - Windows 10/11 64-bit
  - NVIDIA GPU (RTX 20-series or newer)
  - ~7 GB disk + ~3 GB download on first run

xformers (recommended):
  If xformers is missing, double-click install_xformers.bat to install.
  xformers provides faster attention than PyTorch SDPA on most GPUs.

Flash Attention 2:
  This portable package does NOT use flash-attn (uses xformers / PyTorch SDPA).
  Do not pip install flash-attn into python_embeded. See README in SD-Trainer/.
