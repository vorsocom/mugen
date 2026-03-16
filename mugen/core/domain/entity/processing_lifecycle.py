"""Domain entity for processing lifecycle state."""

from dataclasses import dataclass


@dataclass(slots=True, frozen=True)
class ProcessingLifecycleEntity:
    """Captures processing lifecycle state for one queued job."""

    job_id: str
    conversation_id: str
    sender: str

    @classmethod
    def build(
        cls,
        *,
        job_id: str,
        conversation_id: str,
        sender: str,
    ) -> "ProcessingLifecycleEntity":
        for field_name, raw_value in {
            "job_id": job_id,
            "conversation_id": conversation_id,
            "sender": sender,
        }.items():
            if not isinstance(raw_value, str) or raw_value.strip() == "":
                raise ValueError(f"{field_name} must be a non-empty string")

        return cls(
            job_id=job_id.strip(),
            conversation_id=conversation_id.strip(),
            sender=sender.strip(),
        )
