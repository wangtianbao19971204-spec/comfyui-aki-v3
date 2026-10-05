def _anima_selector_tags_result(tags, text):
    payload = tags if isinstance(tags, dict) else {}
    return {"ui": {"anima_selector_tags": [payload]}, "result": (text,)}

class AnimaArtistTagSelector:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "artist_tags": ("STRING", {"multiline": True, "default": ""}),
                "mode": (["append", "override"], {"default": "append"}),
            },
            "optional": {
                "opt_prompt": ("STRING", {"forceInput": True}),
            }
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("text",)
    FUNCTION = "process_tags"
    CATEGORY = "AnimaArt"
    def process_tags(self, artist_tags, mode, opt_prompt=""):
        tags_list = [t.strip() for t in artist_tags.split(",") if t.strip()]
        processed_tags = []
        for tag in tags_list:
            if tag.startswith("_raw_:"):
                processed_tags.append(tag[6:])
                continue
            clean_tag = tag
            if clean_tag.startswith("@"):
                clean_tag = clean_tag[1:].strip()
            elif clean_tag.lower().startswith("by "):
                clean_tag = clean_tag[3:].strip()
            if clean_tag:
                processed_tags.append(f"@{clean_tag}")
        joined_artists = ", ".join(processed_tags)

        # 结合外部 prompt
        if opt_prompt and opt_prompt.strip():
            opt_prompt = opt_prompt.strip()
            if mode == "append":
                # 追加模式：选择的画师 tag 在前，外接的 opt_prompt 在后，末尾补上逗号
                if joined_artists:
                    if opt_prompt.endswith(","):
                        final_text = f"{joined_artists}, {opt_prompt}"
                    else:
                        final_text = f"{joined_artists}, {opt_prompt}, "
                else:
                    final_text = opt_prompt
            else:
                # 覆盖模式：直接输出画师 tags，并在末尾带上逗号
                if joined_artists:
                    final_text = f"{joined_artists}, "
                else:
                    final_text = ""
        else:
            if joined_artists:
                final_text = f"{joined_artists}, "
            else:
                final_text = ""

        return _anima_selector_tags_result({"artist_tags": artist_tags}, final_text)

class AnimaArtistTagSelectorPlus:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "artist_tags": ("STRING", {"multiline": True, "default": ""}),
                "extra_text": ("STRING", {"multiline": True, "default": ""}),
                "separator": ("STRING", {"default": ", "}),
            }
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("text",)
    FUNCTION = "process_tags"
    CATEGORY = "AnimaArt"

    def process_tags(self, artist_tags, extra_text, separator=", "):
        # 1. 过滤并处理画师 tags
        tags_list = [t.strip() for t in artist_tags.split(",") if t.strip()]
        processed_tags = []
        
        for tag in tags_list:
            if tag.startswith("_raw_:"):
                processed_tags.append(tag[6:])
                continue
            clean_tag = tag
            if clean_tag.startswith("@"):
                clean_tag = clean_tag[1:].strip()
            elif clean_tag.lower().startswith("by "):
                clean_tag = clean_tag[3:].strip()
            
            if clean_tag:
                processed_tags.append(f"@{clean_tag}")
        
        joined_artists = ", ".join(processed_tags)
        # 🌟 只要有画师，尾部必带逗号与空格，保证输出框及默认状态下的绝对完美隔开
        if joined_artists:
            joined_artists += ", "

        # 2. 将两段自动拼接到一起 (画师在前，自定义提示词在后)
        extra_text_clean = extra_text.strip() if extra_text else ""
        
        if extra_text_clean and joined_artists:
            # 画师在前，提示词在后
            # 🌟 智能合并去重：如果分隔符是逗号或被删空，则直接利用 joined_artists 尾部的逗号连接，避免产生多余的双逗号
            sep = separator if separator is not None else ", "
            if sep.strip() == "," or sep.strip() == "":
                final_text = f"{joined_artists}{extra_text_clean}"
            else:
                # 否则，剥离画师尾部逗号，使用用户填写的自定义非逗号分隔符连接
                final_text = f"{joined_artists.rstrip(', ')}{sep}{extra_text_clean}"
        elif extra_text_clean:
            final_text = extra_text_clean
        else:
            final_text = joined_artists

        return _anima_selector_tags_result({"artist_tags": artist_tags}, final_text)

class AnimaCharacterTagSelector:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "character_tags": ("STRING", {"multiline": True, "default": ""}),
                "mode": (["append", "override"], {"default": "append"}),
            },
            "optional": {
                "opt_prompt": ("STRING", {"forceInput": True}),
            }
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("text",)
    FUNCTION = "process_tags"
    CATEGORY = "AnimaArt"

    def process_tags(self, character_tags, mode, opt_prompt=""):
        tags_list = [t.strip() for t in character_tags.split(",") if t.strip()]
        processed_tags = []
        
        for tag in tags_list:
            if tag.startswith("_raw_:"):
                processed_tags.append(tag[6:])
                continue
            clean_tag = tag
            if clean_tag.startswith("@"):
                clean_tag = clean_tag[1:].strip()
            
            if clean_tag:
                processed_tags.append(clean_tag)
        
        joined_characters = ", ".join(processed_tags)

        if opt_prompt and opt_prompt.strip():
            opt_prompt = opt_prompt.strip()
            if mode == "append":
                # 追加模式：选择的角色 tag 在前，外接的 opt_prompt 在后，末尾补上逗号
                if joined_characters:
                    if opt_prompt.endswith(","):
                        final_text = f"{joined_characters}, {opt_prompt}"
                    else:
                        final_text = f"{joined_characters}, {opt_prompt}, "
                else:
                    final_text = opt_prompt
            else:
                if joined_characters:
                    final_text = f"{joined_characters}, "
                else:
                    final_text = ""
        else:
            if joined_characters:
                final_text = f"{joined_characters}, "
            else:
                final_text = ""

        return _anima_selector_tags_result({"character_tags": character_tags}, final_text)

class AnimaCharacterTagSelectorPlus:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "character_tags": ("STRING", {"multiline": True, "default": ""}),
                "extra_text": ("STRING", {"multiline": True, "default": ""}),
                "separator": ("STRING", {"default": ", "}),
            }
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("text",)
    FUNCTION = "process_tags"
    CATEGORY = "AnimaArt"

    def process_tags(self, character_tags, extra_text, separator=", "):
        tags_list = [t.strip() for t in character_tags.split(",") if t.strip()]
        processed_tags = []
        
        for tag in tags_list:
            if tag.startswith("_raw_:"):
                processed_tags.append(tag[6:])
                continue
            clean_tag = tag
            if clean_tag.startswith("@"):
                clean_tag = clean_tag[1:].strip()
            
            if clean_tag:
                processed_tags.append(clean_tag)
        
        joined_characters = ", ".join(processed_tags)
        if joined_characters:
            joined_characters += ", "

        extra_text_clean = extra_text.strip() if extra_text else ""
        
        if extra_text_clean and joined_characters:
            sep = separator if separator is not None else ", "
            if sep.strip() == "," or sep.strip() == "":
                final_text = f"{joined_characters}{extra_text_clean}"
            else:
                final_text = f"{joined_characters.rstrip(', ')}{sep}{extra_text_clean}"
        elif extra_text_clean:
            final_text = extra_text_clean
        else:
            final_text = joined_characters

        return _anima_selector_tags_result({"character_tags": character_tags}, final_text)

class AnimaClothingTagSelector:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "clothing_tags": ("STRING", {"multiline": True, "default": ""}),
                "mode": (["append", "override"], {"default": "append"}),
            },
            "optional": {
                "opt_prompt": ("STRING", {"forceInput": True}),
            }
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("text",)
    FUNCTION = "process_tags"
    CATEGORY = "AnimaArt"

    def process_tags(self, clothing_tags, mode, opt_prompt=""):
        tags_list = [t.strip() for t in clothing_tags.split(",") if t.strip()]
        processed_tags = []

        for tag in tags_list:
            if tag.startswith("_raw_:"):
                processed_tags.append(tag[6:])
                continue
            if tag:
                processed_tags.append(tag)

        joined_clothing = ", ".join(processed_tags)

        if opt_prompt and opt_prompt.strip():
            opt_prompt = opt_prompt.strip()
            if mode == "append":
                if joined_clothing:
                    if opt_prompt.endswith(","):
                        final_text = f"{joined_clothing}, {opt_prompt}"
                    else:
                        final_text = f"{joined_clothing}, {opt_prompt}, "
                else:
                    final_text = opt_prompt
            else:
                if joined_clothing:
                    final_text = f"{joined_clothing}, "
                else:
                    final_text = ""
        else:
            if joined_clothing:
                final_text = f"{joined_clothing}, "
            else:
                final_text = ""

        return _anima_selector_tags_result({"clothing_tags": clothing_tags}, final_text)

class AnimaClothingTagSelectorPlus:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "clothing_tags": ("STRING", {"multiline": True, "default": ""}),
                "extra_text": ("STRING", {"multiline": True, "default": ""}),
                "separator": ("STRING", {"default": ", "}),
            }
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("text",)
    FUNCTION = "process_tags"
    CATEGORY = "AnimaArt"

    def process_tags(self, clothing_tags, extra_text, separator=", "):
        tags_list = [t.strip() for t in clothing_tags.split(",") if t.strip()]
        processed_tags = []

        for tag in tags_list:
            if tag.startswith("_raw_:"):
                processed_tags.append(tag[6:])
                continue
            if tag:
                processed_tags.append(tag)

        joined_clothing = ", ".join(processed_tags)
        if joined_clothing:
            joined_clothing += ", "

        extra_text_clean = extra_text.strip() if extra_text else ""

        if extra_text_clean and joined_clothing:
            sep = separator if separator is not None else ", "
            if sep.strip() == "," or sep.strip() == "":
                final_text = f"{joined_clothing}{extra_text_clean}"
            else:
                final_text = f"{joined_clothing.rstrip(', ')}{sep}{extra_text_clean}"
        elif extra_text_clean:
            final_text = extra_text_clean
        else:
            final_text = joined_clothing

        return _anima_selector_tags_result({"clothing_tags": clothing_tags}, final_text)

class AnimaBackgroundTagSelector:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "background_tags": ("STRING", {"multiline": True, "default": ""}),
                "mode": (["append", "override"], {"default": "append"}),
            },
            "optional": {
                "opt_prompt": ("STRING", {"forceInput": True}),
            }
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("text",)
    FUNCTION = "process_tags"
    CATEGORY = "AnimaArt"

    def process_tags(self, background_tags, mode, opt_prompt=""):
        tags_list = [t.strip() for t in background_tags.split(",") if t.strip()]
        processed_tags = []

        for tag in tags_list:
            if tag.startswith("_raw_:"):
                processed_tags.append(tag[6:])
                continue
            if tag:
                processed_tags.append(tag)

        joined_background = ", ".join(processed_tags)

        if opt_prompt and opt_prompt.strip():
            opt_prompt = opt_prompt.strip()
            if mode == "append":
                if joined_background:
                    if opt_prompt.endswith(","):
                        final_text = f"{joined_background}, {opt_prompt}"
                    else:
                        final_text = f"{joined_background}, {opt_prompt}, "
                else:
                    final_text = opt_prompt
            else:
                if joined_background:
                    final_text = f"{joined_background}, "
                else:
                    final_text = ""
        else:
            if joined_background:
                final_text = f"{joined_background}, "
            else:
                final_text = ""

        return _anima_selector_tags_result({"background_tags": background_tags}, final_text)

class AnimaBackgroundTagSelectorPlus:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "background_tags": ("STRING", {"multiline": True, "default": ""}),
                "extra_text": ("STRING", {"multiline": True, "default": ""}),
                "separator": ("STRING", {"default": ", "}),
            }
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("text",)
    FUNCTION = "process_tags"
    CATEGORY = "AnimaArt"

    def process_tags(self, background_tags, extra_text, separator=", "):
        tags_list = [t.strip() for t in background_tags.split(",") if t.strip()]
        processed_tags = []

        for tag in tags_list:
            if tag.startswith("_raw_:"):
                processed_tags.append(tag[6:])
                continue
            if tag:
                processed_tags.append(tag)

        joined_background = ", ".join(processed_tags)
        if joined_background:
            joined_background += ", "

        extra_text_clean = extra_text.strip() if extra_text else ""

        if extra_text_clean and joined_background:
            sep = separator if separator is not None else ", "
            if sep.strip() == "," or sep.strip() == "":
                final_text = f"{joined_background}{extra_text_clean}"
            else:
                final_text = f"{joined_background.rstrip(', ')}{sep}{extra_text_clean}"
        elif extra_text_clean:
            final_text = extra_text_clean
        else:
            final_text = joined_background

        return _anima_selector_tags_result({"background_tags": background_tags}, final_text)

class AnimaPoseTagSelector:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "pose_tags": ("STRING", {"multiline": True, "default": ""}),
                "mode": (["append", "override"], {"default": "append"}),
            },
            "optional": {
                "opt_prompt": ("STRING", {"forceInput": True}),
            }
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("text",)
    FUNCTION = "process_tags"
    CATEGORY = "AnimaArt"

    def process_tags(self, pose_tags, mode, opt_prompt=""):
        tags_list = [t.strip() for t in pose_tags.split(",") if t.strip()]
        processed_tags = []

        for tag in tags_list:
            if tag.startswith("_raw_:"):
                processed_tags.append(tag[6:])
                continue
            if tag:
                processed_tags.append(tag)

        joined_pose = ", ".join(processed_tags)

        if opt_prompt and opt_prompt.strip():
            opt_prompt = opt_prompt.strip()
            if mode == "append":
                if joined_pose:
                    if opt_prompt.endswith(","):
                        final_text = f"{joined_pose}, {opt_prompt}"
                    else:
                        final_text = f"{joined_pose}, {opt_prompt}, "
                else:
                    final_text = opt_prompt
            else:
                if joined_pose:
                    final_text = f"{joined_pose}, "
                else:
                    final_text = ""
        else:
            if joined_pose:
                final_text = f"{joined_pose}, "
            else:
                final_text = ""

        return _anima_selector_tags_result({"pose_tags": pose_tags}, final_text)

class AnimaPoseTagSelectorPlus:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "pose_tags": ("STRING", {"multiline": True, "default": ""}),
                "extra_text": ("STRING", {"multiline": True, "default": ""}),
                "separator": ("STRING", {"default": ", "}),
            }
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("text",)
    FUNCTION = "process_tags"
    CATEGORY = "AnimaArt"

    def process_tags(self, pose_tags, extra_text, separator=", "):
        tags_list = [t.strip() for t in pose_tags.split(",") if t.strip()]
        processed_tags = []

        for tag in tags_list:
            if tag.startswith("_raw_:"):
                processed_tags.append(tag[6:])
                continue
            if tag:
                processed_tags.append(tag)

        joined_pose = ", ".join(processed_tags)
        if joined_pose:
            joined_pose += ", "

        extra_text_clean = extra_text.strip() if extra_text else ""

        if extra_text_clean and joined_pose:
            sep = separator if separator is not None else ", "
            if sep.strip() == "," or sep.strip() == "":
                final_text = f"{joined_pose}{extra_text_clean}"
            else:
                final_text = f"{joined_pose.rstrip(', ')}{sep}{extra_text_clean}"
        elif extra_text_clean:
            final_text = extra_text_clean
        else:
            final_text = joined_pose

        return _anima_selector_tags_result({"pose_tags": pose_tags}, final_text)

class AnimaStyleQualitySelector:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "style_quality_tags": ("STRING", {"multiline": True, "default": ""}),
                "mode": (["append", "override"], {"default": "append"}),
            },
            "optional": {
                "opt_prompt": ("STRING", {"forceInput": True}),
            }
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("text",)
    FUNCTION = "process_tags"
    CATEGORY = "AnimaArt"

    def process_tags(self, style_quality_tags, mode, opt_prompt=""):
        tags_list = [
            tag.strip()
            for tag in style_quality_tags.split(",")
            if tag.strip()
        ]
        processed_tags = [
            tag[6:] if tag.startswith("_raw_:") else tag
            for tag in tags_list
        ]
        joined_tags = ", ".join(processed_tags)

        if opt_prompt and opt_prompt.strip():
            opt_prompt = opt_prompt.strip()
            if mode == "append":
                if joined_tags:
                    final_text = (
                        f"{joined_tags}, {opt_prompt}"
                        if opt_prompt.endswith(",")
                        else f"{joined_tags}, {opt_prompt}, "
                    )
                else:
                    final_text = opt_prompt
            else:
                final_text = f"{joined_tags}, " if joined_tags else ""
        else:
            final_text = f"{joined_tags}, " if joined_tags else ""

        return _anima_selector_tags_result(
            {"style_quality_tags": style_quality_tags},
            final_text,
        )

class AnimaStyleQualitySelectorPlus:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "style_quality_tags": ("STRING", {"multiline": True, "default": ""}),
                "extra_text": ("STRING", {"multiline": True, "default": ""}),
                "separator": ("STRING", {"default": ", "}),
            }
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("text",)
    FUNCTION = "process_tags"
    CATEGORY = "AnimaArt"

    def process_tags(self, style_quality_tags, extra_text, separator=", "):
        tags_list = [
            tag.strip()
            for tag in style_quality_tags.split(",")
            if tag.strip()
        ]
        processed_tags = [
            tag[6:] if tag.startswith("_raw_:") else tag
            for tag in tags_list
        ]
        joined_tags = ", ".join(processed_tags)
        if joined_tags:
            joined_tags += ", "

        extra_text_clean = extra_text.strip() if extra_text else ""
        if extra_text_clean and joined_tags:
            sep = separator if separator is not None else ", "
            if sep.strip() == "," or sep.strip() == "":
                final_text = f"{joined_tags}{extra_text_clean}"
            else:
                final_text = f"{joined_tags.rstrip(', ')}{sep}{extra_text_clean}"
        elif extra_text_clean:
            final_text = extra_text_clean
        else:
            final_text = joined_tags

        return _anima_selector_tags_result(
            {"style_quality_tags": style_quality_tags},
            final_text,
        )

class AnimaPromptPlus:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "quality_prompt": ("STRING", {"multiline": True, "default": ""}),
                "artist_tags": ("STRING", {"multiline": True, "default": ""}),
                "character_tags": ("STRING", {"multiline": True, "default": ""}),
                "clothing_tags": ("STRING", {"multiline": True, "default": ""}),
                "pose_tags": ("STRING", {"multiline": True, "default": ""}),
                "background_tags": ("STRING", {"multiline": True, "default": ""}),
                "extra_prompt": ("STRING", {"multiline": True, "default": ""}),
                "separator": ("STRING", {"default": ", "}),
            }
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("text",)
    FUNCTION = "compose_prompt"
    CATEGORY = "AnimaArt"

    def _split_prompt_tokens(self, value):
        normalized = str(value or "").replace("\r", ",").replace("\n", ",")
        return [
            part.replace("_raw_:", "", 1).strip()
            for part in normalized.split(",")
            if part.replace("_raw_:", "", 1).strip()
        ]

    def _artist_tokens(self, value):
        tokens = []
        for tag in self._split_prompt_tokens(value):
            if tag.startswith("@"):
                clean = tag[1:].strip()
            elif tag.lower().startswith("by "):
                clean = tag[3:].strip()
            else:
                clean = tag.strip()
            if clean:
                tokens.append(f"@{clean}")
        return tokens

    def _selector_tags(self, artist_tags, character_tags, clothing_tags, pose_tags, background_tags):
        return {
            "artist_tags": artist_tags,
            "character_tags": character_tags,
            "clothing_tags": clothing_tags,
            "pose_tags": pose_tags,
            "background_tags": background_tags,
        }

    def _compose_prompt_text(
        self,
        quality_prompt,
        artist_tags,
        character_tags,
        clothing_tags,
        pose_tags,
        background_tags,
        extra_prompt,
        separator=", ",
    ):
        parts = []
        parts.extend(self._split_prompt_tokens(quality_prompt))
        parts.extend(self._artist_tokens(artist_tags))
        parts.extend(self._split_prompt_tokens(character_tags))
        parts.extend(self._split_prompt_tokens(clothing_tags))
        parts.extend(self._split_prompt_tokens(pose_tags))
        parts.extend(self._split_prompt_tokens(background_tags))
        parts.extend(self._split_prompt_tokens(extra_prompt))

        if not parts:
            return ""

        sep = separator if separator is not None else ", "
        if sep.strip() == "" or sep.strip() == ",":
            return f"{', '.join(parts)}, "
        return sep.join(parts)

    def compose_prompt(
        self,
        quality_prompt,
        artist_tags,
        character_tags,
        clothing_tags,
        pose_tags,
        background_tags,
        extra_prompt,
        separator=", ",
    ):
        selector_tags = self._selector_tags(
            artist_tags,
            character_tags,
            clothing_tags,
            pose_tags,
            background_tags,
        )
        text = self._compose_prompt_text(
            quality_prompt,
            artist_tags,
            character_tags,
            clothing_tags,
            pose_tags,
            background_tags,
            extra_prompt,
            separator,
        )
        return _anima_selector_tags_result(selector_tags, text)


