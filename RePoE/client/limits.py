"""Client byte limits, shared by acquisition and native input validation."""

from .source_io import MIB

MAX_RESOURCE = 64 * MIB
MAX_INDEX_READ = 64 * MIB
MAX_SELECTED_RAW = 128 * MIB
MAX_NETWORK = 128 * MIB
MAX_CACHE_BYTES = 128 * MIB
MAX_ARCHIVE_BYTES = 128 * MIB

MAX_RANGE = 4 * MIB
MAX_BUNDLE_RAW = 512 * MIB
MAX_BUNDLE_COMPRESSED = 256 * MIB
MAX_CHUNKS = 4096
MAX_CHUNK_RAW = MIB
MAX_CHUNK_COMPRESSED = 2 * MIB
MAX_RECORDS = 4096

# Decoded JSON and legacy transfer bounds are independent of raw client sizes.
MAX_CRAFTING_TABLE_JSON_BYTES = 64 * MIB
MAX_CRAFTING_TOTAL_JSON_BYTES = 96 * MIB
MAX_DECODED_TABLE_PAIR_BYTES = 128 * MIB
MAX_TRANSFER_COMPRESSED_BYTES = 32 * MIB
MAX_TRANSFER_DECODED_BYTES = 256 * MIB
MAX_TARGET_TABLE_JSON_BYTES = 128 * MIB


def utilisation(resource_sizes, *, network_reserved=None):
    """Percentages for existing command summaries; leave receipts unchanged."""
    sizes = list(resource_sizes)
    result = {
        "largest_resource_percent": round(100 * max(sizes, default=0) / MAX_RESOURCE, 2),
        "selected_raw_percent": round(100 * sum(sizes) / MAX_SELECTED_RAW, 2),
    }
    if network_reserved is not None:
        result["network_reserved_percent"] = round(100 * network_reserved / MAX_NETWORK, 2)
    return result
