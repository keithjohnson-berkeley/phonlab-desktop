from collections.abc import Callable
from dataclasses import dataclass

from core.base.use_case import UseCase


@dataclass
class Job:
    use_case: UseCase
    on_success: Callable
    on_error: Callable
