#!/usr/bin/env python3
"""行政区划变迁图渲染引擎。

用法：  python3 render.py ../configs/hanzhong.py [输出.png]

配置文件是一个 .py，暴露名为 CONFIG 的 dict，schema 见 configs/hanzhong.py
与 SKILL.md。引擎只负责画，所有史料判断留在配置里。
"""
import importlib.util
import json
import os
import sys

import geopandas as gpd
import matplotlib
matplotlib.use("Agg")
import matplotlib.patheffects as pe
import matplotlib.pyplot as plt
from matplotlib.font_manager import FontProperties
from matplotlib.lines import Line2D
from matplotlib.patches import Patch, Rectangle
from shapely.ops import unary_union

FP = "/System/Library/Fonts/Hiragino Sans GB.ttc"
BG = "#FBF9F4"
HALO = [pe.withStroke(linewidth=4.2, foreground=BG)]
HALO_S = [pe.withStroke(linewidth=3.4, foreground=BG)]
# 底色阶：某县被列入的断代数，0 = 从未属于 → 与背景同色
HEAT = ["#FBF9F4", "#F3EDE0", "#EBDFC8", "#E2D0AE", "#D8C094", "#CDAF7B",
        "#C09C60", "#B58B4A", "#A87A38"]
BAND = {"gray": "#A9A294", "ochre": "#B3603C", "olive": "#7E9B5A",
        "blue": "#3D6A93", "teal": "#3F7F78", "plum": "#7A4E9E"}

F = {k: FontProperties(fname=FP, size=s) for k, s in
     [("ttl", 30), ("sub", 14), ("leg", 13), ("cty", 11.5), ("now", 10),
      ("ctyb", 14), ("prov", 19), ("cap", 10.5), ("bd", 14), ("bs", 10),
      ("by", 10.5)]}


