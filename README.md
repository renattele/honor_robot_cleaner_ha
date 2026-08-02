# My HACS

<p align="center">
  Персональный репозиторий кастомных интеграций для Home Assistant<br/>
  <sub>Несколько интеграций в одном репозитории · установка через HACS или вручную</sub>
</p>

<p align="center">
  <img alt="Home Assistant" src="https://img.shields.io/badge/Home%20Assistant-2024.1%2B-41BDF5?style=flat-square&logo=home-assistant&logoColor=white"/>
  <img alt="HACS" src="https://img.shields.io/badge/HACS-Custom-0bae58?style=flat-square"/>
</p>

---

## Интеграции

| Интеграция | Domain | Описание |
|---|---|---|
| [Honor Robot Cleaner](#honor-robot-cleaner) | `honor_robot_cleaner` | Honor Choice R2 Plus через облако YuGong / Grit |

Новые интеграции добавляются каталогом в `custom_components/<domain>/`.

---

## Установка

### Все интеграции сразу (рекомендуется для этого репозитория)

```bash
cd /config
git clone https://git.lxbx.ru/renattele/my_hacs.git /tmp/my_hacs
cp -a /tmp/my_hacs/custom_components/. custom_components/
rm -rf /tmp/my_hacs
```

Перезапусти Home Assistant. Дальше — **Настройки → Устройства и службы → Добавить интеграцию**.

Обновление тем же способом (или `git pull` в клоне + снова `cp -a`).

### Через HACS (одна интеграция)

HACS умеет вести **только первую** интеграцию из `custom_components/`. Сейчас это Honor Robot Cleaner.

1. **HACS** → **Integrations** → **⋮** → **Custom repositories**
2. URL: `https://git.lxbx.ru/renattele/my_hacs`
3. Тип: **Integration** → **Add**
4. Найди **My HACS** → **Download**
5. Перезапусти Home Assistant

---

## Honor Robot Cleaner

Неофициальная интеграция **Honor Choice R2 Plus** через облако YuGong / Grit.

### Настройка

Вход через **Honor ID** (телефон → капча → SMS). JWT обновляется автоматически (silent Honor SSO + keepalive каждые 4 часа). Если сессия Honor истекла — HA попросит войти снова.

Device ID при необходимости: AI Space → сведения об устройстве.

### Возможности

- Управление уборкой и возврат на базу
- Live-карта по WSS
- Уборка по комнатам
- Fan / water / volume / DND
- Расходники и кнопки перемещения

---

## Добавление новой интеграции

1. Создай `custom_components/<domain>/` с `manifest.json`, `__init__.py`, platforms.
2. Добавь строку в таблицу **Интеграции** выше и секцию с настройкой.
3. Для установки пакета целиком по-прежнему используй clone + `cp` — так подтянутся все domain-каталоги.

---

<p align="center">
  <sub>Unofficial custom components · not affiliated with Honor or Home Assistant</sub>
</p>
