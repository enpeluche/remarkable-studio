#!/usr/bin/env python3
"""Analyse (lecture seule) des métaobjets Qt 6 du programme xochitl : retrouver une classe, ses méthodes et
l'adresse réelle d'une méthode, sans symboles (le programme est dépouillé).

Usage : python outils/analyse_moc.py <xochitl> <Classe> [méthode]
  ex.   python outils/analyse_moc.py xochitl-3.30 SceneController addDrawingLine
        python outils/analyse_moc.py xochitl-3.30 Line

Principe (voir docs/EXTENSION-NATIVE.md) :
  1. table de chaînes moc de la classe : paires (décalage, longueur) puis les chaînes ; la 1re est le nom ;
  2. le métaobjet pointe vers cette table (champ stringdata, relocation R_ARM_RELATIVE) ;
  3. métaobjet = {superdata, stringdata, data, static_metacall, relatedMetaObjects, metaTypes, extradata} ;
  4. data : en-tête, puis 6 entiers par méthode (nom, nb d'arguments, paramètres, étiquette, drapeaux, types) ;
  5. qt_static_metacall aiguille l'appel n° i par une table de sauts (ldrh + add pc) : on la décode.
Programme ARM 32 bits (EABI5), PIE. Nécessite capstone (pip install capstone).
"""
import struct
import sys

import capstone


