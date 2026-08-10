from io import BytesIO
from pathlib import Path

import pandas as pd

from app.core.errors import AppError

SUPPORTED_EXTENSIONS = {".csv", ".xlsx", ".xls"}


def validate_upload(filename: str, content: bytes, max_size_mb: int) -> str:
    extension = Path(filename).suffix.lower()
    if extension not in SUPPORTED_EXTENSIONS:
        raise AppError("Only CSV, XLSX, and XLS files are supported.", "UNSUPPORTED_FILE")
    if not content:
        raise AppError("The uploaded file is empty.", "EMPTY_FILE")
    if len(content) > max_size_mb * 1024 * 1024:
        raise AppError(f"File exceeds the {max_size_mb} MB limit.", "FILE_TOO_LARGE", 413)
    return extension


def inspect_sheets(filename: str, content: bytes, max_size_mb: int) -> list[str]:
    extension = validate_upload(filename, content, max_size_mb)
    if extension == ".csv":
        return []
    try:
        with pd.ExcelFile(BytesIO(content)) as workbook:
            return list(workbook.sheet_names)
    except Exception as exc:
        raise AppError("Unable to read this Excel workbook.", "CORRUPT_FILE") from exc


def parse_dataset(
    filename: str,
    content: bytes,
    max_size_mb: int,
    max_rows: int,
    max_columns: int,
    sheet_name: str | None = None,
    header_row: int = 0,
) -> tuple[pd.DataFrame, str, str | None]:
    extension = validate_upload(filename, content, max_size_mb)
    if header_row < 0 or header_row > 100:
        raise AppError("Header row must be between 0 and 100.", "INVALID_HEADER_ROW")
    try:
        if extension == ".csv":
            frame = pd.read_csv(BytesIO(content), header=header_row)
            source_type = "csv"
            selected_sheet = None
        else:
            sheets = inspect_sheets(filename, content, max_size_mb)
            selected_sheet = sheet_name or (sheets[0] if sheets else None)
            if selected_sheet not in sheets:
                raise AppError("The selected worksheet does not exist.", "INVALID_WORKSHEET")
            frame = pd.read_excel(BytesIO(content), sheet_name=selected_sheet, header=header_row)
            source_type = "excel"
    except AppError:
        raise
    except Exception as exc:
        raise AppError("Unable to parse the uploaded file.", "CORRUPT_FILE") from exc
    if frame.empty and len(frame.columns) == 0:
        raise AppError("The uploaded dataset contains no data.", "EMPTY_DATASET")
    if len(frame) > max_rows:
        raise AppError(f"Dataset exceeds the {max_rows:,} row limit.", "TOO_MANY_ROWS", 413)
    if len(frame.columns) > max_columns:
        raise AppError(f"Dataset exceeds the {max_columns} column limit.", "TOO_MANY_COLUMNS", 413)
    frame.columns = [str(column).strip() or f"Column_{index + 1}" for index, column in enumerate(frame.columns)]
    if frame.columns.duplicated().any():
        raise AppError("Column names must be unique.", "DUPLICATE_COLUMNS")
    return frame, source_type, selected_sheet
