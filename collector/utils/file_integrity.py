"""File integrity checking utilities for debugging container staleness issues."""

import hashlib
import os
import logging
from pathlib import Path
from datetime import datetime
from typing import Dict, Tuple, List, Optional

LOG = logging.getLogger(__name__)


def calculate_file_checksum(file_path: Path) -> str:
    """Calculate MD5 checksum of a file."""
    hash_md5 = hashlib.md5()
    try:
        with open(file_path, 'rb') as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hash_md5.update(chunk)
        return hash_md5.hexdigest()
    except (IOError, OSError) as e:
        LOG.warning(f"Could not read file {file_path}: {e}")
        return "ERROR"


def get_file_info(file_path: Path) -> Tuple[str, datetime, int]:
    """Get file checksum, modification time, and size."""
    try:
        stat_info = file_path.stat()
        checksum = calculate_file_checksum(file_path)
        mod_time = datetime.fromtimestamp(stat_info.st_mtime)
        size = stat_info.st_size
        return checksum, mod_time, size
    except (IOError, OSError) as e:
        LOG.warning(f"Could not stat file {file_path}: {e}")
        return "ERROR", datetime.min, 0


def scan_collector_files(collector_root: Path) -> Dict[str, Tuple[str, datetime, int]]:
    """Scan all Python files in collector directory and return file info."""
    file_info = {}

    # Include key file patterns
    patterns = ['*.py', '*.yaml', '*.yml', '*.json', '*.txt', '*.md']

    for pattern in patterns:
        for file_path in collector_root.rglob(pattern):
            # Skip hidden files, __pycache__, .git, etc.
            if any(part.startswith('.') or part == '__pycache__' for part in file_path.parts):
                continue

            # Get relative path for cleaner logging
            try:
                rel_path = file_path.relative_to(collector_root)
                checksum, mod_time, size = get_file_info(file_path)
                file_info[str(rel_path)] = (checksum, mod_time, size)
            except ValueError:
                # File is not relative to collector_root, skip
                continue

    return file_info


def log_file_integrity_info(collector_root: Optional[Path] = None) -> None:
    """Log file integrity information for debugging container staleness."""
    if collector_root is None:
        # Auto-detect collector root
        current_file = Path(__file__)
        collector_root = current_file.parent.parent  # Go up from utils/ to collector/

    LOG.info("=== File Integrity Check ===")
    LOG.info(f"Scanning files in: {collector_root}")

    file_info = scan_collector_files(collector_root)

    if not file_info:
        LOG.warning("No files found in collector directory!")
        return

    # Sort by modification time (newest first)
    sorted_files = sorted(file_info.items(), key=lambda x: x[1][1], reverse=True)

    LOG.info(f"Found {len(file_info)} files")

    # Log newest file for quick staleness check
    newest_file, (checksum, mod_time, size) = sorted_files[0]
    LOG.info(f"Newest file: {newest_file} (modified: {mod_time}, size: {size}, checksum: {checksum[:8]}...)")

    # Log all files with checksums (debug level)
    LOG.debug("=== Complete File Integrity Report ===")
    for file_path, (checksum, mod_time, size) in sorted_files:
        LOG.debug(f"{file_path:<50} | {mod_time} | {size:>8} bytes | {checksum}")

    # Log summary statistics
    total_size = sum(info[2] for info in file_info.values())
    oldest_file, oldest_info = sorted_files[-1]
    LOG.info(f"Oldest file: {oldest_file} (modified: {oldest_info[1]})")
    LOG.info(f"Total files: {len(file_info)}, Total size: {total_size:,} bytes")
    LOG.info("=== End File Integrity Check ===")


def log_key_file_checksums() -> None:
    """Log checksums of key collector files for quick verification."""
    current_file = Path(__file__)
    collector_root = current_file.parent.parent

    key_files = [
        'writer/influxdb_writer.py',
        'core/collector.py',
        'main.py',
        '__main__.py',
        'enrichment/drive_enrichment.py',
        'enrichment/system_identification_helper.py'
    ]

    LOG.info("=== Key File Checksums ===")
    for file_rel_path in key_files:
        file_path = collector_root / file_rel_path
        if file_path.exists():
            checksum, mod_time, size = get_file_info(file_path)
            LOG.info(f"{file_rel_path:<40} | {mod_time} | {checksum[:12]}...")
        else:
            LOG.warning(f"{file_rel_path:<40} | NOT FOUND")
    LOG.info("=== End Key File Checksums ===")