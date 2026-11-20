import os
import logging
import cloudinary
import cloudinary.uploader
import cloudinary.utils
from django.conf import settings
from django.core.files.storage import Storage
from django.utils.deconstruct import deconstructible

logger = logging.getLogger(__name__)


@deconstructible
class VideoCloudinaryStorage(Storage):
    """
    Dedicated Cloudinary Storage backend for video clips.
    Reads credentials from settings.CLOUDINARY_VIDEO_STORAGE or environment variables.
    Falls back gracefully to main CLOUDINARY_STORAGE if video credentials are not yet configured.
    """
    RESOURCE_TYPE = 'video'

    def __init__(self, **kwargs):
        super().__init__()

    def get_credentials(self):
        conf = getattr(settings, 'CLOUDINARY_VIDEO_STORAGE', {})
        cloud_name = conf.get('CLOUD_NAME') or os.environ.get('CLOUDINARY_VIDEO_CLOUD_NAME')
        api_key = conf.get('API_KEY') or os.environ.get('CLOUDINARY_VIDEO_API_KEY')
        api_secret = conf.get('API_SECRET') or os.environ.get('CLOUDINARY_VIDEO_API_SECRET')

        # Fallback to primary CLOUDINARY_STORAGE if video account details are placeholder/empty
        if not cloud_name or 'your_video' in str(cloud_name).lower():
            main_conf = getattr(settings, 'CLOUDINARY_STORAGE', {})
            cloud_name = main_conf.get('CLOUD_NAME')
            api_key = main_conf.get('API_KEY')
            api_secret = main_conf.get('API_SECRET')

        return {
            'cloud_name': str(cloud_name).strip() if cloud_name else None,
            'api_key': str(api_key).strip() if api_key else None,
            'api_secret': str(api_secret).strip() if api_secret else None,
        }

    def _save(self, name, content):
        name = name.replace('\\', '/')
        creds = self.get_credentials()
        options = {
            'resource_type': 'video',
            'use_filename': True,
            'unique_filename': True,
        }
        folder = os.path.dirname(name).strip('/')
        if folder:
            options['folder'] = folder
        else:
            options['folder'] = 'videos'

        if creds.get('cloud_name'):
            options['cloud_name'] = creds['cloud_name']
        if creds.get('api_key'):
            options['api_key'] = creds['api_key']
        if creds.get('api_secret'):
            options['api_secret'] = creds['api_secret']

        try:
            response = cloudinary.uploader.upload_large(content, **options)
        except AttributeError:
            response = cloudinary.uploader.upload(content, **options)

        return response.get('public_id')

    def delete(self, name):
        if not name:
            return False
        creds = self.get_credentials()
        options = {
            'resource_type': 'video',
            'invalidate': True,
        }
        if creds.get('cloud_name'):
            options['cloud_name'] = creds['cloud_name']
        if creds.get('api_key'):
            options['api_key'] = creds['api_key']
        if creds.get('api_secret'):
            options['api_secret'] = creds['api_secret']

        try:
            response = cloudinary.uploader.destroy(name, **options)
            return response.get('result') == 'ok'
        except Exception as exc:
            logger.warning("Error deleting video %s from Cloudinary: %s", name, exc)
            return False

    def url(self, name):
        if not name:
            return ''
        creds = self.get_credentials()
        kwargs = {
            'resource_type': 'video',
            'secure': True,
        }
        if creds.get('cloud_name'):
            kwargs['cloud_name'] = creds['cloud_name']

        url, _ = cloudinary.utils.cloudinary_url(name, **kwargs)
        return url

    def exists(self, name):
        return False

    def get_available_name(self, name, max_length=None):
        if max_length is None:
            return name
        return name[:max_length]


# Convenient shared instance ready for model fields:
video_storage = VideoCloudinaryStorage()
