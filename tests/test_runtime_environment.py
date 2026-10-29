import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from articheck.reproduction.monitor import quantity, ExternalMonitor
from articheck.reproduction.runtime_environment import compare_environment,requirement_checks,inspect_image
from articheck.reproduction.executor import StageExecutor


class RuntimeRequirementTests(unittest.TestCase):
    def test_package_python_and_cuda_require_actual_versions_and_kernel_execution(self):
        expected={'python':'3.11','packages':{'torch':'2.4.1'},'cuda':{'required':True,'runtime':'12.1'}}
        observed={'python':'3.11.9','packages':{'torch':'2.4.1'},'cuda':{'status':'verified','kernel_test':True,'runtime':'12.1'}}
        self.assertTrue(all(x['status']=='pass' for x in compare_environment(expected,observed)))
        observed['cuda']['kernel_test']=False
        self.assertEqual(compare_environment(expected,observed)[-1]['status'],'fail')
        observed['packages']['torch']='2.4.0'
        self.assertEqual(compare_environment(expected,observed)[1]['status'],'fail')
        self.assertEqual(compare_environment({},observed)[0]['status'],'unknown')
    def test_executor_quota_and_daemon_capacity_are_distinct(self):
        spec={'cpus':1,'memory_bytes':1024,'requirements':{'cpus':2,'daemon_cpus':2,'daemon_memory_bytes':2048,'disk_free_bytes':100}}
        checks=requirement_checks(spec,{'logical_cpus':8,'memory_bytes':None},99)
        self.assertEqual([x['status'] for x in checks],['fail','fail','pass','unknown'])
    def test_daemon_memory_parser_respects_binary_and_decimal_units(self):
        self.assertEqual(quantity('1.5 MiB'),1572864);self.assertEqual(quantity('1.5MB'),1500000)
        for value in ['NaN MB','-1 GiB','1 mystery']:
            with self.assertRaises(ValueError):quantity(value)


class ExternalMeasurementTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_probe_uses_interpreter_metadata_and_rejects_expected_mismatch(self):
        import platform
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);executor=StageExecutor('local',allow_local_trusted=True)
            proof=await inspect_image(executor,root,root,{'python':platform.python_version(),'packages':{}},5)
            self.assertEqual(proof['status'],'verified')
            proof=await inspect_image(executor,root,root,{'python':'0.0','packages':{}},5)
            self.assertEqual(proof['status'],'failed')
    async def test_output_disk_peak_is_sampled_outside_artifact_and_limit_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);monitor=ExternalMonitor(root,disk_limit=10)
            (root/'output.bin').write_bytes(b'x'*20);monitor.sample_disk()
            (root/'output.bin').unlink();monitor.sample_disk()
            self.assertEqual(monitor.report['sampled_peak_output_bytes'],20)
            self.assertTrue(monitor.report['disk_limit_exceeded'])
            self.assertIsNone(monitor.report['sampled_peak_container_memory_bytes'])
    async def test_docker_measurement_is_external_and_records_container_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            monitor=ExternalMonitor(Path(tmp),'/docker','own-container')
            async def observe(*args):
                monitor.finished=True
                return {'container_id':'abc123','memory_bytes':4096,'cpu_percent':150.0}
            with patch('articheck.reproduction.monitor.docker_sample',observe):await monitor.run()
            self.assertEqual(monitor.report['sampled_peak_container_memory_bytes'],4096)
            self.assertEqual(monitor.report['container_ids'],['abc123'])
