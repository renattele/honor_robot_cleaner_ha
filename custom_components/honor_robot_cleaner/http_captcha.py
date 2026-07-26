"""Honor YiDun captcha via HA external config-flow step + webhook."""

from __future__ import annotations

import json
import logging
import secrets
import time
from typing import Any

from aiohttp import web
from homeassistant.components import webhook
from homeassistant.core import HomeAssistant, callback

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

CAPTCHA_STORE = "honor_captcha_sessions"
PAGE_VERSION = "1.3.14"


def _store(hass: HomeAssistant) -> dict[str, dict[str, Any]]:
    hass.data.setdefault(DOMAIN, {})
    return hass.data[DOMAIN].setdefault(CAPTCHA_STORE, {})


@callback
def async_register_captcha_views(hass: HomeAssistant) -> None:
    """Kept for callers; captcha is served by the webhook handler."""
    hass.data.setdefault(DOMAIN, {})


def _render_captcha_html(webhook_id: str, challenge: dict[str, Any]) -> str:
    payload = {
        "webhook": webhook_id,
        "captcha_id": challenge.get("captcha_id") or "",
        "captcha_server": (
            str(challenge.get("captcha_server") or "captcha-drru.platform.hihonorcloud.com")
            .replace("https://", "")
            .replace("http://", "")
        ),
        "captcha_static_server": (
            str(
                challenge.get("captcha_static_server")
                or "captcha-image-drru.platform.hihonorcloud.com"
            )
            .replace("https://", "")
            .replace("http://", "")
        ),
        "version": PAGE_VERSION,
    }
    return CAPTCHA_HTML.replace("__PAYLOAD__", json.dumps(payload, ensure_ascii=False))


def _bust_stale_www(hass: HomeAssistant) -> None:
    import os

    try:
        www = hass.config.path("www")
        os.makedirs(www, exist_ok=True)
        dest = os.path.join(www, "honor_robot_cleaner_captcha.html")
        with open(dest, "w", encoding="utf-8") as fh:
            fh.write(
                "<!DOCTYPE html><html><body>"
                "<p>Устаревшая страница. Открой ссылку из визарда "
                "(/api/webhook/hrc_captcha_...).</p>"
                "</body></html>"
            )
    except OSError as err:
        _LOGGER.debug("Could not overwrite stale www captcha page: %s", err)


async def _async_webhook_handler(
    hass: HomeAssistant, webhook_id: str, request: web.Request
) -> web.Response:
    """GET without validate → captcha page; with validate → advance flow."""
    sess = None
    flow_id = None
    for fid, item in list(_store(hass).items()):
        if item.get("webhook_id") == webhook_id:
            sess = item
            flow_id = fid
            break
    if not sess or not flow_id:
        return web.Response(status=404, text="Unknown captcha webhook")

    validate = None
    if request.method == "POST":
        try:
            body = await request.json()
            validate = (body or {}).get("validate")
        except Exception:  # noqa: BLE001
            validate = None
    if not validate:
        validate = request.query.get("validate")

    if not validate:
        html = _render_captcha_html(webhook_id, sess.get("challenge") or {})
        return web.Response(
            text=html,
            content_type="text/html",
            headers={
                "Cache-Control": "no-store, no-cache, must-revalidate",
                "Pragma": "no-cache",
            },
        )

    sess["validate"] = str(validate)
    try:
        await hass.config_entries.flow.async_configure(
            flow_id, {"captcha_done": True}
        )
    except Exception:  # noqa: BLE001
        _LOGGER.exception("Failed to advance config flow after captcha")
        return web.Response(
            status=500,
            text="Captcha saved but flow update failed — return to HA and retry",
        )

    return web.Response(
        text=(
            "<!DOCTYPE html><html><body>"
            "<p>Капча принята. Это окно можно закрыть — визард продолжится сам.</p>"
            "<script>try{window.close();}catch(e){}</script>"
            "</body></html>"
        ),
        content_type="text/html",
        headers={"Cache-Control": "no-store"},
    )


@callback
def async_put_captcha_session(
    hass: HomeAssistant,
    flow_id: str,
    challenge: dict[str, Any],
) -> str:
    """Store challenge, register webhook, return captcha URL."""
    async_register_captcha_views(hass)
    token = secrets.token_urlsafe(16)
    webhook_id = f"hrc_captcha_{token}"

    old = _store(hass).get(flow_id)
    if old and old.get("webhook_id"):
        try:
            webhook.async_unregister(hass, old["webhook_id"])
        except Exception:  # noqa: BLE001
            pass

    webhook.async_register(
        hass,
        DOMAIN,
        "Honor Robot Cleaner captcha",
        webhook_id,
        _async_webhook_handler,
        local_only=False,
        allowed_methods=["GET", "POST"],
    )

    _store(hass)[flow_id] = {
        "challenge": challenge,
        "validate": None,
        "token": token,
        "webhook_id": webhook_id,
        "created": time.time(),
    }
    _bust_stale_www(hass)
    return f"/api/webhook/{webhook_id}?v={PAGE_VERSION}"


@callback
def async_get_captcha_validate(hass: HomeAssistant, flow_id: str) -> str | None:
    sess = _store(hass).get(flow_id) or {}
    val = sess.get("validate")
    return str(val) if val else None


@callback
def async_set_captcha_validate(
    hass: HomeAssistant, flow_id: str, validate: str
) -> None:
    sess = _store(hass).setdefault(
        flow_id,
        {"challenge": {}, "validate": None, "token": "", "created": time.time()},
    )
    sess["validate"] = validate