class AnimaPromptPlusClipEncode(AnimaPromptPlus):
    @classmethod
    def INPUT_TYPES(cls):
        prompt_inputs = super().INPUT_TYPES()["required"]
        return {
            "required": {
                "clip": ("CLIP",),
                **prompt_inputs,
            },
            "hidden": {
                "extra_pnginfo": "EXTRA_PNGINFO",
                "unique_id": "UNIQUE_ID",
            },
        }

    RETURN_TYPES = ("CONDITIONING", "STRING")
    RETURN_NAMES = ("positive", "text")
    FUNCTION = "encode_prompt"
    CATEGORY = "AnimaArt"

    def _record_prompt_metadata(self, extra_pnginfo, unique_id, text):
        if not isinstance(extra_pnginfo, dict):
            return
        records = extra_pnginfo.setdefault("anima_prompt", {})
        if not isinstance(records, dict):
            records = {}
            extra_pnginfo["anima_prompt"] = records
        records[str(unique_id or "prompt")] = {"positive": text}

    def encode_prompt(
        self,
        clip,
        quality_prompt,
        artist_tags,
        character_tags,
        clothing_tags,
        pose_tags,
        background_tags,
        extra_prompt,
        separator=", ",
        extra_pnginfo=None,
        unique_id=None,
    ):
        if clip is None:
            raise RuntimeError(
                "ERROR: clip input is invalid: None\n\n"
                "Connect a valid CLIP output from a checkpoint or text encoder loader."
            )

        selector_tags = self._selector_tags(
            artist_tags,
            character_tags,
            clothing_tags,
            pose_tags,
            background_tags,
        )
        resolved_text = self._compose_prompt_text(
            quality_prompt,
            artist_tags,
            character_tags,
            clothing_tags,
            pose_tags,
            background_tags,
            extra_prompt,
            separator,
        )
        conditioning = clip.encode_from_tokens_scheduled(clip.tokenize(resolved_text))
        self._record_prompt_metadata(extra_pnginfo, unique_id, resolved_text)
        return {
            "ui": {"anima_selector_tags": [selector_tags]},
            "result": (conditioning, resolved_text),
        }

class AnimaPromptComposer:
    SELECTION_PROPERTY = "anima_prompt_composer_selection"
    SELECTION_SECTIONS = (
        "style_quality",
        "artist",
        "character",
        "clothing",
        "pose",
        "background",
    )

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "enable_style_quality": ("BOOLEAN", {"default": True}),
                "enable_artist": ("BOOLEAN", {"default": True}),
                "enable_character": ("BOOLEAN", {"default": True}),
                "enable_clothing": ("BOOLEAN", {"default": True}),
                "enable_pose": ("BOOLEAN", {"default": True}),
                "enable_background": ("BOOLEAN", {"default": True}),
                "character_detail": (["trigger", "trigger_tags"], {"default": "trigger"}),
                "seed": ("INT", {"default": -1, "min": -1, "max": 2147483647}),
                "artist_count": ("INT", {"default": 1, "min": 0, "max": 20}),
                "preview_collapsed": ("BOOLEAN", {"default": False}),
                "resolved_prompt": ("STRING", {"multiline": True, "default": ""}),
            },
            "hidden": {
                "prompt": "PROMPT",
                "extra_pnginfo": "EXTRA_PNGINFO",
                "unique_id": "UNIQUE_ID",
            }
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("text",)
    FUNCTION = "compose_prompt"
    CATEGORY = "AnimaArt"
    _data_cache = {}

    @classmethod
    def IS_CHANGED(cls, *args, **kwargs):
        import hashlib
        import json
        import time

        try:
            seed = int(kwargs.get("seed", -1))
        except Exception:
            seed = -1
        if seed < 0:
            return time.time()

        cache_kwargs = {key: value for key, value in kwargs.items() if key not in ("preview_collapsed", "resolved_prompt")}
        payload = json.dumps(cache_kwargs, ensure_ascii=False, sort_keys=True, default=str)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @classmethod
    def _load_js_array(cls, filename):
        import json
        import os

        if filename in cls._data_cache:
            return cls._data_cache[filename]
        path = os.path.join(os.path.dirname(__file__), "js", filename)
        try:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
            start = content.index("[")
            data, _ = json.JSONDecoder().raw_decode(content[start:])
        except Exception as e:
            print(f"[Anima Tools] Failed to load prompt composer data {filename}: {e}")
            return []
        if not isinstance(data, list):
            return []
        cls._data_cache[filename] = [item for item in data if isinstance(item, dict)]
        return cls._data_cache[filename]

    @classmethod
    def _load_json_object(cls, filename):
        import json
        import os

        cache_key = f"json:{filename}"
        if cache_key in cls._data_cache:
            return cls._data_cache[cache_key]
        path = os.path.join(os.path.dirname(__file__), "js", filename)
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            print(f"[Anima Tools] Failed to load prompt composer data {filename}: {e}")
            data = {}
        if not isinstance(data, dict):
            data = {}
        cls._data_cache[cache_key] = data
        return data

    def _split_prompt_tokens(self, value):
        if isinstance(value, list):
            parts = []
            for item in value:
                parts.extend(self._split_prompt_tokens(item))
            return parts
        return [
            part.replace("_raw_:", "", 1).strip()
            for part in str(value or "").split(",")
            if part.replace("_raw_:", "", 1).strip()
        ]

    def _normalize_text(self, value):
        return " ".join(str(value or "").strip().lower().replace("_", " ").split())

    def _official_character_key(self, item):
        return f"{self._normalize_text(item.get('name'))}||{self._normalize_text(item.get('copyright'))}"

    def _pick_items(self, data, count, rng):
        count = max(0, int(count or 0))
        if count <= 0 or not data:
            return []
        if count >= len(data):
            shuffled = data[:]
            rng.shuffle(shuffled)
            return shuffled
        return rng.sample(data, count)

    def _artist_entry(self, item):
        name = str(item.get("name") or "").strip()
        if not name:
            return None
        partition = item.get("p") or 1
        item_id = item.get("id") or ""
        return {
            "section": "artist",
            "key": f"artist:{item_id or name}",
            "title": name,
            "subtitle": f"{item.get('post_count', 0)} works" if item.get("post_count") else "",
            "preview": item.get('preview', '') if item.get('shared') else (f"https://fastly.jsdelivr.net/gh/ThetaCursed/Anima-Assets@main/images/{partition}/{item_id}.webp" if item_id else ""),
            "prompt_parts": self._split_prompt_tokens(item['tags']) if item.get('shared') else [f"@{name}"],
        }

    def _character_entry(self, item, official_data):
        import urllib.parse

        name = str(item.get("name") or "").strip()
        if not name:
            return None
        copyright = str(item.get("copyright") or "").strip()
        official = official_data.get(self._official_character_key(item)) or {}
        trigger = item.get('trigger') if item.get('shared') else official.get("trigger") or (f"{name}, {copyright}" if copyright else name)
        tags = self._split_prompt_tokens(item.get('detail_tags') if item.get('shared') else official.get("tags"))
        if not tags and not item.get('shared'):
            fallback = []
            if item.get("gender"):
                fallback.append(item.get("gender"))
            if item.get("hair"):
                fallback.append(f"{item.get('hair')} hair")
            if item.get("eye"):
                fallback.append(f"{item.get('eye')} eyes")
            tags = fallback
        raw_name = f"{name}, {copyright}" if copyright else name
        return {
            "section": "character",
            "key": f"character:{name}||{copyright}",
            "title": name,
            "subtitle": copyright,
            "preview": item.get('preview', '') if item.get('shared') else f"https://blobs.animadex.net/Outputs/thumbs/{urllib.parse.quote(raw_name, safe='')}.webp",
            "trigger_parts": self._split_prompt_tokens(trigger),
            "tag_parts": tags,
        }

    def _clothing_entry(self, item):
        item_id = str(item.get("id") or "").strip()
        title = str(item.get("name_zh") or item.get("name") or "").strip()
        if not title:
            return None
        return {
            "section": "clothing",
            "key": f"clothing:{item_id or title}",
            "title": title,
            "subtitle": str(item.get("name") or ""),
            "preview": str(item.get("preview") or ""),
            "prompt_parts": self._split_prompt_tokens(item.get("tags")),
        }

    def _background_entry(self, item):
        item_id = str(item.get("id") or "").strip()
        title = str(item.get("name_zh") or item.get("name") or "").strip()
        if not title:
            return None
        return {
            "section": "background",
            "key": f"background:{item_id or title}",
            "title": title,
            "subtitle": str(item.get("name") or ""),
            "preview": str(item.get("preview") or ""),
            "prompt_parts": self._split_prompt_tokens(item.get("tags")),
        }

    def _pose_entry(self, item):
        item_id = str(item.get("id") or "").strip()
        title = str(item.get("name_zh") or item.get("name") or "").strip()
        if not title:
            return None
        return {
            "section": "pose",
            "key": f"pose:{item_id or title}",
            "title": title,
            "subtitle": str(item.get("name") or ""),
            "preview": str(item.get("preview") or ""),
            "prompt_parts": self._split_prompt_tokens(item.get("tags")),
        }

    def _style_quality_entry(self, item):
        item_id = str(item.get("id") or "").strip()
        title = str(item.get("name_zh") or item.get("name") or "").strip()
        if not title:
            return None
        return {
            "section": "style_quality",
            "key": f"style_quality:{item_id or title}",
            "title": title,
            "subtitle": str(item.get("source_category") or ""),
            "preview": str(item.get("preview") or ""),
            "prompt_parts": self._split_prompt_tokens(item.get("tags")),
        }

    def _entry_parts(self, entry, section, character_detail):
        if section == "character":
            parts = self._split_prompt_tokens(entry.get("trigger_parts"))
            if character_detail == "trigger_tags":
                parts.extend(self._split_prompt_tokens(entry.get("tag_parts")))
            return parts
        return self._split_prompt_tokens(entry.get("prompt_parts"))

    def _append_parts(self, output_parts, seen, entries, section, character_detail):
        for entry in entries:
            for part in self._entry_parts(entry, section, character_detail):
                key = part.lower()
                if key and key not in seen:
                    seen.add(key)
                    output_parts.append(part)

    def _workflow_widget_index(self, name):
        order = [
            "enable_style_quality",
            "enable_artist",
            "enable_character",
            "enable_clothing",
            "enable_pose",
            "enable_background",
            "character_detail",
            "seed",
            "seed_control_after_generate",
            "artist_count",
            "preview_collapsed",
            "resolved_prompt",
        ]
        try:
            return order.index(name)
        except ValueError:
            return -1

    def _set_workflow_widget_value(self, workflow_node, widget_name, value):
        if not isinstance(workflow_node, dict):
            return
        widgets_values = workflow_node.get("widgets_values")
        if isinstance(widgets_values, list):
            index = self._workflow_widget_index(widget_name)
            if index < 0:
                return
            while len(widgets_values) <= index:
                widgets_values.append("")
            widgets_values[index] = value
        elif isinstance(widgets_values, dict):
            widgets_values[widget_name] = value

    def _find_workflow_node(self, workflow, unique_id):
        if not isinstance(workflow, dict):
            return None
        nodes = workflow.get("nodes")
        if not isinstance(nodes, list):
            return None
        unique_id_text = str(unique_id)
        for node in nodes:
            if not isinstance(node, dict):
                continue
            node_id = node.get("id")
            if str(node_id) == unique_id_text:
                return node
        return None

    def _parse_selection_payload(self, value):
        import json

        if isinstance(value, dict):
            return value
        text = str(value or "").strip()
        if not text.startswith("{"):
            return None
        try:
            payload = json.loads(text)
        except Exception:
            return None
        return payload if isinstance(payload, dict) else None

    def _empty_selected(self, resolved_prompt=""):
        selected = {section: [] for section in self.SELECTION_SECTIONS}
        selected["_resolved_prompt"] = resolved_prompt
        return selected

    def _normalize_selected(self, selected, resolved_prompt=""):
        if not isinstance(selected, dict):
            return self._empty_selected(resolved_prompt)

        normalized = {}
        for section in self.SELECTION_SECTIONS:
            entries = selected.get(section)
            normalized[section] = entries if isinstance(entries, list) else []
        normalized["_resolved_prompt"] = resolved_prompt or str(selected.get("_resolved_prompt") or "")
        return normalized

    def _selection_from_workflow(self, extra_pnginfo, unique_id, resolved_prompt=""):
        if not isinstance(extra_pnginfo, dict):
            return None
        workflow_node = self._find_workflow_node(extra_pnginfo.get("workflow"), unique_id)
        properties = workflow_node.get("properties") if isinstance(workflow_node, dict) else None
        if not isinstance(properties, dict):
            return None
        selected = self._parse_selection_payload(properties.get(self.SELECTION_PROPERTY))
        if not selected:
            return None
        return self._normalize_selected(selected, resolved_prompt)

    def _record_resolved_prompt(self, prompt, extra_pnginfo, unique_id, resolved_prompt, selected):
        unique_id_text = str(unique_id) if unique_id is not None else ""
        selected = self._normalize_selected(selected, resolved_prompt)

        if isinstance(prompt, dict) and unique_id_text:
            prompt_node = prompt.get(unique_id_text) or prompt.get(unique_id)
            if isinstance(prompt_node, dict):
                inputs = prompt_node.setdefault("inputs", {})
                if isinstance(inputs, dict):
                    inputs["resolved_prompt"] = resolved_prompt

        if not isinstance(extra_pnginfo, dict):
            return

        record = {
            "node_id": unique_id_text,
            "resolved_prompt": resolved_prompt,
            "selected": selected,
        }
        records = extra_pnginfo.setdefault("anima_prompt_composer", {})
        if not isinstance(records, dict):
            records = {}
            extra_pnginfo["anima_prompt_composer"] = records
        records[unique_id_text or "last"] = record

        workflow = extra_pnginfo.get("workflow")
        workflow_node = self._find_workflow_node(workflow, unique_id_text)
        if workflow_node:
            self._set_workflow_widget_value(workflow_node, "resolved_prompt", resolved_prompt)
            properties = workflow_node.get("properties")
            if not isinstance(properties, dict):
                properties = {}
                workflow_node["properties"] = properties
            properties[self.SELECTION_PROPERTY] = selected

    def _truthy(self, value, default=False):
        if isinstance(value, bool):
            return value
        if value is None:
            return default
        if isinstance(value, (int, float)):
            return value != 0
        value_text = str(value).strip().lower()
        if value_text in ("true", "1", "yes", "on"):
            return True
        if value_text in ("false", "0", "no", "off"):
            return False
        return default

    def _int_value(self, value, default=0):
        try:
            return int(value)
        except Exception:
            return default

    def _resolve_prompt_data(
        self,
        enable_style_quality,
        enable_artist,
        enable_character,
        enable_clothing,
        enable_pose,
        enable_background,
        character_detail,
        seed,
        artist_count,
    ):
        import random

        def current_pool(kind):
            return [item for item in get_shared_prompt_payload(kind).get('items', []) if _shared_random_eligible(item)]
        artist_data = current_pool('artist') if self._truthy(enable_artist, True) else []
        character_data = current_pool('character') if self._truthy(enable_character, True) else []
        clothing_data = current_pool('clothing') if self._truthy(enable_clothing, True) else []
        background_data = current_pool('background') if self._truthy(enable_background, True) else []
        pose_data = current_pool('pose') if self._truthy(enable_pose, True) else []
        official_data = self._load_json_object("character_official_data.json")

        seed_value = self._int_value(seed, -1)
        rng = random.SystemRandom() if seed_value < 0 else random.Random(seed_value)

        artist_items = self._pick_items(artist_data, self._int_value(artist_count, 1), rng) if self._truthy(enable_artist, True) else []
        character_items = self._pick_items(character_data, 1, rng) if self._truthy(enable_character, True) else []
        clothing_items = self._pick_items(clothing_data, 1, rng) if self._truthy(enable_clothing, True) else []
        background_items = self._pick_items(background_data, 1, rng) if self._truthy(enable_background, True) else []
        pose_items = self._pick_items(pose_data, 1, rng) if self._truthy(enable_pose, True) else []

        style_quality_items = []
        if self._truthy(enable_style_quality, True):
            try:
                style_quality_payload = get_shared_prompt_payload("style_quality")
                style_quality_data = [item for item in style_quality_payload.get("items", [])
                    if _shared_random_eligible(item)]
                if isinstance(style_quality_data, list):
                    style_quality_items = self._pick_items(style_quality_data, 1, rng)
            except Exception as error:
                print(f"[Anima Tools] Failed to load style/quality prompt data: {error}")

        selected = {
            "style_quality": [
                entry
                for entry in (
                    self._style_quality_entry(item)
                    for item in style_quality_items
                )
                if entry
            ],
            "artist": [entry for entry in (self._artist_entry(item) for item in artist_items) if entry],
            "character": [entry for entry in (self._character_entry(item, official_data) for item in character_items) if entry],
            "clothing": [entry for entry in (self._clothing_entry(item) for item in clothing_items) if entry],
            "pose": [entry for entry in (self._pose_entry(item) for item in pose_items) if entry],
            "background": [entry for entry in (self._background_entry(item) for item in background_items) if entry],
        }

        output_parts = []
        seen = set()
        self._append_parts(output_parts, seen, selected["style_quality"], "style_quality", character_detail)
        self._append_parts(output_parts, seen, selected["artist"], "artist", character_detail)
        self._append_parts(output_parts, seen, selected["character"], "character", character_detail)
        self._append_parts(output_parts, seen, selected["clothing"], "clothing", character_detail)
        self._append_parts(output_parts, seen, selected["pose"], "pose", character_detail)
        self._append_parts(output_parts, seen, selected["background"], "background", character_detail)

        text = ", ".join(output_parts)
        if text:
            text += ", "

        selected["_resolved_prompt"] = text
        return selected, text

    def _extract_resolved_prompt_text(self, value):
        text = str(value or "")
        payload = self._parse_selection_payload(text)
        if not payload:
            return text
        if isinstance(payload, dict) and isinstance(payload.get("_resolved_prompt"), str):
            return payload.get("_resolved_prompt") or ""
        return text

    def compose_prompt(
        self,
        enable_style_quality,
        enable_artist,
        enable_character,
        enable_clothing,
        enable_pose,
        enable_background,
        character_detail,
        seed,
        artist_count,
        preview_collapsed,
        resolved_prompt="",
        prompt=None,
        extra_pnginfo=None,
        unique_id=None,
    ):
        text = self._extract_resolved_prompt_text(resolved_prompt)
        if text:
            selected = (
                self._selection_from_workflow(extra_pnginfo, unique_id, text)
                or self._normalize_selected(self._parse_selection_payload(resolved_prompt), text)
            )
        else:
            selected, text = self._resolve_prompt_data(
                enable_style_quality,
                enable_artist,
                enable_character,
                enable_clothing,
                enable_pose,
                enable_background,
                character_detail,
                seed,
                artist_count,
            )
        selected["_resolved_prompt"] = text
        self._record_resolved_prompt(prompt, extra_pnginfo, unique_id, text, selected)

        return {"ui": {"anima_prompt_composer": [selected], "resolved_prompt": [text]}, "result": (text,)}

