#!/usr/bin/env python3
"""
code_scan.py  -  สแกนโค้ด Python แบบ SonarQube แต่เบากว่ามาก
รวมผลจาก Ruff + Bandit + mypy ออกมาเป็นรายงาน HTML ไฟล์เดียว

ใช้งาน:
    python code_scan.py            # สแกนโฟลเดอร์ปัจจุบัน (.)
    python code_scan.py app/       # สแกนโฟลเดอร์ที่ระบุ
    python code_scan.py app/ -o myreport.html

ต้องติดตั้งก่อน:
    pip install ruff bandit mypy
"""

import argparse
import datetime
import html
import json
import os
import subprocess
import sys
from pathlib import Path


def run_cmd(args: list[str]) -> tuple[str, str, int]:
    """รันคำสั่งแล้วคืน (stdout, stderr, returncode) โดยไม่ throw เมื่อ exit != 0."""
    try:
        proc = subprocess.run(args, capture_output=True, text=True, encoding="utf-8")
        return proc.stdout or "", proc.stderr or "", proc.returncode
    except FileNotFoundError:
        return "", f"ไม่พบคำสั่ง: {args[0]} (ติดตั้งหรือยัง?)", 127


def scan_ruff(target: str) -> list[dict]:
    out, err, _ = run_cmd(
        ["ruff", "check", target, "--no-cache", "--output-format", "json"]
    )
    if not out.strip():
        return []
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        return []
    rows = []
    for it in data:
        loc = it.get("location") or {}
        rows.append({
            "file": it.get("filename", ""),
            "line": loc.get("row", ""),
            "rule": it.get("code") or "",
            "severity": "Warning",
            "message": it.get("message", ""),
        })
    return rows


def scan_bandit(target: str) -> list[dict]:
    out, err, _ = run_cmd(["bandit", "-r", target, "-f", "json", "-q"])
    if not out.strip():
        return []
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        return []
    sev_map = {"HIGH": "Critical", "MEDIUM": "Major", "LOW": "Minor"}
    rows = []
    for it in data.get("results", []):
        rows.append({
            "file": it.get("filename", ""),
            "line": it.get("line_number", ""),
            "rule": it.get("test_id", ""),
            "severity": sev_map.get(it.get("issue_severity", ""), "Minor"),
            "message": it.get("issue_text", ""),
        })
    return rows


def scan_mypy(target: str) -> list[dict]:
    out, err, _ = run_cmd(
        ["mypy", target, "--no-error-summary", "--no-color-output",
         "--show-error-codes", "--cache-dir", os.devnull]
    )
    rows = []
    for line in out.splitlines():
        # path:line: error/note: message  [code]
        parts = line.split(":", 3)
        if len(parts) < 4:
            continue
        file, lineno, kind, rest = parts[0], parts[1], parts[2].strip(), parts[3].strip()
        if kind not in ("error", "warning", "note"):
            continue
        code = ""
        if rest.endswith("]") and "[" in rest:
            code = rest[rest.rfind("[") + 1:-1]
            rest = rest[:rest.rfind("[")].strip()
        rows.append({
            "file": file,
            "line": lineno,
            "rule": code or "type",
            "severity": "Major" if kind == "error" else "Minor",
            "message": rest,
        })
    return rows


SEV_ORDER = {"Critical": 0, "Major": 1, "Warning": 2, "Minor": 3}
SEV_COLOR = {
    "Critical": "#d6334c", "Major": "#e8833a",
    "Warning": "#d9a300", "Minor": "#5a8dd6",
}


