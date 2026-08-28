from dataclasses import dataclass


@dataclass
class LoadProgressState:
    is_loading: bool = False
