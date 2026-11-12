import io
import tempfile
import types
import unittest
from pathlib import Path
from beacon_routes import configure,INPUT
from bounded_log import copy_tail

class RoutesTests(unittest.TestCase):
    def model(self):
        own=['SuperCollider:in_1','SuperCollider:in_2','SuperCollider:out_1','SuperCollider:out_2']
        ports=own+[INPUT,'R24 Analog Stereo:playback_FL','R24 Analog Stereo:playback_FR','other:mic','other:output','other:app']
        g={p:set() for p in ports};g['other:app'].add('other:output');g['other:output'].add('other:app')
        g[own[0]].add('other:mic');g['other:mic'].add(own[0])
        calls=[]
        def run(command,**kwargs):
            calls.append(command)
            if command[1]=='jack_lsp':
                return types.SimpleNamespace(stdout=''.join(p+'\n'+''.join('   '+peer+'\n' for peer in peers) for p,peers in g.items()))
            _,op,a,b=command
            if op=='jack_disconnect':g[a].remove(b);g[b].remove(a)
            elif op=='jack_connect':g[a].add(b);g[b].add(a)
            else:raise AssertionError(command)
        return g,calls,run
    def test_exact_r24_path_preserves_unrelated_links_and_is_idempotent(self):
        g,calls,run=self.model();result=configure('r24',run=run)
        self.assertEqual(len(result['verified_links']),3)
        self.assertEqual(g['SuperCollider:in_1'],{INPUT})
        self.assertEqual(g['other:app'],{'other:output'})
        calls.clear();configure('r24',run=run);self.assertTrue(all(c[1]=='jack_lsp' for c in calls))
    def test_missing_selected_input_never_falls_back(self):
        g,calls,run=self.model();g.pop(INPUT)
        with self.assertRaises(RuntimeError):configure('r24',run=run)
        self.assertEqual(len(calls),1)
    def test_check_only_never_repairs_silently(self):
        _,calls,run=self.model()
        with self.assertRaises(RuntimeError):configure('r24',check_only=True,run=run)
        self.assertEqual(len(calls),1)
    def test_log_retains_only_tail(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'log';copy_tail(io.BytesIO(b'a'*20000+b'z'*30),p,limit=1000)
            self.assertEqual(p.stat().st_size,1000);self.assertTrue(p.read_bytes().endswith(b'z'*30))

class SelectedPortsTests(unittest.TestCase):
    def test_exact_receiving_ports_do_not_require_r24(self):
        from unittest.mock import patch
        from beacon_routes import desired
        with patch.dict('os.environ',{'BEACON_INPUT_PORT':'Interface:input_2','BEACON_OUTPUT_LEFT':'Headphones:left','BEACON_OUTPUT_RIGHT':'Headphones:right'}):
            self.assertEqual(desired('r24'),[('Interface:input_2','SuperCollider:in_1'),('SuperCollider:out_1','Headphones:left'),('SuperCollider:out_2','Headphones:right')])
    def test_incomplete_receiving_selection_refuses_before_any_graph_write(self):
        from unittest.mock import patch
        from beacon_routes import desired
        with patch.dict('os.environ',{'BEACON_INPUT_PORT':'Interface:input_2'},clear=True):
            with self.assertRaises(ValueError):desired('r24')
