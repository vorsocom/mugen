"""Provide error types for RGQL handling."""


class RGQLExpandError(Exception):
    """An error type raised during RGQL expansions."""

    status_code: int

    message: str

    def __init__(self, status_code: int, message: str) -> None:
        self.status_code = int(status_code)
        self.message = str(message)
        super().__init__(self.status_code, self.message)
