#!/usr/bin/env python3
"""**駅の組ごとの自動車の所要時間を、OpenStreetMap の道路で引く**（ユーザー指示 2026-10-17
「車は実際の所要時間を考慮している？」→ OSRM で前もって計算して入れる）。

1. `./tools/carpairs.sh` が需要の流れのある駅の組を `tools/cache/osrm/pairs.csv` に書く
2. Geofabrik の日本の抽出（`tools/cache/osrm/japan-*.osm.pbf`）から OSRM の車の経路網を作る
   （`osrm-extract -p car.lua` → `osrm-partition` → `osrm-customize`・MLD）
3. `osrm-routed` を手元で立て、駅の座標どうしを table API で引く
4. 書き出す
   - アプリ用：`Data/game_car_times.bin`（駅IDの表＋組ごとの所要と道のり・`GameData.carTimes()` が読む）
   - 公開用：`~/アプリ開発/共有データ/car_times/`（CSV・駅の一覧・README）

**データの決まり**：OpenStreetMap は ODbL。所要時間の表は OSM から作ったデータなので、
同じ ODbL で公開し、アプリには「© OpenStreetMap contributors」を出す。表はほかのゲームのデータと混ぜない
（別のファイルにして、駅や路線のデータを書き換えない）。

    python3 tools/build_car_times.py            # 経路網づくり（初回だけ・数十分）から書き出しまで
    python3 tools/build_car_times.py --query    # 経路網はそのまま、引いて書き出すだけ
"""

import csv
import gzip
import json
import os
import struct
import subprocess
import sys
import time
import urllib.request
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, ".."))
WORK = os.path.join(HERE, "cache", "osrm")
DATA = os.path.join(ROOT, "Data")
SHARE = os.path.expanduser("~/アプリ開発/共有データ/car_times")
PORT = 5917
CHUNK = 300          # 1回に引く行き先の数（URLの長さに収める）


def pbf():
    files = sorted(f for f in os.listdir(WORK) if f.startswith("japan-") and f.endswith(".osm.pbf"))
    if not files:
        sys.exit("tools/cache/osrm に japan-*.osm.pbf が無い（Geofabrik の asia/japan-latest.osm.pbf）")
    return os.path.join(WORK, files[-1])


def build_graph(src):
    base = src[:-len(".osm.pbf")]
    if os.path.exists(base + ".osrm.mldgr"):
        return base + ".osrm"
    profile = subprocess.check_output(["brew", "--prefix", "osrm-backend"], text=True).strip() + "/share/osrm/profiles/car.lua"
    for cmd in (["osrm-extract", "-p", profile, "-t", "8", src],
                ["osrm-partition", base + ".osrm"],
                ["osrm-customize", base + ".osrm"]):
        print("$", " ".join(os.path.basename(c) for c in cmd), flush=True)
        subprocess.run(cmd, check=True)
    return base + ".osrm"


