"""Production smoke tests for Things portfolio on Railway."""

from __future__ import annotations

import json
import os
import sys

import httpx

BASE = os.getenv(
    "THINGS_PROD_URL",
    "https://things-portfolio-production.up.railway.app",
).rstrip("/")results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    print(("OK" if ok else "FAIL"), name, detail)


def main() -> int:
    with httpx.Client(base_url=BASE, follow_redirects=False, timeout=45.0) as c:
        r = c.get("/health")
        body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        check(
            "health",
            r.status_code == 200
            and body.get("ok") is True
            and body.get("db_ok") is True,
            r.text[:120],
        )

        r = c.get("/")
        check("landing", r.status_code == 200 and "Стак" in r.text, f"status={r.status_code}")

        r = c.get("/manifest.webmanifest")
        check(
            "manifest",
            r.status_code == 200 and "standalone" in r.text,
            r.headers.get("content-type", ""),
        )

        r = c.get("/sw.js")
        check("sw", r.status_code == 200 and "things-v4" in r.text)

        for path in [
            "/static/icons/icon-192.png",
            "/static/icons/icon-512.png",
            "/static/icons/apple-touch-icon.png",
            "/static/pwa-install.js",
            "/static/styles.css",
        ]:
            r = c.get(path)
            check(path, r.status_code == 200, f"{r.status_code} {len(r.content)}b")

        r = c.get("/login")
        check("login_page", r.status_code == 200)
        r = c.post("/login", data={"email": "demo@things.local", "password": "demo1234"})
        check(
            "login",
            r.status_code in (302, 303),
            f"status={r.status_code} loc={r.headers.get('location')}",
        )
        cookies = r.cookies

    with httpx.Client(base_url=BASE, cookies=cookies, follow_redirects=True, timeout=45.0) as authed:
        r = authed.get("/portfolio")
        check(
            "portfolio",
            r.status_code == 200 and ("портфел" in r.text.lower() or "Стак" in r.text),
            f"len={len(r.text)}",
        )

        r = authed.get("/scan")
        check("scan_page", r.status_code == 200 and "Сфоткай" in r.text)

        r = authed.get("/api/models", params={"category": "smartphone", "q": "iphone 16"})
        models = r.json() if r.status_code == 200 else []
        check(
            "api_models_iphone16",
            r.status_code == 200 and len(models) >= 1,
            f"n={len(models)} sample={models[:2]}",
        )

        r = authed.get("/api/models", params={"category": "smartphone", "q": "galaxy s24"})
        models = r.json() if r.status_code == 200 else []
        check("api_models_s24", r.status_code == 200 and len(models) >= 1, f"n={len(models)}")

        r = authed.get("/api/models", params={"category": "smartphone", "q": "pixel"})
        models = r.json() if r.status_code == 200 else []
        check("api_models_pixel", r.status_code == 200 and len(models) >= 1, f"n={len(models)}")

        r = authed.get("/api/usage")
        check("api_usage", r.status_code == 200 and "scans_limit" in r.json(), str(r.json())[:160])

        files = {"photo": ("iphone16.jpg", b"\xff\xd8\xff\xd9fakejpeg", "image/jpeg")}
        r = authed.post("/api/scan", files=files)
        body = (
            r.json()
            if r.headers.get("content-type", "").startswith("application/json")
            else {}
        )
        check(
            "api_scan",
            r.status_code == 200 and body.get("status") == "done",
            json.dumps(body, ensure_ascii=False)[:220],
        )

        r = authed.get("/items/new", params={"category": "smartphone", "q": "iphone"})
        check(
            "items_new_phones",
            r.status_code == 200 and ("citySelect" in r.text or "iPhone" in r.text),
            f"len={len(r.text)}",
        )

        r = authed.get("/privacy")
        check("privacy", r.status_code == 200)

    failed = [x for x in results if not x[1]]
    print("---")
    print(f"{len(results) - len(failed)}/{len(results)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
