"""Final synthetic checkpoint: one prespecified longer quiet window, no promotion."""
import argparse
from pathlib import Path

from autoscheduler.dynamic_v5_experiment import run


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--artifacts", type=Path, required=True)
    args = parser.parse_args()
    run(args.output, args.artifacts, quiet_dwell_periods=2,
        seeds=(10601, 10602, 10603), previous_version=5, experiment_version=6)


if __name__ == "__main__":
    main()
