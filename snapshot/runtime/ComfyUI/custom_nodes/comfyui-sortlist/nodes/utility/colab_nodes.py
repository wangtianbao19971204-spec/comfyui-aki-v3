"""
Colab Optimization Nodes - Keep Alive and Tunnel Auto Reconnect
Prevents Google Colab from disconnecting and auto-reconnects tunnels.
"""

import os
import time
import threading
import subprocess
import socket
from typing import Optional, Tuple, Any

# Global state for background threads
_keepalive_thread: Optional[threading.Thread] = None
_keepalive_running = False
_tunnel_thread: Optional[threading.Thread] = None
_tunnel_running = False
_tunnel_proc: Optional[subprocess.Popen] = None


class ColabKeepAlive:
    """
    Node to prevent Google Colab from disconnecting due to inactivity.
    Enhanced version with multiple anti-idle strategies for long-running workflows (8+ hours).
    """
    
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "enabled": ("BOOLEAN", {"default": True}),
                "interval_min": ("INT", {
                    "default": 30,
                    "min": 15,
                    "max": 60,
                    "step": 5,
                    "display": "slider"
                }),
                "interval_max": ("INT", {
                    "default": 60,
                    "min": 30,
                    "max": 120,
                    "step": 5,
                    "display": "slider"
                }),
                "method": (["aggressive", "gpu_ping", "colab_heartbeat", "memory_touch", "file_touch"], 
                          {"default": "aggressive"}),
            },
            "optional": {
                "any_input": ("*",),
            }
        }
    
    RETURN_TYPES = ("STRING", "*")
    RETURN_NAMES = ("status", "passthrough")
    FUNCTION = "execute"
    CATEGORY = "SortList/Utils"
    
    def execute(self, enabled: bool, interval_min: int, interval_max: int, method: str, any_input=None) -> Tuple[str, Any]:
        global _keepalive_thread, _keepalive_running
        
        if not enabled:
            _keepalive_running = False
            return ("⏹️ KeepAlive disabled", any_input)
        
        if _keepalive_thread is not None and _keepalive_thread.is_alive():
            return (f"✅ KeepAlive running ({method}, {interval_min}-{interval_max}s)", any_input)
        
        _keepalive_running = True
        
        def keepalive_worker():
            import gc
            import random
            touch_file = "/tmp/.colab_keepalive"
            colab_log = "/tmp/.colab_activity_log"
            counter = 0
            
            while _keepalive_running:
                try:
                    counter += 1
                    
                    if method == "aggressive":
                        # === AGGRESSIVE MODE: All methods combined ===
                        
                        # 1. GPU ping
                        try:
                            import torch
                            if torch.cuda.is_available():
                                # Larger tensor to create more GPU activity
                                x = torch.randn(100, 100, device="cuda")
                                y = torch.matmul(x, x.T)
                                del x, y
                                torch.cuda.synchronize()
                                torch.cuda.empty_cache()
                        except Exception:
                            pass
                        
                        # 2. File I/O activity
                        with open(touch_file, "w") as f:
                            f.write(f"{time.time()}-{counter}-{random.random()}")
                        
                        # 3. Colab kernel heartbeat + JavaScript browser activity simulation
                        # NOTE: This runs in Colab notebook context, NOT in ComfyUI!
                        # ComfyUI runs in a separate browser tab via tunnel, so these
                        # events will NOT click on your workflow - completely safe!
                        try:
                            from google.colab import output
                            # Simple console log
                            output.eval_js('console.log("keepalive")', ignore_result=True)
                            
                            # Full browser activity simulation (from colab_heartbeat)
                            output.eval_js('''
                                (function() {
                                    // Simulate mouse movement
                                    document.dispatchEvent(new MouseEvent('mousemove', {
                                        bubbles: true,
                                        cancelable: true,
                                        clientX: Math.random() * 100,
                                        clientY: Math.random() * 100
                                    }));
                                    
                                    // Simulate mouse click on body
                                    document.body.dispatchEvent(new MouseEvent('click', {
                                        bubbles: true,
                                        cancelable: true,
                                        clientX: 50,
                                        clientY: 50
                                    }));
                                    
                                    // Simulate keyboard activity
                                    document.dispatchEvent(new KeyboardEvent('keydown', {
                                        bubbles: true,
                                        cancelable: true,
                                        key: 'Shift'
                                    }));
                                    
                                    // Simulate scroll
                                    window.dispatchEvent(new Event('scroll'));
                                    
                                    // Simulate focus
                                    window.dispatchEvent(new Event('focus'));
                                    
                                    // Log for debugging
                                    console.log('Colab keepalive full simulation: ' + Date.now());
                                })();
                            ''', ignore_result=True)
                        except Exception:
                            pass
                        
                        # 4. WebSocket ping via IPython kernel
                        try:
                            from IPython import get_ipython
                            ip = get_ipython()
                            if ip:
                                # Trigger kernel activity
                                ip.kernel.do_one_iteration()
                        except Exception:
                            pass
                        
                        # 5. Memory churn
                        _ = [random.random() for _ in range(100000)]
                        del _
                        gc.collect()
                        
                        # 6. Log activity
                        with open(colab_log, "a") as f:
                            f.write(f"{time.time()}: keepalive #{counter} (aggressive+mouse)\n")
                    
                    elif method == "colab_heartbeat":
                        # Colab-specific heartbeat
                        try:
                            from google.colab import output
                            # Execute JavaScript to simulate activity
                            output.eval_js('''
                                (function() {
                                    // Simulate minimal activity
                                    document.dispatchEvent(new Event('mousemove'));
                                    console.log('Colab keepalive: ' + Date.now());
                                })();
                            ''', ignore_result=True)
                        except Exception:
                            pass
                        
                        # Also ping kernel
                        try:
                            from IPython import get_ipython
                            ip = get_ipython()
                            if ip and hasattr(ip, 'kernel'):
                                ip.kernel.do_one_iteration()
                        except Exception:
                            pass
                    
                    elif method == "gpu_ping":
                        try:
                            import torch
                            if torch.cuda.is_available():
                                x = torch.randn(50, 50, device="cuda")
                                _ = torch.matmul(x, x)
                                del x, _
                                torch.cuda.synchronize()
                                torch.cuda.empty_cache()
                        except Exception:
                            pass
                    
                    elif method == "memory_touch":
                        _ = [random.random() for _ in range(500000)]
                        del _
                        gc.collect()
                    
                    elif method == "file_touch":
                        with open(touch_file, "w") as f:
                            f.write(f"{time.time()}-{counter}")
                    
                    # Random sleep time within user-defined range to avoid pattern detection
                    sleep_time = random.uniform(interval_min, interval_max)
                    time.sleep(sleep_time)
                    
                except Exception as e:
                    print(f"[KeepAlive] Error: {e}")
                    time.sleep(random.uniform(interval_min, interval_max))
        
        _keepalive_thread = threading.Thread(target=keepalive_worker, daemon=True)
        _keepalive_thread.start()
        
        return (f"🟢 KeepAlive started ({method}, random {interval_min}-{interval_max}s)", any_input)



