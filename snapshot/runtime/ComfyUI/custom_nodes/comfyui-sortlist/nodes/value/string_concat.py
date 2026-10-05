"""
StringConcatMulti - Gộp cố định 10 STRING input thành 1 list.
Hoàn toàn tĩnh bằng Python, không sử dụng Javascript để tránh lỗi giao diện.
"""

class StringConcatMulti:
    """
    Nhận cố định 10 STRING input.
    Gộp tất cả lại thành 1 string duy nhất (có thể nhiều dòng).
    Sau đó phân tách các dòng tạo thành một STRING list.
    """

    @classmethod
    def INPUT_TYPES(cls):
        optional_inputs = {}
        for i in range(1, 11):
            optional_inputs[f"string_{i}"] = ("STRING", {"forceInput": True})

        return {
            "required": {},
            "optional": optional_inputs,
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("string_list",)
    OUTPUT_IS_LIST = (True,)
    FUNCTION = "build"
    CATEGORY = "sortlist/value"
    DESCRIPTION = (
        "Gộp tối đa 10 STRING input lại, sau đó tách mỗi dòng thành 1 phần tử danh sách (LIST). "
        "Hoàn toàn dùng Python, không lỗi giao diện."
    )

    def build(self, **kwargs):
        texts = []
        
        # Đọc dữ liệu từ 10 slot tĩnh
        for i in range(1, 11):
            key = f"string_{i}"
            val = kwargs.get(key)
            if val is not None and str(val).strip():
                texts.append(str(val))
                
        # Gộp tất cả string đã nhận
        full_text = "\n".join(texts)
        
        # Tách từng dòng làm 1 string trong list (bỏ qua dòng trống)
        result = [line.strip() for line in full_text.split("\n") if line.strip()]

        # Đảm bảo luôn trả về ít nhất 1 phần tử để tránh lỗi downstream
        if not result:
            result = [""]

        return (result,)


NODE_CLASS_MAPPINGS = {
    "StringConcatMulti": StringConcatMulti,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "StringConcatMulti": "String Concat Multi 🔤",
}
