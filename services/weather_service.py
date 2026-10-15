"""Live weather tools for the EarthScape assistant.

Open-Meteo is used because its current and forecast endpoints do not require an
API key. The assistant receives only the returned weather facts, never request
credentials or arbitrary URLs from user input.
"""
import requests


class WeatherServiceError(RuntimeError):
    """Raised when a live weather lookup cannot be completed."""


_GEOCODING_URL = 'https://geocoding-api.open-meteo.com/v1/search'
_FORECAST_URL = 'https://api.open-meteo.com/v1/forecast'


def _number(value, digits=1):
    try:
        return round(float(value), digits)
    except (TypeError, ValueError):
        return None


def geocode_location(location):
    name = ' '.join(str(location or '').split()).strip()
    if not name:
        raise WeatherServiceError('A weather location is required.')
    try:
        response = requests.get(_GEOCODING_URL, params={
            'name': name, 'count': 1, 'language': 'en', 'format': 'json',
        }, timeout=8)
        response.raise_for_status()
        results = response.json().get('results') or []
        if not results:
            raise WeatherServiceError(f'Location "{name}" was not found.')
        place = results[0]
        return {
            'name': place.get('name') or name,
            'country': place.get('country'),
            'latitude': place.get('latitude'),
            'longitude': place.get('longitude'),
        }
    except WeatherServiceError:
        raise
    except (requests.RequestException, ValueError, TypeError) as error:
        raise WeatherServiceError('Live weather data could not be retrieved.') from error


def get_current_weather(location):
    place = geocode_location(location)
    try:
        response = requests.get(_FORECAST_URL, params={
            'latitude': place['latitude'],
            'longitude': place['longitude'],
            'current': 'temperature_2m,relative_humidity_2m,precipitation,weather_code,wind_speed_10m,surface_pressure',
            'timezone': 'auto',
        }, timeout=8)
        response.raise_for_status()
        current = response.json().get('current') or {}
        if not current:
            raise WeatherServiceError('Live weather data could not be retrieved.')
        return {
            'location': place['name'],
            'country': place.get('country'),
            'latitude': place.get('latitude'),
            'longitude': place.get('longitude'),
            'observed_at': current.get('time'),
            'temperature_c': _number(current.get('temperature_2m')),
            'humidity_percent': _number(current.get('relative_humidity_2m'), 0),
            'precipitation_mm': _number(current.get('precipitation')),
            'wind_speed_kmh': _number(current.get('wind_speed_10m')),
            'pressure_hpa': _number(current.get('surface_pressure')),
            'weather_code': current.get('weather_code'),
            'source': 'Open-Meteo',
        }
    except WeatherServiceError:
        raise
    except (requests.RequestException, ValueError, TypeError) as error:
        raise WeatherServiceError('Live weather data could not be retrieved.') from error


def get_weather_forecast(location, days=3):
    place = geocode_location(location)
    try:
        response = requests.get(_FORECAST_URL, params={
            'latitude': place['latitude'],
            'longitude': place['longitude'],
            'daily': 'temperature_2m_max,temperature_2m_min,precipitation_sum,weather_code',
            'forecast_days': max(1, min(int(days), 7)),
            'timezone': 'auto',
        }, timeout=8)
        response.raise_for_status()
        daily = response.json().get('daily') or {}
        dates = daily.get('time') or []
        return {
            'location': place['name'],
            'country': place.get('country'),
            'source': 'Open-Meteo',
            'days': [
                {
                    'date': date,
                    'max_temperature_c': _number((daily.get('temperature_2m_max') or [])[index]),
                    'min_temperature_c': _number((daily.get('temperature_2m_min') or [])[index]),
                    'precipitation_mm': _number((daily.get('precipitation_sum') or [])[index]),
                    'weather_code': (daily.get('weather_code') or [])[index],
                }
                for index, date in enumerate(dates)
            ],
        }
    except (requests.RequestException, ValueError, TypeError, IndexError) as error:
        raise WeatherServiceError('Weather forecast could not be retrieved.') from error
