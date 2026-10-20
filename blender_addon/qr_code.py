"""
Minimal, dependency-free QR Code generator in pure Python (ISO/IEC 18004).
Byte mode, error correction level M, versions 1-10 (up to ~213 bytes).
Generates a binary 2D matrix (True for dark, False for light).

Algorithm structure follows Project Nayuki's reference design
(correct codeword counts, block splitting/interleaving, BCH format bits).
"""

# --- Tables for EC level M (index = version) ---
_ECC_PER_BLOCK_M = [-1, 10, 16, 26, 18, 24, 16, 18, 22, 22, 26]
_NUM_BLOCKS_M = [-1, 1, 1, 1, 2, 2, 4, 4, 4, 5, 5]
_ECL_M_FORMAT_BITS = 0  # L=1, M=0, Q=3, H=2
_MAX_VERSION = 10


# --- GF(256) arithmetic, primitive polynomial 0x11D ---
def _gf_mul(x, y):
    z = 0
    for i in reversed(range(8)):
        z = (z << 1) ^ ((z >> 7) * 0x11D)
        z ^= ((y >> i) & 1) * x
    return z & 0xFF


def _rs_divisor(degree):
    result = [0] * (degree - 1) + [1]
    root = 1
    for _ in range(degree):
        for j in range(len(result)):
            result[j] = _gf_mul(result[j], root)
            if j + 1 < len(result):
                result[j] ^= result[j + 1]
        root = _gf_mul(root, 0x02)
    return result


def _rs_remainder(data, divisor):
    result = [0] * len(divisor)
    for b in data:
        factor = b ^ result.pop(0)
        result.append(0)
        for i, coef in enumerate(divisor):
            result[i] ^= _gf_mul(coef, factor)
    return result


def _num_raw_data_modules(ver):
    result = (16 * ver + 128) * ver + 64
    if ver >= 2:
        numalign = ver // 7 + 2
        result -= (25 * numalign - 10) * numalign - 55
        if ver >= 7:
            result -= 36
    return result


def _num_data_codewords(ver):
    return _num_raw_data_modules(ver) // 8 - _ECC_PER_BLOCK_M[ver] * _NUM_BLOCKS_M[ver]


def _alignment_positions(ver, size):
    if ver == 1:
        return []
    numalign = ver // 7 + 2
    step = (ver * 8 + numalign * 3 + 5) // (numalign * 4 - 4) * 2
    result = [(size - 7 - i * step) for i in range(numalign - 1)] + [6]
    return list(reversed(result))


def _get_bit(x, i):
    return ((x >> i) & 1) != 0


