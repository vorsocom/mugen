"""Provides a base dataclass for vendor specific parameters."""

__all__ = ["VendorParams"]

from dataclasses import dataclass


@dataclass
class VendorParams:
    """A base dataclass for vendor specific parameters."""