class AnimaMultiLoraLoader:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "model": ("MODEL",),
                "lora_list_json": ("STRING", {"default": "[]", "multiline": True}),
            }
        }

    RETURN_TYPES = ("MODEL",)
    RETURN_NAMES = ("MODEL",)
    FUNCTION = "load_loras"
    CATEGORY = "AnimaArt"

    def load_loras(self, model, lora_list_json):
        import json
        import comfy.sd
        import comfy.utils
        import folder_paths
        from .anima_lora_api import get_lora_save_dir
        
        try:
            loras = json.loads(lora_list_json)
        except Exception as e:
            print(f"[Anima Tools] Error parsing lora_list_json: {e}")
            loras = []
            
        current_model = model
        
        for lora_entry in loras:
            if not lora_entry.get("enabled", True):
                continue
                
            lora_name = lora_entry.get("name")
            lora_base_model = lora_entry.get("base_model", "Anima")
            strength_model = float(lora_entry.get("strength_model", 1.0))
            
            if not lora_name:
                continue
                
            # 查找 LoRA 文件路径
            lora_path = folder_paths.get_full_path("loras", lora_name)
            
            if not lora_path:
                custom_dir = get_lora_save_dir(base_model=lora_base_model)
                candidate = os.path.join(custom_dir, lora_name)
                if os.path.isfile(candidate):
                    lora_path = candidate
                else:
                    candidate_rel = os.path.join(custom_dir, lora_name.replace("/", os.sep))
                    if os.path.isfile(candidate_rel):
                        lora_path = candidate_rel
            
            if not lora_path:
                # 模糊匹配
                found_match = False
                for system_lora in folder_paths.get_filename_list("loras"):
                    if os.path.basename(system_lora) == os.path.basename(lora_name):
                        lora_path = folder_paths.get_full_path("loras", system_lora)
                        found_match = True
                        break
                if not found_match:
                    print(f"[Anima Tools] LoRA file not found: {lora_name}, skipping.")
                    continue
                    
            try:
                print(f"[Anima Tools] Applying LoRA: {lora_name} -> Model Strength: {strength_model}")
                lora_data = comfy.utils.load_torch_file(lora_path, safe_load=True)
                current_model, _ = comfy.sd.load_lora_for_models(
                    current_model, None, lora_data, strength_model, 0.0
                )
            except Exception as e:
                print(f"[Anima Tools] Failed to load LoRA {lora_name}: {e}")
                
        return (current_model,)


NODE_CLASS_MAPPINGS = {
    "AnimaArtistTagSelector": AnimaArtistTagSelector,
    "AnimaArtistTagSelectorPlus": AnimaArtistTagSelectorPlus,
    "AnimaCharacterTagSelector": AnimaCharacterTagSelector,
    "AnimaCharacterTagSelectorPlus": AnimaCharacterTagSelectorPlus,
    "AnimaClothingTagSelector": AnimaClothingTagSelector,
    "AnimaClothingTagSelectorPlus": AnimaClothingTagSelectorPlus,
    "AnimaBackgroundTagSelector": AnimaBackgroundTagSelector,
    "AnimaBackgroundTagSelectorPlus": AnimaBackgroundTagSelectorPlus,
    "AnimaPoseTagSelector": AnimaPoseTagSelector,
    "AnimaPoseTagSelectorPlus": AnimaPoseTagSelectorPlus,
    "AnimaStyleQualitySelector": AnimaStyleQualitySelector,
    "AnimaStyleQualitySelectorPlus": AnimaStyleQualitySelectorPlus,
    "AnimaPromptPlus": AnimaPromptPlus,
    "AnimaPromptPlusClipEncode": AnimaPromptPlusClipEncode,
    "AnimaPromptComposer": AnimaPromptComposer,
    "AnimaMultiLoraLoader": AnimaMultiLoraLoader
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "AnimaArtistTagSelector": "Anima Artist Tag Selector",
    "AnimaArtistTagSelectorPlus": "Anima Artist Tag Selector+",
    "AnimaCharacterTagSelector": "Anima Character Tag Selector",
    "AnimaCharacterTagSelectorPlus": "Anima Character Tag Selector+",
    "AnimaClothingTagSelector": "Anima Clothing Tag Selector",
    "AnimaClothingTagSelectorPlus": "Anima Clothing Tag Selector+",
    "AnimaBackgroundTagSelector": "Anima Background Tag Selector",
    "AnimaBackgroundTagSelectorPlus": "Anima Background Tag Selector+",
    "AnimaPoseTagSelector": "Anima Pose Tag Selector",
    "AnimaPoseTagSelectorPlus": "Anima Pose Tag Selector+",
    "AnimaStyleQualitySelector": "Anima 画风/质量选择器",
    "AnimaStyleQualitySelectorPlus": "Anima 画风/质量选择器+",
    "AnimaPromptPlus": "Anima Prompt",
    "AnimaPromptPlusClipEncode": "Anima Prompt Plus",
    "AnimaPromptComposer": "Anima Prompt Random Draw",
    "AnimaMultiLoraLoader": "Anima Multi LoRA Loader"
}

# ----------------- 后端持久化 API 路由 -----------------
import folder_paths
from server import PromptServer
from aiohttp import web
import asyncio
import copy
import gzip
import json
import os
import hashlib
import re
import threading
import time
import urllib.parse
import urllib.request
from io import BytesIO
from pathlib import Path
try:
    from PIL import Image
except ImportError:
    Image = None

SELECTOR_RANDOM_PROPERTY = "anima_selector_random"

SELECTOR_RANDOM_INPUTS = {
    "AnimaArtistTagSelector": {"artist": "artist_tags"},
    "AnimaArtistTagSelectorPlus": {"artist": "artist_tags"},
    "AnimaCharacterTagSelector": {"character": "character_tags"},
    "AnimaCharacterTagSelectorPlus": {"character": "character_tags"},
    "AnimaClothingTagSelector": {"clothing": "clothing_tags"},
    "AnimaClothingTagSelectorPlus": {"clothing": "clothing_tags"},
    "AnimaBackgroundTagSelector": {"background": "background_tags"},
    "AnimaBackgroundTagSelectorPlus": {"background": "background_tags"},
    "AnimaPoseTagSelector": {"pose": "pose_tags"},
    "AnimaPoseTagSelectorPlus": {"pose": "pose_tags"},
    "AnimaStyleQualitySelector": {"style_quality": "style_quality_tags"},
    "AnimaStyleQualitySelectorPlus": {"style_quality": "style_quality_tags"},
    "AnimaPromptPlus": {
        "artist": "artist_tags",
        "character": "character_tags",
        "clothing": "clothing_tags",
        "pose": "pose_tags",
        "background": "background_tags",
    },
    "AnimaPromptPlusClipEncode": {
        "artist": "artist_tags",
        "character": "character_tags",
        "clothing": "clothing_tags",
        "pose": "pose_tags",
        "background": "background_tags",
    },
}

SELECTOR_WIDGET_ORDERS = {
    "AnimaArtistTagSelector": ["artist_tags", "mode"],
    "AnimaArtistTagSelectorPlus": ["artist_tags", "extra_text", "separator"],
    "AnimaCharacterTagSelector": ["character_tags", "mode"],
    "AnimaCharacterTagSelectorPlus": ["character_tags", "extra_text", "separator"],
    "AnimaClothingTagSelector": ["clothing_tags", "mode"],
    "AnimaClothingTagSelectorPlus": ["clothing_tags", "extra_text", "separator"],
    "AnimaBackgroundTagSelector": ["background_tags", "mode"],
    "AnimaBackgroundTagSelectorPlus": ["background_tags", "extra_text", "separator"],
    "AnimaPoseTagSelector": ["pose_tags", "mode"],
    "AnimaPoseTagSelectorPlus": ["pose_tags", "extra_text", "separator"],
    "AnimaStyleQualitySelector": ["style_quality_tags", "mode"],
    "AnimaStyleQualitySelectorPlus": ["style_quality_tags", "extra_text", "separator"],
    "AnimaPromptPlus": [
        "quality_prompt",
        "artist_tags",
        "character_tags",
        "clothing_tags",
        "pose_tags",
        "background_tags",
        "extra_prompt",
        "separator",
    ],
    "AnimaPromptPlusClipEncode": [
        "quality_prompt",
        "artist_tags",
        "character_tags",
        "clothing_tags",
        "pose_tags",
        "background_tags",
        "extra_prompt",
        "separator",
    ],
}

def _selector_random_state(workflow_node):
    if not isinstance(workflow_node, dict):
        return {}
    properties = workflow_node.get("properties")
    if not isinstance(properties, dict):
        return {}
    state = properties.get(SELECTOR_RANDOM_PROPERTY)
    return state if isinstance(state, dict) else {}

def _selector_random_enabled(workflow_node, section):
    value = _selector_random_state(workflow_node).get(section)
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    return str(value or "").strip().lower() in ("true", "1", "yes", "on")

def _set_selector_workflow_widget_value(workflow_node, class_type, input_name, value):
    if not isinstance(workflow_node, dict):
        return
    widgets_values = workflow_node.get("widgets_values")
    if isinstance(widgets_values, dict):
        widgets_values[input_name] = value
        return
    if not isinstance(widgets_values, list):
        return
    order = SELECTOR_WIDGET_ORDERS.get(class_type) or []
    try:
        index = order.index(input_name)
    except ValueError:
        return
    while len(widgets_values) <= index:
        widgets_values.append("")
    widgets_values[index] = value

def _shared_random_eligible(item):
    decision = item.get("_semantic", {})
    return (decision.get("disposition") in ("reviewed", "classified")
        and decision.get("random_pool_eligible") is True
        and decision.get("strict_model_pool_eligible") is True
        and decision.get("usage") == "positive"
        and decision.get("content_type") in ("atomic_tag", "fragment"))


def _selector_random_text(composer, section):
    if section == "style_quality":
        import random

        payload = get_shared_prompt_payload("style_quality")
        items = payload.get("items") if isinstance(payload, dict) else []
        if not isinstance(items, list) or not items:
            return "", []
        items = [item for item in items if _shared_random_eligible(item)]
        if not items:
            return "", []
        item = random.SystemRandom().choice(items)
        prompt_parts = composer._split_prompt_tokens(item.get("tags"))
        text = ", ".join(prompt_parts)
        if text:
            text += ", "
        item_id = str(item.get("id") or item.get("name") or "")
        return text, [{
            "section": "style_quality",
            "key": f"style_quality:{item_id}",
            "title": str(item.get("name_zh") or item.get("name") or ""),
            "subtitle": str(item.get("source_category") or ""),
            "preview": str(item.get("preview") or ""),
            "prompt_parts": prompt_parts,
        }]

    selected, text = composer._resolve_prompt_data(
        False,
        section == "artist",
        section == "character",
        section == "clothing",
        section == "pose",
        section == "background",
        "trigger",
        -1,
        1,
    )
    return text, selected.get(section, [])

def _record_selector_random(extra_pnginfo, node_id, class_type, section, input_name, text, selected):
    if not isinstance(extra_pnginfo, dict):
        return
    records = extra_pnginfo.setdefault("anima_selector_random", {})
    if not isinstance(records, dict):
        records = {}
        extra_pnginfo["anima_selector_random"] = records
    records[f"{node_id}:{section}"] = {
        "node_id": str(node_id),
        "class_type": class_type,
        "section": section,
        "input": input_name,
        "text": text,
        "selected": selected,
    }

def _resolve_anima_selector_random_nodes(prompt, extra_pnginfo, composer):
    workflow = extra_pnginfo.get("workflow") if isinstance(extra_pnginfo, dict) else None
    for node_id, node in list(prompt.items()):
        if not isinstance(node, dict):
            continue
        class_type = node.get("class_type")
        section_inputs = SELECTOR_RANDOM_INPUTS.get(class_type)
        if not section_inputs:
            continue

        workflow_node = composer._find_workflow_node(workflow, node_id)
        if not workflow_node:
            continue
        inputs = node.setdefault("inputs", {})
        if not isinstance(inputs, dict):
            continue

        for section, input_name in section_inputs.items():
            if not _selector_random_enabled(workflow_node, section):
                continue
            current_value = inputs.get(input_name)
            if isinstance(current_value, list):
                continue
            text, selected = _selector_random_text(composer, section)
            if not text:
                continue
            inputs[input_name] = text
            _set_selector_workflow_widget_value(workflow_node, class_type, input_name, text)
            _record_selector_random(extra_pnginfo, node_id, class_type, section, input_name, text, selected)

def _resolve_anima_prompt_plus_clip_nodes(prompt, extra_pnginfo, prompt_plus):
    updates = {}
    for node_id, node in list(prompt.items()):
        if not isinstance(node, dict) or node.get("class_type") != "AnimaPromptPlusClipEncode":
            continue
        inputs = node.setdefault("inputs", {})
        if not isinstance(inputs, dict):
            continue

        resolved_text = prompt_plus._compose_prompt_text(
            inputs.get("quality_prompt", ""),
            inputs.get("artist_tags", ""),
            inputs.get("character_tags", ""),
            inputs.get("clothing_tags", ""),
            inputs.get("pose_tags", ""),
            inputs.get("background_tags", ""),
            inputs.get("extra_prompt", ""),
            inputs.get("separator", ", "),
        )
        inputs["text"] = resolved_text

        if isinstance(extra_pnginfo, dict):
            records = extra_pnginfo.setdefault("anima_prompt", {})
            if not isinstance(records, dict):
                records = {}
                extra_pnginfo["anima_prompt"] = records
            records[str(node_id)] = {"positive": resolved_text}

        updates[str(node_id)] = {
            "quality_prompt": inputs.get("quality_prompt", ""),
            "artist_tags": inputs.get("artist_tags", ""),
            "character_tags": inputs.get("character_tags", ""),
            "clothing_tags": inputs.get("clothing_tags", ""),
            "pose_tags": inputs.get("pose_tags", ""),
            "background_tags": inputs.get("background_tags", ""),
            "extra_prompt": inputs.get("extra_prompt", ""),
            "separator": inputs.get("separator", ", "),
        }
    return updates

def _install_anima_prompt_composer_queue_resolver():
    if getattr(PromptServer.instance, "_anima_prompt_composer_resolver_installed", False):
        return
    PromptServer.instance._anima_prompt_composer_resolver_installed = True

    def resolve_anima_prompt_composer_nodes(json_data):
        try:
            prompt = json_data.get("prompt")
            if not isinstance(prompt, dict):
                return json_data

            extra_data = json_data.setdefault("extra_data", {})
            if not isinstance(extra_data, dict):
                return json_data
            extra_pnginfo = extra_data.setdefault("extra_pnginfo", {})
            if not isinstance(extra_pnginfo, dict):
                return json_data

            composer = AnimaPromptComposer()
            _resolve_anima_selector_random_nodes(prompt, extra_pnginfo, composer)
            prompt_plus_updates = _resolve_anima_prompt_plus_clip_nodes(
                prompt,
                extra_pnginfo,
                AnimaPromptPlus(),
            )
            if prompt_plus_updates:
                PromptServer.instance.send_sync(
                    "anima.prompt_plus_resolved",
                    {"nodes": prompt_plus_updates},
                    json_data.get("client_id"),
                )

            for node_id, node in list(prompt.items()):
                if not isinstance(node, dict) or node.get("class_type") != "AnimaPromptComposer":
                    continue
                inputs = node.setdefault("inputs", {})
                if not isinstance(inputs, dict):
                    continue

                selected, resolved_prompt = composer._resolve_prompt_data(
                    inputs.get("enable_style_quality", True),
                    inputs.get("enable_artist", True),
                    inputs.get("enable_character", True),
                    inputs.get("enable_clothing", True),
                    inputs.get("enable_pose", True),
                    inputs.get("enable_background", True),
                    inputs.get("character_detail", "trigger"),
                    inputs.get("seed", -1),
                    inputs.get("artist_count", 1),
                )
                inputs["resolved_prompt"] = resolved_prompt
                composer._record_resolved_prompt(
                    prompt,
                    extra_pnginfo,
                    node_id,
                    resolved_prompt,
                    selected,
                )
        except Exception as e:
            print(f"[Anima Tools] Failed to resolve random prompt metadata before queue: {e}")
        return json_data

    PromptServer.instance.add_on_prompt_handler(resolve_anima_prompt_composer_nodes)

_install_anima_prompt_composer_queue_resolver()

@PromptServer.instance.routes.get("/anima-tools/favorites")
async def get_favorites_api(request):
    owner = PromptServer.instance.weilin_selector_favorites
    return await owner[0](request)


@PromptServer.instance.routes.post("/anima-tools/favorites")
async def save_favorites_api(request):
    owner = PromptServer.instance.weilin_selector_favorites
    return await owner[1](request)


_SHARED_PROMPT_KINDS = (
    "artist",
    "pose",
    "background",
    "clothing",
    "character",
    "style_quality",
)
_SHARED_PROMPT_PARENT_FILTER_PREFIX = "shared-parent:"
_SHARED_PROMPT_CHILD_FILTER_PREFIX = "shared-child:"
_SHARED_PROMPT_PATH_FILTER_PREFIX = "shared-path:"
_SHARED_PROMPT_CATEGORY_SEPARATOR = "\x1f"
_SHARED_PROMPT_SOURCE_DIRECTORY_PATH_STRATEGY = (
    "source_directory_without_codex_root"
)
_SHARED_PROMPT_TAXONOMY_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "data",
    "weilin_category_taxonomy.json",
)
_SHARED_PROMPT_DATA_LOCK = threading.Lock()
_SHARED_PROMPT_DATA_CACHE = {
    "path": "",
    "mtime_ns": 0,
    "size": 0,
    "source_data": None,
    "source_sha256": "",
    "taxonomy_path": "",
    "taxonomy_mtime_ns": 0,
    "payloads": {},
}


def _normalize_shared_prompt_rule(value: str) -> str:
    return re.sub(r"\s+", "", str(value or "").replace("／", "/")).casefold()


def _parse_shared_prompt_targets(raw_targets) -> list:
    if not isinstance(raw_targets, list):
        return []
    if raw_targets and all(isinstance(value, str) for value in raw_targets):
        raw_targets = [raw_targets]
    targets = []
    for raw_target in raw_targets:
        if not isinstance(raw_target, list) or len(raw_target) < 2:
            continue
        kind = str(raw_target[0] or "").strip().casefold()
        path_parts = [
            str(part or "").replace("／", "/").strip()
            for part in raw_target[1:]
            if str(part or "").strip()
        ]
        if kind not in _SHARED_PROMPT_KINDS or not path_parts:
            continue
        targets.append({
            "kind": kind,
            "levels": [f"WeiLin / {path_parts[0]}", *path_parts[1:]],
        })
    return targets