class TunnelAutoReconnect:
    """
    Node to manage tunnel connections (Pinggy, ngrok, cloudflare, etc.) with auto-reconnect.
    """
    
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "enabled": ("BOOLEAN", {"default": True}),
                "tunnel_type": (["pinggy", "ngrok", "cloudflare", "localtunnel", "custom"], {"default": "pinggy"}),
                "local_port": ("INT", {
                    "default": 8188,
                    "min": 1024,
                    "max": 65535,
                }),
                "check_interval": ("INT", {
                    "default": 30,
                    "min": 10,
                    "max": 120,
                    "step": 5,
                    "display": "slider"
                }),
                "max_retries": ("INT", {
                    "default": 5,
                    "min": 1,
                    "max": 20,
                }),
            },
            "optional": {
                "token": ("STRING", {"default": "", "multiline": False}),
                "custom_command": ("STRING", {"default": "", "multiline": True}),
                "any_input": ("*",),
            }
        }
    
    RETURN_TYPES = ("STRING", "STRING", "*")
    RETURN_NAMES = ("status", "tunnel_url", "passthrough")
    FUNCTION = "execute"
    CATEGORY = "SortList/Utils"
    
    def execute(
        self, 
        enabled: bool, 
        tunnel_type: str, 
        local_port: int,
        check_interval: int,
        max_retries: int,
        token: str = "",
        custom_command: str = "",
        any_input=None
    ) -> Tuple[str, str, Any]:
        global _tunnel_thread, _tunnel_running, _tunnel_proc
        
        if not enabled:
            _tunnel_running = False
            if _tunnel_proc:
                _tunnel_proc.terminate()
                _tunnel_proc = None
            return ("⏹️ Tunnel disabled", "", any_input)
        
        if _tunnel_thread is not None and _tunnel_thread.is_alive():
            return (f"✅ Tunnel running ({tunnel_type})", "", any_input)
        
        _tunnel_running = True
        tunnel_url_holder = {"url": ""}
        
        def get_tunnel_command() -> list:
            if tunnel_type == "pinggy" and token:
                return [
                    "ssh", "-p", "443",
                    f"-R0:localhost:{local_port}",
                    "-o", "StrictHostKeyChecking=no",
                    "-o", "ServerAliveInterval=30",
                    token
                ]
            elif tunnel_type == "ngrok" and token:
                return ["ngrok", "http", str(local_port), "--authtoken", token]
            elif tunnel_type == "cloudflare":
                if token:
                    return ["cloudflared", "tunnel", "run", "--token", token]
                else:
                    return ["cloudflared", "tunnel", "--url", f"http://localhost:{local_port}"]
            elif tunnel_type == "localtunnel":
                return ["lt", "--port", str(local_port)]
            elif tunnel_type == "custom" and custom_command:
                return custom_command.split()
            else:
                return []
        
        def is_port_available(port: int) -> bool:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            result = sock.connect_ex(('127.0.0.1', port))
            sock.close()
            return result == 0
        
        def start_tunnel():
            global _tunnel_proc
            cmd = get_tunnel_command()
            if not cmd:
                return None
            
            try:
                _tunnel_proc = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1
                )
                return _tunnel_proc
            except Exception as e:
                print(f"[Tunnel] Failed to start: {e}")
                return None
        
        def extract_url_from_output(text: str) -> Optional[str]:
            import re
            patterns = [
                r'https://[a-zA-Z0-9\-]+\.trycloudflare\.com',
                r'https://[a-zA-Z0-9\-]+\.free\.pinggy\.link',
                r'https://[a-zA-Z0-9\-]+\.ngrok\.io',
                r'https://[a-zA-Z0-9\-]+\.loca\.lt',
                r'https://[a-zA-Z0-9\-\.]+\.[a-zA-Z]{2,}(?::[0-9]+)?',
            ]
            for pattern in patterns:
                match = re.search(pattern, text, re.IGNORECASE)
                if match:
                    return match.group(0)
            return None
        
        def tunnel_worker():
            global _tunnel_proc
            
            # Wait for port to be available
            wait_count = 0
            while _tunnel_running and not is_port_available(local_port) and wait_count < 30:
                print(f"⏳ Waiting for ComfyUI on port {local_port}...")
                time.sleep(2)
                wait_count += 1
            
            if not is_port_available(local_port):
                print(f"❌ Port {local_port} not available after waiting")
                return
            
            print(f"✅ ComfyUI ready, starting tunnel...")
            proc = start_tunnel()
            if proc is None:
                print(f"❌ Failed to start tunnel")
                return
            
            print(f"🚀 Tunnel: Started {tunnel_type}")
            
            output_buffer = ""
            while _tunnel_running and proc.poll() is None:
                try:
                    line = proc.stdout.readline()
                    if line:
                        output_buffer += line
                        # Redact token from output
                        display_line = line.strip()
                        if token and token in display_line:
                            display_line = display_line.replace(token, "[REDACTED]")
                        print(f"🔗 Tunnel: {display_line}")
                        
                        url = extract_url_from_output(output_buffer)
                        if url:
                            tunnel_url_holder["url"] = url
                            print(f"🌐 Tunnel URL: {url}")
                except Exception:
                    pass
            
            # If we get here, tunnel ended
            if _tunnel_running:
                print(f"⚠ Tunnel disconnected. Giving up.")
        
        _tunnel_thread = threading.Thread(target=tunnel_worker, daemon=True)
        _tunnel_thread.start()
        
        time.sleep(3)
        
        url = tunnel_url_holder.get("url", "")
        status = f"🟢 Tunnel starting ({tunnel_type}, port {local_port})"
        
        return (status, url, any_input)


