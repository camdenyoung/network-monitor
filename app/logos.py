"""Small raster project logos stored in SQLite so backups remain self-contained."""
import hashlib
import struct
import zlib

MAX_BYTES = 2 * 1024 * 1024
MAX_DIMENSION = 4096


def ensure_table(db):
    db.execute('''CREATE TABLE IF NOT EXISTS project_logos (
        project INTEGER PRIMARY KEY REFERENCES projects(id) ON DELETE CASCADE,
        image BLOB NOT NULL, mime TEXT NOT NULL, digest TEXT NOT NULL
    )''')


def image_type(data):
    """Check raster framing/dimensions without accepting active formats such as SVG.

    The browser additionally decodes the selected file before upload. Files are
    bounded here too, since the API can be called independently of the browser.
    """
    if not 0 < len(data) <= MAX_BYTES:
        raise ValueError('Logos must be no larger than 2 MB')
    width = height = 0
    if data.startswith(b'\x89PNG\r\n\x1a\n'):
        offset, has_image, has_end = 8, False, False
        while offset + 12 <= len(data):
            length = struct.unpack('>I', data[offset:offset + 4])[0]
            end = offset + 12 + length
            if end > len(data):
                raise ValueError('Truncated PNG')
            kind = data[offset + 4:offset + 8]
            chunk = data[offset + 8:offset + 8 + length]
            checksum = struct.unpack('>I', data[offset + 8 + length:end])[0]
            if zlib.crc32(kind + chunk) & 0xffffffff != checksum:
                raise ValueError('Invalid PNG checksum')
            if offset == 8:
                if kind != b'IHDR' or length != 13:
                    raise ValueError('Invalid PNG header')
                width, height = struct.unpack('>II', chunk[:8])
            has_image |= kind == b'IDAT'
            offset = end
            if kind == b'IEND':
                has_end = length == 0 and offset == len(data)
                break
        if not has_image or not has_end:
            raise ValueError('Incomplete PNG')
        mime = 'image/png'
    elif data.startswith(b'\xff\xd8') and data.endswith(b'\xff\xd9'):
        offset, has_scan = 2, False
        while offset + 4 <= len(data):
            if data[offset] != 0xff:
                raise ValueError('Invalid JPEG marker')
            while offset < len(data) and data[offset] == 0xff:
                offset += 1
            if offset >= len(data):
                break
            marker = data[offset]
            offset += 1
            if marker == 0xda:  # Image scan follows the dimension-bearing header.
                has_scan = True
                break
            if marker == 0xd9:
                break
            if offset + 2 > len(data):
                raise ValueError('Truncated JPEG')
            length = struct.unpack('>H', data[offset:offset + 2])[0]
            if length < 2 or offset + length > len(data):
                raise ValueError('Invalid JPEG segment')
            if marker in (0xc0, 0xc1, 0xc2) and length >= 8:
                height, width = struct.unpack('>HH', data[offset + 3:offset + 7])
            offset += length
        if not has_scan:
            raise ValueError('Incomplete JPEG')
        mime = 'image/jpeg'
    else:
        raise ValueError('Use a PNG or JPEG image')
    if not 1 <= width <= MAX_DIMENSION or not 1 <= height <= MAX_DIMENSION:
        raise ValueError('Logo dimensions must be 1–4096 pixels per side')
    return mime


def save(db, project, data):
    if not db.execute('SELECT id FROM projects WHERE id=?', (project,)).fetchone():
        raise ValueError('Unknown project')
    mime = image_type(data)
    digest = hashlib.sha256(data).hexdigest()
    db.execute('''INSERT INTO project_logos VALUES(?,?,?,?)
        ON CONFLICT(project) DO UPDATE SET image=excluded.image,mime=excluded.mime,digest=excluded.digest''',
        (project, data, mime, digest))


def logo_url(project, digest, public=False):
    route = 'public-logo' if public else 'project-logo'
    return f'/api/{route}?project={project}&v={digest}' if digest else None
