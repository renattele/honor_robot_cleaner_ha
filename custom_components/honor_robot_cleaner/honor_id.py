"""Honor ID (CAS / OAuth) client for AI Space → Grit auth_code.

Flow (yxseeper / MagicHome client_id=221000090):
  1) OAuth authorize → CAS wapLogin session (page-token)
  2) YiDun captcha (type 3) via chkPreprocessV2
  3) remoteLogin(userAccount, password, captcha) → possibly SMS 2FA
  4) Follow callbackURL → honorid://redirect_url?code=...
  5) Caller exchanges code with Grit honor_card_login
"""

from __future__ import annotations

import asyncio
import http.client
import http.cookiejar
import json
import logging
import random
import re
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from html import unescape
from typing import Any

_LOGGER = logging.getLogger(__name__)

HONOR_OAUTH_CLIENT_ID = "221000090"
HONOR_REDIRECT_URI = "honorid://redirect_url"
DEFAULT_OAUTH_HOST = "https://hnoauth-login-drru.cloud.honor.com"
DEFAULT_CAS_HOST = "https://hnid-drru.cloud.honor.com"
REQ_CLIENT_TYPE = "90"
LOGIN_CHANNEL = "90000300"

# CAS ajax bases (order matters for some ops)
AJAX_CAS = "/CAS/ajaxHandler/"
AJAX_IDMW = "/CAS/IDM_W/ajaxHandler/"

UA = (
    "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36"
)


