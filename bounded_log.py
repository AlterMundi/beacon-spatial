"""Keep one bounded tail of a component's output; no rotating archive."""
import sys
from pathlib import Path

LIMIT = 1048576

def copy_tail(stream, path, limit=LIMIT):
    tail = bytearray()
    with open(path, 'wb', buffering=0) as out:
        while True:
            chunk = stream.read1(8192) if hasattr(stream, 'read1') else stream.read(8192)
            if not chunk:
                break
            tail.extend(chunk)
            del tail[:-limit]
            out.seek(0)
            out.write(tail)
            out.truncate()

if __name__ == '__main__':
    copy_tail(sys.stdin.buffer, Path(sys.argv[1]))
