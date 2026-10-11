#!/opt/homebrew/bin/python3
"""Imprime le bon d'envoi Mondial Relay (PDF) sur la Rongta RP425 en 4x6 pouces.

Usage :
    imprimer_etiquette.py [fichier.pdf] [--sans-impression] [--sans-dialogue]
                          [--sortie DOSSIER] [--json]

Sans fichier : prend le PDF « bon d'envoi » le plus récent de ~/Downloads.
Étapes : repérer le cadre de l'étiquette, générer le ZPL compressé (RLE),
afficher l'aperçu, demander confirmation, imprimer.
"""
import glob
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import zlib

W, H, RB = 812, 1218, 102          # 4x6 pouces à 203 dpi, 102 octets par ligne
FILE_PAR_DEFAUT = "_RP425_ZPL_203DPI_"
DOSSIER = os.path.dirname(os.path.abspath(__file__))
SORTIE = os.path.join(DOSSIER, "dernier")


def outil(nom: str) -> str:
    """Renvoie le chemin d'un outil poppler, sinon quitte."""
    chemin = shutil.which(nom) or os.path.join("/opt/homebrew/bin", nom)
    if not os.path.exists(chemin):
        chemin = os.path.join("/usr/local/bin", nom)
    if not os.path.exists(chemin):
        raise SystemExit("Outil introuvable : %s (installer poppler : brew install poppler)" % nom)
    return chemin


def dialogue(texte: str, boutons: list, defaut: str, titre: str = "Étiquette RP425"):
    """Renvoie le bouton cliqué, ou None si annulé."""
    liste = ", ".join('"%s"' % b for b in boutons)
    script = 'display dialog "%s" with title "%s" buttons {%s} default button "%s" cancel button "%s"' % (
        texte.replace('"', "'"), titre, liste, defaut, boutons[0])
    r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    if r.returncode != 0:
        return None
    m = re.search(r"button returned:(.*?)(?:,|$)", r.stdout.strip())
    return m.group(1).strip() if m else None


def erreur(texte: str):
    sys.stderr.write(texte + "\n")
    if "--sans-dialogue" not in sys.argv:
        subprocess.run(["osascript", "-e",
                        'display dialog "%s" with title "Étiquette RP425" buttons {"OK"} default button "OK" with icon stop'
                        % texte.replace('"', "'")], capture_output=True)
    sys.exit(1)


def trouver_pdf(args: list) -> str:
    for a in args:
        if not a.startswith("--") and a.lower().endswith(".pdf"):
            return a
    candidats = glob.glob(os.path.expanduser("~/Downloads/*.pdf"))
    candidats = [c for c in candidats if re.search(r"envoi|mondial|colis", os.path.basename(c), re.I)]
    if not candidats:
        erreur("Aucun bon d'envoi trouvé dans Téléchargements. Glisse le PDF sur l'application.")
    return max(candidats, key=os.path.getmtime)


def valeur_arg(args: list, option: str, defaut):
    """Renvoie la valeur d'une option ``--option valeur`` (ou ``--option=valeur``)."""
    for i, a in enumerate(args):
        if a == option and i + 1 < len(args):
            return args[i + 1]
        if a.startswith(option + "="):
            return a.split("=", 1)[1]
    return defaut


def pgm(chemin: str):
    d = open(chemin, "rb").read()
    m = re.match(rb"P5\s+(\d+)\s+(\d+)\s+255\s", d)
    w, h = int(m.group(1)), int(m.group(2))
    return w, h, d[len(d) - w * h:]


def repérer_cadre(pdf: str, tmp: str):
    """Cadre de l'étiquette en pixels à 288 dpi : (x0, y0, largeur, page_w_pt)."""
    base = os.path.join(tmp, "page")
    subprocess.run([outil("pdftoppm"), "-r", "288", "-gray", "-singlefile", pdf, base], check=True)
    w, h, img = pgm(base + ".pgm")
    sombre = bytes(1 if i < 200 else 0 for i in range(256))
    zone = int(w * 0.6)
    lignes = []
    for y in range(h):
        s = img[y * w:y * w + zone].translate(sombre)
        longueur = max((len(m.group()) for m in re.finditer(rb"\x01+", s)), default=0)
        if longueur > 0.4 * w:
            lignes.append(y)
    colonnes = []
    for x in range(zone):
        s = img[x::w].translate(sombre)
        longueur = max((len(m.group()) for m in re.finditer(rb"\x01+", s)), default=0)
        if longueur > 0.3 * h:
            colonnes.append(x)
    if len(lignes) < 2 or len(colonnes) < 2:
        erreur("Cadre de l'étiquette introuvable : ce PDF n'a pas la mise en page Mondial Relay attendue.")
    x0, y0 = min(colonnes), min(lignes)
    largeur = max(colonnes) - x0 + 2
    hauteur = max(lignes) - y0 + 2
    if abs(hauteur / largeur - 1.5) > 0.03:
        erreur("Le cadre détecté n'est pas au format 4x6 (rapport %.2f au lieu de 1,50). Rien imprimé." % (hauteur / largeur))
    return x0, y0, largeur, w * 72 / 288


