import json

PAGE_TIMEOUT_MS = 30000
SETTLE_MS = 1500


class Browser:
    def __enter__(self):
        from playwright.sync_api import sync_playwright
        self._pw = sync_playwright().start()
        try:
            self._browser = self._pw.chromium.launch(channel="chrome", headless=True)
        except Exception:
            self._pw.stop()
            raise
        self.page = self._browser.new_page()
        return self

    def __exit__(self, *exc):
        self._browser.close()
        self._pw.stop()

    def answers(self, action, url_part, accept=None, as_text=False):
        got = []

        def on_response(resp):
            if url_part in resp.url and (accept is None or accept(resp)):
                got.append(resp)

        self.page.on("response", on_response)
        try:
            with self.page.expect_response(lambda r: url_part in r.url and (accept is None or accept(r)),
                                           timeout=PAGE_TIMEOUT_MS):
                action(self.page)
            self.page.wait_for_timeout(SETTLE_MS)
        finally:
            self.page.remove_listener("response", on_response)
        bodies = []
        for resp in got:
            if resp.status != 200:
                raise RuntimeError(f"search answered HTTP {resp.status}")
            try:
                bodies.append(resp.text() if as_text else resp.json())
            except (ValueError, json.JSONDecodeError):
                continue
        return bodies


def run_in_browser(collector, read_with):
    try:
        with Browser() as browser:
            read_with(browser)
    except Exception as e:
        first_line = str(e).splitlines()[0][:160] if str(e) else ""
        collector.fail(f"browser: {type(e).__name__}: {first_line}")
