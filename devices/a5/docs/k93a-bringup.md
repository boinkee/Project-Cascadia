# iPad 2 (2012), iPad2,4 / K93AAP -- bring-up

The 32 nm iPad 2 Wi-Fi (S5L8942, the iPad mini's chip), a revised board of the
iPad 2.  It is a third board of the tree, `BOARD=k93a`:

```bash
./cascadia k93a firmware     # generate the bootchain (important) and pull the firmware from ios (touch,wifi etc.) 
./cascadia k93a kernel 
./cascadia k93a rootfs 
./cascadia k93a build
./cascadia k93a flash --kdfu # from jailbreaked ios
```

download `iPad2,4_8.4.1_12H321_Restore.ipsw` from internet (e.g. ipsw.me) and put it in `devices/a5/` 

## what is working

- boot chain from this IPSW (`tools/k93-build-bootchain.py`, board `k93a`)
- the loader's status screen (1024x768, stride 4096)
- Linux 6.12 to a shell, USB gadget network, ssh
- both cores (`enable-method = "apple,pmgr-core"`, MPIDR `0x80000a00`/`a01`)

## Not working (yet)

Touch, Wi-Fi, Bluetooth, buttons(home and volume), audio, sensors, NAND.

## What differs from the iPad2,1

| | iPad2,1 (k93) | iPad2,4 (k93a) |
|---|---|---|
| SoC | S5L8940X (45 nm) | S5L8942X (32 nm) |
| CPU affinity | `0x900` | `0xa00` |
| iBEC auto-go hook | `0x2366c` | `0x232b4` (cave `0x435c0`) |
| digitizer firmware on iOS | `K93.mtprops` | `K93a.mtprops` |
| touch ATTN / reset GPIO | 21 / 141 | 131 / 22 |

Files left out for now: the GPU microkernel and the cameras' firmware (they come
out of the kernelcache and the root filesystem, whose iPad2,4 keys are not in the
tree).
