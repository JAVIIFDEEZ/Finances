"""Modules of the platform, one per block of the master, and their registry.

Importing this package registers every module in :data:`~investinglab.modules.registry.REGISTRY`.
"""

from investinglab.modules import b1_toolkit
from investinglab.modules.registry import REGISTRY, ModuleInfo, Requirement, RequirementStatus

__all__ = ["REGISTRY", "ModuleInfo", "Requirement", "RequirementStatus", "b1_toolkit"]
