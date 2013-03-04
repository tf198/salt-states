'''
Traffic shaping module
'''
from salt import utils
import logging, StringIO, os

logger = logging.getLogger(__name__)



def __virtual__():
    '''
    Verify that tc (iproute) is installed
    '''
    try:
        utils.check_or_die('tc')
        return 'shaping'
    except:
        return False

_SHAPING_SCRIPT = "/etc/tc_shaping_{0}"

class Counters:
    '''
    Creates unique class ids per qdisc id
    '''
    
    def __init__(self):
        self.qdiscs = [0]
        
    def get_qdisc_id(self, start=100):
        '''
        Get a new qdisc id.
        Optionally you can supply the start number for the class ids.
        '''
        self.qdiscs.append(start-1)
        return len(self.qdiscs)-1
    
    def get_class_id(self, qdisc_id):
        self.qdiscs[qdisc_id] += 1
        return self.qdiscs[qdisc_id]

def _qdisc_info(qdisc, counters):
    '''
    Returns formatted information about the qdisc
    Also sets the '_id' field on the qdisc and initialises the counter
    '''
    if not 'type' in qdisc:
        raise Exception("Missing 'type' for qdisc")
    
    # get a qdisc id and store it on the object
    cls_start = 1 if qdisc['type'] == 'prio' else 100 # prio creates classes automatically so we need to be 1 based
    qdisc['_id'] = counters.get_qdisc_id(cls_start)
    
    if not 'options' in qdisc: qdisc['options'] = ''
    return "handle {_id}: {type} {options}".format(**qdisc).strip()

def _tc_comment(stream, item):
    if 'comment' in item:
        stream.write('\n# {0}\n'.format(item['comment']))

def _tc_qdisc(stream, counters, qdisc, iface, parent_qdisc, parent_cls):
    '''
    Writes a tc qdisc entry to the stream.
    '''
    
    params = { 'iface': iface, 'parent_qdisc': parent_qdisc, 'parent_cls': parent_cls, 'info': _qdisc_info(qdisc, counters) }
    params.update(qdisc)
    
    _tc_comment(stream, qdisc)
    
    parent = "parent {parent_qdisc}:{parent_cls}".format(**params) if parent_qdisc else "root"
        
    stream.write("tc qdisc add dev {iface} {parent} {info}\n".format(parent=parent, **params))
    
    for cls in qdisc.get('classes', ()):
        _tc_class(stream, counters, cls, iface, qdisc['type'], qdisc['_id'], '')
        
def _tc_class(stream, counters, cls, iface, qdisc_type, parent_qdisc, parent_cls):
    '''
    Writes a tc class to the stream.
    Also writes any filters required from the parent qdisc.
    '''
    params = { 'id': counters.get_class_id(parent_qdisc), 'iface': iface, 'qdisc_type': qdisc_type, 'parent_qdisc': parent_qdisc, 'parent_cls': parent_cls , 'options': ''}
    params.update(cls)
    
    _tc_comment(stream, cls)
    
    # add the filters
    params['filter_parent'] = 1 if qdisc_type == 'htb' else parent_qdisc
    for match in cls.get('filters', ()):
        stream.write('tc filter add dev {iface} parent {filter_parent}: u32 {match} flowid {parent_qdisc}:{id}\n'.format(match=match, **params))
    
    if qdisc_type != 'prio': # these are automatically created    
        stream.write('tc class add dev {iface} parent {parent_qdisc}:{parent_cls} classid {parent_qdisc}:{id} {qdisc_type} {options}\n'.format(**params))
    
    if 'qdisc' in cls:
        _tc_qdisc(stream, counters, cls['qdisc'], iface, parent_qdisc, params['id'])

    for subcls in cls.get('classes', ()):
        _tc_class(stream, counters, subcls, iface, qdisc_type, parent_qdisc, params['id'])

def _compile_tc(iface, qdisc, stream):
    
    stream.write('#!/bin/bash\n')
    stream.write('set -e\n\n') # catch all errors
    
    stream.write('## AUTOGENERATED TC FOR {0} - DO NOT EDIT ##\n'.format(iface))
    
    counters = Counters()
    
    _tc_comment(stream, qdisc)
    stream.write('tc qdisc del dev {0} root || true\n'.format(iface))
    
    _tc_qdisc(stream, counters, qdisc, iface, None, None)

def _get_script_name(interface):
    return _SHAPING_SCRIPT.format(interface)

def _cmd_exec(cmd):
    result = __salt__['cmd.run_all'](cmd)
    
    if result['retcode'] != 0:
        raise Exception("Command returned {0}: {1}".format(result['retcode'], result['stderr']))
                        
    return result['stdout']

def get_tc_script(interface, filename=None):
    '''
    Get the current contents of the traffic shaping script
    
    CLI Example::
        
        salt '*' shaping.get_tc_script eth0
    '''
    if not filename:
        filename = _get_script_name(interface)
        
    if not os.path.exists(filename):
        return None
    
    return open(filename, 'r').readlines()       

def build_tc_script(interface, qdisc, filename=None, testing=False):
    '''
    Build the traffic shaping script
    
    CLI Example::

        salt '*' shaping.build_tc_script eth0 <settings>
    '''
    if not filename:
        filename = _get_script_name(interface)
    
    if testing:
        stream = StringIO.StringIO()
    else:
        stream = open(_get_script_name(interface), 'w+')
    
    if not qdisc:
        raise Exception("No qdisc passed")
    
    _compile_tc(interface, qdisc, stream)
    
    stream.flush()
    stream.seek(0)
    
    if not testing:
        os.chmod(filename, 0755)
    
    return stream.readlines()

def enable(iface):
    '''
    Enable shaping on an interface.  Executes the `/etc/tc_shaping_<iface>` script
    built by shaping.build_tc_script
    
    CLI Example::
    
        salt '*' shaping.enable eth0
    '''
    script = _get_script_name(iface)
    
    if not os.path.exists(script):
        raise Exception("Script for {0} has not yet been built".format(iface))
    
    return _cmd_exec(_get_script_name(iface))

def disable(iface):
    '''
    Disable shaping on an interface.  Restores the default pfifo_fast qdisc.

    CLI Example::

        salt '*' shaping.disable eth0
    '''
    return _cmd_exec('tc qdisc del dev {0} root'.format(iface))

def test(iface):
    '''
    Testing
    '''
    import yaml

    test_data = '{0}/shaping_test.yaml'.format(os.path.dirname(os.path.realpath(__file__)))
    data = yaml.load(open(test_data, 'r'))
    
    #return data[iface]
    return build_tc_script(iface, data[iface]['qdisc'], testing=True)
    

if __name__ == '__main__':
    test('eth0')