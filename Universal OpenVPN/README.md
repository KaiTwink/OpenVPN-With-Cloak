# OpenVPN Ordinary Manager

Обычный OpenVPN-проект без лицензий и без веб-панели.

Что входит:
- интерактивный установщик OpenVPN под Ubuntu 20.04+
- SQLite база
- CLI-меню управления ключами
- Telegram-бот для удаленного управления
- systemd-сервисы для OpenVPN, бота и авто-блокировки истекших ключей

## Что спрашивает установщик
Минимально:
- домен или IP OpenVPN-сервера
- основной протокол (`udp` или `tcp`)
- основной порт
- токен Telegram-бота (можно пустым)
- Telegram admin IDs через запятую
- Telegram chat ID для уведомлений/бэкапов (можно пустым)

## Установка
```bash
cd installer
sudo bash install.sh
```

После установки:
- меню: `ovpnmenu`
- запуск бота вручную: `ovpnbot`
- БД: `/etc/ovpnmgr/openvpn.db`
- серверный конфиг: `/etc/openvpn/server/server.conf`
- клиентские профили: `/root/OpenVPNKeys`
- рабочая директория проекта: `/opt/ovpnmgr`

## Замечания
- OpenVPN ставится из пакетов Ubuntu (`openvpn`, `easy-rsa`), а не через сторонние патчи.
- Используются `data-ciphers`, а `compress` не включается, поскольку это не рекомендуется в OpenVPN 2.6.
- У Ubuntu официальная инструкция по установке OpenVPN рекомендует пакеты `openvpn` и `easy-rsa`.
