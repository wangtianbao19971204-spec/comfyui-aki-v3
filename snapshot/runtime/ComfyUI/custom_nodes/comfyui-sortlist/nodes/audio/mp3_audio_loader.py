import os
import torch
import torchaudio


class MP3PathToAudio:
    """Load an MP3 file from path and output AUDIO for Video Combine."""
    
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "file_path": ("STRING", {
                    "default": "",
                    "multiline": False,
                    "placeholder": "Đường dẫn file mp3",
                }),
            }
        }

    RETURN_TYPES = ("AUDIO", "FLOAT")
    RETURN_NAMES = ("audio", "duration")
    FUNCTION = "load"
    CATEGORY = "comfyui-sortlist"

    def load(self, file_path):
        if not file_path or not os.path.isfile(file_path):
            raise Exception(f"File không tồn tại: {file_path}")

        waveform, sample_rate = torchaudio.load(file_path)
        # AUDIO format: {'waveform': (1, channels, samples), 'sample_rate': int}
        waveform = waveform.unsqueeze(0)  # Add batch dim: (channels, samples) -> (1, channels, samples)
        
        duration = waveform.shape[2] / sample_rate

        audio = {
            "waveform": waveform,
            "sample_rate": sample_rate,
        }
        return (audio, duration)


NODE_CLASS_MAPPINGS = {
    "MP3 Path To Audio": MP3PathToAudio,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "MP3 Path To Audio": "MP3 Path → Audio",
}
