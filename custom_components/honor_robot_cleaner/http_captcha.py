"""HTTP views so the user can solve Honor YiDun captcha in a browser."""

from __future__ import annotations

import logging
import secrets
import time
from typing import Any

from aiohttp import web
from homeassistant.components.http import HomeAssistantView
from homeassistant.core import HomeAssistant, callback

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

CAPTCHA_STORE = "honor_captcha_sessions"
_VIEWS_FLAG = "_captcha_views_registered"


def _store(hass: HomeAssistant) -> dict[str, dict[str, Any]]:
    hass.data.setdefault(DOMAIN, {})
    return hass.data[DOMAIN].setdefault(CAPTCHA_STORE, {})


@callback
def async_register_captcha_views(hass: HomeAssistant) -> None:
    """Register captcha HTTP routes (safe to call multiple times)."""
    hass.data.setdefault(DOMAIN, {})
    if hass.data[DOMAIN].get(_VIEWS_FLAG):
        return
    # Pass instances — some HA versions are picky about class vs instance.
    hass.http.register_view(HonorCaptchaPageView())
    hass.http.register_view(HonorCaptchaValidateView())
    hass.data[DOMAIN][_VIEWS_FLAG] = True
    _LOGGER.info("Registered Honor captcha HTTP views")


def _ensure_www_captcha_page(hass: HomeAssistant) -> None:
    """Ship a /local/ captcha page (works through most reverse proxies)."""
    import os

    www = hass.config.path("www")
    os.makedirs(www, exist_ok=True)
    dest = os.path.join(www, "honor_robot_cleaner_captcha.html")
    # Always refresh so upgrades pick up HTML changes
    with open(dest, "w", encoding="utf-8") as fh:
        fh.write(WWW_CAPTCHA_HTML)


@callback
def async_put_captcha_session(
    hass: HomeAssistant,
    flow_id: str,
    challenge: dict[str, Any],
) -> str:
    """Store challenge; return captcha URL on the same host as the HA UI."""
    async_register_captcha_views(hass)
    token = secrets.token_urlsafe(16)
    _store(hass)[flow_id] = {
        "challenge": challenge,
        "validate": None,
        "token": token,
        "created": time.time(),
    }
    try:
        _ensure_www_captcha_page(hass)
    except OSError as err:
        _LOGGER.warning("Could not write /local captcha page: %s", err)

    # Prefer /local/ — reverse proxies (home.lxbx.ru) almost always forward it.
    # Challenge is passed in the query string; validate is posted to API and/or pasted.
    from urllib.parse import urlencode

    q = urlencode(
        {
            "flow": flow_id,
            "token": token,
            "captcha_id": challenge.get("captcha_id") or "",
            "captcha_server": challenge.get("captcha_server") or "",
            "captcha_static_server": challenge.get("captcha_static_server") or "",
        }
    )
    return f"/local/honor_robot_cleaner_captcha.html?{q}"