def _load_shared_prompt_taxonomy(taxonomy_path: str = "") -> dict:
    path = taxonomy_path or _SHARED_PROMPT_TAXONOMY_PATH
    with open(path, "r", encoding="utf-8") as f:
        source = json.load(f)
    if source.get("schema_version") != 1:
        raise ValueError("Unsupported WeiLin taxonomy schema")

    by_id = {}
    by_name = {}
    mappings = source.get("mappings")
    if not isinstance(mappings, dict):
        raise ValueError("WeiLin taxonomy mappings must be an object")

    route_targets = {}
    for route_name, raw_targets in (source.get("routes") or {}).items():
        targets = _parse_shared_prompt_targets(raw_targets)
        if targets:
            route_targets[str(route_name)] = targets

    for category_id, raw_mapping in mappings.items():
        if not isinstance(raw_mapping, dict):
            continue
        source_name = str(raw_mapping.get("source_name") or "").strip()
        targets = _parse_shared_prompt_targets(raw_mapping.get("targets") or [])
        for route_name in raw_mapping.get("routes") or []:
            targets.extend(route_targets.get(str(route_name), []))
        exclude_reason = str(raw_mapping.get("exclude_reason") or "").strip()
        mode = str(raw_mapping.get("mode") or "inherit").strip().casefold()
        if mode not in {"inherit", "prompt_override_only"}:
            mode = "inherit"
        if not source_name or (
            not targets
            and not exclude_reason
            and mode != "prompt_override_only"
        ):
            continue
        entry = {
            "category_id": str(category_id),
            "source_name": source_name,
            "targets": targets,
            "exclude_reason": exclude_reason,
            "mode": mode,
        }
        by_id[str(category_id)] = entry
        normalized_name = _normalize_shared_prompt_rule(source_name)
        existing = by_name.get(normalized_name)
        if (
            existing is None
            or (
                existing["targets"] == targets
                and existing["exclude_reason"] == exclude_reason
                and existing["mode"] == mode
            )
        ):
            by_name[normalized_name] = entry
        else:
            by_name[normalized_name] = False

    prefix_contracts = []
    for prefix, raw_contract in (source.get("prefix_contracts") or {}).items():
        if not isinstance(raw_contract, dict):
            continue
        kind = str(raw_contract.get("kind") or "").strip().casefold()
        path_parts = [
            str(part or "").replace("／", "/").strip()
            for part in raw_contract.get("path") or []
            if str(part or "").strip()
        ]
        if kind not in _SHARED_PROMPT_KINDS or not path_parts:
            continue
        prefix_parts = [
            _normalize_shared_prompt_rule(part)
            for part in str(prefix).split("/")
            if str(part).strip()
        ]
        if not prefix_parts:
            continue
        prefix_contracts.append({
            "prefix_parts": prefix_parts,
            "kind": kind,
            "levels": [f"WeiLin / {path_parts[0]}", *path_parts[1:]],
        })
    prefix_contracts.sort(
        key=lambda contract: len(contract["prefix_parts"]),
        reverse=True,
    )

    prompt_routes = {}
    for prompt_id, raw_routes in (source.get("prompt_routes") or {}).items():
        route_names = raw_routes if isinstance(raw_routes, list) else [raw_routes]
        targets = []
        for route_name in route_names:
            targets.extend(route_targets.get(str(route_name), []))
        if targets:
            prompt_routes[str(prompt_id)] = targets
    prompt_hashes = {
        str(prompt_id): str(semantic_hash)
        for prompt_id, semantic_hash in (source.get("prompt_hashes") or {}).items()
        if str(semantic_hash)
    }
    prompt_route_categories = {
        str(prompt_id): str(category_id)
        for prompt_id, category_id in (
            source.get("prompt_route_categories") or {}
        ).items()
        if str(category_id)
    }

    quarantined_prompts = {
        str(prompt_id): str(reason or "safety")
        for prompt_id, reason in (source.get("quarantined_prompts") or {}).items()
    }
    path_strategy = str(source.get("path_strategy") or "").strip().casefold()
    if path_strategy != _SHARED_PROMPT_SOURCE_DIRECTORY_PATH_STRATEGY:
        path_strategy = ""

    return {
        "version": str(source.get("taxonomy_version") or ""),
        "path_strategy": path_strategy,
        "source_sha256": str(source.get("source_sha256") or "").casefold(),
        "path": path,
        "mapping_count": len(by_id),
        "by_id": by_id,
        "by_name": by_name,
        "prefix_contracts": prefix_contracts,
        "route_targets": route_targets,
        "prompt_routes": prompt_routes,
        "prompt_hashes": prompt_hashes,
        "prompt_route_categories": prompt_route_categories,
        "quarantined_prompts": quarantined_prompts,
    }


def _shared_prompt_targets(category: dict, taxonomy: dict) -> tuple:
    category_id = str(category.get("id") or "").strip()
    category_name = str(category.get("name") or "").strip()
    source_parts = [
        part.strip()
        for part in category_name.replace("／", "/").split("/")
        if part.strip()
    ]
    normalized_parts = [
        _normalize_shared_prompt_rule(part)
        for part in source_parts
    ]
    if not normalized_parts:
        return [], "", "", ""

    for contract in taxonomy["prefix_contracts"]:
        prefix_parts = contract["prefix_parts"]
        if not prefix_parts:
            continue
        if normalized_parts[:len(prefix_parts)] != prefix_parts:
            continue
        suffix_levels = [
            part.replace("／", "/").strip()
            for part in source_parts[len(prefix_parts):]
            if part.strip()
        ]
        levels = [*contract["levels"], *suffix_levels]
        return (
            [{"kind": contract["kind"], "levels": levels}],
            "prefix",
            "",
            "inherit",
        )
    return [], "", "", ""


def _find_weilin_prompt_selector_data() -> str:
    custom_nodes_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    preferred = os.path.join(
        custom_nodes_dir,
        "WeiLin-Comfyui-Tools-V52-FullPromptSelector",
        "user_data",
        "prompt_selector",
        "data.json",
    )
    if os.path.isfile(preferred):
        return preferred

    try:
        sibling_names = os.listdir(custom_nodes_dir)
    except OSError:
        return ""
    for sibling_name in sibling_names:
        if "weilin" not in sibling_name.casefold():
            continue
        candidate = os.path.join(
            custom_nodes_dir,
            sibling_name,
            "user_data",
            "prompt_selector",
            "data.json",
        )
        if os.path.isfile(candidate):
            return candidate
    return ""


def _shared_prompt_source_leaf(category_name: str) -> str:
    value = str(category_name or "").strip()
    if "/" in value:
        value = value.split("/", 1)[1]
    return value.strip()


def _shared_prompt_source_collection(category_name: str) -> str:
    value = str(category_name or "").strip()
    if "/" not in value:
        return "独立分类"
    source_collection = value.split("/", 1)[0].strip()
    return {
        "默认": "默认",
        "所长常规NovelAI个人法典": "常规法典",
        "所长色色NovelAI个人法典(上)": "色色法典上",
        "所长色色NovelAI个人法典(下)": "色色法典下",
    }.get(source_collection, source_collection or "独立分类")


def _shared_prompt_codex_directory_levels(category_name: str) -> list:
    parts = [
        part.strip()
        for part in str(category_name or "").split("/")
        if part.strip()
    ]
    if len(parts) < 2:
        return []
    normalized_root = re.sub(r"\s+", "", parts[0]).casefold()
    if "novelai个人法典" not in normalized_root:
        return []
    return parts[1:]


def _shared_prompt_levels_with_source_lineage(
    levels: list,
    source_category: str,
    match_type: str = "",
    path_strategy: str = "",
) -> list:
    if path_strategy == _SHARED_PROMPT_SOURCE_DIRECTORY_PATH_STRATEGY:
        source_directory_levels = _shared_prompt_codex_directory_levels(
            source_category
        )
        if source_directory_levels:
            return [
                f"WeiLin / {source_directory_levels[0]}",
                *source_directory_levels[1:],
            ]
    resolved = [str(level or "").strip() for level in levels if str(level or "").strip()]
    leaf = _shared_prompt_source_leaf(source_category)
    source_collection = _shared_prompt_source_collection(source_category)
    if not leaf or match_type == "prefix":
        return resolved
    normalized_leaf = _normalize_shared_prompt_rule(leaf)
    normalized_collection = _normalize_shared_prompt_rule(source_collection)
    if not normalized_leaf or not normalized_collection:
        return resolved
    collection_present = any(
        _normalize_shared_prompt_rule(level) == normalized_collection
        for level in resolved
    )
    leaf_index = -1
    for index, level in enumerate(resolved):
        normalized_level = _normalize_shared_prompt_rule(level)
        if (
            normalized_level == normalized_leaf
            or normalized_level.startswith(f"{normalized_leaf}·")
            or normalized_level.startswith(f"{normalized_leaf}（")
        ):
            leaf_index = index
            break
    if collection_present and leaf_index >= 0:
        return resolved
    if not collection_present and leaf_index == len(resolved) - 1:
        return [*resolved[:-1], source_collection, resolved[-1]]
    return [
        *resolved,
        *([] if collection_present else [source_collection]),
        *([] if leaf_index >= 0 else [leaf]),
    ]


def _canonical_shared_prompt(value: str) -> str:
    normalized = str(value or "").casefold().replace("\r", " ").replace("\n", " ")
    normalized = re.sub(r"\s+", " ", normalized)
    normalized = re.sub(r"\s*,\s*", ",", normalized)
    return normalized.strip(" ,")


def _normalize_shared_category_filter_value(value: str) -> str:
    return str(value or "").strip()


def _shared_prompt_category_paths_match_filter(category_paths: list, category_filter: str) -> bool:
    # Legacy directory filters remain readable, but do not define the new tree.
    category_paths = [entry for path in category_paths for entry in [path, *[
        {"levels": levels, "parent": levels[0], "source": levels[-1]}
        for levels in path.get("legacy_paths", []) if levels
    ]]]
    filter_value = str(category_filter or "").strip()
    if not filter_value:
        return True
    if filter_value.startswith(_SHARED_PROMPT_PARENT_FILTER_PREFIX):
        parent = _normalize_shared_category_filter_value(
            filter_value[len(_SHARED_PROMPT_PARENT_FILTER_PREFIX):]
        )
        return any(path.get("parent") == parent for path in category_paths)
    if filter_value.startswith(_SHARED_PROMPT_CHILD_FILTER_PREFIX):
        parts = filter_value[len(_SHARED_PROMPT_CHILD_FILTER_PREFIX):].split(
            _SHARED_PROMPT_CATEGORY_SEPARATOR
        )
        parent = _normalize_shared_category_filter_value(parts[0] if parts else "")
        source = _normalize_shared_category_filter_value(parts[1] if len(parts) > 1 else "")
        return any(
            path.get("parent") == parent and path.get("source") == source
            for path in category_paths
        )
    if filter_value.startswith(_SHARED_PROMPT_PATH_FILTER_PREFIX):
        levels = [
            _normalize_shared_category_filter_value(level)
            for level in filter_value[len(_SHARED_PROMPT_PATH_FILTER_PREFIX):].split(
                _SHARED_PROMPT_CATEGORY_SEPARATOR
            )
            if _normalize_shared_category_filter_value(level)
        ]
        return any(
            all(
                index < len(path.get("levels", []))
                and path.get("levels", [])[index] == level
                for index, level in enumerate(levels)
            )
            for path in category_paths
        )
    return True


def _parse_shared_prompt_filters(category_filter):
    value = str(category_filter or "").strip()
    if value.startswith("shared-filters:"):
        filters = json.loads(value[len("shared-filters:"):])
        if not isinstance(filters, list) or any(not isinstance(entry, str) for entry in filters):
            raise ValueError("Shared filters must be an array of strings")
        filters = list(dict.fromkeys(entry.strip() for entry in filters if entry.strip()))
    else:
        filters = [value] if value else []
    if sum(entry.startswith("shared-source:") for entry in filters) > 1:
        raise ValueError("Only one source may be selected")
    return filters


def _shared_prompt_item_matches_filters(item, filters, subcategory_owners):
    if not filters:
        return True
    semantic = item.get("_semantic") or {}
    themes = set(semantic.get("theme_ids") or [])
    children = semantic.get("subcategories") or []
    owners = semantic.get("subcategory_owners") or {}
    groups = {}
    for value in filters:
        if value.startswith("shared-theme:"):
            group, hit = "theme", value[len("shared-theme:"):] in themes
        elif value.startswith("shared-sub:"):
            child = value[len("shared-sub:"):]
            explicit_owner, separator, label = child.partition("::")
            if separator:
                owner, child = explicit_owner, label
            else:
                owner = subcategory_owners.get(child) or subcategory_owners.get(child.split("/", 1)[0])
            group = "sub:" + (owner or child)
            hit = any((label == child or label.startswith(child + "/"))
                      and (not separator or owners.get(label) == owner) for label in children)
        elif value.startswith("shared-source:"):
            source_id = value[len("shared-source:"):]
            group = "source"
            hit = source_id == str(item.get("source_category_id") or "") or any(
                source_id == str(path.get("source_category_id") or "")
                for path in item.get("shared_category_paths", []))
        else:
            group = "legacy"
            hit = _shared_prompt_category_paths_match_filter(item.get("shared_category_paths", []), value)
        groups.setdefault(group, []).append(hit)
    return all(any(hits) for hits in groups.values())


def _shared_prompt_source_options(items):
    sources = {}
    for item in items:
        identity = item.get("id")
        source_id = str(item.get("source_category_id") or "")
        label = str(item.get("source_category") or "")
        if not source_id or not identity:
            continue
        source = sources.setdefault(source_id, {"id": source_id, "label": label, "ids": set()})
        source["ids"].add(identity)
    return [{"id": source["id"], "label": source["label"], "count": len(source["ids"])}
            for source in sorted(sources.values(), key=lambda source: source["label"].casefold())]


def _shared_prompt_semantic_hash(prompt: dict) -> str:
    value = "\n".join(
        str(prompt.get(field) or "")
        for field in ("alias", "prompt", "description")
    )
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _make_shared_prompt_preview_url(image_name: str, version: str = "") -> str:
    safe_name = os.path.basename(str(image_name or "").replace("\\", "/"))
    if not safe_name:
        return ""
    preview_url = f"/prompt_selector/preview/{urllib.parse.quote(safe_name, safe='')}"
    normalized_version = str(version or "").strip()
    if normalized_version:
        preview_url += f"?v={urllib.parse.quote(normalized_version, safe='')}"
    return preview_url


def _load_semantic_projection_runtime(source_path):
    import importlib
    import importlib.util
    import sys
    from pathlib import Path
    helper_dir = (Path(source_path).parents[2] / "prompt_selector").resolve()
    package_name = "_anima_shared_projection_" + hashlib.sha256(str(helper_dir).encode("utf-8")).hexdigest()[:16]
    if package_name not in sys.modules:
        # Provide relative-import context without running the selector's route-registering __init__.
        spec = importlib.machinery.ModuleSpec(package_name, loader=None, is_package=True)
        spec.submodule_search_locations = [str(helper_dir)]
        sys.modules[package_name] = importlib.util.module_from_spec(spec)
    module = importlib.import_module(package_name + ".semantic_projection")
    document = module.read_projection(Path(source_path).with_name("semantic_projection.json"))
    return module, document


def _build_reviewed_shared_payloads(source_path, source_mtime_ns, data, source_sha256,
        kinds=None, category_filter="", summary_only=False):
    adapter, document = _load_semantic_projection_runtime(source_path)
    import importlib
    taxonomy = importlib.import_module(adapter.__package__ + ".semantic_taxonomy")
    filters = _parse_shared_prompt_filters(category_filter)
    pending, quarantined, nonfragment = [], [], []
    routed = {kind: [] for kind in _SHARED_PROMPT_KINDS}
    for category in data.get("categories", []):
        for prompt in category.get("prompts", []):
            rid = prompt["id"]
            decision = adapter.decision_for(document, category, prompt)
            if decision["disposition"] == "pending":
                pending.append(rid)
                continue
            if decision["disposition"] == "quarantined":
                quarantined.append(rid)
                continue
            route = adapter.fragment_route(decision)
            if not route:
                nonfragment.append(rid)
                continue
            kind, label = route
            codex_lineage = _shared_prompt_codex_directory_levels(category["name"])
            lineage = codex_lineage or category["name"].split("/")
            levels = [f"WeiLin / {label}"]
            legacy_paths = [[levels[0], *lineage]]
            if codex_lineage:
                legacy_paths.append([f"WeiLin / {codex_lineage[0]}", *codex_lineage[1:]])
            paths = [{"levels": levels, "parent": levels[0], "source": levels[-1],
                "source_full": category["name"], "source_category_id": category["id"],
                "path_strategy": "semantic-class-v1", "legacy_paths": legacy_paths}]
            children = adapter.selector_subcategories(decision, prompt)
            paths = [{**paths[0], 'levels': [levels[0], *child.split('/')], 'source': child} for child in children] or paths
            preview = _make_shared_prompt_preview_url(prompt.get("image"),
                prompt.get("updated_at") or category.get("updated_at") or source_mtime_ns)
            # Never collapse variants by normalized body or strip insertion bytes.
            origin = prompt.get('_selector_origin', {})
            item = {**origin.get('record', {}), "id": f"weilin:{kind}:{rid}", "name": prompt.get("alias") or "WeiLin Prompt",
                "name_zh": prompt.get("alias") or "WeiLin Prompt", "aliases": prompt.get("aliases", []),
                "tags": prompt["prompt"],
                "tags_zh": prompt.get("description") or "", "shared": True,
                "source": "weilin_prompt_selector", "source_category": category["name"],
                "source_category_id": category["id"], "source_prompt_ids": [rid],
                "categories": [levels[0]], "shared_parent_category": levels[0],
                "shared_source_category": levels[-1], "shared_category_paths": paths,
                "preview": preview or prompt.get('preview_url', ''), "folder": "weilin-prompt-selector", "traits": prompt.get('tags', []),
                "shared_previews": [{"url": preview, "source_category_id": category["id"], "source_prompt_id": rid}] if preview else [],
                "_semantic": dict(decision)}
            item['source_prompt_id'] = rid
            item['asset_id'] = origin.get('id', '')
            item['favorite'] = prompt.get('favorite', False)
            item['_semantic']['subcategories'] = children
            item['_semantic']['theme_ids'] = sorted(taxonomy.semantic_themes(item['_semantic']))
            item['_semantic']['subcategory_owners'] = {
                child: taxonomy.subcategory_owner(item['_semantic'], child) for child in children
                if taxonomy.subcategory_owner(item['_semantic'], child)
            }
            if not _shared_prompt_item_matches_filters(item, filters, taxonomy.SUBCATEGORY_PARENTS):
                continue
            if origin:
                item['builtin_origin'] = origin['kind']
            if kind == "character":
                item.update(trigger=prompt["prompt"], copyright=item.get('copyright') or category["name"], post_count=item.get('post_count', 0), gender=item.get('gender', ''), hair=item.get('hair', ''), eye=item.get('eye', ''))
                item['detail_tags'] = prompt.get('character_details', '')
            if summary_only:
                item = {key: item[key] for key in ("id", "name", "shared", "shared_category_paths", "_semantic", "source_prompt_id", "source_category_id", "source_category", "favorite")}
            routed[kind].append(item)
    counts = {kind: len(items) for kind, items in routed.items()}
    result = {}
    for kind in kinds or _SHARED_PROMPT_KINDS:
        result[kind] = {"success": True, "enabled": True, "kind": kind, "items": routed[kind],
            "authority": "weilin" if kind in data.get('selector_library', {}).get('kinds', []) else "merged",
            "count": counts[kind], "kind_counts": counts, "source": "WeiLin Prompt Selector",
            "semantic_classes": taxonomy.CLASS_LABELS,
            "semantic_subcategory_owners": taxonomy.SUBCATEGORY_PARENTS,
            "source_options": _shared_prompt_source_options(routed[kind]),
            "source_last_modified": data.get("last_modified", ""), "source_sha256": source_sha256,
            "source_prompt_count": sum(len(c.get("prompts", [])) for c in data.get("categories", [])),
            "source_category_count": len(data.get("categories", [])),
            "pending_prompt_count": len(pending), "pending_prompt_ids": pending,
            "quarantined_prompt_count": len(quarantined), "quarantined_prompt_ids": quarantined,
            "reviewed_nonfragment_count": len(nonfragment),
            "taxonomy_version": "shared-selector-library-v2", "taxonomy_source_matches": not pending}
    return result


def _build_shared_prompt_payloads(
    source_path: str,
    source_mtime_ns: int,
    taxonomy: dict = None,
    kinds: tuple = None,
    category_filter: str = "",
    summary_only: bool = False,
    source_data: dict = None,
    source_sha256: str = "",
) -> dict:
    data = source_data
    if data is None:
        with open(source_path, "rb") as f:
            source_bytes = f.read()
        source_sha256 = hashlib.sha256(source_bytes).hexdigest()
        data = json.loads(source_bytes)

    return _build_reviewed_shared_payloads(source_path, source_mtime_ns, data, source_sha256,
        kinds=kinds, category_filter=category_filter, summary_only=summary_only)



