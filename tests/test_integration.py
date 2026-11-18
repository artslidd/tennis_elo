"""Cross-component regression tests for the installed CLI's validation boundary."""

import csv
import io
import subprocess
import sys

import pytest

CSV_HEADER = (
    "match_id",
    "season_year",
    "date_timestamp",
    "tour_type_human",
    "status",
    "status_extra",
    "home_id",
    "away_id",
    "home_name",
    "away_name",
    "winner_code",
)
GOOD_ROW = [
    "m1",
    "2026",
    "1767320100",
    "ATP Tour",
    "FINISHED",
    "FINISHED",
    "p1",
    "p2",
    "Alpha",
    "Beta",
    "1",
]


def csv_bytes(row):
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer)
    writer.writerow(CSV_HEADER)
    writer.writerow(row)
    return buffer.getvalue().encode()


def malformed_payload(kind):
    if kind == "too_few_fields":
        return csv_bytes(GOOD_ROW[:-1])
    if kind == "too_many_fields":
        return csv_bytes([*GOOD_ROW, "unexpected"])
    if kind == "oversized_field":
        row = list(GOOD_ROW)
        row[8] = "X" * 140000
        return csv_bytes(row)
    if kind == "unterminated_quote":
        header = ",".join(CSV_HEADER)
        return (header + '\nm1,2026,1767320100,ATP Tour,FINISHED,FINISHED,p1,p2,"Alpha\n').encode()
    if kind == "invalid_utf8":
        return csv_bytes(GOOD_ROW).replace(b"Alpha", b"\xffAlpha")
    raise AssertionError(f"unknown test case: {kind}")


@pytest.mark.parametrize(
    "kind",
    ["too_few_fields", "too_many_fields", "oversized_field", "unterminated_quote", "invalid_utf8"],
)
def test_cli_rejects_structural_csv_errors_without_traceback(tmp_path, kind):
    path = tmp_path / "2026-atp-season.csv"
    path.write_bytes(malformed_payload(kind))
    output = tmp_path / "output"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "tennis_elo",
            "rank",
            "--seasons",
            "2026",
            "--input-dir",
            str(tmp_path),
            "--output-dir",
            str(output),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2, result.stdout + result.stderr
    assert "Traceback" not in result.stderr
    assert str(path) in result.stderr
    assert not output.exists()
