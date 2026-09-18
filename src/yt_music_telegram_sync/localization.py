from __future__ import annotations

from typing import Literal

Language = Literal["ru", "en"]

DEFAULT_LANGUAGE: Language = "ru"
SUPPORTED_LANGUAGES: tuple[Language, ...] = ("ru", "en")
LANGUAGE_LABELS: dict[Language, str] = {
    "ru": "Русский",
    "en": "English",
}

_TRANSLATIONS: dict[Language, dict[str, str]] = {
    "ru": {
        "window.title": "YT Music → Telegram · v{version}",
        "header.subtitle": "Last.fm nowplaying и музыка вашего профиля",
        "language.label": "Язык",
        "tabs.sync": "  Синхронизация  ",
        "lastfm.username": "Имя пользователя",
        "lastfm.note": (
            "Пароль здесь не вводится: для чтения nowplaying Last.fm требует только "
            "username и API key. В Web Scrobbler вход выполняется на странице Last.fm."
        ),
        "credentials.show": "Показывать реквизиты",
        "lastfm.get_api_key": "Получить API key",
        "lastfm.test": "Проверить Last.fm",
        "telegram.phone": "Телефон",
        "telegram.send_code": "1. Отправить код",
        "telegram.code": "Код из Telegram",
        "telegram.password": "Пароль Telegram 2FA",
        "telegram.sign_in": "2. Войти в Telegram",
        "telegram.password_note": (
            "Пароль 2FA используется только при входе и не сохраняется."
        ),
        "behavior.title": "Поведение",
        "behavior.poll": "Опрос Last.fm, секунд",
        "behavior.absent": "Проверок перед idle",
        "behavior.cache": "Треков в профиле",
        "behavior.audio_mode": "Режим аудио",
        "behavior.emoji": "Emoji status при nowplaying",
        "behavior.select": "Выбрать…",
        "behavior.workers": "Параллельных загрузок",
        "behavior.remove_idle": "Удалять музыку профиля, когда nowplaying исчез",
        "notifications.title": "Уведомления",
        "notifications.enabled": "Показывать системные уведомления",
        "notifications.sound": "Воспроизводить звук уведомлений",
        "notifications.note": (
            "Отключение звука действует только на уведомления этого приложения."
        ),
        "footer.hint": "Ctrl+S — сохранить",
        "footer.save": "Сохранить",
        "footer.cancel": "Отмена",
        "status.initial": "Заполните параметры и проверьте подключения",
        "status.language_changed": "Язык интерфейса изменён",
        "config.missing": "Не заполнено: {fields}",
        "config.poll_min": "Интервал Last.fm не может быть меньше 3 секунд",
        "config.absent_range": "Подтверждений отсутствия должно быть от 1 до 20",
        "config.cache_range": "Размер кэша должен быть от 1 до 100",
        "config.audio_mode": "Неизвестный режим аудио",
        "config.workers_range": "Количество загрузчиков должно быть от 1 до 4",
        "config.emoji_id": "Telegram emoji status ID должен быть 64-битным числом",
        "config.language": "Неизвестный язык интерфейса",
        "config.not_created": "Конфигурация ещё не создана",
        "config.read_failed": "Не удалось прочитать конфигурацию: {error}",
        "config.invalid": "Некорректная конфигурация: {error}",
        "setup.numeric_invalid": "Числовые параметры заполнены некорректно",
        "setup.api_id_number": "Telegram API ID должен быть числом",
        "setup.api_credentials_required": "Заполните Telegram API ID и API hash",
        "setup.phone_required": "Заполните номер телефона Telegram",
        "lastfm.credentials_required": "Введите username и API key",
        "lastfm.checking": "Проверка Last.fm…",
        "lastfm.error": "Ошибка Last.fm: {error}",
        "lastfm.connected_idle": (
            "Last.fm подключён: {username}. Активный nowplaying не найден."
        ),
        "lastfm.connected_track": (
            "Last.fm подключён: {username}. Сейчас играет: {track}"
        ),
        "lastfm.no_user": "Last.fm вернул ответ без пользователя",
        "lastfm.empty_user": "Last.fm вернул пустое имя пользователя",
        "lastfm.http_error": "Last.fm вернул HTTP {status}",
        "lastfm.network_error": "Сетевая ошибка Last.fm ({error_type})",
        "lastfm.invalid_json": "Last.fm вернул некорректный JSON",
        "lastfm.unexpected_response": "Last.fm вернул неожиданный формат ответа",
        "lastfm.unknown_error": "Неизвестная ошибка Last.fm",
        "lastfm.track_metadata_missing": (
            "У текущего трека отсутствуют название или исполнитель"
        ),
        "telegram.session_authorized": "Существующая Telegram-сессия авторизована",
        "telegram.sending_code": "Отправка кода Telegram…",
        "telegram.error": "Ошибка Telegram: {error}",
        "telegram.already_authorized": (
            "Telegram уже авторизован. Нажмите «Сохранить» после изменений"
        ),
        "telegram.code_sent": (
            "Код отправлен. Введите его и нажмите «Войти в Telegram»"
        ),
        "telegram.code_required": "Введите код из Telegram",
        "telegram.authorizing": "Авторизация Telegram…",
        "telegram.2fa_cancelled": (
            "Вход с 2FA отменён. Запросите новый код и повторите вход"
        ),
        "telegram.2fa_retry": (
            "Для продолжения запросите новый код Telegram. При следующем входе "
            "введите пароль 2FA или укажите его во всплывающем окне."
        ),
        "telegram.authorized": (
            "Telegram успешно авторизован. Проверьте параметры и нажмите «Сохранить»"
        ),
        "telegram.client_closed": "Telegram-клиент уже закрыт",
        "telegram.unauthorized": (
            "Telegram не авторизован. Запустите мастер настройки."
        ),
        "telegram.no_user": "Telegram не вернул данные текущего пользователя",
        "telegram.emoji_set_rejected": "Telegram отклонил установку emoji status",
        "telegram.emoji_previous_missing": (
            "Исходный Telegram emoji status не сохранён"
        ),
        "telegram.emoji_restore_rejected": (
            "Telegram отклонил восстановление emoji status"
        ),
        "telegram.no_document": (
            "Telegram не вернул документ после загрузки трека"
        ),
        "telegram.telethon_too_old": (
            "Установленная версия Telethon не поддерживает Telegram Music on Profile"
        ),
        "telegram.music_add_rejected": "Telegram отклонил добавление музыки профиля",
        "telegram.music_remove_rejected": "Telegram отклонил удаление музыки профиля",
        "telegram.emoji_unsupported": (
            "Неподдерживаемый тип Telegram emoji status: {status_type}"
        ),
        "telegram.2fa_prompt": (
            "Введите пароль двухэтапной аутентификации Telegram.\n"
            "Он используется только сейчас и не сохраняется."
        ),
        "emoji.selecting": "Выбор Telegram emoji status…",
        "emoji.error": "Ошибка Telegram emoji status: {error}",
        "emoji.cancelled": "Выбор Telegram emoji status отменён",
        "emoji.selected": (
            "Emoji status выбран; исходный статус Telegram восстановлен"
        ),
        "emoji.dialog_title": "Emoji status для музыки",
        "emoji.dialog": (
            "Откройте Telegram и установите обычный emoji status, который должен "
            "показываться во время прослушивания.\n\n"
            "После установки вернитесь сюда и нажмите OK. Приложение считает ID "
            "и сразу восстановит ваш исходный статус.\n\n"
            "Коллекционные статусы не поддерживаются."
        ),
        "setup.saving": "Сохранение настроек…",
        "setup.title": "Настройка",
        "setup.save_error": "Ошибка сохранения: {error}",
        "emoji.telegram_unauthorized": (
            "Telegram не авторизован. Сначала выполните вход в мастере настройки."
        ),
        "emoji.no_user": "Telegram не вернул данные текущего пользователя",
        "emoji.premium_required": "Для emoji status требуется Telegram Premium",
        "emoji.collectible": (
            "Выбран коллекционный статус. Выберите обычный Telegram emoji status."
        ),
        "emoji.not_selected": "Emoji status не выбран",
        "emoji.restore_rejected": (
            "Telegram отклонил восстановление исходного emoji status"
        ),
        "service.stopped": "Остановлено",
        "service.resumed": "Синхронизация возобновлена",
        "service.paused": "Синхронизация приостановлена",
        "service.connecting": "Подключение к Last.fm и Telegram…",
        "service.connected": (
            "Last.fm подключён: {username}; проверка nowplaying…"
        ),
        "service.idle": "Last.fm: сейчас ничего не играет",
        "service.idle_cleaned": (
            "Last.fm: сейчас ничего не играет; музыка профиля очищена"
        ),
        "service.profile_cleared": "Музыка профиля очищена",
        "service.clear_error": "Очистка: {error}",
        "sync.cleanup_failed": (
            "Не удалось удалить треков из профиля: {count}. "
            "Они сохранены для повторной очистки."
        ),
        "tray.sync_now": "Синхронизировать сейчас",
        "tray.clear": "Очистить музыку профиля",
        "tray.settings": "Настройки…",
        "tray.open_log": "Открыть журнал",
        "tray.open_data": "Открыть папку данных",
        "tray.restart": "Перезапустить",
        "tray.exit": "Выход",
        "tray.resume": "Возобновить",
        "tray.pause": "Приостановить",
        "tray.synced": "Синхронизировано",
        "tray.sync_error": "Ошибка синхронизации",
        "tray.cleanup_done": "Очистка завершена",
        "tray.setup_open": "Окно настроек уже открыто.",
        "tray.setup_title": "Настройки",
        "tray.setup_open_error": "Ошибка открытия настроек",
        "tray.setup_restart": (
            "После сохранения приложение перезапустится автоматически."
        ),
        "tray.restart_wait": "Сначала сохраните или закройте окно настроек.",
        "tray.restart_wait_title": "Перезапуск отложен",
        "tray.setup_discarded": (
            "Изменения не сохранены; работа продолжена с прежними настройками."
        ),
        "tray.setup_closed": "Настройки закрыты",
        "tray.restart_error": "Ошибка перезапуска",
        "app.already_running": "Приложение уже запущено",
    },
    "en": {
        "window.title": "YT Music → Telegram · v{version}",
        "header.subtitle": "Last.fm now playing and your profile music",
        "language.label": "Language",
        "tabs.sync": "  Synchronization  ",
        "lastfm.username": "Username",
        "lastfm.note": (
            "No password is entered here: reading Last.fm now playing requires only "
            "a username and API key. Web Scrobbler signs in on the Last.fm website."
        ),
        "credentials.show": "Show credentials",
        "lastfm.get_api_key": "Get API key",
        "lastfm.test": "Test Last.fm",
        "telegram.phone": "Phone",
        "telegram.send_code": "1. Send code",
        "telegram.code": "Telegram code",
        "telegram.password": "Telegram 2FA password",
        "telegram.sign_in": "2. Sign in to Telegram",
        "telegram.password_note": (
            "The 2FA password is used only for sign-in and is not saved."
        ),
        "behavior.title": "Behavior",
        "behavior.poll": "Last.fm polling, seconds",
        "behavior.absent": "Checks before idle",
        "behavior.cache": "Tracks in profile",
        "behavior.audio_mode": "Audio mode",
        "behavior.emoji": "Emoji status while playing",
        "behavior.select": "Select…",
        "behavior.workers": "Parallel downloads",
        "behavior.remove_idle": "Remove profile music when now playing disappears",
        "notifications.title": "Notifications",
        "notifications.enabled": "Show system notifications",
        "notifications.sound": "Play notification sounds",
        "notifications.note": (
            "Disabling sound affects notifications from this application only."
        ),
        "footer.hint": "Ctrl+S — save",
        "footer.save": "Save",
        "footer.cancel": "Cancel",
        "status.initial": "Enter the settings and test the connections",
        "status.language_changed": "Interface language changed",
        "config.missing": "Missing: {fields}",
        "config.poll_min": "The Last.fm interval cannot be shorter than 3 seconds",
        "config.absent_range": "Idle confirmations must be between 1 and 20",
        "config.cache_range": "Cache size must be between 1 and 100",
        "config.audio_mode": "Unknown audio mode",
        "config.workers_range": "The number of download workers must be between 1 and 4",
        "config.emoji_id": "Telegram emoji status ID must be a 64-bit number",
        "config.language": "Unknown interface language",
        "config.not_created": "The configuration has not been created yet",
        "config.read_failed": "Could not read the configuration: {error}",
        "config.invalid": "Invalid configuration: {error}",
        "setup.numeric_invalid": "One or more numeric settings are invalid",
        "setup.api_id_number": "Telegram API ID must be a number",
        "setup.api_credentials_required": "Enter the Telegram API ID and API hash",
        "setup.phone_required": "Enter the Telegram phone number",
        "lastfm.credentials_required": "Enter the username and API key",
        "lastfm.checking": "Testing Last.fm…",
        "lastfm.error": "Last.fm error: {error}",
        "lastfm.connected_idle": (
            "Last.fm connected: {username}. No active now playing track was found."
        ),
        "lastfm.connected_track": (
            "Last.fm connected: {username}. Now playing: {track}"
        ),
        "lastfm.no_user": "Last.fm returned a response without a user",
        "lastfm.empty_user": "Last.fm returned an empty username",
        "lastfm.http_error": "Last.fm returned HTTP {status}",
        "lastfm.network_error": "Last.fm network error ({error_type})",
        "lastfm.invalid_json": "Last.fm returned invalid JSON",
        "lastfm.unexpected_response": "Last.fm returned an unexpected response format",
        "lastfm.unknown_error": "Unknown Last.fm error",
        "lastfm.track_metadata_missing": (
            "The current track has no title or artist"
        ),
        "telegram.session_authorized": "The existing Telegram session is authorized",
        "telegram.sending_code": "Sending the Telegram code…",
        "telegram.error": "Telegram error: {error}",
        "telegram.already_authorized": (
            "Telegram is already authorized. Click “Save” after making changes"
        ),
        "telegram.code_sent": (
            "Code sent. Enter it and click “Sign in to Telegram”"
        ),
        "telegram.code_required": "Enter the code from Telegram",
        "telegram.authorizing": "Authorizing Telegram…",
        "telegram.2fa_cancelled": (
            "2FA sign-in was cancelled. Request a new code and try again"
        ),
        "telegram.2fa_retry": (
            "Request a new Telegram code to continue. On the next attempt, enter "
            "the 2FA password in the form or in the pop-up dialog."
        ),
        "telegram.authorized": (
            "Telegram authorization succeeded. Review the settings and click “Save”"
        ),
        "telegram.client_closed": "The Telegram client is already closed",
        "telegram.unauthorized": (
            "Telegram is not authorized. Run the setup wizard."
        ),
        "telegram.no_user": "Telegram did not return the current user",
        "telegram.emoji_set_rejected": "Telegram rejected the emoji status update",
        "telegram.emoji_previous_missing": (
            "The original Telegram emoji status was not saved"
        ),
        "telegram.emoji_restore_rejected": (
            "Telegram rejected restoration of the emoji status"
        ),
        "telegram.no_document": (
            "Telegram did not return a document after uploading the track"
        ),
        "telegram.telethon_too_old": (
            "The installed Telethon version does not support Telegram Music on Profile"
        ),
        "telegram.music_add_rejected": "Telegram rejected adding profile music",
        "telegram.music_remove_rejected": "Telegram rejected removing profile music",
        "telegram.emoji_unsupported": (
            "Unsupported Telegram emoji status type: {status_type}"
        ),
        "telegram.2fa_prompt": (
            "Enter your Telegram two-step verification password.\n"
            "It is used only now and is not saved."
        ),
        "emoji.selecting": "Selecting a Telegram emoji status…",
        "emoji.error": "Telegram emoji status error: {error}",
        "emoji.cancelled": "Telegram emoji status selection cancelled",
        "emoji.selected": (
            "Emoji status selected; the original Telegram status was restored"
        ),
        "emoji.dialog_title": "Emoji status for music",
        "emoji.dialog": (
            "Open Telegram and set the regular emoji status that should appear "
            "while you are listening.\n\n"
            "Return here after setting it and click OK. The application will read "
            "its ID and immediately restore your original status.\n\n"
            "Collectible statuses are not supported."
        ),
        "setup.saving": "Saving settings…",
        "setup.title": "Setup",
        "setup.save_error": "Save error: {error}",
        "emoji.telegram_unauthorized": (
            "Telegram is not authorized. Sign in through the setup window first."
        ),
        "emoji.no_user": "Telegram did not return the current user",
        "emoji.premium_required": "Telegram Premium is required for emoji status",
        "emoji.collectible": (
            "A collectible status was selected. Select a regular Telegram emoji status."
        ),
        "emoji.not_selected": "No emoji status was selected",
        "emoji.restore_rejected": (
            "Telegram rejected restoration of the original emoji status"
        ),
        "service.stopped": "Stopped",
        "service.resumed": "Synchronization resumed",
        "service.paused": "Synchronization paused",
        "service.connecting": "Connecting to Last.fm and Telegram…",
        "service.connected": (
            "Last.fm connected: {username}; checking now playing…"
        ),
        "service.idle": "Last.fm: nothing is playing now",
        "service.idle_cleaned": (
            "Last.fm: nothing is playing now; profile music was cleared"
        ),
        "service.profile_cleared": "Profile music cleared",
        "service.clear_error": "Cleanup: {error}",
        "sync.cleanup_failed": (
            "Could not remove {count} track(s) from the profile. "
            "They were retained for another cleanup attempt."
        ),
        "tray.sync_now": "Synchronize now",
        "tray.clear": "Clear profile music",
        "tray.settings": "Settings…",
        "tray.open_log": "Open log",
        "tray.open_data": "Open data folder",
        "tray.restart": "Restart",
        "tray.exit": "Exit",
        "tray.resume": "Resume",
        "tray.pause": "Pause",
        "tray.synced": "Synchronized",
        "tray.sync_error": "Synchronization error",
        "tray.cleanup_done": "Cleanup complete",
        "tray.setup_open": "The settings window is already open.",
        "tray.setup_title": "Settings",
        "tray.setup_open_error": "Could not open settings",
        "tray.setup_restart": (
            "The application will restart automatically after the settings are saved."
        ),
        "tray.restart_wait": "Save or close the settings window first.",
        "tray.restart_wait_title": "Restart postponed",
        "tray.setup_discarded": (
            "Changes were not saved; the application resumed with the old settings."
        ),
        "tray.setup_closed": "Settings closed",
        "tray.restart_error": "Restart failed",
        "app.already_running": "The application is already running",
    },
}


def normalize_language(value: str) -> Language:
    if value == "en":
        return "en"
    return DEFAULT_LANGUAGE


def translate(key: str, language: str, **values: object) -> str:
    resolved = normalize_language(language)
    template = _TRANSLATIONS[resolved].get(key)
    if template is None:
        template = _TRANSLATIONS[DEFAULT_LANGUAGE].get(key, key)
    return template.format(**values)


def translation_keys(language: Language) -> frozenset[str]:
    return frozenset(_TRANSLATIONS[language])
