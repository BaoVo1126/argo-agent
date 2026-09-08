from __future__ import annotations
import argparse
import sys
from modes.research import bank_rates, snapshots


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass

    parser = argparse.ArgumentParser(description="Argo — lưu bảng lãi suất hôm nay")
    parser.add_argument("--quiet", action="store_true", help="chỉ in một dòng kết quả")
    parser.add_argument("--headed", action="store_true", help="hiện cửa sổ trình duyệt")
    args = parser.parse_args(argv)

    log = (lambda _line: None) if args.quiet else print
    result = bank_rates.capture(headless=not args.headed, log=log)

    if not result.ok:
        print("KHÔNG lấy được bảng lãi suất: " + "; ".join(result.errors or ["không rõ lý do"]))
        return 1

    snapshot = result.snapshot
    snapshots.append(snapshot)
    history = snapshots.load()

    check = snapshot.crosscheck or {}
    agrees = check.get("agrees")
    status = ("khớp với BIDV" if agrees
              else f"LỆCH với BIDV ở kỳ hạn {check.get('mismatched')}" if check.get("checked")
              else "chưa đối chiếu được với BIDV")

    print(f"Đã lưu {len(snapshot.quotes)} mức lãi suất của "
          f"{len(snapshot.banks('counter'))} ngân hàng · {status} · "
          f"tổng cộng {len(history)} lần cập nhật")

    if check.get("checked") and not agrees:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
