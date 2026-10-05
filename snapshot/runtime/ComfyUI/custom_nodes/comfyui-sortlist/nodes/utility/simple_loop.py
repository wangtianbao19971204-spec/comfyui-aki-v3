"""
Simple For Loop nodes for ComfyUI.
Clean implementation without the duplicate-index bug from Easy-Use.

Nodes:
  - Simple For Loop Start
  - Simple For Loop End
  - SimpleWhileOpen  (internal)
  - SimpleWhileClose (internal)
"""

from comfy_execution.graph_utils import GraphBuilder, is_link
from comfy_execution.graph import ExecutionBlocker

try:
    from nodes import NODE_CLASS_MAPPINGS as ALL_NODE_CLASS_MAPPINGS
except ImportError:
    ALL_NODE_CLASS_MAPPINGS = {}

MAX_FLOW_NUM = 5  # value0=index, value1-4=passthrough
any_type = "*"

_LOOP_INITIAL_DONE = set()


# ─────────────────────────────────────────────
# Internal While Loop nodes
# ─────────────────────────────────────────────

class SimpleWhileOpen:
    @classmethod
    def INPUT_TYPES(cls):
        inputs = {
            "required": {
                "condition": ("BOOLEAN", {"default": True}),
            },
            "optional": {},
        }
        for i in range(MAX_FLOW_NUM):
            inputs["optional"]["initial_value%d" % i] = (any_type,)
        return inputs

    RETURN_TYPES = tuple(["FLOW_CONTROL"] + [any_type] * MAX_FLOW_NUM)
    RETURN_NAMES = tuple(["flow"] + ["value%d" % i for i in range(MAX_FLOW_NUM)])
    FUNCTION = "while_loop_open"
    CATEGORY = "comfyui-sortlist/flow"

    def while_loop_open(self, condition, **kwargs):
        values = []
        for i in range(MAX_FLOW_NUM):
            if condition:
                values.append(kwargs.get("initial_value%d" % i, None))
            else:
                values.append(ExecutionBlocker(None))
        return tuple(["stub"] + values)


