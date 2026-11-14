"""Select and verify only the Spatializer's own JACK links; never change defaults."""
import argparse
import json
import os
import subprocess

INPUT = 'R24 Analog Surround 7.1:capture_FL'
OUTPUTS = {'r24': ['R24 Analog Stereo'], 'internal': ['Built-in Audio Analog Stereo'],
           'both': ['R24 Analog Stereo', 'Built-in Audio Analog Stereo']}

def graph(run=subprocess.run):
    result = run(['pw-jack', 'jack_lsp', '-c'], check=True, capture_output=True, text=True, timeout=3)
    links = {}; port = None
    for line in result.stdout.splitlines():
        if line.startswith(' ') and port is not None:
            links[port].add(line.strip())
        elif line:
            port = line; links[port] = set()
    return links

def desired(output):
    selected=[os.environ.get(key) for key in ('BEACON_INPUT_PORT','BEACON_OUTPUT_LEFT','BEACON_OUTPUT_RIGHT')]
    if any(selected):
        if not all(selected) or any(len(value)>512 or '\n' in value for value in selected):
            raise ValueError('Select one exact JACK input and both output ports')
        return [(selected[0],'SuperCollider:in_1'),('SuperCollider:out_1',selected[1]),('SuperCollider:out_2',selected[2])]
    pairs = [(INPUT, 'SuperCollider:in_1')]
    for name in OUTPUTS[output]:
        pairs += [('SuperCollider:out_1', name + ':playback_FL'),
                  ('SuperCollider:out_2', name + ':playback_FR')]
    return pairs

def configure(output, *, check_only=False, run=subprocess.run):
    links = graph(run); pairs = desired(output)
    voice = os.environ.get('BEACON_VOICE_INPUT_PORT','')
    if voice and (len(voice)>512 or '\n' in voice or voice==pairs[0][0]):
        raise ValueError('Select a distinct exact voice input port')
    # A separate clean mono path to each selected output, outside all SC filters.
    voice_pairs = [(voice,b) for a,b in pairs if a.startswith('SuperCollider:out_')] if voice else []
    pairs += voice_pairs
    own = ('SuperCollider:in_1', 'SuperCollider:in_2', 'SuperCollider:out_1', 'SuperCollider:out_2')
    expected = {p: set() for p in own}
    for a,b in pairs:
        if a not in links or b not in links:
            raise RuntimeError('Audio port unavailable: ' + (a if a not in links else b))
        if a in expected or b in expected:
            expected[a if a in expected else b].add(b if a in expected else a)
    for port in own:
        if port not in links:
            raise RuntimeError('Audio port unavailable: ' + port)
    if not check_only:
        for port in own:
            for peer in links[port] - expected[port]:
                run(['pw-jack', 'jack_disconnect', port, peer], check=True, capture_output=True, timeout=3)
        for a,b in pairs:
            if b not in links[a]:
                run(['pw-jack', 'jack_connect', a, b], check=True, capture_output=True, timeout=3)
        links = graph(run)
    if any(b not in links[a] for a,b in pairs) or any(links[port] != peers for port,peers in expected.items()):
        raise RuntimeError('Spatializer audio links do not match the selected input/output')
    return {'input':'R24 channel1', 'output':output, 'verified_links':pairs, 'voice_input':voice or None, 'voice_filtered':False if voice else None}

if __name__ == '__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',choices=OUTPUTS,default='r24');parser.add_argument('--check',action='store_true');args=parser.parse_args()
    print(json.dumps(configure(args.output,check_only=args.check)))
