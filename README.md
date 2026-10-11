# Étiquette Mondial Relay sur une Rongta RP425

Un script pour imprimer le bon d'envoi Mondial Relay sur une imprimante d'étiquettes Rongta RP425, depuis un Mac, au format 4×6 pouces. Tu vois l'aperçu avant que la moindre étiquette sorte.

Écrit en Python 3 pour le script, en AppleScript pour le lanceur et en shell pour la construction de l'application. Pas de Swift ici.

## Démonstration

Une vidéo de 36 secondes : [demo/demo-etiquette-rp425.mp4](demo/demo-etiquette-rp425.mp4). Les coordonnées du colis y sont masquées.

## Le problème

Le PDF de Mondial Relay est en A4. L'étiquette occupe le cadre de gauche, la fiche à glisser dans le colis occupe la droite. Si tu l'envoies tel quel à une imprimante d'étiquettes, tu obtiens une page A4 réduite, illisible. Ici, le script repère le cadre, le cale sur le 4×6 sans déformer, et envoie le résultat en ZPL.

## Ce que ça fait

1. Il prend le PDF que tu lui donnes, ou le bon d'envoi le plus récent de ton dossier Téléchargements.
2. Il repère le cadre de l'étiquette et le dessine à 203 dpi, pile à la taille du papier.
3. Il ouvre un aperçu : l'étiquette à gauche, la fiche destinataire à droite.
4. Il te demande : annuler, étiquette seule, ou étiquette et fiche. Rien ne part avant ton clic.
5. Il envoie le ZPL compressé à l'imprimante par défaut (`lpr -o raw`).

## Ce qu'il te faut

- macOS, avec Python 3 de Homebrew (`/opt/homebrew/bin/python3`)
- poppler : `brew install poppler`
- une Rongta RP425 branchée en USB, avec son pilote ZPL 203 dpi, définie comme imprimante par défaut
- du papier thermique direct en 4×6 pouces (101,6 × 152,4 mm), face thermique vers le haut

## Utilisation

```bash
git clone https://github.com/fbailleux/mondial-relay-rp425.git
cd mondial-relay-rp425
./construire_app.sh
```

Tu obtiens `Imprimer étiquette.app`. Double-clic, ou glisse le PDF dessus. Sans l'appli :

```bash
python3 imprimer_etiquette.py bon-d-envoi.pdf
python3 imprimer_etiquette.py bon-d-envoi.pdf --sans-impression   # génère seulement le ZPL et l'aperçu
python3 imprimer_etiquette.py bon-d-envoi.pdf --sortie /tmp/sortie # écrit dans un autre dossier
python3 imprimer_etiquette.py bon-d-envoi.pdf --json               # résumé JSON sur la sortie standard
```

Les fichiers générés vont dans `dernier/` (ignoré par git), ou dans le
dossier passé à `--sortie`.

### Options

| Option | Effet |
|---|---|
| `--sans-impression` | Génère le ZPL et l'aperçu, n'imprime rien. |
| `--sans-dialogue` | Supprime les fenêtres macOS (impression silencieuse). |
| `--sortie DOSSIER` | Écrit les fichiers dans DOSSIER au lieu de `dernier/`. |
| `--json` | Imprime un résumé JSON (chemins + tailles) sur la sortie standard. |

## Tests

La suite de tests couvre le cœur pixel/ZPL (binarisation, compteur RLE,
aller-retour `encoder`/`décodeur`, génération PNG 1 bit) entièrement hors
ligne — ni poppler, ni imprimante, ni macOS requis :

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install pytest ruff
pytest tests/ -v          # 40 tests, tous verts
ruff check imprimer_etiquette.py tests/
```

## Pour mettre ta propre icône

Dépose un fichier `icone.icns` dans le dossier avant de lancer `construire_app.sh`. Le logo Mondial Relay n'est pas dans le dépôt, c'est une marque.

## Les pièges rencontrés

- **L'imprimante tronque à environ 64 Ko.** Une image envoyée en hexadécimal brut pèse 248 Ko : l'étiquette sort coupée à 26 % de la hauteur, sans aucune erreur. Le script compresse en RLE ZPL (36 Ko) et refuse d'imprimer au-delà de 60 Ko.
- **Étiquette vide.** En thermique direct, seule une face réagit. Gratte l'étiquette avec l'ongle : la bonne face noircit.
- **Cadre au ras du bord.** Le script trace le cadre sur 3 points d'épaisseur pour qu'il ne disparaisse pas si le papier bouge d'un demi-millimètre.

## Garde-fous

Le script refuse d'imprimer si le cadre détecté n'est pas au rapport 2:3, si le ZPL dépasse 60 Ko, ou si la compression ne redonne pas exactement l'image d'origine (il décode son propre flux pour le vérifier).

## Limites

- Testé sur un seul modèle de bon d'envoi (livraison en Locker) et une seule imprimante, la RP425 en 203 dpi. Si Mondial Relay change sa mise en page, la détection du cadre peut échouer : le script s'arrête, il n'imprime pas de travers.
- Aucun bon d'envoi réel dans ce dépôt : il contient des noms et des adresses, il reste sur ta machine.
- Projet indépendant, sans lien avec Mondial Relay ni Rongta.

## Licence

MIT.
