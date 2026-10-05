#!/bin/bash
# Update ComfyUI-SortList from GitHub on Google Colab
# Run this script to update the custom node to the latest version

echo "=========================================="
echo " Updating ComfyUI-SortList from GitHub"
echo "=========================================="

# Navigate to the custom node directory
cd /content/ComfyUI/custom_nodes/comfyui-sortlist

echo ""
echo "[1/3] Fetching latest changes from GitHub..."
git fetch origin

echo ""
echo "[2/3] Pulling and merging changes..."
git pull origin main

echo ""
echo "[3/3] Checking status..."
git status

echo ""
echo "=========================================="
echo " ✓ Update Complete!"
echo "=========================================="
echo ""
echo "Changes applied:"
git log --oneline -5

echo ""
echo "NEXT STEPS:"
echo "1. Restart ComfyUI kernel (Runtime → Restart Runtime)"
echo "2. Re-run ComfyUI startup cells"
echo "3. Your nodes will be updated!"
echo ""
