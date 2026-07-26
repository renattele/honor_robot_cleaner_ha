"""HTTP views so the user can solve Honor YiDun captcha in a browser."""

from __future__ import annotations

import logging
from typing import Any

from aiohttp import web
from homeassistant.components.http import HomeAssistantView
from homeassistant.core import HomeAssistant, callback

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

CAPTCHA_STORE = "honor_captcha_sessions"


def _store(hass: HomeAssistant) -> dict[str, dict[str, Any]]:
    hass.data.setdefault(DOMAIN, {})
    return hass.data[DOMAIN].setdefault(CAPTCHA_STORE, {})


@callback
def async_register_captcha_views(hass: HomeAssistant) -> None:
    hass.http.register_view(HonorCaptchaPageView)
    hass.http.register_view(HonorCaptchaValidateView)


@callback
def async_put_captcha_session(
    hass: HomeAssistant,
    flow_id: str,
    challenge: dict[str, Any],
) -> None:
    _store(hass)[flow_id] = {
        "challenge": challenge,
        "validate": None,
        "created": __import__("time").time(),
    }


@callback
def async_get_captcha_validate(hass: HomeAssistant, flow_id: str) -> str | None:
    sess = _store(hass).get(flow_id) or {}
    val = sess.get("validate")
    return str(val) if val else None


@callback
def async_pop_captcha_session(hass: HomeAssistant, flow_id: str) -> None:
    _store(hass).pop(flow_id, None)


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
  </style>
</head>
<body>
  <h1>Honor ID</h1>
  <p>Пройди проверку (капча). После успеха вернись в Home Assistant и нажми «Продолжить».</p>
  <div id="ne-captcha"></div>
  <div id="msg"></div>
  <script>
    const FLOW = __FLOW__;
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
        const proto = location.protocol === 'https:' ? 'https:' : 'https:';
        const staticHost = CH.captcha_static_server || CH.captchaStaticServer || 'captcha-image-drru.platform.hihonorcloud.com';
        const apiHost = CH.captcha_server || CH.captchaServer || 'captcha-drru.platform.hihonorcloud.com';
        const staticBase = proto + '//' + staticHost.replace(/^https?:\\/\\//, '');
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
            const r = await fetch('/api/honor_robot_cleaner/captcha/' + encodeURIComponent(FLOW) + '/validate', {
              method: 'POST',
              headers: {'Content-Type': 'application/json'},
              credentials: 'same-origin',
              body: JSON.stringify({validate: validate})
            });
            if (!r.ok) {
              msg.className = 'err';
              msg.textContent = 'Не удалось сохранить результат (' + r.status + ').';
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

    url = "/api/honor_robot_cleaner/captcha/{flow_id}"
    name = "api:honor_robot_cleaner:captcha"
    requires_auth = True

    async def get(self, request: web.Request, flow_id: str) -> web.Response:
        hass: HomeAssistant = request.app["hass"]
        sess = _store(hass).get(flow_id)
        if not sess:
            return web.Response(status=404, text="Captcha session expired or unknown")
        challenge = sess.get("challenge") or {}
        html = (
            CAPTCHA_HTML.replace("__FLOW__", json_dumps(flow_id))
            .replace("__CHALLENGE__", json_dumps(challenge))
        )
        return web.Response(text=html, content_type="text/html")


class HonorCaptchaValidateView(HomeAssistantView):
    """Receive YiDun validate token from the captcha page."""

    url = "/api/honor_robot_cleaner/captcha/{flow_id}/validate"
    name = "api:honor_robot_cleaner:captcha_validate"
    requires_auth = True

    async def post(self, request: web.Request, flow_id: str) -> web.Response:
        hass: HomeAssistant = request.app["hass"]
        sess = _store(hass).get(flow_id)
        if not sess:
            return web.json_response({"ok": False, "error": "unknown"}, status=404)
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001
            return web.json_response({"ok": False, "error": "bad json"}, status=400)
        validate = (body or {}).get("validate")
        if not validate:
            return web.json_response({"ok": False, "error": "missing validate"}, status=400)
        sess["validate"] = str(validate)
        _LOGGER.info("Honor captcha validate received for flow %s", flow_id)
        return web.json_response({"ok": True})


def json_dumps(obj: Any) -> str:
    import json

    return json.dumps(obj, ensure_ascii=False)