_SHARED_PROMPT_CACHE_DIR = os.path.join(os.path.dirname(__file__), "data", "shared_prompt_cache")


def _shared_prompt_runtime_hash(source_path):
    helper_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(source_path))), "prompt_selector")
    digest = hashlib.sha256()
    for path in (__file__, os.path.join(helper_dir, "semantic_projection.py"),
                 os.path.join(helper_dir, "semantic_taxonomy.py"), _SHARED_PROMPT_TAXONOMY_PATH):
        with open(path, "rb") as stream:
            digest.update(hashlib.sha256(stream.read()).digest())
    return digest.hexdigest()


def _read_shared_prompt_cache(kind, fingerprint):
    path = os.path.join(_SHARED_PROMPT_CACHE_DIR, kind + ".json.gz")
    try:
        with gzip.open(path, "rt", encoding="utf-8") as stream:
            cached = json.load(stream)
        payload = cached.get("payload")
        if (cached.get("fingerprint") == fingerprint and isinstance(payload, dict)
                and payload.get("kind") == kind and payload.get("revision")
                and payload.get("success") is True):
            return payload
    except (OSError, ValueError, TypeError, AttributeError, EOFError):
        pass
    return None


def _write_shared_prompt_cache(kind, fingerprint, payload):
    path = os.path.join(_SHARED_PROMPT_CACHE_DIR, kind + ".json.gz")
    temporary_path = path + f".{os.getpid()}.{threading.get_ident()}.tmp"
    try:
        os.makedirs(_SHARED_PROMPT_CACHE_DIR, exist_ok=True)
        encoded = json.dumps({"fingerprint": fingerprint, "payload": payload},
                             ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        with gzip.open(temporary_path, "wb", compresslevel=1) as stream:
            stream.write(encoded)
        os.replace(temporary_path, path)
    except OSError:
        # A derived cache must not prevent opening the authoritative library.
        if os.path.exists(temporary_path):
            try:
                os.unlink(temporary_path)
            except OSError:
                pass


def get_shared_prompt_payload(
    kind: str,
    category_filter: str = "",
    summary_only: bool = False,
    force_refresh: bool = False,
) -> dict:
    normalized_kind = str(kind or "").strip().casefold()
    if normalized_kind not in _SHARED_PROMPT_KINDS:
        raise ValueError("Unsupported shared prompt kind")
    normalized_filter = str(category_filter or "").strip()
    cache_payload_key = "\x1f".join([normalized_kind, "summary" if summary_only else "items", normalized_filter])
    source_path = _find_weilin_prompt_selector_data()
    if not source_path:
        return {"success": True, "enabled": False, "kind": normalized_kind,
                "source": "WeiLin Prompt Selector", "count": 0, "items": [],
                "error": "WeiLin Prompt Selector data.json was not found"}

    source_stat = os.stat(source_path)
    taxonomy_path = _SHARED_PROMPT_TAXONOMY_PATH
    with open(os.path.join(os.path.dirname(source_path), "semantic_projection.json"), "rb") as stream:
        projection_hash = hashlib.sha256(stream.read()).hexdigest()
    taxonomy_identity = (os.stat(taxonomy_path).st_mtime_ns, projection_hash,
                         _shared_prompt_runtime_hash(source_path))
    with _SHARED_PROMPT_DATA_LOCK:
        source_matches = (_SHARED_PROMPT_DATA_CACHE["path"] == source_path
                          and _SHARED_PROMPT_DATA_CACHE["mtime_ns"] == source_stat.st_mtime_ns
                          and _SHARED_PROMPT_DATA_CACHE["size"] == source_stat.st_size
                          and bool(_SHARED_PROMPT_DATA_CACHE["source_sha256"]))
        identity_matches = (source_matches and _SHARED_PROMPT_DATA_CACHE["taxonomy_path"] == taxonomy_path
                            and _SHARED_PROMPT_DATA_CACHE["taxonomy_mtime_ns"] == taxonomy_identity)
        if not force_refresh and identity_matches and cache_payload_key in _SHARED_PROMPT_DATA_CACHE["payloads"]:
            return _SHARED_PROMPT_DATA_CACHE["payloads"][cache_payload_key]

        source_bytes = None
        source_data = _SHARED_PROMPT_DATA_CACHE["source_data"] if source_matches else None
        if source_matches:
            source_sha256 = _SHARED_PROMPT_DATA_CACHE["source_sha256"]
        else:
            with open(source_path, "rb") as stream:
                source_bytes = stream.read()
            source_sha256 = hashlib.sha256(source_bytes).hexdigest()
        fingerprint = ["shared-prompts-v1", source_path, source_sha256, *taxonomy_identity]
        next_payloads = dict(_SHARED_PROMPT_DATA_CACHE["payloads"]) if identity_matches else {}
        full_catalog = not normalized_filter and not summary_only
        payload = _read_shared_prompt_cache(normalized_kind, fingerprint) if full_catalog and not force_refresh else None
        if payload is not None:
            next_payloads[cache_payload_key] = payload
        else:
            if source_data is None:
                if source_bytes is None:
                    with open(source_path, "rb") as stream:
                        source_bytes = stream.read()
                    if hashlib.sha256(source_bytes).hexdigest() != source_sha256:
                        raise ValueError("资料正在更新，请重新打开选择器。")
                source_data = json.loads(source_bytes)
            payloads = _build_shared_prompt_payloads(
                source_path, source_stat.st_mtime_ns, _load_shared_prompt_taxonomy(taxonomy_path),
                kinds=None if full_catalog else (normalized_kind,), category_filter=normalized_filter,
                summary_only=summary_only, source_data=source_data, source_sha256=source_sha256)
            revision = hashlib.sha256(json.dumps([source_sha256, taxonomy_identity], ensure_ascii=False).encode("utf-8")).hexdigest()
            for payload_kind, payload in payloads.items():
                payload.update(category_filter=normalized_filter, summary_only=summary_only, revision=revision)
                key = "\x1f".join([payload_kind, "summary" if summary_only else "items", normalized_filter])
                next_payloads[key] = payload
                if full_catalog:
                    _write_shared_prompt_cache(payload_kind, fingerprint, payload)
        _SHARED_PROMPT_DATA_CACHE.update(
            path=source_path, mtime_ns=source_stat.st_mtime_ns, size=source_stat.st_size,
            source_data=source_data, source_sha256=source_sha256, taxonomy_path=taxonomy_path,
            taxonomy_mtime_ns=taxonomy_identity, payloads=next_payloads)
        return next_payloads[cache_payload_key]


def _encode_shared_prompt_response(payload: dict, use_gzip: bool) -> tuple:
    body = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    if use_gzip:
        return gzip.compress(body, compresslevel=5), "gzip"
    return body, ""


@PromptServer.instance.routes.get("/anima-tools/shared-prompts")
async def shared_prompt_data_api(request):
    kind = request.query.get("kind", "")
    category_filter = request.query.get("filter", "")
    summary_only = request.query.get("index") in {"1", "true", "yes"}
    force_refresh = bool(request.query.get("refresh"))
    try:
        payload = await asyncio.to_thread(
            get_shared_prompt_payload,
            kind,
            category_filter,
            summary_only,
            force_refresh,
        )
        response_body, content_encoding = await asyncio.to_thread(
            _encode_shared_prompt_response,
            payload,
            "gzip" in request.headers.get("Accept-Encoding", "").casefold(),
        )
        response = web.Response(body=response_body, content_type="application/json")
        if content_encoding:
            response.headers["Content-Encoding"] = content_encoding
            response.headers["Vary"] = "Accept-Encoding"
        if request.query.get("refresh"):
            response.headers["Cache-Control"] = "no-store"
        else:
            response.headers["Cache-Control"] = "private, max-age=60"
        response.headers["X-Anima-Shared-Source"] = "weilin-prompt-selector"
        return response
    except ValueError as e:
        return web.json_response({"success": False, "error": str(e), "items": []}, status=400)
    except Exception as e:
        print(f"[Anima Tools] Shared Prompt Selector adapter failed: {e}")
        return web.json_response({"success": False, "error": str(e), "items": []}, status=500)


def _artist_search_rank(item, query, nickname=""):
    if not query:
        return 0
    names = [item.get(key) for key in ("name", "name_zh", "alias", "aliases")]
    names.append(nickname)
    names = [str(value).casefold() for entry in names for value in
             (entry if isinstance(entry, list) else [entry]) if value]
    if query in names:
        return 0
    if any(value.startswith(query) for value in names):
        return 1
    body = [item.get(key) for key in ("prompt", "tags", "tags_zh", "trigger", "description", "traits")]
    if any(query in str(value).casefold() for entry in body for value in
           (entry if isinstance(entry, list) else [entry]) if value):
        return 2
    source = [item.get(key) for key in ("id", "copyright", "categories", "source_category",
              "shared_parent_category", "shared_source_category")]
    source.extend(value for path in item.get("shared_category_paths", []) for value in
                  (path.get("levels"), path.get("parent"), path.get("source"), path.get("source_full")))
    if any(query in str(value).casefold() for entry in source for value in
           (entry if isinstance(entry, list) else [entry]) if value):
        return 3
    return None


def _artist_category_tree(items, class_labels=None, subcategory_owners=None):
    if class_labels:
        roots = {}
        for item in items:
            semantic = item.get("_semantic") or {}
            themes = semantic.get("theme_ids") or []
            owners = semantic.get("subcategory_owners") or {}
            for theme in themes:
                if theme not in class_labels:
                    continue
                root = roots.setdefault(theme, {"ids": set(), "children": {}})
                root["ids"].add(item["id"])
            for child in semantic.get("subcategories") or []:
                owner = owners.get(child)
                if owner not in class_labels:
                    continue
                root = roots.setdefault(owner, {"ids": set(), "children": {}})
                root["ids"].add(item["id"])
                root["children"].setdefault(child, set()).add(item["id"])
        subcategory_owners = subcategory_owners or {}
        return [{"key": "shared-theme:" + theme, "name": class_labels[theme],
                 "label": class_labels[theme], "count": len(roots[theme]["ids"]),
                 "children": [{"key": "shared-sub:" + (child if subcategory_owners.get(child)
                                    or subcategory_owners.get(child.split("/", 1)[0]) else theme + "::" + child),
                               "name": child, "label": child,
                               "count": len(ids), "children": []}
                              for child, ids in sorted(roots[theme]["children"].items())]}
                for theme in class_labels if theme in roots]
    roots = {}
    for item in items:
        for path in item.get("shared_category_paths", []):
            levels = path.get("levels") or [path.get("parent"), path.get("source")]
            children = roots
            for level in filter(None, levels):
                node = children.setdefault(level, {"name": level, "ids": set(), "children": {}})
                node["ids"].add(item["id"])
                children = node["children"]

    def serialize(nodes, depth=0):
        return [{"name": node["name"],
                 "label": re.sub(r"^WeiLin\s*/\s*", "", node["name"], flags=re.I) if depth == 0 else node["name"],
                 "count": len(node["ids"]), "children": serialize(node["children"], depth + 1)}
                for node in sorted(nodes.values(), key=lambda node: node["name"].casefold())]
    return serialize(roots)


def _artist_page(payload, query):
    items = payload["items"]
    revision = payload["revision"]
    expected = str(query.get("revision") or "")
    if expected and expected != revision:
        return {"success": False, "error": "资料已变更，请重新打开画师选择器。", "revision": revision}, 409

    lookup_keys = {str(value) for value in query.get("lookup_keys", [])}
    lookup_names = {str(value) for value in query.get("lookup_names", [])}
    lookup = ([item for item in items if f"shared:{item['id']}" in lookup_keys or item.get("name") in lookup_names]
              if lookup_keys or lookup_names else [])

    group_keys = query.get("group_keys")
    selected_keys = query.get("selected_keys")
    if group_keys is not None:
        allowed = {str(key) for key in group_keys}
        matches = [item for item in items if f"shared:{item['id']}" in allowed]
    elif selected_keys is not None:
        allowed = {str(key) for key in selected_keys}
        matches = [item for item in items if f"shared:{item['id']}" in allowed]
    else:
        matches = items

    category_filter = str(query.get("filter") or "")
    if category_filter:
        filters = _parse_shared_prompt_filters(category_filter)
        matches = [item for item in matches if _shared_prompt_item_matches_filters(
            item, filters, payload.get("semantic_subcategory_owners", {}))]
    search = str(query.get("search") or "").strip().casefold()
    aliases = query.get("aliases") or {}
    if search:
        ranked = [(rank, item) for item in matches if
                  (rank := _artist_search_rank(item, search, aliases.get(f"shared:{item['id']}", ""))) is not None]
        matches = [item for _, item in ranked]
    else:
        ranked = []

    sort = str(query.get("sort") or "works-desc")
    if sort in {"works-desc", "works-asc"}:
        matches = sorted(matches, key=lambda item: float(item.get("post_count") or 0),
                         reverse=sort.endswith("desc"))
    elif sort in {"unique-desc", "unique-asc"}:
        rated = [item for item in matches if isinstance(item.get("uniqueness_score"), (int, float))]
        unrated = [item for item in matches if not isinstance(item.get("uniqueness_score"), (int, float))]
        matches = sorted(rated, key=lambda item: item["uniqueness_score"],
                         reverse=sort.endswith("desc")) + unrated
    elif sort in {"name-asc", "name-desc"}:
        matches = sorted(matches, key=lambda item: str(item.get("name") or "").casefold(),
                         reverse=sort.endswith("desc"))
    elif sort == "random":
        seed = str(query.get("random_seed") or "")
        matches = sorted(matches, key=lambda item: hashlib.blake2s(
            (seed + str(item["id"])).encode("utf-8"), digest_size=8).digest())
    if search:
        ranks = {item["id"]: rank for rank, item in ranked}
        matches = sorted(matches, key=lambda item: ranks[item["id"]])

    offset = max(0, min(int(query.get("offset") or 0), len(matches)))
    limit = max(0, min(int(query.get("limit", 60)), 100))
    result = {"success": True, "revision": revision, "total": len(matches),
              "catalog_count": len(items), "items": matches[offset:offset + limit], "lookup": lookup}
    if query.get("include_tree"):
        result["tree"] = _artist_category_tree(items, payload.get("semantic_classes"),
                                              payload.get("semantic_subcategory_owners"))
        result["source_options"] = payload.get("source_options") or _shared_prompt_source_options(items)
    return result, 200


_ARTIST_PAGE_CACHE_LOCK = threading.Lock()
_ARTIST_PAGE_CACHE = {"fingerprint": None, "payload": None}
_ARTIST_PAGE_CACHE_PATH = os.path.join(os.path.dirname(__file__), "data", "artist_page_cache.json.gz")


def _artist_page_fingerprint():
    source = _find_weilin_prompt_selector_data()
    if not source:
        raise ValueError("WeiLin Prompt Selector data.json was not found")
    source_stat = os.stat(source)
    projection_path = os.path.join(os.path.dirname(source), "semantic_projection.json")
    with open(projection_path, "rb") as stream:
        projection_hash = hashlib.sha256(stream.read()).hexdigest()
    taxonomy_stat = os.stat(_SHARED_PROMPT_TAXONOMY_PATH)
    return ["artist-page-v2-canonical", source, source_stat.st_size, source_stat.st_mtime_ns,
            projection_hash, taxonomy_stat.st_size, taxonomy_stat.st_mtime_ns]


def _get_artist_page_payload():
    fingerprint = _artist_page_fingerprint()
    with _ARTIST_PAGE_CACHE_LOCK:
        if _ARTIST_PAGE_CACHE["fingerprint"] == fingerprint:
            return _ARTIST_PAGE_CACHE["payload"]
        try:
            with gzip.open(_ARTIST_PAGE_CACHE_PATH, "rt", encoding="utf-8") as stream:
                cached = json.load(stream)
            if cached.get("fingerprint") == fingerprint and cached.get("payload", {}).get("revision"):
                _ARTIST_PAGE_CACHE.update(fingerprint=fingerprint, payload=cached["payload"])
                return cached["payload"]
        except (OSError, ValueError, TypeError):
            pass

        payload = get_shared_prompt_payload("artist")
        if _artist_page_fingerprint() != fingerprint:
            raise ValueError("资料正在更新，请重试画师选择器。")
        temporary_path = _ARTIST_PAGE_CACHE_PATH + f".{os.getpid()}.tmp"
        try:
            with gzip.open(temporary_path, "wt", encoding="utf-8", compresslevel=3) as stream:
                json.dump({"fingerprint": fingerprint, "payload": payload}, stream,
                          ensure_ascii=False, separators=(",", ":"))
            os.replace(temporary_path, _ARTIST_PAGE_CACHE_PATH)
        except OSError:
            if os.path.exists(temporary_path):
                os.unlink(temporary_path)
        _ARTIST_PAGE_CACHE.update(fingerprint=fingerprint, payload=payload)
        return payload


@PromptServer.instance.routes.post("/anima-tools/artist-page")
async def artist_page_api(request):
    try:
        query = await request.json()
        payload = await asyncio.to_thread(_get_artist_page_payload)
        result, status = await asyncio.to_thread(_artist_page, payload, query)
        return web.json_response(result, status=status)
    except (TypeError, ValueError, KeyError) as error:
        return web.json_response({"success": False, "error": str(error)}, status=400)


ANIMADEX_CHARACTER_SEARCH_API = "https://animadex.net/api/characters/search"
_animadex_character_cache = {}
_animadex_character_cache_lock = threading.Lock()
_animadex_character_cache_ttl = 60 * 60 * 12

def _normalize_animadex_text(value: str) -> str:
    return " ".join(str(value or "").strip().lower().replace("_", " ").split())

def _animadex_character_cache_key(name: str, copyright: str) -> str:
    return f"{_normalize_animadex_text(name)}||{_normalize_animadex_text(copyright)}"

def _select_animadex_character_result(results: list, name: str, copyright: str) -> dict | None:
    if not results:
        return None

    target_name = _normalize_animadex_text(name)
    target_copyright = _normalize_animadex_text(copyright)
    target_trigger = _normalize_animadex_text(f"{name}, {copyright}" if copyright else name)
    target_slug = target_name.replace(" ", "_")

    for item in results:
        trigger = _normalize_animadex_text(item.get("trigger", ""))
        item_name = _normalize_animadex_text(item.get("name", ""))
        item_copyright = _normalize_animadex_text(item.get("copyright", ""))
        item_slug = _normalize_animadex_text(item.get("slug", "")).replace(" ", "_")
        if trigger == target_trigger:
            return item
        if item_slug == target_slug and (not target_copyright or item_copyright == target_copyright):
            return item
        if item_name == target_name and (not target_copyright or item_copyright == target_copyright):
            return item

    return results[0]

def _compact_animadex_character_item(item: dict | None) -> dict | None:
    if not item:
        return None
    return {
        "slug": item.get("slug", ""),
        "name": item.get("name", ""),
        "copyright": item.get("copyright", ""),
        "copyright_name": item.get("copyright_name", ""),
        "trigger": item.get("trigger", ""),
        "tags": item.get("tags") if isinstance(item.get("tags"), list) else [],
        "count": item.get("count", 0),
        "url": item.get("url", ""),
        "thumb_url": item.get("thumb_url", ""),
        "img_url": item.get("img_url", ""),
    }

def _fetch_animadex_character(name: str, copyright: str) -> dict | None:
    query_text = f"{name}, {copyright}" if copyright else name
    params = urllib.parse.urlencode({
        "q": query_text,
        "sort": "count",
        "page": "1",
    })
    url = f"{ANIMADEX_CHARACTER_SEARCH_API}?{params}"
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "ComfyUI-Anima-Tools/1.0 (+https://github.com/zhangp365/Comfyui-Anima-Tools)",
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=12) as resp:
        charset = resp.headers.get_content_charset() or "utf-8"
        data = json.loads(resp.read().decode(charset, errors="replace"))
    return _compact_animadex_character_item(_select_animadex_character_result(data.get("results") or [], name, copyright))

