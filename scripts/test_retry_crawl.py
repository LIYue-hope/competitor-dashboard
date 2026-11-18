import io
import subprocess
import sys
import unittest
from contextlib import redirect_stdout
from unittest.mock import Mock, call, patch

import retry_crawl


class RetryCrawlTest(unittest.TestCase):
    def test_retries_wait_and_preserve_final_exit_code(self):
        script = "scripts/test site.py"
        command = [sys.executable, script]
        cases = (
            ("first attempt succeeds", [0], 0),
            ("first retry succeeds", [8, 0], 0),
            ("last retry succeeds", [8, 9, 10, 0], 0),
            ("all attempts fail", [8, 9, 10, 11], 11),
        )

        for name, exit_codes, expected_code in cases:
            with self.subTest(name=name):
                results = [subprocess.CompletedProcess(command, code) for code in exit_codes]
                calls = Mock()
                with (
                    patch.object(sys, "argv", ["retry_crawl.py", script]),
                    patch.object(subprocess, "run", side_effect=results) as run,
                    patch.object(retry_crawl.time, "sleep") as sleep,
                    redirect_stdout(io.StringIO()),
                ):
                    calls.attach_mock(run, "run")
                    calls.attach_mock(sleep, "sleep")
                    self.assertEqual(retry_crawl.main(), expected_code)

                expected_calls = [call.run(command, check=False)]
                for _ in exit_codes[1:]:
                    expected_calls.extend((call.sleep(30), call.run(command, check=False)))
                self.assertEqual(calls.mock_calls, expected_calls)


if __name__ == "__main__":
    unittest.main()
