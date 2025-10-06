"""
Integration module for the read functionality in the collector.
"""
from .factory import ReaderFactory
from .json_reader import JsonReader
from .cli import add_from_json_args, process_from_json

# Export key components for easier imports
__all__ = [
    'ReaderFactory',
    'JsonReader',
    'add_from_json_args',
    'process_from_json'
]
