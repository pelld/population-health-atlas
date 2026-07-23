"""Build practice-level QOF data with registered-population adjustment."""

from __future__ import annotations

import io
import json
import re
import time
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd
import requests

QOF_URLS = [
    "https://files.digital.nhs.uk/7F/AA91AF/qof-2425-prev-ach-pca-cv-prac.xlsx",
    "https://files.digital.nhs.uk/44/D5DE66/qof-2425-prev-ach-pca-resp-prac.xlsx",
    "https://files.digital.nhs.uk/07/723F89/qof-2425-prev-ach-pca-ls-prac.xlsx",
    "https://files.digital.nhs.uk/E4/BA3715/qof-2425-prev-ach-pca-hd-prac.xlsx",
    "https://files.digital.nhs.uk/47/F03F02/qof-2425-prev-ach-pca-neu-prac.xlsx",
    "https://files.digital.nhs.uk/14/E3B1D1/qof-2425-prev-ach-pca-ms-prac.xlsx",
]
AGE_URL = "https://files.digital.nhs.uk/43/1AEFAA/gp-reg-pat-prac-quin-age.zip"
LSOA_URL = "https://files.digital.nhs.uk/7E/26EB57/gp-reg-pat-prac-lsoa-2021-male-female-Apr-25.zip"
MAPPING_URL = "https://files.digital.nhs.uk/E2/1DCD29/gp-reg-pat-prac-map.zip"
IMD_URL = "https://assets.publishing.service.gov.uk/media/691ded56d140bbbaa59a2a7d/File_7_IoD2025_All_Ranks_Scores_Deciles_Population_Denominators.csv"
POSTCODE_URL = "https://api.postcodes.io/postcodes"
OUTPUT = Path("data/practice-data.js")

CONDITION_NAMES = {
    "AF": "Atrial fibrillation", "CHD": "Coronary heart disease", "HF": "Heart failure", "HYP": "Hypertension",
    "PAD": "Peripheral arterial disease", "STIA": "Stroke and TIA", "DM": "Diabetes", "COPD": "COPD",
    "AST": "Asthma", "CAN": "Cancer", "CKD": "Chronic kidney disease", "DEM": "Dementia", "DEP": "Depression",
    "EP": "Epilepsy", "LD": "Learning disabilities", "MH": "Serious mental illness", "OST": "Osteoporosis",
    "RA": "Rheumatoid arthritis", "OB": "Obesity", "PC": "Palliative care", "NDH": "Non-diabetic hyperglycaemia",
}


# ============================================================
# 00. DOWNLOAD AND PARSING HELPERS
# ============================================================
def download(url: str) -> bytes:
    response = requests.get(url, timeout=180)
    response.raise_for_status()
    return response.content


def clean(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value).lower()).strip()


def read_zip_csv(content: bytes, contains: str | None = None, usecols: list[str] | None = None) -> pd.DataFrame:
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        names = [name for name in archive.namelist() if name.lower().endswith(".csv") and (contains is None or contains in name.lower())]
        if not names:
            raise RuntimeError(f"No matching CSV found in ZIP; files were {archive.namelist()}.")
        with archive.open(names[0]) as source:
            return pd.read_csv(source, usecols=usecols, low_memory=False)


def find_header(frame: pd.DataFrame) -> int | None:
    for row_number in range(min(25, len(frame))):
        cells = [clean(value) for value in frame.iloc[row_number].tolist()]
        if any("practice code" in cell for cell in cells) and any("prevalence" in cell for cell in cells):
            return row_number
    return None


def read_qof_sheet(content: bytes, sheet_name: str) -> pd.DataFrame | None:
    raw = pd.read_excel(io.BytesIO(content), sheet_name=sheet_name, header=None)
    header_row = find_header(raw)
    if header_row is None:
        return None
    headers, seen = [], {}
    for index, value in enumerate(raw.iloc[header_row]):
        header = clean(value) or f"column {index}"
        seen[header] = seen.get(header, 0) + 1
        headers.append(header if seen[header] == 1 else f"{header} {seen[header]}")
    table = raw.iloc[header_row + 1:].copy()
    table.columns = headers
    return table.dropna(how="all")


