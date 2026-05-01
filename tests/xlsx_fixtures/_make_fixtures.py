"""Generate Excel test fixtures for submission_check.py."""
from pathlib import Path
from openpyxl import Workbook

FIX_DIR = Path(__file__).parent


def write_xlsx(name: str, headers: list, rows: list) -> Path:
    wb = Workbook()
    ws = wb.active
    ws.append(headers)
    for r in rows:
        ws.append(r)
    out = FIX_DIR / name
    wb.save(out)
    return out


# 1) Perfect match (mirrors example_perfect-team.csv)
write_xlsx(
    "01_perfect-team.xlsx",
    ["artifact_category", "artifact_class", "start_time", "end_time"],
    [
        ["micro_event",       "ver_eyem",   1.25, 1.60],
        ["medium_task_block", "swallow",    8.20, 10.10],
        ["long_task_block",   "chew",      18.00, 27.50],
        ["macroscopic_state", "close_base",40.00, 105.00],
    ],
)

# 2) Mixed results (mirrors example_mixed-team.csv)
write_xlsx(
    "02_mixed-team.xlsx",
    ["artifact_category", "artifact_class", "start_time", "end_time"],
    [
        ["micro_event",       "ver_eyem", 1.30, 1.70],
        ["medium_task_block", "tongue",   8.30, 10.00],
        ["long_task_block",   "chew",    22.00, 31.00],
        ["macroscopic_state", "open_base",41.00, 106.50],
    ],
)

# 3) Non-numeric times (one row has start_time = "abc")
write_xlsx(
    "03_non-numeric-times.xlsx",
    ["artifact_category", "artifact_class", "start_time", "end_time"],
    [
        ["micro_event",       "ver_eyem",   "abc", 1.60],   # bad start_time
        ["medium_task_block", "swallow",    8.20, 10.10],
        ["long_task_block",   "chew",      18.00, 27.50],
        ["macroscopic_state", "close_base",40.00, 105.00],
    ],
)

# 4) Missing required column (no artifact_class)
write_xlsx(
    "04_missing-column.xlsx",
    ["artifact_category", "start_time", "end_time"],
    [
        ["micro_event",        1.25, 1.60],
        ["medium_task_block",  8.20, 10.10],
        ["long_task_block",   18.00, 27.50],
        ["macroscopic_state", 40.00, 105.00],
    ],
)

# 5) Whitespace in headers (leading/trailing spaces)
write_xlsx(
    "05_whitespace-headers.xlsx",
    [" artifact_category ", " artifact_class ", " start_time ", " end_time "],
    [
        ["micro_event",       "ver_eyem",   1.25, 1.60],
        ["medium_task_block", "swallow",    8.20, 10.10],
        ["long_task_block",   "chew",      18.00, 27.50],
        ["macroscopic_state", "close_base",40.00, 105.00],
    ],
)

# 6) None / empty cells in start_time / end_time on one row
write_xlsx(
    "06_none-empty-cells.xlsx",
    ["artifact_category", "artifact_class", "start_time", "end_time"],
    [
        ["micro_event",       "ver_eyem",   None, None],     # blank time cells
        ["medium_task_block", "swallow",    8.20, 10.10],
        ["long_task_block",   "chew",      18.00, 27.50],
        ["macroscopic_state", "close_base",40.00, 105.00],
    ],
)

# 7) Unsupported extension — write a plain .txt file with CSV-ish content
txt_path = FIX_DIR / "07_unsupported.txt"
txt_path.write_text(
    "artifact_category,artifact_class,start_time,end_time\n"
    "micro_event,ver_eyem,1.25,1.60\n",
    encoding="utf-8",
)

print("Fixtures written:")
for p in sorted(FIX_DIR.iterdir()):
    if p.name.startswith("_"):
        continue
    print(f"  {p.name}")