@callback
def async_pop_captcha_session(hass: HomeAssistant, flow_id: str) -> None:
    sess = _store(hass).pop(flow_id, None)
    if sess and sess.get("webhook_id"):
        try:
            webhook.async_unregister(hass, sess["webhook_id"])
        except Exception:  # noqa: BLE001
            pass


CAPTCHA_HTML = """<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <meta http-equiv="Cache-Control" content="no-store"/>
  <title>Honor ID captcha</title>
  <style>
    body { font-family: system-ui, sans-serif; margin: 2rem; max-width: 36rem; background: #fff; color: #111; }
    .ok { color: #0a7; margin-top: 1rem; }
    .err { color: #c33; margin-top: 1rem; }
    .hint { color: #666; margin-top: 1rem; }
    #ne-captcha {
      margin-top: 1rem;
      min-height: 80px;
      min-width: 320px;
      border: 1px dashed #ccc;
      padding: 12px;
      background: #fafafa;
    }
    #startBtn {
      display: none;
      margin-top: 1rem;
      padding: 10px 16px;
      font-size: 16px;
      cursor: pointer;
    }
    .ver { color: #aaa; font-size: 12px; margin-top: 2rem; }
  </style>
</head>
<body>
  <h1>Honor ID</h1>
  <p>Пройди проверку ниже. После успеха визард Home Assistant продолжит сам.</p>
  <div id="ne-captcha"></div>
  <button id="startBtn" type="button">Показать капчу</button>
  <div id="msg" class="hint">Загрузка капчи…</div>
  <div class="ver" id="ver"></div>
  <script>
    const CH = __PAYLOAD__;
    document.getElementById('ver').textContent = 'captcha page ' + (CH.version || '');
    const WEBHOOK = CH.webhook || '';
    const msg = document.getElementById('msg');
    const startBtn = document.getElementById('startBtn');
    let captchaInstance = null;

    function fmtErr(err) {
      if (err == null) return 'unknown';
      if (typeof err === 'string') return err;
      if (err instanceof Error) return err.message || String(err);
      try {
        if (err.message) return String(err.message);
        if (err.msg) return String(err.msg);
        if (err.errorDesc) return String(err.errorDesc);
        return JSON.stringify(err);
      } catch (e) {
        return Object.prototype.toString.call(err);
      }
    }
    function loadScript(src) {
      return new Promise((resolve, reject) => {
        const s = document.createElement('script');
        s.src = src;
        s.onload = () => resolve();
        s.onerror = () => reject(new Error('load failed: ' + src));
        document.head.appendChild(s);
      });
    }
    function finish(validate) {
      // Avoid service-worker fetch issues: full navigation
      window.location.assign(
        '/api/webhook/' + encodeURIComponent(WEBHOOK)
        + '?validate=' + encodeURIComponent(validate)
      );
    }
    function tryVerify() {
      try {
        if (captchaInstance && typeof captchaInstance.verify === 'function') {
          captchaInstance.verify();
          return true;
        }
      } catch (e) {
        msg.className = 'err';
        msg.textContent = 'verify() failed: ' + fmtErr(e);
      }
      return false;
    }
    startBtn.addEventListener('click', function() {
      if (!tryVerify()) {
        msg.className = 'err';
        msg.textContent = 'Инстанс капчи ещё не готов, подожди секунду.';
      }
    });

    async function initWithMode(mode) {
      return new Promise(function(resolve, reject) {
        window.initNECaptcha({
          captchaId: CH.captcha_id,
          element: '#ne-captcha',
          mode: mode,
          width: '320px',
          protocol: 'https',
          apiServer: CH.captcha_server,
          staticServer: CH.captcha_static_server,
          onVerify: function(err, data) {
            if (err) {
              msg.className = 'err';
              msg.textContent = 'Капча не пройдена: ' + fmtErr(err);
              return;
            }
            const validate = data && data.validate;
            if (!validate) {
              msg.className = 'err';
              msg.textContent = 'Пустой validate';
              return;
            }
            msg.className = 'ok';
            msg.textContent = 'Принято, возвращаемся в визард…';
            finish(validate);
          }
        }, function onload(instance) {
          captchaInstance = instance;
          resolve({ mode: mode, instance: instance });
        }, function onerror(err) {
          reject(err);
        });
      });
    }

    async function main() {
      try {
        if (!CH.captcha_id) throw new Error('captcha_id missing — restart Honor login');
        if (!WEBHOOK) throw new Error('webhook missing — restart Honor login');
        const staticBase = 'https://' + CH.captcha_static_server;
        await loadScript(staticBase + '/load.min.js');
        if (!window.initNECaptcha) {
          throw new Error('initNECaptcha missing after loading ' + staticBase + '/load.min.js');
        }

        // popup often renders an invisible control; prefer visible float/embed.
        let loaded = null;
        const modes = ['float', 'embed', 'popup'];
        let lastErr = null;
        for (const mode of modes) {
          try {
            // clear previous widget remnants
            document.getElementById('ne-captcha').innerHTML = '';
            loaded = await initWithMode(mode);
            break;
          } catch (e) {
            lastErr = e;
          }
        }
        if (!loaded) throw lastErr || new Error('all captcha modes failed');

        startBtn.style.display = 'inline-block';
        msg.className = 'hint';
        msg.textContent = 'Режим: ' + loaded.mode + '. Пройди проверку в блоке выше или нажми кнопку.';
        // Auto-open for popup/float when possible
        setTimeout(tryVerify, 300);
      } catch (e) {
        msg.className = 'err';
        msg.textContent = fmtErr(e);
      }
    }
    main();
  </script>
</body>
</html>
"""
