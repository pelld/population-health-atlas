"""Build the static Population Health Atlas datasets from official sources."""

from __future__ import annotations

import io
import json
import math
import re
from pathlib import Path

import numpy as np
import pandas as pd
import requests

QOF_URL = "https://files.digital.nhs.uk/2D/50DE48/qof-2425-icb-ach-prev-pca.xlsx"
IMD_URL = "https://assets.publishing.service.gov.uk/media/68ff7ed00f801e57b5bef928/File_13_-_IoD2025_Integrated_Care_Board__ICB__Summaries.xlsx"
BOUNDARY_URL = "https://services1.arcgis.com/ESMARspQHYMw9BZ9/arcgis/rest/services/Integrated_Care_Boards_April_2023_EN_BSC/FeatureServer/0/query"
OUTPUT = Path("data")


# ============================================================
# 00. GENERAL HELPERS
# ============================================================
def download(url: str) -> bytes:
    response = requests.get(url, timeout=120)
    response.raise_for_status()
    return response.content


def clean(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value).lower()).strip()


def find_header(frame: pd.DataFrame, required_words: tuple[str, ...]) -> int | None:
    for row_number in range(min(30, len(frame))):
        row = " | ".join(clean(value) for value in frame.iloc[row_number].tolist())
        if all(word in row for word in required_words):
            return row_number
    return None


def read_tables(content: bytes, required_words: tuple[str, ...]) -> list[tuple[str, pd.DataFrame]]:
    raw_sheets = pd.read_excel(io.BytesIO(content), sheet_name=None, header=None)
    tables = []
    for sheet_name, frame in raw_sheets.items():
        header_row = find_header(frame, required_words)
        if header_row is None:
            continue
        table = frame.iloc[header_row + 1 :].copy()
        headers, seen = [], {}
        for index, value in enumerate(frame.iloc[header_row]):
            header = clean(value) or f"column {index}"
            seen[header] = seen.get(header, 0) + 1
            headers.append(header if seen[header] == 1 else f"{header} {seen[header]}")
        table.columns = headers
        table = table.dropna(how="all")
        tables.append((sheet_name, table))
    return tables


def workbook_preview(content: bytes) -> str:
    """Return a compact structural preview when a publisher changes a workbook."""
    sheets = pd.read_excel(io.BytesIO(content), sheet_name=None, header=None)
    previews = []
    for name, frame in sheets.items():
        sample = frame.iloc[:15, :15].fillna("").astype(str)
        previews.append(f"\nSHEET: {name}\n{sample.to_csv(index=False, header=False)}")
    return "".join(previews)


def choose_column(columns: list[str], include: tuple[str, ...], exclude: tuple[str, ...] = ()) -> str | None:
    candidates = [column for column in columns if all(word in column for word in include) and not any(word in column for word in exclude)]
    return min(candidates, key=len) if candidates else None


def weighted_regression_residual(y: pd.Series, x: pd.Series) -> pd.Series:
    valid = y.notna() & x.notna()
    result = pd.Series(np.nan, index=y.index, dtype=float)
    if valid.sum() < 3 or x[valid].nunique() < 2:
        return result
    design = np.column_stack([np.ones(valid.sum()), x[valid].astype(float)])
    coefficients = np.linalg.lstsq(design, y[valid].astype(float), rcond=None)[0]
    result.loc[valid] = y[valid] - design @ coefficients
    return result


