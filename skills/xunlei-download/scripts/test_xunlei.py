import importlib.util
import io
import json
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock


SCRIPT = Path(__file__).with_name("xunlei.py")
SPEC = importlib.util.spec_from_file_location("xunlei_script", SCRIPT)
XUNLEI = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(XUNLEI)


class Response:
    status = 200

    def __init__(self, body):
        self.body = json.dumps(body).encode()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self):
        return self.body


class ScriptExitTest(unittest.TestCase):
    def test_successful_command_exits_zero(self):
        response = Response({"logged_in": True})
        with mock.patch.object(sys, "argv", [str(SCRIPT), "login"]), mock.patch.object(
            XUNLEI.urllib.request, "urlopen", return_value=response
        ), redirect_stdout(io.StringIO()):
            XUNLEI.main()

    def test_business_error_exits_nonzero(self):
        response = Response({"error": "device_space_not_active"})
        with mock.patch.object(sys, "argv", [str(SCRIPT), "login"]), mock.patch.object(
            XUNLEI.urllib.request, "urlopen", return_value=response
        ), redirect_stdout(io.StringIO()), self.assertRaisesRegex(
            SystemExit, "1"
        ):
            XUNLEI.main()


if __name__ == "__main__":
    unittest.main()
