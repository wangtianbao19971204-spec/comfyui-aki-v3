class StringClearIfContains:
    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "text": ("STRING", {"forceInput": True}),
                # mỗi dòng 1 từ khóa
                "filter_keywords": ("STRING", {"default": "man\nwoman"}),
                "case_sensitive": ("BOOLEAN", {"default": False}),
            }
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("output",)
    FUNCTION = "process"
    CATEGORY = "custom/sortlist"

    def process(self, text, filter_keywords, case_sensitive):
        # Chuẩn bị danh sách keyword
        keywords = [k.strip() for k in filter_keywords.split("\n") if k.strip()]

        if not case_sensitive:
            text_to_check = text.lower()
            keywords_lower = [k.lower() for k in keywords]
        else:
            text_to_check = text
            keywords_lower = keywords

        found_keywords = []

        # Tìm tất cả keyword theo đúng thứ tự
        for original_kw, check_kw in zip(keywords, keywords_lower):
            if check_kw in text_to_check:
                found_keywords.append(original_kw)

        # Nếu không có keyword nào → giữ lại toàn bộ text gốc
        if len(found_keywords) == 0:
            return (text,)

        # Có keyword → chỉ trả về các keyword, ghép bằng dấu phẩy
        return (",".join(found_keywords),)


NODE_CLASS_MAPPINGS = {
    "string_clear_if_contains": StringClearIfContains
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "string_clear_if_contains": "String Extract Keywords"
}
