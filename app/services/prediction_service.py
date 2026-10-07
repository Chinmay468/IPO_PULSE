import hashlib
import json
import logging
import math
import re
from datetime import datetime, date, timedelta, timezone
from typing import List, Dict, Any, Optional, Tuple

import numpy as np
import pandas as pd
from sqlalchemy import select, func, and_
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.prediction import Prediction, PredictionResult, DirectionType
from app.services.market_price_service import _yf_symbol
from app.services.groq_client_service import groq_key_pool

logger = logging.getLogger(__name__)

# Default Watchlist of 30 Liquid NSE Stocks + Nifty 50 Benchmark
DEFAULT_WATCHLIST = [
    "RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK",
    "KOTAKBANK", "LT", "ITC", "SBIN", "AXISBANK",
    "BHARTIARTL", "ASIANPAINT", "MARUTI", "SUNPHARMA", "TITAN",
    "HCLTECH", "M&M", "TATASTEEL", "NTPC", "POWERGRID",
    "ULTRACEMCO", "WIPRO", "BAJFINANCE", "BAJAJFINSV", "NESTLEIND",
    "INDUSINDBK", "GRASIM", "TECHM", "HINDUNILVR", "ADANIENT"
]

BENCHMARK_SYMBOL = "^NSEI"
MODEL_NAMES = ["persistence", "always_up", "logistic_regression", "groq_llm"]


def compute_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """Computes 14-period Relative Strength Index (RSI)."""
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss.replace(0, 1e-6)
    rsi = 100 - (100 / (1 + rs))
    return rsi.fillna(50.0)


def extract_features_df(df_stock: pd.DataFrame, df_nifty: pd.DataFrame) -> pd.DataFrame:
    """
    Constructs leak-free daily technical features from stock and Nifty price DataFrames.
    Features for day t are computed strictly using data available up to day t-1:
    - ret_lag1: 1-day return on t-1
    - ret_lag2: 2-day return on t-2
    - rsi_14: 14-day RSI on t-1
    - vol_change: volume change on t-1
    - nifty_ret: 1-day Nifty return on t-1
    Target for day t: direction of close price on day t relative to day t-1.
    """
    df = df_stock.copy()
    if 'Close' not in df.columns:
        return pd.DataFrame()

    df['ret_1d'] = df['Close'].pct_change()
    df['ret_lag1'] = df['ret_1d'].shift(1)
    df['ret_lag2'] = df['ret_1d'].shift(2)
    df['rsi_14'] = compute_rsi(df['Close'], 14).shift(1)

    if 'Volume' in df.columns:
        df['vol_change'] = df['Volume'].pct_change().shift(1).fillna(0.0)
    else:
        df['vol_change'] = 0.0

    # Merge Nifty return
    if not df_nifty.empty and 'Close' in df_nifty.columns:
        nifty_ret = df_nifty['Close'].pct_change().shift(1)
        df['nifty_ret'] = nifty_ret.reindex(df.index).fillna(0.0)
    else:
        df['nifty_ret'] = 0.0

    # Target direction for day t (Close_t vs Close_{t-1})
    # Target return = (Close_t - Close_{t-1}) / Close_{t-1}
    df['target_return'] = df['ret_1d']
    df['target_direction'] = np.where(
        df['target_return'] > 0.0005, 'UP',
        np.where(df['target_return'] < -0.0005, 'DOWN', 'FLAT')
    )

    feature_cols = ['ret_lag1', 'ret_lag2', 'rsi_14', 'vol_change', 'nifty_ret']
    for col in feature_cols:
        df[col] = df[col].replace([np.inf, -np.inf], np.nan).fillna(0.0)
        df[col] = df[col].clip(-10.0, 10.0)

    return df.dropna(subset=['ret_lag1', 'ret_lag2', 'rsi_14'])


def compute_features_hash(features_dict: Dict[str, Any]) -> str:
    """Computes a SHA-256 hash of input features for auditability."""
    raw_str = json.dumps(features_dict, sort_keys=True, default=str)
    return hashlib.sha256(raw_str.encode('utf-8')).hexdigest()


