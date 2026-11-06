"""Portable inventory files and reviewed, atomic merge/update imports."""
from datetime import datetime
import hashlib
import hmac
import ipaddress
import json
import secrets

from . import service_library

FORMAT = 'network-monitor-inventory'
VERSION = 1
MAX_IMPORT_BYTES = 10 * 1024 * 1024
MAX_DEVICES = 5000
MAX_DEFAULTS = 10000
_REVIEW_KEY = secrets.token_bytes(32)


class InventoryImportError(ValueError):
    """Import feedback must never echo credentials or unvalidated file contents."""


def address_key(value):
    parsed = ipaddress.ip_address(value.strip())
    return str(getattr(parsed, 'ipv4_mapped', None) or parsed)


def export_document(db):
    defaults = {}
    for row in db.execute('SELECT * FROM device_service_defaults ORDER BY device,name,id'):
        definition = {field: row[field] for field in service_library.FIELDS}
        definition['state_map'] = json.loads(definition['state_map'])
        defaults.setdefault(row['device'], []).append(definition)
    devices = [{'name':row['name'], 'model':row['model'], 'address':row['address'],
                'service_defaults':defaults.get(row['id'], [])}
               for row in db.execute('SELECT * FROM devices ORDER BY name,id')]
    return {'format':FORMAT, 'version':VERSION,
            'exported_at':datetime.now().astimezone().isoformat(timespec='seconds'),
            'devices':devices}


def validate_document(document, validate_device, validate_service):
    if (not isinstance(document, dict) or document.get('format') != FORMAT
            or type(document.get('version')) is not int or document['version'] != VERSION
            or set(document) - {'format','version','exported_at','devices'}):
        raise InventoryImportError('Choose a Network Monitor inventory export with format version 1.')
    if 'exported_at' in document and (not isinstance(document['exported_at'], str) or len(document['exported_at']) > 100):
        raise InventoryImportError('Invalid inventory export metadata.')
    devices = document.get('devices')
    if not isinstance(devices, list) or len(devices) > MAX_DEVICES:
        raise InventoryImportError(f'Inventory must contain at most {MAX_DEVICES} devices.')
    result, names, total = [], set(), 0
    for index, entry in enumerate(devices, 1):
        if not isinstance(entry, dict) or set(entry) != {'name','model','address','service_defaults'}:
            raise InventoryImportError(f'Device {index} needs a Device ID, model, IP address and service defaults.')
        try:
            name, model, address = validate_device(entry)
        except (ValueError, TypeError, KeyError, AttributeError):
            raise InventoryImportError(f'Device {index} has an invalid Device ID, model or IP address.') from None
        if name in names:
            raise InventoryImportError(f'Device {index} repeats a Device ID in this file.')
        names.add(name)
        definitions = entry['service_defaults']
        if not isinstance(definitions, list):
            raise InventoryImportError(f'Device {index} needs a list of service defaults.')
        total += len(definitions)
        if total > MAX_DEFAULTS:
            raise InventoryImportError(f'Inventory may contain at most {MAX_DEFAULTS} service defaults.')
        try:
            defaults = service_library.validate_document(
                {'format':service_library.FORMAT, 'version':service_library.VERSION, 'services':definitions},
                validate_service)
        except service_library.LibraryImportError as error:
            raise InventoryImportError(f'Device {index}: {error}') from None
        result.append({'name':name, 'model':model, 'address':address, 'defaults':defaults})
    return result