@PromptServer.instance.routes.get("/anima-tools/character/official")
async def get_official_character_api(request):
    name = str(request.query.get("name", "")).strip()
    copyright = str(request.query.get("copyright", "")).strip()
    if not name:
        return web.json_response({"success": False, "error": "Missing character name"}, status=400)
    if len(name) > 160 or len(copyright) > 160:
        return web.json_response({"success": False, "error": "Query is too long"}, status=400)

    cache_key = _animadex_character_cache_key(name, copyright)
    now = time.time()
    with _animadex_character_cache_lock:
        cached = _animadex_character_cache.get(cache_key)
        if cached and now - cached.get("time", 0) < _animadex_character_cache_ttl:
            return web.json_response(cached["payload"])

    try:
        item = await asyncio.to_thread(_fetch_animadex_character, name, copyright)
        payload = {"success": bool(item), "item": item}
        with _animadex_character_cache_lock:
            _animadex_character_cache[cache_key] = {"time": now, "payload": payload}
        return web.json_response(payload)
    except Exception as e:
        print(f"[Anima Tools] Error fetching AnimaDex official character tags: {e}")
        return web.json_response({"success": False, "error": str(e)}, status=502)


# ----------------- LoRA 相关的 API 路由 -----------------
from .anima_lora_api import (
    search_civitai_loras,
    start_download_task,
    get_download_job_status,
    load_config as load_lora_config,
    save_config as save_lora_config,
    get_lora_save_dir,
    download_preview_image,
    open_civitai_preview_url,
    fetch_civitai_model,
    normalize_lora_profile_key,
    resolve_lora_base_model,
)

def scan_loras_in_directory(directory: str) -> list:
    results = []
    if not directory or not os.path.isdir(directory):
        return results
    directory = os.path.abspath(directory)
    for root, _, files in os.walk(directory):
        for file in files:
            if file.endswith(".safetensors"):
                full_path = os.path.join(root, file)
                rel_path = os.path.relpath(full_path, directory)
                rel_path = rel_path.replace(os.sep, "/")
                results.append(rel_path)
    return results

def get_anima_tools_user_dir() -> str:
    try:
        user_dir = folder_paths.get_user_directory()
    except AttributeError:
        user_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "user"))
        if not os.path.exists(user_dir):
            user_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "user"))
    cache_root = os.path.join(user_dir, "anima_tools")
    os.makedirs(cache_root, exist_ok=True)
    return cache_root

_SELECTOR_IMAGE_CACHE_DIR = os.path.join(get_anima_tools_user_dir(), "image_cache")
_SELECTOR_IMAGE_CACHE_ALLOWED_HOSTS = {
    "blobs.animadex.net",
    "cdn.jsdelivr.net",
    "cdn.statically.io",
    "fastly.jsdelivr.net",
    "raw.githubusercontent.com",
}
_SELECTOR_IMAGE_CACHE_EXTENSIONS = {".gif", ".jpeg", ".jpg", ".png", ".webp"}
_SELECTOR_IMAGE_CACHE_MAX_BYTES = 25 * 1024 * 1024
_SELECTOR_IMAGE_CACHE_JOBS = {}
_SELECTOR_IMAGE_CACHE_LOCK = threading.Lock()

def _selector_image_source_url(value: str) -> str:
    source_url = str(value or "").strip()
    parsed = urllib.parse.urlparse(source_url)
    if parsed.scheme.lower() != "https" or parsed.hostname not in _SELECTOR_IMAGE_CACHE_ALLOWED_HOSTS:
        raise ValueError("Unsupported image source")
    return urllib.parse.urlunparse(parsed._replace(fragment=""))

def _selector_image_cache_path(source_url: str) -> str:
    parsed = urllib.parse.urlparse(source_url)
    extension = os.path.splitext(parsed.path)[1].lower()
    if extension not in _SELECTOR_IMAGE_CACHE_EXTENSIONS:
        extension = ".img"
    cache_key = hashlib.sha256(source_url.encode("utf-8", errors="ignore")).hexdigest()
    return os.path.join(_SELECTOR_IMAGE_CACHE_DIR, f"{cache_key}{extension}")

def _download_selector_image(source_url: str, cache_path: str) -> None:
    os.makedirs(_SELECTOR_IMAGE_CACHE_DIR, exist_ok=True)
    tmp_path = f"{cache_path}.{threading.get_ident()}.tmp"
    try:
        req = urllib.request.Request(source_url, headers={"User-Agent": "ComfyUI-Anima-Tools/1.0"})
        with urllib.request.urlopen(req, timeout=30) as response:
            _selector_image_source_url(response.geturl())
            content_type = str(response.headers.get("Content-Type") or "").split(";", 1)[0].strip().lower()
            if content_type and not content_type.startswith("image/"):
                raise ValueError("Remote response is not an image")
            content_length = response.headers.get("Content-Length")
            if content_length and int(content_length) > _SELECTOR_IMAGE_CACHE_MAX_BYTES:
                raise ValueError("Remote image is too large")

            downloaded = 0
            with open(tmp_path, "wb") as output:
                while True:
                    chunk = response.read(1024 * 256)
                    if not chunk:
                        break
                    downloaded += len(chunk)
                    if downloaded > _SELECTOR_IMAGE_CACHE_MAX_BYTES:
                        raise ValueError("Remote image is too large")
                    output.write(chunk)
        if downloaded <= 0:
            raise ValueError("Remote image is empty")
        os.replace(tmp_path, cache_path)
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)

def _ensure_selector_image_cached(source_url: str) -> str:
    cache_path = _selector_image_cache_path(source_url)
    if os.path.isfile(cache_path) and os.path.getsize(cache_path) > 0:
        return cache_path

    cache_key = os.path.basename(cache_path)
    with _SELECTOR_IMAGE_CACHE_LOCK:
        event = _SELECTOR_IMAGE_CACHE_JOBS.get(cache_key)
        owns_download = event is None
        if owns_download:
            event = threading.Event()
            _SELECTOR_IMAGE_CACHE_JOBS[cache_key] = event

    if not owns_download:
        event.wait(35)
        return cache_path if os.path.isfile(cache_path) and os.path.getsize(cache_path) > 0 else ""

    try:
        _download_selector_image(source_url, cache_path)
        return cache_path
    finally:
        with _SELECTOR_IMAGE_CACHE_LOCK:
            _SELECTOR_IMAGE_CACHE_JOBS.pop(cache_key, None)
            event.set()

@PromptServer.instance.routes.get("/anima-tools/image-cache")
async def selector_image_cache_api(request):
    try:
        source_url = _selector_image_source_url(request.query.get("url", ""))
    except ValueError as e:
        return web.json_response({"success": False, "error": str(e)}, status=400)

    cache_path = _selector_image_cache_path(source_url)
    cache_hit = os.path.isfile(cache_path) and os.path.getsize(cache_path) > 0
    try:
        if not cache_hit:
            cache_path = await asyncio.to_thread(_ensure_selector_image_cached, source_url)
        if not cache_path:
            raise RuntimeError("Image cache download did not complete")
        response = web.FileResponse(cache_path)
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        response.headers["X-Anima-Image-Cache"] = "HIT" if cache_hit else "MISS"
        return response
    except Exception as e:
        print(f"[Anima Tools] Selector image cache failed: {e}")
        raise web.HTTPFound(source_url)

def get_lora_profile_dir_status(base_model: str = "Anima") -> tuple[str, bool, str]:
    config = load_lora_config()
    profile_key = normalize_lora_profile_key(base_model)
    config_key = "custom_lora_dir" if profile_key == "anima" else "krea2_lora_dir"
    custom_dir = str(config.get(config_key, "") or "").strip()
    if not custom_dir:
        return "", False, ""
    abs_custom_dir = os.path.abspath(os.path.expanduser(custom_dir))
    return custom_dir, os.path.isdir(abs_custom_dir), abs_custom_dir

def get_custom_lora_dir_status() -> tuple[str, bool, str]:
    return get_lora_profile_dir_status("Anima")

def get_lora_root_infos() -> list[dict]:
    roots = []

    for profile_key in ("anima", "krea2"):
        configured_dir, custom_dir_valid, custom_dir_abs = get_lora_profile_dir_status(profile_key)
        if profile_key == "krea2" and not configured_dir:
            custom_dir_abs = get_lora_save_dir(base_model="Krea 2")
            custom_dir_valid = os.path.isdir(custom_dir_abs)
        if custom_dir_valid:
            roots.append({
                "path": custom_dir_abs,
                "source": "custom",
                "base_model_profile": profile_key,
            })

    try:
        for path in folder_paths.get_folder_paths("loras"):
            if path and os.path.isdir(path):
                roots.append({"path": os.path.abspath(path), "source": "default", "base_model_profile": ""})
    except Exception:
        pass

    fallback = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "models", "loras"))
    if os.path.isdir(fallback):
        roots.append({"path": fallback, "source": "default", "base_model_profile": ""})

    deduped = []
    seen = set()
    for root_info in roots:
        root = root_info["path"]
        key = os.path.normcase(os.path.abspath(root))
        if key in seen:
            existing = next(item for item in deduped if os.path.normcase(os.path.abspath(item["path"])) == key)
            incoming_profile = root_info.get("base_model_profile", "")
            existing_profiles = set(existing.get("base_model_profiles") or [])
            if existing.get("base_model_profile"):
                existing_profiles.add(existing["base_model_profile"])
            if incoming_profile:
                existing_profiles.add(incoming_profile)
            existing["base_model_profiles"] = sorted(existing_profiles)
            if root_info.get("source") == "custom":
                existing["source"] = "custom"
            continue
        seen.add(key)
        root_info["base_model_profiles"] = [root_info["base_model_profile"]] if root_info.get("base_model_profile") else []
        deduped.append(root_info)
    return deduped

def get_lora_roots() -> list[str]:
    return [root_info["path"] for root_info in get_lora_root_infos()]

def normalize_lora_filename(filename: str) -> str | None:
    filename = str(filename or "").replace("\\", "/").strip()
    if not filename or filename.endswith("/"):
        return None
    if os.path.isabs(filename) or Path(filename).is_absolute():
        return None
    parts = [part for part in filename.split("/") if part]
    if any(part in (".", "..") for part in parts):
        return None
    return "/".join(parts)

def is_relative_to_path(candidate: Path, root: Path) -> bool:
    try:
        candidate.relative_to(root)
        return True
    except ValueError:
        try:
            candidate_key = os.path.normcase(os.path.abspath(str(candidate)))
            root_key = os.path.normcase(os.path.abspath(str(root)))
            return os.path.commonpath([candidate_key, root_key]) == root_key
        except ValueError:
            return False

def resolve_lora_root(root: str) -> Path | None:
    try:
        root_path = Path(root).expanduser().resolve()
        if root_path.is_dir():
            return root_path
    except (OSError, RuntimeError):
        return None
    return None

def resolve_lora_candidate_under_root(root: str, filename: str) -> str | None:
    root_path = resolve_lora_root(root)
    if root_path is None:
        return None
    try:
        candidate = (root_path / filename.replace("/", os.sep)).resolve()
    except (OSError, RuntimeError):
        return None
    if not is_relative_to_path(candidate, root_path):
        return None
    if candidate.exists():
        return str(candidate)
    return None

def is_lora_path_contained(path: str) -> bool:
    if not path:
        return False
    try:
        candidate = Path(path).resolve()
    except (OSError, RuntimeError):
        return False
    for root in get_lora_roots():
        root_path = resolve_lora_root(root)
        if root_path is not None and is_relative_to_path(candidate, root_path):
            return True
    return False

def resolve_lora_companion_path(abs_path: str, extension: str, suffix: str = "", must_exist: bool = True) -> str | None:
    if not abs_path or not extension.startswith("."):
        return None
    base_no_ext = os.path.splitext(abs_path)[0]
    candidate = base_no_ext + suffix + extension
    if must_exist and not os.path.exists(candidate):
        return None
    try:
        resolved = Path(candidate).resolve()
    except (OSError, RuntimeError):
        return None
    if not is_lora_path_contained(str(resolved)):
        return None
    if must_exist and not resolved.exists():
        return None
    return str(resolved)

def scan_loras_with_info() -> list[dict]:
    results = []
    seen_abs_paths = set()
    for root_info in get_lora_root_infos():
        root = root_info["path"]
        source = root_info.get("source", "default")
        for rel_path in scan_loras_in_directory(root):
            abs_path = os.path.join(root, rel_path.replace("/", os.sep))
            if not os.path.isfile(abs_path):
                continue
            abs_key = os.path.normcase(os.path.realpath(abs_path))
            if abs_key in seen_abs_paths:
                continue
            seen_abs_paths.add(abs_key)
            results.append({
                "filename": rel_path,
                "abs_path": abs_path,
                "source": source,
                "base_model_profile": root_info.get("base_model_profile", ""),
                "base_model_profiles": root_info.get("base_model_profiles", []),
            })
    return results

def get_custom_lora_subfolders(base_model: str = "Anima") -> list[str]:
    configured_dir, custom_dir_valid, custom_dir_abs = get_lora_profile_dir_status(base_model)
    if normalize_lora_profile_key(base_model) == "krea2" and not configured_dir:
        custom_dir_abs = get_lora_save_dir(base_model="Krea 2")
        custom_dir_valid = os.path.isdir(custom_dir_abs)
    if not custom_dir_valid:
        return []
    folders = []
    for root, dirs, _ in os.walk(custom_dir_abs):
        dirs[:] = [name for name in dirs if not name.startswith(".")]
        rel_path = os.path.relpath(root, custom_dir_abs)
        if rel_path == ".":
            continue
        normalized = rel_path.replace(os.sep, "/")
        if normalize_lora_filename(normalized + "/placeholder.safetensors"):
            folders.append(normalized)
    return sorted(set(folders), key=str.lower)

def resolve_lora_abs_path(filename: str, base_model: str = "") -> str | None:
    filename = normalize_lora_filename(filename)
    if not filename:
        return None

    profile_keys = []
    if str(base_model or "").strip():
        profile_keys.append(normalize_lora_profile_key(base_model))
    profile_keys.extend(profile for profile in ("anima", "krea2") if profile not in profile_keys)
    for profile_key in profile_keys:
        _, custom_dir_valid, custom_dir_abs = get_lora_profile_dir_status(profile_key)
        if custom_dir_valid:
            candidate = resolve_lora_candidate_under_root(custom_dir_abs, filename)
            if candidate:
                return candidate

    try:
        abs_path = folder_paths.get_full_path("loras", filename)
    except Exception:
        abs_path = None

    if abs_path and os.path.exists(abs_path) and is_lora_path_contained(abs_path):
        return str(Path(abs_path).resolve())

    for root in get_lora_roots():
        candidate = resolve_lora_candidate_under_root(root, filename)
        if candidate:
            return candidate
    return None

def find_companion_preview(abs_path: str) -> str | None:
    if not abs_path:
        return None
    for ext in [".png", ".jpg", ".jpeg", ".webp", ".gif", ".mp4", ".webm"]:
        for suffix in ["", ".preview"]:
            preview_file = resolve_lora_companion_path(abs_path, ext, suffix=suffix, must_exist=True)
            if preview_file:
                return preview_file
    return None

def get_preview_cache_key(abs_path: str, preview_file: str | None = None) -> str:
    stat_path = preview_file if preview_file and os.path.exists(preview_file) else abs_path
    try:
        stat = os.stat(stat_path)
        raw = f"{os.path.abspath(stat_path)}|{int(stat.st_mtime)}|{stat.st_size}"
    except OSError:
        raw = f"{os.path.abspath(stat_path)}|missing"
    return hashlib.sha256(raw.encode("utf-8", errors="ignore")).hexdigest()[:20]

def make_display_name(filename: str) -> str:
    name = os.path.basename(filename.replace("\\", "/"))
    if name.lower().endswith(".safetensors"):
        name = name[:-12]
    return name

def get_lora_metadata_candidates(abs_path: str) -> list[str]:
    base_path = os.path.splitext(abs_path)[0]
    candidates = [base_path + ".json", base_path + ".metadata.json"]
    return [
        candidate for candidate in candidates
        if os.path.isfile(candidate) and is_lora_path_contained(candidate)
    ]

def normalize_lora_metadata(data: dict) -> tuple[dict | None, str]:
    if not isinstance(data, dict):
        return None, ""
    model = data.get("model")
    version = data.get("version")
    if isinstance(model, dict) and isinstance(version, dict):
        return {"model": model, "version": version}, "anima"

    civitai = data.get("civitai")
    if not isinstance(civitai, dict) or not civitai:
        return None, ""

    version = dict(civitai)
    model = dict(civitai.get("model") or {}) if isinstance(civitai.get("model"), dict) else {}
    model.setdefault("id", civitai.get("modelId"))
    model.setdefault("name", data.get("model_name") or civitai.get("modelName") or "")
    creator = civitai.get("creator")
    if isinstance(creator, dict) and not isinstance(model.get("creator"), dict):
        model["creator"] = creator
    model["modelVersions"] = [version]
    return {"model": model, "version": version}, "lora_manager"

def read_lora_full_metadata(abs_path: str) -> tuple[dict | None, str]:
    for meta_path in get_lora_metadata_candidates(abs_path):
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                normalized, source = normalize_lora_metadata(json.load(f))
            if normalized:
                return normalized, source
        except (OSError, json.JSONDecodeError) as e:
            print(f"[Anima Tools] Failed to read local LoRA metadata {meta_path}: {e}")
    return None, ""

def read_lora_meta_summary(abs_path: str) -> tuple[str, dict]:
    metadata, metadata_source = read_lora_full_metadata(abs_path)
    if not metadata:
        return "missing", {}
    model = metadata["model"]
    version = metadata["version"]
    creator = model.get("creator") if isinstance(model.get("creator"), dict) else {}
    if not creator and isinstance(version.get("creator"), dict):
        creator = version["creator"]
    images = version.get("images") if isinstance(version.get("images"), list) else []
    preview_url = images[0].get("url", "") if images and isinstance(images[0], dict) else ""
    files = version.get("files") if isinstance(version.get("files"), list) else []
    sha256 = ""
    for file_info in files:
        hashes = file_info.get("hashes") if isinstance(file_info, dict) else None
        if isinstance(hashes, dict) and hashes.get("SHA256"):
            sha256 = hashes["SHA256"]
            break
    return "cached", {
        "name": model.get("name") or version.get("modelName") or "",
        "creator": creator.get("username") or "",
        "version": version.get("name") or "",
        "model_id": model.get("id") or version.get("modelId") or "",
        "version_id": version.get("id") or "",
        "sha256": sha256,
        "trained_words": version.get("trainedWords", [])[:8] if isinstance(version.get("trainedWords"), list) else [],
        "preview_url": preview_url,
        "metadata_source": metadata_source,
        "base_model": version.get("baseModel") or "",
    }

@PromptServer.instance.routes.get("/anima-tools/lora/local")
async def lora_local_list_api(request):
    try:
        local_loras = [item["filename"] for item in scan_loras_with_info()]
        return web.json_response(local_loras)
    except Exception as e:
        print(f"[Anima Tools] Local LoRA List API error: {e}")
        return web.json_response([], status=500)

