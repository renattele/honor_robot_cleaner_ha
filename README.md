# Honor Robot Cleaner

<p align="center">
  <img src="images/logo.png" alt="Logo" width="96"/>
</p>

Неофициальная интеграция Home Assistant для роботов-пылесосов **Honor Choice** (R2 Plus) через облако YuGong / Grit.

## Установка

HACS → Custom repositories → этот репозиторий (Integration) → установить → перезапустить HA → **Добавить интеграцию**.

Или скопировать `custom_components/honor_robot_cleaner` в `/config/custom_components/`.

## Настройка

Рекомендуется вход через **Honor ID** (телефон + капча + SMS). JWT обновляется сам.

При необходимости Device ID берётся в AI Space → сведения об устройстве.

## Возможности

Vacuum, live-карта (WSS), уборка по комнатам, fan / water / volume / DND, расходники, кнопки перемещения.

Unofficial. Not affiliated with Honor.