class HonorIdError(Exception):
    """Honor ID / CAS failure."""

    def __init__(
        self,
        message: str,
        *,
        error_code: str | None = None,
        data: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.data = data or {}


@dataclass
class CaptchaChallenge:
    captcha_type: int
    captcha_trans_no: str
    captcha_id: str = ""
    captcha_server: str = ""
    captcha_static_server: str = ""
    need_image_code: bool = False
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class HonorLoginResult:
    auth_code: str
    callback_url: str = ""
    page_token: str = ""
    raw: dict[str, Any] = field(default_factory=dict)


def normalize_ru_phone(account: str) -> str:
    """National mobile digits for RU-style numbers (drop leading 8)."""
    digits = re.sub(r"\D", "", account or "")
    if digits.startswith("8") and len(digits) == 11:
        return digits[1:]
    if digits.startswith("7") and len(digits) == 11:
        return digits[1:]
    return digits


def mobile_phone_e164_honor(account: str, calling_code: str) -> str:
    """Honor SMS login mobilePhone: calling_code (00x) + national number."""
    cc = (calling_code or "007").strip()
    if cc.startswith("+"):
        cc = "00" + cc[1:]
    if not cc.startswith("00"):
        cc = "00" + cc.lstrip("0")
    national = normalize_ru_phone(account)
    return f"{cc}{national}"


class HonorIdClient:
    """Cookie + page-token session against Honor CAS (RU site by default)."""

    def __init__(
        self,
        *,
        oauth_host: str = DEFAULT_OAUTH_HOST,
        cas_host: str = DEFAULT_CAS_HOST,
        lang: str = "ru-ru",
        country_code: str = "ru",
        timeout: float = 25.0,
    ) -> None:
        self.oauth_host = oauth_host.rstrip("/")
        self.cas_host = cas_host.rstrip("/")
        self.lang = lang
        self.country_code = country_code
        self.timeout = timeout
        self._cj = http.cookiejar.CookieJar()
        self._opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self._cj)
        )
        self.page_token = ""
        self.service = ""
        self.login_url = ""
        self.req_client_type = REQ_CLIENT_TYPE
        self.login_channel = LOGIN_CHANNEL
        self._referer = f"{self.cas_host}/CAS/mobile/standard/wapLogin.html"
        self.last_captcha: CaptchaChallenge | None = None
        self._password = ""
        self._user_account = ""
        self._pending_login: dict[str, Any] = {}

    # --- HTTP helpers -------------------------------------------------

    def _request(
        self,
        url: str,
        *,
        data: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        method: str | None = None,
        allow_redirects: bool = True,
    ) -> tuple[str, int, str]:
        hdr = {
            "User-Agent": UA,
            "Accept": "*/*",
        }
        if headers:
            hdr.update(headers)
        body = None
        if data is not None:
            body = urllib.parse.urlencode(
                {k: v for k, v in data.items() if v is not None}
            ).encode("utf-8")
            hdr.setdefault(
                "Content-Type",
                "application/x-www-form-urlencoded;charset=UTF-8",
            )
            method = method or "POST"
        req = urllib.request.Request(url, data=body, headers=hdr, method=method)
        try:
            if allow_redirects:
                with self._opener.open(req, timeout=self.timeout) as resp:
                    raw = resp.read().decode("utf-8", errors="replace")
                    return resp.geturl(), resp.status, raw
            # Manual redirect handling for honorid:// intercept
            conn_headers = {k: v for k, v in hdr.items()}
            parsed = urllib.parse.urlparse(url)
            if parsed.scheme != "https":
                raise HonorIdError(f"Unsupported scheme {parsed.scheme}")
            context = ssl.create_default_context()
            path = parsed.path or "/"
            if parsed.query:
                path = f"{path}?{parsed.query}"
            conn = http.client.HTTPSConnection(
                parsed.hostname,
                parsed.port or 443,
                timeout=self.timeout,
                context=context,
            )
            try:
                cookie = self._cookie_header(parsed.hostname or "")
                if cookie:
                    conn_headers["Cookie"] = cookie
                conn.request(method or "GET", path, body=body, headers=conn_headers)
                resp = conn.getresponse()
                raw = resp.read().decode("utf-8", errors="replace")
                self._store_cookies(parsed.hostname or "", resp.getheaders())
                loc = resp.getheader("Location") or ""
                final = urllib.parse.urljoin(url, loc) if loc else url
                return final, resp.status, raw
            finally:
                conn.close()
        except urllib.error.HTTPError as err:
            raw = err.read().decode("utf-8", errors="replace")
            loc = err.headers.get("Location") if err.headers else ""
            final = urllib.parse.urljoin(url, loc) if loc else url
            return final, err.code, raw
        except OSError as err:
            raise HonorIdError(f"Network error: {err}") from err

    def _cookie_header(self, host: str) -> str:
        parts = []
        for c in self._cj:
            if c.domain and host.endswith(c.domain.lstrip(".")):
                parts.append(f"{c.name}={c.value}")
            elif not c.domain:
                parts.append(f"{c.name}={c.value}")
        return "; ".join(parts)

    def _store_cookies(self, host: str, headers: list[tuple[str, str]]) -> None:
        # Best-effort: urllib cookie jar already handles opener path;
        # manual path only used for honorid intercept.
        for name, value in headers:
            if name.lower() != "set-cookie":
                continue
            # Minimal parse: name=value; ...
            try:
                first = value.split(";", 1)[0]
                cname, cval = first.split("=", 1)
                self._cj.set_cookie(
                    http.cookiejar.Cookie(
                        version=0,
                        name=cname.strip(),
                        value=cval.strip(),
                        port=None,
                        port_specified=False,
                        domain=host,
                        domain_specified=True,
                        domain_initial_dot=False,
                        path="/",
                        path_specified=True,
                        secure=True,
                        expires=None,
                        discard=True,
                        comment=None,
                        comment_url=None,
                        rest={},
                        rfc2109=False,
                    )
                )
            except Exception:  # noqa: BLE001
                continue

    def _ajax(
        self,
        base_path: str,
        operation: str,
        data: dict[str, Any],
    ) -> dict[str, Any]:
        url = (
            f"{self.cas_host}{base_path}{operation}"
            f"?reflushCode={random.random()}"
        )
        payload = dict(data)
        payload.setdefault("languageCode", self.lang)
        hdr = {
            "page-token": self.page_token,
            "Page-Token": self.page_token,
            "Origin": self.cas_host,
            "Referer": self._referer,
            "X-Requested-With": "XMLHttpRequest",
            "Accept": "application/json, text/plain, */*",
        }
        _, status, raw = self._request(url, data=payload, headers=hdr)
        if status >= 400:
            raise HonorIdError(f"HTTP {status}: {raw[:200]}")
        try:
            return json.loads(raw)
        except json.JSONDecodeError as err:
            raise HonorIdError(f"Invalid JSON from {operation}: {raw[:200]}") from err

    # --- Bootstrap ----------------------------------------------------

    def bootstrap(self) -> None:
        """Open OAuth authorize → CAS wapLogin and capture pageToken/service."""
        auth = (
            f"{self.oauth_host}/oauth2/v3/authorize?"
            + urllib.parse.urlencode(
                {
                    "response_type": "code",
                    "client_id": HONOR_OAUTH_CLIENT_ID,
                    "redirect_uri": HONOR_REDIRECT_URI,
                    "scope": "openid profile",
                    "state": "getAuthCode",
                    "display": "wap",
                    "lang": self.lang,
                    "prompt": "login",
                    "access_type": "offline",
                    "include_granted_scopes": "true",
                    "nonce": "default",
                }
            )
        )
        _, _, body = self._request(auth)
        m = re.search(
            r"(https://hnid[^\"'\s]+remoteLogin[^\"'\s]*)",
            body,
        ) or re.search(r"(https://[^\"'\s]+/CAS/remoteLogin[^\"'\s]*)", body)
        if not m:
            raise HonorIdError("OAuth page did not redirect to CAS remoteLogin")
        remote = unescape(m.group(1))
        qs = urllib.parse.parse_qs(urllib.parse.urlparse(remote).query)
        service = qs.get("service", [""])[0]
        if not service:
            raise HonorIdError("CAS remoteLogin missing service=")
        self._request(remote)

        wap = (
            f"{self.cas_host}/CAS/mobile/standard/wapLogin.html?"
            + urllib.parse.urlencode(
                {
                    "reqClientType": qs.get("reqClientType", [REQ_CLIENT_TYPE])[0],
                    "loginChannel": qs.get("loginChannel", [LOGIN_CHANNEL])[0],
                    "countryCode": self.country_code,
                    "loginUrl": qs.get(
                        "loginUrl",
                        [f"{self.cas_host}/CAS/mobile/standard/welcome.html"],
                    )[0],
                    "service": service,
                    "lang": self.lang,
                    "themeName": "blue",
                    "clientID": HONOR_OAUTH_CLIENT_ID,
                    "validated": "true",
                }
            )
        )
        final, _, html = self._request(wap)
        self._referer = final
        pt = re.search(r'pageToken\s*=\s*"([^"]+)"', html)
        if not pt:
            raise HonorIdError("wapLogin HTML missing pageToken")
        self.page_token = pt.group(1)

        cfg = self._parse_hnid_config(html)
        self.service = cfg.get("service") or service
        self.login_url = cfg.get("loginUrl") or wap.split("?", 1)[0]
        self.req_client_type = str(cfg.get("reqClientType") or REQ_CLIENT_TYPE)
        self.login_channel = str(cfg.get("loginChannel") or LOGIN_CHANNEL)
        _LOGGER.debug(
            "Honor CAS ready pageToken=%s… service=%s",
            self.page_token[:12],
            self.service[:60],
        )

    @staticmethod
    def _parse_hnid_config(html: str) -> dict[str, str]:
        m = re.search(r"var hnidConfigString = '([^']*)'", html)
        if not m:
            return {}
        s = unescape(m.group(1))
        for _ in range(5):
            s2 = unescape(s)
            if s2 == s:
                break
            s = s2
        out: dict[str, str] = {}
        for key in (
            "service",
            "loginUrl",
            "reqClientType",
            "loginChannel",
            "clientID",
            "countryCode",
            "lang",
        ):
            mm = re.search(rf'"{key}"\s*:\s*"([^"]*)"', s)
            if mm:
                out[key] = unescape(mm.group(1))
        return out

    # --- Captcha ------------------------------------------------------

    def prepare_captcha(self, operation: str = "remoteLogin") -> CaptchaChallenge:
        """Ask CAS which captcha is required before ``operation``."""
        if not self.page_token:
            self.bootstrap()
        resp = self._ajax(
            AJAX_CAS,
            "chkPreprocessV2",
            {
                "reqClientType": "cas",
                "operation": operation,
                "operType": operation,
            },
        )
        if str(resp.get("isSuccess")) not in ("1", "true", "True"):
            raise HonorIdError(
                resp.get("errorDesc") or "chkPreprocessV2 failed",
                error_code=str(resp.get("errorCode") or ""),
                data=resp,
            )
        challenge = CaptchaChallenge(
            captcha_type=int(resp.get("captchaType") if resp.get("captchaType") is not None else -1),
            captcha_trans_no=str(resp.get("captchaTransNo") or ""),
            captcha_id=str(resp.get("captchaId") or ""),
            captcha_server=str(resp.get("captchaServer") or resp.get("captchaHost") or ""),
            captcha_static_server=str(resp.get("captchaStaticServer") or ""),
            need_image_code=str(resp.get("needImageCode")) == "1",
            raw=resp,
        )
        self.last_captcha = challenge
        return challenge

    # --- Login --------------------------------------------------------

    def login_password(
        self,
        user_account: str,
        password: str,
        *,
        captcha_validate: str | None = None,
        captcha_trans_no: str | None = None,
        two_step_verify_code: str | None = None,
        verify_user_account: str | None = None,
        verify_account_type: str | int | None = None,
        op_type: int | None = None,
    ) -> dict[str, Any]:
        """Password login (and optional SMS 2FA fields)."""
        if not self.page_token:
            self.bootstrap()
        self._user_account = user_account.strip()
        self._password = password
        data: dict[str, Any] = {
            "loginUrl": self.login_url,
            "service": self.service,
            "loginChannel": self.login_channel,
            "reqClientType": self.req_client_type,
            "lang": self.lang,
            "userAccount": self._user_account,
            "password": password,
            "remember_name": "off",
        }
        trans = captcha_trans_no or (
            self.last_captcha.captcha_trans_no if self.last_captcha else ""
        )
        if trans:
            data["captchaTransNo"] = trans
        if captcha_validate:
            data["randomCode"] = captcha_validate
            data["authcode"] = captcha_validate
        if two_step_verify_code:
            data["twoStepVerifyCode"] = two_step_verify_code
            if verify_user_account:
                data["verifyUserAccount"] = verify_user_account
            if verify_account_type is not None:
                data["verifyAccountType"] = str(verify_account_type)
            data["opType"] = op_type if op_type is not None else 6
        elif op_type is not None:
            data["opType"] = op_type

        resp = self._ajax(AJAX_IDMW, "remoteLogin", data)
        self._pending_login = resp
        return resp

    def request_sms_code(
        self,
        user_account: str,
        *,
        calling_code: str = "007",
        captcha_validate: str | None = None,
        captcha_trans_no: str | None = None,
        oper_type: str = "17",
        sms_req_type: str = "2",
    ) -> dict[str, Any]:
        """Request SMS for password 2FA / SMS login (operType 17 needs captcha)."""
        if not self.page_token:
            self.bootstrap()
        data: dict[str, Any] = {
            "userAccount": user_account.strip(),
            "reqClientType": self.req_client_type,
            "loginChannel": self.login_channel,
            "operType": oper_type,
            "smsReqType": sms_req_type,
            "service": self.service,
            "session_code_key": "sms_login_session_ramdom_code_key",
        }
        trans = captcha_trans_no or (
            self.last_captcha.captcha_trans_no if self.last_captcha else ""
        )
        if trans:
            data["captchaTransNo"] = trans
        if captcha_validate:
            data["randomCode"] = captcha_validate
            data["authcode"] = captcha_validate
        return self._ajax(AJAX_IDMW, "getSMSAuthCode", data)

    def login_sms(
        self,
        user_account: str,
        sms_code: str,
        *,
        calling_code: str = "007",
        captcha_validate: str | None = None,
        captcha_trans_no: str | None = None,
    ) -> dict[str, Any]:
        """SMS-only login (loginBySMS)."""
        if not self.page_token:
            self.bootstrap()
        data: dict[str, Any] = {
            "mobilePhone": mobile_phone_e164_honor(user_account, calling_code),
            "smsAuthCode": sms_code.strip(),
            "loginUrl": self.login_url,
            "service": self.service,
            "loginChannel": self.login_channel,
            "reqClientType": self.req_client_type,
            "lang": self.lang,
            "operType": "18",
        }
        trans = captcha_trans_no or (
            self.last_captcha.captcha_trans_no if self.last_captcha else ""
        )
        if trans:
            data["captchaTransNo"] = trans
        if captcha_validate:
            data["randomCode"] = captcha_validate
            data["authcode"] = captcha_validate
        return self._ajax(AJAX_IDMW, "loginBySMS", data)

    def extract_auth_code(self, login_resp: dict[str, Any]) -> HonorLoginResult:
        """Follow CAS callbackURL until honorid://…?code=."""
        if str(login_resp.get("isSuccess")) not in ("1", "true", "True"):
            raise HonorIdError(
                login_resp.get("errorDesc") or "Login failed",
                error_code=str(login_resp.get("errorCode") or ""),
                data=login_resp,
            )
        if login_resp.get("pageToken"):
            self.page_token = str(login_resp["pageToken"])
        callback = str(login_resp.get("callbackURL") or login_resp.get("callbackUrl") or "")
        if not callback:
            raise HonorIdError("Login OK but no callbackURL", data=login_resp)
        code = self._follow_for_oauth_code(callback)
        return HonorLoginResult(
            auth_code=code,
            callback_url=callback,
            page_token=self.page_token,
            raw=login_resp,
        )

    def _follow_for_oauth_code(self, url: str, *, max_hops: int = 12) -> str:
        current = url
        for _ in range(max_hops):
            if current.startswith("honorid://") or "code=" in current:
                parsed = urllib.parse.urlparse(current)
                qs = urllib.parse.parse_qs(parsed.query)
                # also support fragment
                if not qs and parsed.fragment:
                    qs = urllib.parse.parse_qs(parsed.fragment)
                code = (qs.get("code") or [None])[0]
                if code:
                    return code
            if current.startswith("honorid://"):
                break
            # Prefer not auto-following to custom scheme via urllib
            final, status, body = self._request(
                current, allow_redirects=False, headers={"Referer": self._referer}
            )
            if 300 <= status < 400 and final and final != current:
                current = final
                continue
            # HTML/JS redirect
            m = re.search(
                r"""(?:location\.href|window\.location)\s*=\s*["']([^"']+)""",
                body,
            )
            if m:
                current = urllib.parse.urljoin(current, unescape(m.group(1)))
                continue
            m = re.search(
                r"""honorid://[^"'<\s]+""",
                body,
            )
            if m:
                current = unescape(m.group(0))
                continue
            m = re.search(r"""[?&]code=([A-Za-z0-9._\-~]+)""", body)
            if m:
                return m.group(1)
            # Landed on login UI → session not authenticated
            if any(
                x in current or x in body
                for x in ("wapLogin", "welcome.html", "remoteLogin", "ifmLogin")
            ):
                raise HonorIdError(
                    "Honor login required (session missing/expired)",
                    data={"url": current, "body": body[:300]},
                )
            raise HonorIdError(
                f"Could not extract OAuth code (HTTP {status})",
                data={"url": current, "body": body[:300]},
            )
        raise HonorIdError("OAuth code not found in redirect chain")

    def needs_sms_verification(self, resp: dict[str, Any]) -> bool:
        """Heuristic: password accepted but SMS / 2FA required."""
        code = str(resp.get("errorCode") or "")
        if code in {
            "70002402",
            "10000707",
            "70001203",
            "70001206",
        }:
            return True
        desc = str(resp.get("errorDesc") or "")
        if "twoFactor" in desc or "DoubleVerification" in desc:
            return True
        # Some responses put lists on success-ish payloads
        if resp.get("twoFactorList") or resp.get("verifyAccountList"):
            return True
        # isSuccess=0 with auth dialog hints
        try:
            ed = resp.get("errorDesc")
            if isinstance(ed, str) and ed.strip().startswith("{"):
                parsed = json.loads(ed)
                if parsed.get("twoFactorList") or parsed.get("isDoubleVerification"):
                    return True
        except Exception:  # noqa: BLE001
            pass
        return False

    def parse_verify_targets(self, resp: dict[str, Any]) -> list[dict[str, Any]]:
        """Extract SMS verification targets from a 2FA challenge response."""
        candidates: list[Any] = []
        for key in ("verifyAccountList", "twoFactorList", "authCodeSentList"):
            val = resp.get(key)
            if val:
                candidates = list(val) if isinstance(val, list) else []
                break
        if not candidates:
            try:
                ed = resp.get("errorDesc")
                if isinstance(ed, str) and ed.strip().startswith("{"):
                    parsed = json.loads(ed)
                    for key in ("verifyAccountList", "twoFactorList"):
                        if parsed.get(key):
                            candidates = list(parsed[key])
                            break
            except Exception:  # noqa: BLE001
                pass
        out: list[dict[str, Any]] = []
        for item in candidates:
            if isinstance(item, dict):
                out.append(item)
        return out

    # --- Session persistence / silent refresh -------------------------

    def export_session(self) -> dict[str, Any]:
        """Serialize cookies + hosts for HA config-entry storage."""
        cookies: list[dict[str, Any]] = []
        for c in self._cj:
            cookies.append(
                {
                    "name": c.name,
                    "value": c.value,
                    "domain": c.domain,
                    "path": c.path or "/",
                    "secure": bool(c.secure),
                    "expires": c.expires,
                }
            )
        return {
            "oauth_host": self.oauth_host,
            "cas_host": self.cas_host,
            "lang": self.lang,
            "country_code": self.country_code,
            "cookies": cookies,
            "exported_at": time.time(),
        }

    def import_session(self, data: dict[str, Any] | None) -> None:
        """Restore a previously exported Honor CAS/OAuth session."""
        if not data:
            return
        self.oauth_host = str(data.get("oauth_host") or self.oauth_host).rstrip("/")
        self.cas_host = str(data.get("cas_host") or self.cas_host).rstrip("/")
        self.lang = str(data.get("lang") or self.lang)
        self.country_code = str(data.get("country_code") or self.country_code)
        self._cj = http.cookiejar.CookieJar()
        self._opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self._cj)
        )
        for item in data.get("cookies") or []:
            try:
                domain = str(item.get("domain") or "")
                cookie = http.cookiejar.Cookie(
                    version=0,
                    name=str(item["name"]),
                    value=str(item["value"]),
                    port=None,
                    port_specified=False,
                    domain=domain,
                    domain_specified=bool(domain),
                    domain_initial_dot=domain.startswith("."),
                    path=str(item.get("path") or "/"),
                    path_specified=True,
                    secure=bool(item.get("secure")),
                    expires=item.get("expires"),
                    discard=item.get("expires") is None,
                    comment=None,
                    comment_url=None,
                    rest={},
                    rfc2109=False,
                )
                self._cj.set_cookie(cookie)
            except Exception:  # noqa: BLE001
                continue

    def _authorize_url(self, *, prompt: str | None) -> str:
        params = {
            "response_type": "code",
            "client_id": HONOR_OAUTH_CLIENT_ID,
            "redirect_uri": HONOR_REDIRECT_URI,
            "scope": "openid profile",
            "state": "getAuthCode",
            "display": "wap",
            "lang": self.lang,
            "access_type": "offline",
            "include_granted_scopes": "true",
            "nonce": f"ha-{int(time.time())}",
        }
        if prompt:
            params["prompt"] = prompt
        return f"{self.oauth_host}/oauth2/v3/authorize?{urllib.parse.urlencode(params)}"

    def silent_get_auth_code(self) -> str:
        """Obtain a fresh OAuth auth_code using stored SSO cookies (no password/SMS)."""
        if not list(self._cj):
            raise HonorIdError("No Honor session cookies stored")

        last_err: HonorIdError | None = None
        # Prefer silent SSO; fall back to cookie-based authorize without prompt=login.
        for prompt in ("none", None):
            url = self._authorize_url(prompt=prompt)
            try:
                return self._follow_for_oauth_code(url, max_hops=16)
            except HonorIdError as err:
                last_err = err
                continue
        raise HonorIdError(
            "Honor session expired — reconfigure the integration "
            "(phone + password + SMS once)",
            data=(last_err.data if last_err else None),
        )

    def refresh_auth_code(self) -> tuple[str, dict[str, Any]]:
        """Silent auth_code + updated session blob for persistence."""
        code = self.silent_get_auth_code()
        return code, self.export_session()


async def async_bootstrap_client(**kwargs: Any) -> HonorIdClient:
    client = HonorIdClient(**kwargs)
    await asyncio.to_thread(client.bootstrap)
    return client
