import argparse
import errno
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch,Mock
from beacon_macos import plan,PtyReader,check_ports

class MacLauncherTests(unittest.TestCase):
    def args(self,source='live'):return argparse.Namespace(source=source,osc_port=57120)
    def root(self,directory):
        root=Path(directory);(root/'venv/bin').mkdir(parents=True);(root/'venv/bin/python3').touch();return root
    def test_exact_native_devices_and_no_linux_commands(self):
        with tempfile.TemporaryDirectory() as td:
            root=self.root(td);p=plan(root,{'BEACON_INPUT_DEVICE':'Interface Input','BEACON_OUTPUT_DEVICE':'Interface Output'},self.args(),lambda n,*_:n)
            self.assertEqual(p['scsynth'][-3:],['-H','Interface Input','Interface Output'])
            self.assertIn('32',p['scsynth']);self.assertNotIn('pw-jack',str(p))
            self.assertEqual(p['sclang'][1:3],['-u','57120'])
    def test_missing_devices_refuse_without_fallback(self):
        with tempfile.TemporaryDirectory() as td:
            root=self.root(td)
            for env in ({},{'BEACON_OUTPUT_DEVICE':'Output'}):
                with self.assertRaises(ValueError):plan(root,env,self.args(),lambda n,*_:n)
    def test_file_path_can_be_selected_without_input_capture(self):
        with tempfile.TemporaryDirectory() as td:
            root=self.root(td);audio=root/'own source.wav';audio.touch()
            p=plan(root,{'BEACON_OUTPUT_DEVICE':'Output','BEACON_AUDIO_FILE':str(audio)},self.args('file'),lambda n,*_:n)
            self.assertEqual(p['scsynth'][p['scsynth'].index('-i')+1],'0')
            self.assertIsNone(p['input_device'])
    def test_pty_eof_is_not_a_background_logging_error(self):
        reader=PtyReader.__new__(PtyReader);reader.stream=Mock();reader.stream.read.side_effect=OSError(errno.EIO,'pty closed')
        self.assertEqual(reader.read(8),b'')
    def test_port_guard_does_not_touch_existing_owners(self):
        import socket
        with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as sock:
            sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
            with self.assertRaises(ValueError):check_ports(port)
