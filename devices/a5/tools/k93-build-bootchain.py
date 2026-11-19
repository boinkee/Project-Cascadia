#!/usr/bin/env python3
"""Build K93/12H321 RAM boot images. Offline only: no USB or storage writes."""
import hashlib
import importlib.util
import json
from pathlib import Path
import struct
import subprocess
import os
import sys

# Per board: the stock images' SHA-256 (decrypted), the auto-go hook's places in the
# iBEC, and the startup layout the trampoline's cave depends on.
#   k93  iPad2,1 (S5L8940X)   k93a  iPad2,4 (S5L8942X, 32 nm)
BOARDS = {
    'k93': dict(
        suffix='k93',
        pins={'iBSS': '5f28aa43dba148c1a8ee77fb0d3f065751e3c86139c5ce802b4cb5239389de28',
              'iBEC': '8c033bd9a90ab80329ae205152337052ca95d87266c2c75fce65fe980b440c4d'},
        hook=0x2366c, tramp=0x45c80, cache_flush=0x9ff20f84, done_flag=0x9ff4b2b0, usb_continue=0x9ff200e0,
        layout=(0x9ff46e80, 0x9ff45c74, 0x9ff46000, 0x9ff46e80, 0x9ff46e80, 0x9ff4cd38),
        tail='1a480121017005f10800bde8b040fcf731bd', literal=0x236d8),
    'k93a': dict(
        suffix='k93a',
        pins={'iBSS': '41b60dc51b804d670991c437c5e470e5bc0ee3e3cb2e9fe750e36edcc8e5e41a',
              'iBEC': 'dfc15078ad0d006f5656462da7d450cff256f37dc8389cc926eeb33f76163c7a'},
        hook=0x232b4, tramp=0x435c0, cache_flush=0x9ff20db4, done_flag=0x9ff48b50, usb_continue=0x9ff20014,
        layout=(0x9ff44800, 0x9ff435b0, 0x9ff44000, 0x9ff44800, 0x9ff44800, 0x9ff53568),
        tail='1a480121017005f10800bde8b040fcf7a7be', literal=0x23320),
}
BOARD = os.environ.get('BOARD', 'k93')
B = BOARDS[BOARD]
ROOT = Path(__file__).resolve().parents[1]
FW = ROOT / f'build/{BOARD}/firmware-12H321'
OUT = ROOT / f'build/{BOARD}/bootchain-v2'
PINS = B['pins']

def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for name, pin in PINS.items():
        src = FW / f"{name}.{B['suffix']}.RELEASE.dfu.dec"
        data = src.read_bytes()
        if hashlib.sha256(data).hexdigest() != pin:
            raise SystemExit(f'{name}: incorrect stock firmware')
        subprocess.run(['iBoot32Patcher', str(src), str(OUT / f'{name}.sigpatched')], check=True)
    spec = importlib.util.spec_from_file_location('autogo', ROOT / 'scripts/patch-ibec-autogo.py')
    patch = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(patch)
    patch.HOOK_OFF = B['hook']
    patch.TRAMPOLINE_OFF = B['tramp']
    patch.CACHE_FLUSH = B['cache_flush']
    patch.DONE_FLAG = B['done_flag']
    patch.USB_CONTINUE = B['usb_continue']
    data = bytearray((OUT / 'iBEC.sigpatched').read_bytes())
    stock = (FW / f"iBEC.{B['suffix']}.RELEASE.dfu.dec").read_bytes()
    # Startup's ARM code copies [base, image_end), then clears [bss_start,
    # bss_end). File-tail zeros are NOT a code cave: the first experiment put
    # the trampoline exactly at BSS start and startup erased it. Use only the
    # alignment padding after immutable text and before initialized data.
    image_end, text_end, data_start, data_end, bss_start, bss_end = struct.unpack_from('<6I', stock, 0x314)
    if (image_end, text_end, data_start, data_end, bss_start, bss_end) != B['layout']:
        raise SystemExit(f'Unexpected {BOARD} startup section layout')
    cave_start = patch.IBOOT_BASE + patch.TRAMPOLINE_OFF
    cave_end = cave_start + patch.TRAMPOLINE_MAX
    if not text_end <= cave_start < cave_end <= data_start <= bss_start:
        raise SystemExit('Trampoline is outside preserved text alignment padding')
    for off in range(0, len(stock)-3, 4):
        if cave_start <= struct.unpack_from('<I', stock, off)[0] < cave_end:
            raise SystemExit(f'Stock image references candidate cave at {off:#x}')
    # Verify the entire overwritten original ep4 tail, including its literal
    # and continuation, not just the four-byte hook.
    expected = bytes.fromhex(B['tail'])
    if stock[B['hook']:B['hook'] + len(expected)] != expected:
        raise SystemExit(f'{BOARD} ep4 tail differs from the audited firmware')
    if struct.unpack_from('<I', stock, B['literal'])[0] != patch.DONE_FLAG:
        raise SystemExit(f'{BOARD} done flag differs')
    if any(data[patch.TRAMPOLINE_OFF:patch.TRAMPOLINE_OFF+128]):
        raise SystemExit('Code cave is not zero-filled')
    info = patch.patch_autogo(data)
    # Model startup relocation followed by BSS clearing. The old 0x46e80
    # location fails this check; the new trampoline must survive byte-exact.
    runtime = bytearray(bss_end - patch.IBOOT_BASE)
    copied = image_end - patch.IBOOT_BASE
    runtime[:copied] = data[:copied]
    runtime[bss_start-patch.IBOOT_BASE:bss_end-patch.IBOOT_BASE] = bytes(bss_end-bss_start)
    begin, end = patch.TRAMPOLINE_OFF, patch.TRAMPOLINE_OFF + info['tramp_size']
    if runtime[begin:end] != data[begin:end]:
        raise SystemExit('Startup would erase or fail to copy trampoline')
    allowed = set(range(patch.HOOK_OFF, patch.HOOK_OFF+4)) | set(range(patch.TRAMPOLINE_OFF,patch.TRAMPOLINE_OFF+info['tramp_size']))
    original = (OUT / 'iBEC.sigpatched').read_bytes()
    if len(data) != len(original) or any(a != b and i not in allowed for i,(a,b) in enumerate(zip(data,original))):
        raise SystemExit('Patch changed unexpected bytes')
    (OUT / 'iBEC.autogo').write_bytes(data)
    sys.path.insert(0, str(ROOT / 'scripts'))
    from img3pack import pack_plain, parse_tags
    packed = pack_plain((FW / f"iBEC.{B['suffix']}.RELEASE.dfu").read_bytes(), bytes(data))
    if any(tag == b'GABK' for _,tag,_,_ in parse_tags(packed)):
        raise SystemExit('kDFU iBEC must not contain a KBAG')
    for off,tag,total,size in parse_tags(packed):
        if tag == b'ATAD' and packed[off+12:off+12+size] != data:
            raise SystemExit('Repacked plaintext differs')
    (OUT / 'iBEC.autogo.plain.dfu').write_bytes(packed)
    manifest = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in OUT.iterdir() if p.is_file() and p.name != 'manifest.json'}
    (OUT / 'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print(f'{BOARD} bootchain built and verified offline')

if __name__ == '__main__':
    main()
