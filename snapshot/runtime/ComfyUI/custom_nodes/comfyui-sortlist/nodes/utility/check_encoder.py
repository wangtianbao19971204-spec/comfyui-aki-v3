"""
Google Colab fix for video_cut.py

This file provides utilities to check encoder availability and 
automatically choose the best encoding method for your environment.
"""

import subprocess
import os

def check_nvenc_available():
    """
    Check if NVENC encoder is actually available and working.
    Returns True if h264_nvenc can be used, False otherwise.
    """
    test_cmd = [
        "ffmpeg", "-f", "lavfi", "-i", "testsrc=duration=0.1:size=320x240:rate=25",
        "-c:v", "h264_nvenc", "-frames:v", "1", "-f", "null", "-"
    ]
    
    try:
        result = subprocess.run(
            test_cmd, 
            stdout=subprocess.PIPE, 
            stderr=subprocess.PIPE, 
            timeout=5
        )
        return result.returncode == 0
    except:
        return False

def get_recommended_settings():
    """
    Automatically detect the best encoding settings for your environment.
    Returns a dict with recommended settings.
    """
    settings = {
        "use_gpu": False,
        "encoder": "libx264",
        "reason": "Default CPU encoding"
    }
    
    # Check if NVENC is available
    if check_nvenc_available():
        settings["use_gpu"] = True
        settings["encoder"] = "h264_nvenc"
        settings["reason"] = "NVENC GPU encoding is available and working"
    else:
        # Check if we have CUDA but NVENC doesn't work
        try:
            result = subprocess.run(
                ["ffmpeg", "-hwaccels"],
                capture_output=True,
                text=True,
                timeout=3
            )
            if "cuda" in result.stdout.lower():
                settings["reason"] = "CUDA is available but NVENC is not supported - using CPU encoding"
            else:
                settings["reason"] = "No CUDA acceleration - using CPU encoding"
        except:
            settings["reason"] = "Unable to detect hardware - using CPU encoding"
    
    return settings

if __name__ == "__main__":
    print("=" * 70)
    print("CHECKING OPTIMAL ENCODING SETTINGS FOR YOUR ENVIRONMENT")
    print("=" * 70)
    
    settings = get_recommended_settings()
    
    print(f"\nRecommended Settings:")
    print(f"  use_gpu: {settings['use_gpu']}")
    print(f"  encoder: {settings['encoder']}")
    print(f"  reason: {settings['reason']}")
    
    print("\n" + "=" * 70)
    print("HOW TO USE IN COMFYUI:")
    print("=" * 70)
    if settings["use_gpu"]:
        print("  1. In your workflow, set 'use_gpu' = True")
        print("  2. The node will use NVENC GPU encoding")
        print("  3. Expected speed: VERY FAST")
    else:
        print("  1. In your workflow, set 'use_gpu' = False")
        print("  2. The node will use CPU encoding (libx264)")
        print("  3. Expected speed: Moderate (but the fallback will still work)")
        print("\n  NOTE: The updated video_cut.py will automatically")
        print("        fallback to CPU if GPU encoding fails!")
    print("=" * 70)
