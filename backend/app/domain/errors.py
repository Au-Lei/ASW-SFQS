"""Stable domain errors; HTTP translation belongs to the calling service."""


class DomainError(ValueError):
    def __init__(self, code: str, *, field_paths=(), issue_codes=()):
        self.code = code
        self.field_paths = tuple(field_paths)
        self.issue_codes = tuple(issue_codes)
        super().__init__(code)