def generate_qr_matrix(text: str):
    data = text.encode("utf-8")

    # 1. Choose smallest version that fits
    version = None
    for ver in range(1, _MAX_VERSION + 1):
        count_bits = 8 if ver <= 9 else 16
        needed_bits = 4 + count_bits + len(data) * 8
        if needed_bits <= _num_data_codewords(ver) * 8:
            version = ver
            break
    if version is None:
        raise ValueError(f"Payload too large for QR generator ({len(data)} bytes)")

    size = version * 4 + 17
    capacity_bits = _num_data_codewords(version) * 8

    # 2. Build bitstream (byte mode)
    bits = []

    def append_bits(val, n):
        for i in reversed(range(n)):
            bits.append((val >> i) & 1)

    append_bits(0x4, 4)
    append_bits(len(data), 8 if version <= 9 else 16)
    for b in data:
        append_bits(b, 8)
    append_bits(0, min(4, capacity_bits - len(bits)))
    append_bits(0, -len(bits) % 8)
    pad = 0xEC
    while len(bits) < capacity_bits:
        append_bits(pad, 8)
        pad ^= 0xEC ^ 0x11

    data_codewords = [0] * (len(bits) // 8)
    for i, bit in enumerate(bits):
        data_codewords[i >> 3] |= bit << (7 - (i & 7))

    # 3. Split into blocks, add ECC, interleave
    numblocks = _NUM_BLOCKS_M[version]
    blockecclen = _ECC_PER_BLOCK_M[version]
    rawcodewords = _num_raw_data_modules(version) // 8
    numshortblocks = numblocks - rawcodewords % numblocks
    shortblocklen = rawcodewords // numblocks

    blocks = []
    divisor = _rs_divisor(blockecclen)
    k = 0
    for i in range(numblocks):
        datlen = shortblocklen - blockecclen + (0 if i < numshortblocks else 1)
        dat = data_codewords[k:k + datlen]
        k += datlen
        ecc = _rs_remainder(dat, divisor)
        if i < numshortblocks:
            dat = dat + [0]  # dummy padding to equalize lengths
        blocks.append(dat + ecc)

    final_codewords = []
    for i in range(len(blocks[0])):
        for j, blk in enumerate(blocks):
            if i != shortblocklen - blockecclen or j >= numshortblocks:
                final_codewords.append(blk[i])

    # 4. Matrix with function patterns. modules[y][x]
    modules = [[False] * size for _ in range(size)]
    isfunc = [[False] * size for _ in range(size)]

    def set_func(x, y, dark):
        modules[y][x] = dark
        isfunc[y][x] = True

    # Timing patterns
    for i in range(size):
        set_func(6, i, i % 2 == 0)
        set_func(i, 6, i % 2 == 0)

    # Finder patterns (with separators)
    for cx, cy in ((3, 3), (size - 4, 3), (3, size - 4)):
        for dy in range(-4, 5):
            for dx in range(-4, 5):
                xx, yy = cx + dx, cy + dy
                if 0 <= xx < size and 0 <= yy < size:
                    dist = max(abs(dx), abs(dy))
                    set_func(xx, yy, dist not in (2, 4))

    # Alignment patterns
    alignpos = _alignment_positions(version, size)
    numalign = len(alignpos)
    skips = ((0, 0), (0, numalign - 1), (numalign - 1, 0))
    for i in range(numalign):
        for j in range(numalign):
            if (i, j) in skips:
                continue
            for dy in range(-2, 3):
                for dx in range(-2, 3):
                    set_func(alignpos[i] + dx, alignpos[j] + dy, max(abs(dx), abs(dy)) != 1)

    def draw_format_bits(mask):
        dat = _ECL_M_FORMAT_BITS << 3 | mask
        rem = dat
        for _ in range(10):
            rem = (rem << 1) ^ ((rem >> 9) * 0x537)
        fbits = (dat << 10 | rem) ^ 0x5412
        for i in range(0, 6):
            set_func(8, i, _get_bit(fbits, i))
        set_func(8, 7, _get_bit(fbits, 6))
        set_func(8, 8, _get_bit(fbits, 7))
        set_func(7, 8, _get_bit(fbits, 8))
        for i in range(9, 15):
            set_func(14 - i, 8, _get_bit(fbits, i))
        for i in range(0, 8):
            set_func(size - 1 - i, 8, _get_bit(fbits, i))
        for i in range(8, 15):
            set_func(8, size - 15 + i, _get_bit(fbits, i))
        set_func(8, size - 8, True)  # Dark module

    draw_format_bits(0)  # reserve area

    # Version information (v7+)
    if version >= 7:
        rem = version
        for _ in range(12):
            rem = (rem << 1) ^ ((rem >> 11) * 0x1F25)
        vbits = version << 12 | rem
        for i in range(18):
            bit = _get_bit(vbits, i)
            a = size - 11 + i % 3
            b = i // 3
            set_func(a, b, bit)
            set_func(b, a, bit)

    # 5. Zigzag data placement
    i = 0
    total_bits = len(final_codewords) * 8
    right = size - 1
    while right >= 1:
        if right == 6:
            right = 5
        for vert in range(size):
            for j in range(2):
                x = right - j
                upward = ((right + 1) & 2) == 0
                y = (size - 1 - vert) if upward else vert
                if not isfunc[y][x] and i < total_bits:
                    modules[y][x] = _get_bit(final_codewords[i >> 3], 7 - (i & 7))
                    i += 1
        right -= 2

    # 6. Choose mask with lowest penalty
    mask_funcs = (
        lambda x, y: (x + y) % 2 == 0,
        lambda x, y: y % 2 == 0,
        lambda x, y: x % 3 == 0,
        lambda x, y: (x + y) % 3 == 0,
        lambda x, y: (x // 3 + y // 2) % 2 == 0,
        lambda x, y: x * y % 2 + x * y % 3 == 0,
        lambda x, y: (x * y % 2 + x * y % 3) % 2 == 0,
        lambda x, y: ((x + y) % 2 + x * y % 3) % 2 == 0,
    )

    def apply_mask(m):
        f = mask_funcs[m]
        for yy in range(size):
            for xx in range(size):
                if not isfunc[yy][xx] and f(xx, yy):
                    modules[yy][xx] = not modules[yy][xx]

    best_mask, best_penalty = 0, None
    for m in range(8):
        apply_mask(m)
        draw_format_bits(m)
        p = _penalty(modules, size)
        if best_penalty is None or p < best_penalty:
            best_mask, best_penalty = m, p
        apply_mask(m)  # undo (XOR)
    apply_mask(best_mask)
    draw_format_bits(best_mask)

    # Return as matrix[row][col]
    return modules


def _penalty(modules, size):
    result = 0
    # Rule 1: runs of 5+ same color (rows & columns)
    for lines in (modules, list(zip(*modules))):
        for line in lines:
            run_color = None
            run_len = 0
            for v in line:
                if v == run_color:
                    run_len += 1
                    if run_len == 5:
                        result += 3
                    elif run_len > 5:
                        result += 1
                else:
                    run_color = v
                    run_len = 1
    # Rule 2: 2x2 blocks
    for y in range(size - 1):
        for x in range(size - 1):
            c = modules[y][x]
            if c == modules[y][x + 1] == modules[y + 1][x] == modules[y + 1][x + 1]:
                result += 3
    # Rule 3: finder-like patterns
    pat1 = [True, False, True, True, True, False, True, False, False, False, False]
    pat2 = list(reversed(pat1))
    for lines in (modules, list(zip(*modules))):
        for line in lines:
            line = list(line)
            for x in range(size - 10):
                seg = line[x:x + 11]
                if seg == pat1 or seg == pat2:
                    result += 40
    # Rule 4: dark/light balance
    dark = sum(1 for row in modules for v in row if v)
    total = size * size
    k = (abs(dark * 20 - total * 10) + total - 1) // total - 1
    result += max(0, k) * 10
    return result


def save_qr_bmp(filepath: str, text: str, scale: int = 6):
    """
    Generates a QR Code and saves it as an uncompressed 24-bit BMP image.
    """
    import struct

    matrix = generate_qr_matrix(text)
    qr_size = len(matrix)
    margin = 4
    total_dim = (qr_size + margin * 2) * scale

    row_bytes = (total_dim * 3 + 3) & ~3
    img_size = row_bytes * total_dim
    file_size = 54 + img_size

    header = struct.pack('<2sIHHI', b'BM', file_size, 0, 0, 54)
    dib = struct.pack('<IIIHHIIIIII', 40, total_dim, total_dim, 1, 24, 0, img_size, 2835, 2835, 0, 0)

    data = bytearray([255] * file_size)
    data[0:14] = header
    data[14:54] = dib

    # BMP is stored bottom-to-top
    for r in range(qr_size):
        for c in range(qr_size):
            if matrix[r][c]:
                y_start = (qr_size - 1 - r + margin) * scale
                x_start = (c + margin) * scale
                for dy in range(scale):
                    row_off = 54 + (y_start + dy) * row_bytes
                    for dx in range(scale):
                        idx = row_off + (x_start + dx) * 3
                        data[idx] = 0
                        data[idx + 1] = 0
                        data[idx + 2] = 0

    with open(filepath, 'wb') as f:
        f.write(data)
    return filepath


def create_blender_qr_image(name: str, payload: str, scale: int = 8):
    """
    Creates a Blender bpy.data.images instance containing the QR Code.
    """
    import bpy

    matrix = generate_qr_matrix(payload)
    qr_size = len(matrix)
    margin = 4
    total_size = (qr_size + margin * 2) * scale

    if name in bpy.data.images:
        img = bpy.data.images[name]
        if img.size[0] != total_size or img.size[1] != total_size:
            img.scale(total_size, total_size)
    else:
        img = bpy.data.images.new(name, width=total_size, height=total_size, alpha=False)

    pixels = [1.0] * (total_size * total_size * 4)
    for r in range(qr_size):
        for c in range(qr_size):
            if matrix[r][c]:
                img_y_start = (qr_size - 1 - r + margin) * scale
                img_x_start = (c + margin) * scale
                for dy in range(scale):
                    for dx in range(scale):
                        idx = ((img_y_start + dy) * total_size + img_x_start + dx) * 4
                        pixels[idx] = 0.0
                        pixels[idx + 1] = 0.0
                        pixels[idx + 2] = 0.0
                        pixels[idx + 3] = 1.0

    img.pixels.foreach_set(pixels)
    img.pack()
    return img
