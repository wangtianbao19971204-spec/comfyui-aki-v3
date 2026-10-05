#!/usr/bin/env python3
"""Test script to diagnose video_cut.py issues"""
import subprocess
import sys

def check_cuda_availability():
    """Check if CUDA is available for ffmpeg"""
    print("=" * 60)
    print("CHECKING CUDA/NVENC AVAILABILITY")
    print("=" * 60)
    
    # Check CUDA hwaccel
    cmd = ["ffmpeg", "-hwaccels"]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        print("\n[OK] Available Hardware Accelerators:")
        print(result.stdout)
        
        if "cuda" in result.stdout.lower():
            print("[OK] CUDA hardware acceleration is available")
        else:
            print("[FAIL] CUDA hardware acceleration is NOT available")
    except FileNotFoundError:
        print("[FAIL] ffmpeg is NOT installed or not in PATH")
        print("Please install ffmpeg or add it to your system PATH")
        return False
    except Exception as e:
        print(f"[FAIL] Error checking hwaccels: {e}")
        return False
    
    # Check NVENC encoder
    cmd = ["ffmpeg", "-encoders"]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        
        if "h264_nvenc" in result.stdout:
            print("[OK] h264_nvenc encoder is available")
        else:
            print("[FAIL] h264_nvenc encoder is NOT available")
            print("\n[INFO] Available H.264 encoders:")
            for line in result.stdout.split('\n'):
                if 'h264' in line.lower() and line.strip().startswith('V'):
                    print(f"  - {line.strip()}")
    except Exception as e:
        print(f"[FAIL] Error checking encoders: {e}")
    
    print("\n" + "=" * 60)

def test_simple_encode():
    """Test a simple encode with GPU and CPU"""
    print("\nTESTING SIMPLE ENCODING")
    print("=" * 60)
    
    # Test GPU encoding
    print("\n1. Testing GPU encoding (NVENC)...")
    gpu_cmd = [
        "ffmpeg", "-f", "lavfi", "-i", "testsrc=duration=1:size=640x480:rate=25",
        "-c:v", "h264_nvenc", "-preset", "p1", "-y", "test_gpu.mp4"
    ]
    
    try:
        result = subprocess.run(gpu_cmd, capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            print("[OK] GPU encoding works!")
        else:
            print("[FAIL] GPU encoding failed:")
            print(f"Error: {result.stderr[:500]}")
    except Exception as e:
        print(f"[FAIL] GPU encoding error: {e}")
    
    # Test CPU encoding
    print("\n2. Testing CPU encoding (libx264)...")
    cpu_cmd = [
        "ffmpeg", "-f", "lavfi", "-i", "testsrc=duration=1:size=640x480:rate=25",
        "-c:v", "libx264", "-preset", "veryfast", "-y", "test_cpu.mp4"
    ]
    
    try:
        result = subprocess.run(cpu_cmd, capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            print("[OK] CPU encoding works!")
        else:
            print("[FAIL] CPU encoding failed:")
            print(f"Error: {result.stderr[:500]}")
    except Exception as e:
        print(f"[FAIL] CPU encoding error: {e}")
    
    print("\n" + "=" * 60)

if __name__ == "__main__":
    print("\nVIDEO_CUT.PY DIAGNOSTIC TOOL")
    print("=" * 60)
    
    check_cuda_availability()
    test_simple_encode()
    
    print("\n" + "=" * 60)
    print("RECOMMENDATION:")
    print("=" * 60)
    print("Based on the results above:")
    print("- If CUDA/NVENC is NOT available -> Set use_gpu=False in ComfyUI")
    print("- If both GPU and CPU encoding failed -> Check your ffmpeg installation")
    print("- The updated video_cut.py will auto-fallback to CPU if GPU fails")
    print("=" * 60)