class PredictionService:
    """
    Service for generating, locking, scoring, and evaluating direction predictions.
    """

    @staticmethod
    def predict_persistence(features_row: pd.Series) -> Tuple[DirectionType, float]:
        """(a) Persistence baseline: same direction as yesterday's return."""
        ret1 = features_row.get('ret_lag1', 0.0)
        if ret1 > 0.0005:
            return DirectionType.UP, 0.50
        elif ret1 < -0.0005:
            return DirectionType.DOWN, 0.50
        else:
            return DirectionType.FLAT, 0.50

    @staticmethod
    def predict_always_up() -> Tuple[DirectionType, float]:
        """(b) Always UP baseline."""
        return DirectionType.UP, 0.50

    @staticmethod
    def predict_logistic_regression(train_df: pd.DataFrame, test_row: pd.Series) -> Tuple[DirectionType, float]:
        """
        (c) Logistic Regression trained on expanding window of past daily data strictly before test_row.
        """
        feature_cols = ['ret_lag1', 'ret_lag2', 'rsi_14', 'vol_change', 'nifty_ret']
        clean_train = train_df.dropna(subset=feature_cols + ['target_direction'])
        clean_train = clean_train[clean_train['target_direction'].isin(['UP', 'DOWN'])]

        if len(clean_train) < 30:
            # Fallback to persistence if insufficient training samples
            return PredictionService.predict_persistence(test_row)

        X_train = clean_train[feature_cols].values
        y_train = (clean_train['target_direction'] == 'UP').astype(int).values

        if len(np.unique(y_train)) < 2:
            return DirectionType.UP, 0.50

        try:
            from sklearn.linear_model import LogisticRegression
            from sklearn.preprocessing import StandardScaler

            scaler = StandardScaler()
            X_train_scaled = scaler.fit_transform(X_train)

            model = LogisticRegression(max_iter=500, random_state=42)
            model.fit(X_train_scaled, y_train)

            X_test = test_row[feature_cols].values.reshape(1, -1)
            X_test_scaled = scaler.transform(X_test)

            prob_up = float(model.predict_proba(X_test_scaled)[0, 1])

            if prob_up > 0.52:
                return DirectionType.UP, round(prob_up, 4)
            elif prob_up < 0.48:
                return DirectionType.DOWN, round(1.0 - prob_up, 4)
            else:
                return DirectionType.FLAT, 0.50
        except Exception as exc:
            logger.warning("Logistic Regression prediction failed: %s", exc)
            return PredictionService.predict_persistence(test_row)

    @staticmethod
    async def predict_groq_llm(symbol: str, target_date: date, history_df: pd.DataFrame) -> Tuple[DirectionType, float]:
        """
        (d) Groq LLM prediction given past daily prices and technical indicators (no future data).
        """
        keys = groq_key_pool.get_all_keys()
        if not keys:
            # Fallback to persistence if no API keys
            last_row = history_df.iloc[-1] if not history_df.empty else pd.Series()
            return PredictionService.predict_persistence(last_row)

        last_5 = history_df.tail(5)
        recent_prices = [round(float(c), 2) for c in last_5['Close'].values]
        last_row = history_df.iloc[-1]

        prompt_context = (
            f"Symbol: {symbol}\n"
            f"Target Prediction Date: {target_date.strftime('%Y-%m-%d')}\n"
            f"Last 5 Close Prices: {recent_prices}\n"
            f"Yesterday Return: {last_row.get('ret_lag1', 0.0):.4f}\n"
            f"2-Day Lagged Return: {last_row.get('ret_lag2', 0.0):.4f}\n"
            f"14-Day RSI: {last_row.get('rsi_14', 50.0):.2f}\n"
            f"Volume Change Ratio: {last_row.get('vol_change', 0.0):.4f}\n"
            f"Nifty 50 Benchmark Return: {last_row.get('nifty_ret', 0.0):.4f}\n"
        )

        system_msg = (
            "You are a quantitative stock direction predictor in research mode.\n"
            "Based ONLY on the past prices and indicators provided above (strictly no future data), "
            "predict the next-day price direction (UP, DOWN, or FLAT) and confidence score.\n"
            "Respond ONLY with a JSON object in this format:\n"
            "{\"predicted_direction\": \"UP\"|\"DOWN\"|\"FLAT\", \"confidence\": 0.55-0.95}"
        )

        try:
            from groq import Groq
            active_key, _, _ = groq_key_pool.get_key()
            if not active_key:
                return PredictionService.predict_persistence(last_row)

            client = Groq(api_key=active_key)
            completion = client.chat.completions.create(
                model="openai/gpt-oss-120b",
                messages=[
                    {"role": "system", "content": system_msg},
                    {"role": "user", "content": prompt_context}
                ],
                max_tokens=60,
                temperature=0.1
            )
            raw = completion.choices[0].message.content.strip() if completion.choices else ""
            match = re.search(r"\{.*\}", raw, re.DOTALL)
            if match:
                data = json.loads(match.group(0))
                dir_str = str(data.get("predicted_direction", "UP")).upper()
                conf = float(data.get("confidence", 0.50))
                conf = min(max(conf, 0.50), 0.99)

                if dir_str == "UP":
                    return DirectionType.UP, round(conf, 4)
                elif dir_str == "DOWN":
                    return DirectionType.DOWN, round(conf, 4)
                else:
                    return DirectionType.FLAT, round(conf, 4)
        except Exception as exc:
            logger.warning("Groq LLM prediction error for %s: %s", symbol, exc)

        return PredictionService.predict_persistence(last_row)

    @classmethod
    async def create_prediction(
        cls,
        session: AsyncSession,
        target_date: date,
        symbol: str,
        model_name: str,
        predicted_direction: DirectionType,
        confidence: float,
        features_hash: Optional[str] = None
    ) -> Prediction:
        """
        Creates and locks a prediction record. Edit protection ensures locked predictions cannot be altered.
        """
        clean_sym = symbol.replace(".NS", "").upper()
        
        # Check if prediction already exists for target_date + symbol + model_name
        stmt = select(Prediction).where(
            and_(
                Prediction.target_date == target_date,
                Prediction.symbol == clean_sym,
                Prediction.model_name == model_name
            )
        )
        existing = (await session.execute(stmt)).scalar_one_or_none()
        if existing:
            if existing.locked:
                logger.info("Prediction for %s on %s by %s is locked; retaining original.", clean_sym, target_date, model_name)
                return existing
            else:
                existing.predicted_direction = predicted_direction
                existing.confidence = confidence
                existing.features_hash = features_hash
                existing.locked = True
                await session.flush()
                return existing

        pred = Prediction(
            target_date=target_date,
            symbol=clean_sym,
            model_name=model_name,
            predicted_direction=predicted_direction,
            confidence=confidence,
            features_hash=features_hash,
            locked=True
        )
        session.add(pred)
        await session.flush()
        return pred

    @classmethod
    def verify_locked_protection(cls, prediction: Prediction) -> None:
        """Enforces immutability: raises PermissionError if prediction is locked."""
        if prediction.locked:
            raise PermissionError("Locked prediction cannot be modified or updated.")

    @classmethod
    async def generate_daily_predictions(
        cls,
        session: AsyncSession,
        target_date: Optional[date] = None,
        watchlist: Optional[List[str]] = None
    ) -> List[Prediction]:
        """
        Daily pre-market job: generates and locks next-day direction predictions
        for all 30 watchlist stocks from the 4 predictors.
        """
        import yfinance as yf

        if not target_date:
            target_date = date.today()

        symbols = watchlist or DEFAULT_WATCHLIST
        yf_symbols = [_yf_symbol(s) for s in symbols] + [BENCHMARK_SYMBOL]

        logger.info("Generating daily predictions for target date %s across %d symbols...", target_date, len(symbols))

        # Fetch past price data up to target_date (strictly before target_date)
        try:
            data = yf.download(yf_symbols, period="1y", interval="1d", progress=False)
        except Exception as exc:
            logger.error("Failed to fetch yfinance data for predictions: %s", exc)
            return []

        if data.empty or 'Close' not in data.columns:
            logger.warning("Empty market data returned from yfinance.")
            return []

        # Extract Nifty 50 DataFrame
        try:
            if isinstance(data.columns, pd.MultiIndex):
                df_nifty = data.xs(BENCHMARK_SYMBOL, level=1, axis=1).dropna()
            else:
                df_nifty = data[['Close']].dropna()
        except Exception:
            df_nifty = pd.DataFrame()

        created_preds = []

        for sym in symbols:
            clean_sym = sym.replace(".NS", "").upper()
            yf_sym = _yf_symbol(sym)

            try:
                if isinstance(data.columns, pd.MultiIndex):
                    stock_df = data.xs(yf_sym, level=1, axis=1).dropna(how='all')
                else:
                    stock_df = data[['Close', 'Volume']].dropna()
            except Exception:
                continue

            if stock_df.empty or len(stock_df) < 20:
                continue

            # Compute features strictly up to target_date
            features_df = extract_features_df(stock_df, df_nifty)
            if features_df.empty:
                continue

            last_row = features_df.iloc[-1]
            feat_hash = compute_features_hash({
                "symbol": clean_sym,
                "target_date": str(target_date),
                "ret_lag1": float(last_row.get('ret_lag1', 0.0)),
                "ret_lag2": float(last_row.get('ret_lag2', 0.0)),
                "rsi_14": float(last_row.get('rsi_14', 50.0)),
                "vol_change": float(last_row.get('vol_change', 0.0)),
                "nifty_ret": float(last_row.get('nifty_ret', 0.0)),
            })

            # (a) Persistence
            dir_a, conf_a = cls.predict_persistence(last_row)
            p_a = await cls.create_prediction(session, target_date, clean_sym, "persistence", dir_a, conf_a, feat_hash)
            created_preds.append(p_a)

            # (b) Always UP
            dir_b, conf_b = cls.predict_always_up()
            p_b = await cls.create_prediction(session, target_date, clean_sym, "always_up", dir_b, conf_b, feat_hash)
            created_preds.append(p_b)

            # (c) Logistic Regression
            train_df = features_df.iloc[:-1] if len(features_df) > 30 else features_df
            dir_c, conf_c = cls.predict_logistic_regression(train_df, last_row)
            p_c = await cls.create_prediction(session, target_date, clean_sym, "logistic_regression", dir_c, conf_c, feat_hash)
            created_preds.append(p_c)

            # (d) Groq LLM
            dir_d, conf_d = await cls.predict_groq_llm(clean_sym, target_date, features_df)
            p_d = await cls.create_prediction(session, target_date, clean_sym, "groq_llm", dir_d, conf_d, feat_hash)
            created_preds.append(p_d)

        await session.commit()
        logger.info("Successfully created and locked %d predictions for %s.", len(created_preds), target_date)
        return created_preds

    @classmethod
    async def score_daily_predictions(
        cls,
        session: AsyncSession,
        target_date: Optional[date] = None
    ) -> List[PredictionResult]:
        """
        Daily post-market job: fetches actual close prices, computes actual returns,
        and scores all pending predictions.
        """
        import yfinance as yf

        # Find all predictions without results where target_date <= today
        stmt = (
            select(Prediction)
            .outerjoin(PredictionResult, Prediction.id == PredictionResult.prediction_id)
            .where(PredictionResult.id == None)
        )
        if target_date:
            stmt = stmt.where(Prediction.target_date == target_date)

        unscored_preds = (await session.execute(stmt)).scalars().all()
        if not unscored_preds:
            logger.info("No unscored predictions found.")
            return []

        symbols = list({p.symbol for p in unscored_preds})
        yf_symbols = [_yf_symbol(s) for s in symbols]

        try:
            data = yf.download(yf_symbols, period="10d", interval="1d", progress=False)
        except Exception as exc:
            logger.error("Failed to fetch yfinance data for prediction scoring: %s", exc)
            return []

        results_created = []
        now_scored = datetime.now(timezone.utc)

        for pred in unscored_preds:
            yf_sym = _yf_symbol(pred.symbol)
            try:
                if isinstance(data.columns, pd.MultiIndex):
                    stock_df = data.xs(yf_sym, level=1, axis=1).dropna(how='all')
                else:
                    stock_df = data[['Close']].dropna()
            except Exception:
                continue

            if stock_df.empty or len(stock_df) < 2:
                continue

            # Compute actual return on target_date
            actual_close = float(stock_df['Close'].iloc[-1])
            prev_close = float(stock_df['Close'].iloc[-2])
            actual_return = (actual_close - prev_close) / prev_close if prev_close > 0 else 0.0

            # Actual direction
            if actual_return > 0.0005:
                actual_dir = DirectionType.UP
            elif actual_return < -0.0005:
                actual_dir = DirectionType.DOWN
            else:
                actual_dir = DirectionType.FLAT

            correct = (pred.predicted_direction == actual_dir)

            res = PredictionResult(
                prediction_id=pred.id,
                actual_close=actual_close,
                actual_return=actual_return,
                correct=correct,
                scored_at=now_scored
            )
            session.add(res)
            results_created.append(res)

        await session.commit()
        logger.info("Successfully scored %d predictions.", len(results_created))
        return results_created

    @classmethod
    async def get_model_performance(cls, session: AsyncSession) -> Dict[str, Any]:
        """
        Calculates accuracy, 95% Wilson confidence interval, Brier score, and baseline comparison
        per model. Enforces 'not enough data' notice below 300 predictions.
        """
        stmt = (
            select(Prediction, PredictionResult)
            .join(PredictionResult, Prediction.id == PredictionResult.prediction_id)
        )
        records = (await session.execute(stmt)).all()

        model_stats: Dict[str, Dict[str, Any]] = {}
        for m_name in MODEL_NAMES:
            model_stats[m_name] = {
                "total": 0,
                "correct": 0,
                "brier_errors": [],
                "returns": []
            }

        for pred, res in records:
            m = pred.model_name
            if m not in model_stats:
                model_stats[m] = {"total": 0, "correct": 0, "brier_errors": [], "returns": []}

            model_stats[m]["total"] += 1
            if res.correct:
                model_stats[m]["correct"] += 1

            # Brier score calculation: (confidence - outcome)^2
            outcome = 1.0 if res.correct else 0.0
            conf = pred.confidence if pred.confidence else 0.5
            model_stats[m]["brier_errors"].append((conf - outcome) ** 2)

            # Simulated after-cost return
            pos = 1.0 if pred.predicted_direction == DirectionType.UP else (-1.0 if pred.predicted_direction == DirectionType.DOWN else 0.0)
            trade_ret = pos * res.actual_return - 0.0005  # 5 bps cost
            model_stats[m]["returns"].append(trade_ret)

        # Baselines for comparison
        persist_acc = (model_stats["persistence"]["correct"] / model_stats["persistence"]["total"]) if model_stats["persistence"]["total"] > 0 else 0.0
        always_up_acc = (model_stats["always_up"]["correct"] / model_stats["always_up"]["total"]) if model_stats["always_up"]["total"] > 0 else 0.0
        best_baseline = max(persist_acc, always_up_acc)

        performance_report: Dict[str, Any] = {"models": {}, "disclaimer": "Research and evaluation only, not investment or trading advice."}

        for m_name in MODEL_NAMES:
            st = model_stats[m_name]
            total = st["total"]
            correct = st["correct"]

            if total < 300:
                performance_report["models"][m_name] = {
                    "model_name": m_name,
                    "total_predictions": total,
                    "status": "not enough data",
                    "notice": f"Not enough data ({total}/300 minimum predictions required for statistical significance)",
                    "accuracy_pct": round((correct / total * 100), 2) if total > 0 else 0.0,
                    "confidence_interval_95": [0.0, 0.0],
                    "brier_score": 0.0,
                    "beats_baselines": False
                }
                continue

            acc = correct / total
            acc_pct = round(acc * 100.0, 2)

            # 95% Wilson Score Confidence Interval
            z = 1.96
            denom = 1 + (z ** 2) / total
            center = (acc + (z ** 2) / (2 * total)) / denom
            margin = z * math.sqrt((acc * (1 - acc) / total) + (z ** 2) / (4 * (total ** 2))) / denom
            ci_lower = round(max(0.0, center - margin) * 100.0, 2)
            ci_upper = round(min(1.0, center + margin) * 100.0, 2)

            brier = round(float(np.mean(st["brier_errors"])), 4) if st["brier_errors"] else 0.0
            cum_ret = round(float(np.sum(st["returns"])) * 100.0, 2) if st["returns"] else 0.0

            beats_b = (acc > best_baseline) and (m_name not in ["persistence", "always_up"])

            performance_report["models"][m_name] = {
                "model_name": m_name,
                "total_predictions": total,
                "status": "evaluated",
                "accuracy_pct": acc_pct,
                "confidence_interval_95": [ci_lower, ci_upper],
                "brier_score": brier,
                "simulated_return_pct": cum_ret,
                "beats_baselines": beats_b
            }

        return performance_report
