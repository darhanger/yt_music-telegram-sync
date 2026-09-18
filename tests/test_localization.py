import unittest

from yt_music_telegram_sync.localization import (
    normalize_language,
    translate,
    translation_keys,
)


class LocalizationTests(unittest.TestCase):
    def test_catalogs_have_the_same_keys(self) -> None:
        self.assertEqual(translation_keys("ru"), translation_keys("en"))

    def test_unknown_language_falls_back_to_russian(self) -> None:
        self.assertEqual(normalize_language("de"), "ru")
        self.assertEqual(
            translate("footer.save", "de"),
            translate("footer.save", "ru"),
        )

    def test_translation_formats_values(self) -> None:
        self.assertEqual(
            translate("window.title", "en", version="1.2.3"),
            "YT Music → Telegram · v1.2.3",
        )


if __name__ == "__main__":
    unittest.main()