# ============================================================
# 01. QOF RECORDED PREVALENCE
# ============================================================
def extract_qof(contents: list[bytes]) -> pd.DataFrame:
    frames = []
    for content in contents:
        workbook = pd.ExcelFile(io.BytesIO(content))
        for sheet_name in workbook.sheet_names:
            if sheet_name not in CONDITION_NAMES:
                continue
            table = read_qof_sheet(content, sheet_name)
            if table is None:
                continue
            prevalence_columns = [column for column in table.columns if "prevalence" in column and "change" not in column]
            if "practice code" not in table or "practice name" not in table or not prevalence_columns:
                continue
            part = table[["practice code", "practice name", prevalence_columns[-1]]].copy()
            part.columns = ["practice_code", "practice_name", "prevalence"]
            part["condition"] = CONDITION_NAMES[sheet_name]
            frames.append(part)
    data = pd.concat(frames, ignore_index=True)
    data["practice_code"] = data["practice_code"].astype(str).str.strip()
    data["prevalence"] = pd.to_numeric(data["prevalence"], errors="coerce")
    data = data[data["practice_code"].str.match(r"^[A-Z]\d{5}$", na=False) & data["prevalence"].notna()].drop_duplicates(["practice_code", "condition"])
    if data["practice_code"].nunique() < 5_000 or data["condition"].nunique() < 15:
        raise RuntimeError(f"Practice QOF extraction returned only {data['practice_code'].nunique()} practices and {data['condition'].nunique()} conditions.")
    return data


# ============================================================
# 02. REGISTERED POPULATION AGE MIX AND DEPRIVATION
# ============================================================
def extract_age(content: bytes) -> pd.DataFrame:
    columns = ["ORG_TYPE", "ORG_CODE", "POSTCODE", "SEX", "AGE_GROUP_5", "NUMBER_OF_PATIENTS"]
    age = read_zip_csv(content, usecols=columns)
    age = age[age["ORG_TYPE"] == "GP"].copy()
    age["NUMBER_OF_PATIENTS"] = pd.to_numeric(age["NUMBER_OF_PATIENTS"], errors="coerce").fillna(0)
    totals = age[(age["SEX"] == "ALL") & (age["AGE_GROUP_5"] == "ALL")][["ORG_CODE", "POSTCODE", "NUMBER_OF_PATIENTS"]].rename(columns={"ORG_CODE": "practice_code", "POSTCODE": "postcode", "NUMBER_OF_PATIENTS": "list_size"})
    bands = age[(age["SEX"] != "ALL") & (age["AGE_GROUP_5"] != "ALL")].pivot_table(index="ORG_CODE", columns="AGE_GROUP_5", values="NUMBER_OF_PATIENTS", aggfunc="sum", fill_value=0)

    def band_sum(labels: list[str]) -> pd.Series:
        return bands[[label for label in labels if label in bands]].sum(axis=1)

    age_numbers = pd.DataFrame(index=bands.index)
    age_numbers["age_0_44"] = band_sum(["0_4", "5_9", "10_14", "15_19", "20_24", "25_29", "30_34", "35_39", "40_44"])
    age_numbers["age_45_64"] = band_sum(["45_49", "50_54", "55_59", "60_64"])
    age_numbers["age_65_74"] = band_sum(["65_69", "70_74"])
    age_numbers["age_75_plus"] = band_sum(["75_79", "80_84", "85_89", "90_94", "95+"])
    age_numbers.index.name = "practice_code"
    age_numbers = age_numbers.reset_index()
    result = totals.merge(age_numbers, on="practice_code", how="left")
    for column in ["age_0_44", "age_45_64", "age_65_74", "age_75_plus"]:
        result[column] = result[column] / result["list_size"].replace(0, np.nan)
    return result


def extract_patient_weighted_imd(lsoa_content: bytes, imd_content: bytes) -> pd.DataFrame:
    registrations = read_zip_csv(lsoa_content, contains="lsoa-all", usecols=["PRACTICE_CODE", "LSOA_CODE", "NUMBER_OF_PATIENTS"])
    imd = pd.read_csv(io.BytesIO(imd_content), usecols=["LSOA code (2021)", "Index of Multiple Deprivation (IMD) Score"])
    imd.columns = ["LSOA_CODE", "imd_score"]
    registrations["NUMBER_OF_PATIENTS"] = pd.to_numeric(registrations["NUMBER_OF_PATIENTS"], errors="coerce").fillna(0)
    joined = registrations.merge(imd, on="LSOA_CODE", how="left")
    joined["weighted_score"] = joined["NUMBER_OF_PATIENTS"] * joined["imd_score"]
    grouped = joined.groupby("PRACTICE_CODE", as_index=False).agg(mapped_patients=("NUMBER_OF_PATIENTS", lambda values: values[joined.loc[values.index, "imd_score"].notna()].sum()), lsoa_patients=("NUMBER_OF_PATIENTS", "sum"), weighted_score=("weighted_score", "sum"))
    grouped["imd_score"] = grouped["weighted_score"] / grouped["mapped_patients"].replace(0, np.nan)
    grouped["imd_coverage"] = grouped["mapped_patients"] / grouped["lsoa_patients"].replace(0, np.nan)
    return grouped.rename(columns={"PRACTICE_CODE": "practice_code"})[["practice_code", "imd_score", "imd_coverage"]]


