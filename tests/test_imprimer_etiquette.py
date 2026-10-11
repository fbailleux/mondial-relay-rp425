"""Tests hors-ligne du cœur pixel/ZPL d'imprimer_etiquette.py.

Aucun poppler/pdf/impression/macOS requis : les fonctions testées sont
pures (stdlib). Le point dur est l'aller-retour RLE : encoder(vers_zpl)
puis decoder() doit redonner exactement l'image d'origine.
"""
import json
import os
import random
import struct
import sys
import zlib

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import imprimer_etiquette as ie

W, H, RB = ie.W, ie.H, ie.RB


# ---------------------------------------------------------------- _nombre
def test_nombre_unite():
    # 1..19 -> 'G'..'Y' (71..89)
    for n in range(1, 20):
        assert ie._nombre(n) == chr(ord("G") + n - 1)


def test_nombre_vingtaines():
    assert ie._nombre(20) == "g"
    assert ie._nombre(40) == "h"
    assert ie._nombre(100) == "k"
    assert ie._nombre(380) == "y"


def test_nombre_combinaisons():
    assert ie._nombre(21) == "gG"
    assert ie._nombre(39) == "gY"
    assert ie._nombre(400) == "z"
    assert ie._nombre(800) == "zz"
    assert ie._nombre(419) == "zY"


# ---------------------------------------------------------------- RLE round trip
def _encoder_une_ligne(row):
    return ie._ligne_rle(row)


def _decoder_une_ligne(flux):
    return ie.decoder(flux)[0]


@pytest.mark.parametrize("row", [
    "0" * (2 * RB),                     # entièrement vide
    "F" * (2 * RB),                     # entièrement pleine
    "F" + "0" * (2 * RB - 1),           # un seul bit
    "0" * 100 + "F" * (2 * RB - 100),   # front net
    "F0" * RB,                          # damier
    "A" * (2 * RB),                     # valeurs intermédiaires
    "ABC123" + "0" * (2 * RB - 6),      # motif court + vide
    "0" * (2 * RB - 1) + "F",           # dernier bit plein
    "F" * (2 * RB - 1) + "0",           # dernier bit vide
    "5F" * RB,
])
def test_rle_ligne_roundtrip(row):
    flux = _encoder_une_ligne(row)
    out = _decoder_une_ligne(flux)
    assert len(out) == 2 * RB
    assert out == row


def _bitmap_aleatoire(seed):
    rng = random.Random(seed)
    b = bytearray(W * H)
    for i in range(len(b)):
        b[i] = 1 if rng.random() < 0.3 else 0
    return b


def _bitmap_bondes(seed):
    """Bitmaps à fines rainures verticales pour stresser le comptage de runs."""
    b = bytearray(W * H)
    for y in range(H):
        for x in range(W):
            b[y * W + x] = 1 if (x + y) % (1 + seed % 7) == 0 else 0
    return b


@pytest.mark.parametrize("seed", list(range(8)))
def test_vers_zpl_roundtrip_aleatoire(seed):
    for b in (_bitmap_aleatoire(seed), _bitmap_bondes(seed)):
        zpl, flux = ie.vers_zpl(b)
        assert ie.decoder(flux) == ie.lignes_hex(b)
        assert zpl.startswith("^XA\n")
        assert zpl.endswith("^XZ\n")


def test_vers_zpl_headers():
    b = _bitmap_aleatoire(1)
    zpl, _ = ie.vers_zpl(b)
    assert "^PW%d" % W in zpl
    assert "^LL%d" % H in zpl
    assert "^GFA,%d,%d,%d," % (RB * H, RB * H, RB) in zpl


def test_vers_zpl_white_roundtrip():
    b = bytearray(W * H)          # tout blanc
    zpl, flux = ie.vers_zpl(b)
    assert ie.decoder(flux) == ie.lignes_hex(b)


# ---------------------------------------------------------------- decoder étendu
def test_decoder_premiere_lignes_manquant():
    # decoder renvoie autant de lignes que le flux en contient réellement
    out = ie.decoder(":" * 5)
    assert len(out) == 5