def _plan(db, document, mode, validate_device, validate_service):
    if mode not in ('merge', 'update'):
        raise InventoryImportError('Choose Merge or Update existing.')
    incoming = validate_document(document, validate_device, validate_service)
    devices = [dict(row) for row in db.execute('SELECT * FROM devices ORDER BY id')]
    defaults = [dict(row) for row in db.execute('SELECT * FROM device_service_defaults ORDER BY id')]
    existing = {row['name']:row for row in devices}
    old_default_names = {}
    for row in defaults:
        old_default_names.setdefault(row['device'], []).append(row['name'])
    changes, entries = [], []
    added = updated = skipped = 0
    for item in incoming:
        current = existing.get(item['name'])
        if current and mode == 'merge':
            skipped += 1
            entries.append({'action':'skip','name':item['name'],'reason':'Device ID already exists'})
            continue
        action = 'update' if current else 'add'
        added += int(current is None)
        updated += int(current is not None)
        changes.append({**item, 'device':current['id'] if current else None})
        incoming_default_names = [definition[0] for definition in item['defaults']]
        incoming_default_set = set(incoming_default_names)
        entries.append({'action':action,'name':item['name'],'model':item['model'],
                        'address':item['address'],'previous_address':current['address'] if current else None,
                        'defaults':len(item['defaults']),
                        'default_names':incoming_default_names,
                        'removed_defaults':[name for name in old_default_names.get(current['id'], [])
                            if name not in incoming_default_set] if current else []})

    # Validate the final inventory, so legitimate two-device IP swaps can commit
    # atomically. Untouched legacy records are preserved, never silently rewritten.
    changed = {item['name']:item for item in changes}
    owners = {}
    for item in [changed.get(row['name'], row) for row in devices] + [item for item in changes if item['device'] is None]:
        if not item['address']:
            continue
        try:
            key = address_key(item['address'])
        except (ValueError, AttributeError):
            continue
        owners.setdefault(key, []).append(item['name'])
    conflicts = []
    for item in changes:
        if not item['address']:
            continue
        group = owners[address_key(item['address'])]
        if len(group) > 1:
            # Keep pathological files with thousands of identical IPs bounded.
            others = [name for name in group[:11] if name != item['name']][:10]
            conflicts.append({'name':item['name'],'address':item['address'],'owners':others,
                              'additional_owners':len(group) - 1 - len(others)})

    # Bind approval to the file, mode and current inventory/defaults. HMAC avoids
    # exposing a dictionary-testable hash of stored communities. Restart => re-review.
    try:
        payload = json.dumps([mode, document, devices, defaults], sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
    except (ValueError, TypeError, RecursionError):
        raise InventoryImportError('Inventory file is too complex or contains invalid data.') from None
    token = hmac.new(_REVIEW_KEY, payload, hashlib.sha256).hexdigest()
    preview = {'added':added, 'updated':updated, 'skipped':skipped,
               'defaults':sum(len(item['defaults']) for item in changes),
               'entries':entries, 'conflicts':conflicts, 'token':token}
    return changes, preview


def preview_document(db, document, mode, validate_device, validate_service):
    return _plan(db, document, mode, validate_device, validate_service)[1]


def import_document(db, document, mode, token, validate_device, validate_service, allocate_id, save_default):
    """Caller holds the mutation lock and transaction; nothing is partially imported."""
    changes, preview = _plan(db, document, mode, validate_device, validate_service)
    if not isinstance(token, str) or len(token) != 64 or not token.isascii() or not hmac.compare_digest(token, preview['token']):
        raise InventoryImportError('Inventory changed or the preview is missing/outdated. Close this preview and review the file again.')
    if preview['conflicts']:
        raise InventoryImportError('Resolve the IP conflicts in the preview before importing.')
    for item in changes:
        device = item['device']
        if device is None:
            device = allocate_id(db, 'devices')
            db.execute('INSERT INTO devices(id,name,model,address) VALUES(?,?,?,?)',
                       (device,item['name'],item['model'],item['address']))
        else:
            db.execute('UPDATE devices SET model=?,address=? WHERE id=?', (item['model'],item['address'],device))
        # Replace the default set but retain IDs for defaults with matching names.
        # Project services are independent rows and are never touched here.
        old = {row['name']:row['id'] for row in db.execute('SELECT id,name FROM device_service_defaults WHERE device=?', (device,))}
        incoming_names = {definition[0] for definition in item['defaults']}
        for name, record in old.items():
            if name not in incoming_names:
                db.execute('DELETE FROM device_service_defaults WHERE id=? AND device=?', (record,device))
        for definition in item['defaults']:
            save_default(db, device, definition, old.get(definition[0]))
    return {key:preview[key] for key in ('added','updated','skipped','defaults')}
