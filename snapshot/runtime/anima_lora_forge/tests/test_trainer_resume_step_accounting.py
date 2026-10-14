"""Run the trainer's real resume/loop AST on CPU without training imports."""
import ast
import copy
import math
from pathlib import Path
import types
import unittest


SOURCE = Path(__file__).resolve().parents[1] / "vendor/sd-trainer/SD-Trainer/vendor/sd-scripts/train_network.py"
TREE = ast.parse(SOURCE.read_text(encoding="utf-8"))
TRAINER = next(node for node in TREE.body if isinstance(node, ast.ClassDef) and node.name == "NetworkTrainer")
TRAIN = next(node for node in TRAINER.body if isinstance(node, ast.FunctionDef) and node.name == "train")


def assigns(node, name):
    return (isinstance(node, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id == name for target in node.targets))


START = next(index for index, node in enumerate(TRAIN.body) if assigns(node, "initial_step"))
END = next(index for index in range(START, len(TRAIN.body)) if assigns(TRAIN.body[index], "global_step"))
RESUME_NODES = TRAIN.body[START:END + 1]
PROGRESS = next(node for node in TRAIN.body if assigns(node, "progress_bar"))
EPOCH_LOOP = next(node for node in TRAIN.body if isinstance(node, ast.For)
                  and isinstance(node.target, ast.Name) and node.target.id == "epoch")
SKIP_START = next(index for index, node in enumerate(EPOCH_LOOP.body) if assigns(node, "skipped_dataloader"))
BATCH_LOOP = next(node for node in EPOCH_LOOP.body[SKIP_START:]
                  if isinstance(node, ast.For) and isinstance(node.target, ast.Tuple))
UPDATE = next(node for node in BATCH_LOOP.body if isinstance(node, ast.If)
              and ast.unparse(node.test) == "accelerator.sync_gradients")
INCREMENT = next(node for node in UPDATE.body if isinstance(node, ast.AugAssign)
                 and isinstance(node.target, ast.Name) and node.target.id == "global_step")
STOP = next(node for node in BATCH_LOOP.body if isinstance(node, ast.If)
            and ast.unparse(node.test) == "global_step >= args.max_train_steps")


def execute(nodes, values):
    module = ast.fix_missing_locations(ast.Module(body=copy.deepcopy(nodes), type_ignores=[]))
    exec(compile(module, str(SOURCE), "exec"), values)


class AcceleratorFixture:
    num_processes = 1
    is_local_main_process = True
    sync_gradients = True

    @staticmethod
    def skip_first_batches(loader, count):
        return loader[count:]


def position(start, target=1000, length=120, accumulation=1, skip=True):
    values = {
        "args": types.SimpleNamespace(initial_epoch=None, initial_step=None,
            max_train_steps=target, gradient_accumulation_steps=accumulation,
            skip_until_initial_step=skip, resume="verified-state" if start else None),
        "steps_from_state": start,
        "train_dataloader": list(range(length)),
        "accelerator": AcceleratorFixture(),
        "logger": types.SimpleNamespace(info=lambda *args: None, warning=lambda *args: None),
        "math": math,
        "tqdm": lambda iterable, **kwargs: iterable,
    }
    execute(RESUME_NODES, values)
    execute([PROGRESS], values)
    return values


def simulate(start, target=1000, length=120, accumulation=1, skip=True, extra_epochs=0):
    """Keep real cursor, increment and stop branches; replace model work only."""
    values = position(start, target, length, accumulation, skip)
    values.update({"current_step": types.SimpleNamespace(value=0),
        "num_train_epochs": math.ceil(target / math.ceil(length / accumulation)) + extra_epochs,
        "physical_updates": [], "logged_steps": []})
    values["set_sync"] = lambda batch: setattr(values["accelerator"], "sync_gradients",
        (batch + 1) % accumulation == 0 or batch == length - 1)
    actual_update = copy.deepcopy(UPDATE)
    actual_update.body = [ast.parse("physical_updates.append(global_step)").body[0],
                         copy.deepcopy(INCREMENT), ast.parse("logged_steps.append(global_step)").body[0]]
    actual_update.orelse = []
    actual_batch = copy.deepcopy(BATCH_LOOP)
    actual_batch.body = copy.deepcopy(BATCH_LOOP.body[:2]) + [
        ast.parse("set_sync(batch)").body[0], actual_update, copy.deepcopy(STOP)]
    actual_batch.orelse = []
    actual_epoch = copy.deepcopy(EPOCH_LOOP)
    # The first branch is the real outer-epoch termination guard. Retain the
    # actual within-epoch skipping statements and batch iterator as well.
    actual_epoch.body = [copy.deepcopy(EPOCH_LOOP.body[0])] + copy.deepcopy(
        EPOCH_LOOP.body[SKIP_START:SKIP_START + 2]) + [actual_batch]
    actual_epoch.orelse = []
    execute([actual_epoch], values)
    return values