def test_decoder_ligne_colonnes():
    # ":" répète la ligne précédente
    lignes = ie.lignes_hex(_bitmap_aleatoire(2))
    flux = lignes[0] + ":" + ":" + ie._ligne_rle(lignes[0])
    out = ie.decoder(flux)
    assert out[0] == lignes[0]
    assert out[1] == lignes[0]
    assert out[2] == lignes[0]
    assert out[3] == lignes[0]


# ---------------------------------------------------------------- lignes_hex
def test_lignes_hex_taille():
    b = _bitmap_aleatoire(3)
    lignes = ie.lignes_hex(b)
    assert len(lignes) == H
    assert all(len(l) == 2 * RB for l in lignes)


def test_lignes_hex_padding_bits():
    # W=812 -> 102 octets = 816 bits, les 4 derniers bits sont des 0
    b = bytearray(W * H)
    b[0] = 1                     # bit 0
    b[W - 1] = 1                 # bit 811
    lignes = ie.lignes_hex(b)
    assert lignes[0].startswith("80")      # 1000 0000
    # dernier octet : bit 811 (dans 0x10) + 4 bits de remplissage à 0 -> "10"
    assert lignes[0].endswith("10")


# ---------------------------------------------------------------- binariser / cadre
def test_binariser_seuil():
    gw, gh, seuil = W, H, 128
    g = bytearray([255] * (gw * gh))
    g[0] = 0                       # pixel sombre
    g[5] = 127                     # sous le seuil
    g[10] = 128                    # égal -> pas retenu (strictement inférieur)
    b = ie.binariser(g, gw, gh, seuil)
    assert b[0] == 1
    assert b[5] == 1
    assert b[10] == 0


def test_binariser_marge():
    # marge = 20 : le contenu est décalé de 20px depuis le coin
    gw, gh, marge = W, H, 20
    g = bytearray([255] * (gw * gh))
    g[0] = 0
    b = ie.binariser(g, gw, gh, 128, marge=marge)
    assert b[0] == 0                     # coin laissé vide
    assert b[marge * W + marge] == 1     # contenu décalé


def test_cadre_noir_bordure():
    b = bytearray(W * H)
    ie.cadre_noir(b, epaisseur=3)
    assert b[0] == 1                         # coin supérieur gauche
    assert b[2 * W + 2] == 1
    assert b[3 * W + 3] == 0                 # intérieur
    assert b[(H - 1) * W + (W - 1)] == 1     # coin inférieur droit
    assert sum(1 for i in range(W) if b[i]) == W  # toute la ligne haute


# ---------------------------------------------------------------- png_1bit
def test_png_1bit_structure():
    b = _bitmap_aleatoire(5)
    png = ie.png_1bit([b])
    assert png[:8] == b"\x89PNG\r\n\x1a\n"


def test_png_1bit_parse_chunks():
    b = _bitmap_aleatoire(6)
    png = ie.png_1bit([b, _bitmap_aleatoire(7)])
    # lire IHDR
    assert png[12:16] == b"IHDR"
    length = struct.unpack(">I", png[8:12])[0]
    assert length == 13
    w, h, depth, ctype, comp, filt, inter = struct.unpack(">IIBBBBB", png[16:29])
    assert w == W * 2 + 40     # deux images + séparateur 40px
    assert h == H
    assert depth == 1
    assert ctype == 0
    # IEND : longueur 0 + "IEND" + CRC -> "IEND" est à png[-8:-4]
    assert png[-8:-4] == b"IEND"
    assert struct.unpack(">I", png[-12:-8])[0] == 0