class SimpleWhileClose:
    @classmethod
    def INPUT_TYPES(cls):
        inputs = {
            "required": {
                "flow": ("FLOW_CONTROL", {"rawLink": True}),
                "condition": ("BOOLEAN", {}),
            },
            "optional": {},
            "hidden": {
                "dynprompt": "DYNPROMPT",
                "unique_id": "UNIQUE_ID",
            },
        }
        for i in range(MAX_FLOW_NUM):
            inputs["optional"]["initial_value%d" % i] = (any_type,)
        return inputs

    RETURN_TYPES = tuple([any_type] * MAX_FLOW_NUM)
    RETURN_NAMES = tuple(["value%d" % i for i in range(MAX_FLOW_NUM)])
    FUNCTION = "while_loop_close"
    CATEGORY = "comfyui-sortlist/flow"

    def explore_dependencies(self, node_id, dynprompt, upstream, parent_ids):
        node_info = dynprompt.get_node(node_id)
        if "inputs" not in node_info:
            return
        for k, v in node_info["inputs"].items():
            if is_link(v):
                parent_id = v[0]
                display_id = dynprompt.get_display_node_id(parent_id)
                display_node = dynprompt.get_node(display_id)
                class_type = display_node["class_type"]
                if class_type not in ["SimpleForLoopEnd", "SimpleWhileClose"]:
                    parent_ids.append(display_id)
                if parent_id not in upstream:
                    upstream[parent_id] = []
                    self.explore_dependencies(parent_id, dynprompt, upstream, parent_ids)
                upstream[parent_id].append(node_id)

    def explore_output_nodes(self, dynprompt, upstream, output_nodes, parent_ids):
        for parent_id in upstream:
            display_id = dynprompt.get_display_node_id(parent_id)
            for output_id in output_nodes:
                id = output_nodes[output_id][0]
                if id in parent_ids and display_id == id and output_id not in upstream[parent_id]:
                    if '.' in parent_id:
                        arr = parent_id.split('.')
                        arr[len(arr) - 1] = output_id
                        upstream[parent_id].append('.'.join(arr))
                    else:
                        upstream[parent_id].append(output_id)

    def collect_contained(self, node_id, upstream, contained):
        if node_id not in upstream:
            return
        for child_id in upstream[node_id]:
            if child_id not in contained:
                contained[child_id] = True
                self.collect_contained(child_id, upstream, contained)

    def while_loop_close(self, flow, condition, dynprompt=None, unique_id=None, **kwargs):
        if not condition:
            # Loop done — pass final values through
            values = []
            for i in range(MAX_FLOW_NUM):
                values.append(kwargs.get("initial_value%d" % i, None))
            return tuple(values)

        # Continue looping — clone the subgraph for next iteration
        upstream = {}
        parent_ids = []
        self.explore_dependencies(unique_id, dynprompt, upstream, parent_ids)
        parent_ids = list(set(parent_ids))

        # Find output nodes
        prompts = dynprompt.get_original_prompt()
        output_nodes = {}
        for id in prompts:
            node = prompts[id]
            if "inputs" not in node:
                continue
            class_type = node["class_type"]
            class_def = ALL_NODE_CLASS_MAPPINGS.get(class_type, None)
            if class_def is not None and hasattr(class_def, 'OUTPUT_NODE') and class_def.OUTPUT_NODE:
                for k, v in node['inputs'].items():
                    if is_link(v):
                        output_nodes[id] = v

        graph = GraphBuilder()
        self.explore_output_nodes(dynprompt, upstream, output_nodes, parent_ids)
        contained = {}
        open_node = flow[0]
        self.collect_contained(open_node, upstream, contained)
        contained[unique_id] = True
        contained[open_node] = True

        # Clone all contained nodes into the expand graph
        for node_id in contained:
            original_node = dynprompt.get_node(node_id)
            node = graph.node(
                original_node["class_type"],
                "Recurse" if node_id == unique_id else node_id,
            )
            node.set_override_display_id(node_id)

        for node_id in contained:
            original_node = dynprompt.get_node(node_id)
            node = graph.lookup_node("Recurse" if node_id == unique_id else node_id)
            for k, v in original_node["inputs"].items():
                if is_link(v) and v[0] in contained:
                    parent = graph.lookup_node(v[0])
                    node.set_input(k, parent.out(v[1]))
                else:
                    node.set_input(k, v)

        # Feed updated values back into the open node
        new_open = graph.lookup_node(open_node)
        for i in range(MAX_FLOW_NUM):
            key = "initial_value%d" % i
            new_open.set_input(key, kwargs.get(key, None))

        my_clone = graph.lookup_node("Recurse")
        result = map(lambda x: my_clone.out(x), range(MAX_FLOW_NUM))
        return {
            "result": tuple(result),
            "expand": graph.finalize(),
        }


# ─────────────────────────────────────────────
# User-facing For Loop nodes
# ─────────────────────────────────────────────

class SimpleForLoopStart:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "total": ("INT", {"default": 1, "min": 1, "max": 100000, "step": 1}),
            },
            "optional": {
                "initial_value%d" % i: (any_type,) for i in range(1, MAX_FLOW_NUM)
            },
            "hidden": {
                "initial_value0": (any_type,),
                "unique_id": "UNIQUE_ID",
            },
        }

    RETURN_TYPES = tuple(["FLOW_CONTROL", "INT"] + [any_type] * (MAX_FLOW_NUM - 1))
    RETURN_NAMES = tuple(["flow", "index"] + ["value%d" % i for i in range(1, MAX_FLOW_NUM)])
    FUNCTION = "for_loop_start"
    CATEGORY = "comfyui-sortlist/flow"

    def for_loop_start(self, total, unique_id=None, **kwargs):
        graph = GraphBuilder()

        i = 0
        is_recursion = "initial_value0" in kwargs
        if is_recursion:
            i = kwargs["initial_value0"]

        # Create expand graph with SimpleWhileOpen
        initial_values = {
            "initial_value%d" % num: kwargs.get("initial_value%d" % num, None)
            for num in range(1, MAX_FLOW_NUM)
        }
        graph.node("SimpleWhileOpen", condition=total, initial_value0=i, **initial_values)

        outputs = [kwargs.get("initial_value%d" % num, None) for num in range(1, MAX_FLOW_NUM)]
        return {
            "result": tuple(["stub", i] + outputs),
            "expand": graph.finalize(),
        }


