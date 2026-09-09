from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "build_steps/update_category_mappings.py"
SPEC = importlib.util.spec_from_file_location("update_category_mappings", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class UpdateCategoryMappingsTests(unittest.TestCase):
    def setUp(self):
        self.source = MODULE.read_yaml_file(ROOT / "package_category_list.yml")
        self.expected = {
            **MODULE.subcategory_to_group_mapping(self.source),
            **MODULE.group_list_simple(self.source),
            **MODULE.group_description_list_simple(self.source),
        }

    def test_same_name_web_and_media_categories_are_preserved_without_rewrite(self):
        mapping = self.expected["subcategory_mapping"]

        self.assertEqual(mapping["Web"], "Web")
        self.assertEqual(mapping["Media"], "Media")

        with mock.patch.object(MODULE, "write_mapping_to_yaml") as write_mapping:
            MODULE.update_category_mappings(
                "../package_category_list.yml",
                "../data/category_data.yml",
            )

        write_mapping.assert_not_called()

    def test_missing_output_is_created(self):
        output = Path("/does-not-exist/category_data.yml")
        with (
            mock.patch.object(Path, "is_file", return_value=False),
            mock.patch.object(MODULE, "write_mapping_to_yaml") as write_mapping,
        ):
            MODULE.update_category_mappings(
                "../package_category_list.yml",
                output,
            )

        write_mapping.assert_called_once_with(self.expected, output)

    def test_stale_output_is_rewritten(self):
        output = ROOT / "data/category_data.yml"
        with (
            mock.patch.object(
                MODULE,
                "read_yaml_file",
                side_effect=[self.source, {"stale": True}],
            ),
            mock.patch.object(MODULE, "write_mapping_to_yaml") as write_mapping,
        ):
            MODULE.update_category_mappings(
                "../package_category_list.yml",
                "../data/category_data.yml",
            )

        write_mapping.assert_called_once_with(self.expected, output)


if __name__ == "__main__":
    unittest.main()
