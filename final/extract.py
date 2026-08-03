import pdfplumber
import pandas as pd
import re
import os

pdf_file = "World-Boxing-Ranking-2026-July.pdf"

# -------------------------
# Extract date from filename
# -------------------------
filename = os.path.basename(pdf_file)
date_match = re.search(r'(\d{4}-[A-Za-z]+)', filename)

if date_match:
    ranking_date = date_match.group(1)
else:
    ranking_date = ""

rows = []

pattern = re.compile(
    r'^(\d+)\s+([x\d]+)\s+(.+?)\s+([A-Z]{3})\s+'
    r'([0-9.]+)\s+([0-9.]+)\s+([0-9.]+)$'
)

with pdfplumber.open(pdf_file) as pdf:

    current_category = None

    for page in pdf.pages:

        text = page.extract_text()

        if not text:
            continue

        lines = text.split("\n")

        for line in lines:

            line = line.strip()

            if not line:
                continue

            # Category (Women's 48KG, Men's 50KG, ...)
            if "RANKINGS" in line and ("MEN'S" in line or "WOMEN'S" in line):
                current_category = line
                continue

            # Skip headers
            if (
                line.startswith("#")
                or line.startswith("Prev")
                or "Athletes Name" in line
                or "2024 Points" in line
                or "2025 Points" in line
                or "Total Points" in line
                or "After Reduction" in line
            ):
                continue

            m = pattern.match(line)

            if m:
                rows.append({
                    "Date": ranking_date,
                    "Category": current_category,
                    "Rank": int(m.group(1)),
                    "Previous Rank": m.group(2),
                    "Athlete": m.group(3),
                    "NF": m.group(4),
                    "2024 Points": float(m.group(5)),
                    "2025 Points": float(m.group(6)),
                    "Total Points": float(m.group(7)),
                })

df = pd.DataFrame(rows)

df.to_csv("World_Boxing_Rankings.csv", index=False)

print(df.head())
print(f"\nTotal athletes: {len(df)}")
