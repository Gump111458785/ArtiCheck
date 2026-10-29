"""Simulated NVIDIA and namespace evidence; these are not real GPU measurements."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from articheck.reproduction.gpu_monitor import parse_devices,parse_processes,sample_gpu
from articheck.reproduction.monitor import ExternalMonitor

UUID='GPU-1234abcd-0000-0000-0000-000000000001'

class GPUParsingTests(unittest.TestCase):
    def test_scope_filters_other_devices_and_other_container_processes(self):
        self.assertEqual(parse_devices(UUID+', 100\n',[UUID]),{UUID:100*1024**2})
        rows=UUID+', 10, 50\n'+UUID+', 99, 999\n'
        self.assertEqual(parse_processes(rows,[UUID],{10}),{UUID:50*1024**2})
        self.assertIsNone(parse_processes(UUID+', 10, N/A',[UUID],{10}))
        self.assertIsNone(parse_devices('',[UUID]))
        self.assertIsNone(parse_devices(UUID+', NaN',[UUID]))

class GPUAttributionTests(unittest.IsolatedAsyncioTestCase):
    async def test_kernel_mismatch_never_attributes_whole_device_memory_to_job(self):
        async def command(argv):return UUID+', 200\n'
        with patch('shutil.which',return_value='/nvidia-smi'),patch('articheck.reproduction.gpu_monitor.bounded_command',command):
            result=await sample_gpu('/docker','own',[UUID],False)
        self.assertEqual(result['device_memory_bytes'][UUID],200*1024**2)
        self.assertIsNone(result['container_process_memory_bytes'])
    async def test_matching_kernel_uses_docker_pid_membership(self):
        async def command(argv):
            if 'top' in argv:return 'PID\n10\n11\n'
            if any('query-compute-apps' in x for x in argv):return UUID+', 10, 20\n'+UUID+', 99, 500\n'
            return UUID+', 520\n'
        with patch('shutil.which',return_value='/nvidia-smi'),patch('articheck.reproduction.gpu_monitor.bounded_command',command):
            result=await sample_gpu('/docker','own',[UUID],True)
        self.assertEqual(result['container_process_memory_bytes'][UUID],20*1024**2)
    async def test_monitor_keeps_device_peak_separate_and_cpu_unknown_from_becoming_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            monitor=ExternalMonitor(Path(tmp),'/docker','own',gpu_uuids=[UUID],same_kernel=False)
            async def gpu(*args):
                monitor.finished=True
                return {'device_memory_bytes':{UUID:123},'container_process_memory_bytes':None}
            async def docker(*args):return None
            with patch('articheck.reproduction.monitor.sample_gpu',gpu),patch('articheck.reproduction.monitor.docker_sample',docker):await monitor.run()
            self.assertEqual(monitor.report['sampled_peak_gpu_device_bytes'],{UUID:123})
            self.assertIsNone(monitor.report['sampled_peak_gpu_process_total_bytes'])
            self.assertIsNone(monitor.report['sampled_peak_container_memory_bytes'])
