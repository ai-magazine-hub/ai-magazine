import multiprocessing
from pathlib import Path
import time
import unittest
from unittest.mock import patch

from runtime_limits import bounded_call, bounded_results


def stalled(*args):
    time.sleep(30)


def body(url, permalink):
    if url == "slow":
        return stalled()
    return "正文" * 100


def load_generator():
    # The legacy script executes its pipeline at module scope. Load definitions
    # without fetching data or writing the real archive.
    path = Path(__file__).resolve().parents[1] / "generate_archive.py"
    source = path.read_text()
    ns = {"__file__": str(path), "__name__": "generator_test"}
    prefix = source.split("# ---------- 1. 取全部可用日期列表")[0]
    definitions = source[source.index("def build_day_record("):source.index("\nnew_added = 0")]
    exec(compile(prefix + definitions, str(path), "exec"), ns)
    ns.update(save_archive=lambda arch: None, lead_map={}, id2pub={})
    return ns


class BudgetTests(unittest.TestCase):
    def test_hung_call_is_killed_and_no_child_survives(self):
        before = {p.pid for p in multiprocessing.active_children()}
        start = time.monotonic()
        with self.assertRaises(TimeoutError):
            bounded_call(stalled, timeout=0.15)
        self.assertLess(time.monotonic() - start, 2)
        self.assertEqual(before, {p.pid for p in multiprocessing.active_children()})

    def test_slow_source_does_not_block_other_source(self):
        rows = list(bounded_results(body, [("slow", None), ("ok", None)],
                                    workers=2, timeout=0.2, wall=0.3))
        self.assertTrue(any(index == 1 and value for index, value, error in rows))
        self.assertTrue(any(index == 0 and error for index, value, error in rows))

    def test_backfill_preserves_old_content_and_resets_language(self):
        ns = load_generator()
        old = {"url": "slow", "content": "旧正文"}
        new = {"url": "ok", "content": "", "zh": True}
        arch = {"2026-10-06": {"sections": [{"items": [old, new]}]}}
        ns["fetch_content"] = body
        ns["backfill_content"](arch, workers=2, wall=0.2)
        self.assertEqual(old["content"], "旧正文")
        self.assertEqual(new["content"], "正文" * 100)
        self.assertNotIn("zh", new)

    def test_translation_deadline_preserves_original(self):
        ns = load_generator()
        ns["_load_ds_key"] = lambda: None
        ns["_translate_item"] = stalled
        item = {"content": "Original English article. " * 100}
        original = item["content"]
        arch = {"2026-10-06": {"sections": [{"items": [item]}]}}
        start = time.monotonic()
        ns["translate_archive"](arch, wall=0.2)
        self.assertLess(time.monotonic() - start, 2)
        self.assertEqual(item["content"], original)
        self.assertFalse(item["zh"])

    def test_many_short_paragraphs_are_batched(self):
        ns = load_generator()
        calls = []
        ns["_gtrans_one"] = lambda text: calls.append(text) or text
        original = "\n".join(["This is an English paragraph."] * 306)
        translated = ns["translate_en_zh"](original)
        self.assertEqual(translated, original)
        self.assertLess(len(calls), 10)

    def test_deepseek_failure_has_two_attempts_per_chunk(self):
        ns = load_generator()
        with patch("urllib.request.urlopen", side_effect=OSError) as request, patch("time.sleep"):
            result = ns["translate_deepseek_text"]("English original", "test-placeholder")
        self.assertEqual(result, "English original")
        self.assertEqual(request.call_count, 2)

    def test_empty_official_day_is_valid_but_bad_response_is_not(self):
        ns = load_generator()
        rec = ns["build_day_record"]("2026-10-05", {
            "date": "2026-10-05", "sections": [], "lead": {"title": "今日安静，无大事发生"}})
        self.assertEqual(rec["meta"]["total"], 0)
        self.assertEqual(rec["lead"], "今日安静，无大事发生")
        with self.assertRaises(ValueError):
            ns["build_day_record"]("2026-10-05", {})

    def test_v1_feed_date_boundary_and_dedup(self):
        ns = load_generator()
        rec = ns["build_day_record"]("2026-10-06", {"date": "2026-10-06", "sections": []})
        arch = {"2026-10-06": rec}
        feed = {"items": [{"id": "sample", "title": "产品更新", "summary": "来源摘要",
                           "links": {"original": "https://example.com/news", "aihot": "https://aihot.news/items/sample"},
                           "source": {"name": "来源"}, "publishedAt": "2026-10-05T16:01:00Z",
                           "category": "ai-products"}]}
        self.assertEqual(ns["_merge_feed_into_date"](arch, "2026-10-06", feed), 1)
        self.assertEqual(ns["_merge_feed_into_date"](arch, "2026-10-06", feed), 0)
        self.assertEqual(rec["sections"][0]["items"][0]["url"], "https://example.com/news")


if __name__ == "__main__":
    unittest.main()