WWW_CAPTCHA_HTML = """<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>Honor ID captcha</title>
  <style>
    body { font-family: system-ui, sans-serif; margin: 2rem; max-width: 32rem; }
    .ok { color: #0a7; margin-top: 1rem; }
    .err { color: #c33; margin-top: 1rem; }
    #ne-captcha { margin-top: 1rem; min-height: 40px; }
    code { word-break: break-all; display:block; margin-top:.5rem; padding:.5rem; background:#f4f4f4; }
  </style>
</head>
<body>
  <h1>Honor ID</h1>
  <p>Пройди проверку. После успеха вернись в Home Assistant и нажми «Отправить».</p>
  <div id="ne-captcha"></div>
  <div id="msg"></div>
  <script>
    const params = new URLSearchParams(location.search);
    const FLOW = params.get('flow') || '';
    const TOKEN = params.get('token') || '';
    const CH = {
      captcha_id: params.get('captcha_id') || '',
      captcha_server: params.get('captcha_server') || 'captcha-drru.platform.hihonorcloud.com',
      captcha_static_server: params.get('captcha_static_server') || 'captcha-image-drru.platform.hihonorcloud.com',
    };
    const msg = document.getElementById('msg');
    function loadScript(src) {
      return new Promise((resolve, reject) => {
        const s = document.createElement('script');
        s.src = src;
        s.onload = () => resolve();
        s.onerror = () => reject(new Error('load failed: ' + src));
        document.head.appendChild(s);
      });
    }
    async function saveValidate(validate) {
      try {
        const r = await fetch(
          '/api/honor_robot_cleaner/captcha/' + encodeURIComponent(FLOW) + '/' + encodeURIComponent(TOKEN) + '/validate',
          { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({validate}) }
        );
        return r.ok;
      } catch (e) { return false; }
    }
    async function main() {
      try {
        if (!CH.captcha_id) throw new Error('captcha_id missing — restart Honor login in HA');
        const staticBase = 'https://' + CH.captcha_static_server.replace(/^https?:\\/\\//, '');
        await loadScript(staticBase + '/load.min.js');
        if (!window.initNECaptcha) throw new Error('initNECaptcha missing');
        window.initNECaptcha({
          captchaId: CH.captcha_id,
          element: '#ne-captcha',
          mode: 'popup',
          width: '320px',
          apiServer: CH.captcha_server.replace(/^https?:\\/\\//, ''),
          staticServer: CH.captcha_static_server.replace(/^https?:\\/\\//, ''),
          onVerify: async function(err, data) {
            if (err) { msg.className='err'; msg.textContent='Капча не пройдена'; return; }
            const validate = data && data.validate;
            if (!validate) { msg.className='err'; msg.textContent='Пустой validate'; return; }
            const ok = await saveValidate(validate);
            msg.className = 'ok';
            if (ok) {
              msg.textContent = 'Готово. Вернись в Home Assistant и нажми «Отправить».';
            } else {
              msg.innerHTML = 'Скопируй код в форму HA (поле validate):<code>' + validate + '</code>';
            }
          }
        }, function onerror(err) {
          msg.className='err'; msg.textContent='Ошибка капчи: ' + err;
        });
      } catch (e) {
        msg.className='err'; msg.textContent=String(e);
      }
    }
    main();
  </script>
</body>
</html>
"""


@callback
def async_get_captcha_validate(hass: HomeAssistant, flow_id: str) -> str | None:
    sess = _store(hass).get(flow_id) or {}
    val = sess.get("validate")
    return str(val) if val else None


@callback
def async_set_captcha_validate(
    hass: HomeAssistant, flow_id: str, validate: str
) -> None:
    sess = _store(hass).get(flow_id)
    if sess is None:
        _store(hass)[flow_id] = {
            "challenge": {},
            "validate": validate,
            "token": "",
            "created": time.time(),
        }
    else:
        sess["validate"] = validate


@callback
def async_pop_captcha_session(hass: HomeAssistant, flow_id: str) -> None:
    _store(hass).pop(flow_id, None)


def _session_for(
    hass: HomeAssistant, flow_id: str, token: str
) -> dict[str, Any] | None:
    sess = _store(hass).get(flow_id)
    if not sess:
        return None
    expected = sess.get("token") or ""
    if not expected or not secrets.compare_digest(str(expected), str(token)):
        return None
    return sess


