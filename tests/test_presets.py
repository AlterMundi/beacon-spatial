"""Regression for duplicate Q IDs saving null and muting the actual filters."""
import copy
from html.parser import HTMLParser
import pytest
import webui

class IDs(HTMLParser):
    def __init__(self): super().__init__(); self.ids=[]
    def handle_starttag(self, tag, attrs):
        self.ids.extend(v for k,v in attrs if k=='id')

def test_q_controls_have_unique_input_and_display_ids():
    parser=IDs();parser.feed(webui.app.test_client().get('/').text)
    for n in range(1,13):
        assert parser.ids.count(f'q{n}')==1
        assert parser.ids.count(f'vq{n}')==1

@pytest.mark.parametrize('bad',[None,0,'NaN',float('inf'),-1,True])
def test_bad_q_never_reaches_osc(bad,monkeypatch):
    sent=[];monkeypatch.setattr(webui.osc,'send_message',lambda *x:sent.append(x))
    client=webui.app.test_client()
    assert client.post('/control',json={'address':'/beacon/q/1','value':bad}).status_code==400
    assert client.post('/control/batch',json={'updates':[{'address':'/beacon/q/1','value':bad}]}).json['sent']==0
    assert not sent

def test_old_null_q_preset_is_recovered_without_changing_mix(tmp_path,monkeypatch):
    monkeypatch.setattr(webui,'CONFIG_DIR',str(tmp_path))
    state={'bands':[{'q':None,'gain':.6,'az':90} for _ in range(12)]+[{'gain':.8}], 'master':.9,'mix':.85}
    original=copy.deepcopy(state)
    assert webui.app.test_client().post('/save_config',json={'name':'regression','state':state}).json['ok']
    saved=webui.app.test_client().post('/load_config',json={'name':'regression'}).json['state']
    assert saved['master']==.9 and saved['mix']==.85
    assert [b['q'] for b in saved['bands'][:12]]==[b['default_q'] for b in webui.BANDS[:12]]
    assert all(b['gain']==.6 and b['az']==90 for b in saved['bands'][:12])
    assert state==original
