"""HTTP proxy in front of Jellyfin that fails selected requests on demand.

Point an add-on at http://faultproxy:8096 instead of http://jellyfin:8096.
Every request is passed through unchanged unless it matches a rule in
/data/faults.json, which is read on every request, e.g.

    {"rules": [{"match": "EnableTotalRecordCount=True", "method": "GET",
                "status": 500, "times": 1}]}

"match" is a regular expression searched in the request target, ignoring
case, "method" is optional,
"status" answers with that HTTP status, "drop": true closes the connection
without an answer (a connection error for the client), "delay" waits that
many seconds before passing the request on (a read timeout for the client).
"times" limits how often a rule fires; it is counted down in the file.
Handled requests are appended to /data/faults.log.

Plain requests are forwarded with "Connection: close", so each connection
carries one request and every request is checked. WebSocket upgrades are
piped through as they are, and so are chunked request bodies.
"""

import json
import os
import re
import socket
import socketserver
import threading
import time

UPSTREAM = (os.environ.get('UPSTREAM_HOST', 'jellyfin'), int(os.environ.get('UPSTREAM_PORT', '8096')))
RULES = '/data/faults.json'
LOG = '/data/faults.log'
lock = threading.Lock()


def take_rule(method, target):
    """Return the first rule matching the request and count it down."""
    with lock:
        try:
            with open(RULES) as f:
                config = json.load(f)
        except (OSError, ValueError):
            return None
        for rule in config.get('rules', []):
            if rule.get('method', method).upper() != method:
                continue
            if not re.search(rule.get('match', ''), target, re.IGNORECASE):
                continue
            if 'times' in rule:
                if rule['times'] <= 0:
                    continue
                rule['times'] -= 1
                write_rules(config)
            return rule
    return None


def write_rules(config):
    # Replace the file in one step, kdev reads and writes it too
    tmp = RULES + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(config, f, indent=2)
    os.replace(tmp, RULES)


def log(line):
    with lock:
        with open(LOG, 'a') as f:
            f.write('{} {}\n'.format(time.strftime('%H:%M:%S'), line))


def pipe(source, target):
    try:
        while True:
            data = source.recv(65536)
            if not data:
                break
            target.sendall(data)
    except OSError:
        pass
    finally:
        try:
            target.shutdown(socket.SHUT_WR)
        except OSError:
            pass


class Handler(socketserver.BaseRequestHandler):
    def handle(self):
        client = self.request
        data = b''
        while b'\r\n\r\n' not in data:
            chunk = client.recv(65536)
            if not chunk:
                return
            data += chunk
        head, body = data.split(b'\r\n\r\n', 1)
        lines = head.decode('latin-1').split('\r\n')
        method, target = lines[0].split(' ')[:2]
        headers = [line for line in lines[1:] if line]
        names = {line.split(':', 1)[0].strip().lower(): line.split(':', 1)[1].strip() for line in headers}

        upgrade = 'upgrade' in names
        # A chunked body has no length up front: pipe it like a WebSocket
        stream = upgrade or 'chunked' in names.get('transfer-encoding', '').lower()
        length = int(names.get('content-length', 0))
        while not stream and len(body) < length:
            chunk = client.recv(65536)
            if not chunk:
                return
            body += chunk

        rule = None if upgrade else take_rule(method, target)
        if rule and rule.get('drop'):
            log('DROP {} {}'.format(method, target))
            return
        if rule and 'status' in rule:
            log('{} {} {}'.format(rule['status'], method, target))
            client.sendall('HTTP/1.1 {} Fault\r\nContent-Length: 0\r\nConnection: close\r\n\r\n'
                           .format(rule['status']).encode())
            return
        if rule and 'delay' in rule:
            log('DELAY {} {} {}'.format(rule['delay'], method, target))
            time.sleep(rule['delay'])

        if not upgrade:
            headers = [line for line in headers if not line.lower().startswith(('connection:', 'keep-alive:'))]
            headers.append('Connection: close')
        request = '\r\n'.join([lines[0]] + headers).encode('latin-1') + b'\r\n\r\n' + body

        upstream = socket.create_connection(UPSTREAM)
        try:
            upstream.sendall(request)
            if stream:
                thread = threading.Thread(target=pipe, args=(client, upstream), daemon=True)
                thread.start()
            pipe(upstream, client)
        finally:
            upstream.close()


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


if __name__ == '__main__':
    Server(('0.0.0.0', 8096), Handler).serve_forever()
