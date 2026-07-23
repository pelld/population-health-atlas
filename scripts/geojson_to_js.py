"""Convert the official ONS GeoJSON regions into lightweight SVG paths."""

import json
import math
from pathlib import Path

SOURCE = Path("regions.geojson")
OUTPUT = Path("regions.js")
BASE = {"North East": (11.2, 0.8), "North West": (10.8, 1.2), "Yorkshire and The Humber": (9.9, 0.7), "East Midlands": (8.7, -0.1), "West Midlands": (10.2, 0.9), "East of England": (7.4, -0.7), "London": (8.1, 0.2), "South East": (6.3, -1.1), "South West": (6.7, -0.8)}


def distance(point, start, end):
    """Perpendicular distance from a point to a line segment."""
    x, y = point
    x1, y1 = start
    x2, y2 = end
    if start == end:
        return math.hypot(x - x1, y - y1)
    t = max(0, min(1, ((x - x1) * (x2 - x1) + (y - y1) * (y2 - y1)) / ((x2 - x1) ** 2 + (y2 - y1) ** 2)))
    return math.hypot(x - (x1 + t * (x2 - x1)), y - (y1 + t * (y2 - y1)))


def simplify(points, tolerance=0.008):
    """Douglas–Peucker simplification, retaining the genuine boundary shape."""
    if len(points) <= 3:
        return points
    index, maximum = 0, 0
    for i in range(1, len(points) - 1):
        current = distance(points[i], points[0], points[-1])
        if current > maximum:
            index, maximum = i, current
    if maximum > tolerance:
        return simplify(points[: index + 1], tolerance)[:-1] + simplify(points[index:], tolerance)
    return [points[0], points[-1]]


data = json.loads(SOURCE.read_text(encoding="utf-8"))
all_points = [point for feature in data["features"] for polygon in ([feature["geometry"]["coordinates"]] if feature["geometry"]["type"] == "Polygon" else feature["geometry"]["coordinates"]) for ring in polygon for point in ring]
min_lon, max_lon = min(point[0] for point in all_points), max(point[0] for point in all_points)
min_lat, max_lat = min(point[1] for point in all_points), max(point[1] for point in all_points)
scale = min(430 / ((max_lon - min_lon) * math.cos(math.radians(53))), 560 / (max_lat - min_lat))


def project(point):
    """Project longitude/latitude to the dashboard's SVG coordinate space."""
    x = 35 + (point[0] - min_lon) * math.cos(math.radians(53)) * scale
    y = 25 + (max_lat - point[1]) * scale
    return round(x, 1), round(y, 1)


regions = []
for feature in data["features"]:
    name = feature["properties"]["RGN24NM"]
    polygons = [feature["geometry"]["coordinates"]] if feature["geometry"]["type"] == "Polygon" else feature["geometry"]["coordinates"]
    path_parts = []
    for polygon in polygons:
        for ring in polygon:
            points = [project(point) for point in simplify(ring)]
            if len(points) >= 3:
                path_parts.append("M" + "L".join(f"{x},{y}" for x, y in points) + "Z")
    base, imd = BASE[name]
    regions.append({"id": feature["properties"]["RGN24CD"], "name": name, "path": "".join(path_parts), "base": base, "imd": imd})

OUTPUT.write_text("// Generated from ONS Regions (December 2024) Boundaries EN BSC.\nconst regions = " + json.dumps(regions, separators=(",", ":")) + ";\n", encoding="utf-8")