CAPTCHA_HTML = """<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>Honor ID captcha</title>
  <style>
    body { font-family: system-ui, sans-serif; margin: 2rem; max-width: 28rem; }
    .ok { color: #0a7; margin-top: 1rem; }
    .err { color: #c33; margin-top: 1rem; }
    #ne-captcha { margin-top: 1rem; min-height: 40px; }
    code { word-break: break-all; }
  </style>
</head>
<body>
  <h1>Honor ID</h1>
  <p>Пройди проверку. После успеха вернись в Home Assistant и нажми «Продолжить».</p>
  <div id="ne-captcha"></div>
  <div id="msg"></div>
  <script>
    const FLOW = __FLOW__;
    const TOKEN = __TOKEN__;
    const CH = __CHALLENGE__;
    const msg = document.getElementById('msg');
    function loadScript(src) {
      return new Promise((resolve, reject) => {
        const s = document.createElement('script');
        s.src = src;
        s.onload = () => resolve();
        s.onerror = () => reject(new Error('load failed: ' + src));
        document.head.appendChild(s);
      });
    }
    async function main() {
      try {
        const staticHost = CH.captcha_static_server || CH.captchaStaticServer || 'captcha-image-drru.platform.hihonorcloud.com';
        const apiHost = CH.captcha_server || CH.captchaServer || 'captcha-drru.platform.hihonorcloud.com';
        const staticBase = 'https://' + staticHost.replace(/^https?:\\/\\//, '');
        await loadScript(staticBase + '/load.min.js');
        if (!window.initNECaptcha) {
          throw new Error('initNECaptcha missing');
        }
        window.initNECaptcha({
          captchaId: CH.captcha_id || CH.captchaId,
          element: '#ne-captcha',
          mode: 'popup',
          width: '320px',
          apiServer: apiHost.replace(/^https?:\\/\\//, ''),
          staticServer: staticHost.replace(/^https?:\\/\\//, ''),
          onVerify: async function(err, data) {
            if (err) {
              msg.className = 'err';
              msg.textContent = 'Капча не пройдена, попробуй ещё раз.';
              return;
            }
            const validate = data && data.validate;
            if (!validate) {
              msg.className = 'err';
              msg.textContent = 'Пустой validate.';
              return;
            }
            const r = await fetch(
              '/api/honor_robot_cleaner/captcha/' + encodeURIComponent(FLOW) + '/' + encodeURIComponent(TOKEN) + '/validate',
              {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({validate: validate})
              }
            );
            if (!r.ok) {
              msg.className = 'err';
              msg.innerHTML = 'Не удалось сохранить (' + r.status + '). Скопируй код вручную:<br><code>' + validate + '</code>';
              return;
            }
            msg.className = 'ok';
            msg.textContent = 'Готово. Вернись в Home Assistant и нажми «Продолжить».';
          }
        }, function onerror(err) {
          msg.className = 'err';
          msg.textContent = 'Ошибка инициализации капчи: ' + err;
        });
      } catch (e) {
        msg.className = 'err';
        msg.textContent = String(e);
      }
    }
    main();
  </script>
</body>
</html>
"""


class HonorCaptchaPageView(HomeAssistantView):
    """Serve YiDun captcha page for a config-flow session."""

    url = "/api/honor_robot_cleaner/captcha/{flow_id}/{token}"
    name = "api:honor_robot_cleaner:captcha"
    requires_auth = False

    async def get(
        self, request: web.Request, flow_id: str, token: str
    ) -> web.Response:
        hass: HomeAssistant = request.app["hass"]
        sess = _session_for(hass, flow_id, token)
        if not sess:
            return web.Response(
                status=404,
                text=(
                    "Captcha session not found. Start Honor login again in "
                    "Home Assistant and open the NEW link (same host as HA UI, "
                    "e.g. https://home.lxbx.ru/...)."
                ),
            )
        challenge = sess.get("challenge") or {}
        html = (
            CAPTCHA_HTML.replace("__FLOW__", json_dumps(flow_id))
            .replace("__TOKEN__", json_dumps(token))
            .replace("__CHALLENGE__", json_dumps(challenge))
        )
        return web.Response(text=html, content_type="text/html")


class HonorCaptchaValidateView(HomeAssistantView):
    """Receive YiDun validate token from the captcha page."""

    url = "/api/honor_robot_cleaner/captcha/{flow_id}/{token}/validate"
    name = "api:honor_robot_cleaner:captcha_validate"
    requires_auth = False

    async def post(
        self, request: web.Request, flow_id: str, token: str
    ) -> web.Response:
        hass: HomeAssistant = request.app["hass"]
        sess = _session_for(hass, flow_id, token)
        if not sess:
            return web.json_response({"ok": False, "error": "unknown"}, status=404)
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001
            return web.json_response({"ok": False, "error": "bad json"}, status=400)
        validate = (body or {}).get("validate")
        if not validate:
            return web.json_response(
                {"ok": False, "error": "missing validate"}, status=400
            )
        sess["validate"] = str(validate)
        _LOGGER.info("Honor captcha validate received for flow %s", flow_id)
        return web.json_response({"ok": True})


def json_dumps(obj: Any) -> str:
    import json

    return json.dumps(obj, ensure_ascii=False)
