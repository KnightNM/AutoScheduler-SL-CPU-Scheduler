"""Decision-tree training and persistence."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from statistics import mean
from dataclasses import dataclass

from autoscheduler.evaluation import ALGORITHMS
from autoscheduler.features import FEATURE_NAMES


@dataclass
class PolicyCostModel:
    """One small multi-output tree predicts the cost of each eligible policy."""

    regressor: object
    policies: tuple[str, ...]
    switch_margin: float = 0.005

    def predict(self, matrix):
        return [self.policies[min(range(len(costs)), key=lambda i: (costs[i], i))]
                for costs in self.regressor.predict(matrix)]

    def predict_benefits(self, matrix):
        """Expected score improvement relative to immediate MLFQ continuation."""
        return [dict(zip(self.policies, map(lambda cost: -float(cost), costs)))
                for costs in self.regressor.predict(matrix)]

    def switch_allowed(self, features, active, selected):
        from autoscheduler.dynamic import DYNAMIC_FEATURE_NAMES

        costs = self.regressor.predict([[features[name] for name in DYNAMIC_FEATURE_NAMES]])[0]
        baseline = "No Switch" if "No Switch" in self.policies else active
        return bool(costs[self.policies.index(baseline)] - costs[self.policies.index(selected)] >= self.switch_margin)

    @property
    def feature_importances_(self):
        return self.regressor.feature_importances_


def _imports():
    import joblib
    from sklearn.metrics import accuracy_score
    from sklearn.tree import DecisionTreeClassifier

    return joblib, accuracy_score, DecisionTreeClassifier


def _score_column(algorithm: str) -> str:
    return f"score_{algorithm.lower().replace(' ', '_')}"


def _mean_regret(rows: list[dict], predictions: list[str]) -> float:
    return sum(
        row[_score_column(prediction)] - row[_score_column(row["label"])]
        for row, prediction in zip(rows, predictions)
    ) / len(rows)


def _candidate_key(metrics: dict, depth_rank: int) -> tuple:
    """Prefer lower regret; resolve ties with the simpler, more regularized tree."""
    return (metrics["validation_mean_regret"], depth_rank, -metrics["min_samples_leaf"])


def scheduling_candidate_key(metrics: dict) -> tuple:
    return (not metrics.get("validation_schedule_eligible", True), metrics["validation_schedule_score"])


def select_eligible_family(metrics: dict) -> str | None:
    eligible = [name for name, values in metrics.items() if values.get("validation_schedule_eligible", False)]
    return min(eligible, key=lambda name: (metrics[name]["validation_schedule_score"], name)) if eligible else None


def _split_indexes(rows: list[dict], random_state: int, group_key: str | None = None) -> tuple[list[int], list[int], list[int]]:
    from sklearn.model_selection import GroupShuffleSplit, train_test_split

    indexes = list(range(len(rows)))
    if group_key is not None:
        groups = [row[group_key] for row in rows]
        if len(set(groups)) < 4:
            raise ValueError("grouped training requires at least four distinct traces")
        train_positions, holdout_positions = next(
            GroupShuffleSplit(n_splits=1, test_size=0.30, random_state=random_state).split(indexes, groups=groups)
        )
        train_indexes = [indexes[position] for position in train_positions]
        holdout_indexes = [indexes[position] for position in holdout_positions]
        validation_positions, test_positions = next(
            GroupShuffleSplit(n_splits=1, test_size=0.50, random_state=random_state).split(
                holdout_indexes, groups=[groups[index] for index in holdout_indexes]
            )
        )
        validation_indexes = [holdout_indexes[position] for position in validation_positions]
        test_indexes = [holdout_indexes[position] for position in test_positions]
        train_groups, validation_groups, test_groups = (
            {groups[index] for index in split}
            for split in (train_indexes, validation_indexes, test_indexes)
        )
        assert not (train_groups & validation_groups or train_groups & test_groups or validation_groups & test_groups)
        return train_indexes, validation_indexes, test_indexes

    labels = [row["label"] for row in rows]
    stratify = labels if min(Counter(labels).values()) >= 2 else None
    train_indexes, holdout_indexes = train_test_split(
        indexes, test_size=0.30, random_state=random_state, stratify=stratify
    )
    holdout_labels = [labels[index] for index in holdout_indexes]
    holdout_stratify = holdout_labels if min(Counter(holdout_labels).values()) >= 2 else None
    validation_indexes, test_indexes = train_test_split(
        holdout_indexes, test_size=0.50, random_state=random_state, stratify=holdout_stratify
    )
    return train_indexes, validation_indexes, test_indexes


def train_model(
    rows: list[dict],
    model_path: str | Path,
    random_state: int = 42,
    priority_rr_config: dict | None = None,
    feature_names: tuple[str, ...] = FEATURE_NAMES,
    metadata: dict | None = None,
    group_key: str | None = None,
    model_kind: str = "classifier",
    scheduler_validation=None,
    candidate_settings=None,
    refit: bool = True,
) -> dict:
    if len(rows) < 20:
        raise ValueError("at least 20 labeled workloads are required")
    joblib, accuracy_score, DecisionTreeClassifier = _imports()
    from autoscheduler.dynamic import DYNAMIC_FEATURE_NAMES, DYNAMIC_SCHEMA_VERSION, DynamicRouterConfig, dynamic_action_names

    is_dynamic = tuple(feature_names) == DYNAMIC_FEATURE_NAMES
    if is_dynamic:
        if group_key not in (None, "seed"):
            raise ValueError("dynamic rows must be grouped by trace seed")
        group_key = "seed"
        if not metadata or "dynamic_config" not in metadata:
            raise ValueError("dynamic training requires the frozen dynamic_config")
        dynamic_config = DynamicRouterConfig(**metadata["dynamic_config"])
        if dynamic_config.policy_track == "realistic" and priority_rr_config not in (None, ALGORITHMS["Priority RR"][1]):
            raise ValueError("realistic training requires frozen Priority RR parameters")
        policies = dynamic_action_names(dynamic_config)
    else:
        policies = tuple(ALGORITHMS)
    if model_kind not in {"classifier", "policy_cost"} or (model_kind == "policy_cost" and not is_dynamic):
        raise ValueError("policy_cost training requires dynamic observed-state features")
    labels = [row["label"] for row in rows]
    if not set(labels).issubset(policies):
        raise ValueError("training labels include an ineligible policy")
    train_indexes, validation_indexes, test_indexes = _split_indexes(rows, random_state, group_key)
    train_rows = [rows[index] for index in train_indexes]
    validation_rows = [rows[index] for index in validation_indexes]
    test_rows = [rows[index] for index in test_indexes]
    train_x = [[row[name] for name in feature_names] for row in train_rows]
    validation_x = [[row[name] for name in feature_names] for row in validation_rows]
    validation_y = [row["label"] for row in validation_rows]
    test_x = [[row[name] for name in feature_names] for row in test_rows]
    test_y = [row["label"] for row in test_rows]
    validation_static_scores = {
        algorithm: mean(row[_score_column(algorithm)] for row in validation_rows)
        for algorithm in policies
    }
    static_baseline = min(
        policies,
        key=lambda algorithm: (validation_static_scores[algorithm], policies.index(algorithm)),
    )
    if metadata and "static_baseline" in metadata:
        static_baseline = metadata["static_baseline"]
        if static_baseline not in policies:
            raise ValueError("static baseline must be an eligible policy")

    best = None
    best_key = None
    best_settings = None
    best_metrics = None
    candidate_metrics = []
    def fit_candidate(matrix, labeled_rows, settings):
        depth, leaf, weight = settings
        if model_kind == "policy_cost":
            from autoscheduler.model_bakeoff import _new_model
            regressor = _new_model("Decision Tree", {"max_depth": depth, "min_samples_leaf": leaf}, random_state)
            regressor.fit(matrix, [[row[_score_column(policy)] for policy in policies] for row in labeled_rows])
            return PolicyCostModel(regressor, policies)
        return DecisionTreeClassifier(
            max_depth=depth, min_samples_leaf=leaf, class_weight=weight, random_state=random_state,
        ).fit(matrix, [row["label"] for row in labeled_rows])

    from itertools import product
    weights = (None, "balanced") if is_dynamic and model_kind == "classifier" else (None,)
    for depth_rank, max_depth in enumerate((3, 5, 8, None)):
        for min_samples_leaf, class_weight in product((10, 5, 1), weights):
            settings = (max_depth, min_samples_leaf, class_weight)
            if candidate_settings is not None and settings not in candidate_settings:
                continue
            candidate = fit_candidate(train_x, train_rows, settings)
            predictions = list(candidate.predict(validation_x))
            accuracy = accuracy_score(validation_y, predictions)
            regret = _mean_regret(validation_rows, predictions)
            metrics = {
                "max_depth": max_depth,
                "min_samples_leaf": min_samples_leaf,
                "class_weight": class_weight,
                "validation_accuracy": accuracy,
                "validation_mean_regret": regret,
            }
            if scheduler_validation is not None:
                metrics.update(scheduler_validation(candidate))
            candidate_metrics.append(metrics)
            key = _candidate_key(metrics, depth_rank)
            if scheduler_validation is not None:
                key = (*scheduling_candidate_key(metrics), *key)
            if best_key is None or key < best_key:
                best, best_key = candidate, key
                best_settings = settings
                best_metrics = metrics

    test_predictions = list(best.predict(test_x))
    test_accuracy = accuracy_score(test_y, test_predictions)
    test_regret = _mean_regret(test_rows, test_predictions)
    # Internal test evaluates the train-only candidate. The saved model refits
    # train+validation and is evaluated separately on untouched workload seeds.
    final_model = fit_candidate(train_x + validation_x, train_rows + validation_rows, best_settings) if refit else best

    model_path = Path(model_path)
    model_path.parent.mkdir(parents=True, exist_ok=True)
    bundle_metadata = {
        "policy_set": list(policies),
        "priority_rr_config": priority_rr_config or dict(ALGORITHMS["Priority RR"][1]),
        "static_baseline": static_baseline,
        **(metadata or {}),
    }
    if is_dynamic:
        from autoscheduler.dynamic import dynamic_policy_parameters
        from autoscheduler.dynamic import dynamic_policy_names
        bundle_metadata.update(schema_version=DYNAMIC_SCHEMA_VERSION, policy_set=list(dynamic_policy_names(dynamic_config)),
                               action_set=list(policies),
                               model_kind=model_kind, label_provenance="synthetic_development_only")
        bundle_metadata["policy_parameters"] = dynamic_policy_parameters(dynamic_config, bundle_metadata["priority_rr_config"])
    constrained = scheduler_validation is not None and "validation_schedule_eligible" in best_metrics
    selected_for_development = bool(best_metrics.get("validation_schedule_eligible", False)) if constrained else None
    bundle_metadata["selected_for_development"] = selected_for_development
    bundle_metadata["diagnostic_only"] = selected_for_development is False
    joblib.dump({"model": final_model, "features": feature_names, "metadata": bundle_metadata}, model_path)
    report = {
        "rows": len(rows),
        "random_state": random_state,
        "split": {"train": 0.70, "validation": 0.15, "test": 0.15},
        "class_distribution": dict(Counter(labels)),
        "max_depth": best_settings[0],
        "min_samples_leaf": best_settings[1],
        "class_weight": best_settings[2],
        "model_kind": model_kind,
        "selected_for_development": selected_for_development,
        "diagnostic_only": selected_for_development is False,
        "refit_train_plus_validation": refit,
        "validation_accuracy": best_metrics["validation_accuracy"],
        "validation_mean_regret": best_metrics["validation_mean_regret"],
        "test_accuracy": test_accuracy,
        "test_mean_regret": test_regret,
        # Dynamic costs mean a feasible action followed by continuation, not a
        # continuously running static scheduler. Whole-workload comparators
        # are assessed separately by the scheduling validation callback.
        "validation_action_costs" if is_dynamic else "validation_static_scores": validation_static_scores,
        "static_baseline": static_baseline,
        "priority_rr_config": bundle_metadata["priority_rr_config"],
        "policy_set": bundle_metadata["policy_set"],
        "feature_importance": {
            name: float(value) for name, value in zip(feature_names, final_model.feature_importances_)
        },
        "candidate_metrics": candidate_metrics,
        "selection_basis": "safety_eligibility_then_realized_validation_schedule_score" if scheduler_validation is not None else "validation_action_regret",
    }
    if scheduler_validation is not None:
        report.update({key: value for key, value in best_metrics.items() if key.startswith("validation_schedule_")})
    if is_dynamic:
        from sklearn.metrics import confusion_matrix
        costs = [[row[_score_column(policy)] for policy in policies] for row in test_rows]
        report.update(
            status="SYNTHETIC_DEVELOPMENT_ONLY",
            test_confusion_matrix={
                actual: dict(zip(policies, map(int, counts))) for actual, counts in zip(
                    policies, confusion_matrix(test_y, test_predictions, labels=list(policies)),
                )
            },
            test_tie_aware_accuracy=mean(
                row[_score_column(prediction)] <= min(values) + 1e-12
                for row, prediction, values in zip(test_rows, test_predictions, costs)
            ),
            ambiguous_label_fraction=mean(
                sum(abs(row[_score_column(policy)] - min(row[_score_column(p)] for p in policies)) <= 1e-12
                    for policy in policies) > 1 for row in rows
            ),
            split_class_distribution={name: dict(Counter(row["label"] for row in split)) for name, split in
                                      (("train", train_rows), ("validation", validation_rows), ("test", test_rows))},
            internal_test_model="train_only_before_refit" if refit else "train_only_saved_without_refit",
        )
    if group_key is not None:
        report["split_group_key"] = group_key
        report["split_trace_counts"] = {
            name: len({rows[index][group_key] for index in split})
            for name, split in (
                ("train", train_indexes), ("validation", validation_indexes), ("test", test_indexes)
            )
        }
        report["split_groups"] = {
            name: sorted({rows[index][group_key] for index in split})
            for name, split in (("train", train_indexes), ("validation", validation_indexes), ("test", test_indexes))
        }
    return report


def load_model(
    path: str | Path, feature_names: tuple[str, ...] = FEATURE_NAMES,
    expected_dynamic_config=None, expected_priority_rr_config=None,
):
    joblib, *_ = _imports()
    bundle = joblib.load(path)
    if tuple(bundle.get("features", ())) != tuple(feature_names):
        raise ValueError("model feature schema does not match current code")
    from autoscheduler.dynamic import DYNAMIC_FEATURE_NAMES, DYNAMIC_SCHEMA_VERSION, DynamicRouterConfig, dynamic_action_names
    metadata = bundle.get("metadata", {})
    policies = tuple(ALGORITHMS)
    if tuple(feature_names) == DYNAMIC_FEATURE_NAMES or "dynamic_config" in metadata:
        from autoscheduler.dynamic import dynamic_policy_parameters
        if tuple(feature_names) != DYNAMIC_FEATURE_NAMES:
            raise ValueError("legacy dynamic feature schema is incompatible; retrain")
        if metadata.get("schema_version") != DYNAMIC_SCHEMA_VERSION or "dynamic_config" not in metadata:
            raise ValueError("incompatible dynamic model schema/configuration; retrain the model")
        config = DynamicRouterConfig(**metadata["dynamic_config"])
        policies = dynamic_action_names(config)
        if expected_dynamic_config is not None and config != expected_dynamic_config:
            raise ValueError("saved dynamic configuration differs from runtime; retrain")
        rr_config = metadata.get("priority_rr_config")
        if config.policy_track == "realistic" and rr_config != ALGORITHMS["Priority RR"][1]:
            raise ValueError("realistic saved model requires frozen Priority RR parameters; retrain")
        if not rr_config or (expected_priority_rr_config is not None and rr_config != expected_priority_rr_config):
            raise ValueError("saved Priority RR configuration differs from runtime; retrain")
        if metadata.get("policy_parameters") != dynamic_policy_parameters(config, rr_config):
            raise ValueError("saved policy parameters differ from current schedulers; retrain")
        model = bundle["model"]
        model.dynamic_config_ = config.__dict__
        model.priority_rr_config_ = rr_config
        from autoscheduler.dynamic import dynamic_policy_names
        model.policy_set_ = dynamic_policy_names(config)
        if metadata.get("action_set", metadata.get("policy_set")) != list(policies):
            raise ValueError("saved dynamic action set is incompatible; retrain")
    expected_policies = list(getattr(bundle["model"], "policy_set_", policies))
    if metadata.get("policy_set") != expected_policies:
        raise ValueError("model policy set does not match current schedulers; retrain the model")
    model = bundle["model"]
    estimator = model.regressor if isinstance(model, PolicyCostModel) else model
    if getattr(estimator, "n_features_in_", None) != len(feature_names):
        raise ValueError("saved estimator feature width does not match the schema; retrain")
    if isinstance(model, PolicyCostModel) and getattr(estimator, "n_outputs_", None) != len(policies):
        raise ValueError("saved cost estimator requires one output per policy; retrain")
    if hasattr(model, "classes_") and not set(model.classes_).issubset(policies):
        raise ValueError("saved estimator contains incompatible policy classes; retrain")
    if isinstance(model, PolicyCostModel) and model.policies != policies:
        raise ValueError("saved cost model action order is incompatible; retrain")
    return bundle["model"]


def load_model_metadata(path: str | Path) -> dict:
    joblib, *_ = _imports()
    return joblib.load(path).get("metadata", {})
