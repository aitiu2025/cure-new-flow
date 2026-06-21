"""
County Recorder Adapters for CURE Multi-County Support.

This package contains platform-specific adapters:
- RecorderWorksAdapter: For counties using RecorderWorks platform
- TylerAdapter: For counties using Tyler Technologies platform
"""

from .recorderworks_adapter import RecorderWorksAdapter
from .tyler_adapter import TylerAdapter

__all__ = ["RecorderWorksAdapter", "TylerAdapter"]
