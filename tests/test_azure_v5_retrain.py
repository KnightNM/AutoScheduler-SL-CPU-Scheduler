"""Focused exact-v5 compatibility checks; no model fitting or dataset generation."""
import unittest
from autoscheduler.azure_v5_retrain import validate_splits, cached_references


class AzureV5RetrainTests(unittest.TestCase):
    def test_related_sources_cannot_cross_splits_or_enter_holdout(self):
        rows=[{'source_group':'a','split':'train'},{'source_group':'b','split':'test'}]
        validate_splits(rows,{'reserved'})
        with self.assertRaises(ValueError):
            validate_splits(rows+[{'source_group':'a','split':'validation'}],set())
        with self.assertRaises(ValueError):
            validate_splits(rows,{'a'})

    def test_cached_references_preserve_five_static_score_bounds(self):
        import json
        from autoscheduler.evaluation import DEPLOYABLE_ALGORITHMS,SCORE_WEIGHTS
        from pathlib import Path
        rows=json.loads(Path('results/azure_adapted_20261020/results.json').read_text())['test_rows']
        refs=cached_references(rows,rows[0]['workload_id'])
        self.assertEqual(set(refs),set(DEPLOYABLE_ALGORITHMS))
        for ref in refs.values():
            for key in SCORE_WEIGHTS:self.assertIsInstance(getattr(ref,key),(float,int))
