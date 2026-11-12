"""Native CoreAudio companion to start-beacon.sh; never installs software or opens a camera."""
from __future__ import annotations
import argparse
import errno
import json
import os
from pathlib import Path
import pty
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time

from bounded_log import copy_tail


def executable(name, env, root):
    override=env.get('BEACON_'+name.upper())
    if override:
        if Path(override).is_file():return override
        raise ValueError('Missing configured '+name)
    found=shutil.which(name)
    if found:return found
    directory='MacOS' if name=='sclang' else 'Resources'
    candidate=Path('/Applications/SuperCollider.app/Contents')/directory/name
    if candidate.is_file():return str(candidate)
    raise ValueError('Install SuperCollider or select BEACON_'+name.upper())


def plan(root, env, args, find=executable):
    """Pure launch description: selected device names are exact CoreAudio names."""
    root=Path(root)
    input_device=env.get('BEACON_INPUT_DEVICE','')
    output_device=env.get('BEACON_OUTPUT_DEVICE','')
    if not output_device or (args.source=='live' and not input_device):
        raise ValueError('Select exact BEACON_INPUT_DEVICE and BEACON_OUTPUT_DEVICE CoreAudio names first')
    if args.source=='file':
        audio=Path(env.get('BEACON_AUDIO_FILE',str(root/'harmonic_beacon_2026_05_13_session.wav')))
        if not audio.is_file():raise ValueError('Selected Beacon WAV is missing; choose an existing file or live input')
    python=next((p for p in (root/'venv/bin/python3',root/'.venv/bin/python') if p.is_file()),None)
    if python is None:raise ValueError('Install the existing Spatializer requirements into its venv first')
    return {'scsynth':[find('scsynth',env,root),'-u','57110','-i','2' if args.source=='live' else '0','-o','2','-S','48000','-l','32','-H',input_device if args.source=='live' else '',output_device],
            'sclang':[find('sclang',env,root),'-u',str(args.osc_port),'-d',str(root),str(root/'beacon.scd')],
            'web':[str(python),str(root/'webui.py')],
            'input_device':input_device if args.source=='live' else None,'output_device':output_device,'source':args.source,
            'audio_evidence':'selected CoreAudio command; physical input/output and hearing require receiving checks'}


def check_ports(osc_port):
    for port,kind in ((57110,socket.SOCK_DGRAM),(osc_port,socket.SOCK_DGRAM),(5050,socket.SOCK_STREAM)):
        with socket.socket(socket.AF_INET,kind) as sock:
            try:sock.bind(('127.0.0.1',port))
            except OSError as exc:raise ValueError('Existing process owns port'+str(port)+'; preserve it instead of starting another stack') from exc


class PtyReader:
    def __init__(self,fd):self.stream=os.fdopen(fd,'rb',buffering=0)
    def read(self,size):
        try:return self.stream.read(size)
        except OSError as exc:
            if exc.errno==errno.EIO:return b''
            raise
    def close(self):self.stream.close()


def run(root, env, args, commands):
    state=Path(env.get('BEACON_LOG_DIR',str(Path.home()/'.local/state/beacon-spatial')));state.mkdir(parents=True,exist_ok=True)
    children={};readers=[];threads=[];stop=threading.Event();started=time.monotonic()
    def record(phase,**extra):
        data={'phase':phase,'backend':'coreaudio','source':commands['source'],
              'input_device':commands['input_device'],'output_device':commands['output_device'],
              'owned_pids':{k:p.pid for k,p in children.items()},'hardware_acceptance_observed':False,**extra}
        pending=state/'native.pending';pending.write_text(json.dumps(data,indent=2)+'\n');pending.replace(state/'native.json')
    def start(name,terminal=False):
        if terminal:
            master,slave=pty.openpty()
            try:child=subprocess.Popen(commands[name],cwd=root,env=env,stdin=slave,stdout=slave,stderr=slave,start_new_session=True)
            except BaseException:os.close(master);raise
            finally:os.close(slave)
            reader=PtyReader(master)
        else:
            child=subprocess.Popen(commands[name],cwd=root,env=env,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,start_new_session=True)
            reader=child.stdout
        children[name]=child;readers.append(reader)
        thread=threading.Thread(target=copy_tail,args=(reader,state/(name+'.log')),daemon=True);threads.append(thread);thread.start()
        record('starting')
    for sig in (signal.SIGINT,signal.SIGTERM):signal.signal(sig,lambda *_:stop.set())
    failure=None
    try:
        check_ports(args.osc_port)
        start('scsynth')
        if stop.wait(2):return
        if children['scsynth'].poll() is not None:raise RuntimeError('scsynth failed opening the selected CoreAudio devices; inspect scsynth.log')
        start('sclang',terminal=True)
        if stop.wait(2):return
        start('web');record('processes_started')
        print('Spatializer CoreAudio iniciado; comprobar entrada, salida y escucha en esta Mac.',flush=True)
        while not stop.wait(.5):
            for name,child in children.items():
                if child.poll() is not None:raise RuntimeError(name+' exited; inspect its bounded log')
            if time.monotonic()-started>=args.max_runtime_s:break
    except Exception as exc:
        failure=str(exc);raise
    finally:
        for child in reversed(list(children.values())):
            try:os.killpg(child.pid,signal.SIGTERM)
            except ProcessLookupError:pass
        deadline=time.monotonic()+4
        for child in children.values():
            try:child.wait(timeout=max(.01,deadline-time.monotonic()))
            except subprocess.TimeoutExpired:
                try:os.killpg(child.pid,signal.SIGKILL)
                except ProcessLookupError:pass
                child.wait(timeout=.5)
        for thread in threads:thread.join(timeout=.2)
        for reader in readers:reader.close()
        record('failed' if failure else 'stopped',error=failure,exit_codes={k:p.returncode for k,p in children.items()})


def main():
    parser=argparse.ArgumentParser(description='Native macOS Spatializer; same DSP/OSC/UI, explicit CoreAudio devices')
    group=parser.add_mutually_exclusive_group();group.add_argument('--live',dest='source',action='store_const',const='live');group.add_argument('--file',dest='source',action='store_const',const='file');parser.set_defaults(source='live')
    parser.add_argument('--no-https',action='store_true',help='local UI; no tunnel is created by the native launcher')
    parser.add_argument('--osc-host',default='127.0.0.1');parser.add_argument('--osc-port',type=int,default=57120)
    parser.add_argument('--max-runtime-s',type=float,default=28800);parser.add_argument('--describe',action='store_true')
    args=parser.parse_args()
    if not 1<=args.osc_port<=65535 or not 0<args.max_runtime_s<=28800:parser.error('Invalid port or lifetime (maximum8hours)')
    if args.osc_host!='127.0.0.1':parser.error('Native receiving launch currently supports local OSC only')
    root=Path(__file__).resolve().parent
    env=dict(os.environ,BEACON_SOURCE=args.source,BEACON_OSC_HOST=args.osc_host,BEACON_OSC_PORT=str(args.osc_port),BEACON_WEB_HOST='127.0.0.1',PYTHONDONTWRITEBYTECODE='1',QT_QPA_PLATFORM='offscreen')
    commands=plan(root,env,args)
    if args.describe:print(json.dumps(commands,indent=2));return
    run(root,env,args,commands)

if __name__=='__main__':main()
