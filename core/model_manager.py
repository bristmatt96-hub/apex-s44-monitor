"""
Model Manager
Handles model persistence, versioning, staleness detection, and auto-retraining
"""
import json
import os
import pickle
import shutil
from pathlib import Path
from typing import Dict, Optional, Any, List
from datetime import datetime, timedelta
from dataclasses import dataclass, asdict
from loguru import logger


@dataclass
class ModelMetadata:
    """Metadata about a saved model"""
    model_name: str
    version: int
    trained_at: str
    training_samples: int
    train_accuracy: float
    test_accuracy: float
    feature_count: int
    symbols_trained_on: List[str]
    is_active: bool = True


@dataclass
class PredictionRecord:
    """Record of a prediction and its outcome"""
    symbol: str
    predicted_direction: str  # 'up' or 'down'
    confidence: float
    actual_direction: Optional[str] = None  # filled in later
    correct: Optional[bool] = None
    timestamp: str = ""


class ModelManager:
    """
    Manages ML model lifecycle:
    - Save/load models with versioning
    - Track prediction accuracy in real-time
    - Auto-retrain when accuracy drops below threshold
    - Keep last N model versions as fallback
    - Weekly scheduled retraining

    Storage:
    models/
    ├── active/                  # Currently active models
    │   ├── direction_model.pkl
    │   ├── probability_model.pkl
    │   └── default_scaler.pkl
    ├── versions/                # Historical versions
    │   ├── v001/
    │   ├── v002/
    │   └── v003/
    ├── metadata.json            # Model metadata and history
    └── predictions.json         # Prediction tracking log
    """

    def __init__(self, base_path: str = "models"):
        self.base_path = Path(base_path)
        self.active_path = self.base_path / "active"
        self.versions_path = self.base_path / "versions"

        # Create directories
        self.active_path.mkdir(parents=True, exist_ok=True)
        self.versions_path.mkdir(parents=True, exist_ok=True)

        # Files
        self.metadata_file = self.base_path / "metadata.json"
        self.predictions_file = self.base_path / "predictions.json"

        # Load state
        self.metadata = self._load_metadata()
        self.predictions: List[Dict] = self._load_predictions()

        # Config
        self.accuracy_threshold = 0.55    # Retrain below 55%
        self.retrain_interval_days = 7    # Weekly retraining
        self.max_versions = 3             # Keep last 3 versions
        self.min_predictions_for_check = 20  # Need 20 predictions before checking accuracy
        self.rolling_window = 50          # Check last 50 predictions

    def _load_metadata(self) -> Dict:
        """Load model metadata"""
        if self.metadata_file.exists():
            with open(self.metadata_file, 'r') as f:
                return json.load(f)
        return {
            "current_version": 0,
            "models": {},
            "last_trained": None,
            "last_retrain_check": None,
            "total_retrains": 0,
            "version_history": []
        }

    def _save_metadata(self) -> None:
        """Save metadata"""
        with open(self.metadata_file, 'w') as f:
            json.dump(self.metadata, f, indent=2, default=str)

    def _load_predictions(self) -> List[Dict]:
        """Load prediction history"""
        if self.predictions_file.exists():
            with open(self.predictions_file, 'r') as f:
                return json.load(f)
        return []

    def _save_predictions(self) -> None:
        """Save predictions (keep last 500)"""
        self.predictions = self.predictions[-500:]
        with open(self.predictions_file, 'w') as f:
            json.dump(self.predictions, f, indent=2, default=str)

    # ==================== Save / Load ====================

    def save_models(
        self,
        models: Dict[str, Any],
        scalers: Dict[str, Any],
        train_accuracy: float,
        test_accuracy: float,
        training_samples: int,
        feature_count: int,
        symbols: List[str]
    ) -> int:
        """
        Save models with versioning.
        Returns the new version number.
        """
        # Increment version
        version = self.metadata["current_version"] + 1
        self.metadata["current_version"] = version

        # Save to active directory
        for name, model in models.items():
            model_file = self.active_path / f"{name}_model.pkl"
            with open(model_file, 'wb') as f:
                pickle.dump(model, f)

        for name, scaler in scalers.items():
            scaler_file = self.active_path / f"{name}_scaler.pkl"
            with open(scaler_file, 'wb') as f:
                pickle.dump(scaler, f)

        # Save versioned copy
        version_dir = self.versions_path / f"v{version:03d}"
        version_dir.mkdir(exist_ok=True)

        for name, model in models.items():
            model_file = version_dir / f"{name}_model.pkl"
            with open(model_file, 'wb') as f:
                pickle.dump(model, f)

        for name, scaler in scalers.items():
            scaler_file = version_dir / f"{name}_scaler.pkl"
            with open(scaler_file, 'wb') as f:
                pickle.dump(scaler, f)

        # Update metadata
        model_meta = ModelMetadata(
            model_name="trading_predictor",
            version=version,
            trained_at=datetime.now().isoformat(),
            training_samples=training_samples,
            train_accuracy=train_accuracy,
            test_accuracy=test_accuracy,
            feature_count=feature_count,
            symbols_trained_on=symbols,
            is_active=True
        )

        self.metadata["models"][f"v{version:03d}"] = asdict(model_meta)
        self.metadata["last_trained"] = datetime.now().isoformat()
        self.metadata["total_retrains"] += 1
        self.metadata["version_history"].append({
            "version": version,
            "trained_at": datetime.now().isoformat(),
            "test_accuracy": test_accuracy,
            "reason": "scheduled" if self.metadata["total_retrains"] > 1 else "initial"
        })

        self._save_metadata()

        # Cleanup old versions
        self._cleanup_old_versions()

        logger.info(
            f"Models saved (v{version:03d}) - "
            f"Train: {train_accuracy:.2%}, Test: {test_accuracy:.2%}"
        )

        return version

    def load_models(self) -> Optional[Dict]:
        """
        Load active models from disk.
        Returns dict with 'models' and 'scalers' keys, or None if not found.
        """
        models = {}
        scalers = {}

        # Load models
        for name in ['direction', 'probability']:
            model_file = self.active_path / f"{name}_model.pkl"
            if model_file.exists():
                with open(model_file, 'rb') as f:
                    models[name] = pickle.load(f)

        # Load scalers
        scaler_file = self.active_path / "default_scaler.pkl"
        if scaler_file.exists():
            with open(scaler_file, 'rb') as f:
                scalers['default'] = pickle.load(f)

        if not models:
            return None

        logger.info(
            f"Models loaded (v{self.metadata['current_version']:03d}) - "
            f"Last trained: {self.metadata.get('last_trained', 'never')}"
        )

        return {"models": models, "scalers": scalers}

    def rollback(self, to_version: Optional[int] = None) -> bool:
        """Rollback to a previous model version"""
        if to_version is None:
            # Rollback to previous version
            to_version = self.metadata["current_version"] - 1

        version_dir = self.versions_path / f"v{to_version:03d}"
        if not version_dir.exists():
            logger.error(f"Version v{to_version:03d} not found")
            return False

        # Copy version files to active
        for f in version_dir.iterdir():
            shutil.copy2(f, self.active_path / f.name)

        logger.info(f"Rolled back to v{to_version:03d}")
        return True

    def _cleanup_old_versions(self) -> None:
        """Keep only the last N versions"""
        versions = sorted(self.versions_path.iterdir())
        while len(versions) > self.max_versions:
            oldest = versions.pop(0)
            shutil.rmtree(oldest)
            logger.debug(f"Cleaned up old version: {oldest.name}")

    # ==================== Prediction Tracking ====================

    def record_prediction(
        self,
        symbol: str,
        predicted_direction: str,
        confidence: float
    ) -> None:
        """Record a prediction for later accuracy checking"""
        self.predictions.append({
            "symbol": symbol,
            "predicted_direction": predicted_direction,
            "confidence": confidence,
            "actual_direction": None,
            "correct": None,
            "timestamp": datetime.now().isoformat()
        })
        self._save_predictions()

    def record_outcome(
        self,
        symbol: str,
        actual_direction: str,
        timestamp_approx: Optional[str] = None
    ) -> None:
        """Record the actual outcome of a prediction"""
        # Find matching prediction (most recent for this symbol without outcome)
        for pred in reversed(self.predictions):
            if (pred["symbol"] == symbol and
                    pred["actual_direction"] is None):
                pred["actual_direction"] = actual_direction
                pred["correct"] = (pred["predicted_direction"] == actual_direction)
                break

        self._save_predictions()

    def get_rolling_accuracy(self) -> Optional[float]:
        """Get accuracy over the rolling window"""
        evaluated = [p for p in self.predictions if p["correct"] is not None]

        if len(evaluated) < self.min_predictions_for_check:
            return None  # Not enough data

        recent = evaluated[-self.rolling_window:]
        correct = sum(1 for p in recent if p["correct"])

        return correct / len(recent)

    def get_accuracy_by_market(self) -> Dict[str, float]:
        """Get accuracy broken down by market type"""
        evaluated = [p for p in self.predictions if p["correct"] is not None]

        market_stats = {}
        for pred in evaluated:
            symbol = pred["symbol"]
            # Simple market type detection
            if '/' in symbol or symbol.endswith('USD'):
                market = 'crypto'
            elif len(symbol) == 6 and symbol.isalpha():
                market = 'forex'
            else:
                market = 'equity'

            if market not in market_stats:
                market_stats[market] = {"correct": 0, "total": 0}

            market_stats[market]["total"] += 1
            if pred["correct"]:
                market_stats[market]["correct"] += 1

        return {
            market: stats["correct"] / stats["total"]
            for market, stats in market_stats.items()
            if stats["total"] > 0
        }

    # ==================== Staleness Detection ====================

    def is_stale(self) -> bool:
        """
        Check if models are stale and need retraining.

        Returns True if:
        - Accuracy dropped below threshold (55%)
        - Haven't retrained in over a week
        - No models exist yet
        """
        # No models saved yet
        if self.metadata["current_version"] == 0:
            return True

        # Check accuracy
        accuracy = self.get_rolling_accuracy()
        if accuracy is not None and accuracy < self.accuracy_threshold:
            logger.warning(
                f"Model accuracy dropped to {accuracy:.2%} "
                f"(threshold: {self.accuracy_threshold:.2%}) - STALE"
            )
            return True

        # Check time since last training
        last_trained = self.metadata.get("last_trained")
        if last_trained:
            last_dt = datetime.fromisoformat(last_trained)
            days_since = (datetime.now() - last_dt).days
            if days_since >= self.retrain_interval_days:
                logger.info(
                    f"Models are {days_since} days old "
                    f"(max: {self.retrain_interval_days}) - scheduling retrain"
                )
                return True

        return False

    def should_retrain(self) -> Dict[str, Any]:
        """
        Comprehensive check if retraining is needed.
        Returns dict with reason and details.
        """
        result = {
            "should_retrain": False,
            "reason": None,
            "details": {}
        }

        # No models
        if self.metadata["current_version"] == 0:
            result["should_retrain"] = True
            result["reason"] = "no_models"
            return result

        # Accuracy check
        accuracy = self.get_rolling_accuracy()
        if accuracy is not None:
            result["details"]["current_accuracy"] = accuracy
            if accuracy < self.accuracy_threshold:
                result["should_retrain"] = True
                result["reason"] = "low_accuracy"
                result["details"]["threshold"] = self.accuracy_threshold
                return result

        # Time check
        last_trained = self.metadata.get("last_trained")
        if last_trained:
            last_dt = datetime.fromisoformat(last_trained)
            days_since = (datetime.now() - last_dt).days
            result["details"]["days_since_training"] = days_since

            if days_since >= self.retrain_interval_days:
                result["should_retrain"] = True
                result["reason"] = "scheduled"
                return result

        return result

    def get_status(self) -> Dict:
        """Get model manager status"""
        accuracy = self.get_rolling_accuracy()
        evaluated = [p for p in self.predictions if p["correct"] is not None]

        return {
            "current_version": self.metadata["current_version"],
            "last_trained": self.metadata.get("last_trained"),
            "total_retrains": self.metadata.get("total_retrains", 0),
            "rolling_accuracy": f"{accuracy:.2%}" if accuracy else "insufficient data",
            "predictions_tracked": len(self.predictions),
            "predictions_evaluated": len(evaluated),
            "is_stale": self.is_stale(),
            "versions_stored": len(list(self.versions_path.iterdir())),
            "accuracy_by_market": self.get_accuracy_by_market()
        }


# Singleton
_manager_instance: Optional[ModelManager] = None


def get_model_manager() -> ModelManager:
    """Get or create the model manager instance"""
    global _manager_instance
    if _manager_instance is None:
        _manager_instance = ModelManager()
    return _manager_instance