# ============================================================
# 01. QOF PREVALENCE
# ============================================================
def extract_qof(content: bytes) -> pd.DataFrame:
    condition_names = {"AF": "Atrial fibrillation", "CHD": "Coronary heart disease", "HF": "Heart failure", "HYP": "Hypertension", "PAD": "Peripheral arterial disease", "STIA": "Stroke and TIA", "DM": "Diabetes", "COPD": "COPD", "AST": "Asthma", "CAN": "Cancer", "CKD": "Chronic kidney disease", "DEM": "Dementia", "DEP": "Depression", "EP": "Epilepsy", "LD": "Learning disabilities", "MH": "Serious mental illness", "OST": "Osteoporosis", "RA": "Rheumatoid arthritis", "OB": "Obesity", "PC": "Palliative care"}
    candidates = []
    for sheet_name, table in read_tables(content, ("icb", "prevalence")):
        columns = list(table.columns)
        code_col = choose_column(columns, ("icb", "code"))
        name_col = choose_column(columns, ("icb", "name"))
        prevalence_columns = [column for column in columns if "prevalence" in column and "change" not in column and "difference" not in column]
        prevalence_col = prevalence_columns[-1] if prevalence_columns else None
        group_col = choose_column(columns, ("group", "name")) or choose_column(columns, ("disease",)) or choose_column(columns, ("register", "name"))
        if code_col and name_col and prevalence_col:
            part = table[[code_col, name_col, prevalence_col]].copy()
            part.columns = ["icb_code", "icb_name", "prevalence"]
            part["condition"] = table[group_col].astype(str).str.strip() if group_col else condition_names.get(sheet_name, sheet_name)
            candidates.append(part)
    if not candidates:
        raise RuntimeError("Could not identify the QOF prevalence table. Workbook preview:" + workbook_preview(content))
    data = pd.concat(candidates, ignore_index=True)
    data["icb_code"] = data["icb_code"].astype(str).str.strip()
    data["icb_name"] = data["icb_name"].astype(str).str.replace(r"^NHS\s+", "", regex=True).str.replace(r"\s+Integrated Care Board$", "", regex=True).str.strip()
    data["condition"] = data["condition"].astype(str).str.strip()
    data["prevalence"] = pd.to_numeric(data["prevalence"], errors="coerce")
    if data["prevalence"].dropna().median() <= 1:
        data["prevalence"] *= 100
    data = data[data["icb_code"].str.match(r"^Q[A-Z0-9]{2}$", na=False) & data["prevalence"].notna()]
    data = data.drop_duplicates(["icb_code", "condition"], keep="first")
    if data["icb_code"].nunique() < 35 or data["condition"].nunique() < 10:
        raise RuntimeError(f"QOF extraction returned only {data['icb_code'].nunique()} ICBs and {data['condition'].nunique()} conditions.")
    return data


# ============================================================
# 02. ICB DEPRIVATION
# ============================================================
def extract_imd(content: bytes) -> pd.DataFrame:
    for _, table in read_tables(content, ("icb",)):
        columns = list(table.columns)
        code_col = choose_column(columns, ("icb", "code"))
        name_col = choose_column(columns, ("icb", "name"))
        score_col = choose_column(columns, ("average", "score")) or choose_column(columns, ("imd", "score"))
        if code_col and name_col and score_col:
            data = table[[code_col, name_col, score_col]].copy()
            data.columns = ["icb_code", "icb_name_imd", "imd_score"]
            data["icb_code"] = data["icb_code"].astype(str).str.strip()
            data["imd_score"] = pd.to_numeric(data["imd_score"], errors="coerce")
            data = data[data["icb_code"].str.match(r"^Q[A-Z0-9]{2}$", na=False) & data["imd_score"].notna()].drop_duplicates("icb_code")
            if data["icb_code"].nunique() >= 35:
                return data
    raise RuntimeError("Could not identify the ICB deprivation score table. The source workbook structure may have changed.")


# ============================================================
# 03. BOUNDARIES
# ============================================================
def simplify(points: list[list[float]], tolerance: float = 0.008) -> list[list[float]]:
    if len(points) <= 3:
        return points
    start, end = np.array(points[0]), np.array(points[-1])
    line = end - start
    if np.allclose(line, 0):
        distances = np.linalg.norm(np.array(points) - start, axis=1)
    else:
        values = np.array(points)
        t = np.clip(((values - start) @ line) / (line @ line), 0, 1)
        distances = np.linalg.norm(values - (start + np.outer(t, line)), axis=1)
    index = int(np.argmax(distances))
    if distances[index] > tolerance:
        return simplify(points[: index + 1], tolerance)[:-1] + simplify(points[index:], tolerance)
    return [points[0], points[-1]]


