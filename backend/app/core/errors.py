class AppError(Exception):
    def __init__(self, message: str, error_code: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.error_code = error_code
        self.status_code = status_code


class DatasetNotFoundError(AppError):
    def __init__(self) -> None:
        super().__init__("Dataset not found.", "DATASET_NOT_FOUND", 404)
