"""UK-IP checkpoints on the Playwright worker thread; no automatic retry or posting."""
from review_store import ReviewError


class PosterNetworkProtection:
    def _verify_network(self, force=False):
        if not self.network_guard.enabled:
            return self.network_guard.snapshot()
        self._ensure_browser()
        try:
            result = self.network_guard.check(self._context, force=force)
            return result
        except ReviewError:
            self.diagnostics.record("network_blocked")
            self._prepared.clear()
            context, self._context = self._context, None
            if context is not None:
                try:
                    context.close()
                except Exception:
                    self.diagnostics.record("browser_close_failed")
            self._state_update(status="disconnected", email="", message=self.network_guard.snapshot()["message"])
            active = self.store.active()
            if active:
                uncertain = active["status"] == "submitting"
                self.store.update(active["id"], status="unconfirmed" if uncertain else "interrupted",
                                  message="Network check failed. Check Google before any retry." if uncertain else
                                  "UK IP could not be confirmed. Review interrupted before submission; nothing was retried.")
            raise

    def _network(self, unused):
        return self._verify_network(force=True)

    def _idle_network_check(self):
        if self._context is None or not self.network_guard.enabled or self.network_guard.snapshot()["allowed"]:
            return
        with self._lock:
            if self._state["busy"] or not self._queue.empty() or self._stop.is_set():
                return
            self._state["busy"] = True
        try:
            self._verify_network(force=True)
        except ReviewError:
            pass
        except Exception:
            self.network_guard.invalidate()
            self.diagnostics.record("network_check_failed")
            context, self._context = self._context, None
            if context is not None:
                try:
                    context.close()
                except Exception:
                    self.diagnostics.record("browser_close_failed")
            self._prepared.clear()
            self._state_update(status="error", email="", message="Network protection needs attention. Close and restart the app.")
        finally:
            self._state_update(busy=False)
