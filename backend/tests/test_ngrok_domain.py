import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import main
from app.ngrok_manager import normalize_domain


class NgrokDomainTests(unittest.TestCase):
    def test_normalize(self):
        self.assertEqual(normalize_domain(" https://Photo.Example.com/ "), "photo.example.com")
        self.assertIsNone(normalize_domain("  "))
        for bad in ("localhost", "a b.com", "foo.com:8080", "-x.example.com"):
            with self.assertRaises(ValueError):
                normalize_domain(bad)

    def test_domain_and_token_coexist(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = Path(tmp) / "ngrok_config.json"
            with patch.object(main, "NGROK_CONFIG_FILE", cfg), patch.dict("os.environ", {}, clear=False):
                main.os.environ.pop("NGROK_DOMAIN", None)
                main._save_ngrok_domain("photo.example.com")
                main._save_ngrok_token("tok")
                self.assertEqual(json.loads(cfg.read_text())["domain"], "photo.example.com")
                self.assertEqual(main._load_ngrok_domain(), "photo.example.com")
                main._save_ngrok_domain(None)
                self.assertIsNone(main._load_ngrok_domain())
                self.assertEqual(main._load_ngrok_token(), "tok")


if __name__ == "__main__":
    unittest.main()
