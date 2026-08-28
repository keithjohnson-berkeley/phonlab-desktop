from abc import ABC, abstractmethod
from collections.abc import Generator


class UseCase[T](ABC):
    @abstractmethod
    def invoke(self) -> Generator[T, None, None]:
        pass

    @abstractmethod
    def stop(self) -> None:
        pass
