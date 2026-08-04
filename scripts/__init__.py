"""
video-extractor scripts package.

Public API:
    from scripts import process_url, detect_platform
    result = process_url(url, out_dir)
"""
from .extractor import process_url, detect_platform

__all__ = ["process_url", "detect_platform"]
