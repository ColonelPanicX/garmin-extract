"""garmin-extract — automated Garmin Connect data pipeline."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("garmin-extract")
except PackageNotFoundError:
    __version__ = "dev"
