from unittest import TestCase
from states._modules import shaping
import yaml, os.path

data_dir ="{0}/data".format(os.path.realpath(os.path.dirname(__file__)))

class ShapingModuleTest(TestCase):
    
    def _test_yaml_to_tc(self, test_name):
        data = yaml.load(open("{0}/{1}.yaml".format(data_dir, test_name), 'r'))
        
        iface = data.keys()[0]
        
        qdisc = {}
        for x in data[iface]['shaping.qdisc']:
            qdisc.update(x)
        result =  shaping.build_tc_script(iface, qdisc, testing=True)
        
        expected = open("{0}/{1}.output".format(data_dir, test_name), 'r').readlines()
        
        self.assertListEqual(result, expected)
    
    def test_priority_queue(self):
        self._test_yaml_to_tc('prio_example')

    def test_htb(self):
        self._test_yaml_to_tc('htb_example')