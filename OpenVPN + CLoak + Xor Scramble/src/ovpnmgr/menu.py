from __future__ import annotations

import os

from .openvpn import (
    add_remote,
    allowed_bot_users,
    backup_all,
    block_client,
    connected_clients,
    create_client,
    current_remotes,
    delete_client,
    delete_remote,
    extend_client,
    list_clients,
    recreate_client,
    restart_openvpn,
    service_status_text,
    set_primary_remote,
    set_telegram_settings,
    start_openvpn,
    stop_openvpn,
    summary_text,
    telegram_settings,
    unblock_client,
)
from .utils import ensure_root

RESET = "\033[0m"
CYAN = "\033[96m"
GREEN = "\033[92m"
RED = "\033[91m"
BOLD = "\033[1m"


def clear() -> None:
    os.system("clear")


def pause() -> None:
    input("\nНажмите Enter для продолжения...")


def print_header(title: str) -> None:
    clear()
    print(f"{CYAN}{'=' * 72}{RESET}")
    print(f"{BOLD}{title.center(72)}{RESET}")
    print(f"{CYAN}{'=' * 72}{RESET}\n")


def _ask_int(prompt: str, default: int | None = None) -> int:
    while True:
        raw = input(prompt).strip()
        if not raw and default is not None:
            return default
        if raw.isdigit():
            return int(raw)
        print("Введите число.")


def menu_list_clients() -> None:
    print_header("Список ключей")
    clients = list_clients()
    if not clients:
        print("Клиентов пока нет.")
        pause()
        return
    print(f"{'#':<4}{'Имя':<20}{'Статус':<12}{'Дней':<8}{'Трафик':<14}{'Online':<8}")
    print("-" * 72)
    for idx, c in enumerate(clients, start=1):
        status = "Активен" if c["active"] else "Блок"
        online = "Да" if c["connected"] else "Нет"
        days = c["days_left"] if c["days_left"] is not None else "—"
        print(f"{idx:<4}{c['key_name']:<20}{status:<12}{str(days):<8}{c['traffic_human']:<14}{online:<8}")
    pause()


def menu_create_client() -> None:
    print_header("Создание ключа")
    name = input("Имя ключа: ").strip()
    days = _ask_int("Срок в днях [30]: ", 30)
    try:
        result = create_client(name, days)
        print(f"\n{GREEN}Готово:{RESET} {result['key_name']}")
        print(f"Профиль: {result['profile_path']}")
        print(f"Истекает: {result['expiration_date']}")
    except Exception as exc:
        print(f"{RED}Ошибка:{RESET} {exc}")
    pause()


def _choose_client_name() -> str | None:
    clients = list_clients(raw=True)
    if not clients:
        print("Клиентов нет.")
        pause()
        return None
    for idx, c in enumerate(clients, start=1):
        print(f"{idx}. {c['key_name']} ({c['cert_cn']})")
    num = _ask_int("Выберите номер: ")
    if 1 <= num <= len(clients):
        return clients[num - 1]["key_name"]
    print("Неверный номер.")
    pause()
    return None


def menu_delete_client() -> None:
    print_header("Удаление ключа")
    name = _choose_client_name()
    if not name:
        return
    confirm = input(f"Удалить '{name}'? (yes/NO): ").strip().lower()
    if confirm != "yes":
        return
    try:
        delete_client(name)
        print(f"{GREEN}Клиент удален.{RESET}")
    except Exception as exc:
        print(f"{RED}Ошибка:{RESET} {exc}")
    pause()


def menu_recreate_client() -> None:
    print_header("Пересоздание ключа")
    name = _choose_client_name()
    if not name:
        return
    try:
        result = recreate_client(name)
        print(f"{GREEN}Клиент пересоздан.{RESET}")
        print(f"Новый CN: {result['cert_cn']}")
        print(f"Профиль: {result['profile_path']}")
    except Exception as exc:
        print(f"{RED}Ошибка:{RESET} {exc}")
    pause()


def menu_extend_client() -> None:
    print_header("Продление ключа")
    name = _choose_client_name()
    if not name:
        return
    days = _ask_int("Добавить дней [30]: ", 30)
    try:
        new_date = extend_client(name, days)
        print(f"{GREEN}Новый срок:{RESET} {new_date}")
    except Exception as exc:
        print(f"{RED}Ошибка:{RESET} {exc}")
    pause()


def menu_block_toggle(block: bool) -> None:
    print_header("Блокировка/Разблокировка")
    name = _choose_client_name()
    if not name:
        return
    try:
        if block:
            block_client(name)
            print(f"{GREEN}Клиент заблокирован.{RESET}")
        else:
            unblock_client(name)
            print(f"{GREEN}Клиент разблокирован.{RESET}")
    except Exception as exc:
        print(f"{RED}Ошибка:{RESET} {exc}")
    pause()


