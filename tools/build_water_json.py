#!/usr/bin/env python3
"""
PLATEAU wtr (Water Body) CityGML → water_<area>.json 変換スクリプト

使い方:
    python3 tools/build_water_json.py \
        --wtr-dir "/Users/udon/Desktop/創作/0413_墨田区PLATEAU/13107_sumida-ku_pref_2025_citygml_1_op/udx/wtr" \
        --buildings-json buildings_634635.json \
        --area 634635 \
        --output water_634635.json

各 WaterBody / WaterSurface の lod1MultiSurface ポリゴンを抽出します。
出力フォーマット: { type: 'water', items: [{ fp: [...], a: { class } }, ...] }
"""

import argparse
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _plateau_common import (
    bbox_from_buildings_json, collect_polygons, in_bbox, iter_local,
    localname, parse_xml, polygon_to_xy,
)

# wtr の対象要素 (CityGML 2.0 / 3.0)
WATER_ELEMS = {'WaterBody', 'WaterSurface', 'WaterClosureSurface', 'WaterGroundSurface'}


def extract_water(root, ref_lon, ref_lat, bbox_m, stats):
    out = []
    targets = []
    for el in root.iter():
        if localname(el.tag) in WATER_ELEMS:
            targets.append(el)
    stats['water_elems'] += len(targets)

    for w in targets:
        cls_code = None
        for el in w:
            if localname(el.tag) == 'class' and el.text:
                cls_code = el.text.strip()
                break

        polys = collect_polygons(w)
        if not polys:
            stats['no_geom'] += 1
            continue

        for ext, _holes in polys:
            fp_xy = polygon_to_xy(ext, ref_lon, ref_lat)
            if not any(in_bbox(p, bbox_m) for p in fp_xy):
                stats['out_of_bbox'] += 1
                continue
            attrs = {}
            if cls_code:
                attrs['class'] = cls_code
            out.append({'fp': fp_xy, 'a': attrs})

    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--wtr-dir', required=True)
    ap.add_argument('--buildings-json', required=True)
    ap.add_argument('--area', required=True)
    ap.add_argument('--output', required=True)
    ap.add_argument('--bbox-margin', type=float, default=200.0)
    args = ap.parse_args()

    with open(args.buildings_json) as f:
        bd = json.load(f)
    ref_lat = bd['ref_lat']; ref_lon = bd['ref_lon']
    scale = bd['scale']; range_m = bd['range_m']
    bbox_m = bbox_from_buildings_json(bd, args.bbox_margin)
    print(f"buildings ref: lat={ref_lat}, lon={ref_lon}")
    print(f"bbox (m, local): x[{bbox_m[0]:.0f}, {bbox_m[2]:.0f}] y[{bbox_m[1]:.0f}, {bbox_m[3]:.0f}]")

    files = sorted(glob.glob(os.path.join(args.wtr_dir, '*wtr*.gml'))
                   + glob.glob(os.path.join(args.wtr_dir, '*wtr*.xml')))
    if not files:
        files = sorted(glob.glob(os.path.join(args.wtr_dir, '*.gml')))
    if not files:
        print(f"ERROR: no wtr files found under {args.wtr_dir}", file=sys.stderr)
        sys.exit(1)

    print(f"\nProcessing {len(files)} wtr file(s)...")
    items = []
    stats = {'water_elems': 0, 'no_geom': 0, 'out_of_bbox': 0}
    for fp in files:
        root = parse_xml(fp)
        if root is None:
            continue
        before = len(items)
        items.extend(extract_water(root, ref_lon, ref_lat, bbox_m, stats))
        print(f"  {os.path.basename(fp)}: +{len(items) - before}")

    print(f"\nDiagnostics:")
    print(f"  Water elements found:  {stats['water_elems']}")
    print(f"  No geometry:           {stats['no_geom']}")
    print(f"  Filtered by bbox:      {stats['out_of_bbox']}")
    print(f"  Polygons emitted:      {len(items)}")

    out = {
        'type': 'water',
        'ref_lat': ref_lat, 'ref_lon': ref_lon, 'scale': scale, 'range_m': range_m,
        'items': items,
    }
    with open(args.output, 'w') as f:
        json.dump(out, f, ensure_ascii=False, separators=(',', ':'))
    print(f"\nWrote {len(items):,} water polygons to {args.output}")


if __name__ == '__main__':
    main()
