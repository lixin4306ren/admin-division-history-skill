#!/usr/bin/env python3
"""从阿里云 DataV 拉今日行政区划边界，存进配置同级的 bounds/。

用法：
    python3 fetch_bounds.py 610700 610900 420300      # 地市 → 下辖各县
    python3 fetch_bounds.py --prov                    # 全国省界（画省界虚线用）
    python3 fetch_bounds.py --dir /path/to/bounds 610700

地市代码用 `_full` 后缀取到下辖县级面；省直辖的特殊单元（如神农架 429021）
没有下级，用不带 `_full` 的接口。脚本会自动回退。

DataV 每个 feature 的 properties.center 是民政部口径的政府驻地经纬度，
比 centroid 可靠——渲染时的城市点位一律取它，不要手填坐标。
"""
import json
import os
import sys
import urllib.request

BASE = "https://geo.datav.aliyun.com/areas_v3/bound/"


def grab(code, out_dir):
    for suffix in ("_full", ""):
        url = f"{BASE}{code}{suffix}.json"
        try:
            with urllib.request.urlopen(url, timeout=30) as r:
                data = json.loads(r.read().decode("utf-8"))
        except Exception:
            continue
        if not data.get("features"):
            continue
        path = os.path.join(out_dir, f"{code}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        names = [x["properties"]["name"] for x in data["features"]]
        print(f"{code}  {len(names):>3} 个  {'、'.join(names[:12])}"
              f"{' …' if len(names) > 12 else ''}")
        return True
    print(f"{code}  抓取失败", file=sys.stderr)
    return False


if __name__ == "__main__":
    args = sys.argv[1:]
    out_dir = "bounds"
    if "--dir" in args:
        i = args.index("--dir")
        out_dir = args[i + 1]
        args = args[:i] + args[i + 2:]
    os.makedirs(out_dir, exist_ok=True)
    if "--prov" in args:
        args = [a for a in args if a != "--prov"]
        url = f"{BASE}100000_full.json"
        with urllib.request.urlopen(url, timeout=30) as r:
            data = json.loads(r.read().decode("utf-8"))
        with open(os.path.join(out_dir, "prov.json"), "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        print(f"prov  {len(data['features'])} 个省级单元")
    for code in args:
        grab(code, out_dir)
