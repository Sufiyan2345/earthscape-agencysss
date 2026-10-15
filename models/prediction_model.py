from utils.database import get_collection, next_id
from utils.helper import get_cached_value
from datetime import datetime
import json


class Prediction:
    def __init__(self, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)

    @staticmethod
    def create(model_name, model_type, input_params, prediction_result,
               confidence, created_by, dataset_id=None, status='completed'):
        col = get_collection('predictions')
        pred_id = next_id('predictions')
        col.insert_one({
            'id': pred_id,
            'model_name': model_name,
            'model_type': model_type,
            'input_params': json.dumps(input_params) if isinstance(input_params, dict) else input_params,
            'prediction_result': json.dumps(prediction_result) if isinstance(prediction_result, dict) else prediction_result,
            'confidence': confidence,
            'dataset_id': dataset_id,
            'created_by': created_by,
            'status': status,
            'created_at': datetime.utcnow().isoformat(),
        })
        return pred_id

    @staticmethod
    def get_all(limit=50):
        return get_cached_value('predictions:all:{}'.format(limit), lambda: list(get_collection('predictions').find().sort('created_at', -1).limit(limit)), ttl_seconds=60)

    @staticmethod
    def get_by_id(pred_id):
        return get_collection('predictions').find_one({'id': int(pred_id)})

    @staticmethod
    def get_by_model(model_name, limit=50):
        return get_cached_value('predictions:model:{}:{}'.format(model_name, limit), lambda: list(
            get_collection('predictions').find({'model_name': model_name})
            .sort('created_at', -1).limit(limit)
        ), ttl_seconds=60)

    @staticmethod
    def get_count():
        return get_cached_value('predictions:total_count', lambda: get_collection('predictions').count_documents({}), ttl_seconds=60)

    @staticmethod
    def get_live_forecast(monthly, months_ahead=3):
        """Recompute next-month forecasts from the CURRENT monthly trends.

        Stored predictions are snapshots from when an ML model was last run;
        this helper projects the latest data forward with a linear trend so
        the forecast charts always reflect freshly updated climate data.

        `monthly` must be in ascending chronological order, each entry having
        'period' (or 'month') as 'YYYY-MM' plus 'avg_temp' / 'total_rainfall'.
        """
        periods, temps, rains = [], [], []
        for m in monthly or []:
            period = m.get('period') or m.get('month')
            if not period:
                continue
            periods.append(period)
            temps.append(float(m['avg_temp']) if m.get('avg_temp') is not None else None)
            rains.append(float(m['total_rainfall']) if m.get('total_rainfall') is not None else None)

        if not periods:
            return []

        def _trend(values):
            pts = [(i, v) for i, v in enumerate(values) if v is not None]
            if not pts:
                return None
            n = len(pts)
            if n == 1:
                return pts[0][1], 0.0
            mean_x = sum(p[0] for p in pts) / n
            mean_y = sum(p[1] for p in pts) / n
            denom = sum((p[0] - mean_x) ** 2 for p in pts)
            slope = sum((p[0] - mean_x) * (p[1] - mean_y) for p in pts) / denom if denom else 0.0
            return mean_y, slope

        temp_trend = _trend(temps)
        rain_trend = _trend(rains)
        last_index = len(periods) - 1

        def _value_at(trend, index):
            if trend is None:
                return None
            mean_y, slope = trend
            # mean_y sits at the mean x of the fitted points; re-anchor to series end
            pts = [i for i, v in enumerate(temps if trend is temp_trend else rains) if v is not None]
            mean_x = sum(pts) / len(pts)
            return mean_y + slope * (index - mean_x)

        # Roll the last 'YYYY-MM' period forward
        try:
            year, month = int(periods[-1][:4]), int(periods[-1][5:7])
        except (ValueError, IndexError):
            return []

        forecast = []
        for step in range(1, months_ahead + 1):
            month += 1
            if month > 12:
                month = 1
                year += 1
            temp_val = _value_at(temp_trend, last_index + step)
            rain_val = _value_at(rain_trend, last_index + step)
            forecast.append({
                'period': f'{year}-{month:02d}',
                'predicted_avg_temp': round(temp_val, 1) if temp_val is not None else None,
                'predicted_rainfall_mm': round(max(0.0, rain_val), 1) if rain_val is not None else None,
                'live': True,
            })
        return forecast

    @staticmethod
    def overlay_latest_ml(live_forecast, predictions, latest_data_ts):
        """Overlay ML predictions created AFTER the newest climate record onto
        the live forecast. After a data update + model retrain this shows the
        retrained model's values instead of the plain linear projection, while
        a data-only update still falls back to the live forecast."""
        if not live_forecast or not latest_data_ts:
            return live_forecast
        latest_by_type = {}
        for p in predictions or []:  # expected sorted newest-first
            mt = p.get('model_type')
            if mt in ('temperature', 'rainfall') and mt not in latest_by_type:
                latest_by_type[mt] = p

        def _result(p):
            r = p.get('prediction_result')
            if isinstance(r, str):
                try:
                    r = json.loads(r)
                except (json.JSONDecodeError, TypeError):
                    return {}
            return r if isinstance(r, dict) else {}

        def _number(value):
            try:
                return float(value)
            except (TypeError, ValueError):
                return None

        target = live_forecast[0]
        tp = latest_by_type.get('temperature')
        if tp and (tp.get('created_at') or '') > latest_data_ts:
            value = _number(_result(tp).get('predicted_avg_temp'))
            if value is not None:
                target['predicted_avg_temp'] = round(value, 1)
                target['confidence'] = tp.get('confidence', 0.8)
                target['source'] = 'ml'
        rp = latest_by_type.get('rainfall')
        if rp and (rp.get('created_at') or '') > latest_data_ts:
            value = _number(_result(rp).get('predicted_rainfall_mm'))
            if value is not None:
                target['predicted_rainfall_mm'] = round(max(0.0, value), 1)
                target['confidence'] = rp.get('confidence', 0.8)
                target['source'] = 'ml'
        return live_forecast

    @staticmethod
    def delete(pred_id):
        get_collection('predictions').delete_one({'id': int(pred_id)})

    @staticmethod
    def delete_many(pred_ids):
        """Delete the selected stored predictions and return the count."""
        ids = [int(pred_id) for pred_id in pred_ids]
        if not ids:
            return 0
        return get_collection('predictions').delete_many({'id': {'$in': ids}}).deleted_count
