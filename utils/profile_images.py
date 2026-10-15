"""Persistent storage helpers for user profile images."""

import re
import secrets
from datetime import datetime

from utils.database import get_collection

ALLOWED_IMAGE_EXTENSIONS = {
    'png': 'image/png',
    'jpg': 'image/jpeg',
    'jpeg': 'image/jpeg',
    'gif': 'image/gif',
    'webp': 'image/webp',
    'bmp': 'image/bmp',
}
MAX_PROFILE_IMAGE_SIZE = 2 * 1024 * 1024
_PROFILE_FILENAME = re.compile(
    r'(?P<image_type>avatar|banner)_(?P<user_id>\d+)(?:_[a-f0-9]{16})?'
    r'\.(?P<extension>png|jpe?g|gif|webp|bmp)\Z',
    re.IGNORECASE,
)


def save_profile_image(upload, image_type, user_id):
    """Persist a validated profile image in MongoDB and return its legacy URL path."""
    if not upload or not upload.filename:
        return None
    if image_type not in ('avatar', 'banner'):
        raise ValueError('Invalid profile image type.')

    extension = upload.filename.rsplit('.', 1)[-1].lower() if '.' in upload.filename else ''
    content_type = ALLOWED_IMAGE_EXTENSIONS.get(extension)
    if not content_type:
        raise ValueError('Unsupported image format. Allowed: PNG, JPG, JPEG, GIF, WEBP, BMP.')

    image_data = upload.stream.read(MAX_PROFILE_IMAGE_SIZE + 1)
    if len(image_data) > MAX_PROFILE_IMAGE_SIZE:
        raise ValueError('Profile images must be 2 MB or smaller.')
    if not image_data:
        raise ValueError('The selected image is empty.')

    filename = '{}_{}_{}.{}'.format(
        image_type, user_id, secrets.token_hex(8), extension
    )
    get_collection('profile_images').update_one(
        {'user_id': int(user_id), 'image_type': image_type},
        {'$set': {
            'user_id': int(user_id),
            'image_type': image_type,
            'filename': filename,
            'content_type': content_type,
            'data': image_data,
            'updated_at': datetime.utcnow().isoformat(),
        }},
        upsert=True,
    )
    return 'uploads/profiles/' + filename


def get_profile_image(filename):
    """Fetch a stored image by its generated legacy filename."""
    match = _PROFILE_FILENAME.fullmatch(filename or '')
    if not match:
        return None

    record = get_collection('profile_images').find_one({
        'user_id': int(match.group('user_id')),
        'image_type': match.group('image_type').lower(),
        'filename': filename,
    })
    if not record or not record.get('data'):
        return None
    return bytes(record['data']), record['content_type']
