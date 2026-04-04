"""Photo compression and Supabase Storage upload utilities."""
import io
import os
import uuid
import logging
from datetime import datetime

from PIL import Image
import requests

logger = logging.getLogger(__name__)

# Compression settings
MAX_WIDTH = 1200
JPEG_QUALITY = 65
MAX_FILE_SIZE = 5 * 1024 * 1024  # 5MB max upload


def compress_photo(file_data, max_width=MAX_WIDTH, quality=JPEG_QUALITY):
    """Compress a photo to JPEG with max width, return bytes."""
    img = Image.open(io.BytesIO(file_data))

    # Convert to RGB if needed (handles PNG with alpha, etc)
    if img.mode in ('RGBA', 'P', 'LA'):
        img = img.convert('RGB')

    # Resize if wider than max
    w, h = img.size
    if w > max_width:
        ratio = max_width / w
        new_size = (max_width, int(h * ratio))
        img = img.resize(new_size, Image.LANCZOS)

    # Compress to JPEG
    buf = io.BytesIO()
    img.save(buf, format='JPEG', quality=quality, optimize=True)
    buf.seek(0)

    original_kb = len(file_data) / 1024
    compressed_kb = buf.getbuffer().nbytes / 1024
    logger.info(f"Photo compressed: {original_kb:.0f}KB → {compressed_kb:.0f}KB ({img.size[0]}x{img.size[1]})")

    return buf.read(), img.size


def upload_to_supabase_storage(file_bytes, filename, bucket='cmms-photos'):
    """Upload file to Supabase Storage and return public URL."""
    supabase_url = os.getenv('SUPABASE_URL')
    supabase_key = os.getenv('SUPABASE_SERVICE_KEY') or os.getenv('SUPABASE_ANON_KEY')

    if not supabase_url or not supabase_key:
        raise ValueError("SUPABASE_URL y SUPABASE_SERVICE_KEY son necesarios para subir fotos.")

    # Generate unique filename
    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else 'jpg'
    unique_name = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}.{ext}"
    storage_path = f"photos/{unique_name}"

    # Upload via REST API
    upload_url = f"{supabase_url}/storage/v1/object/{bucket}/{storage_path}"
    headers = {
        'Authorization': f'Bearer {supabase_key}',
        'Content-Type': 'image/jpeg',
    }

    resp = requests.post(upload_url, headers=headers, data=file_bytes)
    if resp.status_code not in (200, 201):
        raise Exception(f"Supabase Storage error: {resp.status_code} {resp.text}")

    # Build public URL
    public_url = f"{supabase_url}/storage/v1/object/public/{bucket}/{storage_path}"
    logger.info(f"Photo uploaded: {public_url}")
    return public_url
