from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image


TOOLS_DIR = (
    Path(__file__).resolve().parents[1]
    / "characters"
    / "alicia_bell"
    / "tools"
)
sys.path.insert(0, str(TOOLS_DIR))

from campaign_checkpoint import campaign_checkpoint  # noqa: E402
from export_codex_thread_text import export_thread  # noqa: E402
from split_builtin_grid import split_grid  # noqa: E402


class ThreadExportTests(unittest.TestCase):
    def test_media_payload_is_replaced_with_placeholder(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "thread.jsonl"
            output = root / "thread-text.jsonl"
            stats = root / "stats.json"
            records = [
                {
                    "timestamp": "2026-01-01T00:00:00Z",
                    "type": "response_item",
                    "payload": {
                        "type": "message",
                        "role": "user",
                        "content": [{"type": "input_text", "text": "hello"}],
                    },
                },
                {
                    "timestamp": "2026-01-01T00:00:01Z",
                    "type": "response_item",
                    "payload": {
                        "type": "function_call",
                        "name": "imagegen",
                        "call_id": "call-1",
                        "arguments": json.dumps({"prompt": "draw"}),
                    },
                },
                {
                    "timestamp": "2026-01-01T00:00:02Z",
                    "type": "response_item",
                    "payload": {
                        "type": "function_call_output",
                        "call_id": "call-1",
                        "output": [
                            {
                                "type": "input_image",
                                "image_url": "data:image/png;base64,AAAA",
                                "saved_path": "C:/image.png",
                            }
                        ],
                    },
                },
            ]
            source.write_text(
                "\n".join(json.dumps(item) for item in records) + "\n",
                encoding="utf-8",
            )

            result = export_thread(
                source,
                output,
                stats,
                max_json_bytes=1024 * 1024,
                max_tool_output_chars=1000,
                progress_bytes=1024 * 1024,
            )
            text = output.read_text(encoding="utf-8")
            exported = [json.loads(line) for line in text.splitlines()]

            self.assertNotIn("data:image", text)
            self.assertEqual(result["media_records_omitted"], 1)
            self.assertEqual([item["kind"] for item in exported], ["message", "tool_call", "media_omitted"])
            self.assertEqual(exported[-1]["saved_path"], "C:/image.png")


class CampaignCheckpointTests(unittest.TestCase):
    def test_next_action_uses_pending_split_asset(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            campaign = Path(folder)
            (campaign / "rounds" / "R01_test" / "ordinary" / "candidates_100").mkdir(parents=True)
            (campaign / "rounds" / "R01_test" / "morning_star" / "candidates_100").mkdir(parents=True)
            (campaign / "final_training_200").mkdir()
            (campaign / "campaign_manifest.json").write_text(
                json.dumps(
                    {
                        "validation": {
                            "total_candidates": 200,
                            "provisional_selected_total": 50,
                            "final_gold_target": 10,
                        }
                    }
                ),
                encoding="utf-8",
            )
            candidate = (
                campaign
                / "rounds"
                / "R01_test"
                / "ordinary"
                / "candidates_100"
                / "R01_ordinary_builtin_001_test.png"
            )
            candidate.touch()
            pending = campaign / "pending.png"
            pending.touch()
            recovery = {
                "pending_assets": [
                    {
                        "round_id": "R01",
                        "form": "ordinary",
                        "candidate_ids": [2, 3, 4, 5],
                        "source": str(pending),
                    }
                ]
            }

            result = campaign_checkpoint(campaign, recovery)

            self.assertEqual(result["counts"]["candidates_saved"], 1)
            self.assertEqual(result["counts"]["candidates_pending_split"], 4)
            self.assertEqual(result["next_action"]["round_id"], "R01")
            self.assertEqual(result["next_action"]["next_candidate_id"], 2)
            self.assertTrue(result["next_action"]["pending_assets"][0]["source_exists"])

    def test_selection_exclusions_reduce_eligible_progress(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            campaign = Path(folder)
            round_dir = campaign / "rounds" / "R01_test"
            for form in ("ordinary", "morning_star"):
                (round_dir / form / "candidates_100").mkdir(parents=True)
                selected_dir = round_dir / "selected_50" / form
                selected_dir.mkdir(parents=True)
                count = 25
                for index in range(1, count + 1):
                    (selected_dir / f"{form}_{index:03d}.png").touch()
            reports = round_dir / "selected_50" / "reports"
            reports.mkdir()
            (reports / "R01_selected_50_manifest.json").write_text(
                json.dumps(
                    {
                        "status": "selected_50_review_ready",
                        "counts": {
                            "selected": 50,
                            "ordinary_selected": 25,
                            "morning_star_selected": 25,
                        },
                        "items": [],
                    }
                ),
                encoding="utf-8",
            )
            (campaign / "final_training_200").mkdir()
            (campaign / "monitoring").mkdir()
            (campaign / "monitoring" / "selection_exclusions.json").write_text(
                json.dumps(
                    {
                        "status": "active",
                        "excluded_rounds": [
                            {
                                "round_id": "R01",
                                "status": "quarantine_pending_full_context_reaudit",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            (campaign / "campaign_manifest.json").write_text(
                json.dumps(
                    {
                        "validation": {
                            "total_candidates": 200,
                            "provisional_selected_total": 50,
                            "final_gold_target": 10,
                        }
                    }
                ),
                encoding="utf-8",
            )

            result = campaign_checkpoint(campaign, {})

            self.assertEqual(result["counts"]["provisional_selected_physical"], 50)
            self.assertEqual(result["counts"]["provisional_selected"], 0)
            self.assertEqual(result["counts"]["provisional_quarantined"], 50)
            self.assertEqual(
                result["next_action"]["action"],
                "repair_or_reaudit_quarantined_round",
            )


class SplitGridTests(unittest.TestCase):
    def test_split_grid_refuses_silent_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "source.png"
            output = root / "out"
            Image.new("RGB", (100, 100), "white").save(source)
            names = ["one.png", "two.png", "three.png", "four.png"]

            saved = split_grid(
                source,
                output,
                names,
                [1, 2, 3, 4],
                overwrite=False,
            )

            self.assertEqual(len(saved), 4)
            with self.assertRaises(FileExistsError):
                split_grid(
                    source,
                    output,
                    names,
                    [1, 2, 3, 4],
                    overwrite=False,
                )


if __name__ == "__main__":
    unittest.main()