def extract_mapping(content: bytes) -> pd.DataFrame:
    columns = ["PRACTICE_CODE", "PRACTICE_NAME", "PRACTICE_POSTCODE", "ONS_ICB_CODE", "ICB_NAME"]
    mapping = read_zip_csv(content, usecols=columns)
    mapping.columns = ["practice_code", "practice_name_map", "postcode_map", "icb_code", "icb_name"]
    mapping["icb_name"] = mapping["icb_name"].str.replace(r"^NHS\s+", "", regex=True).str.replace(r"\s+Integrated Care Board$", "", regex=True)
    return mapping.drop_duplicates("practice_code")


# ============================================================
# 03. POSTCODE LOCATIONS AND ADJUSTMENT MODEL
# ============================================================
def geocode(postcodes: list[str]) -> dict[str, tuple[float, float]]:
    locations = {}
    unique = sorted({str(postcode).strip().upper() for postcode in postcodes if pd.notna(postcode)})
    for start in range(0, len(unique), 100):
        batch = unique[start:start + 100]
        response = requests.post(POSTCODE_URL, json={"postcodes": batch}, timeout=60)
        response.raise_for_status()
        for item in response.json()["result"]:
            result = item["result"]
            if result and result.get("longitude") is not None:
                locations[item["query"]] = (float(result["longitude"]), float(result["latitude"]))
        time.sleep(0.05)
    return locations


def residuals(frame: pd.DataFrame, condition: str) -> pd.Series:
    predictors = ["imd_score", "age_45_64", "age_65_74", "age_75_plus"]
    valid = frame[condition].notna() & frame[predictors].notna().all(axis=1) & (frame["imd_coverage"] >= 0.85)
    result = pd.Series(np.nan, index=frame.index, dtype=float)
    if valid.sum() < 100:
        return result
    design = np.column_stack([np.ones(valid.sum()), frame.loc[valid, predictors].astype(float)])
    coefficients = np.linalg.lstsq(design, frame.loc[valid, condition].astype(float), rcond=None)[0]
    result.loc[valid] = frame.loc[valid, condition] - design @ coefficients
    return result


# ============================================================
# 04. STATIC OUTPUT
# ============================================================
def main() -> None:
    qof = extract_qof([download(url) for url in QOF_URLS])
    age = extract_age(download(AGE_URL))
    deprivation = extract_patient_weighted_imd(download(LSOA_URL), download(IMD_URL))
    mapping = extract_mapping(download(MAPPING_URL))
    wide = qof.pivot(index=["practice_code", "practice_name"], columns="condition", values="prevalence").reset_index()
    wide = wide.merge(age, on="practice_code", how="inner").merge(deprivation, on="practice_code", how="inner").merge(mapping, on="practice_code", how="left")
    conditions = [condition for condition in CONDITION_NAMES.values() if condition in wide and wide[condition].notna().sum() >= 5_000]
    adjusted = pd.DataFrame({condition: residuals(wide, condition) for condition in conditions})
    correlations = adjusted.corr(min_periods=4_500)
    pairs = sorted(({"first": first, "second": second, "correlation": round(float(correlations.loc[first, second]), 3)} for position, first in enumerate(conditions) for second in conditions[position + 1:] if pd.notna(correlations.loc[first, second])), key=lambda item: item["correlation"], reverse=True)[:10]
    locations = geocode(wide["postcode"].fillna(wide["postcode_map"]).tolist())

    practices = {}
    for row_number, row in wide.iterrows():
        postcode = str(row["postcode"] if pd.notna(row["postcode"]) else row["postcode_map"]).strip().upper()
        location = locations.get(postcode)
        if not location:
            continue
        practices[row["practice_code"]] = {
            "name": str(row["practice_name"]).title(), "postcode": postcode, "icb": row["icb_code"], "icbName": row["icb_name"],
            "longitude": round(location[0], 5), "latitude": round(location[1], 5), "listSize": int(row["list_size"]),
            "imdScore": round(float(row["imd_score"]), 2), "imdCoverage": round(float(row["imd_coverage"]) * 100, 1),
            "age75Plus": round(float(row["age_75_plus"]) * 100, 1),
            "prevalence": {condition: round(float(row[condition]), 2) for condition in conditions if pd.notna(row[condition])},
            "adjusted": {condition: round(float(adjusted.loc[row_number, condition]), 2) for condition in conditions if pd.notna(adjusted.loc[row_number, condition])},
        }
    payload = {
        "year": "2024-25", "populationDate": "1 April 2025", "deprivationYear": 2025, "conditions": conditions,
        "method": "Expected prevalence modelled from patient-weighted IMD and registered-population age mix.",
        "pairs": pairs, "practices": practices,
    }
    OUTPUT.parent.mkdir(exist_ok=True)
    OUTPUT.write_text("window.PRACTICE_DATA=" + json.dumps(payload, separators=(",", ":")) + ";\n", encoding="utf-8")
    print(f"Built {len(practices)} geocoded practices, {len(conditions)} conditions; median IMD coverage {wide['imd_coverage'].median():.1%}.")


if __name__ == "__main__":
    main()
