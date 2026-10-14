"""Safety boundaries for local evaluation; no GPU or model deserialization."""
from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


SOURCE = Path(__file__).resolve().parents[1] / "tools/evaluate_checkpoint_plan.py"
SPEC = importlib.util.spec_from_file_location("evaluate_checkpoint_plan", SOURCE)
evaluation = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(evaluation)


def plan(comfy: Path, output: Path) -> dict:
    return {"schema_version": 1, "run_id": "safety_test", "comfy_root": str(comfy),
            "output_root": str(output), "checkpoints": [{"id": "step0400"}],
            "prompts": {"canonical": {"positive": "fully clothed adult character"}},
            "negative": "text, watermark", "sampling": {"width": 1024, "height": 1536,
                "steps": 30, "cfg": 7, "shift": 3, "sampler": "res_multistep", "scheduler": "beta"},
            "jobs": [{"job_key": "safe_job", "checkpoint_id": "step0400", "prompt_id": "canonical",
                      "strength": 0.8, "seed": 26101411}]}


class EvaluationSafety(unittest.TestCase):
    def test_repository_root_and_nonruntime_subtrees_rejected_before_api_or_creation(self):
        repository = SOURCE.resolve().parents[4]
        targets = (repository, repository / "docs/evaluation-safety-test",
                   repository / "snapshot/evidence/evaluation-safety-test",
                   repository / "governance/evaluation-safety-test",
                   repository / "snapshot/runtime/evaluation-safety-test")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "plan.json"
            for target in targets:
                with self.subTest(output=target):
                    existed_before = target.exists()
                    source.write_text(json.dumps(plan(root / "comfy", target)), encoding="utf-8")
                    with patch.object(evaluation, "api") as api:
                        with self.assertRaisesRegex(ValueError, "entire source repository"):
                            evaluation.prepare(source)
                        api.assert_not_called()
                    self.assertEqual(target.exists(), existed_before)

    def test_sibling_with_repository_name_prefix_is_outside_protected_tree(self):
        repository = SOURCE.resolve().parents[4]
        output = repository.with_name(repository.name + "-evaluation-safety-test")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "plan.json"
            source.write_text(json.dumps(plan(root / "comfy", output)), encoding="utf-8")
            with patch.object(evaluation, "api", return_value={"queue_running": [[1, "user-job"]], "queue_pending": []}) as api:
                with self.assertRaisesRegex(RuntimeError, "not empty"):
                    evaluation.prepare(source)
                self.assertEqual(api.call_count, 1)
                self.assertEqual(api.call_args.args[1], "/queue")

    def test_traversal_job_rejected_before_api_or_output_creation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            data = plan(root / "comfy", root / "evaluation")
            data["jobs"][0]["job_key"] = "../user-file"
            source = root / "plan.json"
            source.write_text(json.dumps(data), encoding="utf-8")
            with patch.object(evaluation, "api") as api:
                with self.assertRaises(ValueError):
                    evaluation.prepare(source)
                api.assert_not_called()
            self.assertFalse((root / "evaluation").exists())

    def test_busy_queue_prevents_preparation_and_does_not_remove_user_jobs(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "plan.json"
            source.write_text(json.dumps(plan(root / "comfy", root / "evaluation")), encoding="utf-8")
            with patch.object(evaluation, "api", return_value={"queue_running": [[1, "user-job"]], "queue_pending": []}) as api:
                with self.assertRaisesRegex(RuntimeError, "not empty"):
                    evaluation.prepare(source)
                self.assertEqual(api.call_count, 1)
                self.assertEqual(api.call_args.args[1], "/queue")
            self.assertFalse((root / "evaluation").exists())

    def test_ambiguous_submission_never_automatically_resubmits(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            data = plan(root / "comfy", root)
            submission = root / "jobs/safe_job/submission.json"
            evaluation.write_json(submission, {"state": "post_started_unknown_result"})
            with patch.object(evaluation, "verify_frozen", return_value=(data, {"checkpoints": [{"id": "step0400"}]})), patch.object(evaluation, "api") as api:
                with self.assertRaisesRegex(RuntimeError, "Ambiguous"):
                    evaluation.execute(root, limit=1, timeout=1)
                api.assert_not_called()
            self.assertFalse((root / ".execution.lock").exists())
            error = evaluation.read_json(root / "execution_error.json")
            self.assertFalse(error["automatic_resubmit"])
            self.assertFalse(error["queue_interrupted"])

    def test_cleanup_with_unrecorded_file_removes_nothing(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / "evaluation"
            comfy = root / "comfy"
            directory = comfy / "models/loras/_temporary_anima_eval/safety_test"
            directory.mkdir(parents=True)
            recorded = directory / "step0400.safetensors"
            recorded.write_bytes(b"weight-placeholder")
            unrelated = directory / "user-file.txt"
            unrelated.write_bytes(b"preserve")
            evaluation.write_json(output / "plan.json", plan(comfy, output))
            evaluation.write_json(output / "prepare_receipt.json", {"link_directory": str(directory),
                "temporary_links": [{"link_path": str(recorded)}]})
            with patch.object(evaluation, "api", return_value={"queue_running": [], "queue_pending": []}):
                with self.assertRaisesRegex(ValueError, "Unexpected"):
                    evaluation.cleanup(output)
            self.assertEqual(recorded.read_bytes(), b"weight-placeholder")
            self.assertEqual(unrelated.read_bytes(), b"preserve")

    def test_unexpected_returned_image_is_not_copied(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            data = plan(root / "comfy", root / "evaluation")
            record = {"outputs": {"13": {"images": [{"type": "output", "subfolder": "../private",
                                                      "filename": "safe_job_00001_.png"}]}}}
            destination = root / "retained.png"
            with self.assertRaisesRegex(RuntimeError, "identity"):
                evaluation.retain_image(data, data["jobs"][0], record, destination)
            self.assertFalse(destination.exists())


if __name__ == "__main__":
    unittest.main()