def test_png_1bit_decompresse_sans_erreur():
    b = _bitmap_aleatoire(8)
    png = ie.png_1bit([b])
    # trouver IDAT, décompresser
    off = png.find(b"IDAT")
    n = struct.unpack(">I", png[off - 4:off])[0]
    raw = zlib.decompress(png[off + 4:off + 4 + n])
    assert len(raw) == H * (1 + (W + 7) // 8)     # 1 filtre/ligne + données


# ---------------------------------------------------------------- pgm
def test_pgm_parse(tmp_path):
    w, h = 64, 48
    header = b"P5\n%d %d\n255\n" % (w, h)
    data = bytes((i * 7) % 256 for i in range(w * h))
    p = tmp_path / "x.pgm"
    p.write_bytes(header + data)
    pw, ph, img = ie.pgm(str(p))
    assert (pw, ph) == (w, h)
    assert img == data


# ---------------------------------------------------------------- valeur_arg
def test_valeur_arg_espace():
    assert ie.valeur_arg(["--sortie", "/tmp/out"], "--sortie", "d") == "/tmp/out"


def test_valeur_arg_egal():
    assert ie.valeur_arg(["--sortie=/tmp/out"], "--sortie", "d") == "/tmp/out"


def test_valeur_arg_defaut():
    assert ie.valeur_arg(["--sans-impression"], "--sortie", "d") == "d"


def test_valeur_arg_absorbe_pas_le_pdf():
    # la valeur ne doit pas dévorer un argument PDF indépendant
    assert ie.valeur_arg(["--sortie"], "--sortie", "d") == "d"


# ---------------------------------------------------------------- intégration flags (pipeline factice)
def _run_main_monkeypatched(monkeypatch, tmp_path, args):
    """Lance main() en remplaçant toute la chaîne PDF/pdftoppm par de l'inventé."""
    def fake_pgm(chemin):
        return (ie.W, ie.H, bytearray(ie.W * ie.H))

    def fake_cadre(pdf, tmp):
        return (0, 0, ie.W, 612.0)

    def fake_rendre(pdf, tmp, nom, dpi, x, y, lw, lh):
        return (ie.W, ie.H, bytearray([255] * ie.W * ie.H))

    monkeypatch.setattr(ie, "pgm", fake_pgm)
    monkeypatch.setattr(ie, "repérer_cadre", fake_cadre)
    monkeypatch.setattr(ie, "rendre", fake_rendre)
    monkeypatch.setattr(sys, "argv", ["imprimer_etiquette.py"] + args)
    return ie.main()


def test_main_valeur_arg_defaut(monkeypatch, tmp_path):
    rc = _run_main_monkeypatched(monkeypatch, tmp_path, ["f.pdf", "--sans-impression"])
    assert rc == 0


def test_main_sortie_flag(monkeypatch, tmp_path):
    out = tmp_path / "outsortie"
    _run_main_monkeypatched(monkeypatch, tmp_path, ["f.pdf", "--sans-impression", "--sortie", str(out)])
    assert (out / "etiquette-4x6.zpl").exists()
    assert (out / "fiche-4x6.zpl").exists()
    assert (out / "apercu.png").exists()


def test_main_json_emit(monkeypatch, tmp_path, capsys):
    out = tmp_path / "jsortie"
    rc = _run_main_monkeypatched(monkeypatch, tmp_path, ["f.pdf", "--sans-impression", "--sortie", str(out), "--json"])
    assert rc == 0
    captured = capsys.readouterr().out
    # la dernière ligne imprimée est le JSON
    ligne = [l for l in captured.splitlines() if l.strip().startswith("{")][-1]
    rapport = json.loads(ligne)
    assert rapport["pdf"] == "f.pdf"
    assert rapport["sortie"] == str(out)
    assert rapport["zpl_etiquette_octets"] > 0
    assert (out / "etiquette-4x6.zpl").exists()


# ---------------------------------------------------------------- trouver_pdf
def test_trouver_pdf_arg_direct():
    assert ie.trouver_pdf(["fic.pdf"]) == "fic.pdf"
    assert ie.trouver_pdf(["--sans-impression", "bon.pdf"]) == "bon.pdf"
    assert ie.trouver_pdf(["a.PDF"]) == "a.PDF"  # insensible à la casse


# ---------------------------------------------------------------- vérifie que _nombre est un vrai encodage réversible
def test_nombre_reversible_toutes_valeurs():
    for n in range(1, 600):
        s = ie._nombre(n)
        # décoder manuellement
        tot, i = 0, 0
        while i < len(s):
            c = s[i]
            if "g" <= c <= "z":
                tot += 20 * (ord(c) - ord("g") + 1)
                i += 1
            elif "G" <= c <= "Y":
                tot += ord(c) - ord("G") + 1
                i += 1
            elif c == "z":
                tot += 400
                i += 1
            else:
                i += 1
        assert tot == n, (n, s)