class Binaire:
    def __init__(self, path):
        self.d = open(path, "rb").read()
        if self.d[:4] != b"\x7fELF" or self.d[4] != 1:
            raise SystemExit("ELF 32 bits attendu")
        # segments chargés : (adresse, position, taille)
        phoff, phentsize, phnum = struct.unpack_from("<I", self.d, 0x1c)[0], *struct.unpack_from("<HH", self.d, 0x2a)
        self.segs = []
        for i in range(phnum):
            p_type, p_off, p_vaddr, _, p_filesz = struct.unpack_from("<IIIII", self.d, phoff + i * phentsize)
            if p_type == 1:
                self.segs.append((p_vaddr, p_off, p_filesz))
        # relocations dynamiques (REL) : emplacements relocalisés
        shoff = struct.unpack_from("<I", self.d, 0x20)[0]
        shnum = struct.unpack_from("<H", self.d, 0x30)[0]
        self.rel = set()
        for i in range(shnum):
            sh = struct.unpack_from("<IIIIIIIIII", self.d, shoff + i * 40)
            if sh[1] == 9:                                   # SHT_REL
                for k in range(sh[5] // 8):
                    off, _info = struct.unpack_from("<II", self.d, sh[4] + 8 * k)
                    self.rel.add(off)

    def v2o(self, v):
        for va, off, sz in self.segs:
            if va <= v < va + sz:
                return v - va + off
        return None

    def o2v(self, o):
        for va, off, sz in self.segs:
            if off <= o < off + sz:
                return o - off + va
        return None

    def u32(self, v):
        return struct.unpack_from("<I", self.d, self.v2o(v))[0]

    def cstr(self, v):
        o = self.v2o(v)
        return self.d[o:self.d.index(b"\0", o)].decode("latin1")

    def strdata(self, cls):
        key, k = cls.encode() + b"\0", 0
        while (k := self.d.find(key, k)) >= 0:
            for S in range(k - 4, max(0, k - 40000), -4):
                off, ln = struct.unpack_from("<II", self.d, S)
                if off == k - S and ln == len(cls):
                    strs = []
                    for i in range(off // 8):
                        o_, l_ = struct.unpack_from("<II", self.d, S + 8 * i)
                        strs.append(self.d[S + o_:S + o_ + l_].decode("latin1"))
                    v = self.o2v(S)
                    ptrs = [self.o2v(p) for p in self._find_word(v) if self.o2v(p) in self.rel]
                    if ptrs:
                        return v, strs, ptrs
                    break
            k += 1
        raise SystemExit(f"classe {cls} introuvable")

    def _find_word(self, v):
        p, k, out = struct.pack("<I", v), 0, []
        while (k := self.d.find(p, k)) >= 0:
            if k % 4 == 0:
                out.append(k)
            k += 1
        return out

    def metaobject(self, cls):
        S, strs, ptrs = self.strdata(cls)
        mo = ptrs[0] - 4
        f = dict(zip(["superdata", "stringdata", "data", "static_metacall", "related", "metaTypes", "extradata"],
                     [self.u32(mo + 4 * i) for i in range(7)]))
        dat = f["data"]
        hdr = [self.u32(dat + 4 * i) for i in range(14)]
        meths = []
        for i in range(hdr[4]):
            name, argc = self.u32(dat + 4 * (hdr[5] + 6 * i)), self.u32(dat + 4 * (hdr[5] + 6 * i + 1))
            meths.append((i, strs[name], argc))
        types = []
        mt = f["metaTypes"]
        for i in range(64):
            p = self.u32(mt + 4 * i) if self.v2o(mt + 4 * i) is not None else 0
            if p and self.v2o(p) is not None:
                _rev, align, size = struct.unpack_from("<HHI", self.d, self.v2o(p))
                namep = self.u32(p + 0x14)
                if namep and self.v2o(namep) is not None:
                    types.append((self.cstr(namep), size, align))
        return mo, f, meths, types

    def method_target(self, metacall, index):
        """Décode la table de sauts de qt_static_metacall (InvokeMetaMethod) -> adresse du code du cas `index`,
        puis la cible du premier « bl » de ce cas (la vraie méthode)."""
        md = capstone.Cs(capstone.CS_ARCH_ARM, capstone.CS_MODE_ARM)
        ins = list(md.disasm(self.d[self.v2o(metacall):self.v2o(metacall) + 400], metacall))
        regs = {}
        for k, x in enumerate(ins):
            if x.mnemonic == "ldr" and "[pc, #" in x.op_str:
                r = x.op_str.split(",")[0]
                imm = int(x.op_str.split("#")[1].rstrip("]"), 16)
                regs[r] = self.u32(x.address + 8 + imm)
            elif x.mnemonic == "add" and ", pc, " in x.op_str and x.op_str.count(",") == 2:
                rd, _, rm = [s.strip() for s in x.op_str.split(",")]
                if rm in regs:
                    regs[rd] = (regs[rm] + x.address + 8) & 0xffffffff
            elif x.mnemonic == "ldrh" and k + 1 < len(ins) and ins[k + 1].mnemonic == "add" and ins[k + 1].op_str.startswith("pc, pc"):
                base = regs.get(x.op_str.split("[")[1].split(",")[0].strip())
                if base is None:
                    break
                h = struct.unpack_from("<H", self.d, self.v2o(base + 2 * index))[0]
                case = ins[k + 1].address + 8 + 4 * h
                for y in md.disasm(self.d[self.v2o(case):self.v2o(case) + 40], case):
                    if y.mnemonic == "bl":
                        return case, int(y.op_str.lstrip("#"), 16)
                return case, None
        return None, None


def main():
    if len(sys.argv) < 3:
        raise SystemExit(__doc__)
    b = Binaire(sys.argv[1])
    mo, f, meths, types = b.metaobject(sys.argv[2])
    print(f"métaobjet de {sys.argv[2]} : {mo:#x}   qt_static_metacall : {f['static_metacall']:#x}")
    for name, size, align in types:
        if name == sys.argv[2]:
            print(f"taille du type {name} : {size} octets (alignement {align})")
    if len(sys.argv) > 3:
        for i, name, argc in meths:
            if name == sys.argv[3]:
                case, target = b.method_target(f["static_metacall"], i)
                print(f"méthode n° {i} {name} ({argc} argument(s)) : cas {case and hex(case)} -> fonction {target and hex(target)}")
    else:
        print("méthodes :", ", ".join(f"{i}:{n}" for i, n, _ in meths))


if __name__ == "__main__":
    main()