def rendre(pdf: str, tmp: str, nom: str, dpi: float, x: int, y: int, lw: int, lh: int):
    base = os.path.join(tmp, nom)
    subprocess.run([outil("pdftoppm"), "-r", repr(dpi), "-x", str(x), "-y", str(y), "-W", str(lw), "-H", str(lh),
                    "-gray", "-singlefile", pdf, base], check=True)
    w, h, img = pgm(base + ".pgm")
    return w, h, img


def binariser(g, gw: int, gh: int, seuil: int, marge: int = 0) -> bytearray:
    b = bytearray(W * H)
    for y in range(min(gh, H - marge)):
        lig = g[y * gw:(y + 1) * gw]
        base = (y + marge) * W + marge
        for x in range(min(gw, W - marge)):
            if lig[x] < seuil:
                b[base + x] = 1
    return b


def cadre_noir(b: bytearray, epaisseur: int = 3):
    for y in range(H):
        for x in range(W):
            if x < epaisseur or x >= W - epaisseur or y < epaisseur or y >= H - epaisseur:
                b[y * W + x] = 1


def lignes_hex(b: bytearray) -> list:
    out = []
    for y in range(H):
        r = bytearray()
        for xb in range(RB):
            v = 0
            for k in range(8):
                x = xb * 8 + k
                v = (v << 1) | (b[y * W + x] if x < W else 0)
            r.append(v)
        out.append(r.hex().upper())
    return out


