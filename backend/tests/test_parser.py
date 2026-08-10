from io import BytesIO

import pandas as pd
import pytest

from app.core.errors import AppError
from app.services.datasets.parser import inspect_sheets, parse_dataset


def test_csv_parsing() -> None:
    frame, source, sheet = parse_dataset("sales.csv", b"Product,Revenue\nA,10\nB,20\n", 1, 100, 10)
    assert source == "csv" and sheet is None
    assert frame["Revenue"].sum() == 30


def test_excel_sheets_and_selection() -> None:
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        pd.DataFrame({"A": [1]}).to_excel(writer, sheet_name="Overview", index=False)
        pd.DataFrame({"B": [2]}).to_excel(writer, sheet_name="Sales", index=False)
    content = output.getvalue()
    assert inspect_sheets("book.xlsx", content, 5) == ["Overview", "Sales"]
    frame, _, sheet = parse_dataset("book.xlsx", content, 5, 100, 10, "Sales")
    assert sheet == "Sales" and list(frame.columns) == ["B"]


@pytest.mark.parametrize("name,content,code", [("bad.pdf", b"x", "UNSUPPORTED_FILE"), ("empty.csv", b"", "EMPTY_FILE")])
def test_invalid_uploads(name: str, content: bytes, code: str) -> None:
    with pytest.raises(AppError) as error:
        parse_dataset(name, content, 1, 100, 10)
    assert error.value.error_code == code


def test_oversized_upload() -> None:
    with pytest.raises(AppError) as error:
        parse_dataset("large.csv", b"x" * 1025, 0, 100, 10)
    assert error.value.error_code == "FILE_TOO_LARGE"