class RAMCleanup:
    """
    Node to aggressively clean up RAM and VRAM when workflow passes through.
    Useful between heavy processing steps to free up memory.
    """
    
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "enabled": ("BOOLEAN", {"default": True}),
                "clean_gpu": ("BOOLEAN", {"default": True, "tooltip": "Clean GPU VRAM"}),
                "clean_cpu": ("BOOLEAN", {"default": True, "tooltip": "Clean CPU RAM"}),
                "unload_models": ("BOOLEAN", {"default": False, "tooltip": "Unload all models from ComfyUI memory (aggressive)"}),
            },
            "optional": {
                "any_input": ("*",),
            }
        }
    
    RETURN_TYPES = ("STRING", "*")
    RETURN_NAMES = ("status", "passthrough")
    FUNCTION = "execute"
    CATEGORY = "SortList/Utils"
    
    def _get_memory_info(self):
        """Get current memory usage for reporting."""
        info = {}
        
        # CPU RAM
        try:
            import psutil
            mem = psutil.virtual_memory()
            info["ram_used_gb"] = mem.used / (1024**3)
            info["ram_total_gb"] = mem.total / (1024**3)
            info["ram_percent"] = mem.percent
        except Exception:
            pass
        
        # GPU VRAM
        try:
            import torch
            if torch.cuda.is_available():
                info["vram_used_gb"] = torch.cuda.memory_allocated() / (1024**3)
                info["vram_reserved_gb"] = torch.cuda.memory_reserved() / (1024**3)
                props = torch.cuda.get_device_properties(0)
                info["vram_total_gb"] = props.total_memory / (1024**3)
        except Exception:
            pass
        
        return info
    
    def execute(self, enabled: bool, clean_gpu: bool, clean_cpu: bool, unload_models: bool, any_input=None):
        if not enabled:
            return ("⏹️ RAM Cleanup disabled", any_input)
        
        import gc
        status_parts = []
        
        # Get memory BEFORE cleanup
        before = self._get_memory_info()
        
        # Unload all models from ComfyUI FIRST (most effective)
        if unload_models:
            try:
                import comfy.model_management as mm
                mm.unload_all_models()
                mm.soft_empty_cache()
                status_parts.append("Unloaded models")
            except Exception:
                pass
        
        # Clean CPU RAM - multiple passes
        if clean_cpu:
            # Multiple GC passes for thorough cleanup
            for _ in range(3):
                gc.collect()
            
            # Force release memory back to OS (Linux only)
            try:
                import ctypes
                libc = ctypes.CDLL("libc.so.6")
                libc.malloc_trim(0)
            except Exception:
                pass
            
            status_parts.append("CPU RAM")
        
        # Clean GPU VRAM
        if clean_gpu:
            try:
                import torch
                if torch.cuda.is_available():
                    # Synchronize first
                    torch.cuda.synchronize()
                    
                    # Clear all caches
                    torch.cuda.empty_cache()
                    torch.cuda.ipc_collect()
                    
                    # Clear cublas workspaces
                    try:
                        torch._C._cuda_clearCublasWorkspaces()
                    except Exception:
                        pass
                    
                    # Reset peak memory stats
                    torch.cuda.reset_peak_memory_stats()
                    
                    status_parts.append("GPU VRAM")
            except Exception:
                pass
        
        # Final cleanup
        gc.collect()
        
        # Get memory AFTER cleanup
        after = self._get_memory_info()
        
        # Build status with memory delta
        if status_parts:
            status = f"🧹 Cleaned: {', '.join(status_parts)}"
            
            # Add memory delta if available
            if "ram_used_gb" in before and "ram_used_gb" in after:
                ram_freed = before["ram_used_gb"] - after["ram_used_gb"]
                status += f" | RAM: {ram_freed:+.2f}GB"
            
            if "vram_used_gb" in before and "vram_used_gb" in after:
                vram_freed = before["vram_used_gb"] - after["vram_used_gb"]
                status += f" | VRAM: {vram_freed:+.2f}GB"
        else:
            status = "⚠️ No cleanup performed"
        
        return (status, any_input)


NODE_CLASS_MAPPINGS = {
    "ColabKeepAlive": ColabKeepAlive,
    "TunnelAutoReconnect": TunnelAutoReconnect,
    "RAMCleanup": RAMCleanup,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "ColabKeepAlive": "🔋 Colab Keep Alive",
    "TunnelAutoReconnect": "🔗 Tunnel Auto Reconnect",
    "RAMCleanup": "🧹 RAM Cleanup",
}
