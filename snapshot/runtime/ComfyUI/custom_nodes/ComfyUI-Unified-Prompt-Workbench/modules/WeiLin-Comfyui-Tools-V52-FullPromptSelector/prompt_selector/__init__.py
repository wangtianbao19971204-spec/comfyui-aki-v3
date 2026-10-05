# -*- coding: utf-8 -*-

from .prompt_selector import PromptSelector
from . import autocomplete_api  # noqa: F401 - registers WeiLin-owned autocomplete routes
from . import tag_api  # noqa: F401 - registers common Tag maintenance routes
from . import reference_collections  # noqa: F401 - registers shared resource membership
from . import prompt_merge_jobs  # noqa: F401 - registers numbered merge tasks and their results
from . import settings_api  # noqa: F401 - registers the small settings owner
from . import category_migration  # noqa: F401 - registers the legacy category-id migration

NODE_CLASS_MAPPINGS = {
    "PromptSelector": PromptSelector,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "PromptSelector": "提示词选择器 (Prompt Selector)",
}

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS"]
