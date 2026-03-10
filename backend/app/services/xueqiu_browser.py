"""
雪球登录与浏览器抓取服务

登录阶段使用有界面浏览器，抓取阶段使用 headless 浏览器并复用已保存的 storage state。
"""

import json
import os
import threading
from datetime import datetime
from typing import Any, Dict, List, Optional

from ..config import Config
from ..utils.logger import get_logger

logger = get_logger("mirofish.xueqiu.browser")


class XueqiuBrowserAuthService:
    AUTH_DIR = os.path.join(Config.UPLOAD_FOLDER, "xueqiu_auth")
    STORAGE_STATE_PATH = os.path.join(AUTH_DIR, "storage_state.json")
    META_PATH = os.path.join(AUTH_DIR, "session_meta.json")

    _lock = threading.Lock()
    _playwright = None
    _browser = None
    _context = None
    _page = None

    @classmethod
    def _ensure_dir(cls) -> None:
        os.makedirs(cls.AUTH_DIR, exist_ok=True)

    @classmethod
    def _playwright_import_error(cls) -> Optional[str]:
        try:
            from playwright.sync_api import sync_playwright  # noqa: F401
            return None
        except Exception as exc:
            return str(exc)

    @classmethod
    def _read_meta(cls) -> Dict[str, Any]:
        cls._ensure_dir()
        if not os.path.exists(cls.META_PATH):
            return {
                "authenticated": False,
                "browser_open": False,
                "last_error": None,
                "last_login_at": None,
                "last_mode": None,
            }
        with open(cls.META_PATH, "r", encoding="utf-8") as f:
            return json.load(f)

    @classmethod
    def _write_meta(cls, meta: Dict[str, Any]) -> None:
        cls._ensure_dir()
        temp_path = f"{cls.META_PATH}.tmp"
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)
        os.replace(temp_path, cls.META_PATH)

    @classmethod
    def get_status(cls) -> Dict[str, Any]:
        meta = cls._read_meta()
        meta["browser_open"] = cls._page is not None
        meta["storage_state_exists"] = os.path.exists(cls.STORAGE_STATE_PATH)
        meta["playwright_available"] = cls._playwright_import_error() is None
        if not meta["playwright_available"]:
            meta["authenticated"] = False
        return meta

    @classmethod
    def start_login(cls) -> Dict[str, Any]:
        with cls._lock:
            error = cls._playwright_import_error()
            if error:
                raise RuntimeError(
                    "Playwright 不可用，请先执行 `cd backend && uv sync && uv run playwright install chromium`"
                )

            if cls._page is not None:
                return cls.get_status()

            from playwright.sync_api import sync_playwright

            cls._ensure_dir()
            cls._playwright = sync_playwright().start()
            cls._browser = cls._playwright.chromium.launch(headless=False)
            storage_state = cls.STORAGE_STATE_PATH if os.path.exists(cls.STORAGE_STATE_PATH) else None
            cls._context = cls._browser.new_context(storage_state=storage_state)
            cls._page = cls._context.new_page()
            cls._page.goto("https://xueqiu.com/", wait_until="domcontentloaded", timeout=60000)
            cls._page.bring_to_front()

            meta = cls._read_meta()
            meta.update({
                "browser_open": True,
                "last_error": None,
                "last_mode": "interactive_login",
            })
            cls._write_meta(meta)
            logger.info("雪球登录浏览器已打开")
            return cls.get_status()

    @classmethod
    def complete_login(cls) -> Dict[str, Any]:
        with cls._lock:
            if cls._context is None:
                raise RuntimeError("当前没有打开中的雪球登录浏览器")

            cookies = cls._context.cookies()
            authenticated = cls._has_auth_cookie(cookies)

            meta = cls._read_meta()
            meta["browser_open"] = False
            meta["authenticated"] = authenticated
            meta["last_login_at"] = datetime.now().isoformat() if authenticated else meta.get("last_login_at")
            meta["last_mode"] = "interactive_login"
            if authenticated:
                cls._context.storage_state(path=cls.STORAGE_STATE_PATH)
                meta["last_error"] = None
                logger.info("雪球登录态已保存")
            else:
                meta["last_error"] = "未检测到雪球登录 Cookie，请在打开的浏览器中完成登录后再点一次确认。"
            cls._write_meta(meta)
            cls._close_open_browser()
            return cls.get_status()

    @classmethod
    def logout(cls) -> Dict[str, Any]:
        with cls._lock:
            cls._close_open_browser()
            if os.path.exists(cls.STORAGE_STATE_PATH):
                os.remove(cls.STORAGE_STATE_PATH)
            meta = cls._read_meta()
            meta.update({
                "authenticated": False,
                "browser_open": False,
                "last_mode": "logout",
            })
            cls._write_meta(meta)
            return cls.get_status()

    @classmethod
    def _close_open_browser(cls) -> None:
        for obj in (cls._page, cls._context, cls._browser):
            try:
                if obj is not None:
                    obj.close()
            except Exception:
                pass
        try:
            if cls._playwright is not None:
                cls._playwright.stop()
        except Exception:
            pass
        cls._page = None
        cls._context = None
        cls._browser = None
        cls._playwright = None

    @classmethod
    def _has_auth_cookie(cls, cookies: List[Dict[str, Any]]) -> bool:
        auth_keys = {"xq_a_token", "xqat", "u"}
        return any(cookie.get("name") in auth_keys and cookie.get("value") for cookie in cookies)

    @classmethod
    def is_authenticated(cls) -> bool:
        status = cls.get_status()
        return bool(status.get("authenticated") and status.get("storage_state_exists"))

    @classmethod
    def fetch_search_statuses(cls, query: str, count: int = 10) -> List[Dict[str, Any]]:
        if not cls.is_authenticated():
            return []
        payload = cls._run_headless_fetch(query=query, count=count)
        if not payload:
            return []

        statuses = payload.get("list") or payload.get("statuses") or payload.get("items") or []
        if isinstance(statuses, list):
            return statuses
        return []

    @classmethod
    def scrape_stock_page(cls, ticker: str, sample_limit: int = 12) -> List[str]:
        if not cls.is_authenticated():
            return []

        def runner(page):
            page.goto(f"https://xueqiu.com/S/{ticker}", wait_until="domcontentloaded", timeout=60000)
            try:
                page.wait_for_load_state("networkidle", timeout=10000)
            except Exception:
                pass
            page.wait_for_timeout(2500)
            return page.evaluate(
                """
                (sampleLimit) => {
                  const selectors = [
                    'article',
                    '[class*="timeline"]',
                    '[class*="status"]',
                    '[class*="card"]',
                    '[class*="comment"]',
                    '[class*="detail"]'
                  ];
                  const texts = [];
                  for (const selector of selectors) {
                    for (const node of document.querySelectorAll(selector)) {
                      const text = (node.innerText || '').replace(/\\s+/g, ' ').trim();
                      if (text.length >= 24 && text.length <= 320) {
                        texts.push(text);
                      }
                    }
                  }
                  return Array.from(new Set(texts)).slice(0, sampleLimit);
                }
                """,
                sample_limit,
            )

        return cls._run_with_headless_page(runner) or []

    @classmethod
    def _run_headless_fetch(cls, query: str, count: int) -> Optional[Dict[str, Any]]:
        def runner(page):
            page.goto("https://xueqiu.com/", wait_until="domcontentloaded", timeout=60000)
            try:
                page.wait_for_load_state("networkidle", timeout=10000)
            except Exception:
                pass
            result = page.evaluate(
                """
                async ({ query, count }) => {
                  const url = `/query/v1/search/status.json?count=${count}&q=${encodeURIComponent(query)}`;
                  const response = await fetch(url, {
                    credentials: 'include',
                    headers: { 'x-requested-with': 'XMLHttpRequest' }
                  });
                  return {
                    status: response.status,
                    text: await response.text()
                  };
                }
                """,
                {"query": query, "count": count},
            )
            if not result or result.get("status") != 200:
                return None
            return json.loads(result["text"])

        return cls._run_with_headless_page(runner)

    @classmethod
    def _run_with_headless_page(cls, callback):
        error = cls._playwright_import_error()
        if error:
            logger.warning("Playwright 不可用，无法执行雪球浏览器抓取: %s", error)
            return None

        from playwright.sync_api import sync_playwright

        cls._ensure_dir()
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                context = browser.new_context(storage_state=cls.STORAGE_STATE_PATH)
                page = context.new_page()
                result = callback(page)
                context.close()
                browser.close()
                meta = cls._read_meta()
                meta["last_error"] = None
                meta["last_mode"] = "headless_scrape"
                cls._write_meta(meta)
                return result
        except Exception as exc:
            logger.warning("雪球 headless 抓取失败: %s", exc)
            meta = cls._read_meta()
            meta["last_error"] = str(exc)
            meta["last_mode"] = "headless_scrape"
            cls._write_meta(meta)
            return None
