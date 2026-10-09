"""GPT encoding for disposable regular files; no device-write API."""
import struct
import uuid
import zlib

from .manifest import MIB, require, validate

SECTOR = 512
ENTRIES = 128
ENTRY_SIZE = 128
TABLE_SECTORS = ENTRIES * ENTRY_SIZE // SECTOR
ESP_TYPE = "c12a7328-f81f-11d2-ba4b-00a0c93ec93b"
LINUX_TYPE = "0fc63daf-8483-4772-8e79-3d69d8477de4"


def plan(manifest, size):
    validate(manifest)
    require(type(size) is int and size % MIB == 0, "disk size must be an integral MiB")
    minimum = (2 + sum(p["mib"] for p in manifest["layout"]["partitions"])) * MIB
    require(size >= minimum, f"disk requires at least {minimum} bytes")
    start = MIB // SECTOR
    partitions = []
    for index, p in enumerate(manifest["layout"]["partitions"], 1):
        sectors = p["mib"] * MIB // SECTOR
        partitions.append(dict(p, number=index, first_lba=start, last_lba=start + sectors - 1,
                               type_guid=ESP_TYPE if index == 1 else LINUX_TYPE))
        start += sectors
    return {"sector_bytes": SECTOR, "disk_bytes": size,
            "disk_guid": manifest["layout"]["disk_guid"], "partitions": partitions}


def regions(p):
    """Return byte offsets and exact protective MBR/GPT bytes."""
    count = p["disk_bytes"] // SECTOR
    table = bytearray(ENTRIES * ENTRY_SIZE)
    for i, part in enumerate(p["partitions"]):
        struct.pack_into("<16s16sQQQ72s", table, i * ENTRY_SIZE,
                         uuid.UUID(part["type_guid"]).bytes_le,
                         uuid.UUID(part["partuuid"]).bytes_le,
                         part["first_lba"], part["last_lba"], 0,
                         part["role"].encode("utf-16-le"))
    def header(current, alternate, table_lba):
        data = bytearray(SECTOR)
        struct.pack_into("<8sIIIIQQQQ16sQIII", data, 0, b"EFI PART", 0x10000, 92, 0, 0,
                         current, alternate, 2 + TABLE_SECTORS, count - TABLE_SECTORS - 2,
                         uuid.UUID(p["disk_guid"]).bytes_le, table_lba, ENTRIES, ENTRY_SIZE,
                         zlib.crc32(table))
        struct.pack_into("<I", data, 16, zlib.crc32(data[:92]))
        return bytes(data)
    mbr = bytearray(SECTOR)
    struct.pack_into("<B3sB3sII", mbr, 446, 0, b"\0\2\0", 0xEE, b"\xff\xff\xff",
                     1, min(count - 1, 0xFFFFFFFF))
    mbr[510:512] = b"\x55\xaa"
    return [(0, bytes(mbr)), (SECTOR, header(1, count - 1, 2)),
            (2 * SECTOR, bytes(table)), ((count - TABLE_SECTORS - 1) * SECTOR, bytes(table)),
            ((count - 1) * SECTOR, header(count - 1, 1, count - TABLE_SECTORS - 1))]


def verify(file, p):
    file.seek(0, 2)
    require(file.tell() == p["disk_bytes"], "disk image length changed")
    for offset, expected in regions(p):
        file.seek(offset)
        require(file.read(len(expected)) == expected, f"GPT mismatch at offset {offset}")
    return {"primary_gpt": "matched", "backup_gpt": "matched", "protective_mbr": "matched",
            "partitions": p["partitions"]}