@PromptServer.instance.routes.get("/anima-tools/lora/manifest")
async def lora_manifest_api(request):
    try:
        try:
            width = max(80, min(int(request.query.get("width", "320")), 1024))
        except (ValueError, TypeError):
            width = 320

        custom_dir, custom_dir_valid, custom_dir_abs = get_custom_lora_dir_status()
        krea2_dir, krea2_dir_valid, krea2_dir_abs = get_lora_profile_dir_status("Krea 2")
        anima_resolved_dir = get_lora_save_dir(base_model="Anima")
        krea2_resolved_dir = get_lora_save_dir(base_model="Krea 2")
        items = []
        for info in scan_loras_with_info():
            filename = info["filename"]
            abs_path = info["abs_path"]
            try:
                stat = os.stat(abs_path)
            except OSError:
                continue

            preview_file = find_companion_preview(abs_path)
            cache_key = get_preview_cache_key(abs_path, preview_file)
            metadata_status, meta_summary = read_lora_meta_summary(abs_path)
            profile_key = info.get("base_model_profile", "")
            metadata_base_model = str(meta_summary.get("base_model") or "").strip()
            if not profile_key and metadata_base_model:
                try:
                    profile_key = normalize_lora_profile_key(metadata_base_model)
                except ValueError:
                    pass
            if not profile_key and len(info.get("base_model_profiles") or []) == 1:
                profile_key = info["base_model_profiles"][0]
            preview_params = {
                "filename": filename,
                "width": str(width),
                "v": cache_key,
            }
            if profile_key:
                preview_params["base_model"] = profile_key
            items.append({
                "filename": filename,
                "display_name": meta_summary.get("name") or make_display_name(filename),
                "folder": os.path.dirname(filename).replace("\\", "/"),
                "size": stat.st_size,
                "mtime": int(stat.st_mtime),
                "cache_key": cache_key,
                "thumb_url": f"/anima-tools/lora/local-preview?{urllib.parse.urlencode(preview_params)}",
                "has_preview": bool(preview_file),
                "metadata_status": metadata_status,
                "meta_summary": meta_summary,
                "source": info.get("source", "default"),
                "base_model_profile": profile_key,
                "_preview_file": preview_file,
                "_abs_path": abs_path,
            })

        items.sort(key=lambda item: item["display_name"].lower())
        for item in items[:160]:
            preview_file = item.get("_preview_file")
            if preview_file and width > 0:
                _ensure_local_thumbnail_async(preview_file, width, delay=2.0)
            elif item.get("meta_summary", {}).get("preview_url"):
                _ensure_local_preview_download_async(item.get("_abs_path"), item["meta_summary"]["preview_url"], delay=3.0)
        for item in items:
            item.pop("_preview_file", None)
            item.pop("_abs_path", None)
        return web.json_response({
            "items": items,
            "count": len(items),
            "width": width,
            "custom_lora_dir": custom_dir,
            "custom_lora_dir_valid": custom_dir_valid,
            "custom_lora_dir_abs": custom_dir_abs if custom_dir_valid else "",
            "folders": get_custom_lora_subfolders(),
            "profiles": {
                "anima": {
                    "base_model": "Anima",
                    "custom_lora_dir": custom_dir,
                    "custom_lora_dir_valid": custom_dir_valid,
                    "custom_lora_dir_abs": custom_dir_abs if custom_dir_valid else "",
                    "folders": get_custom_lora_subfolders("Anima"),
                    "resolved_save_dir": anima_resolved_dir,
                    "uses_default_dir": not bool(custom_dir),
                },
                "krea2": {
                    "base_model": "Krea 2",
                    "custom_lora_dir": krea2_dir or krea2_resolved_dir,
                    "custom_lora_dir_valid": krea2_dir_valid if krea2_dir else os.path.isdir(krea2_resolved_dir),
                    "custom_lora_dir_abs": krea2_dir_abs if krea2_dir_valid else (krea2_resolved_dir if not krea2_dir else ""),
                    "folders": get_custom_lora_subfolders("Krea 2"),
                    "resolved_save_dir": krea2_resolved_dir,
                    "uses_default_dir": not bool(krea2_dir),
                },
            },
            "generated_at": int(time.time())
        })
    except Exception as e:
        print(f"[Anima Tools] LoRA Manifest API error: {e}")
        return web.json_response({"items": [], "error": str(e)}, status=500)

@PromptServer.instance.routes.get("/anima-tools/lora/search")
async def lora_search_api(request):
    try:
        query = request.query.get("query", "")
        tag = request.query.get("tag", "")
        category = request.query.get("category", "")
        sort = request.query.get("sort", "Highest Rated")
        cursor = request.query.get("cursor", "")
        base_model = request.query.get("base_model", "Anima")
        force_refresh = request.query.get("refresh", "").strip().lower() in {"1", "true", "yes"}
        cache_only = request.query.get("cache_only", "").strip().lower() in {"1", "true", "yes"}
        limit_str = request.query.get("limit", "40")
        try:
            limit = int(limit_str)
        except ValueError:
            limit = 40
            
        result = await asyncio.to_thread(
            search_civitai_loras,
            query,
            tag,
            category,
            sort,
            cursor,
            limit,
            base_model,
            force_refresh,
            cache_only,
        )
        if cache_only and result is None:
            return web.Response(status=204, headers={"Cache-Control": "no-store"})
        return web.json_response(result or {"items": [], "metadata": {}})
    except ValueError as e:
        return web.json_response({"items": [], "error": str(e)}, status=400)
    except Exception as e:
        print(f"[Anima Tools] Search API error: {e}")
        return web.json_response({"items": [], "error": str(e)}, status=500)

@PromptServer.instance.routes.get("/anima-tools/lora/model-detail")
async def lora_model_detail_api(request):
    try:
        model_id = str(request.query.get("id", "")).strip()
        cache_only = request.query.get("cache_only", "").strip().lower() in {"1", "true", "yes"}
        if not model_id or not model_id.isdigit():
            return web.json_response({"success": False, "error": "Missing model id"}, status=400)

        model = await asyncio.to_thread(fetch_civitai_model, model_id, False, cache_only)
        if cache_only and not model:
            return web.Response(status=204, headers={"Cache-Control": "no-store"})
        if not model or (isinstance(model, dict) and model.get("error")):
            return web.json_response({"success": False, "error": "Model detail not found"}, status=404)

        source_metadata = dict(model.get("_anima_source") or {}) if isinstance(model, dict) else {}
        return web.json_response({"success": True, "model": model, "metadata": source_metadata})
    except Exception as e:
        print(f"[Anima Tools] Model Detail API error: {e}")
        return web.json_response({"success": False, "error": str(e)}, status=500)

@PromptServer.instance.routes.post("/anima-tools/lora/download")
async def lora_download_api(request):
    try:
        body = await request.json()
        version_id = body.get("version_id")
        download_url = body.get("download_url")
        filename = body.get("filename")
        subfolder = body.get("subfolder", "")
        base_model = body.get("base_model", "Anima")
        metadata = body.get("metadata")
        
        if not version_id or not download_url or not filename:
            return web.json_response({"success": False, "error": "Missing parameters"}, status=400)

        parsed_url = urllib.parse.urlparse(str(download_url))
        if parsed_url.scheme != "https" or parsed_url.netloc.lower() not in ("civitai.com", "www.civitai.com", "civitai.red"):
            return web.json_response({"success": False, "error": "Only Civitai HTTPS downloads are supported"}, status=400)
            
        task_id = start_download_task(
            version_id,
            download_url,
            filename,
            metadata=metadata,
            subfolder=subfolder,
            base_model=base_model,
        )
        return web.json_response({"success": True, "task_id": task_id})
    except ValueError as e:
        return web.json_response({"success": False, "error": str(e)}, status=400)
    except Exception as e:
        print(f"[Anima Tools] Download API error: {e}")
        return web.json_response({"success": False, "error": str(e)}, status=500)


_LOCAL_METADATA_CACHE = {}

def get_info_from_civitai_by_hash(file_hash: str) -> dict | None:
    import urllib.request
    import json
    url = f"https://civitai.red/api/v1/model-versions/by-hash/{file_hash}"
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0"}
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            return json.loads(response.read().decode("utf-8"))
    except Exception:
        return None

@PromptServer.instance.routes.get("/anima-tools/lora/local-metadata")
async def lora_local_metadata_api(request):
    try:
        filename = request.query.get("filename", "")
        base_model = request.query.get("base_model", "")
        if not filename:
            return web.json_response({"success": False, "error": "Missing filename"}, status=400)
        filename = normalize_lora_filename(filename)
        if not filename:
            return web.json_response({"success": False, "error": "Invalid filename"}, status=400)
        profile_key = normalize_lora_profile_key(base_model) if str(base_model or "").strip() else ""
        metadata_cache_key = f"{profile_key}:{filename}"
        
        # Try metadata cache first
        if metadata_cache_key in _LOCAL_METADATA_CACHE:
            return web.json_response({"success": True, "metadata": _LOCAL_METADATA_CACHE[metadata_cache_key]})
            
        abs_path = resolve_lora_abs_path(filename, profile_key)
            
        if abs_path and os.path.exists(abs_path):
            local_metadata, metadata_source = read_lora_full_metadata(abs_path)
            if local_metadata:
                local_model = local_metadata.get("model", {})
                local_version = local_metadata.get("version", {})
                is_complete = (
                    isinstance(local_model.get("modelVersions"), list)
                    and isinstance(local_model.get("creator"), dict)
                    and isinstance(local_version.get("files"), list)
                )
                if metadata_source == "lora_manager" or is_complete:
                    _LOCAL_METADATA_CACHE[metadata_cache_key] = local_metadata
                    return web.json_response({"success": True, "metadata": local_metadata})

            meta_path = resolve_lora_companion_path(abs_path, ".json", must_exist=False)
            if not meta_path:
                return web.json_response({"success": False, "error": "Invalid metadata path"}, status=403)
            
            # 1. 优先读取已存在的本地 JSON 配置文件（支持旧版格式自动升级与自愈）
            if os.path.exists(meta_path):
                try:
                    with open(meta_path, "r", encoding="utf-8") as f:
                        meta_data = json.load(f)
                    # 检查是否是包含 files、modelVersions 和 creator（作者）的新版完整格式，如果是则直接返回
                    if (isinstance(meta_data, dict) and 
                        "version" in meta_data and "files" in meta_data["version"] and 
                        "model" in meta_data and "modelVersions" in meta_data["model"] and
                        "creator" in meta_data["model"]):
                        _LOCAL_METADATA_CACHE[metadata_cache_key] = meta_data
                        return web.json_response({"success": True, "metadata": meta_data})
                    else:
                        print(f"[Anima Tools] Legacy local metadata found for {filename}, regenerating to fetch complete fields...")
                except Exception:
                    pass
                
            # 2. 如果不存在（或为旧版非完整格式），计算 SHA256 哈希值，从 Civitai 反向抓取元数据
            print(f"[Anima Tools] Resolving complete metadata for {filename}...")
            try:
                h = hashlib.sha256()
                with open(abs_path, 'rb') as f:
                    for chunk in iter(lambda: f.read(4096 * 1024), b''): # 4MB chunk
                        h.update(chunk)
                file_hash = h.hexdigest().upper()
                
                info = await asyncio.to_thread(get_info_from_civitai_by_hash, file_hash)
                if info and "error" not in info:
                    # 二次查询模型完整元数据，获取作者 (creator) 及其它版本详情和高质量预览图
                    model_id = info.get("modelId")
                    full_model = None
                    if model_id:
                        try:
                            full_model = fetch_civitai_model(model_id)
                        except Exception:
                            full_model = None
                            
                    # 组装符合前端所需的全包元数据格式
                    version_info = {
                        "id": info.get("id"),
                        "name": info.get("name"),
                        "trainedWords": info.get("trainedWords", []),
                        "images": info.get("images", []),
                        "files": info.get("files", []),
                        "downloadUrl": info.get("downloadUrl", ""),
                        "description": info.get("description", "")
                    }
                    
                    if full_model and "error" not in full_model:
                        model_info = full_model.copy()
                        # 补全或覆盖 modelVersions
                        model_info["modelVersions"] = full_model.get("modelVersions", [version_info])
                    else:
                        model_info = info.get("model", {}).copy()
                        model_info["modelVersions"] = [version_info]
                        model_info["description"] = info.get("description", "")
                    
                    meta_data = {
                        "model": model_info,
                        "version": version_info
                    }
                    # 自动保存本地同名 JSON 伴随文件，后续便可秒开
                    with open(meta_path, "w", encoding="utf-8") as f:
                        json.dump(meta_data, f, indent=2, ensure_ascii=False)
                        
                    # 尝试自动补齐本地 LoRA 的封面图！这样之前没有封面图的也能自动显示 C 站封面
                    images = info.get("images", [])
                    if images:
                        preview_url = images[0].get("url")
                        if preview_url:
                            preview_ext = ".png"
                            if ".jpg" in preview_url.lower() or ".jpeg" in preview_url.lower():
                                preview_ext = ".jpg"
                            elif ".webp" in preview_url.lower():
                                preview_ext = ".webp"
                            
                            preview_path = resolve_lora_companion_path(abs_path, preview_ext, must_exist=False)
                            if preview_path and not os.path.exists(preview_path):
                                # 后台多线程异步下载图片，防止阻塞 metadata 请求
                                threading.Thread(
                                    target=download_preview_image,
                                    args=(preview_url, preview_path),
                                    daemon=True
                                ).start()
                                
                    _LOCAL_METADATA_CACHE[metadata_cache_key] = meta_data
                    return web.json_response({"success": True, "metadata": meta_data})
            except Exception as ex:
                print(f"[Anima Tools] Auto-metadata recovery failed for {filename}: {ex}")
                
        return web.json_response({"success": False, "error": "Metadata not found"}, status=404)
    except Exception as e:
        print(f"[Anima Tools] Get Local Metadata API error: {e}")
        return web.json_response({"success": False, "error": str(e)}, status=500)


# 缩略图磁盘缓存目录，放在 user 下以便 ComfyUI 重启和插件升级后继续复用
_THUMB_CACHE_DIR = os.path.join(get_anima_tools_user_dir(), "thumb_cache")
_REMOTE_THUMB_CACHE_DIR = os.path.join(get_anima_tools_user_dir(), "remote_thumb_cache")
_REMOTE_THUMB_INDEX_PATH = os.path.join(_REMOTE_THUMB_CACHE_DIR, "index.json")
_LOCAL_THUMB_JOBS = set()
_LOCAL_THUMB_QUEUE = []
_LOCAL_THUMB_WORKER_ACTIVE = False
_LOCAL_THUMB_LOCK = threading.Lock()
_LOCAL_PREVIEW_DOWNLOAD_JOBS = set()
_LOCAL_PREVIEW_DOWNLOAD_QUEUE = []
_LOCAL_PREVIEW_DOWNLOAD_WORKER_ACTIVE = False
_LOCAL_PREVIEW_DOWNLOAD_LOCK = threading.Lock()

def _preview_extension_from_url(url: str) -> str:
    lower = (url or "").lower()
    if ".jpg" in lower or ".jpeg" in lower:
        return ".jpg"
    if ".webp" in lower:
        return ".webp"
    return ".png"

def _local_preview_download_worker(delay: float = 0.0) -> None:
    global _LOCAL_PREVIEW_DOWNLOAD_WORKER_ACTIVE
    if delay > 0:
        time.sleep(delay)
    while True:
        with _LOCAL_PREVIEW_DOWNLOAD_LOCK:
            if not _LOCAL_PREVIEW_DOWNLOAD_QUEUE:
                _LOCAL_PREVIEW_DOWNLOAD_WORKER_ACTIVE = False
                return
            image_url, preview_path, job_key = _LOCAL_PREVIEW_DOWNLOAD_QUEUE.pop(0)
        try:
            if not os.path.exists(preview_path):
                download_preview_image(image_url, preview_path)
        finally:
            with _LOCAL_PREVIEW_DOWNLOAD_LOCK:
                _LOCAL_PREVIEW_DOWNLOAD_JOBS.discard(job_key)

def _ensure_local_preview_download_async(abs_path: str, image_url: str, delay: float = 3.0) -> None:
    global _LOCAL_PREVIEW_DOWNLOAD_WORKER_ACTIVE
    if not abs_path or not image_url or not image_url.lower().startswith(("http://", "https://")):
        return
    preview_path = resolve_lora_companion_path(abs_path, _preview_extension_from_url(image_url), must_exist=False)
    if not preview_path:
        return
    if os.path.exists(preview_path):
        return
    job_key = f"{preview_path}:{image_url}"
    with _LOCAL_PREVIEW_DOWNLOAD_LOCK:
        if job_key in _LOCAL_PREVIEW_DOWNLOAD_JOBS:
            return
        _LOCAL_PREVIEW_DOWNLOAD_JOBS.add(job_key)
        _LOCAL_PREVIEW_DOWNLOAD_QUEUE.append((image_url, preview_path, job_key))
        if _LOCAL_PREVIEW_DOWNLOAD_WORKER_ACTIVE:
            return
        _LOCAL_PREVIEW_DOWNLOAD_WORKER_ACTIVE = True
    threading.Thread(target=_local_preview_download_worker, args=(delay,), daemon=True).start()

def _thumbnail_cache_path(preview_file: str, target_width: int) -> str:
    stat = os.stat(preview_file)
    cache_key = hashlib.sha256(
        f"{os.path.abspath(preview_file)}|{int(stat.st_mtime)}|{stat.st_size}|{target_width}".encode("utf-8", errors="ignore")
    ).hexdigest()
    return os.path.join(_THUMB_CACHE_DIR, f"{cache_key}.webp")

def _get_thumbnail(preview_file: str, target_width: int, generate: bool = True) -> tuple[bytes, str] | None:
    """生成并缓存缩略图，返回 (图片bytes, content_type) 或 None"""
    if Image is None:
        return None

    # 视频文件不处理缩略图
    ext_lower = os.path.splitext(preview_file)[1].lower()
    if ext_lower in (".mp4", ".webm", ".gif"):
        return None

    # 检查磁盘缓存
    cache_path = _thumbnail_cache_path(preview_file, target_width)

    if os.path.exists(cache_path):
        with open(cache_path, "rb") as f:
            return f.read(), "image/webp"
    if not generate:
        return None

    try:
        img = Image.open(preview_file)
        img = img.convert("RGB")
        if target_width > 0 and img.width > target_width:
            ratio = target_width / img.width
            new_size = (target_width, int(img.height * ratio))
            img = img.resize(new_size, Image.LANCZOS)

        buf = BytesIO()
        img.save(buf, format="WEBP", quality=82)
        thumb_data = buf.getvalue()

        # 写入磁盘缓存
        os.makedirs(_THUMB_CACHE_DIR, exist_ok=True)
        with open(cache_path, "wb") as f:
            f.write(thumb_data)

        return thumb_data, "image/webp"
    except Exception as e:
        print(f"[Anima Tools] Thumbnail generation failed: {e}")
        return None

def _warm_local_thumbnail(preview_file: str, target_width: int) -> None:
    try:
        _get_thumbnail(preview_file, target_width, generate=True)
    finally:
        job_key = f"{preview_file}:{target_width}"
        with _LOCAL_THUMB_LOCK:
            _LOCAL_THUMB_JOBS.discard(job_key)

def _local_thumbnail_worker(delay: float = 0.0) -> None:
    global _LOCAL_THUMB_WORKER_ACTIVE
    if delay > 0:
        time.sleep(delay)
    while True:
        with _LOCAL_THUMB_LOCK:
            if not _LOCAL_THUMB_QUEUE:
                _LOCAL_THUMB_WORKER_ACTIVE = False
                return
            preview_file, target_width = _LOCAL_THUMB_QUEUE.pop(0)
        _warm_local_thumbnail(preview_file, target_width)

def _ensure_local_thumbnail_async(preview_file: str, target_width: int, delay: float = 0.0) -> None:
    global _LOCAL_THUMB_WORKER_ACTIVE
    if Image is None or target_width <= 0:
        return
    try:
        cache_path = _thumbnail_cache_path(preview_file, target_width)
        if os.path.exists(cache_path):
            return
    except Exception:
        return
    job_key = f"{preview_file}:{target_width}"
    with _LOCAL_THUMB_LOCK:
        if job_key in _LOCAL_THUMB_JOBS:
            return
        _LOCAL_THUMB_JOBS.add(job_key)
        _LOCAL_THUMB_QUEUE.append((preview_file, target_width))
        if _LOCAL_THUMB_WORKER_ACTIVE:
            return
        _LOCAL_THUMB_WORKER_ACTIVE = True
    threading.Thread(target=_local_thumbnail_worker, args=(delay,), daemon=True).start()

