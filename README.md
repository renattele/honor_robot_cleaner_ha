# Honor Robot Cleaner (Home Assistant)

Cloud integration for **Honor Choice** robot vacuums (R2 Plus / `DPIZ` / `rob-01`) via the YuGong / Grit API used by Honor AI Space (`yxseeper` plugin).

> Not local. Commands go through `https://honour.grit-cloud.com/prod/`.

## Install

1. Copy `custom_components/honor_robot_cleaner` into your HA `config/custom_components/`.
2. Restart Home Assistant.
3. **Settings → Devices & services → Add integration → Honor Robot Cleaner**.

Or with HACS (custom repository): add this git URL as an integration repository.

## Credentials

On a rooted phone with Honor AI Space logged in:

```text
/data/data/com.hihonor.magichome/shared_prefs/plugin_account.xml
```

Field `token` looks like:

```text
<device_id>;<JWT>;<region>;<lang>;<expiry_ms>;https://honour.grit-cloud.com/prod/;wss://...
```

Paste either:

- the **full** string (device id / region / base URL are parsed automatically), or
- JWT only + Device ID manually.

JWT lifetime is roughly **24 hours**. Refresh via **Configure** on the integration (options flow), or re-run your token pull script and paste again.

Example helper (adb + root):

```bash
adb shell 'su -c "grep token /data/data/com.hihonor.magichome/shared_prefs/plugin_account.xml"'
```

## Entities

| Entity | Notes |
|--------|--------|
| `vacuum.*` | start / pause / stop / return to dock / fan speed |
| `sensor.*_battery` | battery % |
| `sensor.*_working_status` | raw cloud status (`AutoClean`, `Pause`, …) |
| `sensor.*_clean_area` | m² |
| `sensor.*_clean_time` | minutes |

## Defaults

| Key | Default |
|-----|---------|
| region | `eu-central-1` |
| base_url | `https://honour.grit-cloud.com/prod/` |
| sub_type | `rob-01` |

China deployments may need `https://honour.grit-cloud.cn/prod/`.

## Disclaimer

Unofficial reverse‑engineered cloud API. May break when Honor/Grit change backends. Do not share your JWT.
