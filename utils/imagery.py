"""
Satellite imagery analysis utilities.

Extracts climate-relevant indicators from uploaded satellite/aerial images
(PNG, JPG, TIFF, BMP, GIF, WEBP). All indicators are spectral proxies
derived from the visible RGB bands - they are clearly labelled as estimates
so downstream consumers know they are imagery-derived, not station readings.
"""
import os
import numpy as np

ALLOWED_IMAGE_EXTENSIONS = {'png', 'jpg', 'jpeg', 'jfif', 'jpe', 'tif', 'tiff', 'bmp', 'gif', 'webp'}
MAX_IMAGE_PIXELS = 4096 * 4096  # guard against decompression bombs


def is_allowed_image(filename):
    """True if the filename has a supported image extension."""
    ext = os.path.splitext(filename or '')[1].lstrip('.').lower()
    return ext in ALLOWED_IMAGE_EXTENSIONS


def analyze_imagery(filepath):
    """Analyze an image file and return spectral climate proxies.

    Returns a dict with image metadata + derived indicators:
      brightness, land_surface_temp (C estimate), cloud_cover (% of near-white
      pixels), vegetation_index (green/red ratio scaled 0-100),
      water_cover (% blue-dominant pixels), snow_cover (% bright neutral
      pixels), albedo (reflectance estimate %) and per-channel means.
    Raises ValueError when the file is not a readable image.
    """
    from PIL import Image

    try:
        img = Image.open(filepath)
        img.load()
    except Exception:
        raise ValueError('The uploaded file is not a readable image.')

    width, height = img.size
    if width * height > MAX_IMAGE_PIXELS:
        raise ValueError('Image too large (max 4096x4096 pixels).')

    fmt = (img.format or 'UNKNOWN').upper()
    original_mode = img.mode
    rgb = img.convert('RGB')
    arr = np.asarray(rgb, dtype=np.float32)
    r, g, b = arr[..., 0], arr[..., 1], arr[..., 2]
    total = float(r.size)

    # Luminance (ITU-R BT.601)
    brightness = 0.299 * r + 0.587 * g + 0.114 * b
    mean_brightness = float(brightness.mean())

    # Cloud cover proxy: fraction of near-white pixels
    cloud_cover = float((brightness > 230).sum()) / total * 100.0

    # Snow/ice proxy: very bright and spectrally neutral pixels
    channel_spread = np.maximum(np.maximum(r, g), b) - np.minimum(np.minimum(r, g), b)
    snow_cover = float(((brightness > 220) & (channel_spread < 25)).sum()) / total * 100.0

    # Vegetation proxy: green dominance over red (NDVI-like, scaled to 0-100)
    denom = g + r
    ndvi_like = np.where(denom > 0, (g - r) / denom, 0.0)
    vegetation_index = float(np.clip(ndvi_like.mean() * 100.0 + 50.0, 0.0, 100.0))

    # Water proxy: blue clearly dominant over red and green
    water_cover = float(((b > r + 15) & (b > g + 10)).sum()) / total * 100.0

    # Land surface temperature estimate: scale mean brightness to -10..45 C
    land_surface_temp = -10.0 + (mean_brightness / 255.0) * 55.0

    # Albedo estimate: mean reflectance of visible bands
    albedo = mean_brightness / 255.0 * 100.0

    return {
        'format': fmt,
        'original_mode': original_mode,
        'width': int(width),
        'height': int(height),
        'megapixels': round(width * height / 1_000_000.0, 2),
        'brightness': round(mean_brightness, 1),
        'land_surface_temp': round(land_surface_temp, 1),
        'cloud_cover': round(cloud_cover, 1),
        'snow_cover': round(snow_cover, 1),
        'vegetation_index': round(vegetation_index, 1),
        'water_cover': round(water_cover, 1),
        'albedo': round(albedo, 1),
        'channel_means': {
            'red': round(float(r.mean()), 1),
            'green': round(float(g.mean()), 1),
            'blue': round(float(b.mean()), 1),
        },
    }
