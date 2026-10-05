import os
import re
import random


class SortListString:
    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "list_string": ("STRING", {"forceInput": True}),
                "sort_method": (
                    [
                        "default",       # so sánh nguyên chuỗi
                        "filename",      # theo tên file
                        "parent_folder", # theo thư mục cha
                        "full_path",     # giống default
                        "numeric",       # sort theo số trong tên file (LTT-1,2,3,...)
                        "date",          # sort theo chuỗi số kiểu ngày
                        "random",        # xáo trộn
                    ],
                    {"default": "numeric"},
                ),
                "sort_ascending": ("BOOLEAN", {"default": True}),
            }
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("sorted_list",)
    FUNCTION = "sort_list"
    CATEGORY = "custom/sortlist"

    # ---------- Helpers ----------

    @staticmethod
    def _get_filename(path: str) -> str:
        return os.path.basename(path)

    @staticmethod
    def _get_parent_folder(path: str) -> str:
        return os.path.basename(os.path.dirname(path))

    @staticmethod
    def _natural_numeric_key(text: str):
        """
        Natural sort theo tất cả các cụm số trong chuỗi.

        'LTT-1_00001.mp4'   -> (1, 1)
        'LTT-10_00001.mp4'  -> (10, 1)
        'LTT-35_00001.mp4'  -> (35, 1)
        """
        nums = re.findall(r'\d+', text)
        if not nums:
            return (99999999,)
        return tuple(int(n) for n in nums)

    @staticmethod
    def _date_key(text: str):
        """
        Sort kiểu 'date' đơn giản: ghép tất cả số lại thành một int.
        """
        nums = re.findall(r'\d+', text)
        if not nums:
            return 0
        return int("".join(nums))

    # ---------- Main ----------

    def sort_list(self, list_string, sort_method, sort_ascending):
        # Tách từng dòng thành 1 phần tử
        items = [i.strip() for i in list_string.split("\n") if i.strip()]

        if not items:
            return ("",)

        # Chọn key sort theo sort_method
        if sort_method in ("default", "full_path"):
            key_func = lambda x: x
        elif sort_method == "filename":
            key_func = lambda x: self._get_filename(x)
        elif sort_method == "parent_folder":
            key_func = lambda x: self._get_parent_folder(x)
        elif sort_method == "numeric":
            key_func = lambda x: self._natural_numeric_key(self._get_filename(x))
        elif sort_method == "date":
            key_func = lambda x: self._date_key(self._get_filename(x))
        elif sort_method == "random":
            random_items = items[:]
            random.shuffle(random_items)
            return ("\n".join(random_items),)
        else:
            key_func = lambda x: x

        items_sorted = sorted(
            items,
            key=key_func,
            reverse=not sort_ascending
        )

        return ("\n".join(items_sorted),)


NODE_CLASS_MAPPINGS = {
    "sort_list_string": SortListString
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "sort_list_string": "Sort List String"
}
