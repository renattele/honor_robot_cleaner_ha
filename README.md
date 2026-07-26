# Honor Robot Cleaner (Home Assistant)

Cloud integration for **Honor Choice** robot vacuums (R2 Plus / `DPIZ` / `rob-01`) via the YuGong / Grit API used by Honor AI Space (`yxseeper` plugin).

> Not local. Commands go through `https://honour.grit-cloud.com/prod/` (or `.cn` for China).

## Install

1. Copy `custom_components/honor_robot_cleaner` into your HA `config/custom_components/`.
2. Restart Home Assistant.
3. **Settings → Devices & services → Add integration → Honor Robot Cleaner**.

Or add this repository in HACS as a custom integration.

## Sign-in

### Recommended: phone + password

1. Choose **Sign in with phone / password**.
2. Enter phone **without** country code (Russia: `9XXXXXXXXX`), password, country calling code (`007` for +7).
3. Pick the robot if several are on the account.

Credentials are stored in the config entry. The integration **re-logs in automatically** when the JWT is about to expire (~every 24h).

If you only ever used Honor AI Space and never set a RobotCleaner/Grit password, set one in the **Robot Sweeper** app (same cloud) or use the token mode below.

### Advanced: paste token

Paste JWT or the full `plugin_account.xml` string from a rooted phone:

```text
/data/data/com.hihonor.magichome/shared_prefs/plugin_account.xml
```

Token mode does **not** auto-refresh; update it in **Configure** when it expires.

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