def build_html(results: dict[str, list[dict]], target: str) -> str:
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    all_rows = [r for rows in results.values() for r in rows]
    total = len(all_rows)
    by_sev: dict[str, int] = {}
    for r in all_rows:
        by_sev[r["severity"]] = by_sev.get(r["severity"], 0) + 1

    # เกณฑ์ผ่าน/ไม่ผ่าน แบบง่าย ๆ (เลียนแบบ Quality Gate)
    crit = by_sev.get("Critical", 0)
    major = by_sev.get("Major", 0)
    if crit > 0:
        gate, gate_color = "FAILED", "#d6334c"
    elif major > 0:
        gate, gate_color = "WARN", "#e8833a"
    else:
        gate, gate_color = "PASSED", "#1f9d57"

    def cards() -> str:
        c = [f'<div class="card gate" style="border-color:{gate_color}">'
             f'<div class="big" style="color:{gate_color}">{gate}</div>'
             f'<div class="lbl">Quality Gate</div></div>',
             f'<div class="card"><div class="big">{total}</div>'
             f'<div class="lbl">Issues ทั้งหมด</div></div>']
        for sev in ["Critical", "Major", "Warning", "Minor"]:
            n = by_sev.get(sev, 0)
            c.append(f'<div class="card"><div class="big" style="color:{SEV_COLOR[sev]}">{n}</div>'
                     f'<div class="lbl">{sev}</div></div>')
        return "".join(c)

    def table(rows: list[dict]) -> str:
        if not rows:
            return '<p class="empty">ไม่พบปัญหา ✓</p>'
        rows = sorted(rows, key=lambda r: (SEV_ORDER.get(r["severity"], 9), r["file"]))
        body = []
        for r in rows:
            col = SEV_COLOR.get(r["severity"], "#888")
            body.append(
                "<tr>"
                f'<td><span class="badge" style="background:{col}">{html.escape(r["severity"])}</span></td>'
                f'<td class="mono">{html.escape(str(r["file"]))}:{html.escape(str(r["line"]))}</td>'
                f'<td class="mono">{html.escape(str(r["rule"]))}</td>'
                f'<td>{html.escape(str(r["message"]))}</td>'
                "</tr>"
            )
        return ('<table><thead><tr><th>Severity</th><th>ตำแหน่ง</th>'
                '<th>Rule</th><th>รายละเอียด</th></tr></thead><tbody>'
                + "".join(body) + "</tbody></table>")

    sections = []
    titles = {"ruff": "Ruff — Lint / Code Smell",
              "bandit": "Bandit — Security",
              "mypy": "mypy — Type Check"}
    for key, rows in results.items():
        sections.append(f'<h2>{titles.get(key, key)} <span class="count">({len(rows)})</span></h2>'
                        + table(rows))

    return f"""<!doctype html>
<html lang="th"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Code Scan Report</title>
<style>
  * {{ box-sizing: border-box; }}
  body {{ font-family: -apple-system, "Segoe UI", Roboto, sans-serif; margin:0;
         background:#f4f6f9; color:#1c2733; }}
  header {{ background:#1c2733; color:#fff; padding:24px 32px; }}
  header h1 {{ margin:0 0 4px; font-size:20px; }}
  header .meta {{ font-size:13px; opacity:.75; }}
  .wrap {{ max-width:1100px; margin:0 auto; padding:24px 32px 48px; }}
  .cards {{ display:flex; gap:14px; flex-wrap:wrap; margin-bottom:8px; }}
  .card {{ background:#fff; border:1px solid #e3e8ee; border-radius:10px;
          padding:16px 20px; min-width:120px; flex:1; text-align:center; }}
  .card.gate {{ border-width:2px; }}
  .card .big {{ font-size:28px; font-weight:700; }}
  .card .lbl {{ font-size:12px; color:#6b7886; margin-top:4px; }}
  h2 {{ font-size:16px; margin:32px 0 12px; }}
  h2 .count {{ color:#6b7886; font-weight:400; font-size:14px; }}
  table {{ width:100%; border-collapse:collapse; background:#fff;
          border:1px solid #e3e8ee; border-radius:10px; overflow:hidden; }}
  th, td {{ text-align:left; padding:10px 14px; font-size:13px;
           border-bottom:1px solid #eef1f5; vertical-align:top; }}
  th {{ background:#f7f9fb; color:#6b7886; font-weight:600; }}
  tr:last-child td {{ border-bottom:none; }}
  .mono {{ font-family: ui-monospace, "Cascadia Code", Consolas, monospace; font-size:12px; }}
  .badge {{ color:#fff; padding:2px 8px; border-radius:20px; font-size:11px; font-weight:600; }}
  .empty {{ color:#1f9d57; background:#fff; border:1px solid #e3e8ee;
           border-radius:10px; padding:14px; }}
</style></head>
<body>
<header>
  <h1>รายงานสแกนคุณภาพโค้ด</h1>
  <div class="meta">เป้าหมาย: {html.escape(target)} &nbsp;·&nbsp; สร้างเมื่อ: {now}
       &nbsp;·&nbsp; Ruff + Bandit + mypy</div>
</header>
<div class="wrap">
  <div class="cards">{cards()}</div>
  {''.join(sections)}
</div>
</body></html>"""


_SOURCE_CACHE: dict[str, list[str] | None] = {}


def read_source(path: str) -> list[str] | None:
    if path not in _SOURCE_CACHE:
        try:
            _SOURCE_CACHE[path] = Path(path).read_text(
                encoding="utf-8", errors="replace"
            ).splitlines()
        except OSError:
            _SOURCE_CACHE[path] = None
    return _SOURCE_CACHE[path]


def _norm(path: str) -> str:
    """ทำให้ path จากทุกเครื่องมือเป็นรูปแบบเดียวกัน (relative กับ cwd)."""
    try:
        return os.path.relpath(os.path.abspath(path))
    except ValueError:
        return path


def _to_int(v) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0


def _merge_windows(line_nums: set[int], total: int, ctx: int) -> list[tuple[int, int]]:
    merged: list[tuple[int, int]] = []
    for ln in sorted(line_nums):
        s, e = max(1, ln - ctx), min(total, ln + ctx)
        if merged and s <= merged[-1][1] + 1:
            merged[-1] = (merged[-1][0], max(merged[-1][1], e))
        else:
            merged.append((s, e))
    return merged


def _render_snippet(lines: list[str], issue_lines: set[int], ctx: int, full: bool) -> str:
    total = len(lines)
    out: list[str] = []
    if full:
        windows = [(1, total)]
    else:
        windows = _merge_windows(issue_lines, total, ctx)
    for i, (s, e) in enumerate(windows):
        if i > 0:
            out.append("       ...")
        for ln in range(s, e + 1):
            mark = ">" if ln in issue_lines else " "
            out.append(f"{mark} {ln:4d} | {lines[ln - 1]}")
    return "\n".join(out)


