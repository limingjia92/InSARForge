"""Runtime version lookup from installed package metadata."""

from importlib.metadata import PackageNotFoundError, version


try:
    __version__ = version("insarforge")
except PackageNotFoundError:
    __version__ = "0+unknown"