def load_config(path):
    spec = importlib.util.spec_from_file_location("cfg", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.CONFIG


def load_bounds(codes, cache):
    """读今日县级界。缺失的自动从 DataV 拉取（见 fetch_bounds.py）。"""
    feats = []
    for code in codes:
        p = os.path.join(cache, f"{code}.json")
        if not os.path.exists(p):
            raise SystemExit(
                f"缺边界文件 {p}\n先运行：python3 fetch_bounds.py {' '.join(codes)}")
        feats += json.load(open(p))["features"]
    g = gpd.GeoDataFrame.from_features(feats, crs="EPSG:4326")
    return g[["name", "center", "geometry"]].drop_duplicates("name").set_index("name")


def render(cfg, out):
    cache = cfg.get("bounds_dir") or os.path.join(
        os.path.dirname(os.path.abspath(cfg["__file__"])), "bounds")
    gdf = load_bounds(cfg["bounds_codes"], cache)

    eras = cfg["eras"]
    polys, counts = {}, {n: 0 for n in gdf.index}
    for e in eras:
        missing = [c for c in e["counties"] if c not in gdf.index]
        if missing:
            raise SystemExit(f"{e['name']} 的辖县不在边界数据里: {missing}\n"
                             f"检查县名写法，或把所属地市代码加进 bounds_codes")
        polys[e["name"]] = unary_union(
            [gdf.loc[c, "geometry"] for c in e["counties"]])
        for c in e["counties"]:
            counts[c] += 1

    has_band = bool(cfg.get("band_segments"))
    fh = cfg.get("fig_h", 14.3 if has_band else 11.6)
    fig = plt.figure(figsize=(cfg.get("fig_w", 17.5), fh), dpi=170)
    fig.patch.set_facecolor(BG)
    if has_band:
        ax = fig.add_axes([0.015, 0.228, 0.97, 0.695])
        ax_b = fig.add_axes([0.055, 0.072, 0.90, 0.118])
    else:
        ax = fig.add_axes([0.015, 0.075, 0.97, 0.845])
        ax_b = None

    W, E, S, N = cfg["extent"]
    ax.set_facecolor(BG)
    ax.set_xlim(W, E); ax.set_ylim(S, N); ax.set_axis_off()
    ax.set_aspect(cfg.get("aspect", 1 / 0.84))

    # 底色：被辖次数热力
    for n, row in gdf.iterrows():
        geom = row.geometry
        for g in (geom.geoms if geom.geom_type == "MultiPolygon" else [geom]):
            ax.fill(*g.exterior.xy, color=HEAT[min(counts[n], len(HEAT) - 1)],
                    zorder=1)
    gpd.GeoSeries(gdf.geometry).boundary.plot(ax=ax, color="#FFFFFF", lw=0.9,
                                              zorder=2)

    # 省界
    pv = os.path.join(cache, "prov.json")
    if os.path.exists(pv):
        prov = gpd.GeoDataFrame.from_features(
            json.load(open(pv))["features"], crs="EPSG:4326")
        for g in prov.geometry:
            for p in (g.geoms if g.geom_type == "MultiPolygon" else [g]):
                ax.plot(*p.exterior.xy, color="#9A9384", lw=1.6, zorder=3,
                        dashes=(7, 3))

    # 断代轮廓。lw/zorder/dashes 由配置给出——相邻断代辖境高度重合时，
    # 必须让后者用细虚线叠到上层，否则会被完全吞掉（详见 SKILL.md 陷阱一）
    for e in eras:
        g = polys[e["name"]]
        for p in (g.geoms if g.geom_type == "MultiPolygon" else [g]):
            ax.plot(*p.exterior.xy, color=e["color"], lw=e.get("lw", 3.0),
                    zorder=e.get("z", 6), dashes=e.get("dash", (None, None)),
                    solid_capstyle="round", solid_joinstyle="round")

    # 地名：旧名 + 今名两行
    def ctr(n):
        c = gdf.loc[n, "center"]
        if c:
            return c[0], c[1]
        g = gdf.loc[n].geometry.centroid
        return g.x, g.y

    lh = cfg.get("label_lh", 0.088)

    def two_line(x, y, old, new, dx, dy, font, col, halo, z):
        up = dy > 0
        va = "bottom" if up else "top"
        y_old = y + dy + (lh if (up and new) else 0)
        ax.text(x + dx, y_old, old, ha="center", va=va, fontproperties=font,
                color=col, zorder=z, path_effects=halo, linespacing=1.35)
        if new:
            ax.text(x + dx, y_old - lh if up else y + dy - lh, new,
                    ha="center", va=va, fontproperties=F["now"],
                    color="#8A8271", zorder=z, path_effects=halo)

    if cfg.get("seat"):
        n, old, new, dx, dy = cfg["seat"]
        x, y = ctr(n)
        ax.plot(x, y, "o", ms=13, mfc="#B3261E", mec=BG, mew=2.2, zorder=14)
        two_line(x, y, old, new, dx, dy, F["ctyb"], "#7A1A14", HALO, 15)

    for n, old, new, dx, dy in cfg.get("places", []):
        x, y = ctr(n)
        ax.plot(x, y, "o", ms=6.5, mfc="#4A4438", mec=BG, mew=1.5, zorder=13)
        two_line(x, y, old, new, dx, dy, F["cty"], "#3C372C", HALO_S, 14)

    for x, y, t in cfg.get("province_labels", []):
        ax.text(x, y, t, ha="center", va="center", fontproperties=F["prov"],
                color="#B9AF9A", zorder=4)
    for x, y, t, size, rot in cfg.get("terrain_labels", []):
        ax.text(x, y, t, ha="center", va="center", rotation=rot, color="#A79B84",
                fontproperties=FontProperties(fname=FP, size=size), zorder=4)

    # 图例
    h = [Line2D([], [], color=e["color"], lw=e.get("lw", 3.0) * 0.5 + 1.9,
                dashes=e.get("dash", (None, None)),
                label=f"{e['name']}　{e['sub']}　{e['years']}") for e in eras]
    lg = ax.legend(handles=h, loc=cfg.get("legend_loc", "lower left"),
                   bbox_to_anchor=cfg.get("legend_anchor", (0.007, 0.012)),
                   frameon=True, facecolor="#FFFDF8", edgecolor="#D8D0BE",
                   prop=F["leg"], labelspacing=0.72, borderpad=0.95,
                   handlelength=2.6)
    lg.set_zorder(20)
    ne = len(eras)
    hh = [Patch(fc=HEAT[i], ec="#C6BCA6", lw=0.7, label=f"{i}")
          for i in range(ne + 1)]
    lg2 = ax.legend(handles=hh, loc=cfg.get("heat_loc", "lower right"),
                    bbox_to_anchor=cfg.get("heat_anchor", (0.995, 0.012)),
                    frameon=True, facecolor="#FFFDF8", edgecolor="#D8D0BE",
                    prop=F["leg"], ncol=ne + 1, columnspacing=0.55,
                    handlelength=1.5, handletextpad=0.4,
                    title=f"底色：该县被上述 {ne} 个断代中的几个辖过　（左＝0，右＝{ne}）")
    lg2.get_title().set_fontproperties(F["leg"])
    lg2.set_zorder(20)
    ax.add_artist(lg)

    # ---------- 隶属带 ----------
    if has_band:
        x0a = min(s[0] for s in cfg["band_segments"])
        x1a = max(s[1] for s in cfg["band_segments"])
        pad = (x1a - x0a) * 0.025
        ax_b.set_xlim(x0a - pad, x1a + pad)
        ax_b.set_ylim(0, 1); ax_b.set_axis_off()

        for x0, x1, col, main, sub in cfg["band_segments"]:
            ax_b.add_patch(Rectangle((x0, 0.38), x1 - x0, 0.36,
                                     fc=BAND.get(col, col), ec=BG, lw=1.6,
                                     zorder=2))
            ax_b.text((x0 + x1) / 2, 0.615 if sub else 0.56, main, ha="center",
                      va="center", fontproperties=F["bd"], color="#FFFFFF",
                      zorder=3, linespacing=1.25)
            if sub:
                ax_b.text((x0 + x1) / 2, 0.455, sub, ha="center", va="center",
                          fontproperties=F["bs"], color="#F3EDE0", zorder=3)

        # 上排：主图各断代所处时段，与主图轮廓同色
        for e in eras:
            if not e.get("span"):
                continue
            a, b = e["span"]
            ax_b.add_patch(Rectangle((a, 0.80), b - a, 0.13, fc=e["color"],
                                     ec=BG, lw=1.2, zorder=2))
            if (b - a) / (x1a - x0a) > 0.07:
                ax_b.text((a + b) / 2, 0.865, e["name"].split("·")[-1],
                          ha="center", va="center", fontproperties=F["bs"],
                          color="#FFFFFF", zorder=3)

        # 下排：朝代尺。与政区段刻意不对齐，错位说明一名跨数朝
        for i, (a, b, lab) in enumerate(cfg.get("dynasties", [])):
            ax_b.add_patch(Rectangle((a, 0.20), b - a, 0.155,
                                     fc="#E9E2D3" if i % 2 else "#DCD3BE",
                                     ec=BG, lw=1.0, zorder=2))
            ax_b.text((a + b) / 2, 0.277, lab, ha="center", va="center",
                      fontproperties=F["bs"], color="#5C5646", zorder=3)

        if cfg.get("pivot"):
            yr, note = cfg["pivot"]
            ax_b.plot([yr, yr], [0.16, 0.95], color="#8C1D14", lw=2.4, zorder=5)
            ax_b.text(yr + (x1a - x0a) * 0.006, 0.075, note, ha="left",
                      va="top", fontproperties=F["by"], color="#8C1D14",
                      zorder=5)
        for yr, lab in cfg.get("year_ticks", []):
            ax_b.plot([yr, yr], [0.16, 0.20], color="#8A8271", lw=1.0, zorder=4)
            ax_b.text(yr, 0.075, lab, ha="center", va="top",
                      fontproperties=F["by"], color="#7A7364", zorder=4)

        fig.text(0.055, 0.203, cfg["band_caption"], fontproperties=F["bs"],
                 color="#5A5A52", ha="left", va="bottom")

    fig.text(0.033, 0.978, cfg["title"], fontproperties=F["ttl"],
             color="#23231F", ha="left", va="top")
    fig.text(0.033, 0.944, cfg["subtitle"], fontproperties=F["sub"],
             color="#5A5A52", ha="left", va="top")
    fig.text(0.033, 0.012, "\n".join(cfg["footnotes"]), fontproperties=F["cap"],
             color="#7A7364", ha="left", va="bottom")

    fig.savefig(out, dpi=170, facecolor=BG, bbox_inches="tight", pad_inches=0.28)
    print("saved", out)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    cfg_path = os.path.abspath(sys.argv[1])
    cfg = load_config(cfg_path)
    cfg["__file__"] = cfg_path
    default = os.path.join(os.path.dirname(cfg_path),
                           f"{cfg.get('slug', 'map')}.png")
    render(cfg, sys.argv[2] if len(sys.argv) > 2 else default)