def extract_boundaries() -> list[dict]:
    response = requests.get(BOUNDARY_URL, params={"where": "1=1", "outFields": "ICB23CD,ICB23NM", "outSR": 4326, "f": "geojson"}, timeout=120)
    response.raise_for_status()
    features = response.json()["features"]
    all_points = [point for feature in features for polygon in ([feature["geometry"]["coordinates"]] if feature["geometry"]["type"] == "Polygon" else feature["geometry"]["coordinates"]) for ring in polygon for point in ring]
    min_lon, max_lon = min(point[0] for point in all_points), max(point[0] for point in all_points)
    min_lat, max_lat = min(point[1] for point in all_points), max(point[1] for point in all_points)
    scale = min(430 / ((max_lon - min_lon) * math.cos(math.radians(53))), 560 / (max_lat - min_lat))

    def project(point: list[float]) -> tuple[float, float]:
        return round(35 + (point[0] - min_lon) * math.cos(math.radians(53)) * scale, 1), round(25 + (max_lat - point[1]) * scale, 1)

    boundaries = []
    for feature in features:
        polygons = [feature["geometry"]["coordinates"]] if feature["geometry"]["type"] == "Polygon" else feature["geometry"]["coordinates"]
        path_parts = []
        for polygon in polygons:
            for ring in polygon:
                points = [project(point) for point in simplify(ring)]
                if len(points) >= 3:
                    path_parts.append("M" + "L".join(f"{x},{y}" for x, y in points) + "Z")
        boundaries.append({"id": feature["properties"]["ICB23CD"], "name": re.sub(r"\s+Integrated Care Board$", "", feature["properties"]["ICB23NM"]), "path": "".join(path_parts)})
    return boundaries


# ============================================================
# 04. ANALYSIS AND STATIC OUTPUT
# ============================================================
def main() -> None:
    qof = extract_qof(download(QOF_URL))
    imd = extract_imd(download(IMD_URL))
    wide = qof.pivot(index=["icb_code", "icb_name"], columns="condition", values="prevalence").reset_index().merge(imd[["icb_code", "imd_score"]], on="icb_code", how="inner")
    conditions = [condition for condition in wide.columns if condition not in {"icb_code", "icb_name", "imd_score"} and wide[condition].notna().sum() >= 35]
    residuals = pd.DataFrame(index=wide.index)
    for condition in conditions:
        residuals[condition] = weighted_regression_residual(wide[condition], wide["imd_score"])
    correlations = residuals.corr(min_periods=30)
    pairs = sorted(({"first": first, "second": second, "correlation": round(float(correlations.loc[first, second]), 3)} for position, first in enumerate(conditions) for second in conditions[position + 1 :] if pd.notna(correlations.loc[first, second])), key=lambda item: item["correlation"], reverse=True)[:10]
    areas = {}
    for row_number, row in wide.iterrows():
        areas[row["icb_code"]] = {"name": row["icb_name"], "imdScore": round(float(row["imd_score"]), 3), "prevalence": {condition: round(float(row[condition]), 2) for condition in conditions if pd.notna(row[condition])}, "residual": {condition: round(float(residuals.loc[row_number, condition]), 2) for condition in conditions if pd.notna(residuals.loc[row_number, condition])}}
    payload = {"year": "2024-25", "deprivationYear": 2025, "geography": "Integrated Care Boards (April 2023)", "conditions": conditions, "areas": areas, "pairs": pairs}
    OUTPUT.mkdir(exist_ok=True)
    (OUTPUT / "atlas-data.js").write_text("window.ATLAS_DATA=" + json.dumps(payload, separators=(",", ":")) + ";\n", encoding="utf-8")
    (OUTPUT / "icb-boundaries.js").write_text("window.ICB_BOUNDARIES=" + json.dumps(extract_boundaries(), separators=(",", ":")) + ";\n", encoding="utf-8")
    print(f"Built {len(areas)} ICBs, {len(conditions)} conditions and {len(pairs)} ranked pairs.")


if __name__ == "__main__":
    main()