def build_prompt(results: dict[str, list[dict]], target: str, ctx: int, full: bool) -> str:
    by_file: dict[str, list[dict]] = {}
    for tool, rows in results.items():
        for r in rows:
            by_file.setdefault(r["file"], []).append({**r, "tool": tool})

    total_issues = sum(len(v) for v in by_file.values())
    p: list[str] = []
    p.append("# งานแก้โค้ดจากผลสแกนคุณภาพ (Ruff + Bandit + mypy)\n")
    p.append(
        "คุณเป็นวิศวกรซอฟต์แวร์ที่ช่วยแก้โค้ด Python ด้านล่างคือ issue ที่เครื่องมือสแกนตรวจพบ "
        f"ทั้งหมด **{total_issues} รายการ** จาก **{len(by_file)} ไฟล์**\n\n"
        "กรุณา:\n"
        "1. แก้ทุก issue โดยคงพฤติกรรมเดิมของโปรแกรมไว้ "
        "(ยกเว้นช่องโหว่ security ที่ต้องแก้ให้ปลอดภัยขึ้น)\n"
        "2. สำหรับแต่ละไฟล์ ส่งโค้ดเวอร์ชันที่แก้แล้วกลับมาให้\n"
        "3. ใต้โค้ดของแต่ละไฟล์ สรุปสั้น ๆ ว่าแก้ issue ไหน และแก้อย่างไร\n"
        "4. ถ้า issue ไหนเป็น false positive ให้บอกเหตุผลแทนการแก้\n\n"
        "หมายเหตุ: ในบล็อกโค้ด บรรทัดที่ขึ้นต้นด้วย `>` คือบรรทัดที่ตรวจพบปัญหา "
        "(เลขหน้า `|` คือเลขบรรทัดจริงในไฟล์)\n\n---"
    )

    for file in sorted(by_file):
        issues = sorted(
            by_file[file],
            key=lambda x: (SEV_ORDER.get(x["severity"], 9), _to_int(x["line"])),
        )
        p.append(f"\n## ไฟล์: `{file}`\n")
        p.append("**Issues ที่ต้องแก้:**\n")
        for r in issues:
            p.append(
                f"- [{r['tool']} · {r['rule']} · {r['severity']}] "
                f"บรรทัด {r['line']}: {r['message']}"
            )
        lines = read_source(file)
        if lines is None:
            p.append("\n_(อ่านไฟล์นี้ไม่ได้ — กรุณาแนบโค้ดเพิ่มเอง)_")
            continue
        issue_lines = {_to_int(r["line"]) for r in issues if _to_int(r["line"]) > 0}
        snippet = _render_snippet(lines, issue_lines, ctx, full)
        p.append("\n```python\n" + snippet + "\n```")

    return "\n".join(p) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description="สแกนโค้ด Python เป็นรายงาน HTML")
    ap.add_argument("target", nargs="?", default=".", help="โฟลเดอร์/ไฟล์ที่จะสแกน")
    here = Path(__file__).resolve().parent
    ap.add_argument("-o", "--output", default=str(here / "report.html"),
                    help="ไฟล์รายงาน HTML (default: ข้าง ๆ สคริปต์)")
    ap.add_argument("-p", "--prompt", default=str(here / "fix_prompt.md"),
                    help="ไฟล์ prompt สำหรับวางลง Claude (default: ข้าง ๆ สคริปต์)")
    ap.add_argument("-c", "--context", type=int, default=5,
                    help="จำนวนบรรทัดโค้ดรอบ ๆ จุดที่มีปัญหา (default 5)")
    ap.add_argument("--full-context", action="store_true",
                    help="ใส่โค้ดทั้งไฟล์ลงใน prompt แทนเฉพาะส่วนที่เกี่ยวข้อง")
    args = ap.parse_args()

    if not Path(args.target).exists():
        print(f"ไม่พบ path: {args.target}", file=sys.stderr)
        return 1

    print(f"กำลังสแกน {args.target} ...")
    results = {
        "ruff": scan_ruff(args.target),
        "bandit": scan_bandit(args.target),
        "mypy": scan_mypy(args.target),
    }
    for rows in results.values():
        for r in rows:
            r["file"] = _norm(r["file"])

    for k, v in results.items():
        print(f"  {k:7s}: {len(v)} issue(s)")

    total = sum(len(v) for v in results.values())
    Path(args.output).write_text(build_html(results, args.target), encoding="utf-8")
    print(f"\n[1] รายงาน HTML -> {args.output}  (เปิดด้วย browser)")

    if total == 0:
        print("[2] ไม่พบ issue เลย ไม่ต้องสร้าง prompt แก้โค้ด ✓")
    else:
        prompt = build_prompt(results, args.target, args.context, args.full_context)
        Path(args.prompt).write_text(prompt, encoding="utf-8")
        print(f"[2] Prompt แก้โค้ด -> {args.prompt}  (ก๊อปเนื้อหาไปวางใน Claude)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
