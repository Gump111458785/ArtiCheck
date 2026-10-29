import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from articheck.environment import collect_environment, command

class EnvironmentTests(unittest.TestCase):
    def test_snapshot_is_readonly_and_does_not_include_machine_identity(self):
        with tempfile.TemporaryDirectory() as folder, patch('articheck.environment.shutil.which',return_value=None):
            result=collect_environment(Path(folder))
            self.assertEqual(result['format'],'articheck-environment-v1')
            self.assertIsNone(result['gpus'])
            self.assertGreaterEqual(result['disk']['free_bytes'],0)
            self.assertNotIn('hostname',result)
            self.assertNotIn('environment',result)
            self.assertNotIn(folder,json.dumps(result))

    def test_nvidia_csv_is_read_as_individual_free_memory(self):
        with tempfile.TemporaryDirectory() as folder, patch('articheck.environment.shutil.which',return_value='/usr/bin/nvidia-smi'), patch('articheck.environment.command',return_value='0, Test GPU, 24576, 16384, 555.1\n'):
            result=collect_environment(Path(folder))
            self.assertEqual(result['gpus'][0]['free_memory_bytes'],16384*1024**2)
            self.assertEqual(result['gpus'][0]['total_memory_bytes'],24576*1024**2)

    def test_unreadable_gpu_values_stay_unknown(self):
        with tempfile.TemporaryDirectory() as folder, patch('articheck.environment.shutil.which',return_value='/usr/bin/nvidia-smi'), patch('articheck.environment.command',return_value='0, GPU, N/A, N/A, driver\n'):
            self.assertIsNone(collect_environment(Path(folder))['gpus'])

    def test_probe_failure_is_not_converted_to_hardware_success(self):
        with patch('articheck.environment.subprocess.run',side_effect=OSError('missing')):
            self.assertIsNone(command(['nvidia-smi']))

    def test_downloadable_collector_matches_actual_module(self):
        root=Path(__file__).resolve().parents[1]
        self.assertEqual((root/'web/dist/collect-environment.py').read_bytes(),(root/'articheck/environment.py').read_bytes())
