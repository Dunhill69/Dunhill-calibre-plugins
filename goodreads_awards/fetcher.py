# -*- coding: utf-8 -*-
"""
Descargas de Goodreads.

Goodreads (Amazon) tiene un filtro antirrobots que a los programas les
devuelve páginas vacías. Desde calibre 9.17 se usa el navegador Camoufox que
trae calibre (un Firefox preparado para pasar esos controles). En versiones
anteriores se usa el navegador simple de calibre, con cookies.
"""

import asyncio
import re
import threading
import time

CHROME_UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
             '(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36')

# Qué tiene que aparecer en la página para darla por cargada (después del
# desafío antirrobots, que recarga la página una o más veces)
READY_SEARCH = r'class="bookTitle"|No results|searchSubNavContainer|/book/show/\d+'
READY_BOOK = r'__NEXT_DATA__|class="award"|application/ld\+json'


def camoufox_available():
    try:
        import calibre.web.automate.browser  # noqa
        return True
    except Exception:
        return False


class CamoufoxFetcher:
    """Un navegador Camoufox en su propio hilo con su propio bucle asyncio."""

    def __init__(self, log=print):
        self.log = log
        self.loop = None
        self.thread = None
        self.browser = None
        self.page = None
        self.lock = threading.Lock()

    def _start_loop(self):
        with self.lock:
            if self.loop is None:
                self.loop = asyncio.new_event_loop()
                self.thread = threading.Thread(target=self.loop.run_forever, name='GoodreadsAwardsCamoufox', daemon=True)
                self.thread.start()

    async def _launch(self):
        from calibre.web.automate.browser import Browser, Warmup
        self.log('[Goodreads Awards] Starting the Camoufox browser…')
        started = time.monotonic()
        # Visitar antes un par de sitios comunes hace que el navegador parezca
        # el de una persona y no uno recién creado
        self.browser = Browser(headless=True, warmup=Warmup(min_num=1, max_num=2, excluded_domains=('goodreads.com',)))
        await self.browser.launch()
        self.page = await self.browser.new_page()
        self.log('[Goodreads Awards] Camoufox ready in %.1f s' % (time.monotonic() - started))

    async def _get(self, url, ready, timeout):
        if self.browser is None:
            await self._launch()
        deadline = time.monotonic() + timeout
        await self.page.open(url, wait='domcontentloaded', timeout=timeout)
        html = ''
        while True:
            try:
                html = await self.page.html()
            except Exception:
                html = ''  # la página se está recargando (desafío antirrobots)
            if not ready or re.search(ready, html or '') or time.monotonic() > deadline:
                break
            await asyncio.sleep(1)
        try:
            final = await self.page.current_url()
        except Exception:
            final = url
        return html or '', final or url

    def submit(self, url, ready=None, timeout=60):
        """Devuelve un concurrent.futures.Future con (html, url_final)."""
        self._start_loop()
        return asyncio.run_coroutine_threadsafe(self._get(url, ready, timeout), self.loop)

    async def _close(self):
        browser, self.browser, self.page = self.browser, None, None
        if browser is not None:
            try:
                await browser.close()
            except Exception:
                pass

    def close(self):
        """Cierra el navegador y el hilo (sin bloquear la interfaz)."""
        loop = self.loop
        if loop is None:
            return
        fut = asyncio.run_coroutine_threadsafe(self._close(), loop)

        def stop():
            try:
                fut.result(60)
            except Exception:
                pass
            loop.call_soon_threadsafe(loop.stop)
        threading.Thread(target=stop, daemon=True).start()
        self.loop = None


class SimpleFetcher:
    """Navegador simple de calibre (mechanize) o urllib, con cookies."""

    def __init__(self, headers):
        self.headers = headers
        self.opener = None

    def _get_opener(self):
        if self.opener is None:
            try:
                from calibre import browser
                br = browser(user_agent=self.headers.get('User-Agent', CHROME_UA))
                br.addheaders = list(self.headers.items())

                def open_url(url, timeout):
                    resp = br.open_novisit(url, timeout=timeout)
                    return resp.read(), resp.geturl()
            except Exception:
                from http.cookiejar import CookieJar
                from urllib.request import build_opener, HTTPCookieProcessor, Request
                op = build_opener(HTTPCookieProcessor(CookieJar()))

                def open_url(url, timeout):
                    with op.open(Request(url, headers=self.headers), timeout=timeout) as resp:
                        return resp.read(), resp.geturl()
            self.opener = open_url
        return self.opener

    def get(self, url, timeout=25):
        raw, final = self._get_opener()(url, timeout)
        return raw.decode('utf-8', errors='replace'), final or url


def wait_future(fut, timeout):
    """Espera un Future. En el hilo de la interfaz sigue procesando eventos
    para que calibre no se congele mientras arranca el navegador."""
    if threading.current_thread() is threading.main_thread():
        try:
            from qt.core import QApplication, QEventLoop
        except Exception:
            return fut.result(timeout)
        end = time.monotonic() + timeout
        while not fut.done():
            if time.monotonic() > end:
                fut.cancel()
                raise TimeoutError('Timed out')
            QApplication.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 50)
            time.sleep(0.02)
        return fut.result()
    return fut.result(timeout)