class _LoopAdd:
    """Internal helper: a + b (integers)"""
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "a": ("INT", {"default": 0}),
                "b": ("INT", {"default": 1}),
            }
        }
    RETURN_TYPES = ("INT",)
    FUNCTION = "add"
    CATEGORY = "comfyui-sortlist/flow"

    def add(self, a, b):
        return (a + b,)


class _LoopLessThan:
    """Internal helper: a < b → boolean"""
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "a": ("INT", {"default": 0}),
                "b": ("INT", {"default": 1}),
            }
        }
    RETURN_TYPES = ("BOOLEAN",)
    FUNCTION = "compare"
    CATEGORY = "comfyui-sortlist/flow"

    def compare(self, a, b):
        return (a < b,)


class SimpleForLoopEnd:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "flow": ("FLOW_CONTROL", {"rawLink": True}),
            },
            "optional": {
                "initial_value%d" % i: (any_type, {"rawLink": True})
                for i in range(1, MAX_FLOW_NUM)
            },
            "hidden": {
                "dynprompt": "DYNPROMPT",
                "unique_id": "UNIQUE_ID",
            },
        }

    RETURN_TYPES = tuple([any_type] * (MAX_FLOW_NUM - 1))
    RETURN_NAMES = tuple(["value%d" % i for i in range(1, MAX_FLOW_NUM)])
    FUNCTION = "for_loop_end"
    CATEGORY = "comfyui-sortlist/flow"

    def for_loop_end(self, flow, dynprompt=None, unique_id=None, **kwargs):
        graph = GraphBuilder()
        while_open = flow[0]

        # Get total from the original ForLoopStart node
        forstart_node = dynprompt.get_node(while_open)
        total = None
        if forstart_node["class_type"] == "SimpleForLoopStart":
            total = forstart_node["inputs"]["total"]

        if total is None:
            raise ValueError("Simple For Loop End must be connected to Simple For Loop Start")

        # Increment index: i + 1 (using self-contained helper)
        sub = graph.node("_LoopAdd", a=[while_open, 1], b=1)
        # Check condition: (i + 1) < total
        cond = graph.node("_LoopLessThan", a=sub.out(0), b=total)

        input_values = {
            "initial_value%d" % i: kwargs.get("initial_value%d" % i, None)
            for i in range(1, MAX_FLOW_NUM)
        }

        while_close = graph.node(
            "SimpleWhileClose",
            flow=flow,
            condition=cond.out(0),
            initial_value0=sub.out(0),
            **input_values,
        )

        return {
            "result": tuple([while_close.out(i) for i in range(1, MAX_FLOW_NUM)]),
            "expand": graph.finalize(),
        }


# ─────────────────────────────────────────────
# Registration
# ─────────────────────────────────────────────

NODE_CLASS_MAPPINGS = {
    "SimpleForLoopStart": SimpleForLoopStart,
    "SimpleForLoopEnd": SimpleForLoopEnd,
    "SimpleWhileOpen": SimpleWhileOpen,
    "SimpleWhileClose": SimpleWhileClose,
    "_LoopAdd": _LoopAdd,
    "_LoopLessThan": _LoopLessThan,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "SimpleForLoopStart": "Simple For Loop Start A100",
    "SimpleForLoopEnd": "Simple For Loop End A100",
    "SimpleWhileOpen": "Simple While Open",
    "SimpleWhileClose": "Simple While Close",
    "_LoopAdd": "_Loop Add (internal)",
    "_LoopLessThan": "_Loop Less Than (internal)",
}
