"""
Machine Learning Signal Predictor
Uses ML models to predict price movements and validate signals
"""
import asyncio
from typing import List, Optional, Dict, Any, Tuple
from datetime import datetime
import pandas as pd
import numpy as np
from loguru import logger
import pickle
import os

try:
    from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier
    from sklearn.preprocessing import StandardScaler
    from sklearn.model_selection import train_test_split
    SKLEARN_AVAILABLE = True
except ImportError:
    SKLEARN_AVAILABLE = False

try:
    import xgboost as xgb
    XGB_AVAILABLE = True
except ImportError:
    XGB_AVAILABLE = False

try:
    import pandas_ta as ta
    PANDAS_TA_AVAILABLE = True
except ImportError:
    PANDAS_TA_AVAILABLE = False

from core.base_agent import BaseAgent, AgentMessage
from core.models import Signal, SignalType
from core.model_manager import get_model_manager


class MLPredictor(BaseAgent):
    """
    ML-based price prediction agent.

    Models:
    - Random Forest for direction prediction
    - XGBoost for probability estimation
    - Gradient Boosting for trend classification

    Features:
    - Technical indicators
    - Price patterns
    - Volume metrics
    - Momentum features
    """

    def __init__(self, config: Optional[Dict] = None):
        super().__init__("MLPredictor", config)

        self.models: Dict[str, Any] = {}
        self.scalers: Dict[str, StandardScaler] = {}
        self.model_dir = config.get('model_dir', 'models/') if config else 'models/'
        self.pending_predictions: List[Dict] = []
        self.min_training_samples = 200

        # Model manager for persistence and staleness detection
        self.model_manager = get_model_manager()

        # Try loading persisted models first
        loaded = self.model_manager.load_models()
        if loaded:
            self.models = loaded["models"]
            self.scalers = loaded["scalers"]
            logger.info("Loaded persisted ML models from disk")
        else:
            # No saved models - initialize fresh
            self._init_models()

    def _init_models(self):
        """Initialize ML models"""
        if not SKLEARN_AVAILABLE:
            logger.warning("scikit-learn not available - ML features disabled")
            return

        # Direction classifier
        self.models['direction'] = RandomForestClassifier(
            n_estimators=100,
            max_depth=10,
            min_samples_split=5,
            random_state=42,
            n_jobs=-1
        )

        # Probability estimator
        if XGB_AVAILABLE:
            self.models['probability'] = xgb.XGBClassifier(
                n_estimators=100,
                max_depth=6,
                learning_rate=0.1,
                random_state=42
            )
        else:
            self.models['probability'] = GradientBoostingClassifier(
                n_estimators=100,
                max_depth=6,
                learning_rate=0.1,
                random_state=42
            )

        self.scalers['default'] = StandardScaler()

        logger.info("ML models initialized")

    async def process(self) -> None:
        """Process pending prediction requests"""
        # Check if models need retraining
        retrain_check = self.model_manager.should_retrain()
        if retrain_check["should_retrain"]:
            reason = retrain_check["reason"]
            logger.info(f"Model retrain triggered: {reason}")
            await self._auto_retrain(reason)

        if not self.pending_predictions:
            await asyncio.sleep(1)
            return

        while self.pending_predictions:
            request = self.pending_predictions.pop(0)
            prediction = await self.predict(request)

            if prediction:
                await self._send_prediction(prediction)

    async def handle_message(self, message: AgentMessage) -> None:
        """Handle incoming prediction requests"""
        if message.msg_type == 'predict':
            self.pending_predictions.append(message.payload)
            logger.debug(f"Prediction request received: {message.payload.get('symbol')}")

        elif message.msg_type == 'train':
            await self.train_models(message.payload)

    async def predict(self, request: Dict) -> Optional[Dict]:
        """Make prediction for a signal"""
        if not SKLEARN_AVAILABLE:
            return None

        symbol = request.get('symbol')
        market_type = request.get('market_type')

        # Get data and features
        data = await self._fetch_data(symbol, market_type)
        if data is None or len(data) < 50:
            return None

        features = await self._extract_features(data)
        if features is None:
            return None

        try:
            # Get latest features
            X = features.iloc[-1:].values

            # Scale features (use transform if scaler is already fitted, else fit_transform)
            scaler = self.scalers['default']
            if hasattr(scaler, 'mean_') and scaler.mean_ is not None:
                X_scaled = scaler.transform(features.values)
            else:
                X_scaled = scaler.fit_transform(features.values)
            X_current = X_scaled[-1:]

            predictions = {}

            # Direction prediction
            if 'direction' in self.models and hasattr(self.models['direction'], 'predict'):
                # Check if model is fitted
                try:
                    direction = self.models['direction'].predict(X_current)[0]
                    direction_proba = self.models['direction'].predict_proba(X_current)[0]
                    predictions['direction'] = 'up' if direction == 1 else 'down'
                    predictions['direction_confidence'] = float(max(direction_proba))
                except:
                    # Model not fitted - train on historical data
                    await self._train_on_history(features, data)
                    predictions['direction'] = 'unknown'
                    predictions['direction_confidence'] = 0.5

            # Probability estimation
            if 'probability' in self.models:
                try:
                    proba = self.models['probability'].predict_proba(X_current)[0]
                    predictions['up_probability'] = float(proba[1]) if len(proba) > 1 else 0.5
                except:
                    predictions['up_probability'] = 0.5

            # Track prediction for accuracy monitoring
            if predictions.get('direction') in ['up', 'down']:
                self.model_manager.record_prediction(
                    symbol=symbol,
                    predicted_direction=predictions['direction'],
                    confidence=predictions.get('direction_confidence', 0.5)
                )

            # Combine with original signal
            result = {
                **request,
                'ml_predictions': predictions,
                'ml_timestamp': datetime.now().isoformat()
            }

            # Calculate adjusted confidence
            original_confidence = request.get('confidence', 0.5)
            ml_confidence = predictions.get('direction_confidence', 0.5)
            result['ml_adjusted_confidence'] = (original_confidence + ml_confidence) / 2

            return result

        except Exception as e:
            logger.error(f"Prediction error: {e}")
            return None

    async def _fetch_data(self, symbol: str, market_type: str) -> Optional[pd.DataFrame]:
        """Fetch historical data for prediction"""
        try:
            import yfinance as yf

            if market_type == 'forex':
                symbol = f"{symbol}=X"
            elif market_type == 'crypto':
                symbol = symbol.replace('/', '-').replace('USDT', 'USD').replace('usdt', 'usd')

            ticker = yf.Ticker(symbol)
            df = ticker.history(period="1y", interval="1d")

            if df.empty:
                return None

            df.columns = [c.lower() for c in df.columns]
            return df

        except Exception as e:
            logger.debug(f"Data fetch error: {e}")
            return None

    async def _extract_features(self, data: pd.DataFrame) -> Optional[pd.DataFrame]:
        """Extract ML features from price data"""
        if not PANDAS_TA_AVAILABLE:
            return None

        try:
            df = data.copy()
            close = df['close']
            high = df['high']
            low = df['low']
            volume = df['volume']

            # Price features
            df['returns_1d'] = close.pct_change(1)
            df['returns_5d'] = close.pct_change(5)
            df['returns_10d'] = close.pct_change(10)
            df['returns_20d'] = close.pct_change(20)

            # Volatility features
            df['volatility_10d'] = df['returns_1d'].rolling(10).std()
            df['volatility_20d'] = df['returns_1d'].rolling(20).std()

            # Moving averages
            df['sma_10'] = ta.sma(close, length=10)
            df['sma_20'] = ta.sma(close, length=20)
            df['sma_50'] = ta.sma(close, length=50)
            df['ema_10'] = ta.ema(close, length=10)
            df['ema_20'] = ta.ema(close, length=20)

            # Price vs MAs
            df['price_sma10_ratio'] = close / df['sma_10']
            df['price_sma20_ratio'] = close / df['sma_20']
            df['price_sma50_ratio'] = close / df['sma_50']
            df['sma10_sma20_ratio'] = df['sma_10'] / df['sma_20']
            df['sma20_sma50_ratio'] = df['sma_20'] / df['sma_50']

            # RSI
            df['rsi_14'] = ta.rsi(close, length=14)
            df['rsi_7'] = ta.rsi(close, length=7)

            # MACD
            macd = ta.macd(close)
            df['macd'] = macd['MACD_12_26_9']
            df['macd_signal'] = macd['MACDs_12_26_9']
            df['macd_hist'] = macd['MACDh_12_26_9']

            # Bollinger Bands
            bb = ta.bbands(close, length=20)
            bb_cols = bb.columns.tolist()
            bb_upper_col = [c for c in bb_cols if c.startswith('BBU')][0]
            bb_lower_col = [c for c in bb_cols if c.startswith('BBL')][0]
            bb_mid_col = [c for c in bb_cols if c.startswith('BBM')][0]
            df['bb_upper'] = bb[bb_upper_col]
            df['bb_lower'] = bb[bb_lower_col]
            df['bb_mid'] = bb[bb_mid_col]
            df['bb_width'] = (df['bb_upper'] - df['bb_lower']) / df['bb_mid']
            df['bb_position'] = (close - df['bb_lower']) / (df['bb_upper'] - df['bb_lower'])

            # ATR
            df['atr_14'] = ta.atr(high, low, close, length=14)
            df['atr_pct'] = df['atr_14'] / close

            # ADX
            adx = ta.adx(high, low, close, length=14)
            df['adx'] = adx['ADX_14']
            df['di_plus'] = adx['DMP_14']
            df['di_minus'] = adx['DMN_14']

            # Stochastic
            stoch = ta.stoch(high, low, close)
            df['stoch_k'] = stoch['STOCHk_14_3_3']
            df['stoch_d'] = stoch['STOCHd_14_3_3']

            # Volume features
            df['volume_sma'] = volume.rolling(20).mean()
            df['volume_ratio'] = volume / df['volume_sma']

            # Candlestick features
            df['body'] = close - df['open']
            df['body_pct'] = df['body'] / df['open']
            df['upper_shadow'] = high - df[['open', 'close']].max(axis=1)
            df['lower_shadow'] = df[['open', 'close']].min(axis=1) - low

            # Range features
            df['high_low_range'] = (high - low) / close
            df['close_position'] = (close - low) / (high - low)

            # Lag features
            df['rsi_lag1'] = df['rsi_14'].shift(1)
            df['macd_lag1'] = df['macd'].shift(1)
            df['volume_ratio_lag1'] = df['volume_ratio'].shift(1)

            # Select feature columns
            feature_cols = [
                'returns_1d', 'returns_5d', 'returns_10d', 'returns_20d',
                'volatility_10d', 'volatility_20d',
                'price_sma10_ratio', 'price_sma20_ratio', 'price_sma50_ratio',
                'sma10_sma20_ratio', 'sma20_sma50_ratio',
                'rsi_14', 'rsi_7',
                'macd', 'macd_signal', 'macd_hist',
                'bb_width', 'bb_position',
                'atr_pct',
                'adx', 'di_plus', 'di_minus',
                'stoch_k', 'stoch_d',
                'volume_ratio',
                'body_pct', 'high_low_range', 'close_position',
                'rsi_lag1', 'macd_lag1', 'volume_ratio_lag1'
            ]

            features = df[feature_cols].copy()
            features = features.replace([np.inf, -np.inf], np.nan)
            features = features.dropna()

            if features.empty:
                return None

            return features

        except Exception as e:
            logger.error(f"Feature extraction error: {e}")
            return None

    async def _train_on_history(self, features: pd.DataFrame, data: pd.DataFrame) -> None:
        """Train models on historical data"""
        if len(features) < self.min_training_samples:
            return

        try:
            # Create target (1 if price up next day, 0 if down)
            y = (data['close'].shift(-1) > data['close']).astype(int)
            y = y.loc[features.index[:-1]]  # Exclude last row (no future data)

            X = features.iloc[:-1]

            # Split data
            X_train, X_test, y_train, y_test = train_test_split(
                X, y, test_size=0.2, shuffle=False
            )

            # Scale
            X_train_scaled = self.scalers['default'].fit_transform(X_train)
            X_test_scaled = self.scalers['default'].transform(X_test)

            # Train direction model
            self.models['direction'].fit(X_train_scaled, y_train)

            # Train probability model
            self.models['probability'].fit(X_train_scaled, y_train)

            # Log accuracy
            train_acc = self.models['direction'].score(X_train_scaled, y_train)
            test_acc = self.models['direction'].score(X_test_scaled, y_test)

            logger.info(f"Models trained - Train acc: {train_acc:.2%}, Test acc: {test_acc:.2%}")

            # Save models with versioning
            self.model_manager.save_models(
                models=self.models,
                scalers=self.scalers,
                train_accuracy=train_acc,
                test_accuracy=test_acc,
                training_samples=len(X_train),
                feature_count=X_train.shape[1],
                symbols=[data.attrs.get('symbol', 'unknown')] if hasattr(data, 'attrs') else ['unknown']
            )

        except Exception as e:
            logger.error(f"Training error: {e}")

    async def train_models(self, config: Dict) -> None:
        """Train models with custom configuration"""
        symbols = config.get('symbols', [])

        for symbol in symbols:
            data = await self._fetch_data(symbol, config.get('market_type', 'equity'))
            if data is not None:
                features = await self._extract_features(data)
                if features is not None:
                    await self._train_on_history(features, data)

    def save_models(self, path: Optional[str] = None):
        """Save trained models to disk"""
        save_path = path or self.model_dir

        if not os.path.exists(save_path):
            os.makedirs(save_path)

        for name, model in self.models.items():
            model_file = os.path.join(save_path, f"{name}_model.pkl")
            with open(model_file, 'wb') as f:
                pickle.dump(model, f)

        for name, scaler in self.scalers.items():
            scaler_file = os.path.join(save_path, f"{name}_scaler.pkl")
            with open(scaler_file, 'wb') as f:
                pickle.dump(scaler, f)

        logger.info(f"Models saved to {save_path}")

    def load_models(self, path: Optional[str] = None):
        """Load trained models from disk"""
        load_path = path or self.model_dir

        if not os.path.exists(load_path):
            return

        for name in ['direction', 'probability']:
            model_file = os.path.join(load_path, f"{name}_model.pkl")
            if os.path.exists(model_file):
                with open(model_file, 'rb') as f:
                    self.models[name] = pickle.load(f)

        scaler_file = os.path.join(load_path, "default_scaler.pkl")
        if os.path.exists(scaler_file):
            with open(scaler_file, 'rb') as f:
                self.scalers['default'] = pickle.load(f)

        logger.info(f"Models loaded from {load_path}")

    async def _auto_retrain(self, reason: str) -> None:
        """Auto-retrain models when staleness detected"""
        logger.info(f"Auto-retraining models (reason: {reason})")

        # Train on a diverse set of liquid symbols
        training_symbols = {
            'equity': ['SPY', 'QQQ', 'AAPL', 'MSFT', 'NVDA', 'TSLA'],
            'crypto': ['BTC-USD', 'ETH-USD'],
        }

        for market_type, symbols in training_symbols.items():
            for symbol in symbols:
                try:
                    data = await self._fetch_data(symbol, market_type)
                    if data is not None and len(data) >= self.min_training_samples:
                        features = await self._extract_features(data)
                        if features is not None:
                            await self._train_on_history(features, data)
                            logger.info(f"Retrained on {symbol}")
                except Exception as e:
                    logger.debug(f"Retrain error for {symbol}: {e}")

        # Check if new model is better
        accuracy = self.model_manager.get_rolling_accuracy()
        if accuracy is not None:
            logger.info(f"Post-retrain accuracy: {accuracy:.2%}")

            # If still bad, rollback to previous version
            if accuracy < 0.50:
                logger.warning("New model worse than random - rolling back")
                self.model_manager.rollback()
                loaded = self.model_manager.load_models()
                if loaded:
                    self.models = loaded["models"]
                    self.scalers = loaded["scalers"]

    def record_outcome(self, symbol: str, actual_direction: str) -> None:
        """Record actual outcome for prediction tracking"""
        self.model_manager.record_outcome(symbol, actual_direction)

    async def _send_prediction(self, prediction: Dict) -> None:
        """Send prediction to coordinator"""
        await self.send_message(
            target='coordinator',
            msg_type='ml_prediction',
            payload=prediction,
            priority=3
        )
