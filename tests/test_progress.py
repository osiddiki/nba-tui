import io
import unittest
from unittest.mock import patch

from sportscli import progress


class Terminal(io.StringIO):
    def isatty(self): return True


class DownloadProgressTests(unittest.TestCase):
    def test_non_terminal_output_has_no_control_sequences(self):
        output = io.StringIO()
        with progress.Download('Downloading model', 2000, output) as download:
            download.update(1000)
            download.update(2000)
        self.assertIn('2.0 KB', output.getvalue())
        self.assertNotIn('\r', output.getvalue())
        self.assertNotIn('\x1b', output.getvalue())

    def test_plain_terminal_shows_actual_percentage_and_unknown_size(self):
        output = Terminal()
        with patch.object(progress, 'Progress', None), patch.object(progress, '_load_rich'):
            with progress.Download('Model', 2000, output) as download:
                download.update(2000)
            self.assertIn('100%', output.getvalue())
            unknown = Terminal()
            with progress.Download('Model', None, unknown) as download:
                download.update(2000)
            self.assertIn('2.0 KB', unknown.getvalue())
            self.assertNotIn('%', unknown.getvalue())

    def test_failure_does_not_claim_a_completed_download(self):
        output = io.StringIO()
        with self.assertRaises(OSError):
            with progress.Download('Model', 100, output) as download:
                download.update(50)
                raise OSError('interrupted')
        self.assertNotIn('100%', output.getvalue())
        self.assertNotIn('Model: 100 B', output.getvalue())


if __name__ == '__main__':
    unittest.main()
