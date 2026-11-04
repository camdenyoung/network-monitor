"""Small external SNMP v2c/Modbus simulator for the synthetic load test.

Run this on another machine. OIDs and Modbus unit IDs identify virtual hosts;
sharing one simulator address deliberately leaves every host reachable by ping.
Timeout scenarios therefore exercise the more expensive host-up/service-down case.
"""
import heapq
import selectors
import socket
import socketserver
import struct
import threading
import time

OID_PREFIX = (1, 3, 6, 1, 4, 1, 99999)
PROFILES = (
    ('RSSI', -55, -80, 'dBm', 'below', -65, -75),
    ('Temperature', 35, 75, '°C', 'above', 55, 65),
    ('Supply voltage', 54, 40, 'V', 'below', 48, 44),
    ('Battery', 95, 10, '%', 'below', 30, 15),
    ('Port status', 1, 2, '', 'below', None, None),
)


def tlv(tag, payload):
    length = len(payload)
    if length < 128:
        encoded_length = bytes([length])
    else:
        raw = length.to_bytes((length.bit_length() + 7) // 8, 'big')
        encoded_length = bytes([128 | len(raw)]) + raw
    return bytes([tag]) + encoded_length + payload


def integer(value):
    length = max(1, (value.bit_length() + 8) // 8)
    return tlv(2, value.to_bytes(length, 'big', signed=True))


def parse_tlv(data, offset=0):
    if offset + 2 > len(data):
        raise ValueError('Incomplete BER value')
    tag, length = data[offset:offset + 2]
    start = offset + 2
    if length & 128:
        count = length & 127
        if not 1 <= count <= 4 or start + count > len(data):
            raise ValueError('Invalid BER length')
        length = int.from_bytes(data[start:start + count], 'big')
        start += count
    end = start + length
    if end > len(data):
        raise ValueError('Truncated BER value')
    return tag, data[start:end], end


def children(data):
    values, offset = [], 0
    while offset < len(data):
        tag, value, offset = parse_tlv(data, offset)
        values.append((tag, value))
    return values


def decode_oid(data):
    numbers, number = [], 0
    for byte in data:
        number = (number << 7) | (byte & 127)
        if not byte & 128:
            numbers.append(number)
            number = 0
    if not numbers or data[-1] & 128:
        raise ValueError('Invalid OID')
    first = min(2, numbers[0] // 40)
    return (first, numbers[0] - first * 40, *numbers[1:])


class Scenario:
    def __init__(self, kind='healthy', latency_ms=10, failure_percent=10, flap_period=30):
        self.kind = kind
        self.delay = latency_ms / 1000
        self.failure_percent = failure_percent
        self.flap_period = flap_period

    def affected(self, host, service):
        return (host * 37 + service * 17) % 100 < self.failure_percent

    def value(self, host, service, modbus=False):
        if not 1 <= host <= 247 or service < 1:
            raise ValueError('Unknown virtual host/service')
        affected = self.affected(host, service)
        if self.kind == 'timeouts' and affected:
            return None  # Drop the response; the real monitor's timeout expires.
        fault = self.kind == 'flapping' and affected and int(time.monotonic() / self.flap_period) % 2
        if modbus:
            return 4000 if fault else 5400  # Unsigned centivolts; app scale is 0.01.
        profile = PROFILES[(service - 1) % len(PROFILES)]
        return profile[2] if fault else profile[1]


def snmp_response(packet, scenario):
    """Respond to the numeric single-OID GETs used by production snmpget."""
    tag, body, end = parse_tlv(packet)
    fields = children(body)
    if tag != 48 or end != len(packet) or len(fields) != 3 or fields[0] != (2, b'\x01') or fields[2][0] != 160:
        raise ValueError('Expected SNMP v2c GET')
    pdu = children(fields[2][1])
    bindings = children(pdu[3][1])
    responses = []
    for tag, binding in bindings:
        oid, _null = children(binding)
        numbers = decode_oid(oid[1])
        if tag != 48 or oid[0] != 6 or numbers[:7] != OID_PREFIX or len(numbers) != 10 or numbers[-1] != 0:
            raise ValueError('Unknown synthetic OID')
        value = scenario.value(numbers[7], numbers[8])
        if value is None:
            return None
        responses.append(tlv(48, tlv(6, oid[1]) + integer(value)))
    response_pdu = tlv(162, tlv(*pdu[0]) + integer(0) + integer(0) + tlv(48, b''.join(responses)))
    return tlv(48, integer(1) + tlv(*fields[1]) + response_pdu)


def receive_exact(sock, count):
    result = b''
    while len(result) < count:
        part = sock.recv(count - len(result))
        if not part:
            raise ValueError('Connection closed')
        result += part
    return result


class ModbusHandler(socketserver.BaseRequestHandler):
    def handle(self):
        self.request.settimeout(5)
        try:
            header = receive_exact(self.request, 7)
            transaction, protocol, length, unit = struct.unpack('>HHHB', header)
            if protocol != 0 or length != 6:
                return
            function, register, count = struct.unpack('>BHH', receive_exact(self.request, 5))
            if function != 3 or count != 1:
                return
            value = self.server.scenario.value(unit, register + 1, modbus=True)
            if value is None:
                # Keep TCP open while the production client's receive timeout expires.
                self.request.recv(1)
                return
            time.sleep(self.server.scenario.delay)
            self.request.sendall(struct.pack('>HHHBBBH', transaction, 0, 5, unit, 3, 2, value))
        except (OSError, ValueError, struct.error):
            pass


class ModbusServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True
    request_queue_size = 256


def serve(bind, snmp_port, modbus_port, scenario):
    udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    udp.bind((bind, snmp_port))
    udp.setblocking(False)
    tcp = ModbusServer((bind, modbus_port), ModbusHandler)
    tcp.scenario = scenario
    threading.Thread(target=tcp.serve_forever, daemon=True).start()
    selector = selectors.DefaultSelector()
    selector.register(udp, selectors.EVENT_READ)
    pending, serial = [], 0
    print(f'Synthetic devices: UDP {snmp_port}, TCP {modbus_port}; scenario={scenario.kind}', flush=True)
    try:
        while True:
            delay = max(0, pending[0][0] - time.monotonic()) if pending else 1
            for _key, _mask in selector.select(timeout=min(1, delay)):
                packet, peer = udp.recvfrom(65535)
                try:
                    response = snmp_response(packet, scenario)
                    if response is not None:
                        serial += 1
                        heapq.heappush(pending, (time.monotonic() + scenario.delay, serial, peer, response))
                except (ValueError, IndexError):
                    continue
            while pending and pending[0][0] <= time.monotonic():
                _due, _serial, peer, response = heapq.heappop(pending)
                try:
                    udp.sendto(response, peer)
                except OSError:
                    pass  # A timed-out or disconnected poller may already be gone.
    except KeyboardInterrupt:
        pass
    finally:
        selector.close()
        udp.close()
        tcp.shutdown()
        tcp.server_close()
