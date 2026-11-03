"""Portable, versioned library files; importing never touches materialized services."""
from datetime import datetime
import json
import math

FORMAT = 'network-monitor-service-library'
VERSION = 1
MAX_IMPORT_BYTES = 5 * 1024 * 1024
MAX_SERVICES = 5000
FIELDS = ('name', 'kind', 'target', 'community', 'unit', 'scale', 'units',
          'direction', 'warning', 'critical', 'persistence', 'value_type', 'state_map')


class LibraryImportError(ValueError):
    """Safe import feedback that does not echo credentials or file contents."""


def export_document(db):
    services = []
    for row in db.execute('SELECT * FROM service_templates ORDER BY name,id'):
        item = {field: row[field] for field in FIELDS}
        item['state_map'] = json.loads(item['state_map'])
        services.append(item)
    return {'format': FORMAT, 'version': VERSION,
            'exported_at': datetime.now().astimezone().isoformat(timespec='seconds'),
            'services': services}


def validate_document(document, validate_service):
    """Validate the complete file before any DELETE/INSERT can occur."""
    if (not isinstance(document, dict) or document.get('format') != FORMAT
            or type(document.get('version')) is not int or document['version'] != VERSION):
        raise LibraryImportError('Choose a Network Monitor service-library export with format version 1.')
    entries = document.get('services')
    if not isinstance(entries, list) or len(entries) > MAX_SERVICES:
        raise LibraryImportError(f'The library must contain a list of at most {MAX_SERVICES} services.')
    definitions, names = [], set()
    for index, entry in enumerate(entries, 1):
        error = f'Service {index} has an invalid definition. Check its protocol, target, thresholds and state mappings.'
        if not isinstance(entry, dict) or set(entry) - set(FIELDS):
            raise LibraryImportError(error)
        for field in ('name', 'kind', 'target', 'community', 'units', 'direction', 'value_type'):
            if field in entry and not isinstance(entry[field], str):
                raise LibraryImportError(error)
        for field in ('unit', 'persistence'):
            if field in entry and type(entry[field]) is not int:
                raise LibraryImportError(error)
        for field in ('scale', 'warning', 'critical'):
            value = entry.get(field)
            if value is None and field != 'scale':
                continue
            if field not in entry:
                continue
            if type(value) not in (int, float) or not math.isfinite(value):
                raise LibraryImportError(error)
        if 'state_map' in entry and not isinstance(entry['state_map'], dict):
            raise LibraryImportError(error)
        try:
            definition = validate_service(entry)
        except (ValueError, TypeError, KeyError, OverflowError):
            raise LibraryImportError(error) from None
        if definition[0] in names:
            raise LibraryImportError(f'Service {index} repeats a service name in this file. Names must be unique.')
        names.add(definition[0])
        definitions.append(definition)
    return definitions


def import_document(db, document, mode, validate_service):
    """Caller supplies a transaction: failed imports leave the entire library intact.

    Merge keeps exact, case-sensitive name matches; Replace affects only this
    library table. Neither changes project services or device defaults.
    """
    if mode not in ('merge', 'replace'):
        raise LibraryImportError('Choose Merge or Replace.')
    definitions = validate_document(document, validate_service)
    existing = {row[0] for row in db.execute('SELECT name FROM service_templates')}
    replaced = len(existing) if mode == 'replace' else 0
    if mode == 'replace':
        db.execute('DELETE FROM service_templates')
        existing.clear()
    added = skipped = 0
    columns = ','.join(FIELDS)
    placeholders = ','.join('?' for _ in FIELDS)
    for definition in definitions:
        if definition[0] in existing:
            skipped += 1
            continue
        db.execute(f'INSERT INTO service_templates({columns}) VALUES({placeholders})', definition)
        added += 1
    return {'added': added, 'skipped': skipped, 'replaced': replaced,
            'total': db.execute('SELECT COUNT(*) FROM service_templates').fetchone()[0]}