class TrainerResumeStepAccountingTests(unittest.TestCase):
    def test_400_resume_keeps_absolute_step_and_600_remaining(self):
        values = position(400)
        self.assertEqual(values["global_step"], 400)
        self.assertEqual(values["epoch_to_start"], 3)
        self.assertEqual(values["initial_step"], 40)
        self.assertEqual(len(values["progress_bar"]), 600)

    def test_400_to_1000_executes_exactly_600_updates_and_logs_401_onward(self):
        values = simulate(400)
        self.assertEqual(values["physical_updates"], list(range(400, 1000)))
        self.assertEqual(values["logged_steps"], list(range(401, 1001)))
        self.assertEqual(values["global_step"], 1000)
        self.assertEqual([step for step in values["logged_steps"] if step % 200 == 0], [600, 800, 1000])

    def test_exact_epoch_boundary_does_not_reset_to_zero(self):
        values = position(360)
        self.assertEqual((values["global_step"], values["epoch_to_start"], values["initial_step"]), (360, 3, 0))
        values = simulate(360)
        self.assertEqual(values["physical_updates"], list(range(360, 1000)))

    def test_before_and_after_epoch_boundary_skip_exact_batches(self):
        for start, epoch, batches in ((359, 2, 119), (360, 3, 0), (361, 3, 1)):
            with self.subTest(start=start):
                values = position(start)
                self.assertEqual((values["global_step"], values["epoch_to_start"], values["initial_step"]),
                                 (start, epoch, batches))
                self.assertEqual(simulate(start)["physical_updates"], list(range(start, 1000)))

    def test_non_epoch_aligned_target_stops_exactly_at_target(self):
        values = simulate(400, target=601)
        self.assertEqual(values["physical_updates"], list(range(400, 601)))
        self.assertEqual(values["logged_steps"][-1], 601)

    def test_no_extra_update_when_another_epoch_is_available(self):
        values = simulate(400, target=601, extra_epochs=2)
        self.assertEqual(values["physical_updates"], list(range(400, 601)))
        self.assertEqual(values["global_step"], 601)

    def test_from_scratch_with_or_without_skip_has_original_count(self):
        for skip in (True, False):
            with self.subTest(skip=skip):
                values = simulate(0, skip=skip)
                self.assertEqual(values["physical_updates"], list(range(1000)))
                self.assertEqual(values["logged_steps"], list(range(1, 1001)))

    def test_skip_off_retains_legacy_epoch_only_start_behavior(self):
        values = position(400, skip=False)
        self.assertEqual((values["global_step"], values["epoch_to_start"], values["initial_step"]), (0, 3, 0))
        self.assertEqual(len(values["progress_bar"]), 1000)
        # This legacy branch is not supported by the Colab continuation route.
        self.assertEqual(len(simulate(400, skip=False)["physical_updates"]), 720)

    def test_accumulation_handles_partial_last_batch_and_epoch_boundaries(self):
        for start, epoch, batches in ((399, 133, 0), (400, 133, 2), (401, 133, 4), (402, 134, 0)):
            with self.subTest(start=start):
                values = position(start, length=5, accumulation=2)
                self.assertEqual((values["global_step"], values["epoch_to_start"], values["initial_step"]),
                                 (start, epoch, batches))
                resumed = simulate(start, length=5, accumulation=2)
                self.assertEqual(resumed["physical_updates"], list(range(start, 1000)))
                self.assertEqual(resumed["logged_steps"][-1], 1000)

    def test_resume_at_or_beyond_target_is_rejected(self):
        for start in (1000, 1001):
            with self.subTest(start=start), self.assertRaises(AssertionError):
                position(start)


if __name__ == "__main__":
    unittest.main()
