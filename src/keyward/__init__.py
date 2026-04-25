"""Local secret broker that keeps API keys out of files AI agents can read."""

__version__ = "0.0.1"

from keyward.inject import ActivateResult, DaemonNotRunning, activate

__all__ = ["ActivateResult", "DaemonNotRunning", "__version__", "activate"]