def _placeholder_svg_response(cache_control: str = "no-store") -> web.Response:
    svg_content = (
        "<svg xmlns='http://www.w3.org/2000/svg' width='100' height='100' viewBox='0 0 100 100'>"
        "<rect width='100' height='100' fill='#222'/>"
        "<text x='50%' y='50%' font-size='10' fill='#666' dominant-baseline='middle' text-anchor='middle'>No Preview</text>"
        "</svg>"
    )
    return web.Response(body=svg_content, content_type="image/svg+xml", headers={"Cache-Control": cache_control})

_REMOTE_THUMB_JOBS = set()
_REMOTE_THUMB_LOCK = threading.Lock()
_REMOTE_THUMB_INDEX_LOCK = threading.Lock()
_CIVITAI_UUID_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
    re.IGNORECASE
)

def _clear_cache_directory(directory: str) -> tuple[int, int, list[str]]:
    deleted_count = 0
    deleted_bytes = 0
    errors = []
    if not os.path.isdir(directory):
        return deleted_count, deleted_bytes, errors

    for name in os.listdir(directory):
        path = os.path.join(directory, name)
        if not os.path.isfile(path):
            continue
        try:
            deleted_bytes += os.path.getsize(path)
            os.remove(path)
            deleted_count += 1
        except Exception as e:
            errors.append(f"{name}: {e}")
    return deleted_count, deleted_bytes, errors

def _remote_thumb_cache_path(cache_key: str, width: int) -> str:
    safe_key = "".join(ch for ch in cache_key if ch.isalnum())[:80] or "remote"
    return os.path.join(_REMOTE_THUMB_CACHE_DIR, f"{safe_key}_{width}.webp")

def _remote_thumb_content_cache_path(content_hash: str, width: int) -> str:
    safe_hash = "".join(ch for ch in content_hash if ch.isalnum())[:80] or "content"
    return os.path.join(_REMOTE_THUMB_CACHE_DIR, f"content_{safe_hash}_{width}.webp")

def _remote_thumb_index_key(cache_key: str, width: int) -> str:
    return f"{cache_key}:{width}"

def _load_remote_thumb_index_unlocked() -> dict:
    try:
        if not os.path.exists(_REMOTE_THUMB_INDEX_PATH):
            return {}
        with open(_REMOTE_THUMB_INDEX_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}

def _save_remote_thumb_index_unlocked(index: dict) -> None:
    os.makedirs(_REMOTE_THUMB_CACHE_DIR, exist_ok=True)
    tmp_path = _REMOTE_THUMB_INDEX_PATH + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp_path, _REMOTE_THUMB_INDEX_PATH)

def _set_remote_thumb_index(cache_key: str, width: int, cache_path: str) -> None:
    if not cache_key or not cache_path:
        return
    with _REMOTE_THUMB_INDEX_LOCK:
        index = _load_remote_thumb_index_unlocked()
        index[_remote_thumb_index_key(cache_key, width)] = os.path.basename(cache_path)
        _save_remote_thumb_index_unlocked(index)

def _find_remote_thumb_indexed_path(cache_key: str, width: int) -> str:
    if not cache_key:
        return ""
    direct_path = _remote_thumb_cache_path(cache_key, width)
    if os.path.exists(direct_path):
        return direct_path
    with _REMOTE_THUMB_INDEX_LOCK:
        index = _load_remote_thumb_index_unlocked()
        cached_name = index.get(_remote_thumb_index_key(cache_key, width))
    if not cached_name:
        return ""
    indexed_path = os.path.join(_REMOTE_THUMB_CACHE_DIR, os.path.basename(cached_name))
    return indexed_path if os.path.exists(indexed_path) else ""

def _find_remote_thumb_cache(cache_keys: list[str], width: int) -> tuple[str, str]:
    for cache_key in cache_keys:
        cache_path = _find_remote_thumb_indexed_path(cache_key, width)
        if cache_path:
            return cache_path, cache_key
    return "", ""

def _extract_civitai_image_id(url: str) -> str:
    if not url or "civitai" not in url.lower():
        return ""
    try:
        parsed = urllib.parse.urlparse(url)
        path = urllib.parse.unquote(parsed.path or "")
    except Exception:
        path = str(url)

    cache_match = re.search(r"/civitai-media-cache/([^/]+)", path, re.IGNORECASE)
    if cache_match:
        return cache_match.group(1)

    uuid_match = _CIVITAI_UUID_RE.search(path)
    if uuid_match:
        return uuid_match.group(0).lower()

    numeric_match = re.search(r"/images/(\d+)", path, re.IGNORECASE)
    if numeric_match:
        return numeric_match.group(1)
    return ""

def _normalize_remote_source_url(url: str) -> str:
    try:
        parsed = urllib.parse.urlparse(url)
        query = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
        query = [
            (key, value)
            for key, value in query
            if key.lower() not in {"width", "height", "format", "quality"}
        ]
        query.sort()
        return urllib.parse.urlunparse((
            parsed.scheme.lower(),
            parsed.netloc.lower(),
            urllib.parse.unquote(parsed.path or ""),
            "",
            urllib.parse.urlencode(query),
            ""
        ))
    except Exception:
        return url

def _remote_thumb_stable_cache_key(source_url: str, image_id: str = "", url_hash: str = "") -> str:
    stable_image_id = image_id or _extract_civitai_image_id(source_url)
    if stable_image_id:
        safe_image_id = "".join(ch for ch in stable_image_id if ch.isalnum()).lower()
        if safe_image_id:
            return f"civitai{safe_image_id}"
    if source_url:
        normalized_url = _normalize_remote_source_url(source_url)
        return hashlib.sha256(normalized_url.encode("utf-8", errors="ignore")).hexdigest()
    return "".join(ch for ch in url_hash if ch.isalnum()) or ""

def _remote_thumb_cache_keys(source_url: str, image_id: str, url_hash: str) -> list[str]:
    keys = []
    stable_key = _remote_thumb_stable_cache_key(source_url, image_id, url_hash)
    if stable_key:
        keys.append(stable_key)
    if source_url:
        legacy_key = hashlib.sha256(source_url.encode("utf-8", errors="ignore")).hexdigest()
        keys.append(legacy_key)
    if url_hash:
        keys.append(url_hash)

    unique_keys = []
    for key in keys:
        if key and key not in unique_keys:
            unique_keys.append(key)
    return unique_keys

def _write_remote_thumbnail_content(cache_key: str, width: int, thumb_data: bytes) -> str:
    os.makedirs(_REMOTE_THUMB_CACHE_DIR, exist_ok=True)
    content_hash = hashlib.sha256(thumb_data).hexdigest()
    content_path = _remote_thumb_content_cache_path(content_hash, width)
    if not os.path.exists(content_path):
        tmp_path = content_path + ".tmp"
        with open(tmp_path, "wb") as f:
            f.write(thumb_data)
        os.replace(tmp_path, content_path)
    _set_remote_thumb_index(cache_key, width, content_path)
    return content_path

def _fetch_remote_thumbnail(url: str, cache_key: str, width: int) -> str:
    if Image is None:
        return ""
    cached_path = _find_remote_thumb_indexed_path(cache_key, width)
    if cached_path:
        return cached_path

    req = urllib.request.Request(url, headers={"User-Agent": "ComfyUI-Anima-Tools/1.0"})
    with open_civitai_preview_url(req, timeout=30) as resp:
        data = resp.read()

    img = Image.open(BytesIO(data)).convert("RGB")
    if width > 0 and img.width > width:
        ratio = width / img.width
        img = img.resize((width, int(img.height * ratio)), Image.LANCZOS)

    buf = BytesIO()
    img.save(buf, format="WEBP", quality=82)
    return _write_remote_thumbnail_content(cache_key, width, buf.getvalue())


def _download_remote_thumbnail(url: str, cache_key: str, width: int, job_key: str) -> None:
    try:
        _fetch_remote_thumbnail(url, cache_key, width)
    except Exception as e:
        print(f"[Anima Tools] Remote preview cache failed: {e}")
    finally:
        with _REMOTE_THUMB_LOCK:
            _REMOTE_THUMB_JOBS.discard(job_key)

@PromptServer.instance.routes.get("/anima-tools/lora/remote-preview")
async def lora_remote_preview_api(request):
    try:
        try:
            width = max(80, min(int(request.query.get("width", "320")), 1024))
        except (ValueError, TypeError):
            width = 320

        source_url = request.query.get("url", "").strip()
        url_hash = request.query.get("url_hash", "").strip()
        image_id = request.query.get("image_id", "").strip()
        miss_mode = request.query.get("miss", "").strip().lower()
        cache_keys = _remote_thumb_cache_keys(source_url, image_id, url_hash)

        if not cache_keys:
            return _placeholder_svg_response()

        cache_key = cache_keys[0]
        cache_path, matched_key = _find_remote_thumb_cache(cache_keys, width)
        if cache_path:
            if matched_key != cache_key:
                _set_remote_thumb_index(cache_key, width, cache_path)
            resp = web.FileResponse(cache_path)
            resp.headers["Cache-Control"] = "public, max-age=31536000, immutable"
            return resp

        if source_url and source_url.lower().startswith(("http://", "https://")):
            try:
                cache_path = await asyncio.to_thread(
                    _fetch_remote_thumbnail,
                    source_url,
                    cache_key,
                    width,
                )
                if cache_path:
                    resp = web.FileResponse(cache_path)
                    resp.headers["Cache-Control"] = "public, max-age=31536000, immutable"
                    return resp
            except Exception as e:
                print(f"[Anima Tools] Remote preview fetch failed: {e}")

        if miss_mode in {"redirect", "direct"} and source_url:
            raise web.HTTPFound(
                source_url,
                headers={"Cache-Control": "no-store", "X-Anima-Preview-Cache": "WARMING"},
            )
        if miss_mode == "error":
            return web.Response(status=202, headers={"Cache-Control": "no-store", "Retry-After": "1"})
        return _placeholder_svg_response("no-store")
    except web.HTTPException:
        raise
    except Exception as e:
        print(f"[Anima Tools] Remote Preview API error: {e}")
        return _placeholder_svg_response()

@PromptServer.instance.routes.get("/anima-tools/lora/local-preview")
async def lora_local_preview_api(request):
    try:
        filename = request.query.get("filename", "")
        base_model = request.query.get("base_model", "")
        if not filename:
            return web.Response(status=400)
        
        # 解析目标缩略图宽度（默认不缩放以保持向后兼容）
        try:
            target_width = int(request.query.get("width", "0"))
        except (ValueError, TypeError):
            target_width = 0
            
        filename = normalize_lora_filename(filename)
        if not filename:
            return web.Response(status=400)
        abs_path = resolve_lora_abs_path(filename, base_model)
            
        if abs_path and os.path.exists(abs_path):
            preview_file = find_companion_preview(abs_path)
            if preview_file:
                immutable_cache = "public, max-age=31536000, immutable" if request.query.get("v") else "public, max-age=86400"
                if target_width > 0:
                    thumb = await asyncio.to_thread(_get_thumbnail, preview_file, target_width, generate=False)
                    if thumb:
                        thumb_data, content_type = thumb
                        return web.Response(
                            body=thumb_data,
                            content_type=content_type,
                            headers={"Cache-Control": immutable_cache}
                        )
                resp = web.FileResponse(preview_file)
                resp.headers["Cache-Control"] = immutable_cache
                return resp
                    
        # 找不到本地预览图时，返回默认的 No Preview 占位图，状态设为 200，防止控制台大量 404 报错
        return _placeholder_svg_response("public, max-age=3600")
    except Exception as e:
        print(f"[Anima Tools] Local Preview API error: {e}")
        return web.Response(status=500)

@PromptServer.instance.routes.post("/anima-tools/lora/clear-cache")
async def lora_clear_cache_api(request):
    try:
        with _LOCAL_THUMB_LOCK:
            _LOCAL_THUMB_JOBS.clear()
            _LOCAL_THUMB_QUEUE.clear()
        with _REMOTE_THUMB_LOCK:
            _REMOTE_THUMB_JOBS.clear()

        local_count, local_bytes, local_errors = _clear_cache_directory(_THUMB_CACHE_DIR)
        remote_count, remote_bytes, remote_errors = _clear_cache_directory(_REMOTE_THUMB_CACHE_DIR)
        errors = local_errors + remote_errors

        return web.json_response({
            "success": len(errors) == 0,
            "deleted_files": local_count + remote_count,
            "deleted_bytes": local_bytes + remote_bytes,
            "local_thumb_cache": {
                "path": _THUMB_CACHE_DIR,
                "deleted_files": local_count,
                "deleted_bytes": local_bytes,
            },
            "remote_thumb_cache": {
                "path": _REMOTE_THUMB_CACHE_DIR,
                "deleted_files": remote_count,
                "deleted_bytes": remote_bytes,
            },
            "errors": errors[:20],
        })
    except Exception as e:
        print(f"[Anima Tools] Clear LoRA cache API error: {e}")
        return web.json_response({"success": False, "error": str(e)}, status=500)

@PromptServer.instance.routes.get("/anima-tools/lora/download-status")
async def lora_download_status_api(request):
    try:
        task_id = request.query.get("task_id", "")
        if not task_id:
            from .anima_lora_api import get_all_download_jobs
            return web.json_response(get_all_download_jobs())
            
        status_info = get_download_job_status(task_id)
        if not status_info:
            return web.json_response({"status": "not_found"}, status=404)
        return web.json_response(status_info)
    except Exception as e:
        print(f"[Anima Tools] Download Status API error: {e}")
        return web.json_response({"error": str(e)}, status=500)

@PromptServer.instance.routes.get("/anima-tools/lora/config")
async def lora_get_config_api(request):
    try:
        config = dict(load_lora_config())
        config["resolved_save_dir"] = get_lora_save_dir(base_model="Anima")
        config["resolved_save_dirs"] = {
            "anima": get_lora_save_dir(base_model="Anima"),
            "krea2": get_lora_save_dir(base_model="Krea 2"),
        }
        custom_dir, custom_dir_valid, custom_dir_abs = get_custom_lora_dir_status()
        krea2_dir, krea2_dir_valid, krea2_dir_abs = get_lora_profile_dir_status("Krea 2")
        config["custom_lora_dir"] = custom_dir
        config["custom_lora_dir_valid"] = custom_dir_valid
        config["custom_lora_dir_abs"] = custom_dir_abs if custom_dir_valid else ""
        config["krea2_lora_dir"] = krea2_dir
        config["krea2_lora_dir_valid"] = krea2_dir_valid
        config["krea2_lora_dir_abs"] = krea2_dir_abs if krea2_dir_valid else ""
        return web.json_response(config)
    except Exception as e:
        print(f"[Anima Tools] Get Config API error: {e}")
        return web.json_response({"error": str(e)}, status=500)

@PromptServer.instance.routes.post("/anima-tools/lora/config")
async def lora_save_config_api(request):
    try:
        body = await request.json()
        current_config = load_lora_config()
        config = {
            "custom_lora_dir": current_config.get("custom_lora_dir", ""),
            "krea2_lora_dir": current_config.get("krea2_lora_dir", ""),
            "civitai_api_key": current_config.get("civitai_api_key", ""),
            "civitai_image_proxy": current_config.get("civitai_image_proxy", "")
        }
        if "custom_lora_dir" in body:
            config["custom_lora_dir"] = body["custom_lora_dir"]
        if "krea2_lora_dir" in body:
            config["krea2_lora_dir"] = body["krea2_lora_dir"]
        if "civitai_api_key" in body:
            config["civitai_api_key"] = body["civitai_api_key"]
        if "civitai_image_proxy" in body:
            config["civitai_image_proxy"] = body["civitai_image_proxy"]
            
        success = save_lora_config(config)
        custom_dir, custom_dir_valid, custom_dir_abs = get_custom_lora_dir_status()
        krea2_dir, krea2_dir_valid, krea2_dir_abs = get_lora_profile_dir_status("Krea 2")
        return web.json_response({
            "success": success,
            "resolved_save_dir": get_lora_save_dir(base_model="Anima"),
            "resolved_save_dirs": {
                "anima": get_lora_save_dir(base_model="Anima"),
                "krea2": get_lora_save_dir(base_model="Krea 2"),
            },
            "custom_lora_dir": custom_dir,
            "custom_lora_dir_valid": custom_dir_valid,
            "custom_lora_dir_abs": custom_dir_abs if custom_dir_valid else "",
            "krea2_lora_dir": krea2_dir,
            "krea2_lora_dir_valid": krea2_dir_valid,
            "krea2_lora_dir_abs": krea2_dir_abs if krea2_dir_valid else "",
        })
    except Exception as e:
        print(f"[Anima Tools] Save Config API error: {e}")
        return web.json_response({"success": False, "error": str(e)}, status=500)


def delete_local_lora_files(filename: str, base_model: str = "") -> bool:
    """Helper to delete a local LoRA model and its companion meta files."""
    try:
        # 统一将反斜杠替换为正斜杠，防止 Windows 路径转义解析错误
        filename = normalize_lora_filename(filename)
        if not filename:
            return False
        
        # Invalidate metadata cache
        profile_key = normalize_lora_profile_key(base_model) if str(base_model or "").strip() else ""
        _LOCAL_METADATA_CACHE.pop(f"{profile_key}:{filename}", None)
        
        abs_path = resolve_lora_abs_path(filename, profile_key)
            
        if not abs_path:
            return False
            
        abs_path = str(Path(abs_path).resolve())
        if not is_lora_path_contained(abs_path):
            return False
        
        if not os.path.exists(abs_path):
            # 如果主模型文件都不存在，我们也尝试看看有没有残留的伴随文件
            print(f"[Anima Tools] Model file {abs_path} not found, checking companion files...")
            
        deleted_any = False

        # 1. 尝试删除 Anima Tools / LoRA Manager companion JSON metadata
        for meta_file in get_lora_metadata_candidates(abs_path):
            try:
                os.remove(meta_file)
                print(f"[Anima Tools] Successfully deleted companion meta JSON: {meta_file}")
                deleted_any = True
            except Exception as e:
                print(f"[Anima Tools] Failed to delete companion meta JSON {meta_file}: {e}")
                
        # 2. 尝试删除 companion preview images (支持同名和带 .preview 后缀的预览图)
        preview_extensions = [".png", ".jpg", ".jpeg", ".webp", ".gif", ".mp4", ".webm"]
        for ext in preview_extensions:
            for suffix in ["", ".preview"]:
                preview_file = resolve_lora_companion_path(abs_path, ext, suffix=suffix, must_exist=True)
                if preview_file:
                    try:
                        os.remove(preview_file)
                        print(f"[Anima Tools] Successfully deleted preview image: {preview_file}")
                        deleted_any = True
                    except Exception as e:
                        print(f"[Anima Tools] Failed to delete preview image {preview_file}: {e}")
                    
        # 3. 尝试删除主模型文件
        model_deleted = False
        if os.path.exists(abs_path) and is_lora_path_contained(abs_path):
            try:
                os.remove(abs_path)
                print(f"[Anima Tools] Successfully deleted main model file: {abs_path}")
                model_deleted = True
            except Exception as e:
                print(f"[Anima Tools] Failed to delete main model file {abs_path} (it might be locked or in-use by ComfyUI): {e}")
                
        return model_deleted or deleted_any
    except Exception as e:
        print(f"[Anima Tools] Error deleting local LoRA files: {e}")
        return False


@PromptServer.instance.routes.post("/anima-tools/lora/delete-local")
async def lora_delete_local_api(request):
    try:
        body = await request.json()
        filename = body.get("filename", "")
        base_model = body.get("base_model", "")
        if not filename:
            return web.json_response({"success": False, "error": "Missing filename"}, status=400)
            
        success = delete_local_lora_files(filename, base_model)
        if success:
            # Refresh local lists in memory if cached, though ComfyUI usually handles dynamically
            return web.json_response({"success": True})
        else:
            return web.json_response({"success": False, "error": "File not found or failed to delete"}, status=404)
    except Exception as e:
        print(f"[Anima Tools] Delete Local API error: {e}")
        return web.json_response({"success": False, "error": str(e)}, status=500)
