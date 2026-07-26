# Honor Robot Cleaner

<p align="center">
  <img src="images/logo.png" alt="Logo" width="112"/>
</p>

<p align="center">
  <strong>Honor Choice R2 Plus</strong> → Home Assistant<br/>
  <sub>Неофициальная интеграция через облако YuGong / Grit</sub>
</p>

<p align="center">
  <img alt="Home Assistant" src="https://img.shields.io/badge/Home%20Assistant-2024.1%2B-41BDF5?style=flat-square&logo=home-assistant&logoColor=white"/>
  <img alt="HACS" src="https://img.shields.io/badge/HACS-Custom-0bae58?style=flat-square"/>
  <img alt="Cloud" src="https://img.shields.io/badge/IoT-Cloud-6c757d?style=flat-square"/>
</p>

---

### Установка

1. **HACS** → Custom repositories → этот репо → *Integration*
2. Установить → перезапустить Home Assistant
3. **Настройки → Устройства и службы → Добавить интеграцию**

<details>
<summary>Вручную</summary>

```text
config/custom_components/honor_robot_cleaner/
```

</details>

### Настройка

Вход через **Honor ID** (телефон → капча → SMS). JWT обновляется автоматически.

Device ID при необходимости: AI Space → сведения об устройстве.

### Возможности

- Управление уборкой и возврат на базу  
- Live-карта по WSS  
- Уборка по комнатам  
- Fan / water / volume / DND  
- Расходники и кнопки перемещения  

---

<p align="center">
  <sub>Unofficial · not affiliated with Honor</sub>
</p>
