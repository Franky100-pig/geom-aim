#!/usr/bin/env python3
"""GEOM AIM 用户数度量：GitHub Release 资产下载量。

存在的唯一理由：`docs/ACCOUNT_SYSTEM_PLAN.md` §1 把「用户数 ≥ 20」定为启动账号
系统的触发条件，而在没有服务器的现在，Release 下载量是唯一零成本的近似值。
这个脚本不做别的，也不该长大。

它**不是游戏的一部分**：游戏本体保持离线优先，这个脚本只在你想知道
「够不够 20 个用户了」的时候手动跑一次。

用法：

    python3 tools/user_count.py                    # 走 gh api（需已登录）
    python3 tools/user_count.py --file rel.json    # 离线：读已保存的 releases JSON
    python3 tools/user_count.py --json             # 机器可读
    python3 tools/user_count.py --self-downloads 2 # 换个「去掉自己」的口径

为什么分母是「下载量」而不是「用户数」——这个差别必须说清楚：

* 同一个人可以下载多次（换机器、重装、帮同学下）
* CI / 镜像 / 爬虫抓 release 也会计入
* 所以它只能当**上界**用：下载量 < 20 时，用户数一定 < 20，可以放心不动工；
  反过来下载量 ≥ 20 只是「该去看一眼真实数字了」，不是「可以开工了」

判据因此是不对称的：这个脚本能**否决**启动，不能**批准**启动。
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys

REPO = "Franky100-pig/geom-aim"
THRESHOLD = 20      # §1：用户数 ≥ 20 才启动账号系统
SELF_DOWNLOADS = 1  # 粗略去掉自己：每个 release 至少被自己下过一次


def count_downloads(releases, self_downloads=SELF_DOWNLOADS):
    """把 releases API 的 JSON 折成 (每个 release 的统计, 净总计)。

    纯函数，不联网 —— 联网那部分单独放在 fetch()，这样口径可以离线测。
    `net` 按 release 逐个做减法并夹到 0，而不是先汇总再减：
    只有 1 个 release 时先汇总再减会把「自己下过」这件事算丢。
    """
    rows = []
    for rel in releases or []:
        raw = sum(int(a.get("download_count") or 0) for a in (rel.get("assets") or []))
        rows.append({
            "tag": rel.get("tag_name") or "(未命名)",
            "published_at": (rel.get("published_at") or "")[:10],
            "raw": raw,
            "net": max(raw - self_downloads, 0),
        })
    return rows, sum(r["net"] for r in rows)


def flatten_pages(data):
    """把 gh api 的返回摊平成 release 列表。

    三种形状都要能吃下，因为它们在真实调用里都会出现：
      * `[...]`              单页
      * `[[...], [...]]`     多页（`--paginate --slurp`）
      * `{"message": ...}`   出错时的对象（当成空，让上游报错更清楚）
    """
    if isinstance(data, dict):
        return []
    flat = []
    for item in data or []:
        if isinstance(item, dict):
            flat.append(item)
        elif isinstance(item, list):
            flat.extend(x for x in item if isinstance(x, dict))
    return flat


def verdict(total, threshold=THRESHOLD):
    """返回 (是否达到阈值, 一句话结论)。"""
    if total < threshold:
        return False, (
            f"下载量 {total} < {threshold} —— 用户数一定不足，"
            f"账号系统按 §1 继续不动工"
        )
    return True, (
        f"下载量 {total} ≥ {threshold} —— 下载量只是上界，"
        f"下一步是核实真实用户数，不是直接开工"
    )


def fetch(repo=REPO, timeout=30):
    """用 gh api 拉全部 release。没有 gh 或未登录时抛 RuntimeError。"""
    cmd = ["gh", "api", f"repos/{repo}/releases", "--paginate", "--slurp"]
    try:
        out = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, check=True
        )
    except FileNotFoundError as exc:
        raise RuntimeError(
            "找不到 gh CLI。装好并登录，或先用 --file 读一份已保存的 JSON。"
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"gh api 超时（{timeout}s），检查网络后重试。") from exc
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f"gh api 失败：{(exc.stderr or '').strip()}") from exc
    return json.loads(out.stdout or "[]")


def main(argv=None):
    ap = argparse.ArgumentParser(description="GEOM AIM 用户数度量（Release 下载量）")
    ap.add_argument("--repo", default=REPO, help=f"默认 {REPO}")
    ap.add_argument("--file", help="读已保存的 releases JSON（离线，不调用 gh）")
    ap.add_argument("--threshold", type=int, default=THRESHOLD)
    ap.add_argument("--self-downloads", type=int, default=SELF_DOWNLOADS)
    ap.add_argument("--json", action="store_true", help="机器可读输出")
    args = ap.parse_args(argv)

    if args.file:
        with open(args.file, encoding="utf-8") as fh:
            data = json.load(fh)
    else:
        try:
            data = fetch(args.repo)
        except RuntimeError as exc:
            print(f"错误：{exc}", file=sys.stderr)
            return 2

    releases = flatten_pages(data)
    rows, total = count_downloads(releases, self_downloads=args.self_downloads)
    enough, line = verdict(total, threshold=args.threshold)

    if args.json:
        print(json.dumps({
            "repo": args.repo,
            "threshold": args.threshold,
            "self_downloads_per_release": args.self_downloads,
            "releases": rows,
            "total_net": total,
            "enough": enough,
        }, ensure_ascii=False, indent=2))
        return 0

    if not rows:
        print(f"{args.repo}：还没有任何 release，下载量为 0。")
    else:
        print(f"{args.repo} — {len(rows)} 个 release")
        for r in sorted(rows, key=lambda r: r["published_at"]):
            print(f"  {r['tag']:<14} {r['published_at'] or '---- -- --'}  "
                  f"原始 {r['raw']:>5}  去掉自己 {r['net']:>5}")
    print(f"\n净下载量合计：{total}（阈值 {args.threshold}）")
    print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
