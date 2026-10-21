"""Headroom must clear the real controller margin, not numerical zero."""
import unittest


class AzureHeadroomTests(unittest.TestCase):
    def test_tiny_benefits_do_not_count_as_actionable_switches(self):
        from autoscheduler.azure_headroom import cost_headroom
        rows=[{'costs':[0,0,-.0001,.0002]}, {'costs':[0,0,0,0]},
              {'costs':[0,0,-.006,.001]}]
        summary=cost_headroom(rows)
        self.assertEqual(summary['mlfq_optimal_or_tied_states'],1)
        self.assertEqual(summary['positive_benefit_states'],2)
        self.assertEqual(summary['states_clearing_frozen_margin'],1)
        self.assertAlmostEqual(summary['maximum_benefit'],.006)

    def test_target_differences_already_use_mlfq_reference(self):
        from autoscheduler.azure_headroom import cost_headroom
        summary=cost_headroom([{'costs':[0,0,0,.01]}])
        self.assertEqual(summary['nonzero_cost_difference_states'],1)
        self.assertEqual(summary['positive_benefit_states'],0)
        self.assertEqual(summary['states_clearing_frozen_margin'],0)


if __name__=='__main__':unittest.main()