def _nombre(n: int) -> str:
    """Compteur ZPL : 'z' = 400, 'g'..'z' = multiples de 20, 'G'..'Y' = 1..19."""
    s = ""
    while n >= 400:
        s += "z"
        n -= 400
    if n >= 20:
        s += chr(ord("g") + n // 20 - 1)
        n %= 20
    if n:
        s += chr(ord("G") + n - 1)
    return s


def _ligne_rle(row: str) -> str:
    if set(row) == {"0"}:
        return ","
    if set(row) == {"F"}:
        return "!"
    queue = ""
    t = row.rstrip("0")
    if len(row) - len(t) > 0 and t:
        row, queue = t, ","
    else:
        t2 = row.rstrip("F")
        if len(row) - len(t2) > 0 and t2:
            row, queue = t2, "!"
    out, i = "", 0
    while i < len(row):
        j = i
        while j < len(row) and row[j] == row[i]:
            j += 1
        n = j - i
        out += (_nombre(n) + row[i]) if n > 1 else row[i]
        i = j
    return out + queue


def decoder(flux: str) -> list:
    """Décodeur indépendant du RLE ZPL, pour vérifier ce qu'on envoie."""
    out, cur, prev, n, i = [], "", "", 0, 0
    while len(out) < H and i < len(flux):
        c = flux[i]
        i += 1
        if c == ":":
            out.append(prev)
            continue
        if c in ",!":
            cur += ("0" if c == "," else "F") * (2 * RB - len(cur))
            out.append(cur)
            prev, cur, n = cur, "", 0
            continue
        if c in "0123456789ABCDEF":
            cur += c * max(n, 1)
            n = 0
        elif "g" <= c <= "z":
            n += 20 * (ord(c) - ord("g") + 1)
        elif "G" <= c <= "Y":
            n += ord(c) - ord("G") + 1
        if len(cur) == 2 * RB:
            out.append(cur)
            prev, cur = cur, ""
    return out


def vers_zpl(b: bytearray):
    lignes = lignes_hex(b)
    flux, prec = "", None
    for r in lignes:
        flux += ":" if r == prec else _ligne_rle(r)
        prec = r
    if decoder(flux) != lignes:
        erreur("Vérification interne échouée : la compression ZPL ne redonne pas l'image. Rien imprimé.")
    total = RB * H
    return ("^XA\n^MMT\n^PW%d\n^LL%d\n^LS0\n^LH0,0\n^FO0,0^GFA,%d,%d,%d,%s^FS\n^PQ1,0,1,N\n^XZ\n"
            % (W, H, total, total, RB, flux)), flux


def png_1bit(images) -> bytes:
    """Aperçu : plusieurs images 812x1218 côte à côte, séparées de 40 points gris."""
    sep = 40
    largeur = len(images) * W + (len(images) - 1) * sep
    raw = bytearray()
    for y in range(H):
        raw.append(0)
        ligne = bytearray(largeur)
        for k, b in enumerate(images):
            o = k * (W + sep)
            for x in range(W):
                ligne[o + x] = 0 if b[y * W + x] else 1
            for x in range(W, W + sep if k < len(images) - 1 else W):
                if o + x < largeur:
                    ligne[o + x] = 0 if (x - W) % 2 == 0 and y % 2 == 0 else 1
        for xb in range((largeur + 7) // 8):
            v = 0
            for kk in range(8):
                x = xb * 8 + kk
                v = (v << 1) | (ligne[x] if x < largeur else 1)
            raw.append(v)

    def bloc(t, s):
        return struct.pack(">I", len(s)) + t + s + struct.pack(">I", zlib.crc32(t + s) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + bloc(b"IHDR", struct.pack(">IIBBBBB", largeur, H, 1, 0, 0, 0, 0))
            + bloc(b"IDAT", zlib.compress(bytes(raw), 9)) + bloc(b"IEND", b""))


def file_par_defaut() -> str:
    r = subprocess.run(["lpstat", "-d"], capture_output=True, text=True)
    m = re.search(r":\s*(\S+)\s*$", r.stdout.strip())
    return m.group(1) if m else FILE_PAR_DEFAUT


def main() -> int:
    args = sys.argv[1:]
    pdf = trouver_pdf(args)
    sortie = os.path.abspath(os.path.expanduser(valeur_arg(args, "--sortie", SORTIE)))
    os.makedirs(sortie, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        x0, y0, fw, page_pt = repérer_cadre(pdf, tmp)

        # Étiquette : le cadre est calé au ras du 4x6, sans déformation
        dpi = 288 * W / fw
        x = round(x0 * dpi / 288)
        y = round(y0 * dpi / 288)
        gw, gh, g = rendre(pdf, tmp, "etiquette", dpi, x, y, W, H)
        etiquette = binariser(g, gw, gh, 170)
        cadre_noir(etiquette)
        zpl_e, _ = vers_zpl(etiquette)

        # Fiche destinataire : colonne de droite, ajustée dans le 4x6 avec 20 points de marge
        pt = lambda px: px * 72 / 288
        fx_pt = pt(x0 + fw) + 22.75
        fy_pt = pt(y0) + 32.25
        dpi_f = 206.6
        fx = round(fx_pt * dpi_f / 72)
        fy = round(fy_pt * dpi_f / 72)
        fg, fgh, fgg = rendre(pdf, tmp, "fiche", dpi_f, fx, fy, 772, 1128)
        fiche = binariser(fgg, fg, fgh, 185, marge=20)
        zpl_f, _ = vers_zpl(fiche)

    fichiers = {
        "etiquette": os.path.join(sortie, "etiquette-4x6.zpl"),
        "fiche": os.path.join(sortie, "fiche-4x6.zpl"),
    }
    with open(fichiers["etiquette"], "w") as f:
        f.write(zpl_e)
    with open(fichiers["fiche"], "w") as f:
        f.write(zpl_f)
    apercu = os.path.join(sortie, "apercu.png")
    open(apercu, "wb").write(png_1bit([etiquette, fiche]))
    print("PDF :", pdf)
    print("ZPL :", fichiers["etiquette"], len(zpl_e), "octets;", fichiers["fiche"], len(zpl_f), "octets")
    print("Aperçu :", apercu)

    if "--json" in args:
        print(json.dumps({
            "pdf": pdf,
            "etiquette": fichiers["etiquette"],
            "zpl_etiquette_octets": len(zpl_e),
            "fiche": fichiers["fiche"],
            "zpl_fiche_octets": len(zpl_f),
            "apercu": apercu,
            "sortie": sortie,
        }, ensure_ascii=False))

    if "--sans-impression" in args:
        return 0
    if len(zpl_e) > 60000 or len(zpl_f) > 60000:
        erreur("Fichier ZPL trop gros (> 60 Ko) : l'imprimante le tronquerait. Rien imprimé.")

    choix = "Étiquette seule"
    if "--sans-dialogue" not in args:
        subprocess.run(["open", "-a", "Preview", apercu])
        choix = dialogue(
            "Aperçu ouvert (étiquette à gauche, fiche destinataire à droite). Que faut-il imprimer ?",
            ["Annuler", "Étiquette + fiche", "Étiquette seule"], "Étiquette seule")
        if choix is None or choix == "Annuler":
            print("Annulé, rien imprimé.")
            return 0
    file_ = file_par_defaut()
    envois = [fichiers["etiquette"]] + ([fichiers["fiche"]] if choix == "Étiquette + fiche" else [])
    for f in envois:
        r = subprocess.run(["lpr", "-P", file_, "-o", "raw", f], capture_output=True, text=True)
        if r.returncode != 0:
            erreur("L'envoi à l'imprimante a échoué : " + (r.stderr.strip() or "erreur lpr"))
    print("Envoyé à", file_, ":", len(envois), "travail(aux).")
    if "--sans-dialogue" not in args:
        subprocess.run(["osascript", "-e",
                        'display notification "%d étiquette(s) envoyée(s) à l\'imprimante" with title "Étiquette RP425"'
                        % len(envois)], capture_output=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())