def main():
    src = pbf()
    graph = build_graph(src) if "--query" not in sys.argv else src[:-len(".osm.pbf")] + ".osrm"
    stations = {}
    with open(os.path.join(WORK, "stations.csv"), encoding="utf-8") as f:
        for r in csv.DictReader(f):
            stations[r["id"]] = (r["name"], float(r["lat"]), float(r["lon"]))
    by_from = defaultdict(list)
    with open(os.path.join(WORK, "pairs.csv"), encoding="utf-8") as f:
        for r in csv.DictReader(f):
            by_from[r["from"]].append(r["to"])
    print(f"駅 {len(stations)} / 組 {sum(len(v) for v in by_from.values())}", flush=True)

    server = subprocess.Popen(["osrm-routed", "--algorithm", "mld", "--port", str(PORT),
                               "--max-table-size", "10000", graph],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(120):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{PORT}/nearest/v1/driving/135.5,34.7", timeout=2)
                break
            except Exception:
                time.sleep(1)

        def query(job):
            a, dests = job
            coords = [stations[a]] + [stations[b] for b in dests]
            path = ";".join(f"{lon:.6f},{lat:.6f}" for _, lat, lon in coords)
            url = (f"http://127.0.0.1:{PORT}/table/v1/driving/{path}?sources=0"
                   f"&destinations={';'.join(str(i) for i in range(1, len(coords)))}&annotations=duration,distance")
            for attempt in range(3):
                try:
                    d = json.load(urllib.request.urlopen(url, timeout=120))
                    break
                except Exception:
                    time.sleep(1 + attempt)
            else:
                return []
            if d.get("code") != "Ok":
                return []
            out = []
            for b, sec, m in zip(dests, d["durations"][0], d["distances"][0]):
                if sec is not None and m is not None:
                    out.append((a, b, sec / 60, m / 1000))
            return out

        jobs = []
        for a, dests in by_from.items():
            for k in range(0, len(dests), CHUNK):
                jobs.append((a, dests[k:k + CHUNK]))
        rows = []
        t0 = time.time()
        with ThreadPoolExecutor(max_workers=8) as ex:
            for i, r in enumerate(ex.map(query, jobs)):
                rows += r
                if (i + 1) % 2000 == 0:
                    print(f"  {i + 1}/{len(jobs)}（{time.time() - t0:.0f}秒）", flush=True)
    finally:
        server.terminate()
    print(f"引けた組 {len(rows)}（{time.time() - t0:.0f}秒）", flush=True)

    # アプリ用（駅IDの表＋組・所要は0.1分・道のりは0.1km 単位）
    ids = sorted({a for a, *_ in rows} | {b for _, b, *_ in rows})
    index = {s: i for i, s in enumerate(ids)}
    with open(os.path.join(DATA, "game_car_times.bin"), "wb") as f:
        f.write(b"CART")
        f.write(struct.pack("<I", len(ids)))
        for s in ids:
            raw = s.encode("utf-8")
            f.write(struct.pack("<H", len(raw)) + raw)
        packed = sorted((min(index[a], index[b]), max(index[a], index[b]),
                         min(65535, round(mi * 10)), min(65535, round(km * 10))) for a, b, mi, km in rows)
        f.write(struct.pack("<I", len(packed)))
        for a, b, mi, km in packed:
            f.write(struct.pack("<HHHH", a, b, mi, km))

    # 公開用（ODbL）
    os.makedirs(SHARE, exist_ok=True)
    with gzip.open(os.path.join(SHARE, "car_times.csv.gz"), "wt", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["from_station", "to_station", "minutes", "km"])
        for a, b, mi, km in sorted(rows):
            w.writerow([a, b, f"{mi:.1f}", f"{km:.1f}"])
    with open(os.path.join(SHARE, "stations.csv"), "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["station", "name", "lat", "lon"])
        for s in ids:
            n, lat, lon = stations[s]
            w.writerow([s, n, lat, lon])
    extract = os.path.basename(src)
    with open(os.path.join(SHARE, "README.md"), "w", encoding="utf-8") as f:
        f.write(f"""# 駅どうしの自動車の所要時間

日本の鉄道駅の組ごとに、自動車で走ったときの所要時間（分）と道のり（km）。

- `car_times.csv.gz`：`from_station, to_station, minutes, km`（向きは問わない・{len(rows):,}組）
- `stations.csv`：駅の名前と座標（座標は国土数値情報 鉄道データ等から）

## 作り方

- 道路：OpenStreetMap（Geofabrik の日本の抽出 `{extract}`）
- 経路：OSRM {subprocess.check_output(['osrm-routed', '--version'], text=True).strip()}・車の設定（`car.lua` そのまま）・MLD
- 駅の座標から最寄りの道路に寄せ、table API で所要と道のりを引いた（渋滞は含まない）
- 作ったスクリプト：`build_car_times.py`（この README と同じ場所に写しを置く）

## ライセンス

This data is derived from OpenStreetMap and is made available under the
[Open Database License (ODbL) 1.0](https://opendatacommons.org/licenses/odbl/1-0/).
© OpenStreetMap contributors — https://www.openstreetmap.org/copyright
""")
    subprocess.run(["cp", os.path.abspath(__file__), os.path.join(SHARE, "build_car_times.py")])
    print("書き出した:", os.path.join(DATA, "game_car_times.bin"), SHARE, flush=True)


if __name__ == "__main__":
    main()
