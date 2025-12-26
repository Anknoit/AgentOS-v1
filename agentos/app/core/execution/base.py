from abc import ABC, abstractmethod
from app.core.ontology.decision import Decision


class ExecutionAdapter(ABC):
    @abstractmethod
    def execute(self, decision: Decision) -> dict:
        """
        Executes an action based on decision.
        Must return execution result metadata.
        """
        pass