def menu_connected() -> None:
    print_header("Подключенные клиенты")
    rows = connected_clients()
    if not rows:
        print("Сейчас никто не подключен.")
    else:
        for row in rows:
            print(f"- {row['key_name']} ({row['cert_cn']})")
    pause()


def menu_remotes() -> None:
    while True:
        print_header("Remote-адреса")
        remotes = current_remotes()
        for idx, remote in enumerate(remotes, start=1):
            tag = " [MAIN]" if idx == 1 else ""
            print(f"{idx}. {remote}{tag}")
        print("\n1. Сменить основной remote")
        print("2. Добавить remote")
        print("3. Удалить remote")
        print("0. Назад")
        choice = input("\nВыбор: ").strip()
        try:
            if choice == "1":
                new_remote = input("Новый основной домен/IP: ").strip()
                set_primary_remote(new_remote)
                print(f"{GREEN}Основной remote обновлен. Все профили пересобраны.{RESET}")
                pause()
            elif choice == "2":
                new_remote = input("Remote: ").strip()
                add_remote(new_remote)
                print(f"{GREEN}Remote добавлен.{RESET}")
                pause()
            elif choice == "3":
                to_delete = input("Remote для удаления: ").strip()
                delete_remote(to_delete)
                print(f"{GREEN}Remote удален.{RESET}")
                pause()
            elif choice == "0":
                return
        except Exception as exc:
            print(f"{RED}Ошибка:{RESET} {exc}")
            pause()


def menu_telegram() -> None:
    print_header("Настройки Telegram")
    settings = telegram_settings()
    print(f"Включен: {'Да' if settings['enabled'] else 'Нет'}")
    print(f"Admin IDs: {settings['admin_ids']}")
    print(f"Notify chat ID: {settings['notify_chat_id']}")
    print(f"Доп. пользователи: {', '.join(allowed_bot_users()) or 'нет'}")
    print("\n1. Изменить токен")
    print("2. Изменить admin IDs")
    print("3. Изменить notify chat ID")
    print("4. Включить/выключить бота")
    print("5. Добавить пользователя бота")
    print("6. Удалить пользователя бота")
    print("0. Назад")
    choice = input("\nВыбор: ").strip()
    try:
        if choice == "1":
            token = input("Новый bot token: ").strip()
            set_telegram_settings(bot_token=token)
        elif choice == "2":
            ids = [x.strip() for x in input("Admin IDs через запятую: ").split(",") if x.strip()]
            set_telegram_settings(admin_ids=ids)
        elif choice == "3":
            chat_id = input("Notify chat ID: ").strip()
            set_telegram_settings(notify_chat_id=chat_id)
        elif choice == "4":
            set_telegram_settings(enabled=not bool(settings['enabled']))
        elif choice == "5":
            from .openvpn import add_bot_user
            add_bot_user(input("Telegram ID: ").strip())
        elif choice == "6":
            from .openvpn import remove_bot_user
            remove_bot_user(input("Telegram ID: ").strip())
    except Exception as exc:
        print(f"{RED}Ошибка:{RESET} {exc}")
    pause()


def menu_services() -> None:
    print_header("Службы")
    print(f"Статус OpenVPN: {service_status_text()}")
    print("\n1. Запустить OpenVPN")
    print("2. Остановить OpenVPN")
    print("3. Перезапустить OpenVPN")
    print("4. Создать бэкап")
    print("0. Назад")
    choice = input("\nВыбор: ").strip()
    if choice == "1":
        start_openvpn()
    elif choice == "2":
        stop_openvpn()
    elif choice == "3":
        restart_openvpn()
    elif choice == "4":
        path = backup_all()
        print(f"Бэкап: {path}")
        pause()
        return
    pause()


def main() -> int:
    try:
        ensure_root()
    except Exception as exc:
        print(exc)
        return 1
    while True:
        print_header("OpenVPN Menu")
        print(summary_text())
        print("\n1. Список ключей")
        print("2. Создать ключ")
        print("3. Удалить ключ")
        print("4. Пересоздать ключ")
        print("5. Продлить срок")
        print("6. Заблокировать ключ")
        print("7. Разблокировать ключ")
        print("8. Подключенные клиенты")
        print("9. Remote-адреса")
        print("10. Telegram настройки")
        print("11. Службы и бэкап")
        print("0. Выход")
        choice = input("\nВыберите пункт: ").strip()
        if choice == "1":
            menu_list_clients()
        elif choice == "2":
            menu_create_client()
        elif choice == "3":
            menu_delete_client()
        elif choice == "4":
            menu_recreate_client()
        elif choice == "5":
            menu_extend_client()
        elif choice == "6":
            menu_block_toggle(True)
        elif choice == "7":
            menu_block_toggle(False)
        elif choice == "8":
            menu_connected()
        elif choice == "9":
            menu_remotes()
        elif choice == "10":
            menu_telegram()
        elif choice == "11":
            menu_services()
        elif choice == "0":
            return 0


if __name__ == "__main__":
    raise SystemExit(main())
