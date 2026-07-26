# Honor Robot Cleaner (Home Assistant)

Cloud integration for **Honor Choice** robot vacuums (R2 Plus / `DPIZ` / `rob-01`) via the YuGong / Grit API used by Honor AI Space (`yxseeper` plugin).

> Not local. Commands go through `https://honour.grit-cloud.com/prod/` (or `.cn` for China).

## Install

1. Copy `custom_components/honor_robot_cleaner` into your HA `config/custom_components/`.
2. Restart Home Assistant.
3. **Settings → Devices & services → Add integration → Honor Robot Cleaner**.

Or add this repository in HACS as a custom integration.

## Sign-in

### Honor AI Space (phone + password + SMS) — recommended

Same flow as Honor ID in AI Space:

1. Enter Honor phone and password
2. Open the captcha link in a browser (logged into HA), solve YiDun captcha
3. Enter the SMS code from your phone
4. Integration exchanges Honor OAuth `code` → Grit `honor_card_login` → discovers `thing_name` from the device list → JWT

Grit JWT lasts ~24h. After Honor AI Space setup, HA stores Honor SSO cookies and **refreshes the JWT automatically** (silent OAuth → `honor_card_login`) — no phone required. If the Honor session itself expires, re-run the Honor login flow once.

### Paste cloud token (advanced)

Paste a JWT or full `plugin_account` token string. **No auto-refresh** in this mode — prefer Honor AI Space login.

### YuGong password (RobotCleaner account only)

Separate from Honor ID. Honor-only accounts get `UserNotExist`.

## Entities

| Entity | Notes |
|--------|--------|
| `vacuum.*` | start / pause / stop / return to dock / fan speed |
| `sensor.*_battery` | battery % |
| `sensor.*_working_status` | raw cloud status |
| `sensor.*_clean_area` | m² |
| `sensor.*_clean_time` | minutes |

## Defaults

| Key | Default |
|-----|---------|
| calling_code | `007` (+7) |
| region | from login / `eu-central-1` |
| base_url | `https://honour.grit-cloud.com/prod/` |
| sub_type | `rob-01` (from device list) |

## Disclaimer

Unofficial reverse‑engineered cloud API. May break when Honor/Grit change backends. Do not share passwords or JWTs.
