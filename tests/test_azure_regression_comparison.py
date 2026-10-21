"""Prediction diagnostics only: no training or simulator runs."""
import unittest
import numpy as np
from autoscheduler.azure_regression_comparison import metrics, compatible_estimator


class RegressionComparisonTests(unittest.TestCase):
    def test_six_output_shape_and_constant_target_r2(self):
        result=metrics(np.zeros((3,6)),np.zeros((3,6)))
        self.assertIsNone(result['r_squared'])
        self.assertTrue(all(r['r_squared'] is None for r in result['outputs']))
        with self.assertRaises(ValueError):metrics(np.zeros((3,6)),np.zeros((3,4)))

    def test_scaling_pipeline_exposes_v5_output_width_without_refitting(self):
        class Estimator:
            def predict(self,rows):return np.zeros((len(rows),6))
        estimator=compatible_estimator(Estimator(),np.zeros((2,19)))
        self.assertEqual(estimator.n_outputs_,6)
        self.assertEqual(estimator.predict(np.zeros((1,19))).shape,(1,6))
